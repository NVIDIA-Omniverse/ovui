# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ovstage dirty-ordinal polling bridged to common change events."""

from __future__ import annotations

import contextlib
import ctypes
import os
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable

from ovui_data_adapters.ovstage._handles import (
    native_prim_path,
    native_token,
    read_groups,
    release_read_group,
)
from ovui_data_adapters.common import ChangeEvent, ChangeEventType
from ovui_data_adapters.common._command import (
    history_consistent_interrupt,
    in_command_edge,
    interrupt_copy,
)
from ovui_data_adapters.common._subscription import SubscriptionProtocol
from ovui_data_adapters.ovstage._native import path_strings, resolve_query_names
from ovui_data_adapters.ovstage._scene import (
    _KitTopologySnapshot,
    _kit_topology_snapshot,
    _record_deleted_paths,
    classify_native_writes,
)
from ovui_data_adapters.ovstage._stage_write import (
    discard_recorded_stage_writes,
    recorded_stage_writes,
    wait_operation,
)

_EventKey = tuple[ChangeEventType, str | None, tuple[str, ...], tuple[str, ...]]
_POLL_INTERVAL_SECS = 1.0 / 30.0
_ADDED_SOURCE = "ovstage:added"
_REMOVED_SOURCE = "ovstage:removed"
_TOPOLOGY_SOURCE = "ovstage:topology"
_TRANSFORM_SOURCE = "ovstage:transform"
_VISIBILITY_SOURCE = "ovstage:visibility"
_ATTRIBUTE_SOURCE = "ovstage:attribute"
_USD_PATH_ATTRIBUTE = "usd-path"

_TRANSFORM_ATTRS = frozenset(
    {
        "localMatrix",
        "worldMatrix",
        "omni:fabric:localMatrix",
        "omni:fabric:worldMatrix",
        "omni:xform",
        "xformOpOrder",
        "xformOp:transform",
        "xformOp:translate",
        "xformOp:rotateXYZ",
        "xformOp:scale",
        "resetXformStack",
    }
)
_VISIBILITY_ATTRS = frozenset(
    {"visibility", "worldVisibility", "_worldVisibility"}
)
_TOPOLOGY_ATTRS = frozenset(
    {
        "usd-prim-type",
        "usd-schemas",
    }
)
_NATIVE_DIRTY_ATTRIBUTES = (
    _TOPOLOGY_ATTRS
    | _TRANSFORM_ATTRS
    | _VISIBILITY_ATTRS
    | frozenset({_USD_PATH_ATTRIBUTE})
)
_NATIVE_DIRTY_PENDING = object()


class _ChangeSubscription(SubscriptionProtocol):
    def __init__(self, cancel: Callable[[], None]) -> None:
        self._cancel = cancel
        self._active = True

    def cancel(self) -> None:
        if not self._active:
            return
        # Deactivate only AFTER the provider removal succeeded: a failed
        # revocation stays active, owned, and genuinely retryable.
        self._cancel()
        self._active = False


@dataclass
class _StageSubscriber:
    callback: Callable[[ChangeEvent], None]
    call_later: Callable[[float, Callable[[], None]], Any] | None


@dataclass
class _PropertySubscriber:
    paths: tuple[str, ...]
    callback: Callable[[], None]
    call_later: Callable[[float, Callable[[], None]], Any] | None


class OvstageChangeStream:
    """Shared polling stream for all adapters attached to one ovstage scene."""

    def __init__(
        self,
        scene: Any,
        *,
        poll_interval_secs: float = _POLL_INTERVAL_SECS,
    ) -> None:
        self._scene = scene
        self._last_ordinal = int(getattr(scene, "initial_ordinal", 0) or 0)
        self._poll_interval_secs = float(poll_interval_secs)
        self._stage_subscribers: list[_StageSubscriber] = []
        self._property_subscribers: list[_PropertySubscriber] = []
        self._poll_handle: Any = None
        self._poll_scheduled = False
        self._suppressed = 0
        self._suppressed_until_ordinal: int | None = None
        # Newest ordinal whose suppressed writes a poll dropped undelivered;
        # reset once a transform publication delivers it.
        self._discarded_through_ordinal = 0
        self._closed = False
        # PROVIDER-OWNED delivery receipts (round 11): every genuinely
        # ACCEPTED visibility publication (past the closed/suppressed and
        # user-path gates, with subscriber dispatch attempted) appends an
        # (ordinal, frozen path set) entry here. Debt-clearing proof reads
        # THIS stream instance's ledger — a caller cannot forge delivery
        # by returning a shape-matching object from a replaced publish
        # method, and a receipt on a different stream instance proves
        # nothing for this one.
        self._accepted_visibility_ordinal = 0
        self.accepted_visibility_publications: list = []
        # Stack of committed-edge publication captures (see
        # ``committed_edge_publication``): while non-empty, interrupt-class
        # subscriber failures are captured into the innermost scope instead
        # of re-raised mid-dispatch; the scope re-raises them at exit.
        self._committed_edge_captures: list[list] = []
        self._render_flow_mode = os.environ.get(
            "OMNIUI_RENDER_FLOW_MODE", "nativePacing"
        )
        self._native_dirty_collector: Any = None
        self._native_dirty_paths: Any = None
        self._native_dirty_pending = False
        stage = getattr(scene, "_stage", None)
        # Set while no readable topology has been observed yet.  Nothing may
        # be diffed against an unestablished baseline, and the recovery floor
        # must not be consumed while it is set.
        self._topology_baseline_pending = False
        try:
            self._topology_paths = (
                _native_topology_paths(
                    stage,
                    scene=scene,
                    render_flow_mode=self._render_flow_mode,
                )
                if _is_native_kit_stage(stage)
                else set()
            )
        except _TopologyUnreadable:
            self._topology_paths = set()
            self._topology_baseline_pending = True
        self._topology_prim_count = getattr(stage, "_ovui_kit_topology_prim_count", None)
        self._topology_query_revision = 0
        if stage is not None:
            discard_recorded_stage_writes(
                stage,
                through_ordinal=self._last_ordinal,
            )
        if _is_native_kit_stage(stage):
            (
                self._native_dirty_collector,
                self._native_dirty_paths,
            ) = _create_native_dirty_collector(
                stage,
                getattr(scene, "_native_dirty_worker", None),
            )

    def _profile_call(
        self,
        function_name: str,
        function: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        profile_fn = getattr(self._scene, "profile_ovui_call", None)
        if callable(profile_fn):
            return profile_fn(function_name, function, *args, **kwargs)
        return function(*args, **kwargs)

    @property
    def last_ordinal(self) -> int:
        return self._last_ordinal

    @property
    def has_pending_suppressed_range(self) -> bool:
        return self._suppressed > 0 or self._suppressed_until_ordinal is not None

    @property
    def discarded_through_ordinal(self) -> int:
        """Newest ordinal a poll skipped past without delivering its writes."""
        return self._discarded_through_ordinal

    @property
    def accepted_visibility_ordinal(self) -> int:
        """Monotonic count of genuinely ACCEPTED visibility publications."""
        return self._accepted_visibility_ordinal

    @property
    def has_scheduled_subscribers(self) -> bool:
        return self._first_call_later() is not None

    def dirty_transform_paths(
        self,
        *,
        since_ordinal: int,
        current_ordinal: int | None = None,
    ) -> tuple[str, ...]:
        """Return transform-dirty prim paths without advancing subscribers."""
        return self._dirty_paths_for_attribute_set(
            _TRANSFORM_ATTRS,
            since_ordinal=since_ordinal,
            current_ordinal=current_ordinal,
        )

    def dirty_visibility_paths(
        self,
        *,
        since_ordinal: int,
        current_ordinal: int | None = None,
    ) -> tuple[str, ...]:
        """Return visibility-dirty prim paths without advancing subscribers."""
        return self._dirty_paths_for_attribute_set(
            _VISIBILITY_ATTRS,
            since_ordinal=since_ordinal,
            current_ordinal=current_ordinal,
        )

    def close(self) -> None:
        self._closed = True
        self._stage_subscribers.clear()
        self._property_subscribers.clear()
        self._cancel_poll()
        self._close_native_dirty_collector()

    def subscribe_stage(
        self,
        callback: Callable[[ChangeEvent], None],
        *,
        call_later: Callable[[float, Callable[[], None]], Any] | None = None,
    ) -> SubscriptionProtocol:
        subscriber = _StageSubscriber(callback=callback, call_later=call_later)
        self._stage_subscribers.append(subscriber)
        self._ensure_polling(call_later)
        return _ChangeSubscription(lambda: self._remove_stage_subscriber(subscriber))

    def subscribe_property(
        self,
        paths: tuple[str, ...],
        callback: Callable[[], None],
        *,
        call_later: Callable[[float, Callable[[], None]], Any] | None = None,
    ) -> SubscriptionProtocol:
        subscriber = _PropertySubscriber(
            paths=tuple(dict.fromkeys(str(path) for path in paths if str(path))),
            callback=callback,
            call_later=call_later,
        )
        self._property_subscribers.append(subscriber)
        self._ensure_polling(call_later)
        return _ChangeSubscription(lambda: self._remove_property_subscriber(subscriber))

    @contextlib.contextmanager
    def suppress_notifications(self):
        """Drop automatic poll delivery while a caller batches manual edits."""
        self._suppressed += 1
        try:
            yield
        finally:
            self._suppressed = max(0, self._suppressed - 1)
            if self._suppressed == 0:
                self._mark_suppressed_through_current()

    def poll(
        self,
        *,
        source: str | None = None,
        deliver_suppressed: bool = False,
    ) -> tuple[ChangeEvent, ...]:
        """Poll ovstage once and synchronously deliver any classified events."""
        return self._poll_impl(
            source=source,
            deliver_suppressed=deliver_suppressed,
            allow_native_async=False,
        )

    def _poll_impl(
        self,
        *,
        source: str | None,
        deliver_suppressed: bool,
        allow_native_async: bool,
    ) -> tuple[ChangeEvent, ...]:
        if self._closed:
            return ()
        scene = self._scene
        stage = getattr(scene, "_stage", None)
        current_ordinal = getattr(scene, "current_ordinal", None)
        if stage is None or current_ordinal is None:
            return ()
        current = int(current_ordinal)
        if _is_native_kit_stage(stage):
            # While the stage still keeps them, find out whether the new
            # ordinals of other writers (such as solver results) wrote only
            # values, so that the hierarchy caches do not count them as
            # structure changes. Also during suppressed edits.
            self._profile_call(
                "OvstageChangeStream.classify_native_writes",
                classify_native_writes,
                stage,
            )
        native_dirty_result: Any = None
        if self._native_dirty_pending:
            native_dirty_result = self._profile_call(
                "OvstageChangeStream.native_dirty.update",
                self._poll_native_dirty,
                stage,
                current,
                self._last_ordinal,
                blocking=not allow_native_async,
            )
            if native_dirty_result is _NATIVE_DIRTY_PENDING:
                return ()
            current = int(native_dirty_result[1])
        # A pending baseline still owes this ordinal a read, so the usual
        # "already delivered" shortcut would strand the stream on it.
        stale = current <= self._last_ordinal and not self._topology_baseline_pending
        if stale:
            return ()
        if self._suppressed:
            return ()
        if not deliver_suppressed:
            self._discard_suppressed_range(current)
            if current <= self._last_ordinal and not self._topology_baseline_pending:
                return ()
        else:
            self._clear_delivered_suppression(current)

        since = self._last_ordinal
        physics_paths: tuple[str, ...] = ()
        if native_dirty_result is None:
            physics_paths = self._physics_transform_paths_for_range(
                since_ordinal=since,
                current_ordinal=current,
            )
        if physics_paths and native_dirty_result is None:
            events = (
                _info_event(
                    set(physics_paths),
                    _classified_source(_TRANSFORM_SOURCE, source),
                ),
            )
        else:
            try:
                if (
                    native_dirty_result is None
                    and _is_native_kit_stage(stage)
                    and self._native_dirty_collector is not None
                ):
                    native_dirty_result = self._profile_call(
                        "OvstageChangeStream.native_dirty.update",
                        self._poll_native_dirty,
                        stage,
                        current,
                        since,
                        blocking=not allow_native_async,
                    )
                    if native_dirty_result is _NATIVE_DIRTY_PENDING:
                        return ()
                    since = int(native_dirty_result[0])
                    current = int(native_dirty_result[1])
                events = tuple(
                    self._profile_call(
                        "OvstageChangeStream.poll.collect_events",
                        self._collect_events,
                        stage,
                        current,
                        since,
                        source=source,
                        native_dirty_result=native_dirty_result,
                    )
                )
            except _TopologyUnreadable:
                # Nothing about this ordinal is known yet.  Leave the
                # watermark, the topology set and the delivered model exactly
                # as they were so the next poll re-reads this same ordinal.
                return ()
        self._advance_last_ordinal(current)
        for event in events:
            self._notify_all(event)
        return events

    def publish_transform_change(
        self,
        paths: tuple[str, ...] | list[str],
        *,
        source: str | None = None,
    ) -> ChangeEvent | None:
        """Publish an explicit transform edit after a suppressed write batch.

        Adapter-authored transform edits already know their affected paths.  A
        native OVStage dirty read normally rediscovers them, but this explicit
        fallback preserves the common adapter notification contract when the
        runtime has already consumed or coalesced that dirty range.
        """
        if self._closed or self._suppressed:
            return None
        changed = {
            str(path)
            for path in paths
            if _is_user_change_path(str(path), scene=self._scene)
        }
        stage = getattr(self._scene, "_stage", None)
        if stage is not None:
            changed = _expand_transform_paths(stage, changed, scene=self._scene)
        if not changed:
            return None
        current_ordinal = getattr(self._scene, "current_ordinal", None)
        if current_ordinal is not None:
            self._advance_last_ordinal(int(current_ordinal))
            if self._discarded_through_ordinal <= int(current_ordinal):
                # This publication delivers the dropped transform state.
                self._discarded_through_ordinal = 0
        self._suppressed_until_ordinal = None
        event = _info_event(
            changed,
            _classified_source(_TRANSFORM_SOURCE, source),
        )
        self._notify_all(event)
        return event

    def publish_visibility_change(
        self,
        paths: tuple[str, ...] | list[str],
        *,
        source: str | None = None,
    ) -> ChangeEvent | None:
        """Publish an adapter-authored OVStage visibility edit fallback."""
        if self._closed or self._suppressed:
            return None
        changed = {
            str(path)
            for path in paths
            if _is_user_change_path(str(path), scene=self._scene)
        }
        if not changed:
            return None
        current_ordinal = getattr(self._scene, "current_ordinal", None)
        if current_ordinal is not None:
            self._advance_last_ordinal(int(current_ordinal))
        self._suppressed_until_ordinal = None
        # Canonical visibility classification travels SEPARATELY from the
        # provenance source: a Property Inspector write keeps its
        # ``property:set`` provenance while consumers (the Stage Browser
        # hierarchy model) still route the event down the visibility-only
        # invalidation path. The delta is truthful by construction — this
        # stream publishes visibility only for committed native visibility
        # frames, the paths ARE the authored prim roots, and there are no
        # replay resyncs on the native path.
        event = _info_event(
            changed,
            _classified_source(_VISIBILITY_SOURCE, source),
            visibility_delta={
                "proven": True,
                "precise": True,
                "authored": tuple(sorted(changed)),
                "operation_resyncs": (),
                "boundaries": {},
            },
        )
        self._notify_all(event)
        # Accepted: dispatch was attempted across both channels. Under the
        # native post-commit policy an observer Exception is recorded on
        # ``delivery_failures`` without rejecting the publication, so the
        # receipt stays truthful; only an interrupt-class failure that
        # re-raises mid-dispatch (no committed-edge scope deferring it)
        # leaves the publication unreceipted.
        self._accepted_visibility_ordinal += 1
        self.accepted_visibility_publications.append(
            (self._accepted_visibility_ordinal, frozenset(changed))
        )
        del self.accepted_visibility_publications[:-64]
        return event

    def publish_attribute_change(
        self,
        paths: tuple[str, ...] | list[str],
        *,
        source: str | None = None,
    ) -> ChangeEvent | None:
        """Publish a source-USD property edit when native dirties coalesce.

        ``population.apply_usd_changes`` may consume the Fabric dirty range
        before the polling bridge can classify it.  The authoring adapter
        already knows the affected prim paths, so this is the deterministic
        fallback used after a successful USD-to-OVStage synchronization.
        """

        return self._publish_explicit_info_change(
            paths,
            category_source=_ATTRIBUTE_SOURCE,
            source=source,
        )

    def publish_resync_change(
        self,
        paths: tuple[str, ...] | list[str],
        *,
        source: str | None = None,
    ) -> ChangeEvent | None:
        """Publish a source-USD topology/namespace edit fallback."""

        if self._closed or self._suppressed:
            return None
        changed = {
            str(path)
            for path in paths
            if _is_user_change_path(str(path), scene=self._scene)
        }
        if not changed:
            return None
        current_ordinal = getattr(self._scene, "current_ordinal", None)
        if current_ordinal is not None:
            stage = getattr(self._scene, "_stage", None)
            if _is_native_kit_stage(stage):
                try:
                    self._topology_paths = _native_topology_paths(
                        stage,
                        scene=self._scene,
                        render_flow_mode=self._render_flow_mode,
                    )
                except _TopologyUnreadable:
                    # This publication could not be reconciled, so the set no
                    # longer describes the stage.  Keep it for now, but
                    # re-baseline on the next readable poll: diffing against
                    # it would replay these paths as native additions on top
                    # of the delivery this call already made.
                    self._topology_baseline_pending = True
            self._advance_last_ordinal(int(current_ordinal))
        self._suppressed_until_ordinal = None
        event = ChangeEvent(
            changed_paths=(),
            resynced_paths=tuple(sorted(changed)),
            event_type=ChangeEventType.RESYNC,
            source=_classified_source(_TOPOLOGY_SOURCE, source),
        )
        self._notify_all(event)
        return event

    def _publish_explicit_info_change(
        self,
        paths: tuple[str, ...] | list[str],
        *,
        category_source: str,
        source: str | None,
    ) -> ChangeEvent | None:
        if self._closed or self._suppressed:
            return None
        changed = {
            str(path)
            for path in paths
            if _is_user_change_path(str(path), scene=self._scene)
        }
        if not changed:
            return None
        current_ordinal = getattr(self._scene, "current_ordinal", None)
        if current_ordinal is not None:
            self._advance_last_ordinal(int(current_ordinal))
        self._suppressed_until_ordinal = None
        event = _info_event(
            changed,
            _classified_source(category_source, source),
        )
        self._notify_all(event)
        return event

    def _mark_suppressed_through_current(self) -> None:
        current_ordinal = getattr(self._scene, "current_ordinal", None)
        if current_ordinal is None:
            return
        current = int(current_ordinal)
        if current <= self._last_ordinal:
            return
        suppressed_until = self._suppressed_until_ordinal
        self._suppressed_until_ordinal = (
            current
            if suppressed_until is None
            else max(suppressed_until, current)
        )

    def _advance_last_ordinal(self, ordinal: int) -> None:
        self._last_ordinal = max(self._last_ordinal, int(ordinal))
        stage = getattr(self._scene, "_stage", None)
        if stage is not None:
            discard_recorded_stage_writes(
                stage,
                through_ordinal=self._last_ordinal,
            )

    def _discard_suppressed_range(self, current: int) -> None:
        suppressed_until = self._suppressed_until_ordinal
        if suppressed_until is None:
            return
        drop_until = min(current, suppressed_until)
        if drop_until > self._last_ordinal:
            self._discarded_through_ordinal = drop_until
            self._advance_last_ordinal(drop_until)
        if self._last_ordinal >= suppressed_until:
            self._suppressed_until_ordinal = None

    def _clear_delivered_suppression(self, current: int) -> None:
        suppressed_until = self._suppressed_until_ordinal
        if suppressed_until is not None and current >= suppressed_until:
            self._suppressed_until_ordinal = None

    def _ensure_polling(
        self,
        call_later: Callable[[float, Callable[[], None]], Any] | None,
    ) -> None:
        if call_later is None or self._poll_scheduled or self._closed:
            return
        self._poll_scheduled = True
        self._poll_handle = call_later(self._poll_interval_secs, self._scheduled_poll)

    def _scheduled_poll(self) -> None:
        self._scheduled_poll_impl()

    def _scheduled_poll_impl(self) -> None:
        self._poll_scheduled = False
        self._poll_handle = None
        if self._closed or not self._has_subscribers():
            return
        try:
            self._poll_impl(
                source=None,
                deliver_suppressed=False,
                allow_native_async=True,
            )
        finally:
            call_later = self._first_call_later()
            if call_later is not None:
                self._ensure_polling(call_later)

    def _cancel_poll(self) -> None:
        handle = self._poll_handle
        self._poll_handle = None
        self._poll_scheduled = False
        if handle is not None and hasattr(handle, "cancel"):
            try:
                handle.cancel()
            except Exception:
                pass

    def _has_subscribers(self) -> bool:
        return bool(self._stage_subscribers or self._property_subscribers)

    def _first_call_later(self) -> Callable[[float, Callable[[], None]], Any] | None:
        for subscriber in self._stage_subscribers:
            if subscriber.call_later is not None:
                return subscriber.call_later
        for subscriber in self._property_subscribers:
            if subscriber.call_later is not None:
                return subscriber.call_later
        return None

    def _remove_stage_subscriber(self, subscriber: _StageSubscriber) -> None:
        if subscriber in self._stage_subscribers:
            self._stage_subscribers.remove(subscriber)
        if not self._has_subscribers():
            self._cancel_poll()

    def _remove_property_subscriber(self, subscriber: _PropertySubscriber) -> None:
        if subscriber in self._property_subscribers:
            self._property_subscribers.remove(subscriber)
        if not self._has_subscribers():
            self._cancel_poll()

    def _collect_events(
        self,
        stage: Any,
        current: int,
        since: int,
        *,
        source: str | None,
        native_dirty_result: tuple[int, int, dict[str, set[str]], bool] | None = None,
    ) -> list[ChangeEvent]:
        if _is_native_kit_stage(stage):
            return self._collect_native_events(
                stage,
                current,
                since,
                source=source,
                native_dirty_result=native_dirty_result,
            )
        query = stage.query_prims(current, since_ordinal=since)
        events: list[ChangeEvent] = []
        seen_events: set[_EventKey] = set()

        for group in query.get("groups", ()):
            paths = _paths_for_group(stage, group)
            added_paths = set(_paths_from_indices(paths, group.get("added_indices", ())))
            removed_paths = set(_paths_from_indices(paths, group.get("removed_indices", ())))
            structural_paths = added_paths | removed_paths
            self._append_resync_event(events, seen_events, added_paths, _ADDED_SOURCE)
            self._append_resync_event(events, seen_events, removed_paths, _REMOVED_SOURCE)

            dirty_count = int(group.get("dirty_count") or 0)
            if dirty_count <= 0:
                continue
            available_attrs = set(
                resolve_query_names(stage, group.get("attributes", ()))
            )
            topology_attrs = tuple(
                attr for attr in _TOPOLOGY_ATTRS if attr in available_attrs
            )
            topology_paths = (
                self._dirty_paths_for_attrs(
                    stage,
                    current,
                    since,
                    paths,
                    group,
                    topology_attrs,
                )
                if topology_attrs
                else set()
            )
            topology_paths.difference_update(structural_paths)
            self._append_resync_event(events, seen_events, topology_paths, _TOPOLOGY_SOURCE)

            transform_paths = self._dirty_paths_for_attrs(
                stage,
                current,
                since,
                paths,
                group,
                _TRANSFORM_ATTRS,
            )
            transform_paths.difference_update(structural_paths)
            self._append_info_event(
                events,
                seen_events,
                transform_paths,
                _TRANSFORM_SOURCE,
                source,
            )
            visibility_paths = self._dirty_paths_for_attrs(
                stage,
                current,
                since,
                paths,
                group,
                _VISIBILITY_ATTRS,
            )
            visibility_paths.difference_update(structural_paths)
            self._append_info_event(
                events,
                seen_events,
                visibility_paths,
                _VISIBILITY_SOURCE,
                None,
            )
            other_attrs = tuple(
                attr
                for attr in available_attrs
                if attr
                and attr not in _TOPOLOGY_ATTRS
                and attr not in _TRANSFORM_ATTRS
                and attr not in _VISIBILITY_ATTRS
            )
            attribute_paths = self._dirty_paths_for_attrs(
                stage,
                current,
                since,
                paths,
                group,
                other_attrs,
            )
            attribute_paths.difference_update(structural_paths)
            self._append_info_event(
                events,
                seen_events,
                attribute_paths,
                _ATTRIBUTE_SOURCE,
                None,
            )
        return events

    def _collect_native_events(
        self,
        stage: Any,
        current: int,
        since: int,
        *,
        source: str | None,
        native_dirty_result: tuple[int, int, dict[str, set[str]], bool] | None = None,
    ) -> list[ChangeEvent]:
        events: list[ChangeEvent] = []
        seen_events: set[_EventKey] = set()
        if native_dirty_result is None:
            dirty_by_attr, dirty_read_complete = self._profile_call(
                "OvstageChangeStream.native_dirty.update",
                _native_dirty_paths_by_attribute,
                stage,
                since,
                current,
                scene=self._scene,
                profile_call=self._profile_call,
            )
        else:
            dirty_by_attr = native_dirty_result[2]
            dirty_read_complete = native_dirty_result[3]
        structural_paths: set[str] = set()
        read_topology = True
        if self._render_flow_mode == "nativePacing":
            count_sample = getattr(stage, "_ovui_kit_dirty_topology", None)
            prim_count = (
                count_sample[1]
                if count_sample is not None and count_sample[0] == current
                else None
            )
            topology_revision = (
                count_sample[2]
                if (
                    count_sample is not None
                    and count_sample[0] == current
                    and len(count_sample) > 2
                )
                else None
            )
            # Native insert/delete may not dirty usd-path. Use the existing
            # query's membership revision/count and structural dirty signals.
            membership_changed = (
                prim_count is not None and prim_count != self._topology_prim_count
            )
            if topology_revision is not None:
                membership_changed = (
                    membership_changed
                    or topology_revision != self._topology_query_revision
                )
            structural_dirty = any(dirty_by_attr.get(attr) for attr in _TOPOLOGY_ATTRS)
            new_paths = any(
                path not in self._topology_paths
                for paths in dirty_by_attr.values()
                for path in paths
            )
            topology_dirty_paths = set(
                dirty_by_attr.get(_USD_PATH_ATTRIBUTE, ())
            )
            topology_dirty_read_complete = dirty_read_complete
            if (
                not self._topology_baseline_pending
                and not topology_dirty_read_complete
            ):
                (
                    topology_dirty_paths,
                    topology_dirty_read_complete,
                ) = self._profile_call(
                    "OvstageChangeStream.native_dirty.topology",
                    _native_dirty_topology_paths,
                    stage,
                    since,
                    current,
                    scene=self._scene,
                )
            read_topology = (
                self._topology_baseline_pending
                or not topology_dirty_read_complete
                or bool(topology_dirty_paths)
                or membership_changed
                or structural_dirty
                or new_paths
                # Older bindings cannot prove an empty read is value-only.
                or (prim_count is None and not dirty_by_attr)
            )

        if read_topology:
            current_paths = _native_topology_paths(
                stage,
                scene=self._scene,
                render_flow_mode=self._render_flow_mode,
            )
            if (
                self._render_flow_mode == "nativePacing"
                and self._topology_baseline_pending
            ):
                self._topology_baseline_pending = False
                self._topology_paths = set(current_paths)
                stage._ovui_kit_child_paths_cache = None
                self._scene._topology_revision += 1
                self._append_resync_event(
                    events,
                    seen_events,
                    _rootmost_paths(current_paths),
                    _TOPOLOGY_SOURCE,
                )
            previous_paths = set(self._topology_paths)
            added_delta = current_paths - previous_paths
            removed_delta = previous_paths - current_paths
            added_paths = _leafmost_paths(added_delta)
            removed_paths = _leafmost_paths(removed_delta)
            structural_paths = added_paths | removed_paths
            if added_delta or removed_delta:
                _record_deleted_paths(stage, removed_delta)
                stage._ovui_kit_child_paths_cache = None
                self._scene._topology_revision += 1
            self._topology_paths = current_paths
            self._append_resync_event(events, seen_events, added_paths, _ADDED_SOURCE)
            self._append_resync_event(events, seen_events, removed_paths, _REMOVED_SOURCE)
            if self._render_flow_mode == "nativePacing":
                self._topology_prim_count = prim_count
                if topology_revision is not None:
                    self._topology_query_revision = topology_revision
        else:
            # Attribute-only native-pacing commits preserve path membership.
            # Keep the established snapshot valid at the new ordinal without
            # enumerating every prim in the stage.
            cached_topology = getattr(stage, "_ovui_kit_topology_snapshot", None)
            if cached_topology is not None and bool(
                getattr(cached_topology, "readable", False)
            ):
                cached_topology.ordinal = int(current)

        def paths_for(attributes: frozenset[str]) -> set[str]:
            result: set[str] = set()
            for attr_name in attributes:
                result.update(dirty_by_attr.get(attr_name, ()))
            result.difference_update(structural_paths)
            return result

        topology_paths = paths_for(_TOPOLOGY_ATTRS)
        if topology_paths:
            self._scene._topology_revision += 1
        self._append_resync_event(
            events, seen_events, topology_paths, _TOPOLOGY_SOURCE
        )
        self._append_info_event(
            events,
            seen_events,
            _expand_transform_paths(
                stage,
                paths_for(_TRANSFORM_ATTRS),
                scene=self._scene,
            ),
            _TRANSFORM_SOURCE,
            source,
        )
        self._append_info_event(
            events,
            seen_events,
            paths_for(_VISIBILITY_ATTRS),
            _VISIBILITY_SOURCE,
            None,
        )
        classified = _TOPOLOGY_ATTRS | _TRANSFORM_ATTRS | _VISIBILITY_ATTRS
        attribute_paths: set[str] = set()
        for attr_name, paths in dirty_by_attr.items():
            if (
                attr_name in classified
                or attr_name == _USD_PATH_ATTRIBUTE
                or attr_name.startswith("_")
            ):
                continue
            attribute_paths.update(paths)
        attribute_paths.difference_update(structural_paths)
        self._append_info_event(
            events,
            seen_events,
            attribute_paths,
            _ATTRIBUTE_SOURCE,
            None,
        )
        return events

    def _poll_native_dirty(
        self,
        stage: Any,
        current: int,
        since: int,
        *,
        blocking: bool,
    ) -> tuple[int, int, dict[str, set[str]], bool] | object:
        collector = self._native_dirty_collector
        paths = self._native_dirty_paths
        if collector is None or paths is None:
            return since, current, {}, False
        try:
            if not self._native_dirty_pending:
                if not collector.begin(since, current):
                    raise RuntimeError("native dirty collector rejected a valid range")
                self._native_dirty_pending = True
            else:
                collector.update_current_ordinal(current)
            result = collector.poll(blocking=blocking)
            if result is None:
                return _NATIVE_DIRTY_PENDING
            self._native_dirty_pending = False
            captured_since = int(result[0])
            captured_current = int(result[1])
            if captured_current <= self._last_ordinal:
                return _NATIVE_DIRTY_PENDING
            if len(result) > 3:
                stage._ovui_kit_dirty_topology = (captured_current, *result[3:])
            dirty = _recorded_dirty_paths_for_range(
                stage,
                captured_since,
                captured_current,
                scene=self._scene,
                profile_call=self._profile_call,
            )
            _merge_native_dirty_handles(
                dirty,
                result[2],
                paths,
                scene=self._scene,
            )
            return (
                captured_since,
                captured_current,
                _normalize_native_dirty_paths(dirty),
                True,
            )
        except Exception:
            self._native_dirty_pending = False
            if not blocking:
                return _NATIVE_DIRTY_PENDING
            self._close_native_dirty_collector()
            dirty, complete = _native_dirty_paths_by_attribute(
                stage,
                since,
                current,
                scene=self._scene,
                profile_call=self._profile_call,
            )
            return since, current, dirty, complete

    def _close_native_dirty_collector(self) -> None:
        collector = self._native_dirty_collector
        paths = self._native_dirty_paths
        self._native_dirty_collector = None
        self._native_dirty_paths = None
        self._native_dirty_pending = False
        if collector is not None:
            try:
                collector.close()
            except Exception:
                pass
        if paths is not None:
            try:
                paths.destroy()
            except Exception:
                pass

    def _physics_transform_paths_for_range(
        self,
        *,
        since_ordinal: int,
        current_ordinal: int,
    ) -> tuple[str, ...]:
        controls = getattr(self._scene, "physics_controls", None)
        get_paths = getattr(controls, "simulated_transform_paths_for_range", None)
        if not callable(get_paths):
            return ()
        try:
            return tuple(
                str(path)
                for path in get_paths(
                    since_ordinal=since_ordinal,
                    current_ordinal=current_ordinal,
                )
                if str(path)
            )
        except Exception:
            return ()

    def _append_resync_event(
        self,
        events: list[ChangeEvent],
        seen_events: set[_EventKey],
        paths: set[str],
        source: str,
    ) -> None:
        if not paths:
            return
        event = ChangeEvent(
            changed_paths=(),
            resynced_paths=tuple(sorted(paths)),
            event_type=ChangeEventType.RESYNC,
            source=source,
        )
        _append_unique_event(events, seen_events, event)

    def _append_info_event(
        self,
        events: list[ChangeEvent],
        seen_events: set[_EventKey],
        paths: set[str],
        category_source: str,
        provenance_source: str | None,
    ) -> None:
        if not paths:
            return
        event = _info_event(
            paths,
            _classified_source(category_source, provenance_source),
        )
        _append_unique_event(events, seen_events, event)

    def _dirty_paths_for_attrs(
        self,
        stage: Any,
        current: int,
        since: int,
        fallback_paths: tuple[str, ...],
        original_group: dict[str, Any],
        attrs: tuple[str, ...] | frozenset[str],
    ) -> set[str]:
        dirty_paths: set[str] = set()
        original_handle = int(original_group.get("prim_list_handle") or 0)
        available_attrs = set(
            resolve_query_names(stage, original_group.get("attributes", ()))
        )
        requested_attrs = tuple(attr for attr in attrs if attr in available_attrs)
        if not requested_attrs:
            return dirty_paths

        def collect(attr_query: dict[str, Any]) -> None:
            for attr_group in attr_query.get("groups", ()):
                if int(attr_group.get("prim_list_handle") or 0) != original_handle:
                    continue
                paths = _paths_for_group(stage, attr_group) or fallback_paths
                dirty_paths.update(
                    _paths_from_indices(paths, attr_group.get("dirty_indices", ()))
                )

        try:
            collect(
                stage.query_prims(
                    current,
                    since_ordinal=since,
                    attribute_filter=list(requested_attrs),
                )
            )
            return dirty_paths
        except Exception:
            pass

        for attr_name in requested_attrs:
            try:
                collect(
                    stage.query_prims(
                        current,
                        since_ordinal=since,
                        attribute_filter=[attr_name],
                    )
                )
            except Exception:
                continue
        return dirty_paths

    def _dirty_paths_for_attribute_set(
        self,
        attrs: tuple[str, ...] | frozenset[str],
        *,
        since_ordinal: int,
        current_ordinal: int | None,
    ) -> tuple[str, ...]:
        scene = self._scene
        stage = getattr(scene, "_stage", None)
        if stage is None:
            return ()
        current = (
            int(current_ordinal)
            if current_ordinal is not None
            else int(getattr(scene, "current_ordinal", 0) or 0)
        )
        since = int(since_ordinal)
        if current <= since:
            return ()

        if _is_native_kit_stage(stage):
            dirty_by_attr, _dirty_read_complete = _native_dirty_paths_by_attribute(
                stage,
                since,
                current,
                scene=self._scene,
                profile_call=self._profile_call,
            )
            paths: set[str] = set()
            for attr_name in attrs:
                paths.update(dirty_by_attr.get(attr_name, ()))
            if set(attrs) & _TRANSFORM_ATTRS:
                paths = _expand_transform_paths(stage, paths, scene=self._scene)
            return tuple(sorted(paths))

        query = stage.query_prims(current, since_ordinal=since)
        dirty_paths: set[str] = set()
        for group in query.get("groups", ()):
            paths = _paths_for_group(stage, group)
            added_paths = set(_paths_from_indices(paths, group.get("added_indices", ())))
            removed_paths = set(_paths_from_indices(paths, group.get("removed_indices", ())))
            structural_paths = added_paths | removed_paths
            dirty_count = int(group.get("dirty_count") or 0)
            if dirty_count <= 0:
                continue
            group_dirty = self._dirty_paths_for_attrs(
                stage,
                current,
                since,
                paths,
                group,
                attrs,
            )
            group_dirty.difference_update(structural_paths)
            dirty_paths.update(group_dirty)
        return tuple(sorted(dirty_paths))

    @contextlib.contextmanager
    def committed_edge_publication(self) -> Any:
        """Defer interrupt-class subscriber failures past a committed edge.

        Publications inside this scope run after a native state commit
        and BEFORE the command service records or moves the history edge
        (``UndoManager`` push, undo, redo, and grouped finalization all
        record an entry only when the command edge returns). An
        interrupt escaping a subscriber mid-dispatch would therefore
        leave committed native state with no corresponding history entry.

        Within the scope every subscriber is still attempted exactly
        once, every failure is recorded on the ``delivery_failures``
        ledger, and receipts stay truthful. Interrupt-class failures are
        NOT hidden: the first one re-raises at scope exit, marked
        ``_ovui_history_consistent = True`` so the command service (see
        ``services.undo``) records the pending entry first and then lets
        the interrupt reach the caller. Outside the scope the default
        policy holds: the first non-Exception BaseException re-raises
        after all subscribers were attempted.
        """
        capture: list = []
        self._committed_edge_captures.append(capture)
        try:
            yield
        finally:
            self._committed_edge_captures.pop()
        if capture:
            original = capture[0]
            # The delivered interrupt is a fresh same-type instance, never
            # the subscriber's own (possibly shared and later-reused)
            # exception object. It carries the history-consistent mark
            # ONLY while a command-service edge is executing — that is the
            # only situation with a pending history entry to protect. A
            # public direct adapter write (caller-managed undo) therefore
            # delivers a clean interrupt with no internal per-edge state.
            if in_command_edge():
                interrupt = history_consistent_interrupt(original)
            else:
                interrupt = interrupt_copy(original)
            add_note = getattr(interrupt, "add_note", None)
            if callable(add_note):
                for extra in capture[1:]:
                    add_note(f"{type(extra).__name__}: {extra}")
            raise interrupt from original

    def _notify_all(self, event: ChangeEvent) -> None:
        """ONE frozen publication across BOTH channels, then one report.

        Every applicable stage subscriber AND every applicable property
        subscriber is attempted exactly once before any failure is
        aggregated or rethrown — a stage-channel KeyboardInterrupt can no
        longer starve the property channel (or vice versa). Failure
        semantics match the per-channel envelopes: native state and undo
        history are already committed before subscribers run, so
        Exception-class observer failures are recorded on the stream's
        ``delivery_failures`` ledger without rejecting the publication;
        only the first non-Exception BaseException re-raises, with the
        rest attached as notes — and inside a
        ``committed_edge_publication`` scope even those are contained so
        the pending history edge is recorded.
        """
        failures: list = []
        failures.extend(self._deliver_stage(event))
        failures.extend(self._deliver_properties(event))
        _raise_delivery_failures(failures, capture=self._committed_edge_capture())

    def _committed_edge_capture(self) -> list | None:
        if self._committed_edge_captures:
            return self._committed_edge_captures[-1]
        return None

    def _notify_stage(self, event: ChangeEvent) -> None:
        # Failure-isolated provider delivery: the event is frozen (the
        # subscriber tuple snapshot), every still-valid subscriber is
        # attempted exactly once even when an earlier one raises ANY
        # BaseException (a KeyboardInterrupt in the hierarchy callback must
        # not starve the renderer/PI/footer equivalents behind it). Observer
        # Exceptions are recorded post-commit instead of failing the
        # publication; only interrupts re-raise afterwards.
        _raise_delivery_failures(
            self._deliver_stage(event),
            capture=self._committed_edge_capture(),
        )

    def _deliver_stage(self, event: ChangeEvent) -> list:
        failures: list = []
        for subscriber in tuple(self._stage_subscribers):
            try:
                _deliver(
                    subscriber.call_later,
                    lambda s=subscriber, e=event: _guarded_call(
                        self,
                        lambda: s.callback(e),
                        scheduled=s.call_later is not None,
                    ),
                )
            except BaseException as exc:  # noqa: BLE001 — isolation
                failures.append(exc)
        return failures

    def _notify_properties(self, event: ChangeEvent) -> None:
        _raise_delivery_failures(
            self._deliver_properties(event),
            capture=self._committed_edge_capture(),
        )

    def _deliver_properties(self, event: ChangeEvent) -> list:
        event_paths = set(event.changed_paths) | set(event.resynced_paths)
        if not event_paths:
            return []
        failures: list = []
        for subscriber in tuple(self._property_subscribers):
            if not subscriber.paths or _paths_overlap(subscriber.paths, event_paths):
                try:
                    _deliver(
                        subscriber.call_later,
                        lambda s=subscriber: _guarded_call(
                            self,
                            s.callback,
                            scheduled=s.call_later is not None,
                        ),
                    )
                except BaseException as exc:  # noqa: BLE001 — isolation
                    failures.append(exc)
        return failures


def _is_native_kit_stage(stage: Any) -> bool:
    return (
        stage is not None
        and callable(getattr(stage, "read_attributes", None))
        and callable(getattr(stage, "fetch_read_next", None))
        and callable(getattr(stage, "get_attribute_write_floor", None))
    )


def _create_native_dirty_collector(stage: Any, worker: Any) -> tuple[Any, Any]:
    """Create the optional native dirty pipeline over the stage's borrowed ABI."""
    paths = None
    collector = None
    try:
        from omni.ui import _ui as native_ui

        collector_type = getattr(native_ui, "_NativeOvstageDirtyCollector", None)
        stage_instance = getattr(stage, "__dict__", {}).get("_inst")
        if collector_type is None or stage_instance is None or worker is None:
            return None, None
        stage_address = int(
            ctypes.cast(stage_instance, ctypes.c_void_p).value or 0
        )
        if not stage_address:
            return None, None
        ovstage = import_module("ovstage")
        paths = ovstage.PathDictionary(stage)
        required_attributes = tuple(
            paths.intern_token(name) for name in _NATIVE_DIRTY_ATTRIBUTES
        )
        collector = collector_type(worker, stage_address, required_attributes)
        if not bool(collector.supported):
            collector.close()
            paths.destroy()
            return None, None
        return collector, paths
    except Exception:
        if collector is not None:
            try:
                collector.close()
            except Exception:
                pass
        if paths is not None:
            try:
                paths.destroy()
            except Exception:
                pass
        return None, None


class _TopologyUnreadable(RuntimeError):
    """No OVStage surface could report the whole-stage topology this poll."""


def _run_profiled(
    profile_call: Callable[..., Any] | None,
    function_name: str,
    function: Callable[..., Any],
    /,
    *args: Any,
    **kwargs: Any,
) -> Any:
    if profile_call is None:
        return function(*args, **kwargs)
    return profile_call(function_name, function, *args, **kwargs)


def _native_topology_paths(
    stage: Any,
    *,
    scene: Any | None = None,
    render_flow_mode: str = "nativePacing",
) -> set[str]:
    if not _is_native_kit_stage(stage):
        return set()
    if callable(getattr(stage, "query", None)) and callable(
        getattr(stage, "fetch_query_result", None)
    ):
        try:
            return _query_native_kit_topology_paths(stage, scene=scene)
        except Exception:
            if render_flow_mode == "fast":
                return set()
    if render_flow_mode == "fast":
        try:
            result = stage.query_prims(
                int(getattr(stage, "current_ordinal", 0) or 0)
            )
            topology_paths: set[str] = set()
            for group in result.get("groups", ()):
                handle = int(group.get("prim_list_handle") or 0)
                if not handle:
                    continue
                topology_paths.update(
                    str(path)
                    for path in stage.get_prim_paths(handle)
                    if _is_user_change_path(str(path), scene=scene)
                )
            return topology_paths
        except Exception:
            return set()
    # The poll owns the retry: it is the one caller that must re-read an
    # ordinal whose earlier probe found no answer, so a source coming back is
    # noticed without waiting for the next edit.  Everything else reuses that
    # probe's result instead of repeating the read.
    stage._ovui_kit_topology_unreadable = None
    snapshot = _kit_topology_snapshot(
        stage,
        int(getattr(stage, "current_ordinal", 0) or 0),
    )
    if not snapshot.readable:
        raise _TopologyUnreadable
    return {
        str(path)
        for path in snapshot.path_order
        if _is_user_change_path(str(path), scene=scene)
    }


def _query_native_kit_topology_paths(
    stage: Any,
    *,
    scene: Any | None,
) -> set[str]:
    """Copy the native OVStage topology without building the compatibility cache."""

    ovstage = import_module("ovstage")
    with ovstage.PathDictionary(stage) as paths:
        with stage.query(None, None) as query:
            wait_operation(query)
            result = query.result()
            handle = int(result.all_handle)
            if not handle:
                stage._ovui_kit_topology_prim_count = getattr(result, "total_prim_count", None)
                stage._ovui_kit_topology_snapshot = _KitTopologySnapshot(
                    int(getattr(stage, "current_ordinal", 0) or 0),
                    (),
                )
                return set()

            topology_paths: set[str] = set()
            path_order: list[str] = []
            for raw_path in path_strings(paths, handle):
                path = str(raw_path)
                if not _is_user_change_path(path, scene=scene):
                    continue
                parts = [part for part in path.split("/") if part]
                candidate = ""
                for part in parts:
                    candidate = f"{candidate}/{part}" if candidate else f"/{part}"
                    if (
                        _is_user_change_path(candidate, scene=scene)
                        and candidate not in topology_paths
                    ):
                        topology_paths.add(candidate)
                        path_order.append(candidate)
            stage._ovui_kit_topology_snapshot = _KitTopologySnapshot(
                int(getattr(stage, "current_ordinal", 0) or 0),
                tuple(path_order),
            )
            stage._ovui_kit_topology_unreadable = None
            stage._ovui_kit_topology_prim_count = getattr(result, "total_prim_count", None)
            return topology_paths


def _filter_recorded_dirty_paths(
    recorded_writes: dict[str, set[str]],
    *,
    scene: Any | None,
) -> dict[str, set[str]]:
    dirty = {
        str(attribute_name): {
            str(path)
            for path in attribute_paths
            if _is_user_change_path(str(path), scene=scene)
        }
        for attribute_name, attribute_paths in recorded_writes.items()
    }
    return {
        attribute_name: attribute_paths
        for attribute_name, attribute_paths in dirty.items()
        if attribute_paths
    }


def _recorded_dirty_paths_for_range(
    stage: Any,
    since: int,
    current: int,
    *,
    scene: Any | None,
    profile_call: Callable[..., Any] | None,
) -> dict[str, set[str]]:
    recorded_writes = _run_profiled(
        profile_call,
        "OvstageChangeStream.native_dirty.recorded_stage_writes",
        recorded_stage_writes,
        stage,
        since_ordinal=since,
        current_ordinal=current,
    )
    return _run_profiled(
        profile_call,
        "OvstageChangeStream.native_dirty.filter_recorded_writes",
        _filter_recorded_dirty_paths,
        recorded_writes,
        scene=scene,
    )


def _merge_native_dirty_handles(
    dirty: dict[str, set[str]],
    raw_groups: Any,
    paths: Any,
    *,
    scene: Any | None,
) -> None:
    for attribute_token, prim_paths in raw_groups:
        attribute_name = paths.token_to_string(native_token(paths, attribute_token))
        attribute_paths = dirty.setdefault(attribute_name, set())
        for prim_path in prim_paths:
            path = paths.path_to_string(native_prim_path(paths, prim_path))
            if _is_user_change_path(path, scene=scene):
                attribute_paths.add(path)


def _prepare_native_dirty_attribute_tokens(result: Any, paths: Any) -> list[int]:
    attributes = [native_token(paths, token) for token in getattr(result, "attributes", ())]
    # A column created after the query population snapshot is writable and
    # render-visible, but is not necessarily returned by unscoped attribute
    # discovery immediately. Explicitly include the adapter's semantic columns.
    attributes.extend(paths.intern_token(name) for name in _NATIVE_DIRTY_ATTRIBUTES)
    return list(dict.fromkeys(attributes))


def _normalize_native_dirty_paths(
    dirty: dict[str, set[str]],
) -> dict[str, set[str]]:
    return {
        attribute_name: attribute_paths
        for attribute_name, attribute_paths in dirty.items()
        if attribute_paths
    }


def _native_dirty_paths_by_attribute(
    stage: Any,
    since: int,
    current: int,
    *,
    scene: Any | None = None,
    profile_call: Callable[..., Any] | None = None,
) -> tuple[dict[str, set[str]], bool]:
    """Return dirty user paths and whether the native dirty read completed."""

    if current <= since or not _is_native_kit_stage(stage):
        return {}, True
    query = None
    read = None
    paths = None
    # Journal rows supplement native dirty reads for newly-upserted columns,
    # but renderer-owned writes use the same copy-in path.  Apply the exact
    # user-path policy used below for native read groups before journal
    # evidence can participate in a user-facing ChangeEvent.
    dirty = _recorded_dirty_paths_for_range(
        stage,
        since,
        current,
        scene=scene,
        profile_call=profile_call,
    )
    try:
        ovstage = import_module("ovstage")
        paths = _run_profiled(
            profile_call,
            "OvstageChangeStream.native_dirty.create_path_dictionary",
            ovstage.PathDictionary,
            stage,
        )
        query = _run_profiled(
            profile_call,
            "OvstageChangeStream.native_dirty.stage_query",
            stage.query,
            filter=None,
        )
        _run_profiled(
            profile_call,
            "OvstageChangeStream.native_dirty.wait_query",
            wait_operation,
            query,
        )
        result = _run_profiled(
            profile_call,
            "OvstageChangeStream.native_dirty.query_result",
            query.result,
        )
        stage._ovui_kit_dirty_topology = (
            current,
            getattr(result, "total_prim_count", None),
        )
        attributes = _run_profiled(
            profile_call,
            "OvstageChangeStream.native_dirty.prepare_attributes",
            _prepare_native_dirty_attribute_tokens,
            result,
            paths,
        )
        if not attributes:
            return dirty, True
        read = _run_profiled(
            profile_call,
            "OvstageChangeStream.native_dirty.read_attributes",
            stage.read_attributes,
            query,
            attributes,
            ovstage.OrdinalRange.between(int(since) + 1, int(current)),
        )
        _run_profiled(
            profile_call,
            "OvstageChangeStream.native_dirty.wait_read",
            wait_operation,
            read,
        )

        def fetch_groups() -> None:
            for group in read_groups(iter(lambda: read.fetch_next(), None)):
                try:
                    attr_name = paths.token_to_string(native_token(paths, group.attribute))
                    group_paths = tuple(
                        str(path) for path in path_strings(paths, group.prim_list)
                    )
                    attr_paths = dirty.setdefault(attr_name, set())
                    for local in range(int(group.prim_count)):
                        try:
                            path = group_paths[int(group.prim_index(local))]
                            if _is_user_change_path(path, scene=scene):
                                attr_paths.add(path)
                        except Exception:
                            continue
                finally:
                    try:
                        release_read_group(stage, group)
                    except Exception:
                        pass

        _run_profiled(
            profile_call,
            "OvstageChangeStream.native_dirty.fetch_groups",
            fetch_groups,
        )
        dirty = _run_profiled(
            profile_call,
            "OvstageChangeStream.native_dirty.normalize_results",
            _normalize_native_dirty_paths,
            dirty,
        )
        # After the dirty read: ovstage may release all_handle with the result.
        # The Python-only fallback uses the same already-completed query.
        # Compare interned handles, not whole-scene attribute/path strings.
        get_paths = getattr(paths, "get_paths", None)
        handle = getattr(result, "all_handle", 0)
        if callable(get_paths) and handle:
            membership = tuple(sorted(get_paths(handle)))
            previous = getattr(stage, "_ovui_kit_dirty_membership", None)
            revision = int(getattr(stage, "_ovui_kit_dirty_membership_revision", 0))
            if membership != previous:
                revision += 1
                stage._ovui_kit_dirty_membership = membership
                stage._ovui_kit_dirty_membership_revision = revision
            stage._ovui_kit_dirty_topology += (revision,)
        return dirty, True
    except Exception:
        return dirty, False
    finally:
        if read is not None:
            try:
                def release_read() -> None:
                    release = getattr(read, "release", None)
                    wait_operation(
                        release() if callable(release) else stage.release_read(read)
                    )

                _run_profiled(
                    profile_call,
                    "OvstageChangeStream.native_dirty.release_read",
                    release_read,
                )
            except Exception:
                pass
        _run_profiled(
            profile_call,
            "OvstageChangeStream.native_dirty.release_query",
            _release_native_query,
            query,
        )
        _run_profiled(
            profile_call,
            "OvstageChangeStream.native_dirty.destroy_path_dictionary",
            _destroy_path_dictionary,
            paths,
        )


def _native_dirty_topology_paths(
    stage: Any,
    since: int,
    current: int,
    *,
    scene: Any | None = None,
) -> tuple[set[str], bool]:
    """Return user topology paths from a narrow native ``usd-path`` read."""

    if current <= since or not _is_native_kit_stage(stage):
        return set(), True
    try:
        ovstage = import_module("ovstage")
        with ovstage.PathDictionary(stage) as paths:
            path_token = paths.intern_token(_USD_PATH_ATTRIBUTE)
            with stage.query(None, [path_token]) as query:
                wait_operation(query)
                with stage.read_attributes(
                    query,
                    [path_token],
                    ovstage.OrdinalRange.between(int(since) + 1, int(current)),
                ) as read:
                    wait_operation(read)
                    dirty_paths: set[str] = set()
                    for group in read_groups(iter(lambda: read.fetch_next(), None)):
                        try:
                            group_paths = tuple(
                                str(path)
                                for path in path_strings(paths, group.prim_list)
                            )
                            for local in range(int(group.prim_count)):
                                try:
                                    path = group_paths[int(group.prim_index(local))]
                                    if _is_user_change_path(path, scene=scene):
                                        dirty_paths.add(path)
                                except Exception:
                                    continue
                        finally:
                            release_read_group(stage, group)
                    return dirty_paths, True
    except Exception:
        return set(), False


def _release_native_query(query: Any) -> None:
    release = getattr(query, "release", None)
    if callable(release):
        try:
            wait_operation(release())
        except Exception:
            pass


def _destroy_path_dictionary(paths: Any) -> None:
    destroy = getattr(paths, "destroy", None)
    if callable(destroy):
        try:
            destroy()
        except Exception:
            pass


def _is_user_change_path(path: str, *, scene: Any | None = None) -> bool:
    value = str(path)
    if not value.startswith("/"):
        return False
    presentation_roots = tuple(
        str(root)
        for root in (getattr(scene, "presentation_root_paths", ()) or ())
    )
    if any(
        value == root or value.startswith(f"{root}/")
        for root in presentation_roots
    ):
        return False
    if value == "/Render/OmniverseGlobalRenderSettings" or value.startswith(
        "/Render/OmniverseGlobalRenderSettings/"
    ):
        return False
    return True


def _leafmost_paths(paths: set[str]) -> set[str]:
    """Drop ancestors when an atomic topology change also contains descendants."""
    normalized = {str(path).rstrip("/") or "/" for path in paths}
    return {
        path
        for path in normalized
        if not any(
            other != path and other.startswith(path.rstrip("/") + "/")
            for other in normalized
        )
    }


def _rootmost_paths(paths: set[str]) -> set[str]:
    """Keep only the paths whose parent is not itself in ``paths``."""
    normalized = {str(path).rstrip("/") or "/" for path in paths}
    return {
        path
        for path in normalized
        if (path.rsplit("/", 1)[0] or "/") not in normalized
    }


def _expand_transform_paths(
    stage: Any,
    paths: set[str],
    *,
    scene: Any | None = None,
) -> set[str]:
    """Include descendants whose derived world matrix changes with a parent."""
    expanded = set(paths)
    pending = list(paths)
    while pending:
        parent = pending.pop()
        try:
            children = tuple(stage.get_child_paths(parent))
        except Exception:
            continue
        for child in children:
            child_path = str(child)
            if child_path in expanded or not _is_user_change_path(
                child_path,
                scene=scene,
            ):
                continue
            expanded.add(child_path)
            pending.append(child_path)
    return expanded


def _info_event(
    paths: set[str],
    source: str,
    visibility_delta: Any | None = None,
) -> ChangeEvent:
    return ChangeEvent(
        changed_paths=tuple(sorted(paths)),
        resynced_paths=(),
        event_type=ChangeEventType.INFO_CHANGE,
        source=source,
        visibility_delta=visibility_delta,
    )


def _classified_source(category_source: str, provenance_source: str | None) -> str:
    if not provenance_source:
        return category_source
    return provenance_source


def _append_unique_event(
    events: list[ChangeEvent],
    seen_events: set[_EventKey],
    event: ChangeEvent,
) -> None:
    key = (
        event.event_type,
        event.source,
        tuple(event.changed_paths),
        tuple(event.resynced_paths),
    )
    if key in seen_events:
        return
    seen_events.add(key)
    events.append(event)


def _paths_for_group(stage: Any, group: dict[str, Any]) -> tuple[str, ...]:
    handle = int(group.get("prim_list_handle") or 0)
    if not handle:
        return ()
    try:
        return tuple(str(path) for path in stage.get_prim_paths(handle))
    except Exception:
        return ()


def _paths_from_indices(paths: tuple[str, ...], indices: Any) -> tuple[str, ...]:
    result: list[str] = []
    for index in indices or ():
        try:
            i = int(index)
        except Exception:
            continue
        if 0 <= i < len(paths):
            result.append(paths[i])
    return tuple(result)


def _deliver(
    call_later: Callable[[float, Callable[[], None]], Any] | None,
    callback: Callable[[], None],
) -> None:
    if call_later is None:
        callback()
    else:
        call_later(0.0, callback)


def _guarded_call(
    stream: Any, callback: Callable[[], None], scheduled: bool
) -> None:
    """Run one subscriber callback with adapter-owned failure accounting.

    Synchronous delivery records then re-raises so the caller's isolation
    loop can aggregate. Scheduled (call_later) delivery has no caller to
    aggregate into, so failures — BaseException included — are recorded on
    the stream (`delivery_failures`, bounded) instead of being lost or
    breaking the scheduler's callback loop.
    """
    try:
        callback()
    except BaseException as exc:  # noqa: BLE001 — provider isolation
        failures = getattr(stream, "delivery_failures", None)
        if failures is None:
            failures = []
            try:
                stream.delivery_failures = failures
            except Exception:
                raise
        failures.append(exc)
        del failures[:-16]
        if not scheduled:
            raise


def _raise_delivery_failures(
    failures: list, *, capture: list | None = None
) -> None:
    """Re-raise only interrupt-class failures after all subscribers ran.

    Native state and undo history are already committed before semantic
    observers run, so one faulty observer must not make the command
    service report a false mutation failure or leave the committed edit
    unundoable: Exception-class failures were already recorded on the
    stream's ``delivery_failures`` ledger by ``_guarded_call`` and are
    swallowed here. Non-Exception BaseExceptions (KeyboardInterrupt,
    SystemExit) cannot be swallowed — by default the first re-raises
    after every subscriber was attempted, with the remaining failures
    attached as notes. With ``capture`` (a committed-edge publication:
    the history entry for the already-committed state is still pending)
    interrupts are deferred into the scope instead, which re-raises them
    marked history-consistent at exit — never hidden from the caller.
    """
    if capture is not None:
        capture.extend(f for f in failures if not isinstance(f, Exception))
        return
    primary = next((f for f in failures if not isinstance(f, Exception)), None)
    if primary is None:
        return
    extras = [f for f in failures if f is not primary]
    add_note = getattr(primary, "add_note", None)
    if callable(add_note):
        for failure in extras:
            add_note(f"{type(failure).__name__}: {failure}")
    raise primary


def _paths_overlap(paths: tuple[str, ...], event_paths: set[str]) -> bool:
    for path in paths:
        if path in event_paths:
            return True
        prefix = f"{path.rstrip('/')}/"
        if any(changed.startswith(prefix) for changed in event_paths):
            return True
    return False

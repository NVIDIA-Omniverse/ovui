# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this software, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovstage dirty-ordinal polling bridged to common change events."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable

from ovui_data_adapters.common import ChangeEvent, ChangeEventType
from ovui_data_adapters.common._command import (
    history_consistent_interrupt,
    in_command_edge,
    interrupt_copy,
)
from ovui_data_adapters.common._subscription import SubscriptionProtocol
from ovui_data_adapters.ovstage._native import resolve_query_names
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
        stage = getattr(scene, "_stage", None)
        self._topology_paths = (
            _native_topology_paths(stage, scene=scene)
            if _is_native_kit_stage(stage)
            else set()
        )
        if stage is not None:
            discard_recorded_stage_writes(
                stage,
                through_ordinal=self._last_ordinal,
            )

    @property
    def last_ordinal(self) -> int:
        return self._last_ordinal

    @property
    def has_pending_suppressed_range(self) -> bool:
        return self._suppressed > 0 or self._suppressed_until_ordinal is not None

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
        if self._closed:
            return ()
        scene = self._scene
        stage = getattr(scene, "_stage", None)
        current_ordinal = getattr(scene, "current_ordinal", None)
        if stage is None or current_ordinal is None:
            return ()
        current = int(current_ordinal)
        if current <= self._last_ordinal:
            return ()
        if self._suppressed:
            return ()
        if not deliver_suppressed:
            self._discard_suppressed_range(current)
            if current <= self._last_ordinal:
                return ()
        else:
            self._clear_delivered_suppression(current)

        since = self._last_ordinal
        physics_paths = self._physics_transform_paths_for_range(
            since_ordinal=since,
            current_ordinal=current,
        )
        if physics_paths:
            events = (
                _info_event(
                    set(physics_paths),
                    _classified_source(_TRANSFORM_SOURCE, source),
                ),
            )
        else:
            events = tuple(self._collect_events(stage, current, since, source=source))
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
        self._poll_scheduled = False
        self._poll_handle = None
        if self._closed or not self._has_subscribers():
            return
        self.poll()
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
    ) -> list[ChangeEvent]:
        if _is_native_kit_stage(stage):
            return self._collect_native_events(stage, current, since, source=source)
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
    ) -> list[ChangeEvent]:
        events: list[ChangeEvent] = []
        seen_events: set[_EventKey] = set()
        current_paths = _native_topology_paths(stage, scene=self._scene)
        previous_paths = set(self._topology_paths)
        # OVStage's compatibility cache synthesizes missing ancestors so the
        # hierarchy remains traversable.  A single child creation can therefore
        # introduce both its path and a synthetic parent in the same ordinal.
        # Report the leaf operation; consumers resync its ancestors naturally.
        added_paths = _leafmost_paths(current_paths - previous_paths)
        removed_paths = _leafmost_paths(previous_paths - current_paths)
        structural_paths = added_paths | removed_paths
        self._topology_paths = current_paths
        self._append_resync_event(events, seen_events, added_paths, _ADDED_SOURCE)
        self._append_resync_event(events, seen_events, removed_paths, _REMOVED_SOURCE)

        dirty_by_attr = _native_dirty_paths_by_attribute(
            stage,
            since,
            current,
            scene=self._scene,
        )

        def paths_for(attributes: frozenset[str]) -> set[str]:
            result: set[str] = set()
            for attr_name in attributes:
                result.update(dirty_by_attr.get(attr_name, ()))
            result.difference_update(structural_paths)
            return result

        topology_paths = paths_for(_TOPOLOGY_ATTRS)
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
                or attr_name == "usd-path"
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
            dirty_by_attr = _native_dirty_paths_by_attribute(
                stage,
                since,
                current,
                scene=self._scene,
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


def _native_topology_paths(stage: Any, *, scene: Any | None = None) -> set[str]:
    if not _is_native_kit_stage(stage):
        return set()
    try:
        result = stage.query_prims(int(getattr(stage, "current_ordinal", 0) or 0))
        paths: set[str] = set()
        for group in result.get("groups", ()):
            handle = int(group.get("prim_list_handle") or 0)
            if not handle:
                continue
            paths.update(
                str(path)
                for path in stage.get_prim_paths(handle)
                if _is_user_change_path(str(path), scene=scene)
            )
        return paths
    except Exception:
        return set()


def _native_dirty_paths_by_attribute(
    stage: Any,
    since: int,
    current: int,
    *,
    scene: Any | None = None,
) -> dict[str, set[str]]:
    if current <= since or not _is_native_kit_stage(stage):
        return {}
    query = None
    read = None
    paths = None
    # Journal rows supplement native dirty reads for newly-upserted columns,
    # but renderer-owned writes use the same copy-in path.  Apply the exact
    # user-path policy used below for native read groups before journal
    # evidence can participate in a user-facing ChangeEvent.
    dirty = {
        str(attribute_name): {
            str(path)
            for path in attribute_paths
            if _is_user_change_path(str(path), scene=scene)
        }
        for attribute_name, attribute_paths in recorded_stage_writes(
            stage,
            since_ordinal=since,
            current_ordinal=current,
        ).items()
    }
    dirty = {
        attribute_name: attribute_paths
        for attribute_name, attribute_paths in dirty.items()
        if attribute_paths
    }
    try:
        ovstage = import_module("ovstage")
        paths = ovstage.PathDictionary(stage)
        query = stage.query(filter=None)
        wait_operation(query)
        result = query.result()
        attributes = [int(token) for token in getattr(result, "attributes", ())]
        # A column created after the query population snapshot is writable and
        # render-visible, but is not necessarily returned by unscoped attribute
        # discovery immediately.  Explicitly include the adapter's semantic
        # columns so their dirty ranges are still observable.
        known_names = _TOPOLOGY_ATTRS | _TRANSFORM_ATTRS | _VISIBILITY_ATTRS
        attributes.extend(paths.intern_token(name) for name in known_names)
        attributes = list(dict.fromkeys(attributes))
        if not attributes:
            return dirty
        read = stage.read_attributes(
            query,
            attributes,
            ovstage.OrdinalRange.between(int(since) + 1, int(current)),
        )
        wait_operation(read)
        while True:
            group = read.fetch_next()
            if group is None:
                break
            try:
                attr_name = paths.token_to_string(int(group.attribute))
                group_paths = tuple(
                    str(path) for path in paths.get_path_strings(group.prim_list)
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
                    stage.release_group(group)
                except Exception:
                    pass
        return dirty
    except Exception:
        return dirty
    finally:
        if read is not None:
            try:
                release = getattr(read, "release", None)
                wait_operation(
                    release() if callable(release) else stage.release_read(read)
                )
            except Exception:
                pass
        _release_native_query(query)
        _destroy_path_dictionary(paths)


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

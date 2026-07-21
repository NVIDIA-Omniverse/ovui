# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""HierarchyItem and HierarchyModel — tree model for the Stage Browser TreeView.

HierarchyModel wraps a StageAdapter into
omni.ui.AbstractItemModel for display in a ui.TreeView.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import omni.ui as ui
from ovui_data_adapters.common import (
    BadgeFlags,
    ChangeEvent,
    ChangeEventType,
    ItemFlags,
    ReparentPosition,
    VisibilityState,
    is_camera_property_only_info_change,
    is_viewport_camera_pose_change_event,
)

from ovui_widgets.common import scheduler as _scheduler
from ovui_widgets.stage.models import VisibilityValueModel
from ovui_widgets.stage.widget.filter_pipeline import FilterPipeline, make_name_filter

DRAG_MIME = "application/ovui_widgets.stage-item"
_TRANSFORM_INFO_CHANGE_SOURCES = frozenset({"ovstage:transform"})

if TYPE_CHECKING:
    from ovui_data_adapters.common import StageAdapter


def _is_transform_only_info_change(event: ChangeEvent) -> bool:
    """Return true for transform dirtiness that cannot alter hierarchy rows."""
    if event.event_type is not ChangeEventType.INFO_CHANGE:
        return False
    if event.source not in _TRANSFORM_INFO_CHANGE_SOURCES:
        return False
    return bool(event.changed_paths) and not bool(event.resynced_paths)


class _NullSubscription:
    """Inert subscription handle for the explicit no-document state."""

    def cancel(self) -> None:
        pass


class HierarchyItem(ui.AbstractItem):
    """Wraps an AdapterItem for use in the TreeView model.

    Lazy-loads children on first access. Caches ``ItemFlags`` / ``BadgeFlags``
    from the adapter behind a dirty bit so the delegate can ask
    ``is_default`` / ``is_inactive`` / etc. without re-entering the adapter on
    every render. See the stage hierarchy behavior for the pattern.
    """

    def __init__(self, adapter_item: Any, parent: "HierarchyItem | None" = None) -> None:
        super().__init__()
        self.adapter_item = adapter_item
        self.parent = parent
        self._children: "list[HierarchyItem] | None" = None
        self._name_model: ui.SimpleStringModel | None = None
        self._type_model: ui.SimpleStringModel | None = None
        self._vis_model: VisibilityValueModel | None = None

        # Lazy flag cache — populated on first accessor call, invalidated by
        # mark_dirty() whenever the adapter reports a change.
        self._flags_dirty: bool = True
        self._item_flags: ItemFlags = ItemFlags.NONE
        self._badge_flags: BadgeFlags = BadgeFlags.NONE

        # Filter state — set by the filter pipeline (Steps 18+). ``filtered``
        # is True when this item itself passes the active filter;
        # ``child_filtered`` is True when any descendant passes. Kept on the
        # item so the delegate can paint match vs. pass-through styling.
        self.filtered: bool = False
        self.child_filtered: bool = False

    # ── Flag cache ────────────────────────────────────────────────────────────

    def mark_dirty(self) -> None:
        """Invalidate cached flags and rebroadcast the visibility model.

        The next ``item_flags`` / ``badge_flags`` call will re-read the
        adapter. The visibility model reads through to the adapter on every
        access, so we only have to notify listeners — ``_value_changed()``
        triggers a repaint of any eye-checkbox bound to this item.
        """
        self._flags_dirty = True
        if self._vis_model is not None:
            self._vis_model._value_changed()

    def _refresh_flags(self, adapter: "StageAdapter") -> None:
        """Re-read ``ItemFlags`` / ``BadgeFlags`` from the adapter if dirty."""
        if not self._flags_dirty:
            return
        self._item_flags = adapter.get_item_flags(self.adapter_item)
        self._badge_flags = adapter.get_badge_flags(self.adapter_item)
        self._flags_dirty = False

    def item_flags(self, adapter: "StageAdapter") -> ItemFlags:
        self._refresh_flags(adapter)
        return self._item_flags

    def badge_flags(self, adapter: "StageAdapter") -> BadgeFlags:
        self._refresh_flags(adapter)
        return self._badge_flags

    def is_default(self, adapter: "StageAdapter") -> bool:
        return bool(self.item_flags(adapter) & ItemFlags.IS_DEFAULT_PRIM)

    def is_inactive(self, adapter: "StageAdapter") -> bool:
        return bool(self.item_flags(adapter) & ItemFlags.IS_INACTIVE)

    def is_instance_proxy(self, adapter: "StageAdapter") -> bool:
        return bool(self.item_flags(adapter) & ItemFlags.IS_INSTANCE_PROXY)

    def is_class_item(self, adapter: "StageAdapter") -> bool:
        return bool(self.item_flags(adapter) & ItemFlags.IS_CLASS)

    def is_abstract(self, adapter: "StageAdapter") -> bool:
        return bool(self.item_flags(adapter) & ItemFlags.IS_ABSTRACT)


class HierarchyModel(ui.AbstractItemModel):
    """TreeView data model backed by a StageAdapter.

    Lazy-loads children on expand. Listens to adapter change events
    and refreshes affected items.

    3 columns: Name (0), Type (1), Visibility (2).
    """

    NUM_COLUMNS = 3
    PRIM_EXPAND_THRESHOLD = 10_000
    PRIM_LAZY_BATCH_SIZE = 100

    def __init__(self, adapter: "StageAdapter") -> None:
        super().__init__()
        self._adapter = adapter
        self._root = HierarchyItem(adapter.get_root(), None)
        self._path_cache: dict[str, HierarchyItem] = {}
        self._selected_items: list[HierarchyItem] = []
        self._selection_guard: bool = False
        self._filter_pipeline: FilterPipeline = FilterPipeline()
        self._expanded_paths: set[str] = set()
        self._pending_expand_paths: set[str] = set()
        self._rename_controller = None
        self._drop_visual = None
        self._namespace_selection_remap_callback = None
        # Set by StageWidget after it creates the TreeView. Used in
        # _on_adapter_changed to snapshot which items the user currently
        # has expanded (authoritative) before the rebuild blows away the
        # item cache.
        self._tree_view_ref: Any = None
        # Old-subscription handles whose cancellation failed: retained
        # for retry so an old provider callback is never silently leaked.
        self._stale_change_subs: list = []
        self._adapter_epoch: Any = object()
        self._change_sub = adapter.subscribe_changes(
            self._epoch_guarded_callback(self._adapter_epoch))

    def set_adapter(self, adapter: "StageAdapter") -> None:
        """Hot-swap the underlying adapter TRANSACTIONALLY and rebuild.

        The new subscription and root are acquired FIRST: if either
        raises, the model still points at the old adapter with its live
        subscription — a replacement that cannot notify this consumer
        never half-installs. A failed old-subscription cancellation is
        retained for retry so the old callback is never silently leaked.
        """
        self._drain_stale_change_subs()
        if len(self._stale_change_subs) >= 32:
            # BOUNDED revocation ownership: refuse further swaps instead
            # of accumulating live registrations — the current document
            # stays fully usable and the swap can retry after the
            # provider allows revocation.
            raise RuntimeError(
                "stage model swap refused: too many hierarchy "
                "subscriptions with failed cancellation are retained; "
                "retry after revocation succeeds"
            )
        new_epoch = object()
        new_sub = adapter.subscribe_changes(
            self._epoch_guarded_callback(new_epoch))
        try:
            new_root = HierarchyItem(adapter.get_root(), None)
        except BaseException as primary:
            # EXACT ownership of the acquired subscription across every
            # throwable: revoke it, or retain the handle for retry — and
            # keep the cleanup failure inspectable on the primary.
            try:
                new_sub.cancel()
            except BaseException as secondary:  # noqa: BLE001 — retained
                self._stale_change_subs.append(new_sub)
                add_note = getattr(primary, "add_note", None)
                if callable(add_note):
                    add_note(
                        "secondary cleanup failure: "
                        f"{type(secondary).__name__}: {secondary}")
            raise
        # A failed old-subscription revocation — ANY throwable — must not
        # half-swap: the handle is retained for retry, the swap completes
        # (nothing acquired leaks, nothing old keeps ownership), and a
        # non-Exception throwable then propagates from a COMPLETE state.
        pending_throwable: BaseException | None = None
        try:
            self._change_sub.cancel()
        except Exception:
            self._stale_change_subs.append(self._change_sub)
        except BaseException as exc:
            self._stale_change_subs.append(self._change_sub)
            pending_throwable = exc
        self._adapter = adapter
        self._root = new_root
        self._path_cache.clear()
        # Paths persisted from the previous stage rarely apply to the new
        # one — drop them so ``_restore_expansion`` doesn't try to expand
        # /World paths that no longer resolve.
        self._expanded_paths.clear()
        self._selected_items = []
        self._pending_expand_paths.clear()
        self._change_sub = new_sub
        self._adapter_epoch = new_epoch
        self._drain_stale_change_subs()
        self._item_changed(None)
        if pending_throwable is not None:
            raise pending_throwable

    def _epoch_guarded_callback(self, epoch: Any) -> Any:
        """Event callback bound to ONE document epoch.

        A stale subscription (failed revocation, retained for retry) can
        never regain authority — not even when the SAME adapter object is
        installed again later, because every install mints a new epoch.
        """

        def _guarded(event: Any) -> None:
            if self._adapter_epoch is epoch:
                self._on_adapter_event(event)

        return _guarded

    def detach_document(self) -> None:
        """Converge this model to the explicit NO-DOCUMENT state.

        The subscription is revoked (or retained for retry when the
        cancellation fails), every cache clears, and no stale row remains
        resolvable. The tree presents empty until a new adapter installs.
        """
        pending_throwable: BaseException | None = None
        try:
            self._change_sub.cancel()
        except Exception:
            self._stale_change_subs.append(self._change_sub)
        except BaseException as exc:
            self._stale_change_subs.append(self._change_sub)
            pending_throwable = exc
        self._change_sub = _NullSubscription()
        self._adapter_epoch = None
        self._adapter = None
        self._root = None
        self._path_cache.clear()
        self._expanded_paths.clear()
        self._selected_items = []
        self._pending_expand_paths.clear()
        self._drain_stale_change_subs()
        self._item_changed(None)
        if pending_throwable is not None:
            raise pending_throwable

    def _drain_stale_change_subs(self) -> None:
        """Retry cancellation of subscriptions whose revocation failed."""
        remaining = []
        for handle in self._stale_change_subs:
            try:
                handle.cancel()
            except BaseException:  # noqa: BLE001 — retained for retry
                remaining.append(handle)
        self._stale_change_subs[:] = remaining

    def set_rename_controller(self, controller: Any) -> None:
        self._rename_controller = controller

    def set_drop_visual_controller(self, controller: Any) -> None:
        self._drop_visual = controller

    def set_namespace_selection_remap_callback(self, callback: Any) -> None:
        """Install the StageWidget callback that restores moved selections."""

        self._namespace_selection_remap_callback = callback

    def begin_edit(self, item: Any) -> None:
        """Accept ovui's native TreeView drop transaction boundary.

        The pybind trampoline's inherited fallback re-enters the virtual
        ``begin_edit`` method. An explicit Python override is required even
        though this model has no additional begin-side work.
        """

    def end_edit(self, item: Any) -> None:
        """Complete ovui's native TreeView drop transaction boundary."""

    # ── Drag / drop (AbstractItemModel overrides) ─────────────────────────────

    def get_drag_mime_data(self, item: Any) -> str:
        """Called when a drag starts on item. Cancel pending rename to avoid conflicts."""
        if self._rename_controller is not None:
            self._rename_controller.cancel_pending_timer()
        return DRAG_MIME

    def drop_accepted(self, target_item: Any, source_item: Any, drop_location: int = -1) -> bool:
        """Called while dragging over target. Returns True if reparent is valid."""
        if not isinstance(target_item, HierarchyItem) or not isinstance(source_item, HierarchyItem):
            return False
        can = self._adapter.can_reparent(
            [source_item.adapter_item], target_item.adapter_item
        )
        if self._drop_visual is not None:
            if can:
                self._drop_visual.show_drop_target(target_item, drop_location)
            else:
                self._drop_visual.clear()
        return can

    def drop(self, target_item: Any, source_item: Any, drop_location: int = -1) -> None:
        """Schedule a reparent after the native TreeView drop callback returns.

        A reparent publishes a hierarchy resync synchronously.  Mutating this
        model from inside ovui's native drop callback invalidates the exact
        ``HierarchyItem`` objects that callback still owns and can re-enter
        TreeView indefinitely.  Capture stable paths here, re-resolve their
        current adapter items on the next application tick, and abort if an
        intervening resync removed either endpoint.  Isolated model tests have
        no scheduler, so they retain their historical synchronous behavior.
        """
        if self._drop_visual is not None:
            self._drop_visual.clear()
        if not isinstance(target_item, HierarchyItem) or not isinstance(source_item, HierarchyItem):
            return
        adapter = self._adapter
        if not adapter.can_reparent(
            [source_item.adapter_item], target_item.adapter_item
        ):
            return
        source_path = adapter.get_item_path(source_item.adapter_item)
        target_parent_path = adapter.get_item_path(target_item.adapter_item)
        target_path = (
            f"{target_parent_path.rstrip('/')}/{source_path.rsplit('/', 1)[-1]}"
        )
        selected_paths = tuple(self.get_selected_paths())

        def reparent_after_drop() -> None:
            if self._adapter is not adapter:
                return

            try:
                source_adapter_item = adapter.get_item_at_path(source_path)
                target_adapter_item = adapter.get_item_at_path(target_parent_path)
                if source_adapter_item is None or target_adapter_item is None:
                    return
                if not adapter.can_reparent(
                    [source_adapter_item], target_adapter_item
                ):
                    return
            except Exception as exc:
                from ovui_widgets.common.error_reporter import ErrorReporter

                ErrorReporter.show_error(
                    f"Cannot reparent prim: {type(exc).__name__}: {exc}"
                )
                return

            reparented = False
            operation_error: Exception | None = None
            undo_group_open = False
            try:
                adapter.begin_undo_group("Reparent")
                undo_group_open = True
                adapter.reparent(
                    [source_adapter_item],
                    target_adapter_item,
                    ReparentPosition.CHILD,
                )
                reparented = True
            except Exception as exc:
                operation_error = exc
            finally:
                if undo_group_open:
                    try:
                        adapter.end_undo_group()
                    except Exception as exc:
                        if operation_error is None:
                            operation_error = exc
                        else:
                            add_note = getattr(operation_error, "add_note", None)
                            if callable(add_note):
                                add_note(
                                    "Reparent undo-group cleanup also failed: "
                                    f"{type(exc).__name__}: {exc}"
                                )

            if operation_error is not None:
                from ovui_widgets.common.error_reporter import ErrorReporter

                ErrorReporter.show_error(
                    "Cannot reparent prim: "
                    f"{type(operation_error).__name__}: {operation_error}"
                )
            if not reparented:
                return

            remap_selection = self._namespace_selection_remap_callback
            if remap_selection is None:
                return
            mapped_selection = [
                target_path + path[len(source_path) :]
                if path == source_path or path.startswith(source_path + "/")
                else path
                for path in selected_paths
            ]

            def restore_selection_after_notices() -> None:
                if self._adapter is adapter:
                    remap_selection(mapped_selection)

            try:
                # Adapter RESYNC callbacks were queued by reparent() above.
                # Restore the canonical path only after those callbacks have
                # rebuilt TreeView, otherwise its stale-item clear wins.
                _scheduler.call_later(0.0, restore_selection_after_notices)
            except RuntimeError:
                restore_selection_after_notices()

        try:
            _scheduler.call_later(0.0, reparent_after_drop)
        except RuntimeError:
            reparent_after_drop()

    def get_item_children(self, item: Any) -> list[HierarchyItem]:
        """If item is None, return [root]. Otherwise lazy-load children."""
        if self._root is None or self._adapter is None:
            return []  # explicit no-document state: nothing resolvable
        if item is None:
            return [self._root]
        if not isinstance(item, HierarchyItem):
            return []
        if item._children is None:
            item._children = self._load_children(item)
        return item._children

    def resolve_path(self, path: str) -> "HierarchyItem | None":
        """Resolve ``path`` to a HierarchyItem, lazy-loading ancestors along the way.

        The widget's public API (``expand``, ``set_selection``,
        ``_restore_expansion``) reads from ``_path_cache``, which is only
        populated when the TreeView has already rendered a row. That leaves
        paths unreachable right after a model rebuild (all ancestor rows are
        collapsed again) — walking from the root and forcing
        ``get_item_children`` at each step re-populates the cache so callers
        can address deep paths reliably.

        Returns ``None`` when the path doesn't resolve in the backing adapter.
        """
        if not path:
            return None
        if self._adapter is None or self._root is None:
            return None  # explicit no-document state: nothing resolves
        root_path = self._adapter.get_item_path(self._root.adapter_item)
        if path == root_path:
            return self._root
        cached = self._path_cache.get(path)
        if cached is not None:
            return cached
        if self._adapter.get_item_at_path(path) is None:
            return None
        root_parts = [p for p in root_path.split("/") if p]
        target_parts = [p for p in path.split("/") if p]
        if target_parts[: len(root_parts)] != root_parts:
            return None
        walk = target_parts[len(root_parts):]
        current = self._root
        current_path = root_path
        for seg in walk:
            children = self.get_item_children(current)
            next_path = f"{current_path.rstrip('/')}/{seg}"
            found = None
            for ch in children:
                if self._adapter.get_item_path(ch.adapter_item) == next_path:
                    found = ch
                    break
            if found is None:
                return None
            current = found
            current_path = next_path
        return current

    def can_item_have_children(self, item: Any) -> bool:
        if not isinstance(item, HierarchyItem):
            return False
        return bool(self._adapter.get_children(item.adapter_item))

    def get_item_value_model_count(self, item: Any) -> int:
        return self.NUM_COLUMNS

    def get_item_value_model(self, item: Any, column_id: int) -> Any:
        """Column 0 = name, Column 1 = type label, Column 2 = inverted visibility (True=hidden)."""
        if not isinstance(item, HierarchyItem):
            return None
        if column_id == 0:
            if item._name_model is None:
                name = self._adapter.get_display_name(item.adapter_item)
                item._name_model = ui.SimpleStringModel(name)
            return item._name_model
        if column_id == 1:
            if item._type_model is None:
                type_name = self._adapter.get_type_name(item.adapter_item)
                item._type_model = ui.SimpleStringModel(type_name)
            return item._type_model
        if column_id == 2:
            if item._vis_model is None:
                item._vis_model = VisibilityValueModel(item, self._adapter, self)
            return item._vis_model
        return None

    def _get_children_count(self, item: HierarchyItem) -> int:
        """Return the total adapter child count without creating HierarchyItems."""
        return len(self._adapter.get_children(item.adapter_item))

    def load_more_children(self, item: HierarchyItem) -> int:
        """Load the next batch of children for a lazily-loaded item.

        Returns the number of newly added children. Returns 0 when item has no
        pending children (path not in _pending_expand_paths).
        """
        item_path = self._adapter.get_item_path(item.adapter_item)
        if item_path not in self._pending_expand_paths:
            return 0

        all_adapter_children = self._adapter.get_children(item.adapter_item)
        current_loaded = len(item._children) if item._children is not None else 0

        if current_loaded >= len(all_adapter_children):
            self._pending_expand_paths.discard(item_path)
            return 0

        next_batch = all_adapter_children[
            current_loaded: current_loaded + self.PRIM_LAZY_BATCH_SIZE
        ]
        new_items = []
        for ac in next_batch:
            child = HierarchyItem(ac, parent=item)
            child_path = self._adapter.get_item_path(ac)
            self._path_cache[child_path] = child
            new_items.append(child)

        if item._children is None:
            item._children = []
        item._children.extend(new_items)

        if current_loaded + len(new_items) >= len(all_adapter_children):
            self._pending_expand_paths.discard(item_path)

        self._item_changed(item)
        return len(new_items)

    def _load_children(self, item: HierarchyItem) -> list[HierarchyItem]:
        adapter_children = self._adapter.get_children(item.adapter_item)

        # Lazy loading: when count > threshold and no active filter, show first batch only.
        # Filter mode bypassed: filter traversal already scans the full subtree.
        if (
            not self._filter_pipeline.is_active
            and len(adapter_children) > self.PRIM_EXPAND_THRESHOLD
        ):
            item_path = self._adapter.get_item_path(item.adapter_item)
            self._pending_expand_paths.add(item_path)
            adapter_children = adapter_children[: self.PRIM_LAZY_BATCH_SIZE]

        children = []
        for ac in adapter_children:
            if self._filter_pipeline.is_active:
                passes = self._filter_pipeline.passes(self._adapter, ac)
                if not passes:
                    passes = self._has_matching_descendant(ac)
                if not passes:
                    continue
            path = self._adapter.get_item_path(ac)
            # Re-use the existing HierarchyItem for this path when we can
            # so the TreeView's object-identity-keyed expansion state
            # survives a rebuild. Without this, clearing the cache inside
            # _on_adapter_changed forced us to hand the TreeView fresh
            # items that it has never seen — set_expanded on those lands
            # on nothing until the TreeView has walked them at least once.
            child = self._path_cache.get(path)
            if child is None:
                child = HierarchyItem(ac, parent=item)
            else:
                child.adapter_item = ac
                child.parent = item
                child.mark_dirty()
            self._path_cache[path] = child
            children.append(child)
        return children

    def _has_matching_descendant(self, adapter_item: Any) -> bool:
        """Returns True if any descendant passes the active filter."""
        for child in self._adapter.get_children(adapter_item):
            if self._filter_pipeline.passes(self._adapter, child):
                return True
            if self._has_matching_descendant(child):
                return True
        return False

    def set_filter(self, text: str) -> None:
        """Apply a name filter to the hierarchy. Empty string clears the filter."""
        self._filter_pipeline.clear()
        if text:
            self._filter_pipeline.add_predicate(make_name_filter(text))
        self._reset_children(self._root)
        self._path_cache.clear()
        self._item_changed(None)

    def _reset_children(self, item: HierarchyItem) -> None:
        """Recursively clear cached children so they reload with the active filter."""
        if item._children is not None:
            for child in item._children:
                self._reset_children(child)
            item._children = None

    def _set_path_expanded(self, path: str, expanded: bool) -> None:
        """Track expand/collapse state so it can be restored after tree rebuild."""
        if expanded:
            self._expanded_paths.add(path)
        else:
            self._expanded_paths.discard(path)

    def _on_adapter_event(self, event: ChangeEvent) -> None:
        if is_viewport_camera_pose_change_event(event):
            return
        if is_camera_property_only_info_change(event):
            return
        if _is_transform_only_info_change(event):
            return
        if self._is_visibility_only_event(event):
            self._apply_visibility_event(event)
            return
        self._on_adapter_changed(event)

    # ── Visibility events: per-item invalidation ──────────────────────────────
    #
    # Repaint roots come exclusively from the event's paths, which the
    # adapter derives from genuine Usd.Notice.ObjectsChanged payloads. Roots
    # carrying an adapter-owned pre/post boundary record get precise descent
    # cuts. Roots that arrived as genuine `.visibility` property paths in an
    # adapter-marked event name an exhaustive write set, so an explicitly
    # invisible descendant outside that set (its own resolved value,
    # unchanged by this edit) prunes its branch. Coarse roots — bare prim
    # resyncs (Mode B replays), provider-published prim paths, and every
    # root of a delta-less or uncertain fallback event — may include a
    # descendant's own property change, so they traverse the entire
    # materialized subtree with no current-state cut; only non-imageable
    # prims stay transparent (they carry no visibility of their own). This
    # never falls back to a whole-model _item_changed(None).

    def _is_visibility_only_event(self, event: ChangeEvent) -> bool:
        """True for events whose roots are PROVEN visibility-bounded.

        Three shapes qualify (PR review: name/shape-only reclassification
        is prohibited at this boundary too — anything unproven takes the
        structural rebuild path):
        - an adapter-marked event whose delta is attempt-PROVEN and
          PRECISE, whose resyncs are all annotated replay consequences,
          and whose changed property paths all belong to adapter-proven
          visibility-authored prims. Context-free conservative flushes,
          precise+imprecise merges, disposal assemblies, and events
          retaining lookalike property paths (relationships, custom or
          non-Imageable attributes named ``visibility``) fail one of these
          and rebuild structurally;
        - an OVStage visibility event (``source == "ovstage:visibility"``):
          the provider-owned visibility stream publishes bare prim paths;
        - a plain external OpenUSD info event whose `.visibility` property
          paths each currently compose as the genuine Imageable schema
          visibility attribute (verified through the adapter's
          observational ``is_visibility_attribute_path``; bare prim
          changed-info entries fold to row-only roots). A pure external
          relationship/lookalike notice therefore rebuilds structurally.
        """
        if event.visibility_delta is not None:
            delta = event.visibility_delta or {}
            if delta.get("proven") is not True:
                return False
            if not delta.get("precise", True):
                return False
            annotated = set(delta.get("operation_resyncs") or ())
            if not all(
                str(path) in annotated
                for path in tuple(event.resynced_paths or ())
            ):
                return False
            authored = set(delta.get("authored") or ())
            for path in tuple(event.changed_paths or ()):
                prim, separator, _prop = str(path).rpartition(".")
                if not separator:
                    continue  # bare prim path: fold (row-only root)
                if prim not in authored:
                    # A retained property path the adapter did NOT prove
                    # as visibility-authored (e.g. a lookalike): the
                    # lightweight per-item path cannot own it.
                    return False
            return True
        if event.event_type is not ChangeEventType.INFO_CHANGE:
            return False
        if getattr(event, "source", None) == "ovstage:visibility":
            return bool(tuple(event.changed_paths or ()))
        if tuple(event.resynced_paths or ()):
            return False
        changed = tuple(event.changed_paths or ())
        if not changed:
            return False
        attribute_probe = getattr(
            self._adapter, "is_visibility_attribute_path", None
        )
        if not callable(attribute_probe):
            return False  # unverifiable externals rebuild structurally
        saw_visibility = False
        for path in changed:
            prim, separator, prop = str(path).rpartition(".")
            if not separator:
                continue  # bare prim path: fold (row-only root)
            if prop != "visibility":
                return False
            try:
                if not attribute_probe(str(path)):
                    return False
            except Exception:
                return False
            saw_visibility = True
        return saw_visibility

    @staticmethod
    def _row_changed(record: "tuple[Any, Any]") -> bool:
        old, new = record
        return old != new

    @staticmethod
    def _pruning_changed(record: "tuple[Any, Any]") -> bool:
        old, new = record
        return (old is not VisibilityState.VISIBLE) != (
            new is not VisibilityState.VISIBLE
        )

    def _apply_visibility_event(self, event: ChangeEvent) -> None:
        delta = event.visibility_delta or {}
        vis_prims: set = set()
        bare_prims: set = set()
        other_prims: set = set()
        for path in tuple(event.changed_paths or ()) + tuple(
            event.resynced_paths or ()
        ):
            prim, separator, prop = str(path).rpartition(".")
            if separator and prop == "visibility":
                vis_prims.add(prim)
            elif not separator:
                bare_prims.add(str(path))
            else:
                # Non-visibility surviving genuine path (e.g. a re-entrant
                # metadata/property mutation retained by the ledger): its
                # prim's row repaints (badges/flags may change).
                other_prims.add(prim)
        authored = set(delta.get("authored") or ())
        row_only: set = set()
        if not authored:
            authored = set(vis_prims)
            if vis_prims:
                # Bare prim entries alongside visibility properties are the
                # created ``over`` ancestor chain: row-only, no descent.
                row_only = bare_prims
            else:
                # Provider-published prim roots (e.g. ovstage:visibility):
                # visibility changed at these prims — conservative subtree.
                authored |= bare_prims
        # Surviving genuine paths outside the visibility root set (bare
        # changed-info prims, non-visibility properties) repaint their rows.
        row_only |= (bare_prims | other_prims) - authored
        # The explicit-invisible descent cut needs an exhaustive write set:
        # only roots that arrived as genuine `.visibility` property paths in
        # an adapter-marked event qualify. Bare prim roots (replay resyncs,
        # provider streams) and every root of a delta-less event are coarse.
        trusted_delta = bool(delta) and delta.get("precise", True)
        precise_roots = (
            (vis_prims - bare_prims) & authored if trusted_delta else set()
        )
        boundaries = dict(delta.get("boundaries") or {})
        scheduled: set = set()
        visited: set = set()
        root_path = self._adapter.get_item_path(self._root.adapter_item)

        def item_for(path: str) -> "HierarchyItem | None":
            if path == root_path:
                return self._root
            return self._path_cache.get(path)

        def schedule(path: str) -> None:
            if path in scheduled:
                return
            scheduled.add(path)
            item = item_for(path)
            if item is not None:
                item.mark_dirty()
                self._item_changed(item)

        def is_imageable(item: HierarchyItem) -> bool:
            probe = getattr(self._adapter, "is_imageable", None)
            if not callable(probe):
                return True  # conservative: treat as imageable
            try:
                return bool(probe(item.adapter_item))
            except Exception:
                return True

        def descend(path: str, coarse: bool) -> None:
            item = item_for(path)
            if item is None or item._children is None:
                return
            for child in item._children:
                child_path = self._adapter.get_item_path(child.adapter_item)
                if child_path in visited:
                    continue
                visited.add(child_path)
                if not is_imageable(child):
                    descend(child_path, coarse)  # transparent for inheritance
                    continue
                if coarse:
                    # A coarse root may include this child's own property
                    # change; no current-state evidence can prove the branch
                    # unchanged, so every materialized descendant repaints.
                    schedule(child_path)
                    descend(child_path, coarse)
                    continue
                # Adapter-owned boundary records are authoritative where
                # present (a changed record proves this child's state moved
                # this edge — e.g. a redo re-hiding it).
                record = boundaries.get(child_path)
                if record is not None:
                    if self._row_changed(record) or child_path in authored:
                        schedule(child_path)
                    if self._pruning_changed(record):
                        descend(child_path, coarse)
                    continue
                try:
                    child_state = self._adapter.compute_visibility(
                        child.adapter_item
                    )
                except Exception:
                    child_state = None
                if (
                    child_state is VisibilityState.INVISIBLE
                    and child_path not in authored
                ):
                    continue  # explicitly invisible branch: pruned before and after
                schedule(child_path)
                descend(child_path, coarse)

        # Conservative roots (no boundary record) first: they dominate their
        # subtrees; precise roots inside an already-visited region add nothing.
        roots = sorted(
            authored,
            key=lambda p: (p in boundaries, p.count("/")),
        )
        for root in roots:
            coarse = root not in precise_roots
            if root in visited:
                record = boundaries.get(root)
                if record is not None and (
                    self._row_changed(record) or root in authored
                ):
                    schedule(root)
                continue
            visited.add(root)
            record = boundaries.get(root)
            if record is None or coarse:
                schedule(root)
                descend(root, coarse)
                continue
            if self._row_changed(record) or root in authored:
                schedule(root)
            if self._pruning_changed(record):
                descend(root, coarse)
        for path in row_only:
            schedule(path)  # row-only root; ``scheduled`` dedups

    def _on_adapter_changed(self, event: ChangeEvent) -> None:
        # Full rebuild: clear cached children so new/removed adapter items
        # appear. Keep ``_path_cache`` intact so ``_load_children`` can
        # re-use existing HierarchyItems (see comment there) — that's what
        # lets the TreeView's object-identity-keyed expansion survive.
        # Paths that no longer exist in the adapter will be pruned the
        # next time they're walked through ``resolve_path`` / rendered.
        self._snapshot_expansion_from_tree()
        invalidated: set[int] = set()
        self._invalidate_value_models(self._root, invalidated)
        for item in list(self._path_cache.values()):
            if id(item) in invalidated:
                continue
            item._type_model = None
            item.mark_dirty()
        self._reset_children(self._root)
        self._pending_expand_paths.clear()
        # Best-effort prune: drop cache entries for paths the adapter no
        # longer knows about so they can't mask newer items at the same
        # path after a delete-and-recreate.
        stale = [p for p in self._path_cache
                 if self._adapter.get_item_at_path(p) is None]
        for p in stale:
            self._path_cache.pop(p, None)
            self._expanded_paths.discard(p)
        self._item_changed(None)

    def _snapshot_expansion_from_tree(self) -> None:
        """Refresh ``_expanded_paths`` from the TreeView's live expansion state.

        Programmatic ``expand`` / ``collapse`` calls already maintain
        ``_expanded_paths`` directly, so the only state the set could miss
        is user chevron clicks. Reading it back off the TreeView right
        before a rebuild keeps those clicks from getting erased when we
        drop the path cache.
        """
        tv = self._tree_view_ref
        if tv is None:
            return
        root_path = self._adapter.get_item_path(self._root.adapter_item)
        try:
            if tv.is_expanded(self._root):
                self._expanded_paths.add(root_path)
            else:
                self._expanded_paths.discard(root_path)
            for path, item in list(self._path_cache.items()):
                if tv.is_expanded(item):
                    self._expanded_paths.add(path)
                else:
                    self._expanded_paths.discard(path)
        except Exception:
            # is_expanded can raise if the TreeView has been torn down.
            pass

    def _invalidate_value_models(
        self, item: HierarchyItem, invalidated: set[int] | None = None
    ) -> None:
        if invalidated is not None:
            invalidated.add(id(item))
        item._type_model = None
        # _vis_model stays — VisibilityValueModel reads through to the adapter
        # on every access, and mark_dirty() rebroadcasts _value_changed() so
        # any bound eye-checkbox repaints with the new state.
        item.mark_dirty()
        if item._children:
            for child in item._children:
                self._invalidate_value_models(child, invalidated)

    def get_selected_paths(self) -> list[str]:
        """Return the stage paths of all currently selected items."""
        return [self._adapter.get_item_path(i.adapter_item) for i in self._selected_items]

    def invalidate_item(self, item: HierarchyItem) -> None:
        """Mark an item's children and cached value models as needing reload."""
        item._children = None
        item._type_model = None
        # _vis_model stays — see _invalidate_value_models for the rationale.
        item.mark_dirty()
        self._item_changed(item)

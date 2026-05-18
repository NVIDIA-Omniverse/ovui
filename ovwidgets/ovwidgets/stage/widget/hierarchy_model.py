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
    ItemFlags,
    ReparentPosition,
    is_camera_property_only_info_change,
    is_viewport_camera_pose_change_event,
)

from ovwidgets.stage.models import VisibilityValueModel
from ovwidgets.stage.widget.filter_pipeline import FilterPipeline, make_name_filter

DRAG_MIME = "application/ovwidgets.stage-item"

if TYPE_CHECKING:
    from ovui_data_adapters.common import StageAdapter


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
        # Set by StageWidget after it creates the TreeView. Used in
        # _on_adapter_changed to snapshot which items the user currently
        # has expanded (authoritative) before the rebuild blows away the
        # item cache.
        self._tree_view_ref: Any = None
        self._change_sub = adapter.subscribe_changes(self._on_adapter_event)

    def set_adapter(self, adapter: "StageAdapter") -> None:
        """Hot-swap the underlying adapter, cancel the old subscription, and rebuild."""
        self._change_sub.cancel()
        self._adapter = adapter
        self._root = HierarchyItem(adapter.get_root(), None)
        self._path_cache.clear()
        # Paths persisted from the previous stage rarely apply to the new
        # one — drop them so ``_restore_expansion`` doesn't try to expand
        # /World paths that no longer resolve.
        self._expanded_paths.clear()
        self._selected_items = []
        self._pending_expand_paths.clear()
        self._change_sub = adapter.subscribe_changes(self._on_adapter_event)
        self._item_changed(None)

    def set_rename_controller(self, controller: Any) -> None:
        self._rename_controller = controller

    def set_drop_visual_controller(self, controller: Any) -> None:
        self._drop_visual = controller

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
        """Called when item is dropped on target. Executes reparent wrapped in an undo group."""
        if self._drop_visual is not None:
            self._drop_visual.clear()
        if not isinstance(target_item, HierarchyItem) or not isinstance(source_item, HierarchyItem):
            return
        if self._adapter.can_reparent([source_item.adapter_item], target_item.adapter_item):
            self._adapter.begin_undo_group("Reparent")
            self._adapter.reparent(
                [source_item.adapter_item],
                target_item.adapter_item,
                ReparentPosition.CHILD,
            )
            self._adapter.end_undo_group()

    def get_item_children(self, item: Any) -> list[HierarchyItem]:
        """If item is None, return [root]. Otherwise lazy-load children."""
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
        self._on_adapter_changed(event)

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

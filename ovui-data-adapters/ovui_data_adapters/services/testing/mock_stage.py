# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Mock StageAdapter for development and testing (no USD required).

MockStageAdapter implements every abstract method from StageAdapter using a
fully in-memory prim tree.
"""

from __future__ import annotations

import re
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from ovui_data_adapters.common import (
    AdapterItem,
    BadgeFlags,
    ChangeEvent,
    ChangeEventType,
    ContextManager,
    ItemFlags,
    ReparentPosition,
    StageAdapter,
    VisibilityState,
)

from ovui_data_adapters.services.settings import Subscription


@dataclass
class _MockItem:
    path: str
    name: str
    prim_type: str
    visible: bool = True
    children: List["_MockItem"] = field(default_factory=list)
    parent: Optional["_MockItem"] = field(default=None, repr=False)


# Prim type → icon name registered in StageIcons (Step 13). Mock types
# already use canonical USD spellings, so the map is keyed by display name.
_ICON_MAP = {
    "Mesh": "Mesh",
    "Light": "Light",
    "Camera": "Camera",
    "Scope": "Scope",
    "Xform": "Xform",
}

# Prim type → high-level category for icons and filtering. Mirrors the six
# categories used by the shared data-adapter stage metadata contract.
_TYPE_CATEGORY_MAP = {
    "Mesh": "Mesh",
    "Light": "Light",
    "Camera": "Camera",
    "Xform": "Xform",
    "Scope": "Scope",
}

_NAME_RE = re.compile(r"[^A-Za-z0-9_]")


def _build_default_tree() -> _MockItem:
    root = _MockItem(path="/World", name="World", prim_type="Xform")

    geometry = _MockItem(path="/World/Geometry", name="Geometry", prim_type="Xform", parent=root)
    ground = _MockItem(path="/World/Geometry/Ground", name="Ground", prim_type="Mesh", parent=geometry)
    sphere = _MockItem(path="/World/Geometry/Sphere", name="Sphere", prim_type="Mesh", parent=geometry)
    cube = _MockItem(path="/World/Geometry/Cube", name="Cube", prim_type="Mesh", parent=geometry)
    geometry.children = [ground, sphere, cube]

    lights = _MockItem(path="/World/Lights", name="Lights", prim_type="Xform", parent=root)
    dome = _MockItem(path="/World/Lights/DomeLight", name="DomeLight", prim_type="Light", parent=lights)
    lights.children = [dome]

    camera = _MockItem(path="/World/Camera", name="Camera", prim_type="Camera", parent=root)

    root.children = [geometry, lights, camera]
    return root


def _build_large_tree(prim_count: int) -> _MockItem:
    root = _MockItem(path="/World", name="World", prim_type="Xform")
    for i in range(prim_count):
        child = _MockItem(
            path=f"/World/Prim_{i}",
            name=f"Prim_{i}",
            prim_type="Mesh",
            parent=root,
        )
        root.children.append(child)
    return root


class MockStageAdapter(StageAdapter):
    """In-memory StageAdapter for testing and prototyping.

    Pass prim_count>0 to create a flat tree with N children for perf testing.
    """

    def __init__(self, prim_count: int = 0) -> None:
        self._root = _build_large_tree(prim_count) if prim_count > 0 else _build_default_tree()
        self._subscribers: List[Callable] = []
        self._suppress = False
        # Per-path flag overrides for tests. Paths not in the map default to
        # ``ItemFlags.NONE`` / ``BadgeFlags.NONE``.
        self._item_flags_overrides: dict[str, ItemFlags] = {}
        self._badge_flags_overrides: dict[str, BadgeFlags] = {}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _remove_subscriber(self, key: str, callback: Callable) -> None:
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def _notify(self, event: ChangeEvent) -> None:
        if self._suppress:
            return
        for cb in list(self._subscribers):
            cb(event)

    def _find_by_path(self, path: str, item: Optional[_MockItem] = None) -> Optional[_MockItem]:
        if item is None:
            item = self._root
        if item.path == path:
            return item
        for child in item.children:
            found = self._find_by_path(path, child)
            if found is not None:
                return found
        return None

    def _update_paths(self, item: _MockItem, old_prefix: str, new_prefix: str) -> None:
        item.path = new_prefix + item.path[len(old_prefix):]
        for child in item.children:
            self._update_paths(child, old_prefix, new_prefix)

    # ── Hierarchy ─────────────────────────────────────────────────────────────

    def get_root(self) -> _MockItem:
        return self._root

    def get_children(self, item: AdapterItem) -> List[_MockItem]:
        return list(item.children)

    def can_have_children(self, item: AdapterItem) -> bool:
        return True

    def get_item_path(self, item: AdapterItem) -> str:
        return item.path

    def get_item_at_path(self, path: str) -> Optional[_MockItem]:
        return self._find_by_path(path)

    # ── Display ───────────────────────────────────────────────────────────────

    def get_display_name(self, item: AdapterItem) -> str:
        return item.name

    def get_type_name(self, item: AdapterItem) -> str:
        return item.prim_type

    def get_type_category(self, item: AdapterItem) -> str:
        return _TYPE_CATEGORY_MAP.get(item.prim_type, "Other")

    def get_icon_name(self, item: AdapterItem) -> str:
        return _ICON_MAP.get(item.prim_type, "Prim")

    def get_badge_flags(self, item: AdapterItem) -> BadgeFlags:
        return self._badge_flags_overrides.get(item.path, BadgeFlags.NONE)

    def get_item_flags(self, item: AdapterItem) -> ItemFlags:
        return self._item_flags_overrides.get(item.path, ItemFlags.NONE)

    # ── Visibility ────────────────────────────────────────────────────────────

    def compute_visibility(self, item: AdapterItem) -> VisibilityState:
        if not item.visible:
            return VisibilityState.INVISIBLE
        ancestor = item.parent
        while ancestor is not None:
            if not ancestor.visible:
                return VisibilityState.INHERITED_INVISIBLE
            ancestor = ancestor.parent
        return VisibilityState.VISIBLE

    def set_visibility(self, item: AdapterItem, visible: bool) -> None:
        old_state = self.compute_visibility(item)
        item.visible = visible
        new_state = self.compute_visibility(item)
        # Mirror the product event contract: visibility edits emit the
        # property path plus an adapter-owned semantic delta.
        self._notify(ChangeEvent(
            changed_paths=(f"{item.path}.visibility",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            visibility_delta={
                "authored": (item.path,),
                "boundaries": {item.path: (old_state, new_state)},
            },
        ))

    def can_edit_visibility(self, item: AdapterItem) -> bool:
        flags = self._item_flags_overrides.get(item.path, ItemFlags.NONE)
        return not bool(flags & (ItemFlags.IS_INSTANCE_PROXY | ItemFlags.IS_INACTIVE))

    # ── Rename ────────────────────────────────────────────────────────────────

    def can_rename(self, item: AdapterItem) -> bool:
        return item.parent is not None

    def rename(self, item: AdapterItem, new_name: str) -> str:
        new_name = self.normalize_name(new_name)
        old_path = item.path
        parent_path = item.parent.path if item.parent else ""
        new_path = f"{parent_path}/{new_name}"
        self._update_paths(item, old_path, new_path)
        item.name = new_name
        self._notify(ChangeEvent(
            changed_paths=(),
            resynced_paths=(item.path,),
            event_type=ChangeEventType.RESYNC,
        ))
        return new_name

    def normalize_name(self, name: str) -> str:
        return _NAME_RE.sub("_", name)

    # ── Drag-drop / reparent ──────────────────────────────────────────────────

    def can_reparent(self, items: List[AdapterItem], new_parent: AdapterItem) -> bool:
        for item in items:
            if item is new_parent:
                return False
            ancestor = new_parent
            while ancestor is not None:
                if ancestor is item:
                    return False
                ancestor = ancestor.parent
        return True

    def reparent(
        self,
        items: List[AdapterItem],
        new_parent: AdapterItem,
        position: ReparentPosition,
    ) -> None:
        for item in items:
            old_parent = item.parent
            if old_parent is not None:
                old_parent.children.remove(item)
            old_path = item.path
            new_path = f"{new_parent.path}/{item.name}"
            self._update_paths(item, old_path, new_path)
            item.parent = new_parent
            new_parent.children.append(item)
        self._notify(ChangeEvent(
            changed_paths=(),
            resynced_paths=tuple(item.path for item in items),
            event_type=ChangeEventType.RESYNC,
        ))

    # ── Filter ────────────────────────────────────────────────────────────────

    def filter_items(
        self,
        items: List[AdapterItem],
        predicate: Callable[[AdapterItem], bool],
    ) -> List[AdapterItem]:
        return [item for item in items if predicate(item)]

    # ── Change notifications ──────────────────────────────────────────────────

    def subscribe_changes(self, callback: Callable[[ChangeEvent], None]) -> Subscription:
        self._subscribers.append(callback)
        return Subscription(weakref.ref(self), "changes", callback)

    # ── Undo integration ──────────────────────────────────────────────────────

    def begin_undo_group(self, label: str) -> None:
        pass

    def end_undo_group(self) -> None:
        pass

    # ── Notification suppression ──────────────────────────────────────────────

    @contextmanager
    def suppress_change_notifications(self) -> ContextManager:
        old = self._suppress
        self._suppress = True
        try:
            yield
        finally:
            self._suppress = old

    # ── World AABB / framing / bound-camera (Step 7 plan §7) ──────────────────
    #
    # Deterministic stubs for tests / mock use. Real bbox/framing/bound-camera
    # behavior lives in concrete USD adapters; the mock returns a unit cube for
    # bbox queries and ``None`` for the bound-camera (no scene metadata).

    def compute_world_aabb(self, paths):
        return ((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))

    def compute_prim_world_aabb_with_extent_fallback(self, path):
        return ((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))

    def read_bound_camera(self):
        return None

    # ── Test helpers ──────────────────────────────────────────────────────────

    def add_child(self, parent_path: str, name: str, prim_type: str) -> _MockItem:
        parent = self._find_by_path(parent_path)
        if parent is None:
            raise ValueError(f"No item at path: {parent_path}")
        new_item = _MockItem(
            path=f"{parent_path}/{name}",
            name=name,
            prim_type=prim_type,
            parent=parent,
        )
        parent.children.append(new_item)
        self._notify(ChangeEvent(
            changed_paths=(),
            resynced_paths=(new_item.path,),
            event_type=ChangeEventType.RESYNC,
        ))
        return new_item

    def remove(self, path: str) -> None:
        item = self._find_by_path(path)
        if item is None:
            return
        if item.parent is not None:
            item.parent.children.remove(item)
        item.parent = None
        self._notify(ChangeEvent(
            changed_paths=(),
            resynced_paths=(path,),
            event_type=ChangeEventType.RESYNC,
        ))

    def fire_change(self, paths: List[str]) -> None:
        self._notify(ChangeEvent(
            changed_paths=tuple(paths),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        ))

    def set_default(self, path: str) -> None:
        """Mark ``path`` as the default prim and fire an INFO_CHANGE event.

        Clears the ``IS_DEFAULT_PRIM`` flag on any previously-default path so
        the adapter always exposes at most one default prim (matching
        ``UsdStage.SetDefaultPrim`` semantics).
        """
        if self._find_by_path(path) is None:
            raise ValueError(f"No item at path: {path}")
        changed_paths: list[str] = []
        for existing_path, flags in list(self._item_flags_overrides.items()):
            if flags & ItemFlags.IS_DEFAULT_PRIM:
                new_flags = flags & ~ItemFlags.IS_DEFAULT_PRIM
                if new_flags == ItemFlags.NONE:
                    del self._item_flags_overrides[existing_path]
                else:
                    self._item_flags_overrides[existing_path] = new_flags
                changed_paths.append(existing_path)
        current = self._item_flags_overrides.get(path, ItemFlags.NONE)
        self._item_flags_overrides[path] = current | ItemFlags.IS_DEFAULT_PRIM
        changed_paths.append(path)
        self._notify(ChangeEvent(
            changed_paths=tuple(changed_paths),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        ))

    def set_item_flags(self, path: str, flags: ItemFlags) -> None:
        """Replace the ``ItemFlags`` exposed for ``path`` and fire a change event."""
        if self._find_by_path(path) is None:
            raise ValueError(f"No item at path: {path}")
        if flags == ItemFlags.NONE:
            self._item_flags_overrides.pop(path, None)
        else:
            self._item_flags_overrides[path] = flags
        self._notify(ChangeEvent(
            changed_paths=(path,),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        ))

    def set_badge_flags(self, path: str, flags: BadgeFlags) -> None:
        """Replace the ``BadgeFlags`` exposed for ``path`` and fire a change event."""
        if self._find_by_path(path) is None:
            raise ValueError(f"No item at path: {path}")
        if flags == BadgeFlags.NONE:
            self._badge_flags_overrides.pop(path, None)
        else:
            self._badge_flags_overrides[path] = flags
        self._notify(ChangeEvent(
            changed_paths=(path,),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        ))

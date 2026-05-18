# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""USD-backed StageAdapter wrapping a Usd.Stage.

Hierarchy traversal from Step 22; Step 23 adds visibility edits,
rename/reparent (all undoable via UndoManager), and change notifications.
"""

from __future__ import annotations

import contextlib
import re
import weakref
from typing import Any, Callable, List, Optional

try:
    from pxr import Sdf, Tf, Usd, UsdGeom
    try:
        from pxr import UsdRender
    except ImportError:
        UsdRender = None  # type: ignore[assignment]
    HAS_USD = True
except ImportError:
    HAS_USD = False
    Usd = Sdf = Tf = UsdGeom = UsdRender = None  # type: ignore[assignment]

from ovui_data_adapters.common import (
    AdapterItem,
    BadgeFlags,
    BoundCameraPose,
    ChangeEvent,
    ChangeEventType,
    ContextManager,
    ItemFlags,
    ReparentPosition,
    StageAdapter,
    StageChoice,
    SubscriptionProtocol,
    VisibilityState,
)


def _is_live_prim(item: Any) -> bool:
    """Return ``True`` iff ``item`` is a live ``Usd.Prim`` reference.

    The Stage tree model captures ``Usd.Prim`` handles when it builds
    rows; deleting a prim (e.g. ``DeletePrimCommand`` or any other
    ``Sdf.BatchNamespaceEdit``-Apply) invalidates those handles a few
    frames before the model rebuilds. Any subsequent attribute access
    on the expired handle raises ``RuntimeError: Accessed invalid
    expired '<name>' prim`` (or ``Accessed invalid null prim`` when
    the handle never resolved). The Stage delegate calls into adapter
    methods like ``get_children`` / ``get_type_category`` /
    ``can_edit_visibility`` from per-frame ``build_branch`` /
    ``build_widget`` / ``can_toggle_now`` — those must short-circuit
    on stale prims and return safe defaults so the delegate frame
    completes without raising. Codex final-UI-QA rerun (2026-05-08)
    captured this regression on `tests/data/simple_scene.usda` →
    `/World/Cube` after the Delete-key path.
    """
    if item is None:
        return False
    is_valid = getattr(item, "IsValid", None)
    if is_valid is None:
        # Not a USD object — caller passed something else (e.g. a
        # path string in a test). Treat as live so we don't suppress
        # useful errors elsewhere.
        return True
    try:
        return bool(is_valid())
    except Exception:
        # An expired ``Usd.Prim`` may itself raise on ``IsValid()``
        # in pathological cases. Treat any exception as "not live".
        return False


def _choice_for_prim(prim: Any) -> StageChoice:
    path = str(prim.GetPath())
    return StageChoice(path=path, display_name=path)


def _is_transform_property_name(name: str) -> bool:
    return name == "xformOpOrder" or name.startswith("xformOp:")


class _StageSubscription:
    """Private subscription handle for ``UsdStageAdapter.subscribe_changes``.

    Step 13: replaces the prior dependency on
    ``ovwidgets.common.settings.Subscription`` so the moved openusd
    stage adapter carries zero ``ovwidgets.*`` runtime imports.
    Structurally satisfies :class:`SubscriptionProtocol` from
    :mod:`ovui_data_adapters.common` — a no-arg ``cancel()`` method is
    the only required surface.
    """

    def __init__(
        self,
        owner_ref: "weakref.ref[Any]",
        key: str,
        callback: Callable,
    ) -> None:
        self._owner_ref = owner_ref
        self._key = key
        self._callback = callback
        self._cancelled = False

    def cancel(self) -> None:
        """Remove this subscriber from the owning adapter."""
        if self._cancelled:
            return
        self._cancelled = True
        owner = self._owner_ref()
        if owner is not None:
            owner._remove_subscriber(self._key, self._callback)

    def __del__(self) -> None:
        self.cancel()


_NAME_RE = re.compile(r"[^A-Za-z0-9_]")

# Lowercase USD schema type name → icon name registered in StageIcons.
# Concrete light/mesh types resolve to their own icon keys so StageIcons can
# ship per-type artwork; unmapped types fall back to the "Prim" default at
# lookup time (Step 13 wires the real registration).
_ICON_MAP: dict[str, str] = {
    "mesh": "Mesh",
    "sphere": "Mesh", "cube": "Mesh", "cone": "Mesh", "cylinder": "Mesh",
    "capsule": "Mesh", "plane": "Mesh",
    "basiscurves": "Mesh", "points": "Mesh",
    "nurbscurves": "Mesh", "nurbspatch": "Mesh",
    "camera": "Camera",
    "distantlight": "DistantLight",
    "domelight": "DomeLight",
    "spherelight": "SphereLight",
    "rectlight": "RectLight",
    "disklight": "DiskLight",
    "cylinderlight": "CylinderLight",
    "scope": "Scope",
    "xform": "Xform",
}

# Lowercase USD schema type name → high-level display category. Categories
# drive icon choice and filter grouping; type labels themselves stay visually
# neutral. Keep these values in sync with
# ``ovui_data_adapters.common.adapters._DEFAULT_TYPE_CATEGORY_MAP``.
_TYPE_CATEGORY_MAP: dict[str, str] = {
    "sphere": "Mesh",
    "cube": "Mesh",
    "cone": "Mesh",
    "cylinder": "Mesh",
    "capsule": "Mesh",
    "plane": "Mesh",
    "basiscurves": "Mesh",
    "points": "Mesh",
    "nurbscurves": "Mesh",
    "nurbspatch": "Mesh",
    "mesh": "Mesh",
    "domelight": "Light",
    "distantlight": "Light",
    "disklight": "Light",
    "rectlight": "Light",
    "spherelight": "Light",
    "cylinderlight": "Light",
    "camera": "Camera",
    "xform": "Xform",
    "scope": "Scope",
}


class UsdStageAdapter(StageAdapter):
    """USD-backed StageAdapter. Wraps a Usd.Stage.

    Pass an UndoManager to make visibility, rename, and reparent operations
    undoable. If undo_manager is None, operations execute directly.
    """

    def __init__(self, stage: Any, undo_manager: Any = None, call_later: Any = None) -> None:
        self._stage = stage
        self._undo_manager = undo_manager
        self._subscribers: List[Callable] = []
        self._suppressed = False
        self._call_later = call_later

        # Tf.Notice batching state
        self._pending_changed: set = set()
        self._pending_resynced: set = set()
        self._pending_sources: set[Optional[str]] = set()
        self._pending_default_change: Optional[tuple[Optional[str], Optional[str]]] = None
        self._flush_scheduled = False
        self._in_mutation = False  # True while _push() is executing
        self._current_notice_source: Optional[str] = None

        # Cached default-prim path so get_item_flags() is O(1) per call;
        # refreshed on every LAYER_INFO event.
        self._default_prim_path: Optional[str] = self._compute_default_prim_path()

        if HAS_USD:
            self._notice_key = Tf.Notice.Register(
                Usd.Notice.ObjectsChanged,
                self._on_notice,
                self._stage,
            )
            self._layer_notice_key = Tf.Notice.Register(
                Sdf.Notice.LayerInfoDidChange,
                self._on_layer_info,
                self._stage.GetRootLayer(),
            )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _remove_subscriber(self, key: str, callback: Callable) -> None:
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def _notify(self, event: ChangeEvent) -> None:
        if self._suppressed:
            return
        for cb in list(self._subscribers):
            cb(event)

    def _on_notice(self, notice: Any, sender: Any) -> None:
        if self._suppressed or self._in_mutation:
            return
        received_paths = False
        for path in notice.GetResyncedPaths():
            self._pending_resynced.add(str(path))
            received_paths = True
        for path in notice.GetChangedInfoOnlyPaths():
            self._pending_changed.add(str(path))
            received_paths = True
        if received_paths:
            self._pending_sources.add(self._current_notice_source)
        if (self._pending_changed or self._pending_resynced) and not self._flush_scheduled:
            self._flush_scheduled = True
            self._schedule_flush()

    def _compute_default_prim_path(self) -> Optional[str]:
        if not HAS_USD or self._stage is None:
            return None
        if not self._stage.HasDefaultPrim():
            return None
        prim = self._stage.GetDefaultPrim()
        if not prim or not prim.IsValid():
            return None
        return str(prim.GetPath())

    def _on_layer_info(self, notice: Any, sender: Any) -> None:
        if self._suppressed or self._in_mutation:
            return
        new_default = self._compute_default_prim_path()
        if new_default == self._default_prim_path:
            return
        old_default = self._default_prim_path
        if self._pending_default_change is None:
            self._pending_default_change = (old_default, new_default)
        else:
            # Coalesce: keep the original old value, update to newest target.
            self._pending_default_change = (self._pending_default_change[0], new_default)
        if not self._flush_scheduled:
            self._flush_scheduled = True
            self._schedule_flush()

    def _schedule_flush(self) -> None:
        # Production Application injects a ``call_later`` (drain hook); bare
        # tests with no scheduler get a synchronous flush. Step 13 simplified
        # this from a lazy ``ovwidgets.common.scheduler`` import to keep the
        # moved openusd file free of ``ovwidgets.*`` runtime imports.
        if self._call_later is not None:
            self._call_later(0.0, self._flush)
        else:
            self._flush()

    def _flush(self) -> None:
        self._flush_scheduled = False
        pending_default = self._pending_default_change
        self._pending_default_change = None

        if self._pending_changed or self._pending_resynced:
            source = self._pending_event_source()
            event_type = ChangeEventType.RESYNC if self._pending_resynced else ChangeEventType.INFO_CHANGE
            event = ChangeEvent(
                changed_paths=tuple(sorted(self._pending_changed)),
                resynced_paths=tuple(sorted(self._pending_resynced)),
                event_type=event_type,
                source=source,
            )
            self._pending_changed.clear()
            self._pending_resynced.clear()
            self._pending_sources.clear()
            self._notify(event)

        if pending_default is not None:
            old_default, new_default = pending_default
            self._default_prim_path = new_default
            changed = tuple(p for p in (old_default, new_default) if p)
            self._notify(ChangeEvent(
                changed_paths=changed,
                resynced_paths=(),
                event_type=ChangeEventType.LAYER_INFO,
            ))

    def _pending_event_source(self) -> Optional[str]:
        if len(self._pending_sources) != 1:
            return None
        source = next(iter(self._pending_sources))
        return source or None

    def _push(self, cmd: Any) -> None:
        """Push cmd to undo_manager (which calls do()), or call do() directly.

        Sets _in_mutation to suppress Tf.Notice collection; adapter methods fire
        their own synchronous notifications instead.
        """
        self._in_mutation = True
        try:
            if self._undo_manager is not None:
                self._undo_manager.push(cmd)
            else:
                cmd.do()
        finally:
            self._in_mutation = False

    @property
    def stage(self) -> Any:
        return self._stage

    # ── Hierarchy ─────────────────────────────────────────────────────────────

    def get_root(self) -> AdapterItem:
        return self._stage.GetPseudoRoot()

    def get_children(self, item: AdapterItem) -> List[AdapterItem]:
        # Deleting a prim invalidates ``Usd.Prim`` references that the
        # Stage tree model captured a frame ago. Returning ``[]`` for
        # an expired/null prim lets the row drain through the next
        # notice flush without raising ``RuntimeError: Accessed invalid
        # ... prim``. Codex final-UI-QA rerun (2026-05-08) hit this on
        # `/World/Cube` after Delete.
        if not _is_live_prim(item):
            return []
        return list(item.GetChildren())

    def can_have_children(self, item: AdapterItem) -> bool:
        return True

    def get_item_path(self, item: AdapterItem) -> str:
        return str(item.GetPath())

    def get_item_at_path(self, path: str) -> Optional[AdapterItem]:
        prim = self._stage.GetPrimAtPath(Sdf.Path(path))
        return prim if prim.IsValid() else None

    # ── Display ───────────────────────────────────────────────────────────────

    def get_display_name(self, item: AdapterItem) -> str:
        name = item.GetName()
        return name if name else "/"

    def get_type_name(self, item: AdapterItem) -> str:
        raw = str(item.GetTypeName())
        if raw:
            return raw
        # Empty typeName: USD class prims carry no schema type, so the Type
        # column shows "Class". Non-class prims with an empty typeName (most
        # commonly the pseudo-root and raw ``over`` specs) render blank.
        get_specifier = getattr(item, "GetSpecifier", None)
        if get_specifier is not None and get_specifier() == Sdf.SpecifierClass:
            return "Class"
        return ""

    def get_type_category(self, item: AdapterItem) -> str:
        if not _is_live_prim(item):
            return "Other"
        raw = str(item.GetTypeName()).lower()
        if not raw:
            return "Other"
        return _TYPE_CATEGORY_MAP.get(raw, "Other")

    def get_icon_name(self, item: AdapterItem) -> str:
        raw = str(item.GetTypeName()).lower()
        if not raw:
            return "Prim"
        return _ICON_MAP.get(raw, "Prim")

    def get_badge_flags(self, item: AdapterItem) -> BadgeFlags:
        flags = BadgeFlags.NONE
        if item.HasAuthoredReferences():
            flags |= BadgeFlags.REFERENCE
        if item.HasAuthoredPayloads():
            flags |= BadgeFlags.PAYLOAD
        if item.IsInstanceable():
            flags |= BadgeFlags.INSTANCE
        if item.HasAuthoredInherits():
            flags |= BadgeFlags.INHERITS
        if item.HasAuthoredSpecializes():
            flags |= BadgeFlags.SPECIALIZES
        return flags

    def get_item_flags(self, item: AdapterItem) -> ItemFlags:
        flags = ItemFlags.NONE
        if item.IsInstanceProxy():
            flags |= ItemFlags.IS_INSTANCE_PROXY
        if item.IsAbstract():
            flags |= ItemFlags.IS_ABSTRACT
        if not item.IsActive():
            flags |= ItemFlags.IS_INACTIVE
        specifier = item.GetSpecifier()
        if specifier == Sdf.SpecifierOver:
            flags |= ItemFlags.IS_OVER
        elif specifier == Sdf.SpecifierClass:
            flags |= ItemFlags.IS_CLASS
        if (
            self._default_prim_path is not None
            and str(item.GetPath()) == self._default_prim_path
        ):
            flags |= ItemFlags.IS_DEFAULT_PRIM
        # TODO(live-session): IS_OUTDATED / IS_IN_LIVE_SESSION / HAS_MISSING_REFS
        # require omni.kit.usd.layers, which is unavailable in the standalone build.
        return flags

    # ── Visibility ────────────────────────────────────────────────────────────

    def compute_visibility(self, item: AdapterItem) -> VisibilityState:
        if item.GetPath() == Sdf.Path.absoluteRootPath:
            return VisibilityState.VISIBLE
        imageable = UsdGeom.Imageable(item)
        if not imageable:
            return VisibilityState.VISIBLE
        vis_attr = imageable.GetVisibilityAttr()
        # Explicitly invisible: authored value is 'invisible'
        if vis_attr.HasAuthoredValue() and vis_attr.Get() == UsdGeom.Tokens.invisible:
            return VisibilityState.INVISIBLE
        # Inherited invisible: effective visibility is invisible but not authored here
        computed = imageable.ComputeVisibility()
        if computed == UsdGeom.Tokens.invisible:
            return VisibilityState.INHERITED_INVISIBLE
        return VisibilityState.VISIBLE

    def set_visibility(self, item: AdapterItem, visible: bool) -> None:
        if not self.can_edit_visibility(item):
            raise ValueError(f"Visibility is not editable for {item.GetPath()}")
        from ovui_data_adapters.openusd import SetVisibilityCommand
        cmd = SetVisibilityCommand(item, visible)
        self._push(cmd)
        self._notify(ChangeEvent(
            changed_paths=(str(item.GetPath()),),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        ))

    def can_edit_visibility(self, item: AdapterItem) -> bool:
        if not _is_live_prim(item):
            return False
        if item.GetPath() == Sdf.Path.absoluteRootPath:
            return False
        if item.IsInstanceProxy():
            return False
        if not item.IsActive():
            return False
        return bool(UsdGeom.Imageable(item))

    # ── Rename ────────────────────────────────────────────────────────────────

    def can_rename(self, item: AdapterItem) -> bool:
        if item.GetPath() == Sdf.Path.absoluteRootPath:
            return False
        if item.IsInstanceProxy():
            return False
        return True

    def rename(self, item: AdapterItem, new_name: str) -> str:
        from ovui_data_adapters.openusd import NamespaceEditCommand
        old_path = item.GetPath()
        new_path = old_path.GetParentPath().AppendChild(new_name)
        layer = self._stage.GetEditTarget().GetLayer()
        cmd = NamespaceEditCommand(layer, old_path, new_path)
        self._push(cmd)
        self._notify(ChangeEvent(
            changed_paths=(),
            resynced_paths=(str(new_path),),
            event_type=ChangeEventType.RESYNC,
        ))
        return new_name

    def normalize_name(self, name: str) -> str:
        return _NAME_RE.sub("_", name)

    # ── Drag-drop / reparent ──────────────────────────────────────────────────

    def can_reparent(self, items: List[AdapterItem], new_parent: AdapterItem) -> bool:
        new_parent_path = new_parent.GetPath()
        for item in items:
            item_path = item.GetPath()
            # Cannot reparent into self
            if item_path == new_parent_path:
                return False
            # Cannot reparent into a descendant of the item
            if new_parent_path.HasPrefix(item_path):
                return False
        return True

    def reparent(
        self,
        items: List[AdapterItem],
        new_parent: AdapterItem,
        position: ReparentPosition,
    ) -> None:
        from ovui_data_adapters.openusd import NamespaceEditCommand
        layer = self._stage.GetEditTarget().GetLayer()

        if position == ReparentPosition.CHILD:
            target_parent_path = new_parent.GetPath()
        else:
            # BEFORE/AFTER: place alongside new_parent in its parent
            target_parent_path = new_parent.GetPath().GetParentPath()

        moved_paths = []
        for item in items:
            old_path = item.GetPath()
            new_path = target_parent_path.AppendChild(old_path.name)
            moved_paths.append(str(new_path))
            cmd = NamespaceEditCommand(layer, old_path, new_path)
            self._push(cmd)

        self._notify(ChangeEvent(
            changed_paths=(),
            resynced_paths=tuple(moved_paths),
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

    def subscribe_changes(self, callback: Callable[[ChangeEvent], None]) -> SubscriptionProtocol:
        self._subscribers.append(callback)
        return _StageSubscription(weakref.ref(self), "changes", callback)

    def notify_transform_changed(
        self,
        paths: List[str],
        source: Optional[str] = None,
    ) -> None:
        """Emit an explicit transform event after suppressed viewport edits."""
        changed: list[str] = []
        seen: set[str] = set()
        for path in paths:
            for changed_path in self._transform_change_paths(path):
                if changed_path in seen:
                    continue
                seen.add(changed_path)
                changed.append(changed_path)
        if not changed:
            return
        self._notify(ChangeEvent(
            changed_paths=tuple(changed),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            source=source,
        ))

    def _transform_change_paths(self, path: str) -> list[str]:
        try:
            sdf_path = Sdf.Path(path)
            prim_path = sdf_path.GetPrimPath() if sdf_path.IsPropertyPath() else sdf_path
            prim = self._stage.GetPrimAtPath(prim_path)
        except Exception:
            return [str(path)]
        if not prim or not prim.IsValid():
            return [str(prim_path)]
        changed = [
            f"{prim_path}.{attr.GetName()}"
            for attr in prim.GetAttributes()
            if _is_transform_property_name(attr.GetName())
        ]
        return changed or [str(prim_path)]

    # ── Undo integration ──────────────────────────────────────────────────────

    def begin_undo_group(self, label: str) -> None:
        if self._undo_manager is not None:
            self._undo_manager.begin_group(label)

    def end_undo_group(self) -> None:
        if self._undo_manager is not None:
            self._undo_manager.end_group()

    # ── Notification suppression ──────────────────────────────────────────────

    @contextlib.contextmanager
    def suppress_change_notifications(self) -> ContextManager:
        old = self._suppressed
        self._suppressed = True
        try:
            yield
        finally:
            self._suppressed = old

    # ── World AABB / framing / bound-camera (Step 7 plan §7) ──────────────────
    #
    # Relocated verbatim from ``ovwidgets/viewport/viewport_widget.py`` so the
    # widget's inline pxr code can be replaced by abstract calls in Step 17.
    # Until then the widget keeps its own inline copies and these methods
    # mirror the same logic.

    @staticmethod
    def _prims_to_bound(stage: Any, path: str) -> List[Any]:
        """Return the list of prims whose bounds union for ``path``.

        Mirrors :meth:`ViewportWidget._prims_to_bound`: the pseudo-root
        ``"/"`` returns its top-level children (``BBoxCache.ComputeWorldBound``
        on the pseudo-root yields an empty bound because it isn't an
        Imageable prim); every other path returns the single prim at that
        path when valid.
        """
        if path == "/":
            pseudo_root = stage.GetPseudoRoot()
            return [child for child in pseudo_root.GetChildren() if child.IsValid()]
        prim = stage.GetPrimAtPath(path)
        return [prim] if prim.IsValid() else []

    def compute_world_aabb(self, paths: List[str]):
        """Combined world AABB across ``paths``; ``None`` if empty.

        Relocates the BBoxCache iteration from
        ``ViewportWidget.frame_paths`` (lines ~1207-1227) verbatim. Returns
        the same ``((min_xyz), (max_xyz))`` tuple shape the inline code
        produces today; ``None`` when ``paths`` is empty, the stage is
        unavailable, or no prim contributes a non-empty bound.
        """
        if not paths or not HAS_USD or self._stage is None:
            return None
        try:
            from pxr import Gf, UsdGeom
            stage = self._stage
            bbox_cache = UsdGeom.BBoxCache(
                stage.GetTimeCode() if hasattr(stage, "GetTimeCode") else 0,
                [UsdGeom.Tokens.default_],
            )
            total = Gf.BBox3d()
            for path in paths:
                prims = self._prims_to_bound(stage, path)
                for prim in prims:
                    total = Gf.BBox3d.Combine(
                        total, bbox_cache.ComputeWorldBound(prim)
                    )
            rng = total.ComputeAlignedRange()
            if rng.IsEmpty():
                return None
            minp = rng.GetMin()
            maxp = rng.GetMax()
            return (
                (float(minp[0]), float(minp[1]), float(minp[2])),
                (float(maxp[0]), float(maxp[1]), float(maxp[2])),
            )
        except Exception:
            return None

    def compute_prim_world_aabb_with_extent_fallback(self, path: str):
        """Two-tier world AABB for one prim: ``Boundable`` extent → ``BBoxCache``.

        Relocates :meth:`ViewportWidget._compute_world_bbox` verbatim
        (lines ~1100-1159). For :class:`UsdGeom.Boundable` prims, prefers
        ``Boundable.ComputeExtentFromPlugins`` so a Property-panel
        ``radius`` / ``size`` edit invalidates the cached ``extent``
        attribute correctly; falls back to ``UsdGeom.BBoxCache`` for
        non-Boundable selections (Xforms, Scopes). Returns ``None`` for
        invalid paths or any error.
        """
        if not HAS_USD or self._stage is None:
            return None
        try:
            from pxr import Gf, Usd, UsdGeom
            stage = self._stage
            prim = stage.GetPrimAtPath(path)
            if not prim.IsValid():
                return None
            tc = Usd.TimeCode.Default()
            rng = None
            if prim.IsA(UsdGeom.Boundable):
                boundable = UsdGeom.Boundable(prim)
                local_extent = UsdGeom.Boundable.ComputeExtentFromPlugins(
                    boundable, tc
                )
                if local_extent:
                    ltow = UsdGeom.Imageable(prim).ComputeLocalToWorldTransform(tc)
                    local_range = Gf.Range3d(
                        Gf.Vec3d(local_extent[0]),
                        Gf.Vec3d(local_extent[1]),
                    )
                    world_bbox = Gf.BBox3d(local_range, ltow)
                    rng = world_bbox.ComputeAlignedRange()
            if rng is None or rng.IsEmpty():
                bcache = UsdGeom.BBoxCache(tc, [UsdGeom.Tokens.default_])
                bbox = bcache.ComputeWorldBound(prim)
                rng = bbox.ComputeAlignedRange()
            if rng.IsEmpty():
                return None
            minp = rng.GetMin()
            maxp = rng.GetMax()
            return (
                (float(minp[0]), float(minp[1]), float(minp[2])),
                (float(maxp[0]), float(maxp[1]), float(maxp[2])),
            )
        except Exception:
            return None

    def read_bound_camera(self):
        """Return the stage's authored ``boundCamera`` pose, or ``None``.

        Delegates to
        :func:`ovui_data_adapters.openusd.bound_camera.read_bound_camera`
        — the parser was relocated in Step 13 of the plan.
        """
        if self._stage is None:
            return None
        try:
            from ovui_data_adapters.openusd.bound_camera import read_bound_camera
            return read_bound_camera(self._stage)
        except Exception:
            return None

    def list_cameras(self) -> List[StageChoice]:
        """Return selectable ``UsdGeom.Camera`` prims in stage traversal order."""
        if not HAS_USD or self._stage is None:
            return []
        return [
            _choice_for_prim(prim)
            for prim in self._stage.Traverse()
            if prim.IsValid() and prim.IsA(UsdGeom.Camera)
        ]

    def read_camera_pose(self, path: str) -> Optional[BoundCameraPose]:
        """Return a viewport pose for the camera prim at ``path``."""
        if self._stage is None:
            return None
        try:
            from ovui_data_adapters.openusd.bound_camera import read_camera_pose
            return read_camera_pose(self._stage, path)
        except Exception:
            return None

    def write_camera_pose_from_matrices(
        self,
        path: str,
        view_matrix: Any,
        proj_matrix: Any,
        width: int,
        height: int,
        target_world: Any,
        source: Optional[str] = None,
        undoable: bool = True,
    ) -> bool:
        """Author the selected USD camera pose from viewport navigation.

        ``proj_matrix``/``width``/``height`` are accepted for parity with the
        renderer camera writer. Navigation edits only change pose here: lens
        and clipping attributes remain as the user's camera authored them.
        ``source`` is carried onto the resulting ``ChangeEvent`` when the USD
        notice batch contains only this write's camera changes. ``undoable``
        controls whether this single final pose write joins the UndoManager.
        """
        if self._stage is None:
            return False
        try:
            from ovui_data_adapters.openusd.commands import CameraPoseCommand

            command = CameraPoseCommand(
                self._stage,
                path,
                view_matrix,
                (
                    float(target_world[0]),
                    float(target_world[1]),
                    float(target_world[2]),
                ),
            )
            previous_source = self._current_notice_source
            self._current_notice_source = source
            try:
                if undoable and self._undo_manager is not None:
                    self._undo_manager.push(command)
                else:
                    command.do()
            finally:
                self._current_notice_source = previous_source
        except Exception:
            return False
        return True

    def list_render_products(self) -> List[StageChoice]:
        """Return selectable ``UsdRender.Product`` prims in stage traversal order."""
        if not HAS_USD or self._stage is None or UsdRender is None:
            return []
        return [
            _choice_for_prim(prim)
            for prim in self._stage.Traverse()
            if prim.IsValid() and prim.IsA(UsdRender.Product)
        ]

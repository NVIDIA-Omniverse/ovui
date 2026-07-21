# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Stage adapter scaffold for the registered ovstage provider."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
import math
import struct
import sys
from typing import Any, Callable, Iterable, List, Optional

from ovui_data_adapters.common import (
    AABB,
    AdapterItem,
    BadgeFlags,
    BoundCameraPose,
    BindMaterialRequest,
    BindMaterialResult,
    ChangeEvent,
    Command,
    CoreMaterialErrorCode,
    ContextManager,
    CoreMaterialsAdapter,
    CreateActionCatalog,
    CreateActionCategory,
    CreateActionCategoryDescriptor,
    CreateActionDescriptor,
    CreateActionErrorCode,
    CreateActionRequirement,
    CreateActionWarning,
    CreateActionWarningSeverity,
    CreateActionsAdapter,
    CreatePlacementPolicy,
    CreateRequest,
    CreateResult,
    CreateSelectionPolicy,
    ItemFlags,
    ReparentPosition,
    RenderTargetCatalog,
    RenderTargetDescriptor,
    RenderTargetKind,
    RenderTargetOutputKind,
    RenderTargetWarning,
    StageAdapter,
    StageChoice,
    SubscriptionProtocol,
    VisibilityState,
)

from ovui_data_adapters.common._command import clear_history_consistent
from ovui_data_adapters.ovstage._catalog import native_catalog_snapshot
from ovui_data_adapters.ovstage._authoring import (
    MISSING,
    NativeValueDescriptor,
    NativeValueEditCommand,
)
from ovui_data_adapters.ovstage._errors import raise_not_ready
from ovui_data_adapters.ovstage._native import read_matrix_attribute
from ovui_data_adapters.ovstage._native import read_population_up_axis
from ovui_data_adapters.ovstage._native import read_token_attribute
from ovui_data_adapters.ovstage._native import resolve_query_names
from ovui_data_adapters.ovstage._native import resolve_token_id
from ovui_data_adapters.ovstage._structural import (
    NativeCreatePrimsCommand,
    NativeMovePrimsCommand,
)
from ovui_data_adapters.ovstage._stage_write import (
    supports_native_stage_writes,
    write_token_attribute,
)


_ROOT_PATH = "/"
_ROOT_QUERY_PATH = ""
_VISIBILITY_ATTR = "visibility"
_VISIBILITY_INHERITED = "inherited"
_VISIBILITY_INVISIBLE = "invisible"
_VISIBILITY_TOKENS = frozenset({_VISIBILITY_INHERITED, _VISIBILITY_INVISIBLE})
_PURPOSE_ATTR = "purpose"
_PURPOSE_DEFAULTS = frozenset({"default", "geometry"})
_DLPACK_FLOAT = 2
_BOUND_CAMERA_FOV_DEGREES = 45.0
_BOUND_CAMERA_MIN_RADIUS = 1.0
_BOUND_CAMERA_DISTANCE_SCALE = 4.0
_BOUND_CAMERA_MIN_DISTANCE = 4.0
_BOUND_CAMERA_EYE_OFFSET = (0.75, 0.45, 1.0)
_BOUND_CAMERA_PRIM_PATH = "ovstage:computed-bound-camera"
_CONDITIONAL_RUNTIME_ROOTS = (
    "/TempChangeTracking",
    "/omni_rtx_loadingStatePrim",
    "/Render",
)
_KNOWN_INTERNAL_ROOTS = frozenset(
    {
        "/TempChangeTracking",
        "/omni_rtx_loadingStatePrim",
        "/__ovstage_population_stage_info__",
        "/__Fabric_StageInfo",
    }
)


@dataclass(frozen=True)
class _NativeCreateSpec:
    action_id: str
    label: str
    category: CreateActionCategory
    type_name: str
    kind: str
    order: float
    default_name: str
    default_parent: str = "/World"
    enabled: bool = True
    disabled_reason: str = ""


_NATIVE_CREATE_SPECS: tuple[_NativeCreateSpec, ...] = (
    _NativeCreateSpec("create.geometry.mesh.cone", "Cone", CreateActionCategory.MESH, "Mesh", "mesh", 0, "Cone"),
    _NativeCreateSpec("create.geometry.mesh.cube", "Cube", CreateActionCategory.MESH, "Mesh", "mesh", 10, "Cube"),
    _NativeCreateSpec("create.geometry.mesh.cylinder", "Cylinder", CreateActionCategory.MESH, "Mesh", "mesh", 20, "Cylinder"),
    _NativeCreateSpec("create.geometry.mesh.disk", "Disk", CreateActionCategory.MESH, "Mesh", "mesh", 30, "Disk"),
    _NativeCreateSpec("create.geometry.mesh.plane", "Plane", CreateActionCategory.MESH, "Mesh", "mesh", 40, "Plane"),
    _NativeCreateSpec("create.geometry.mesh.sphere", "Sphere", CreateActionCategory.MESH, "Mesh", "mesh", 50, "Sphere"),
    _NativeCreateSpec("create.geometry.mesh.torus", "Torus", CreateActionCategory.MESH, "Mesh", "mesh", 60, "Torus"),
    _NativeCreateSpec("create.geometry.shape.capsule", "Capsule", CreateActionCategory.SHAPE, "Capsule", "shape", 0, "Capsule"),
    _NativeCreateSpec("create.geometry.shape.cone", "Cone", CreateActionCategory.SHAPE, "Cone", "shape", 10, "Cone"),
    _NativeCreateSpec("create.geometry.shape.cube", "Cube", CreateActionCategory.SHAPE, "Cube", "shape", 20, "Cube"),
    _NativeCreateSpec("create.geometry.shape.cylinder", "Cylinder", CreateActionCategory.SHAPE, "Cylinder", "shape", 30, "Cylinder"),
    _NativeCreateSpec("create.geometry.shape.sphere", "Sphere", CreateActionCategory.SHAPE, "Sphere", "shape", 40, "Sphere"),
    _NativeCreateSpec("create.light.cylinder", "Cylinder Light", CreateActionCategory.LIGHTS, "CylinderLight", "light", 0, "CylinderLight"),
    _NativeCreateSpec("create.light.disk", "Disk Light", CreateActionCategory.LIGHTS, "DiskLight", "light", 10, "DiskLight"),
    _NativeCreateSpec("create.light.distant", "Distant Light", CreateActionCategory.LIGHTS, "DistantLight", "light", 20, "DistantLight"),
    _NativeCreateSpec("create.light.dome", "Dome Light", CreateActionCategory.LIGHTS, "DomeLight", "light", 30, "DomeLight"),
    _NativeCreateSpec("create.light.rect", "Rect Light", CreateActionCategory.LIGHTS, "RectLight", "light", 40, "RectLight"),
    _NativeCreateSpec("create.light.sphere", "Sphere Light", CreateActionCategory.LIGHTS, "SphereLight", "light", 50, "SphereLight"),
    _NativeCreateSpec("create.camera", "Camera", CreateActionCategory.CAMERAS, "Camera", "camera", 0, "Camera"),
    _NativeCreateSpec("create.scope", "Scope", CreateActionCategory.SCOPES, "Scope", "scope", 0, "Scope", "/"),
    _NativeCreateSpec("create.xform", "Xform", CreateActionCategory.TRANSFORMS, "Xform", "xform", 0, "Xform"),
    _NativeCreateSpec("create.material.usd-preview-surface", "USD Preview Surface", CreateActionCategory.MATERIALS, "Material", "material", 0, "PreviewSurface", "/World/Looks"),
    _NativeCreateSpec("create.render_product", "Render Product", CreateActionCategory.RENDER_PRODUCTS, "RenderProduct", "render_product", 0, "RenderProduct", "/Render/Products"),
    _NativeCreateSpec("create.sensor.generic-lidar", "Generic Lidar Sensor", CreateActionCategory.SENSORS, "OmniLidar", "sensor", 0, "Lidar"),
    _NativeCreateSpec("create.decal", "Decal", CreateActionCategory.DECALS, "Decal", "decal", 0, "Decal"),
    _NativeCreateSpec("create.projector", "Projector", CreateActionCategory.PROJECTORS, "Projector", "projector", 0, "Projector"),
    _NativeCreateSpec("create.prim", "Prim", CreateActionCategory.OTHER, "", "generic", 0, "Prim"),
    _NativeCreateSpec(
        "create.material.usd-preview-surface.bind",
        "USD Preview Surface and Bind to Selection",
        CreateActionCategory.MATERIALS,
        "Material",
        "material_bind",
        10,
        "PreviewSurface",
        "/World/Looks",
        True,
        "",
    ),
)
_SUPPORTED_GENERIC_TYPES = frozenset(
    spec.type_name for spec in _NATIVE_CREATE_SPECS if spec.type_name
)


def _is_below(path: str, root: str) -> bool:
    value = str(path)
    return value == root or value.startswith(f"{root}/")


def is_user_facing_scene_path(path: str, scene: Any, stage: Any | None) -> bool:
    """Return whether ``path`` is user-facing for ``scene``.

    This is the single authoritative ownership rule shared by the OVStage
    stage adapter and the Inspector evidence capture, so evidence filtering
    cannot drift from production filtering:

    - paths below a scene-registered presentation root
      (``scene.presentation_root_paths``) are renderer-owned;
    - the ``/Render`` subtree is user-facing when the native authoring birth
      records show the user created ``/Render``;
    - otherwise, conditional runtime roots are provider-internal.
    """

    value = str(path)
    runtime_roots = tuple(getattr(scene, "presentation_root_paths", ()) or ())
    if any(_is_below(value, str(root)) for root in runtime_roots):
        return False
    if _is_below(value, "/Render"):
        births = (
            getattr(stage, "_ovui_path_birth_ordinals", {})
            if stage is not None
            else {}
        )
        if "/Render" in births:
            return True
    return not any(_is_below(value, root) for root in _CONDITIONAL_RUNTIME_ROOTS)


@dataclass(frozen=True, eq=False)
class _OvstageStageItem:
    path: str
    topology_version: int
    owner: object = field(repr=False)
    display_name: str = ""
    type_name: str = ""
    type_category: str = "Other"
    icon_name: str = "Prim"
    applied_schemas: tuple[str, ...] = ()
    is_root: bool = False


_TYPE_CATEGORY_MAP: dict[str, str] = {
    "mesh": "Mesh",
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
    "usdgeommesh": "Mesh",
    "usdgeomsphere": "Mesh",
    "usdgeomcube": "Mesh",
    "usdgeomcone": "Mesh",
    "usdgeomcylinder": "Mesh",
    "usdgeomcapsule": "Mesh",
    "usdgeomplane": "Mesh",
    "usdgeombasiscurves": "Mesh",
    "usdgeompoints": "Mesh",
    "usdgeomnurbscurves": "Mesh",
    "usdgeomnurbspatch": "Mesh",
    "light": "Light",
    "domelight": "Light",
    "distantlight": "Light",
    "disklight": "Light",
    "rectlight": "Light",
    "spherelight": "Light",
    "cylinderlight": "Light",
    "usdluxlight": "Light",
    "usdluxdomelight": "Light",
    "usdluxdistantlight": "Light",
    "usdluxdisklight": "Light",
    "usdluxrectlight": "Light",
    "usdluxspherelight": "Light",
    "usdluxcylinderlight": "Light",
    "camera": "Camera",
    "usdgeomcamera": "Camera",
    "xform": "Xform",
    "usdgeomxform": "Xform",
    "scope": "Scope",
    "usdgeomscope": "Scope",
}

_ICON_MAP: dict[str, str] = {
    "mesh": "Mesh",
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
    "usdgeommesh": "Mesh",
    "usdgeomsphere": "Mesh",
    "usdgeomcube": "Mesh",
    "usdgeomcone": "Mesh",
    "usdgeomcylinder": "Mesh",
    "usdgeomcapsule": "Mesh",
    "usdgeomplane": "Mesh",
    "usdgeombasiscurves": "Mesh",
    "usdgeompoints": "Mesh",
    "usdgeomnurbscurves": "Mesh",
    "usdgeomnurbspatch": "Mesh",
    "light": "Light",
    "domelight": "DomeLight",
    "distantlight": "DistantLight",
    "disklight": "DiskLight",
    "rectlight": "RectLight",
    "spherelight": "SphereLight",
    "cylinderlight": "CylinderLight",
    "usdluxlight": "Light",
    "usdluxdomelight": "DomeLight",
    "usdluxdistantlight": "DistantLight",
    "usdluxdisklight": "DiskLight",
    "usdluxrectlight": "RectLight",
    "usdluxspherelight": "SphereLight",
    "usdluxcylinderlight": "CylinderLight",
    "camera": "Camera",
    "usdgeomcamera": "Camera",
    "xform": "Xform",
    "usdgeomxform": "Xform",
    "scope": "Scope",
    "usdgeomscope": "Scope",
}

_IMAGEABLE_TYPE_NAMES = frozenset(_TYPE_CATEGORY_MAP)
_IMAGEABLE_SCHEMA_NAMES = frozenset(
    {
        "imageable",
        "usdgeomimageable",
        "geomimageable",
    }
)


_VISIBILITY_DESCRIPTOR = NativeValueDescriptor(
    name=_VISIBILITY_ATTR,
    dtype=(1, 64, 1),
    semantic=2,
    native_is_array=False,
    logical_is_array=False,
)
_MATERIAL_BINDING_DESCRIPTOR = NativeValueDescriptor(
    name="material:binding",
    dtype=(1, 64, 1),
    semantic=4,
    native_is_array=True,
    logical_is_array=True,
)


class _CreateAndBindMaterialCommand(Command):
    """One structural create plus relationship bind history edge."""

    def __init__(
        self,
        scene: Any,
        create_command: Command,
        bind_command: Command,
        event_paths: Iterable[str],
    ) -> None:
        self._scene = scene
        self._stage = getattr(scene, "_stage", None)
        self._create_command = create_command
        self._bind_command = bind_command
        self._event_paths = tuple(dict.fromkeys(str(path) for path in event_paths))

    def do(self) -> None:
        self._require_scene()
        stream = self._scene.change_stream
        with stream.suppress_notifications():
            self._create_command.do()
            try:
                self._bind_command.do()
            except BaseException as operation_error:
                try:
                    self._create_command.undo()
                except BaseException as rollback_error:
                    _add_cleanup_note(
                        operation_error,
                        "material create-bind create rollback failed",
                        rollback_error,
                    )
                raise
        with stream.committed_edge_publication():
            stream.publish_resync_change(
                self._event_paths,
                source="structural:create-bind",
            )

    def undo(self) -> None:
        self._require_scene()
        stream = self._scene.change_stream
        with stream.suppress_notifications():
            self._bind_command.undo()
            try:
                self._create_command.undo()
            except BaseException as operation_error:
                try:
                    self._bind_command.do()
                except BaseException as rollback_error:
                    _add_cleanup_note(
                        operation_error,
                        "material create-bind binding compensation failed",
                        rollback_error,
                    )
                raise
        with stream.committed_edge_publication():
            stream.publish_resync_change(
                self._event_paths,
                source="structural:create-bind",
            )

    def _require_scene(self) -> None:
        if (
            self._stage is None
            or getattr(self._scene, "_stage", None) is not self._stage
            or not getattr(self._scene, "is_open", False)
        ):
            raise RuntimeError(
                "material create-bind history belongs to a closed or replaced OVStage scene"
            )


class OvstageStageAdapter(StageAdapter, CreateActionsAdapter, CoreMaterialsAdapter):
    """Stage hierarchy adapter backed by an opened ovstage scene."""

    def __init__(
        self,
        scene: Any | None = None,
        undo_manager: Any | None = None,
        call_later: Any | None = None,
    ) -> None:
        self._scene = scene
        self._undo_manager = undo_manager
        self._call_later = call_later
        self._item_owner = object()
        self._root_item = _OvstageStageItem(
            path=_ROOT_PATH,
            topology_version=-1,
            owner=self._item_owner,
            display_name=_ROOT_PATH,
            is_root=True,
        )
        self._topology_version: tuple[int, int] | None = None
        self._items_by_path: dict[str, _OvstageStageItem] = {
            _ROOT_PATH: self._root_item,
        }
        self._child_paths_by_path: dict[str, tuple[str, ...]] = {
            _ROOT_PATH: (),
        }
        self._stage_up_axis: str | None = None
        self._spatial_token_ordinal: int | None = None
        self._raw_visibility_by_path: dict[str, str] = {}
        self._raw_purpose_by_path: dict[str, str] = {}
        self._suppressed = 0
        self._visibility_group_depth = 0
        self._pending_visibility: dict[str, tuple[str, str]] = {}
        # True once a grouped member failed (or the owner aborted): the
        # outermost close then discards the group instead of committing it.
        self._visibility_group_failed = False
        # Manager group depth recorded when the outermost adapter scope
        # opened: cleanup always restores the manager to this depth, even
        # when end_group()/cancel_group() themselves fail.
        self._manager_group_floor: int | None = None

    def get_root(self) -> AdapterItem:
        self._ensure_topology_cache_current()
        return self._root_item

    def get_children(self, item: AdapterItem) -> List[AdapterItem]:
        record = self._record_for_item(item)
        if record is None:
            return []
        path = record.path
        child_paths = self._child_paths_by_path.get(path, ())
        return [
            self._items_by_path[child_path]
            for child_path in child_paths
            if child_path in self._items_by_path
        ]

    def can_have_children(self, item: AdapterItem) -> bool:
        return bool(self.get_children(item))

    def get_item_path(self, item: AdapterItem) -> str:
        record = self._record_for_item(item)
        if record is None:
            raise_not_ready("stage path lookup")
        return record.path

    def get_item_at_path(self, path: str) -> Optional[AdapterItem]:
        normalized = self._normalize_path(path)
        if not normalized or self._stage_or_none() is None:
            return None
        self._ensure_topology_cache_current()
        return self._items_by_path.get(normalized)

    def get_display_name(self, item: AdapterItem) -> str:
        record = self._record_for_item(item)
        if record is None:
            return ""
        return record.display_name

    def get_type_name(self, item: AdapterItem) -> str:
        record = self._record_for_item(item)
        if record is None:
            return ""
        return record.type_name

    def get_type_category(self, item: AdapterItem) -> str:
        record = self._record_for_item(item)
        if record is None:
            return "Other"
        return record.type_category

    def get_icon_name(self, item: AdapterItem) -> str:
        record = self._record_for_item(item)
        if record is None:
            return "Prim"
        return record.icon_name

    def get_badge_flags(self, item: AdapterItem) -> BadgeFlags:
        del item
        return BadgeFlags.NONE

    def get_item_flags(self, item: AdapterItem) -> ItemFlags:
        del item
        return ItemFlags.NONE

    def compute_visibility(self, item: AdapterItem) -> VisibilityState:
        record = self._record_for_item(item)
        if record is None or record.path == _ROOT_PATH:
            return VisibilityState.VISIBLE
        path = record.path
        stage = self._require_stage()

        parent = self._parent_path(stage, path)
        while parent not in ("", _ROOT_PATH):
            if self._read_raw_visibility(parent) == _VISIBILITY_INVISIBLE:
                return VisibilityState.INHERITED_INVISIBLE
            parent = self._parent_path(stage, parent)
        if self._read_raw_visibility(path) == _VISIBILITY_INVISIBLE:
            return VisibilityState.INVISIBLE
        return VisibilityState.VISIBLE

    def set_visibility(self, item: AdapterItem, visible: bool) -> None:
        record = self._record_for_item(item)
        if record is None or not self.can_edit_visibility(item):
            raise_not_ready("stage visibility write")
        path = record.path
        stage = self._require_stage()
        old_value = _read_raw_visibility(stage, path)
        new_value = _VISIBILITY_INHERITED if visible else _VISIBILITY_INVISIBLE
        pending = self._pending_visibility.get(path)
        if pending is not None:
            old_value = pending[0]
        if old_value == new_value:
            self._pending_visibility.pop(path, None)
            return
        if self._visibility_group_depth:
            self._pending_visibility[path] = (old_value, new_value)
            return
        command = NativeValueEditCommand(
            self._scene,
            (path,),
            _VISIBILITY_DESCRIPTOR,
            (old_value,),
            (new_value,),
            category="visibility",
            source="",
        )
        _dispatch_command(self._undo_manager, command)

    def can_edit_visibility(self, item: AdapterItem) -> bool:
        record = self._record_for_item(item)
        if record is None or record.path == _ROOT_PATH:
            return False
        return _is_imageable(record)

    def can_rename(self, item: AdapterItem) -> bool:
        record = self._record_for_item(item)
        return bool(
            record is not None
            and record.path != _ROOT_PATH
            and not self._is_protected_structural_path(record.path)
        )

    def rename(self, item: AdapterItem, new_name: str) -> str:
        record = self._record_for_item(item)
        if record is None or not self.can_rename(item):
            raise_not_ready("stage rename")
        actual_name = self.normalize_name(new_name)
        if not actual_name:
            raise ValueError("OVStage prim name must not be empty")
        old_path = record.path
        parent_path = old_path.rsplit("/", 1)[0] or _ROOT_PATH
        new_path = self._append_child_path(parent_path, actual_name)
        if new_path == old_path:
            return actual_name
        if self.get_item_at_path(new_path) is not None:
            raise ValueError(f"OVStage rename target already exists: {new_path}")
        source_subtree = self._subtree_paths(old_path)
        command = NativeMovePrimsCommand(
            self._scene,
            ((old_path, new_path),),
            {old_path: source_subtree},
        )
        self._push_structural_command(command)
        return actual_name

    def normalize_name(self, name: str) -> str:
        value = str(name).strip()
        if not value:
            return ""
        normalized = "".join(
            character if character == "_" or character.isalnum() else "_"
            for character in value
        )
        if normalized and normalized[0].isdigit():
            normalized = "_" + normalized
        return normalized if normalized.isidentifier() else ""

    def can_reparent(self, items: List[AdapterItem], new_parent: AdapterItem) -> bool:
        try:
            self._validated_reparent_edits(items, new_parent, ReparentPosition.CHILD)
        except (RuntimeError, ValueError):
            return False
        return True

    def reparent(
        self,
        items: List[AdapterItem],
        new_parent: AdapterItem,
        position: ReparentPosition,
    ) -> None:
        edits, subtrees = self._validated_reparent_edits(items, new_parent, position)
        command = NativeMovePrimsCommand(self._scene, edits, subtrees)
        self._push_structural_command(command)

    def filter_items(
        self,
        items: List[AdapterItem],
        predicate: Callable[[AdapterItem], bool],
    ) -> List[AdapterItem]:
        self._ensure_topology_cache_current()
        filtered: list[AdapterItem] = []
        for item in items:
            record = self._record_for_item(item)
            if record is not None and predicate(record):
                filtered.append(record)
        return filtered

    def list_create_actions(
        self,
        *,
        selection_paths: Iterable[str] | None = None,
    ) -> Any:
        selections = tuple(str(path) for path in (selection_paths or ()))
        scene = self._scene
        if scene is None or not getattr(scene, "is_open", False):
            return CreateActionCatalog(
                selection_paths=selections,
                warnings=(
                    CreateActionWarning(
                        code=CreateActionErrorCode.NO_ACTIVE_STAGE.value,
                        message="No active OVStage scene is available.",
                        severity=CreateActionWarningSeverity.ERROR,
                    ),
                ),
            )
        bind_selection_available = bool(selections) and all(
            _is_imageable(record)
            for record in (
                self._record_for_item(self.get_item_at_path(path))
                for path in selections
            )
            if record is not None
        ) and all(self.get_item_at_path(path) is not None for path in selections)
        actions = tuple(
            CreateActionDescriptor(
                action_id=spec.action_id,
                label=spec.label,
                category_id=spec.category,
                target_prim_type=spec.type_name,
                prim_kind=spec.kind,
                order=spec.order,
                requirements=(
                    (
                        CreateActionRequirement.ACTIVE_STAGE,
                        CreateActionRequirement.SELECTION,
                    )
                    if spec.kind == "material_bind"
                    else (CreateActionRequirement.ACTIVE_STAGE,)
                ),
                placement_policy=(
                    CreatePlacementPolicy.ROOT
                    if spec.default_parent == _ROOT_PATH
                    else CreatePlacementPolicy.DEFAULT_PARENT
                ),
                selection_policy=CreateSelectionPolicy.SELECT_PRIMARY,
                default_parent_path=spec.default_parent,
                default_name=spec.default_name,
                option_schema=(
                    {"prim_type": tuple(sorted(_SUPPORTED_GENERIC_TYPES))}
                    if spec.kind == "generic"
                    else {}
                ),
                enabled=(
                    spec.enabled
                    and (spec.kind != "material_bind" or bind_selection_available)
                ),
                disabled_reason=(
                    "Select at least one current native imageable prim to bind."
                    if spec.kind == "material_bind" and not bind_selection_available
                    else spec.disabled_reason
                ),
                metadata={
                    "native_structural_identity_only": spec.kind != "material_bind",
                    "native_relationship_binding": spec.kind == "material_bind",
                },
            )
            for spec in _NATIVE_CREATE_SPECS
        )
        category_ids = {action.category_id for action in actions}
        categories = tuple(
            CreateActionCategoryDescriptor(category)
            for category in CreateActionCategory.ordered()
            if category.value in category_ids
        )
        return CreateActionCatalog(
            categories=categories,
            actions=actions,
            active_stage_id=str(getattr(scene, "source_path", "") or id(self.stage)),
            selection_paths=selections,
            revision=(
                f"{int(getattr(scene, 'current_ordinal', 0) or 0)}:"
                f"{int(getattr(scene, 'topology_revision', 0) or 0)}"
            ),
        )

    def create_prim(self, request: Any) -> Any:
        if not isinstance(request, CreateRequest):
            return self._rejected_create("Invalid native create request.")
        if getattr(self._scene, "_ovui_structural_edit_active", False):
            return self._rejected_create("Reentrant native structural edits are not allowed.")
        catalog = self.list_create_actions(selection_paths=request.selection_paths)
        action = catalog.action(request.action_id)
        if action is None:
            return self._rejected_create(
                f"Unknown OVStage create action: {request.action_id}",
                CreateActionErrorCode.UNSUPPORTED,
            )
        if not action.is_available:
            return self._rejected_create(
                action.disabled_reason or "Native create action is disabled.",
                CreateActionErrorCode.DISABLED,
            )
        type_name = action.target_prim_type
        if action.prim_kind == "generic":
            type_name = str(request.options.get("prim_type", ""))
            if type_name not in _SUPPORTED_GENERIC_TYPES:
                return self._rejected_create(
                    f"Unsupported native prim type: {type_name!r}",
                    CreateActionErrorCode.VALIDATION_FAILED,
                )

        requested_parent = request.requested_parent_path
        parent_path = requested_parent or action.default_parent_path or _ROOT_PATH
        parent_path = self._normalize_path(parent_path)
        if not parent_path:
            return self._rejected_create(
                "Native create parent must be a canonical absolute prim path.",
                CreateActionErrorCode.VALIDATION_FAILED,
            )
        parent_rows: tuple[tuple[str, str], ...] = ()
        if parent_path != _ROOT_PATH and not self._native_path_exists(parent_path):
            if requested_parent:
                return self._rejected_create(
                    f"Native create parent does not exist: {parent_path}",
                    CreateActionErrorCode.VALIDATION_FAILED,
                )
            try:
                parent_rows = self._missing_default_parent_rows(parent_path)
            except ValueError as exc:
                return self._rejected_create(
                    str(exc),
                    CreateActionErrorCode.VALIDATION_FAILED,
                )

        raw_name = request.requested_name or action.default_name or action.label
        if request.requested_name and not request.requested_name.strip():
            return self._rejected_create(
                "Native prim name must not be blank.",
                CreateActionErrorCode.VALIDATION_FAILED,
            )
        child_name = self.normalize_name(raw_name)
        if not child_name:
            return self._rejected_create(
                f"Native prim name is invalid: {raw_name!r}",
                CreateActionErrorCode.VALIDATION_FAILED,
            )
        target_path = self._next_unique_child_path(parent_path, child_name)
        rows = (*parent_rows, (target_path, type_name))
        create_command = NativeCreatePrimsCommand(self._scene, rows)
        command: Command = create_command
        if action.prim_kind == "material_bind":
            selection_paths = tuple(dict.fromkeys(request.selection_paths))
            try:
                old_bindings = self._material_binding_values(selection_paths)
            except ValueError as exc:
                return self._rejected_create(
                    str(exc),
                    CreateActionErrorCode.VALIDATION_FAILED,
                )
            bind_command = NativeValueEditCommand(
                self._scene,
                selection_paths,
                _MATERIAL_BINDING_DESCRIPTOR,
                old_bindings,
                tuple((target_path,) for _path in selection_paths),
                source="material:bind",
            )
            command = _CreateAndBindMaterialCommand(
                self._scene,
                create_command,
                bind_command,
                (
                    *(created_path for created_path, _created_type in rows),
                    *selection_paths,
                ),
            )
        try:
            self._push_structural_command(command)
        except Exception as exc:
            return self._rejected_create(
                f"Native create failed: {type(exc).__name__}: {exc}",
                CreateActionErrorCode.CREATE_FAILED,
            )
        actual_type = read_token_attribute(
            self._require_stage(),
            target_path,
            "usd-prim-type",
        )
        if actual_type != type_name:
            return self._rejected_create(
                f"Native create did not expose requested type {type_name!r} at {target_path}.",
                CreateActionErrorCode.CREATE_FAILED,
            )
        created_paths = tuple(path for path, _type_name in rows)
        binding_applied = action.prim_kind == "material_bind"
        return CreateResult.accepted_result(
            created_paths=created_paths,
            primary_path=target_path,
            selection_paths=(target_path,),
            focus_path=target_path,
            binding_applied=binding_applied,
            message=(
                f"Created {target_path} as native {type_name} and bound it to the selection."
                if binding_applied
                else f"Created {target_path} as native {type_name}."
            ),
            metadata={
                "native_type": type_name,
                "native_relationship_binding": binding_applied,
            },
        )

    def _push_structural_command(self, command: Command) -> None:
        _dispatch_command(self._undo_manager, command)

    @staticmethod
    def _rejected_create(
        message: str,
        error_code: CreateActionErrorCode = CreateActionErrorCode.VALIDATION_FAILED,
    ) -> CreateResult:
        return CreateResult.rejected_result(
            message=message,
            error_code=error_code,
            warnings=(
                CreateActionWarning(
                    code=error_code.value,
                    message=message,
                    severity=CreateActionWarningSeverity.ERROR,
                ),
            ),
        )

    def _missing_default_parent_rows(
        self,
        parent_path: str,
    ) -> tuple[tuple[str, str], ...]:
        rows: list[tuple[str, str]] = []
        current = ""
        for component in parent_path.strip("/").split("/"):
            if not component:
                raise ValueError("Native default parent is malformed.")
            current = f"{current}/{component}"
            if self._native_path_exists(current):
                continue
            type_name = "Xform" if current == "/World" else "Scope"
            rows.append((current, type_name))
        return tuple(rows)

    def _next_unique_child_path(self, parent_path: str, name: str) -> str:
        candidate = self._append_child_path(parent_path, name)
        if not self._native_path_exists(candidate):
            return candidate
        index = 1
        while True:
            candidate = self._append_child_path(parent_path, f"{name}_{index:02d}")
            if not self._native_path_exists(candidate):
                return candidate
            index += 1

    @staticmethod
    def _append_child_path(parent_path: str, child_name: str) -> str:
        return (
            f"/{child_name}"
            if parent_path == _ROOT_PATH
            else f"{parent_path}/{child_name}"
        )

    def _native_path_exists(self, path: str) -> bool:
        value = self._normalize_path(path)
        if not value:
            return False
        if value == _ROOT_PATH:
            return True
        parent = value.rsplit("/", 1)[0]
        query_parent = parent or ""
        try:
            return value in {
                str(child)
                for child in self._require_stage().get_child_paths(query_parent)
            }
        except KeyError:
            return False

    def _subtree_paths(self, root_path: str) -> tuple[str, ...]:
        self._ensure_topology_cache_current()
        if root_path not in self._items_by_path:
            raise ValueError(f"Native subtree does not exist: {root_path}")
        result: list[str] = []
        stack = [root_path]
        while stack:
            path = stack.pop()
            result.append(path)
            stack.extend(reversed(self._child_paths_by_path.get(path, ())))
        return tuple(result)

    def _is_protected_structural_path(self, path: str) -> bool:
        value = str(path)
        if any(_is_below(value, root) for root in _KNOWN_INTERNAL_ROOTS):
            return True
        return any(
            _is_below(value, str(root))
            for root in tuple(
                getattr(self._scene, "presentation_root_paths", ()) or ()
            )
        )

    def _validated_reparent_edits(
        self,
        items: List[AdapterItem],
        new_parent: AdapterItem,
        position: ReparentPosition,
    ) -> tuple[tuple[tuple[str, str], ...], dict[str, tuple[str, ...]]]:
        if not items:
            raise ValueError("At least one current OVStage item is required.")
        target = self._record_for_item(new_parent)
        if target is None:
            raise ValueError("Reparent target is stale or foreign.")
        if position is ReparentPosition.CHILD:
            target_parent_path = target.path
        elif position in (ReparentPosition.BEFORE, ReparentPosition.AFTER):
            raise NotImplementedError(
                "the supplied OVStage API does not expose sibling ordering for "
                "namespace edits"
            )
        else:
            raise ValueError("Unknown OVStage reparent position.")

        records = []
        seen_paths: set[str] = set()
        for item in items:
            record = self._record_for_item(item)
            if record is None or record.path == _ROOT_PATH:
                raise ValueError("Reparent source is stale, foreign, or root.")
            if self._is_protected_structural_path(record.path):
                raise ValueError("Protected OVStage runtime paths cannot be moved.")
            if record.path in seen_paths:
                raise ValueError("Duplicate OVStage reparent source.")
            seen_paths.add(record.path)
            records.append(record)

        for record in records:
            if target_parent_path == record.path or target_parent_path.startswith(
                record.path + "/"
            ):
                raise ValueError("OVStage prims cannot be reparented into themselves.")
            if any(
                other.path.startswith(record.path + "/")
                for other in records
                if other is not record
            ):
                raise ValueError("Nested OVStage reparent sources are ambiguous.")

        edits = tuple(
            (
                record.path,
                self._append_child_path(
                    target_parent_path,
                    record.path.rsplit("/", 1)[-1],
                ),
            )
            for record in records
        )
        if all(old == new for old, new in edits):
            raise ValueError("OVStage reparent would not change the namespace.")
        destinations = tuple(new for _old, new in edits)
        if len(set(destinations)) != len(destinations):
            raise ValueError("OVStage reparent destinations collide.")
        source_paths = {old for old, _new in edits}
        collisions = tuple(
            new
            for old, new in edits
            if new != old and self._native_path_exists(new) and new not in source_paths
        )
        if collisions:
            raise ValueError(
                "OVStage reparent target already exists: " + ", ".join(collisions)
            )
        subtrees = {old: self._subtree_paths(old) for old, _new in edits}
        return edits, subtrees

    def list_core_materials(
        self,
        *,
        selection_paths: Iterable[str] | None = None,
    ) -> Any:
        return CoreMaterialsAdapter.list_core_materials(
            self,
            selection_paths=selection_paths,
        )

    def create_material(self, request: Any) -> Any:
        return CoreMaterialsAdapter.create_material(self, request)

    def bind_material(self, request: Any) -> Any:
        if not isinstance(request, BindMaterialRequest):
            return BindMaterialResult.rejected_result(
                message="Invalid native material-binding request.",
                error_code=CoreMaterialErrorCode.VALIDATION_FAILED,
            )
        if request.binding_strength:
            return BindMaterialResult.rejected_result(
                material_path=request.material_path,
                failed_prim_paths=request.selection_paths,
                message=(
                    "The supplied OVStage API exposes relationship targets but no "
                    "public material binding-strength authoring field."
                ),
                error_code=CoreMaterialErrorCode.UNSUPPORTED,
            )
        material_item = self.get_item_at_path(request.material_path)
        material_record = self._record_for_item(material_item)
        if material_record is None or material_record.type_name != "Material":
            return BindMaterialResult.rejected_result(
                material_path=request.material_path,
                failed_prim_paths=request.selection_paths,
                message=(
                    "Native material path is missing, stale, or not a Material: "
                    f"{request.material_path}"
                ),
                error_code=CoreMaterialErrorCode.VALIDATION_FAILED,
            )
        selection_paths = tuple(dict.fromkeys(request.selection_paths))
        try:
            old_values = self._material_binding_values(selection_paths)
        except ValueError as exc:
            return BindMaterialResult.rejected_result(
                material_path=request.material_path,
                failed_prim_paths=request.selection_paths,
                message=str(exc),
                error_code=CoreMaterialErrorCode.VALIDATION_FAILED,
            )
        new_values = tuple((request.material_path,) for _path in selection_paths)
        if old_values == new_values:
            return BindMaterialResult.accepted_result(
                material_path=request.material_path,
                bound_prim_paths=selection_paths,
                selection_paths=selection_paths,
                message=(
                    f"Native material {request.material_path} was already bound to "
                    f"{len(selection_paths)} prim(s)."
                ),
            )
        command = NativeValueEditCommand(
            self._scene,
            selection_paths,
            _MATERIAL_BINDING_DESCRIPTOR,
            old_values,
            new_values,
            source="material:bind",
        )
        try:
            _dispatch_command(self._undo_manager, command)
        except Exception as exc:
            return BindMaterialResult.rejected_result(
                material_path=request.material_path,
                failed_prim_paths=selection_paths,
                message=f"Native material binding failed: {type(exc).__name__}: {exc}",
                error_code=CoreMaterialErrorCode.BIND_FAILED,
            )
        return BindMaterialResult.accepted_result(
            material_path=request.material_path,
            bound_prim_paths=selection_paths,
            selection_paths=selection_paths,
            message=(
                f"Bound native material {request.material_path} to "
                f"{len(selection_paths)} prim(s)."
            ),
        )

    def create_and_bind_material(self, request: Any) -> Any:
        return CoreMaterialsAdapter.create_and_bind_material(self, request)

    def _material_binding_values(
        self,
        selection_paths: Iterable[str],
    ) -> tuple[Any, ...]:
        paths = tuple(str(path) for path in selection_paths)
        if not paths:
            raise ValueError("Select at least one current native prim to bind.")
        if len(set(paths)) != len(paths):
            raise ValueError("Native material-binding selection contains duplicates.")
        from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter

        values: list[Any] = []
        for path in paths:
            item = self.get_item_at_path(path)
            record = self._record_for_item(item)
            if record is None or not _is_imageable(record):
                raise ValueError(
                    f"Native material-binding target is stale, missing, or not imageable: {path}"
                )
            properties = OvstagePropertyAdapter(self._scene, [path])
            if "material:binding" not in properties.get_attribute_names():
                values.append(MISSING)
                continue
            metadata = properties.get_attribute_metadata("material:binding")
            if metadata.type_name != "relationship":
                raise ValueError(
                    f"Native material-binding target has an incompatible column: {path}"
                )
            values.append(properties.get_value("material:binding"))
        return tuple(values)

    def subscribe_changes(
        self,
        callback: Callable[[ChangeEvent], None],
    ) -> SubscriptionProtocol:
        scene = self._scene
        if scene is None or not getattr(scene, "is_open", False):
            raise_not_ready("stage change subscription")
        return scene.change_stream.subscribe_stage(
            callback,
            call_later=self._call_later,
        )

    def notify_transform_changed(
        self,
        paths: List[str],
        source: Optional[str] = None,
    ) -> None:
        if self._suppressed or not paths:
            return
        scene = self._scene
        if scene is None or not getattr(scene, "is_open", False):
            return
        stream = scene.change_stream
        current_ordinal = getattr(scene, "current_ordinal", None)
        if (
            current_ordinal is not None
            and not stream.has_pending_suppressed_range
            and stream.last_ordinal >= int(current_ordinal)
        ):
            # A direct TransformAdapter write already published the committed
            # native ordinal. Manipulator callers may still invoke this
            # compatibility hook; do not emit the same change twice.
            return
        events = stream.poll(source=source, deliver_suppressed=True)
        if not events:
            stream.publish_transform_change(paths, source=source)

    def begin_undo_group(self, label: str) -> None:
        # Transactional acquisition: the manager group first — if it
        # raises, no adapter visibility scope is created and the depth
        # counter is untouched.
        manager_floor: int | None = None
        if self._undo_manager is not None:
            depth = getattr(self._undo_manager, "open_group_depth", None)
            manager_floor = int(depth) if depth is not None else None
            self._undo_manager.begin_group(label)
        self._visibility_group_depth += 1
        if self._visibility_group_depth == 1:
            self._pending_visibility = {}
            self._visibility_group_failed = False
            self._manager_group_floor = manager_floor

    def abort_undo_group(self) -> None:
        """Poison and close the visibility group; the member error stays primary.

        A failed grouped member must leave no partial native write, no
        history entry, and no provider event: the pending grouped edits
        are discarded and the outermost close cancels the manager group
        instead of committing it. When called while an exception is being
        handled, cleanup failures attach to it as notes instead of
        displacing it.
        """
        if self._visibility_group_depth > 0:
            self._visibility_group_failed = True
        active = sys.exc_info()[1]
        if active is None:
            self.end_undo_group()
            return
        try:
            self.end_undo_group()
        except BaseException as cleanup_error:  # secondary: never displaces
            add_note = getattr(active, "add_note", None)
            if callable(add_note):
                add_note(
                    "abort cleanup also failed: "
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )

    def end_undo_group(self) -> None:
        if self._visibility_group_depth <= 0:
            raise RuntimeError("OVStage undo group was not begun")
        outermost = self._visibility_group_depth == 1
        failed = self._visibility_group_failed
        operation_error: BaseException | None = None
        deferred_interrupt: BaseException | None = None
        push_count_before: int | None = None
        try:
            if outermost and not failed and self._pending_visibility:
                paths = tuple(self._pending_visibility)
                command = NativeValueEditCommand(
                    self._scene,
                    paths,
                    _VISIBILITY_DESCRIPTOR,
                    tuple(self._pending_visibility[path][0] for path in paths),
                    tuple(self._pending_visibility[path][1] for path in paths),
                    category="visibility",
                    source="",
                )
                if self._undo_manager is not None:
                    count = getattr(
                        self._undo_manager, "open_group_command_count", None
                    )
                    push_count_before = int(count) if count is not None else None
                    self._undo_manager.push(command)
                else:
                    command.do()
        except BaseException as exc:
            recorded_by_push = False
            if push_count_before is not None:
                count = getattr(
                    self._undo_manager, "open_group_command_count", None
                )
                recorded_by_push = (
                    count is not None and int(count) > push_count_before
                )
            if not isinstance(exc, Exception) and (
                recorded_by_push
                or getattr(exc, "_ovui_history_consistent", False)
            ):
                # The grouped edit fully applied and its entry is recorded:
                # push consumed the edge mark after appending to the open
                # accumulator (observed via the command-count growth); the
                # direct-execution branch still carries the mark, consumed
                # here. Commit the close normally, then keep the interrupt
                # caller-visible.
                clear_history_consistent(exc)
                deferred_interrupt = exc
            else:
                operation_error = exc
        finally:
            self._visibility_group_depth -= 1
            manager_floor = self._manager_group_floor
            if outermost:
                self._pending_visibility = {}
                self._visibility_group_failed = False
                self._manager_group_floor = None
        cleanup_error = self._close_manager_group(
            outermost=outermost,
            discard=failed or operation_error is not None,
            manager_floor=manager_floor,
        )
        if operation_error is not None:
            # The member/push failure stays primary; cleanup context
            # attaches as a note instead of displacing it.
            if cleanup_error is not None:
                _add_cleanup_note(
                    operation_error,
                    "undo-group cleanup also failed",
                    cleanup_error,
                )
            raise operation_error
        if deferred_interrupt is not None:
            if cleanup_error is not None:
                _add_cleanup_note(
                    deferred_interrupt,
                    "undo-group cleanup also failed",
                    cleanup_error,
                )
            raise deferred_interrupt
        if cleanup_error is not None:
            raise cleanup_error

    def _close_manager_group(
        self,
        *,
        outermost: bool,
        discard: bool,
        manager_floor: int | None,
    ) -> BaseException | None:
        """Close one manager group level; never leave depth above the floor.

        Returns the primary cleanup failure instead of raising so the
        caller controls error primacy. ``discard`` closes cancel
        (compensating anything the group accumulated) rather than commit.

        Every recovery decision uses the manager's OBSERVED
        ``open_group_depth``, never an assumption about what a failed
        call did: a close that failed AFTER its level already popped (for
        example a change subscriber raising from the top-level record) is
        treated as closed — no compensating call may run against an outer
        (possibly caller-owned) level, and everything below the recorded
        pre-scope floor stays untouched.

        Levels that remain open above the floor after a failure recover
        per level: a committed close retries ``end_group()`` first (an
        APPLIED command must never lose its history entry), then
        ``cancel_group()`` (compensated means truthfully "not applied"),
        then ``force_discard_group()`` as the documented last resort. A
        discard close retries in ``cancel`` → ``end`` → ``discard`` order
        so compensation is preferred but a nonempty accumulator whose
        cancellation keeps failing is RECORDED rather than silently
        dropped with its effects applied. All failures aggregate onto the
        first error as notes.
        """
        manager = self._undo_manager
        if manager is None:
            return None
        errors: list[BaseException] = []
        cancel = getattr(manager, "cancel_group", None)

        def depth_of() -> int | None:
            observed = getattr(manager, "open_group_depth", None)
            return int(observed) if observed is not None else None

        floor = manager_floor if manager_floor is not None else 0
        before = depth_of()
        try:
            if (
                discard
                and outermost
                and callable(cancel)
                and (before is None or before > floor)
            ):
                # An aborted group records nothing: cancel compensates
                # anything already accumulated instead of committing it.
                cancel()
            else:
                manager.end_group()
        except BaseException as exc:
            errors.append(exc)
        if not outermost or before is None:
            # Inner levels report their failure; the outermost close owns
            # floor recovery. Without an observable depth there is nothing
            # safe to recover against.
            return _aggregate_cleanup_errors(errors)
        # Recover every level still open above the floor — unconditionally:
        # an inner level whose close already failed (and was reported to
        # its caller) would otherwise leak past the outermost close.
        raw_discard = getattr(manager, "force_discard_group", None)

        def guarded_discard() -> None:
            # Force-discard drops the accumulator WITHOUT undoing or
            # recording it: only safe when it is observed empty. Dropping
            # a nonempty one would leave applied effects with no history
            # ownership — then the level is retained (reported below) so
            # a later end/cancel can still record or compensate it.
            count = getattr(manager, "open_group_command_count", None)
            if count is not None and int(count) > 0:
                raise RuntimeError(
                    "group accumulator retained: force-discard refused for "
                    f"{int(count)} applied command(s) with no other "
                    "recovery; ownership stays with the open group"
                )
            raw_discard()

        discard_group = guarded_discard if callable(raw_discard) else None
        attempts = (
            (cancel, manager.end_group, discard_group)
            if discard
            else (manager.end_group, cancel, discard_group)
        )
        while True:
            depth = depth_of()
            if depth is None or depth <= floor:
                break
            progressed = False
            for attempt in attempts:
                if not callable(attempt):
                    continue
                try:
                    attempt()
                except BaseException as exc:
                    errors.append(exc)
                current = depth_of()
                if current is None or current < depth:
                    progressed = True
                    break
            if not progressed:
                break  # nothing makes progress: stop rather than spin
        return _aggregate_cleanup_errors(errors)

    def suppress_change_notifications(self) -> ContextManager:
        return self._suppress_change_notifications()

    @contextlib.contextmanager
    def _suppress_change_notifications(self) -> ContextManager:
        self._suppressed += 1
        stream = self._change_stream_or_none()
        try:
            if stream is None:
                yield
            else:
                with stream.suppress_notifications():
                    yield
        finally:
            self._suppressed = max(0, self._suppressed - 1)

    def compute_world_aabb(self, paths: List[str]) -> AABB:
        if not paths:
            return None
        stage = self._stage_or_none()
        if stage is None:
            return None
        self._ensure_topology_cache_current()

        bounds: AABB = None
        for raw_path in paths:
            for path in self._paths_to_bound(self._normalize_path(raw_path)):
                prim_bounds = self.compute_prim_world_aabb_with_extent_fallback(path)
                bounds = _union_aabb(bounds, prim_bounds)
        return bounds

    def compute_prim_world_aabb_with_extent_fallback(self, path: str) -> AABB:
        normalized_path = self._normalize_path(path)
        stage = self._stage_or_none()
        if stage is None or normalized_path == _ROOT_PATH:
            return None
        self._ensure_topology_cache_current()
        record = self._items_by_path.get(normalized_path)
        if record is None:
            return None
        local_bounds = _local_geometry_bounds(stage, normalized_path, record.type_name)
        if local_bounds is None:
            return None
        world_matrix = self._read_world_matrix(normalized_path)
        if world_matrix is None:
            return None
        return _transform_aabb(local_bounds, world_matrix)

    def read_bound_camera(self) -> Optional[BoundCameraPose]:
        bounds = self.compute_world_aabb([_ROOT_PATH])
        if bounds is None:
            return None
        mins, maxs = bounds
        center = tuple((mins[axis] + maxs[axis]) * 0.5 for axis in range(3))
        size = tuple(maxs[axis] - mins[axis] for axis in range(3))
        radius = max(_length_vec3(size) * 0.5, _BOUND_CAMERA_MIN_RADIUS)
        distance = max(
            radius * _BOUND_CAMERA_DISTANCE_SCALE,
            _BOUND_CAMERA_MIN_DISTANCE,
        )
        eye = (
            center[0] + distance * _BOUND_CAMERA_EYE_OFFSET[0],
            center[1] + distance * _BOUND_CAMERA_EYE_OFFSET[1],
            center[2] + distance * _BOUND_CAMERA_EYE_OFFSET[2],
        )
        return BoundCameraPose(
            eye=eye,
            target=center,
            up_axis=self.read_stage_up_axis(),
            fov_degrees=_BOUND_CAMERA_FOV_DEGREES,
            prim_path=_BOUND_CAMERA_PRIM_PATH,
        )

    def read_stage_up_axis(self) -> str:
        stage = self._stage_or_none()
        if stage is None:
            return StageAdapter.read_stage_up_axis(self)
        if self._stage_up_axis is not None:
            return self._stage_up_axis
        try:
            axis = read_population_up_axis(stage)
        except Exception:
            axis = None
        if axis in {"Y", "Z"}:
            self._stage_up_axis = axis
            return axis
        return StageAdapter.read_stage_up_axis(self)

    def list_cameras(self) -> List[StageChoice]:
        """Return native OVStage Camera prims as common selector choices."""
        return self._list_choices_for_prim_types(("Camera", "UsdGeomCamera"))

    def read_camera_pose(self, path: str) -> Optional[BoundCameraPose]:
        """Return a viewport pose for a native OVStage Camera prim."""
        normalized_path = self._normalize_path(path)
        stage = self._stage_or_none()
        if stage is None or normalized_path == _ROOT_PATH:
            return None
        self._ensure_topology_cache_current()
        record = self._items_by_path.get(normalized_path)
        if record is None or record.type_category != "Camera":
            return None
        matrix = self._read_world_matrix(normalized_path)
        if matrix is None:
            return None
        eye = (
            float(matrix[12]),
            float(matrix[13]),
            float(matrix[14]),
        )
        forward = _normalize_vec3(
            (
                -float(matrix[8]),
                -float(matrix[9]),
                -float(matrix[10]),
            )
        )
        if _length_vec3(forward) <= 1.0e-9:
            forward = (0.0, 0.0, -1.0)
        target = _read_camera_target_offset(stage, normalized_path, eye, forward)
        fov_degrees = _camera_fov_degrees(stage, normalized_path)
        return BoundCameraPose(
            eye=eye,
            target=target,
            up_axis=self.read_stage_up_axis(),
            fov_degrees=fov_degrees,
            prim_path=normalized_path,
        )

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
        del path, view_matrix, proj_matrix, width, height, target_world, source, undoable
        return False

    def list_render_products(self) -> List[StageChoice]:
        """Return RenderProduct prims exposed by the owning OVStage."""
        return self._list_choices_for_prim_types(("RenderProduct", "UsdRenderProduct"))

    def get_render_target_catalog(self) -> RenderTargetCatalog:
        snapshot = native_catalog_snapshot(self._scene)
        targets: list[RenderTargetDescriptor] = []
        for product_path in snapshot.paths_of_type("RenderProduct", "UsdRenderProduct"):
            product = snapshot.prim(product_path)
            if product is None:
                continue
            camera_targets = _canonical_target_paths(product.value("camera"))
            var_targets = _canonical_target_paths(product.value("orderedVars"))
            warnings: list[RenderTargetWarning] = []
            source_path = camera_targets[0] if camera_targets else None
            source = snapshot.prim(source_path) if source_path else None
            source_is_camera = bool(
                source is not None
                and source.type_name.lower() in {"camera", "usdgeomcamera"}
            )
            if source is None:
                warnings.append(
                    RenderTargetWarning(
                        code="invalid_source",
                        message="RenderProduct has no current native source target.",
                    )
                )
            output_names: list[str] = []
            output_families: set[RenderTargetOutputKind] = set()
            for var_path in var_targets:
                render_var = snapshot.prim(var_path)
                if render_var is None or render_var.type_name.lower() not in {
                    "rendervar",
                    "usdrendervar",
                }:
                    warnings.append(
                        RenderTargetWarning(
                            code="invalid_render_var",
                            message=f"RenderProduct target is not a native RenderVar: {var_path}",
                        )
                    )
                    continue
                source_name = str(render_var.value("sourceName") or "")
                if source_name:
                    output_names.append(source_name)
                    token = "".join(ch for ch in source_name.lower() if ch.isalnum())
                    if token == "ldrcolor":
                        output_families.add(RenderTargetOutputKind.IMAGE)
                    elif token == "pointcloud":
                        output_families.add(RenderTargetOutputKind.POINT_CLOUD)
                    else:
                        output_families.add(RenderTargetOutputKind.GENERIC_MODEL_OUTPUT)
            output_kind = (
                next(iter(output_families))
                if len(output_families) == 1
                else RenderTargetOutputKind.MULTI_OUTPUT
                if output_families
                else RenderTargetOutputKind.UNKNOWN
            )
            if (
                source is not None
                and not source_is_camera
                and output_kind is not RenderTargetOutputKind.POINT_CLOUD
            ):
                warnings.append(
                    RenderTargetWarning(
                        code="wrong_source_type",
                        message="Image RenderProduct source is not a native Camera.",
                    )
                )
            resolution = _positive_resolution(product.value("resolution"))
            source_kind = (
                RenderTargetKind.CAMERA
                if source_is_camera
                else RenderTargetKind.SENSOR
                if source is not None and output_kind is RenderTargetOutputKind.POINT_CLOUD
                else RenderTargetKind.RENDER_PRODUCT
            )
            enabled = bool(
                source is not None
                and output_names
                and (
                    source_is_camera
                    or output_kind is RenderTargetOutputKind.POINT_CLOUD
                )
            )
            targets.append(
                RenderTargetDescriptor(
                    target_id=product_path,
                    render_product_path=product_path,
                    display_name=self._display_name_from_path(product_path),
                    kind=source_kind,
                    source_path=source_path if source is not None else None,
                    source_display_name=(
                        self._display_name_from_path(source_path) if source is not None else ""
                    ),
                    source_type=source.type_name if source is not None else "",
                    output_kind=output_kind,
                    output_names=tuple(output_names),
                    resolution=resolution,
                    capabilities=("activate_render_product",) if enabled else (),
                    warnings=tuple(warnings),
                    enabled=enabled,
                    disabled_reason=(
                        ""
                        if enabled
                        else "Native source and RenderVar targets are required."
                    ),
                )
            )
        return RenderTargetCatalog(
            targets=tuple(targets),
            revision=_catalog_revision(snapshot),
        )

    @property
    def stage(self) -> Any:
        scene = self._scene
        return getattr(scene, "_stage", None)

    def _is_user_facing_scene_path(self, path: str) -> bool:
        """Hide renderer-owned rows from the native hierarchy."""

        return is_user_facing_scene_path(path, self._scene, self._stage_or_none())

    def _stage_or_none(self) -> Any | None:
        scene = self._scene
        stage = getattr(scene, "_stage", None)
        if scene is None or stage is None or not getattr(scene, "is_open", False):
            return None
        return stage

    def _require_stage(self) -> Any:
        stage = self._stage_or_none()
        if stage is None:
            raise_not_ready("stage topology")
        return stage

    def _change_stream_or_none(self) -> Any | None:
        scene = self._scene
        if scene is None or not getattr(scene, "is_open", False):
            return None
        return getattr(scene, "change_stream", None)

    def _ensure_topology_cache_current(self) -> None:
        stage = self._require_stage()
        topology_version = int(stage.get_topology_version())
        topology_revision = int(
            getattr(self._scene, "topology_revision", 0) or 0
        )
        cache_version = (topology_version, topology_revision)
        if self._topology_version == cache_version:
            return

        type_records = self._copy_type_records(stage)
        previous_items = self._items_by_path
        items_by_path: dict[str, _OvstageStageItem] = {
            _ROOT_PATH: self._root_item,
        }
        child_paths_by_path: dict[str, tuple[str, ...]] = {}
        stack = [_ROOT_PATH]

        while stack:
            path = stack.pop()
            query_path = _ROOT_QUERY_PATH if path == _ROOT_PATH else path
            try:
                native_child_paths = self._copy_paths(
                    stage.get_child_paths(query_path)
                )
            except KeyError:
                native_child_paths = ()
            child_paths = tuple(
                child_path
                for child_path in native_child_paths
                if self._is_user_facing_scene_path(child_path)
            )
            child_paths_by_path[path] = child_paths
            for child_path in reversed(child_paths):
                type_record = type_records.get(child_path, ("", ()))
                type_name, applied_schemas = type_record
                display_name = self._display_name_from_path(child_path)
                type_category = self._type_category_for(type_name)
                icon_name = self._icon_name_for(type_name)
                previous = previous_items.get(child_path)
                birth_ordinal = getattr(
                    stage,
                    "_ovui_path_birth_ordinals",
                    {},
                ).get(child_path)
                if (
                    previous is not None
                    and (
                        birth_ordinal is None
                        or previous.topology_version == int(birth_ordinal)
                    )
                    and previous.display_name == display_name
                    and previous.type_name == type_name
                    and previous.type_category == type_category
                    and previous.icon_name == icon_name
                    and previous.applied_schemas == applied_schemas
                ):
                    # Kit currently exposes the committed ordinal as its
                    # topology version.  Preserve item identity across ordinary
                    # value writes so selection does not disappear merely
                    # because a transform or property changed.
                    item = previous
                else:
                    item = _OvstageStageItem(
                        path=child_path,
                        topology_version=(
                            int(birth_ordinal)
                            if birth_ordinal is not None
                            else topology_version
                        ),
                        owner=self._item_owner,
                        display_name=display_name,
                        type_name=type_name,
                        type_category=type_category,
                        icon_name=icon_name,
                        applied_schemas=applied_schemas,
                    )
                items_by_path[child_path] = item
                stack.append(child_path)

        self._topology_version = cache_version
        self._items_by_path = items_by_path
        self._child_paths_by_path = child_paths_by_path

    @staticmethod
    def _copy_paths(paths: Iterable[Any]) -> tuple[str, ...]:
        return tuple(str(path) for path in paths)

    @classmethod
    def _copy_type_records(
        cls,
        stage: Any,
    ) -> dict[str, tuple[str, tuple[str, ...]]]:
        records: dict[str, tuple[str, tuple[str, ...]]] = {}
        query_result = stage.query_prims(int(stage.current_ordinal))
        for group in query_result.get("groups", ()):
            group_type_name = str(group.get("prim_type", ""))
            applied_schemas = resolve_query_names(
                stage,
                group.get("applied_schemas", ()),
            )
            prim_list_handle = int(group.get("prim_list_handle") or 0)
            if not prim_list_handle:
                continue
            for path in cls._copy_paths(stage.get_prim_paths(prim_list_handle)):
                type_name = (
                    read_token_attribute(stage, path, "usd-prim-type")
                    or group_type_name
                )
                records[path] = (type_name, applied_schemas)
        return records

    @staticmethod
    def _display_name_from_path(path: str) -> str:
        value = str(path).rstrip("/")
        if value in ("", _ROOT_PATH):
            return _ROOT_PATH
        return value.rsplit("/", 1)[-1]

    @staticmethod
    def _type_category_for(type_name: str) -> str:
        return _TYPE_CATEGORY_MAP.get(str(type_name).lower(), "Other")

    @staticmethod
    def _icon_name_for(type_name: str) -> str:
        return _ICON_MAP.get(str(type_name).lower(), "Prim")

    def _record_for_item(self, item: AdapterItem) -> _OvstageStageItem | None:
        path = self._path_from_item(item)
        if path is None or self._stage_or_none() is None:
            return None
        self._ensure_topology_cache_current()
        record = self._items_by_path.get(path)
        if record is item:
            return record
        return None

    @staticmethod
    def _normalize_path(path: str) -> str:
        if not isinstance(path, str):
            return ""
        value = path
        if value == _ROOT_PATH:
            return value
        if (
            not value.startswith(_ROOT_PATH)
            or value.endswith(_ROOT_PATH)
            or "//" in value
            or any(part in ("", ".", "..") for part in value.split("/")[1:])
        ):
            return ""
        return value

    def _path_from_item(self, item: AdapterItem) -> str | None:
        if (
            isinstance(item, _OvstageStageItem)
            and item.owner is self._item_owner
        ):
            return item.path
        return None

    @staticmethod
    def _parent_path(stage: Any, path: str) -> str:
        try:
            parent = stage.get_parent_path(path)
        except KeyError:
            return _ROOT_PATH
        parent_path = str(parent)
        return _ROOT_PATH if parent_path == "" else parent_path

    def _paths_to_bound(self, path: str) -> tuple[str, ...]:
        if path not in self._items_by_path:
            return ()
        roots = (
            self._child_paths_by_path.get(_ROOT_PATH, ())
            if path == _ROOT_PATH
            else (path,)
        )
        result: list[str] = []
        stack = [(root, True) for root in reversed(tuple(roots))]
        while stack:
            current, is_selected_root = stack.pop()
            if (
                not is_selected_root
                and self._read_raw_visibility(current) == _VISIBILITY_INVISIBLE
            ):
                continue
            if self._read_raw_purpose(current) in _PURPOSE_DEFAULTS:
                result.append(current)
            children = self._child_paths_by_path.get(current, ())
            stack.extend((child, False) for child in reversed(children))
        return tuple(result)

    def _read_raw_visibility(self, path: str) -> str:
        self._ensure_spatial_token_cache_current()
        value = self._raw_visibility_by_path.get(path)
        if value is None:
            value = _read_raw_visibility(self._require_stage(), path)
            self._raw_visibility_by_path[path] = value
        return value

    def _read_raw_purpose(self, path: str) -> str:
        self._ensure_spatial_token_cache_current()
        value = self._raw_purpose_by_path.get(path)
        if value is None:
            value = _read_raw_purpose(self._require_stage(), path)
            self._raw_purpose_by_path[path] = value
        return value

    def _ensure_spatial_token_cache_current(self) -> None:
        ordinal = int(self._require_stage().current_ordinal)
        if self._spatial_token_ordinal == ordinal:
            return
        self._spatial_token_ordinal = ordinal
        self._raw_visibility_by_path.clear()
        self._raw_purpose_by_path.clear()

    def _read_world_matrix(self, path: str) -> tuple[float, ...] | None:
        scene = self._scene
        if scene is not None and getattr(scene, "is_open", False):
            try:
                matrix = _matrix_tuple_from_flat(scene.hierarchy.get_world_xform(path))
                if matrix is not None:
                    return matrix
            except (ImportError, RuntimeError):
                # Match TransformAdapter: fall back only when the hierarchy
                # runtime is unavailable or the prim has no hierarchy column.
                pass
        return _read_matrix_attribute(self._require_stage(), path, "worldMatrix")

    def _list_choices_for_prim_types(
        self,
        type_names: tuple[str, ...],
    ) -> List[StageChoice]:
        if self._stage_or_none() is None:
            return []
        snapshot = native_catalog_snapshot(self._scene)
        return [
            StageChoice(path=path, display_name=self._display_name_from_path(path))
            for path in snapshot.paths_of_type(*type_names)
        ]


def _is_imageable(record: _OvstageStageItem) -> bool:
    type_key = str(record.type_name).lower()
    if type_key in _IMAGEABLE_TYPE_NAMES:
        return True
    for schema in record.applied_schemas:
        schema_key = str(schema).lower()
        if schema_key in _IMAGEABLE_SCHEMA_NAMES or schema_key.endswith("imageable"):
            return True
    return False


def _canonical_target_paths(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, (tuple, list)):
        values = tuple(value)
    else:
        return ()
    result: list[str] = []
    for item in values:
        path = str(item)
        if OvstageStageAdapter._normalize_path(path) and path not in result:
            result.append(path)
    return tuple(result)


def _positive_resolution(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None
    try:
        width, height = int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def _catalog_revision(snapshot: Any) -> str:
    return (
        f"{snapshot.ordinal}:{snapshot.topology_version}:"
        f"{snapshot.topology_revision}"
    )


def _read_raw_visibility(stage: Any, path: str) -> str:
    try:
        raw_value = bytes(
            stage.read_attribute(
                int(stage.current_ordinal),
                [str(path)],
                _VISIBILITY_ATTR,
            )
        )
    except Exception:
        return _VISIBILITY_INHERITED
    token = _decode_visibility_token(stage, raw_value)
    return token if token in _VISIBILITY_TOKENS else _VISIBILITY_INHERITED


def _read_raw_purpose(stage: Any, path: str) -> str:
    value = read_token_attribute(stage, path, _PURPOSE_ATTR)
    return str(value) if value else "geometry"


def _decode_visibility_token(stage: Any, raw_value: bytes) -> str:
    if not raw_value:
        return _VISIBILITY_INHERITED
    try:
        text = raw_value.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    if text in _VISIBILITY_TOKENS:
        return text
    if len(raw_value) == 8:
        try:
            resolved = resolve_token_id(stage, struct.unpack("<Q", raw_value)[0])
        except Exception:
            resolved = ""
        if resolved in _VISIBILITY_TOKENS:
            return resolved
    return _VISIBILITY_INHERITED


def _write_raw_visibility(stage: Any, path: str, value: str) -> None:
    if value not in _VISIBILITY_TOKENS:
        raise ValueError(f"unsupported visibility token: {value!r}")
    if supports_native_stage_writes(stage):
        write_token_attribute(stage, [str(path)], _VISIBILITY_ATTR, [value])
        return
    ordinal = stage.begin_frame()
    try:
        stage.write_attribute(
            ordinal,
            [str(path)],
            _VISIBILITY_ATTR,
            [value.encode("ascii")],
        )
    finally:
        stage.end_frame(ordinal)


def _poll_change_stream(change_stream: Any | None) -> tuple[ChangeEvent, ...]:
    if change_stream is None:
        return ()
    return tuple(change_stream.poll())


def _local_geometry_bounds(
    stage: Any,
    path: str,
    type_name: str,
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    type_key = str(type_name).lower()
    if type_key in {"cube", "usdgeomcube"}:
        size = _read_scalar(stage, path, "size")
        if size is not None and size >= 0.0:
            half = float(size) * 0.5
            bounds = ((-half, -half, -half), (half, half, half))
            if _valid_bounds(bounds):
                return bounds

    if type_key in {"sphere", "usdgeomsphere"}:
        radius = _read_scalar(stage, path, "radius")
        if radius is not None and radius >= 0.0:
            radius = float(radius)
            bounds = ((-radius, -radius, -radius), (radius, radius, radius))
            if _valid_bounds(bounds):
                return bounds

    extent = _read_vec3_array(stage, path, "extent")
    if len(extent) >= 2:
        bounds = (extent[0], extent[1])
        if _valid_bounds(bounds):
            return bounds

    points = _read_vec3_array(stage, path, "points")
    if points:
        bounds = (
            tuple(min(point[axis] for point in points) for axis in range(3)),
            tuple(max(point[axis] for point in points) for axis in range(3)),
        )
        if _valid_bounds(bounds):
            return bounds

    return None


def _valid_bounds(
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
) -> bool:
    """Reject non-finite, absurd (e.g. Kit Xform sentinel ``extent``), or
    inverted AABBs so they cannot poison camera framing / world-bounds unions.

    Mirrors the renderer adapter's container-bounds guard (commit
    ``fix(ovstage): ignore invalid container bounds for framing``).
    """
    values = tuple(float(component) for point in bounds for component in point)
    if not all(math.isfinite(component) for component in values):
        return False
    if any(abs(component) > 1.0e20 for component in values):
        return False
    mins, maxs = bounds
    return all(float(mins[axis]) <= float(maxs[axis]) for axis in range(3))


def _read_vec3_array(
    stage: Any,
    path: str,
    attr_name: str,
) -> tuple[tuple[float, float, float], ...]:
    raw = _read_attribute_bytes(stage, path, attr_name)
    if not raw:
        return ()
    dtype = _read_attribute_dtype(stage, path, attr_name)
    if dtype is not None:
        code, bits, lanes = dtype
        if code != _DLPACK_FLOAT or lanes != 3:
            return ()
        format_char = {32: "f", 64: "d"}.get(bits)
        scalar_size = bits // 8
        if format_char is None or scalar_size <= 0 or len(raw) % (3 * scalar_size):
            return ()
        values = struct.unpack(f"<{len(raw) // scalar_size}{format_char}", raw)
    else:
        if len(raw) % 12:
            return ()
        values = struct.unpack(f"<{len(raw) // 4}f", raw)
    if len(values) % 3:
        return ()
    return tuple(
        (float(values[index]), float(values[index + 1]), float(values[index + 2]))
        for index in range(0, len(values), 3)
    )


def _read_scalar(stage: Any, path: str, attr_name: str) -> float | None:
    raw = _read_attribute_bytes(stage, path, attr_name)
    if len(raw) == 8:
        return float(struct.unpack("<d", raw)[0])
    if len(raw) == 4:
        return float(struct.unpack("<f", raw)[0])
    return None


def _read_vec3_tuple(
    stage: Any,
    path: str,
    attr_name: str,
) -> tuple[float, float, float] | None:
    raw = _read_attribute_bytes(stage, path, attr_name)
    if len(raw) == 24:
        values = struct.unpack("<3d", raw)
    elif len(raw) == 12:
        values = struct.unpack("<3f", raw)
    else:
        return None
    return (float(values[0]), float(values[1]), float(values[2]))


def _read_camera_target_offset(
    stage: Any,
    path: str,
    eye: tuple[float, float, float],
    forward: tuple[float, float, float],
) -> tuple[float, float, float]:
    offset = _read_vec3_tuple(stage, path, "omni:kit:centerOfInterest")
    if offset is not None:
        return tuple(float(eye[axis]) + float(offset[axis]) for axis in range(3))
    return tuple(float(eye[axis]) + float(forward[axis]) * 10.0 for axis in range(3))


def _camera_fov_degrees(stage: Any, path: str) -> float:
    focal = _read_scalar(stage, path, "focalLength")
    vertical_aperture = _read_scalar(stage, path, "verticalAperture")
    if vertical_aperture is None:
        vertical_aperture = 15.2908
    if focal is None or focal <= 0.0 or vertical_aperture <= 0.0:
        return _BOUND_CAMERA_FOV_DEGREES
    return math.degrees(2.0 * math.atan(float(vertical_aperture) / (2.0 * float(focal))))


def _read_matrix_attribute(stage: Any, path: str, attr_name: str) -> tuple[float, ...] | None:
    return read_matrix_attribute(stage, path, attr_name)


def _read_attribute_bytes(stage: Any, path: str, attr_name: str) -> bytes:
    try:
        value = stage.read_attribute(
            int(stage.current_ordinal),
            [str(path)],
            attr_name,
        )
    except Exception:
        return b""
    if not isinstance(value, (bytes, bytearray, memoryview)):
        return b""
    return bytes(value)


def _read_attribute_dtype(
    stage: Any,
    path: str,
    attr_name: str,
) -> tuple[int, int, int] | None:
    info_reader = getattr(stage, "read_attribute_info", None)
    if callable(info_reader):
        try:
            info = info_reader(
                int(stage.current_ordinal),
                str(path),
                str(attr_name),
            )
            code, bits, lanes = info["dtype"]
        except (KeyError, TypeError, ValueError):
            return None
        except Exception:
            return None
        return (int(code), int(bits), int(lanes))

    # Legacy public-shaped stages predate read-group metadata. Retain their
    # query/read-column fallback without using it for the exact api-v2 Stage,
    # whose compatibility query handles are intentionally snapshot-scoped.
    try:
        groups = stage.query_prims(int(stage.current_ordinal)).get("groups", ())
    except Exception:
        return None
    for group in groups:
        group_attrs = set(resolve_query_names(stage, group.get("attributes", ())))
        if attr_name not in group_attrs:
            continue
        prim_list_handle = int(group.get("prim_list_handle") or 0)
        if not prim_list_handle:
            continue
        try:
            paths = {str(value) for value in stage.get_prim_paths(prim_list_handle)}
        except Exception:
            continue
        if str(path) not in paths:
            continue
        try:
            _items, dtype = stage.read_column(
                int(stage.current_ordinal),
                prim_list_handle,
                attr_name,
            )
            code, bits, lanes = dtype
        except Exception:
            return None
        return (int(code), int(bits), int(lanes))
    return None


def _matrix_tuple_from_flat(values: Iterable[Any]) -> tuple[float, ...] | None:
    try:
        flat = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        return None
    if len(flat) != 16 or not all(math.isfinite(value) for value in flat):
        return None
    return flat


def _transform_aabb(
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
    matrix: tuple[float, ...],
) -> AABB:
    mins = [math.inf, math.inf, math.inf]
    maxs = [-math.inf, -math.inf, -math.inf]
    for point in _bounds_corners(*bounds):
        world = _transform_point(point, matrix)
        for axis in range(3):
            mins[axis] = min(mins[axis], world[axis])
            maxs[axis] = max(maxs[axis], world[axis])
    return (tuple(mins), tuple(maxs))


def _bounds_corners(
    mins: tuple[float, float, float],
    maxs: tuple[float, float, float],
) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        (x, y, z)
        for x in (mins[0], maxs[0])
        for y in (mins[1], maxs[1])
        for z in (mins[2], maxs[2])
    )


def _transform_point(
    point: tuple[float, float, float],
    matrix: tuple[float, ...],
) -> tuple[float, float, float]:
    x, y, z = point
    return (
        x * matrix[0] + y * matrix[4] + z * matrix[8] + matrix[12],
        x * matrix[1] + y * matrix[5] + z * matrix[9] + matrix[13],
        x * matrix[2] + y * matrix[6] + z * matrix[10] + matrix[14],
    )


def _union_aabb(lhs: AABB, rhs: AABB) -> AABB:
    if lhs is None:
        return rhs
    if rhs is None:
        return lhs
    lhs_min, lhs_max = lhs
    rhs_min, rhs_max = rhs
    return (
        tuple(min(lhs_min[axis], rhs_min[axis]) for axis in range(3)),
        tuple(max(lhs_max[axis], rhs_max[axis]) for axis in range(3)),
    )


def _length_vec3(value: tuple[float, float, float]) -> float:
    return math.sqrt(sum(component * component for component in value))


def _normalize_vec3(value: tuple[float, float, float]) -> tuple[float, float, float]:
    length = _length_vec3(value)
    if length <= 1.0e-9:
        return (0.0, 0.0, 0.0)
    return tuple(component / length for component in value)


def _dispatch_command(undo_manager: Any, command: Command) -> None:
    """Run/push one command; consume the edge-internal interrupt mark.

    The history-consistent mark is a protocol between the provider stream
    and the command service. Once the edge is finalized here (recorded by
    ``push`` or executed directly), the interrupt escapes to application
    code — which may catch and re-raise the same object later — so the
    mark must not travel with it.
    """
    try:
        if undo_manager is not None:
            undo_manager.push(command)
        else:
            command.do()
    except BaseException as exc:
        clear_history_consistent(exc)
        raise


def _add_cleanup_note(
    primary: BaseException,
    action: str,
    secondary: BaseException,
) -> None:
    add_note = getattr(primary, "add_note", None)
    if callable(add_note):
        add_note(f"{action}: {type(secondary).__name__}: {secondary}")


def _aggregate_cleanup_errors(errors: list) -> BaseException | None:
    """First failure stays primary; the rest attach as notes.

    Marks are consumed here: cleanup errors escape to application code,
    and the edge-internal history-consistent protocol must not travel
    with a reusable exception object.
    """
    if not errors:
        return None
    primary = errors[0]
    clear_history_consistent(primary)
    for extra in errors[1:]:
        clear_history_consistent(extra)
        _add_cleanup_note(
            primary, "undo-group depth recovery also failed", extra
        )
    return primary

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""OpenUSD provider factories registered through common."""

from __future__ import annotations

from typing import Any

from ovui_data_adapters.common import (
    AdapterCapabilities,
    AdapterCapability,
    AdapterFactories,
    CreateMaterialRequest,
    CreateRequest,
    StageCapabilities,
)

from ovui_data_adapters.openusd import renderer_adapter
from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter
from ovui_data_adapters.openusd.property_adapter import UsdPropertyAdapter
from ovui_data_adapters.openusd.stage_adapter import HAS_USD, UsdStageAdapter
from ovui_data_adapters.openusd.transform_adapter import UsdTransformAdapter


_OPENUSD_STAGE_CAPABILITIES = StageCapabilities(
    create_stage=AdapterCapability.supported(),
    export_stage=AdapterCapability.supported(),
    create_prims=AdapterCapability.supported(),
    delete_prims=AdapterCapability.supported(),
)

_MESH_ACTION_IDS = {
    "Cone": "create.geometry.mesh.cone",
    "Cube": "create.geometry.mesh.cube",
    "Cylinder": "create.geometry.mesh.cylinder",
    "Disk": "create.geometry.mesh.disk",
    "Plane": "create.geometry.mesh.plane",
    "Sphere": "create.geometry.mesh.sphere",
    "Torus": "create.geometry.mesh.torus",
}
_SHAPE_ACTION_IDS = {
    "Capsule": "create.geometry.shape.capsule",
    "Cone": "create.geometry.shape.cone",
    "Cube": "create.geometry.shape.cube",
    "Cylinder": "create.geometry.shape.cylinder",
    "Sphere": "create.geometry.shape.sphere",
}
_LIGHT_ACTION_IDS = {
    "CylinderLight": "create.light.cylinder",
    "DiskLight": "create.light.disk",
    "DistantLight": "create.light.distant",
    "DomeLight": "create.light.dome",
    "RectLight": "create.light.rect",
    "SphereLight": "create.light.sphere",
}
_USD_PREVIEW_SURFACE_MATERIAL_ID = "core_material.usd_preview_surface"


def _selection_paths_from_app(app: Any) -> tuple[str, ...]:
    bus_getter = getattr(app, "get_selection_bus", None)
    bus = bus_getter() if callable(bus_getter) else None
    if bus is None:
        bus = getattr(app, "selection_bus", None)
    if bus is None:
        bus = getattr(app, "_selection_bus", None)
    snapshot_getter = getattr(bus, "get_snapshot", None)
    if not callable(snapshot_getter):
        return ()
    try:
        snapshot = snapshot_getter()
        paths = getattr(snapshot, "paths", None)
        if callable(paths):
            return tuple(str(path) for path in paths())
    except Exception:
        return ()
    return ()


def _stage_adapter_from_app(app: Any) -> Any | None:
    getter = getattr(app, "get_stage_adapter", None)
    if callable(getter):
        adapter = getter()
        if adapter is not None:
            return adapter

    adapter = getattr(app, "stage_adapter", None)
    if adapter is not None:
        return adapter

    legacy_getter = getattr(app, "_get_stage_adapter", None)
    if callable(legacy_getter):
        adapter = legacy_getter()
        if adapter is not None:
            return adapter

    return getattr(app, "_stage_adapter", None)


def _stage_from_app(app: Any, adapter: Any | None = None) -> Any | None:
    getter = getattr(app, "get_stage", None)
    if callable(getter):
        stage = getter()
        if stage is not None:
            return stage

    stage = getattr(app, "stage", None)
    if stage is not None:
        return stage

    if adapter is not None:
        stage = getattr(adapter, "stage", None)
        if stage is not None:
            return stage

    stage = getattr(app, "_stage", None)
    if stage is not None:
        return stage

    if adapter is not None:
        stage = getattr(adapter, "_stage", None)
        if stage is not None:
            return stage

    return None


def _undo_manager_from_app(app: Any) -> Any | None:
    getter = getattr(app, "get_undo_manager", None)
    if callable(getter):
        undo_manager = getter()
        if undo_manager is not None:
            return undo_manager
    undo_manager = getattr(app, "undo_manager", None)
    if undo_manager is not None:
        return undo_manager
    return getattr(app, "_undo_manager", None)


class OpenUSDProviderSession:
    """Provider-owned application helpers for the OpenUSD backend."""

    name = "openusd"

    def __init__(self, app: Any | None = None) -> None:
        self._app = app
        self.prepare_runtime_imports()

    def prepare_runtime_imports(self) -> None:
        from pxr import Gf, Sdf, Tf, Usd, UsdGeom  # noqa: F401

    def inspector_usd_local_matrix(self, prim: Any) -> Any | None:
        """Return exact local USD transform evidence for the Inspector."""

        from pxr import UsdGeom

        xformable = UsdGeom.Xformable(prim)
        return xformable.GetLocalTransformation() if xformable else None

    def inspector_usd_computed_extent(self, prim: Any) -> Any | None:
        """Return the schema-computed USD extent used for parity evidence."""

        from pxr import Usd, UsdGeom

        boundable = UsdGeom.Boundable(prim)
        if not boundable:
            return None
        return UsdGeom.Boundable.ComputeExtentFromPlugins(
            boundable,
            Usd.TimeCode.Default(),
        )

    def inspector_find_relative_layer(self, layer: Any, path: str) -> Any | None:
        """Resolve a logical sublayer without exposing OpenUSD to ovui_widgets."""

        from pxr import Sdf

        return Sdf.Layer.FindRelativeToLayer(layer, str(path))

    def open_stage(self, path: str) -> Any:
        from pxr import Usd

        return Usd.Stage.Open(path)

    def create_stage(self, path: str) -> Any:
        from pxr import Usd

        stage = Usd.Stage.CreateNew(path)
        if stage is None:
            raise RuntimeError(f"Usd.Stage.CreateNew returned None for {path!r}")
        return stage

    def export_stage(self, stage: Any, path: str) -> None:
        stage.Export(path)

    def get_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(stage=_OPENUSD_STAGE_CAPABILITIES)

    def can_export_stage(self) -> bool:
        return self.get_capabilities().stage.export_stage.is_supported

    def can_create_prims(self) -> bool:
        return self.get_capabilities().stage.create_prims.is_supported

    def can_delete_prims(self) -> bool:
        return self.get_capabilities().stage.delete_prims.is_supported

    def make_delete_prim_command(self, stage: Any, path: str) -> Any:
        from pxr import Sdf
        from ovui_data_adapters.openusd.commands import DeletePrimCommand

        return DeletePrimCommand(stage, Sdf.Path(path))

    def create_renderer(self) -> Any:
        return renderer_adapter.OvRtxRendererAdapter()

    def renderer_available(self) -> bool:
        return bool(renderer_adapter.AVAILABLE)

    def renderer_unavailable_reason(self) -> str:
        error = renderer_adapter._OVRTX_IMPORT_ERROR
        if error is not None:
            return f"{type(error).__name__}: {error}"
        return "ovrtx not available on this system"

    def create_livestream_tap(self) -> Any | None:
        from ovui_data_adapters.openusd._livestream_tap import LivestreamTap

        return LivestreamTap.maybe_create()

    def _stage_adapter_for_create(self, app: Any) -> UsdStageAdapter | Any | None:
        adapter = _stage_adapter_from_app(app)
        if adapter is not None and (
            callable(getattr(adapter, "create_prim", None))
            or callable(getattr(adapter, "create_material", None))
        ):
            return adapter

        stage = _stage_from_app(app, adapter)
        if stage is None:
            return None
        undo_manager = _undo_manager_from_app(app)
        call_later = getattr(app, "call_later", None)
        return UsdStageAdapter(stage, undo_manager, call_later)

    @staticmethod
    def _prim_from_result(adapter: Any, primary_path: str) -> Any | None:
        stage = getattr(adapter, "stage", None)
        if stage is None:
            stage = getattr(adapter, "_stage", None)
        get_prim = getattr(stage, "GetPrimAtPath", None)
        if not callable(get_prim) or not primary_path:
            return None
        return get_prim(primary_path)

    def _create_prim_action(self, app: Any, action_id: str) -> Any | None:
        adapter = self._stage_adapter_for_create(app)
        create_prim = getattr(adapter, "create_prim", None)
        if not callable(create_prim):
            return None
        result = create_prim(
            CreateRequest(
                action_id,
                selection_paths=_selection_paths_from_app(app),
            )
        )
        if not getattr(result, "accepted", False):
            return None
        return self._prim_from_result(adapter, getattr(result, "primary_path", ""))

    def _create_core_material(self, app: Any, material_id: str) -> Any | None:
        adapter = self._stage_adapter_for_create(app)
        create_material = getattr(adapter, "create_material", None)
        if not callable(create_material):
            return None
        result = create_material(
            CreateMaterialRequest(
                material_id,
                selection_paths=_selection_paths_from_app(app),
            )
        )
        if not getattr(result, "accepted", False):
            return None
        return self._prim_from_result(adapter, getattr(result, "created_material_path", ""))

    def create_mesh_prim(self, app: Any, mesh_name: str) -> Any | None:
        action_id = _MESH_ACTION_IDS.get(mesh_name)
        return self._create_prim_action(app, action_id) if action_id else None

    def create_shape_prim(self, app: Any, shape_name: str) -> Any | None:
        action_id = _SHAPE_ACTION_IDS.get(shape_name)
        return self._create_prim_action(app, action_id) if action_id else None

    def create_light_prim(self, app: Any, light_type: str) -> Any | None:
        action_id = _LIGHT_ACTION_IDS.get(light_type)
        return self._create_prim_action(app, action_id) if action_id else None

    def create_camera(self, app: Any) -> Any | None:
        return self._create_prim_action(app, "create.camera")

    def create_scope(self, app: Any) -> Any | None:
        return self._create_prim_action(app, "create.scope")

    def create_xform(self, app: Any) -> Any | None:
        return self._create_prim_action(app, "create.xform")

    def create_usd_preview_surface_material(self, app: Any) -> Any | None:
        return self._create_core_material(app, _USD_PREVIEW_SURFACE_MATERIAL_ID)

    def get_geometry_standard_prim_attrs(self, stage: Any) -> dict[str, dict[Any, Any]]:
        from ovui_data_adapters.openusd import create_prims

        return create_prims.get_geometry_standard_prim_attrs(stage)

    def get_light_prim_attrs(self, stage: Any) -> dict[str, dict[Any, Any]]:
        from ovui_data_adapters.openusd import create_prims

        return create_prims.get_light_prim_attrs(stage)

    def get_next_free_prim_path(self, stage: Any, child_name: str) -> Any:
        from ovui_data_adapters.openusd import create_prims

        return create_prims.get_next_free_prim_path(stage, child_name)

    def get_next_free_path(self, stage: Any, base_path: Any) -> Any:
        from ovui_data_adapters.openusd import create_prims

        return create_prims.get_next_free_path(stage, base_path)


def create_stage_adapter(
    stage: Any,
    undo_manager: Any,
    call_later: Any,
) -> UsdStageAdapter:
    return UsdStageAdapter(stage, undo_manager, call_later)


def create_property_adapter(
    stage: Any,
    paths: list[str],
    undo_manager: Any,
    stage_adapter: Any,
) -> UsdPropertyAdapter:
    return UsdPropertyAdapter(stage, paths, undo_manager, stage_adapter)


def create_transform_adapter(stage: Any) -> UsdTransformAdapter:
    return UsdTransformAdapter(stage)


def create_layer_stack_adapter(stage: Any, undo_manager: Any) -> UsdLayerStackAdapter:
    return UsdLayerStackAdapter(stage, undo_manager)


def create_renderer_adapter() -> Any:
    return renderer_adapter.OvRtxRendererAdapter()


def create_provider_session(app: Any | None = None) -> OpenUSDProviderSession:
    return OpenUSDProviderSession(app)


def build_factories() -> AdapterFactories:
    if not HAS_USD:
        raise RuntimeError("OpenUSD runtime is unavailable")
    return AdapterFactories(
        stage=create_stage_adapter,
        properties=create_property_adapter,
        transforms=create_transform_adapter,
        renderer=create_renderer_adapter,
        layers=create_layer_stack_adapter,
        session=create_provider_session,
    )

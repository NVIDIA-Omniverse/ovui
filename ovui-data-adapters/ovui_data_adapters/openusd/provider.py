# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OpenUSD provider factories registered through common."""

from __future__ import annotations

import os
import sys
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
from ovui_data_adapters.openusd.layer_stack_adapter import (
    UsdLayerStackAdapter,
    layer_display_name,
)
from ovui_data_adapters.openusd.property_adapter import UsdPropertyAdapter
from ovui_data_adapters.openusd.stage_adapter import HAS_USD, UsdStageAdapter
from ovui_data_adapters.openusd.transform_adapter import UsdTransformAdapter


_URL_OPEN_ERROR = (
    "The OpenUSD provider cannot open URLs. "
    "Use the ovstage provider: OVUI_DATA_ADAPTER_PROVIDER=ovstage."
)

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


def _same_file(first: str, second: str) -> bool:
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(
        os.path.realpath(second)
    )


def _layer_row_name(identifier: str) -> str:
    """Return the name of a layer row in the Layers window."""
    from pxr import Sdf

    layer = Sdf.Layer.Find(identifier)
    if layer is None:
        return os.path.basename(identifier) or identifier
    return layer_display_name(layer)


def _anchor_root_asset_path(root_layer: Any, asset_path: str) -> str:
    """Return a relative asset path as the original root layer resolves it.

    An absolute path, a URI (``https://``, ``omniverse://``) and an anonymous
    layer identifier do not depend on the directory of the layer: they stay
    as they are. ``ComputeAbsolutePath`` must not see a URI, because the
    default resolver changes it (``https://x`` becomes ``https:/x``).

    An in-memory root layer has no file. The resolver finds its relative
    paths from the current directory, so they are anchored to that
    directory.
    """
    from pxr import Ar, Sdf

    if (
        not asset_path
        or Sdf.Layer.IsAnonymousLayerIdentifier(asset_path)
        or renderer_adapter._ASSET_URI_SCHEME_RE.match(asset_path)
        or os.path.isabs(asset_path)
    ):
        return asset_path
    if root_layer.anonymous:
        # A path that ends with a separator is a directory for the resolver.
        anchored = Ar.GetResolver().CreateIdentifier(
            asset_path, Ar.ResolvedPath(os.path.join(os.getcwd(), ""))
        )
    else:
        anchored = root_layer.ComputeAbsolutePath(asset_path)
    if not anchored:
        raise RuntimeError(
            f"cannot anchor the asset path {asset_path!r} of the root layer "
            f"{root_layer.identifier!r}"
        )
    return anchored


def _save_root_layer_with_layer_stack(
    stage: Any, path: str, *, save_changed_sublayers: bool = True,
) -> None:
    """Write the root layer of ``stage`` to ``path`` and keep its sublayers.

    ``Usd.Stage.Export`` flattens the composed stage: the sublayers and the
    session layer are merged into the file, and instances become
    ``Flattened_Prototype_N`` prims. Save and Save As must keep the layer
    stack that the Layers window shows, so this writes only the root layer,
    with its sublayer list. The session layer is not saved.

    Decisions that keep every change of the user:

    * An anonymous layer in the layer stack has no file, so the saved root
      cannot refer to it. The save stops before it writes a file.
    * The stage is not saved over a file of one of its own sublayers: the
      saved root would use itself as a sublayer, and the sublayer content
      would be lost from the disk.
    * A sublayer with unsaved changes is saved to its own file first (as
      Save All does), so the saved scene contains the changes. With
      ``save_changed_sublayers=False`` only the root layer is written: each
      sublayer keeps its unsaved changes and its unsaved mark.
    * When the target directory is not the directory of the root layer, each
      relative asset path is changed to the absolute path that the original
      root layer resolves, so the saved file composes the same scene. The
      offset and scale of each sublayer (its timing) stay as authored. For
      an in-memory root layer, this directory is the current directory.
    """
    from pxr import Sdf, UsdUtils

    root_layer = stage.GetRootLayer()
    sublayers = [
        layer
        for layer in stage.GetLayerStack(includeSessionLayers=False)
        if layer != root_layer
    ]
    # Name each anonymous layer as the Layers window shows it: its row name
    # and the row name of its parent layer.
    anonymous = [
        f"{_layer_row_name(str(sublayer_path))!r} "
        f"under {layer_display_name(parent)!r}"
        for parent in [root_layer, *sublayers]
        for sublayer_path in parent.subLayerPaths
        if Sdf.Layer.IsAnonymousLayerIdentifier(str(sublayer_path))
    ]
    if anonymous:
        raise RuntimeError(
            "the layer stack has anonymous layers that have no file: "
            f"{', '.join(anonymous)}. Save these layers to files first"
        )
    for layer in sublayers:
        if layer.realPath and _same_file(layer.realPath, path):
            raise RuntimeError(
                f"{path!r} is the file of the sublayer {layer.identifier!r}; "
                "select a different file"
            )
    if save_changed_sublayers:
        for layer in sublayers:
            if layer.dirty and not layer.Save():
                raise RuntimeError(
                    f"cannot save the changed sublayer {layer.identifier!r}"
                )

    saved_root = Sdf.Layer.CreateAnonymous(os.path.basename(path))
    saved_root.TransferContent(root_layer)
    if root_layer.anonymous:
        root_directory = os.getcwd()
    else:
        root_directory = os.path.dirname(os.path.abspath(root_layer.realPath))
    if not _same_file(root_directory, os.path.dirname(os.path.abspath(path))):
        sublayer_offsets = list(saved_root.subLayerOffsets)
        UsdUtils.ModifyAssetPaths(
            saved_root,
            lambda asset_path: _anchor_root_asset_path(root_layer, asset_path),
        )
        # ModifyAssetPaths writes the sublayer list again and resets the
        # offset and scale of each sublayer: put the authored timing back.
        if len(saved_root.subLayerPaths) != len(sublayer_offsets):
            raise RuntimeError(
                "cannot keep the sublayer offsets of the root layer "
                f"{root_layer.identifier!r}: the sublayer list changed"
            )
        for index, offset in enumerate(sublayer_offsets):
            saved_root.subLayerOffsets[index] = offset
    if not saved_root.Export(path):
        raise RuntimeError(f"cannot write the root layer to {path!r}")


class OpenUSDProviderSession:
    """Provider-owned application helpers for the OpenUSD backend."""

    name = "openusd"

    def __init__(self, app: Any | None = None) -> None:
        self._app = app
        self.prepare_runtime_imports()

    def prepare_runtime_imports(self) -> None:
        from pxr import Gf, Sdf, Tf, Usd, UsdGeom  # noqa: F401

    def runtime_component_versions(self) -> tuple[tuple[str, str], ...]:
        """Return concrete runtime versions without exposing OpenUSD to widgets.

        ovrtx is reported only when the renderer has loaded it, so this does
        not import ovrtx.
        """
        from pxr import Usd

        from ovui_data_adapters.common.ovrtx_import import loaded_ovrtx_version

        versions = [("OpenUSD", ".".join(str(part) for part in Usd.GetVersion()))]
        ovrtx_version = loaded_ovrtx_version()
        if ovrtx_version:
            versions.append(("ovrtx", ovrtx_version))
        return tuple(versions)

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

        try:
            return Usd.Stage.Open(path)
        except Exception as exc:
            if str(path).lower().startswith(("http://", "https://")):
                raise RuntimeError(_URL_OPEN_ERROR) from exc
            raise

    def create_stage(self, path: str) -> Any:
        from pxr import Usd

        stage = Usd.Stage.CreateNew(path)
        if stage is None:
            raise RuntimeError(f"Usd.Stage.CreateNew returned None for {path!r}")
        return stage

    def export_stage(self, stage: Any, path: str) -> None:
        """Save the stage to ``path`` and keep its layer stack.

        File > Save and File > Save As use this. See
        :func:`_save_root_layer_with_layer_stack`.
        """
        _save_root_layer_with_layer_stack(stage, path)

    def export_root_layer(self, stage: Any, path: str) -> None:
        """Write only the root layer of the stage to ``path``, with its sublayer list.

        Unlike :meth:`export_stage`, this does not save the sublayers that
        have unsaved changes: they keep their changes and their unsaved
        mark. The application uses this when the user saves only the root
        layer of a New Stage that File > Save As gave a file. See
        :func:`_save_root_layer_with_layer_stack`.
        """
        _save_root_layer_with_layer_stack(
            stage, path, save_changed_sublayers=False,
        )

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
        bus = getattr(app, "selection_bus", None)
        if bus is not None:
            bus.publish(list(result.selection_paths), source="create_menu")
        return self._prim_from_result(adapter, getattr(result, "primary_path", ""))

    def _create_core_material(self, app: Any, material_id: str) -> Any | None:
        adapter = self._stage_adapter_for_create(app)
        create_material = getattr(adapter, "create_material", None)
        if not callable(create_material):
            return None
        request = CreateMaterialRequest(
            material_id,
            selection_paths=_selection_paths_from_app(app),
        )
        create_and_bind = getattr(adapter, "create_and_bind_material", None)
        result = create_and_bind(request) if callable(create_and_bind) else None
        if not getattr(result, "accepted", False):
            # A refused bind still creates the material, without a binding,
            # as Create > Material did before it could bind.
            if result is not None and request.selection_paths:
                causes = dict.fromkeys(
                    (
                        str(getattr(result, "message", "")),
                        *(str(warning.message) for warning in getattr(result, "warnings", ())),
                    )
                )
                print(
                    f"[OpenUSD adapter] Create and bind material {material_id} was refused: "
                    f"{' '.join(cause for cause in causes if cause)} "
                    "Creating the material without a binding.",
                    file=sys.stderr,
                )
            result = create_material(request)
        elif getattr(result, "skipped_prim_paths", ()):
            # The other selected prims are bound; report the ones that are not.
            print(
                f"[OpenUSD adapter] Create and bind material {material_id} did not bind "
                f"{len(result.skipped_prim_paths)} selected prim(s): "
                f"{' '.join(str(warning.message) for warning in result.warnings)} "
                "The material is bound to the other selected prims.",
                file=sys.stderr,
            )
        if not getattr(result, "accepted", False):
            print(
                f"[OpenUSD adapter] Create material {material_id} failed: "
                f"{getattr(result, 'message', '')}",
                file=sys.stderr,
            )
            return None
        bus = getattr(app, "selection_bus", None)
        if bus is not None:
            bus.publish(list(result.selection_paths), source="create_menu")
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

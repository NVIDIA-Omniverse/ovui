# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Behavioral coverage for OpenUSD adapter capability advertisements."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

pytest.importorskip("pxr", reason="OpenUSD runtime is unavailable")
from pxr import Sdf, Usd, UsdGeom

from ovui_data_adapters.common import (
    CreateMaterialRequest,
    CreateMaterialResult,
    CreateRequest,
    CreateResult,
    LayerHandle,
)
from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter
from ovui_data_adapters.openusd.property_adapter import UsdPropertyAdapter
from ovui_data_adapters.openusd.provider import OpenUSDProviderSession


def test_openusd_stage_capabilities_match_export_create_delete_behavior(tmp_path) -> None:
    session = OpenUSDProviderSession()
    stage_path = tmp_path / "stage.usda"
    export_path = tmp_path / "exported.usda"
    stage = session.create_stage(str(stage_path))
    app = SimpleNamespace(_stage_adapter=SimpleNamespace(stage=stage))

    stage_capabilities = session.get_capabilities().stage
    assert set(stage_capabilities.supported_actions()) == {
        "create_stage",
        "export_stage",
        "create_prims",
        "delete_prims",
    }

    created = session.create_xform(app)
    assert created is not None
    created_path = str(created.GetPath())
    assert stage.GetPrimAtPath(created_path).IsValid()

    command = session.make_delete_prim_command(stage, created_path)
    command.do()
    assert not stage.GetPrimAtPath(created_path).IsValid()
    command.undo()
    assert stage.GetPrimAtPath(created_path).IsValid()

    session.export_stage(stage, str(export_path))
    assert export_path.is_file()
    reopened = Usd.Stage.Open(str(export_path))
    assert reopened is not None
    assert reopened.GetPrimAtPath(created_path).IsValid()


def test_openusd_provider_session_create_helpers_delegate_to_stage_adapter() -> None:
    session = OpenUSDProviderSession()
    prim = object()

    class _Stage:
        def GetPrimAtPath(self, path: str) -> object | None:
            assert path == "/World/Cube"
            return prim

    class _StageAdapter:
        stage = _Stage()

        def __init__(self) -> None:
            self.requests: list[CreateRequest] = []

        def create_prim(self, request: CreateRequest) -> CreateResult:
            self.requests.append(request)
            return CreateResult.accepted_result(
                created_paths=("/World/Cube",),
                primary_path="/World/Cube",
                selection_paths=("/World/Cube",),
            )

    class _SelectionBus:
        def get_snapshot(self) -> SimpleNamespace:
            return SimpleNamespace(paths=lambda: ["/World/Selected"])

    adapter = _StageAdapter()
    app = SimpleNamespace(_stage_adapter=adapter, selection_bus=_SelectionBus())

    assert session.create_mesh_prim(app, "Cube") is prim

    assert adapter.requests == [
        CreateRequest(
            "create.geometry.mesh.cube",
            selection_paths=("/World/Selected",),
        )
    ]


def test_openusd_provider_session_material_helper_delegates_to_stage_adapter() -> None:
    session = OpenUSDProviderSession()
    prim = object()

    class _Stage:
        def GetPrimAtPath(self, path: str) -> object | None:
            assert path == "/World/Looks/PreviewSurface"
            return prim

    class _StageAdapter:
        stage = _Stage()

        def __init__(self) -> None:
            self.requests: list[CreateMaterialRequest] = []

        def create_material(self, request: CreateMaterialRequest) -> CreateMaterialResult:
            self.requests.append(request)
            return CreateMaterialResult.accepted_result(
                created_material_path="/World/Looks/PreviewSurface",
                created_paths=("/World/Looks/PreviewSurface",),
                selection_paths=("/World/Looks/PreviewSurface",),
            )

    adapter = _StageAdapter()
    app = SimpleNamespace(_stage_adapter=adapter)

    assert session.create_usd_preview_surface_material(app) is prim

    assert adapter.requests == [
        CreateMaterialRequest("core_material.usd_preview_surface")
    ]


def test_openusd_provider_session_create_helpers_use_public_backend_contract() -> None:
    session = OpenUSDProviderSession()
    prim = object()

    class _Stage:
        def GetPrimAtPath(self, path: str) -> object | None:
            assert path == "/World/Cube"
            return prim

    class _StageAdapter:
        stage = _Stage()

        def __init__(self) -> None:
            self.requests: list[CreateRequest] = []

        def create_prim(self, request: CreateRequest) -> CreateResult:
            self.requests.append(request)
            return CreateResult.accepted_result(
                created_paths=("/World/Cube",),
                primary_path="/World/Cube",
                selection_paths=("/World/Cube",),
            )

    class _SelectionBus:
        def get_snapshot(self) -> SimpleNamespace:
            return SimpleNamespace(paths=lambda: ["/World/Selected"])

    class _PublicBackendApp:
        def __init__(self, adapter: _StageAdapter) -> None:
            self.stage_adapter = adapter
            self.selection_bus = _SelectionBus()

        def get_stage_adapter(self) -> _StageAdapter:
            return self.stage_adapter

        def get_selection_bus(self) -> _SelectionBus:
            return self.selection_bus

    adapter = _StageAdapter()
    app = _PublicBackendApp(adapter)

    assert not hasattr(app, "_stage_adapter")
    assert not hasattr(app, "_get_stage_adapter")
    assert session.create_mesh_prim(app, "Cube") is prim
    assert adapter.requests == [
        CreateRequest(
            "create.geometry.mesh.cube",
            selection_paths=("/World/Selected",),
        )
    ]


def test_openusd_provider_session_material_helper_uses_public_stage_fallback() -> None:
    session = OpenUSDProviderSession()
    stage = Usd.Stage.CreateInMemory()

    class _PublicBackendApp:
        def __init__(self, stage: Usd.Stage) -> None:
            self.stage = stage

        def get_stage(self) -> Usd.Stage:
            return self.stage

    app = _PublicBackendApp(stage)

    assert not hasattr(app, "_stage")
    assert not hasattr(app, "_stage_adapter")
    material = session.create_usd_preview_surface_material(app)
    assert material is not None
    assert material.GetTypeName() == "Material"
    assert stage.GetPrimAtPath(str(material.GetPath())).IsValid()


def test_openusd_provider_session_orders_public_accessors_before_legacy_private_fallbacks() -> None:
    source = inspect.getsource(OpenUSDProviderSession._stage_adapter_for_create)

    assert source.index("_stage_adapter_from_app") < source.index("_stage_from_app")
    helper_source = inspect.getsource(
        __import__(
            "ovui_data_adapters.openusd.provider",
            fromlist=["_stage_adapter_from_app"],
        )._stage_adapter_from_app
    )
    assert helper_source.index('"get_stage_adapter"') < helper_source.index('"_get_stage_adapter"')
    assert helper_source.index('"stage_adapter"') < helper_source.index('"_stage_adapter"')


def test_openusd_property_capabilities_match_clear_value_behavior() -> None:
    stage = Usd.Stage.CreateInMemory()
    sphere = UsdGeom.Sphere.Define(stage, "/Sphere")
    radius_attr = sphere.GetRadiusAttr()
    radius_attr.Set(7.0)
    adapter = UsdPropertyAdapter(stage, ["/Sphere"])

    property_capabilities = adapter.get_capabilities()
    assert set(property_capabilities.supported_actions()) == {"clear_values"}
    assert adapter.get_value("radius") == 7.0

    adapter.clear_value("radius")

    assert not radius_attr.HasAuthoredValueOpinion()
    assert adapter.get_value("radius") == 1.0


def test_openusd_layer_capabilities_match_edit_and_sublayer_behavior(tmp_path) -> None:
    root_path = tmp_path / "root.usda"
    stage = Usd.Stage.CreateNew(str(root_path))
    assert stage is not None
    adapter = UsdLayerStackAdapter(stage, object())
    root_id = adapter.get_root_layer().identifier

    layer_capabilities = adapter.get_capabilities()
    required_actions = {
        "layer_stack",
        "edit_target_read",
        "edit_target_write",
        "save_layer",
        "save_layer_as",
        "create_sublayer",
        "insert_sublayer",
        "remove_sublayer",
        "reload_layer",
    }
    assert required_actions <= set(layer_capabilities.supported_actions())

    created_path = tmp_path / "created.usda"
    created_id = adapter.create_sublayer(root_id, -1, str(created_path))
    assert adapter.find_layer(created_id) is not None

    adapter.set_edit_target(created_id)
    assert adapter.get_edit_target_identifier() == created_id

    UsdGeom.Xform.Define(stage, "/AuthoredInCreatedLayer")
    assert adapter.save_layer(created_id) is True
    exported_id = adapter.save_layer_as(
        created_id,
        str(tmp_path / "created_copy.usda"),
        replace_in_parent=False,
    )
    assert exported_id is not None
    assert adapter.find_layer(exported_id) is not None

    inserted_stage = Usd.Stage.CreateNew(str(tmp_path / "inserted.usda"))
    assert inserted_stage is not None
    inserted_stage.GetRootLayer().Save()
    adapter.insert_sublayer(root_id, 0, str(tmp_path / "inserted.usda"))
    assert any(
        identifier.endswith("inserted.usda")
        for identifier in adapter.get_sublayer_identifiers(adapter.get_root_layer())
    )
    removed_id = adapter.remove_sublayer(root_id, 0)
    assert removed_id.endswith("inserted.usda")

    UsdGeom.Xform.Define(stage, "/DiscardedByReload")
    assert stage.GetPrimAtPath("/DiscardedByReload").IsValid()
    assert adapter.reload_layer(created_id) is True
    assert not stage.GetPrimAtPath("/DiscardedByReload").IsValid()


def test_openusd_layer_capabilities_match_advanced_layer_behavior(tmp_path) -> None:
    root_path = tmp_path / "root.usda"
    top_path = tmp_path / "top.usda"
    middle_path = tmp_path / "middle.usda"
    replacement_path = tmp_path / "replacement.usda"

    top_layer = Sdf.Layer.CreateNew(str(top_path))
    Sdf.CreatePrimInLayer(top_layer, "/PrimFromTop")
    assert top_layer.Save()

    middle_layer = Sdf.Layer.CreateNew(str(middle_path))
    Sdf.CreatePrimInLayer(middle_layer, "/PrimFromMiddle")
    assert middle_layer.Save()

    replacement_layer = Sdf.Layer.CreateNew(str(replacement_path))
    Sdf.CreatePrimInLayer(replacement_layer, "/PrimFromReplacement")
    assert replacement_layer.Save()

    root_layer = Sdf.Layer.CreateNew(str(root_path))
    root_layer.subLayerPaths = [str(top_path), str(middle_path)]
    assert root_layer.Save()

    stage = Usd.Stage.Open(str(root_path))
    assert stage is not None
    adapter = UsdLayerStackAdapter(stage, object())
    root_handle = adapter.get_root_layer()
    root_id = root_handle.identifier
    top_id = top_layer.identifier
    middle_id = middle_layer.identifier
    replacement_id = replacement_layer.identifier

    advanced_actions = {
        "mute_layer",
        "lock_layer",
        "move_sublayer",
        "replace_sublayer",
        "prim_spec_read",
        "prim_spec_edit",
        "layer_snapshot",
        "layer_restore",
        "transfer_layer_content",
    }
    assert advanced_actions <= set(adapter.get_capabilities().supported_actions())

    adapter.set_mute(top_id, True)
    assert adapter.is_muted(LayerHandle(top_id)) is True
    adapter.set_mute(top_id, False)
    assert adapter.is_muted(LayerHandle(top_id)) is False

    adapter.set_lock(top_id, True)
    assert adapter.is_locked(LayerHandle(top_id)) is True
    adapter.set_lock(top_id, False)
    assert adapter.is_locked(LayerHandle(top_id)) is False

    adapter.move_sublayer(root_id, 0, root_id, 2)
    assert adapter.get_sublayer_identifiers(root_handle) == [middle_id, top_id]

    replaced_id = adapter.replace_sublayer(root_id, 0, replacement_id)
    assert replaced_id == middle_id
    assert adapter.get_sublayer_identifiers(root_handle) == [
        replacement_id,
        top_id,
    ]

    descriptors = adapter.get_prim_specs(top_id, "/")
    assert any(descriptor.path == "/PrimFromTop" for descriptor in descriptors)
    assert adapter.has_prim_spec(top_id, "/PrimFromTop") is True

    exported = adapter.export_prim_spec(top_id, "/PrimFromTop")
    assert "PrimFromTop" in exported
    adapter.remove_prim_spec(top_id, "/PrimFromTop")
    assert adapter.has_prim_spec(top_id, "/PrimFromTop") is False
    adapter.import_prim_spec(top_id, "/PrimFromTop", exported)
    assert adapter.has_prim_spec(top_id, "/PrimFromTop") is True

    snapshot = adapter.snapshot_layer(top_id)
    removed_id = adapter.remove_sublayer(root_id, 1)
    assert removed_id == top_id
    assert top_id not in adapter.get_sublayer_identifiers(root_handle)
    restored_id = adapter.restore_layer_from_snapshot(snapshot)
    assert restored_id == top_id
    assert top_id in adapter.get_sublayer_identifiers(root_handle)

    adapter.transfer_layer_content(top_id, replacement_id)
    assert adapter.has_prim_spec(replacement_id, "/PrimFromTop") is True

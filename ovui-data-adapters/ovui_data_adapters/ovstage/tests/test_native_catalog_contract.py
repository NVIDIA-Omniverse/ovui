# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OVStage-native camera, render-output, and physics catalog contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
from typing import Any, Iterator

import pytest

from ovui_data_adapters.common import (
    RenderTargetKind,
    RenderTargetOutputKind,
    RenderVarOutputKind,
)
from ovui_data_adapters.ovstage._constants import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
)
from ovui_data_adapters.ovstage._authoring import (
    MISSING,
    NativeValueDescriptor,
    NativeValueEditCommand,
)
from ovui_data_adapters.ovstage._catalog import native_catalog_snapshot
from ovui_data_adapters.ovstage.provider import (
    _discover_rigid_body_paths,
    create_provider_session,
    create_stage_adapter,
)
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes


_FIXTURE = Path(__file__).resolve().parents[4] / "ovui-widgets/tests/data/multiple_render_targets.usda"


@pytest.fixture(scope="module")
def runtime() -> Any:
    package_parent = Path(__file__).resolve().parents[2]
    previous_paths = list(sys.path)
    loaded = sys.modules.get("ovstage")
    if loaded is not None and not callable(getattr(loaded, "Stage", None)):
        sys.modules.pop("ovstage", None)
    sys.path[:] = [
        entry
        for entry in sys.path
        if not entry or Path(entry).resolve() != package_parent
    ]
    try:
        return load_required_runtimes(
            module_name=PROVIDER_NAME,
            entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
        )
    finally:
        sys.path[:] = previous_paths


@pytest.fixture()
def opened(runtime: Any) -> Iterator[tuple[Any, Any, Any]]:
    session = create_provider_session(runtime=runtime)
    scene = session.open_stage(str(_FIXTURE))
    adapter = create_stage_adapter(scene)
    try:
        yield session, scene, adapter
    finally:
        session.shutdown_scene()


def _renderer_for(scene: Any, active_path: str) -> OvstageRendererAdapter:
    renderer = object.__new__(OvstageRendererAdapter)
    renderer._scene = scene
    renderer._active_render_product_common_path = active_path
    renderer._render_product_path = active_path
    return renderer


def test_camera_and_product_choices_are_type_driven_sorted_and_named(opened) -> None:
    _session, _scene, adapter = opened
    assert [(item.path, item.display_name) for item in adapter.list_cameras()] == [
        ("/World/Cameras/Closeup", "Closeup"),
        ("/World/Cameras/Main", "Main"),
    ]
    assert [(item.path, item.display_name) for item in adapter.list_render_products()] == [
        ("/Render/Products/CloseupCamera", "CloseupCamera"),
        ("/Render/Products/MainCamera", "MainCamera"),
        ("/Render/Products/RoofLidar", "RoofLidar"),
    ]
    pose = adapter.read_camera_pose("/World/Cameras/Main")
    assert pose is not None and pose.up_axis == "Z"
    assert adapter.read_camera_pose("/World/Geometry/BlueCube") is None


def test_camera_choices_never_build_the_full_stage_value_cache(
    opened,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog discovery copies only type metadata and catalog-owned columns."""

    import ovui_data_adapters.ovstage._scene as scene_module

    _session, scene, adapter = opened
    scene._ovui_native_catalog_cache = None

    def reject_full_value_cache(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("camera discovery attempted the full-stage value cache")

    monkeypatch.setattr(scene_module, "_kit_stage_cache", reject_full_value_cache)

    assert [item.path for item in adapter.list_cameras()] == [
        "/World/Cameras/Closeup",
        "/World/Cameras/Main",
    ]


def test_referenced_camera_keeps_its_exact_native_world_transform(opened) -> None:
    _session, scene, _adapter = opened

    camera = native_catalog_snapshot(scene).prim("/World/Cameras/Main")

    assert camera is not None
    matrix = camera.value("worldMatrix")
    assert matrix is not None
    assert len(matrix) == 16
    assert matrix[12:15] == pytest.approx((-6.0, -8.0, 5.0))


def test_render_target_catalog_preserves_native_relationship_order(opened) -> None:
    _session, _scene, adapter = opened
    catalog = adapter.get_render_target_catalog()
    assert [target.render_product_path for target in catalog.targets] == [
        "/Render/Products/CloseupCamera",
        "/Render/Products/MainCamera",
        "/Render/Products/RoofLidar",
    ]
    main = catalog.targets[1]
    assert main.source_path == "/World/Cameras/Main"
    assert main.output_names == ("LdrColor", "DistanceToCameraSD")
    assert main.output_kind is RenderTargetOutputKind.MULTI_OUTPUT
    assert main.resolution == (1280, 720)
    assert main.kind is RenderTargetKind.CAMERA
    lidar = catalog.targets[2]
    assert lidar.kind is RenderTargetKind.RENDER_PRODUCT
    assert lidar.source_path is None
    assert lidar.enabled is False
    assert lidar.output_names == ("PointCloud",)
    assert lidar.output_kind is RenderTargetOutputKind.POINT_CLOUD


def test_render_var_catalog_uses_exact_product_targets(opened) -> None:
    _session, scene, _adapter = opened
    renderer = _renderer_for(scene, "/Render/Products/MainCamera")
    catalog = renderer.list_render_var_outputs("/Render/Products/MainCamera")
    assert len(catalog.outputs) == 1
    output = catalog.outputs[0]
    assert output.render_var_name == "DistanceToCameraSD"
    assert output.output_kind is RenderVarOutputKind.SCALAR_DEPTH
    assert output.dtype == "float32"
    assert output.metadata["source_path"] == "/Render/Vars/DistanceToCamera"
    assert not hasattr(renderer, "_renderer")
    assert not hasattr(renderer, "_runtime_root_path")


def test_aov_authoring_catalog_is_version_qualified_and_excludes_broken_outputs(
    opened,
) -> None:
    _session, scene, _adapter = opened
    renderer = _renderer_for(scene, "/Render/Products/MainCamera")
    renderer._ovrtx_version = (0, 4, 0)
    catalog = renderer.get_aov_authoring_catalog()
    assert catalog.enabled is True
    assert catalog.output("normal").source_name == "NormalSD"
    assert {output.source_name for output in catalog.outputs}.isdisjoint(
        {"DepthSD", "SemanticIdMap", "LdrColor"}
    )

    renderer._ovrtx_version = (0, 5, 0)
    unsupported = renderer.get_aov_authoring_catalog()
    assert unsupported.enabled is False
    assert unsupported.outputs == ()


def test_render_var_catalog_tracks_native_product_mode_compatibility(opened) -> None:
    _session, scene, _adapter = opened
    product_path = "/Render/Products/MainCamera"
    renderer = _renderer_for(scene, product_path)
    mode = NativeValueDescriptor(
        name="omni:rtx:rendermode",
        dtype=(1, 64, 1),
        semantic=2,
        native_is_array=False,
        logical_is_array=False,
    )
    command = NativeValueEditCommand(
        scene,
        (product_path,),
        mode,
        (MISSING,),
        ("PathTracing",),
        source="test:render-mode",
    )

    command.do()
    path_tracing = renderer.list_render_var_outputs(product_path).outputs[0]
    assert path_tracing.render_var_name == "DistanceToCameraSD"
    assert path_tracing.is_available is False
    assert path_tracing.disabled_reason == "Requires Real-Time 2.0."

    command.undo()
    real_time = renderer.list_render_var_outputs(product_path).outputs[0]
    assert real_time.render_var_name == "DistanceToCameraSD"
    assert real_time.is_available is True


def test_point_cloud_catalog_is_truthfully_disabled_without_native_channels(opened) -> None:
    _session, scene, _adapter = opened
    renderer = _renderer_for(scene, "/Render/Products/RoofLidar")
    catalog = renderer.list_point_cloud_outputs("/Render/Products/RoofLidar")
    assert len(catalog.outputs) == 1
    output = catalog.outputs[0]
    assert output.render_var_name == "PointCloud"
    assert output.source_sensor_path is None
    assert output.source_sensor_type == ""
    assert output.channels == ()
    assert output.is_available is False
    assert "no complete PointCloud channel catalog" in output.disabled_reason


def test_catalog_snapshots_are_owned_cached_and_read_only(opened) -> None:
    _session, scene, adapter = opened
    stage = scene._stage
    ordinal = int(stage.current_ordinal)
    first = adapter.get_render_target_catalog()
    second = adapter.get_render_target_catalog()
    assert first == second
    assert first.targets is not second.targets
    assert int(stage.current_ordinal) == ordinal
    assert getattr(scene, "_ovui_native_catalog_cache")[1].prims


class _PhysicsStage:
    current_ordinal = 5

    def __init__(self, schemas: tuple[str, ...]) -> None:
        self.schemas = schemas
        self.calls = 0

    def query_prims(self, ordinal: int, applied_schemas: list[str]):
        assert ordinal == 5
        assert applied_schemas == ["PhysicsRigidBodyAPI"]
        self.calls += 1
        return {
            "groups": (
                {
                    "prim_list_handle": 7,
                    "applied_schemas": self.schemas,
                },
            )
        }

    def get_prim_paths(self, handle: int):
        assert handle == 7
        return ("/World/Pretender", "/World/Body")

    def read_attribute_info(self, path: str, name: str):
        del path, name
        return None


class _PhysicsScene:
    current_ordinal = 5

    def __init__(self, stage: Any) -> None:
        self._stage = stage


def test_physics_schema_filter_fails_closed_when_compatibility_query_ignores_it() -> None:
    stage = _PhysicsStage(())
    with pytest.raises(RuntimeError, match="no PhysicsRigidBodyAPI"):
        _discover_rigid_body_paths(_PhysicsScene(stage))
    assert stage.calls == 1


def test_physics_schema_filter_accepts_only_positive_native_schema_evidence() -> None:
    stage = _PhysicsStage(("PhysicsRigidBodyAPI",))
    assert _discover_rigid_body_paths(_PhysicsScene(stage)) == (
        "/World/Pretender",
        "/World/Body",
    )


class _Snapshot:
    ordinal = 3
    topology_version = 4
    topology_revision = 5

    def __init__(self, prims: tuple[Any, ...]) -> None:
        self.prims = prims

    def prim(self, path: str) -> Any | None:
        return next((prim for prim in self.prims if prim.path == path), None)

    def paths_of_type(self, *type_names: str) -> tuple[str, ...]:
        accepted = {name.lower() for name in type_names}
        return tuple(prim.path for prim in self.prims if prim.type_name.lower() in accepted)


def _prim(path: str, type_name: str, **properties: Any) -> Any:
    return SimpleNamespace(
        path=path,
        type_name=type_name,
        value=lambda name, default=None: properties.get(name, default),
    )


def test_adversarial_names_and_wrong_relationship_types_never_create_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ovui_data_adapters.ovstage.stage_adapter as stage_module

    snapshot = _Snapshot(
        (
            _prim("/World/Camera", "Xform"),
            _prim("/World/Real", "Camera"),
            _prim("/Render/Beauty", "Xform"),
            _prim(
                "/Render/Product",
                "RenderProduct",
                camera=("/World/Camera",),
                orderedVars=("/Render/Beauty",),
                resolution=(-1, 0),
            ),
        ),
    )
    monkeypatch.setattr(
        stage_module,
        "native_catalog_snapshot",
        lambda _scene: snapshot,
        raising=False,
    )
    adapter = stage_module.OvstageStageAdapter(object())
    catalog = adapter.get_render_target_catalog()
    assert len(catalog.targets) == 1
    assert catalog.targets[0].enabled is False
    assert {warning.code for warning in catalog.targets[0].warnings} == {
        "invalid_render_var",
        "wrong_source_type",
    }
    assert catalog.targets[0].resolution is None


def test_grounded_point_channel_and_unknown_render_var_policies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ovui_data_adapters.ovstage.renderer_adapter as renderer_module

    snapshot = _Snapshot(
        (
            _prim("/World/Sensor", "OmniLidar", worldMatrix=tuple(range(16))),
            _prim(
                "/Render/Product",
                "RenderProduct",
                camera=("/World/Sensor",),
                orderedVars=("/Render/PointCloud", "/Render/Unknown"),
            ),
            _prim(
                "/Render/PointCloud",
                "RenderVar",
                sourceName="PointCloud",
                channels=("Coordinates", "Counts", "MadeUp"),
            ),
            _prim("/Render/Unknown", "RenderVar", sourceName="NovelOutput"),
        ),
    )
    monkeypatch.setattr(
        renderer_module,
        "native_catalog_snapshot",
        lambda _scene: snapshot,
        raising=False,
    )
    renderer = _renderer_for(object(), "/Render/Product")
    point = renderer.list_point_cloud_outputs("/Render/Product").outputs[0]
    assert point.channel_names == ("Coordinates", "Counts")
    assert point.is_available is True
    unknown = renderer.list_render_var_outputs("/Render/Product").outputs[0]
    assert unknown.render_var_name == "NovelOutput"
    assert unknown.output_kind is RenderVarOutputKind.UNKNOWN
    assert unknown.is_available is False

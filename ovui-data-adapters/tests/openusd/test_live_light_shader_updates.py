# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Light/shader value edits and presence metadata update ovrtx without a reload."""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from pxr import Gf, Sdf, Usd, UsdLux, UsdShade

from ovui_data_adapters.common.adapters import ChangeEvent, ChangeEventType
from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter


@pytest.fixture
def stage():
    stage = Usd.Stage.CreateInMemory()
    key = UsdLux.RectLight.Define(stage, "/World/Key")
    key.CreateIntensityAttr(1000)
    key.CreateColorAttr(Gf.Vec3f(1, 1, 1))
    key.CreateColorTemperatureAttr(6500)
    key.CreateEnableColorTemperatureAttr(False)
    key.CreateExposureAttr(0)
    UsdLux.SphereLight.Define(stage, "/World/Bulb").CreateRadiusAttr(0.5)
    material = UsdShade.Material.Define(stage, "/World/Looks/Mat")
    surface = UsdShade.Shader.Define(stage, "/World/Looks/Mat/Surface")
    surface.CreateIdAttr("UsdPreviewSurface")
    surface.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.5, 0.5, 0.5))
    surface.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.5)
    surface.CreateInput("useSpecularWorkflow", Sdf.ValueTypeNames.Int).Set(0)
    texture = UsdShade.Shader.Define(stage, "/World/Looks/Mat/Tex")
    texture.CreateInput("file", Sdf.ValueTypeNames.Asset).Set("./wood.png")
    connected = UsdShade.Shader.Define(stage, "/World/Looks/Mat/Mix")
    connected.CreateInput("roughness", Sdf.ValueTypeNames.Float).ConnectToSource(
        surface.ConnectableAPI(), "roughness"
    )
    participant = stage.DefinePrim("/Participants/worker1", "Xform")
    participant.CreateAttribute("worldview:position", Sdf.ValueTypeNames.Double3).Set((0, 0, 0))
    material.GetPrim()
    return stage


def adapter_for(stage):
    adapter = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    adapter._stage = stage
    adapter._renderer = SimpleNamespace(write_attribute=Mock())
    adapter._render_product_path = None
    adapter._stop_native_frame_pacing = Mock()
    adapter._reload_live_root_snapshot = Mock(return_value=True)
    adapter._sync_ovrtx_root_snapshot_overlay_from_stage = Mock(return_value=True)
    adapter._write_prim_transform_to_ovrtx = Mock(return_value=True)
    # A collaborating host declares its presence metadata as non-rendering.
    adapter.non_rendering_property_prefixes = ("worldview:",)
    return adapter


def decide(adapter, *paths):
    return adapter._stage_change_sync_decision(SimpleNamespace(), paths, (), Sdf)


@pytest.mark.parametrize(
    "path",
    [
        "/World/Key.inputs:intensity",
        "/World/Key.inputs:exposure",
        "/World/Key.inputs:color",
        "/World/Key.inputs:colorTemperature",
        "/World/Key.inputs:enableColorTemperature",
        "/World/Bulb.inputs:radius",
        "/World/Looks/Mat/Surface.inputs:diffuseColor",
        "/World/Looks/Mat/Surface.inputs:roughness",
        "/World/Looks/Mat/Surface.inputs:useSpecularWorkflow",
        "/Participants/worker1.worldview:position",
    ],
)
def test_value_edits_on_existing_lights_shaders_and_presence_are_live(stage, path):
    assert decide(adapter_for(stage), path) == "live"


@pytest.mark.parametrize(
    "path",
    [
        "/World/Looks/Mat/Tex.inputs:file",  # asset-valued input
        "/World/Looks/Mat/Mix.inputs:roughness",  # connected input
        "/World/Looks/Mat/Surface.info:id",  # shader identity
        "/World/Key.inputs:missing",  # does not compose
    ],
)
def test_asset_connected_and_identity_edits_stay_structural(stage, path):
    assert decide(adapter_for(stage), path) == "reload"


def test_material_binding_stays_structural(stage):
    from pxr import UsdGeom

    UsdGeom.Cube.Define(stage, "/World/Cube")
    UsdShade.MaterialBindingAPI.Apply(stage.GetPrimAtPath("/World/Cube")).Bind(
        UsdShade.Material(stage.GetPrimAtPath("/World/Looks/Mat"))
    )
    assert decide(adapter_for(stage), "/World/Cube.material:binding") == "reload"


def test_live_writes_use_the_exact_attribute_dtype(stage):
    adapter = adapter_for(stage)
    stage.GetAttributeAtPath("/World/Key.inputs:intensity").Set(2000)
    stage.GetAttributeAtPath("/World/Key.inputs:color").Set(Gf.Vec3f(1, 0.5, 0.25))
    stage.GetAttributeAtPath("/World/Key.inputs:enableColorTemperature").Set(True)
    stage.GetAttributeAtPath("/World/Looks/Mat/Surface.inputs:useSpecularWorkflow").Set(1)
    adapter.notify_stage_changed(
        ChangeEvent(
            changed_paths=(
                "/World/Key.inputs:intensity",
                "/World/Key.inputs:color",
                "/World/Key.inputs:enableColorTemperature",
                "/World/Looks/Mat/Surface.inputs:useSpecularWorkflow",
                "/Participants/worker1.worldview:position",
            ),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        )
    )
    adapter._reload_live_root_snapshot.assert_not_called()
    writes = {
        call.kwargs["attribute_name"]: call.kwargs["tensor"]
        for call in adapter._renderer.write_attribute.call_args_list
        if "attribute_name" in call.kwargs
    }
    # OVRTX rejects float64 for float attributes; each payload matches USD.
    assert writes["inputs:intensity"].dtype == np.float32
    assert writes["inputs:intensity"].tolist() == [2000.0]
    assert writes["inputs:color"].dtype == np.float32 and writes["inputs:color"].shape == (1, 3)
    assert writes["inputs:enableColorTemperature"].dtype == np.bool_
    assert writes["inputs:useSpecularWorkflow"].dtype == np.int32
    # Presence metadata is not rendered and is never sent to the renderer.
    assert "worldview:position" not in writes


def test_rejected_live_write_falls_back_to_a_reload(stage):
    adapter = adapter_for(stage)
    adapter._renderer.write_attribute.side_effect = RuntimeError("unsupported attribute")
    adapter.notify_stage_changed(
        ChangeEvent(
            changed_paths=("/World/Key.inputs:intensity",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        )
    )
    adapter._reload_live_root_snapshot.assert_called_once()


def test_public_decision_matches_notify(stage):
    adapter = adapter_for(stage)
    live = ChangeEvent(("/World/Key.inputs:intensity",), (), ChangeEventType.INFO_CHANGE)
    structural = ChangeEvent(("/World/Looks/Mat/Tex.inputs:file",), (), ChangeEventType.INFO_CHANGE)
    assert adapter.stage_change_sync_decision(live) == "live"
    assert adapter.stage_change_sync_decision(structural) == "reload"


@pytest.mark.parametrize(
    "property_path, live",
    [
        ("/Key.inputs:intensity", True),
        ("/Key.inputs:color", True),
        ("/Look/Shader.inputs:roughness", True),
        ("/Cam.focalLength", True),
        ("/Cube.xformOp:translate", True),
        ("/Cube.visibility", True),
        ("/Cube.size", True),
        ("/Cube.purpose", False),
        ("/Key.inputs:texture:file", False),
        ("/Cube", False),
    ],
)
def test_property_updates_live_matches_the_stage_change_classifier(property_path, live):
    from pxr import Sdf, Usd, UsdGeom, UsdLux, UsdShade

    stage = Usd.Stage.CreateInMemory()
    light = UsdLux.RectLight.Define(stage, "/Key")
    light.CreateIntensityAttr(4000)
    light.CreateColorAttr((1, 1, 1))
    light.CreateTextureFileAttr("./tex.png")
    shader = UsdShade.Shader.Define(stage, "/Look/Shader")
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.5)
    UsdGeom.Camera.Define(stage, "/Cam").CreateFocalLengthAttr(35)
    cube = UsdGeom.Cube.Define(stage, "/Cube")
    cube.CreateSizeAttr(1.0)
    renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    renderer._stage = stage
    assert renderer.property_updates_live(property_path) is live


def test_live_camera_lens_write_forces_the_viewport_intrinsics_again():
    from pxr import UsdGeom

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Camera.Define(stage, "/Views/primary").CreateFocalLengthAttr(24.0)
    adapter = adapter_for(stage)
    # The render loop pushed viewport-fitted intrinsics for this camera.
    adapter._last_pushed_camera_intrinsics = ("/Views/primary", 24.0, 20.955, 11.79)
    adapter.notify_stage_changed(
        ChangeEvent(("/Views/primary.focalLength",), (), ChangeEventType.INFO_CHANGE)
    )
    # The live write mirrored the authored lens (with its 4:3 aperture) into
    # ovrtx: the next frame must push the viewport-fitted intrinsics again.
    assert adapter._last_pushed_camera_intrinsics is None


def test_camera_center_of_interest_never_reloads_the_scene(stage):
    """The viewport's camera writer authors omni:kit:centerOfInterest after every navigation
    gesture; it is Kit UI metadata, so it must not reload the renderer (a ~0.55 s freeze)."""
    from pxr import UsdGeom

    camera = UsdGeom.Camera.Define(stage, "/OvuiViews/Cameras/primary").GetPrim()
    camera.CreateAttribute("omni:kit:centerOfInterest", Sdf.ValueTypeNames.Double3, custom=True).Set((0, 0, -5))
    adapter = adapter_for(stage)
    adapter.non_rendering_property_prefixes = ()  # also without any host-declared prefixes
    assert decide(adapter, "/OvuiViews/Cameras/primary.omni:kit:centerOfInterest") == "live"
    assert adapter.property_updates_live("/OvuiViews/Cameras/primary.omni:kit:centerOfInterest")


@pytest.mark.parametrize(
    "prim_type, attribute, expected",
    [
        ("Cube", "size", "live"),
        ("Sphere", "radius", "live"),
        ("Cylinder", "radius", "live"),
        ("Cylinder", "height", "live"),
        ("Cone", "height", "live"),
        ("Capsule", "radius", "live"),
        ("Cylinder", "axis", "reload"),  # token, not a size
        ("Cube", "purpose", "reload"),
        ("Mesh", "extent", "reload"),
    ],
)
def test_implicit_shape_sizes_are_live_and_other_geometry_reloads(prim_type, attribute, expected):
    from pxr import Usd

    stage = Usd.Stage.CreateInMemory()
    prim = stage.DefinePrim("/Shape", prim_type)
    if prim_type == "Mesh":
        prim.CreateAttribute("extent", Sdf.ValueTypeNames.Float3Array).Set([(0, 0, 0), (1, 1, 1)])
    adapter = adapter_for(stage)
    assert decide(adapter, f"/Shape.{attribute}") == expected


def test_a_custom_size_attribute_on_another_prim_type_stays_structural():
    from pxr import Usd

    stage = Usd.Stage.CreateInMemory()
    stage.DefinePrim("/Other", "Xform").CreateAttribute("size", Sdf.ValueTypeNames.Double, custom=True).Set(1.0)
    adapter = adapter_for(stage)
    assert decide(adapter, "/Other.size") == "reload"


def test_a_cube_size_edit_is_written_as_float64_without_a_reload():
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Cube.Define(stage, "/Cube").CreateSizeAttr(2.0)
    adapter = adapter_for(stage)
    stage.GetAttributeAtPath("/Cube.size").Set(2.98)
    adapter.notify_stage_changed(
        ChangeEvent(("/Cube.size",), (), ChangeEventType.INFO_CHANGE)
    )
    adapter._reload_live_root_snapshot.assert_not_called()
    (call,) = adapter._renderer.write_attribute.call_args_list
    assert call.kwargs["attribute_name"] == "size"
    assert call.kwargs["prim_paths"] == ["/Cube"]
    assert call.kwargs["tensor"].dtype == np.float64
    assert call.kwargs["tensor"].tolist() == [2.98]


def _point_instancer_stage(cube_path):
    from pxr import UsdGeom

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Cube.Define(stage, cube_path).CreateSizeAttr(1.0)
    instancer = UsdGeom.PointInstancer.Define(stage, "/World/Instancer")
    instancer.CreatePrototypesRel().SetTargets([cube_path])
    instancer.CreateProtoIndicesAttr([0, 0])
    instancer.CreatePositionsAttr([(-2, 0, 0), (2, 0, 0)])
    return stage


@pytest.mark.parametrize(
    "cube_path", ["/World/Instancer/Prototypes/Cube", "/World/Cube"]
)
def test_a_size_edit_of_a_point_instancer_prototype_reloads_the_scene(cube_path):
    # ovrtx draws the instances from a copy of the prototype: a live write to
    # the Cube left both instances at the old size.
    stage = _point_instancer_stage(cube_path)
    adapter = adapter_for(stage)
    stage.GetAttributeAtPath(f"{cube_path}.size").Set(2.0)
    adapter.notify_stage_changed(
        ChangeEvent((f"{cube_path}.size",), (), ChangeEventType.INFO_CHANGE)
    )
    adapter._reload_live_root_snapshot.assert_called_once()
    adapter._renderer.write_attribute.assert_not_called()


def test_a_shape_that_becomes_a_prototype_reloads_on_its_next_size_edit():
    from pxr import UsdGeom

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Cube.Define(stage, "/World/Cube").CreateSizeAttr(1.0)
    instancer = UsdGeom.PointInstancer.Define(stage, "/World/Instancer")
    adapter = adapter_for(stage)
    assert decide(adapter, "/World/Cube.size") == "live"
    instancer.CreatePrototypesRel().SetTargets(["/World/Cube"])
    adapter.notify_stage_changed(
        ChangeEvent(("/World/Instancer.prototypes",), (), ChangeEventType.INFO_CHANGE)
    )
    assert decide(adapter, "/World/Cube.size") == "reload"


def test_a_failed_shape_size_write_is_reported_and_reloads_the_scene(capsys):
    from pxr import UsdGeom

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Cube.Define(stage, "/Cube").CreateSizeAttr(2.0)
    adapter = adapter_for(stage)
    adapter._renderer.write_attribute.side_effect = RuntimeError("size refused")
    stage.GetAttributeAtPath("/Cube.size").Set(3.0)
    adapter.notify_stage_changed(
        ChangeEvent(("/Cube.size",), (), ChangeEventType.INFO_CHANGE)
    )
    adapter._reload_live_root_snapshot.assert_called_once()
    error = capsys.readouterr().err
    assert "/Cube.size" in error and "RuntimeError: size refused" in error

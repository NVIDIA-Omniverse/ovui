# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for Create menu USD authoring defaults."""

from types import SimpleNamespace

import pytest
from pxr import Usd, UsdGeom, UsdShade

from ovui_widgets.app import create_menu


def _stage(up_axis: str = "Y", meters_per_unit: float = 0.01):
    stage = Usd.Stage.CreateInMemory()
    token = UsdGeom.Tokens.y if up_axis == "Y" else UsdGeom.Tokens.z
    UsdGeom.SetStageUpAxis(stage, token)
    UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
    return stage


def _app(stage):
    return SimpleNamespace(_stage=stage)


def _attr_tuple(prim, attr_name: str):
    value = prim.GetAttribute(attr_name).Get()
    return tuple(float(component) for component in value)


def test_mesh_prims_are_offset_above_ground_and_shapes_keep_standard_defaults():
    stage = _stage("Y", 0.01)
    app = _app(stage)

    cube = create_menu.create_mesh_prim(app, "Cube")
    torus = create_menu.create_mesh_prim(app, "Torus")
    disk = create_menu.create_mesh_prim(app, "Disk")
    shape_cube = create_menu.create_shape_prim(app, "Cube")

    assert _attr_tuple(cube, "xformOp:translate") == pytest.approx((0.0, 50.0, 0.0))
    assert _attr_tuple(torus, "xformOp:translate") == pytest.approx((0.0, 25.0, 0.0))
    assert _attr_tuple(disk, "xformOp:translate") == pytest.approx((0.0, 0.0, 0.0))
    assert shape_cube.GetTypeName() == "Cube"
    assert _attr_tuple(shape_cube, "xformOp:translate") == pytest.approx((0.0, 0.0, 0.0))
    assert shape_cube.GetAttribute("size").Get() == pytest.approx(100.0)
    assert shape_cube.GetAttribute("extent").Get() == [
        (-50.0, -50.0, -50.0),
        (50.0, 50.0, 50.0),
    ]


def test_mesh_above_ground_offset_respects_z_up_and_stage_units():
    stage = _stage("Z", 1.0)
    prim = create_menu.create_mesh_prim(_app(stage), "Sphere")

    assert _attr_tuple(prim, "xformOp:translate") == pytest.approx((0.0, 0.0, 0.5))


def test_create_mesh_prim_uses_canonical_adapter_topology():
    stage = _stage()
    prim = create_menu.create_mesh_prim(_app(stage), "Cube")
    mesh = UsdGeom.Mesh(prim)

    assert mesh
    assert mesh.GetPointsAttr().Get()
    assert mesh.GetFaceVertexIndicesAttr().Get()
    assert mesh.GetFaceVertexCountsAttr().Get()
    assert mesh.GetSubdivisionSchemeAttr().Get() == "none"


def test_light_and_camera_helpers_create_canonical_schema_prims():
    y_up_stage = _stage("Y", 0.01)
    y_up_app = _app(y_up_stage)
    sun = create_menu.create_light_prim(y_up_app, "DistantLight")
    sphere = create_menu.create_light_prim(y_up_app, "SphereLight")
    dome = create_menu.create_light_prim(y_up_app, "DomeLight")

    assert sun.GetTypeName() == "DistantLight"
    assert sphere.GetTypeName() == "SphereLight"
    assert dome.GetTypeName() == "DomeLight"

    z_up_stage = _stage("Z", 0.01)
    z_up_app = _app(z_up_stage)
    camera = create_menu.create_camera(z_up_app)
    rect = create_menu.create_light_prim(z_up_app, "RectLight")
    distant = create_menu.create_light_prim(z_up_app, "DistantLight")
    z_dome = create_menu.create_light_prim(z_up_app, "DomeLight")

    assert camera.GetTypeName() == "Camera"
    assert rect.GetTypeName() == "RectLight"
    assert distant.GetTypeName() == "DistantLight"
    assert z_dome.GetTypeName() == "DomeLight"


def test_preview_surface_material_connects_surface_and_displacement_outputs():
    stage = _stage()
    material_prim = create_menu.create_usd_preview_surface_material(_app(stage))
    material = UsdShade.Material(material_prim)

    surface = material.GetSurfaceOutput()
    displacement = material.GetDisplacementOutput()

    assert surface.HasConnectedSource()
    assert displacement.HasConnectedSource()


def test_preview_surface_material_binds_to_selected_prim():
    stage = _stage()
    cube = create_menu.create_mesh_prim(_app(stage), "Cube")
    snapshot = SimpleNamespace(paths=lambda: (str(cube.GetPath()),))
    app = SimpleNamespace(_stage=stage, selection_bus=SimpleNamespace(get_snapshot=lambda: snapshot, publish=lambda *a, **k: None))

    material_prim = create_menu.create_usd_preview_surface_material(app)
    bound, _relationship = UsdShade.MaterialBindingAPI(cube).ComputeBoundMaterial()

    assert bound.GetPrim().GetPath() == material_prim.GetPath()


def _selection_app(stage, *paths):
    snapshot = SimpleNamespace(paths=lambda: paths)
    published = []
    bus = SimpleNamespace(get_snapshot=lambda: snapshot, publish=lambda paths, **_k: published.append(list(paths)))
    return SimpleNamespace(_stage=stage, selection_bus=bus), published


def _instance_proxy(stage):
    UsdGeom.Cube.Define(stage, "/World/Proto/Cube")
    instance = UsdGeom.Xform.Define(stage, "/World/Instance").GetPrim()
    instance.GetReferences().AddInternalReference("/World/Proto")
    instance.SetInstanceable(True)
    proxy = stage.GetPrimAtPath("/World/Instance/Cube")
    assert proxy.IsInstanceProxy()
    return proxy


def _materials(stage):
    return [str(prim.GetPath()) for prim in stage.Traverse() if prim.IsA(UsdShade.Material)]


def test_preview_surface_material_with_an_instance_proxy_selected_creates_the_material(capsys):
    stage = _stage()
    proxy = _instance_proxy(stage)
    app, published = _selection_app(stage, str(proxy.GetPath()))

    material_prim = create_menu.create_usd_preview_surface_material(app)

    assert material_prim is not None
    assert _materials(stage) == [str(material_prim.GetPath())]
    assert not UsdShade.MaterialBindingAPI(proxy).ComputeBoundMaterial()[0]
    assert published == [[str(material_prim.GetPath())]]
    error = capsys.readouterr().err
    assert "Create and bind material core_material.usd_preview_surface was refused" in error
    assert "instance proxy" in error
    assert "Creating the material without a binding" in error


def test_preview_surface_material_binds_the_selected_prims_that_are_not_instance_proxies(capsys):
    stage = _stage()
    proxy = _instance_proxy(stage)
    cube = create_menu.create_mesh_prim(_app(stage), "Cube")
    app, _published = _selection_app(stage, str(proxy.GetPath()), str(cube.GetPath()))

    material_prim = create_menu.create_usd_preview_surface_material(app)

    bound, _relationship = UsdShade.MaterialBindingAPI(cube).ComputeBoundMaterial()
    assert bound.GetPrim().GetPath() == material_prim.GetPath()
    assert not UsdShade.MaterialBindingAPI(proxy).ComputeBoundMaterial()[0]
    error = capsys.readouterr().err
    assert "Create and bind material core_material.usd_preview_surface did not bind 1 selected prim(s)" in error
    assert f"instance proxy, which cannot take a material binding, and was skipped: {proxy.GetPath()}" in error
    assert str(cube.GetPath()) not in error


def test_preview_surface_material_creates_the_material_after_a_failed_bind(monkeypatch, capsys):
    from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter

    def _fail_bind(self, material_prim, targets, binding_strength):
        raise RuntimeError("forced bind failure")

    monkeypatch.setattr(UsdStageAdapter, "_bind_core_material_to_targets", _fail_bind)
    stage = _stage()
    cube = create_menu.create_mesh_prim(_app(stage), "Cube")
    app, published = _selection_app(stage, str(cube.GetPath()))

    material_prim = create_menu.create_usd_preview_surface_material(app)

    assert material_prim is not None
    assert _materials(stage) == [str(material_prim.GetPath())]
    assert not UsdShade.MaterialBindingAPI(cube).ComputeBoundMaterial()[0]
    assert published == [[str(material_prim.GetPath())]]
    error = capsys.readouterr().err
    assert "Create and bind material core_material.usd_preview_surface was refused" in error
    assert "forced bind failure" in error
    assert "Creating the material without a binding" in error


def test_preview_surface_material_reports_a_rejected_bind_target(monkeypatch, capsys):
    from ovui_data_adapters.openusd import stage_adapter

    monkeypatch.setattr(
        stage_adapter,
        "_core_material_resolve_scope_path",
        lambda *_args: (None, "forced scope error", False),
    )
    stage = _stage()
    cube = create_menu.create_mesh_prim(_app(stage), "Cube")
    snapshot = SimpleNamespace(paths=lambda: (str(cube.GetPath()),))
    published = []
    bus = SimpleNamespace(get_snapshot=lambda: snapshot, publish=lambda paths, **_k: published.append(paths))
    app = SimpleNamespace(_stage=stage, selection_bus=bus)

    assert create_menu.create_usd_preview_surface_material(app) is None

    assert not [prim for prim in stage.Traverse() if prim.IsA(UsdShade.Material)]
    assert published == []
    error = capsys.readouterr().err
    assert "Create material core_material.usd_preview_surface failed" in error
    assert "forced scope error" in error

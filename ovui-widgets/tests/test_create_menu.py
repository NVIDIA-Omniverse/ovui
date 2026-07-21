# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

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

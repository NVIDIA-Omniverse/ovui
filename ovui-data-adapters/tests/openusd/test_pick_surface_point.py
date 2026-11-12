# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Pick world positions: renderer values when populated, USD ray casts otherwise."""

import math
from types import SimpleNamespace

import numpy as np
import pytest

from ovui_data_adapters.openusd import renderer_adapter as module
from pxr import Gf, Usd, UsdGeom


def gl_camera(eye, target, fovy=40.0, aspect=16 / 9, near=0.1, far=1000.0):
    """GL column-vector view and projection, as the viewport submits them."""
    eye, target = np.asarray(eye, float), np.asarray(target, float)
    forward = target - eye
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0, 0, 1.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    view = np.eye(4)
    view[0, :3], view[1, :3], view[2, :3] = right, up, -forward
    view[:3, 3] = -view[:3, :3] @ eye
    f = 1 / math.tan(math.radians(fovy) / 2)
    proj = np.zeros((4, 4))
    proj[0, 0], proj[1, 1] = f / aspect, f
    proj[2, 2], proj[2, 3] = (far + near) / (near - far), 2 * far * near / (near - far)
    proj[3, 2] = -1
    return view, proj


def ndc(view, proj, point):
    clip = proj @ view @ np.append(point, 1.0)
    return clip[0] / clip[3], clip[1] / clip[3]


@pytest.fixture
def stage():
    stage = Usd.Stage.CreateInMemory()
    cube = UsdGeom.Cube.Define(stage, "/Cube")
    cube.CreateSizeAttr(1.0)
    cube.AddTranslateOp().Set(Gf.Vec3d(-2, 0, 0.5))
    sphere = UsdGeom.Sphere.Define(stage, "/Sphere")
    sphere.CreateRadiusAttr(0.6)
    sphere.AddTranslateOp().Set(Gf.Vec3d(2, 0, 0.6))
    mesh = UsdGeom.Mesh.Define(stage, "/Floor")
    mesh.CreatePointsAttr([(-5, -5, 0), (5, -5, 0), (5, 5, 0), (-5, 5, 0)])
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    group = UsdGeom.Xform.Define(stage, "/Group")
    group.AddScaleOp().Set(Gf.Vec3f(2, 1, 1))
    UsdGeom.Cube.Define(stage, "/Group/Child").CreateSizeAttr(0.5)
    UsdGeom.Xform.Define(stage, "/NotGeometry")
    return stage


@pytest.mark.parametrize(
    "path, aim, on_surface",
    [
        ("/Cube", (-2, 0, 0.5), lambda p: np.isclose(np.abs(p - (-2, 0, 0.5)).max(), 0.5)),
        ("/Sphere", (2, 0, 0.6), lambda p: np.isclose(np.linalg.norm(p - (2, 0, 0.6)), 0.6)),
        ("/Floor", (1, 1, 0), lambda p: np.isclose(p[2], 0.0)),
        ("/Group/Child", (0, 0, 0), lambda p: np.isclose(max(abs(p[0]) / 2, abs(p[1]), abs(p[2])), 0.25)),
    ],
)
def test_ray_cast_returns_the_visible_surface_point_under_the_pixel(stage, path, aim, on_surface):
    view, proj = gl_camera((8, -12, 8), (0, 0, 0.5))
    x, y = ndc(view, proj, np.asarray(aim, float))
    point = module._pick_surface_point(stage, path, view, proj, x, y)
    assert point is not None
    point = np.asarray(point)
    assert on_surface(point)
    np.testing.assert_allclose(ndc(view, proj, point), (x, y), atol=1e-6)
    # The first surface along the ray faces the camera.
    assert np.linalg.norm(point - (8, -12, 8)) < np.linalg.norm(np.asarray(aim) - (8, -12, 8)) + 1e-9


@pytest.mark.parametrize("path", ["/NotGeometry", "/Missing"])
def test_ray_cast_is_unavailable_without_supported_geometry(stage, path):
    view, proj = gl_camera((8, -12, 8), (0, 0, 0.5))
    assert module._pick_surface_point(stage, path, view, proj, 0.0, 0.0) is None


def test_ray_that_misses_the_picked_prim_reports_no_point(stage):
    view, proj = gl_camera((8, -12, 8), (0, 0, 0.5))
    assert module._pick_surface_point(stage, "/Cube", view, proj, 0.95, 0.95) is None


class _Mapping:
    def __init__(self, normal):
        self.params = {
            "magic": np.array([module._PICK_HIT_BUFFER_MAGIC], dtype=np.uint32),
            "version": np.array([module._PICK_HIT_BUFFER_VERSION], dtype=np.uint32),
            "hitCount": np.array([1], dtype=np.uint32),
        }
        self._tensors = {
            "primPath": np.array([7], dtype=np.uint64),
            "worldPositionM": np.array([[0.0, 0.0, 0.0]]),
            "worldNormal": np.array([normal], dtype=np.float64),
        }

    def keys(self):
        return self._tensors.keys()

    def __getitem__(self, key):
        return self._tensors[key]


@pytest.mark.parametrize("normal, expected", [((0.0, 0.0, 0.0), None), ((0.0, 0.0, 1.0), (0.0, 0.0, 0.0))])
def test_unpopulated_renderer_positions_are_reported_unavailable(normal, expected):
    adapter = module.OvRtxRendererAdapter.__new__(module.OvRtxRendererAdapter)
    adapter._resolve_ovrtx_prim_path = lambda _id: "/Cube"
    assert adapter._parse_pick_hit_mapping(_Mapping(normal)) == [("/Cube", expected)]


def test_mixed_polygon_mesh_is_fan_triangulated():
    stage = Usd.Stage.CreateInMemory()
    mesh = UsdGeom.Mesh.Define(stage, "/Mesh")
    # A quad at z=0 and a triangle at z=1 whose footprints do not overlap.
    mesh.CreatePointsAttr([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (3, 0, 1), (4, 0, 1), (3, 1, 1)])
    mesh.CreateFaceVertexCountsAttr([4, 3])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3, 4, 5, 6])
    view, proj = gl_camera((2, -6, 6), (2, 0.5, 0.5))
    for aim, z in (((0.8, 0.8, 0), 0.0), ((3.2, 0.2, 1), 1.0)):
        x, y = ndc(view, proj, np.asarray(aim, float))
        point = module._pick_surface_point(stage, "/Mesh", view, proj, x, y)
        assert point is not None and np.isclose(point[2], z)

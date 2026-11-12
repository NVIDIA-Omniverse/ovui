# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""ovrtx composes ``omni:xform`` under the prim's parents; camera writes must be parent-local."""

import numpy as np
import pytest

from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter
from pxr import Gf, Usd, UsdGeom


def adapter(stage):
    renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    renderer._stage = stage
    return renderer


def world_tensor(eye):
    world = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(0, 3, 0.25), Gf.Vec3d(0, 0, 1)).GetInverse()
    return np.asarray(world, dtype=np.float64).reshape(1, 4, 4)


@pytest.mark.parametrize(
    "parent_ops",
    [
        [("translate", (0, -3, 0.4))],
        [("translate", (0, 3, 0)), ("scale", (2, 1, 1))],
        [("translate", (1, 2, 3)), ("rotateZ", 30.0), ("scale", (1, 2, 0.5))],
    ],
)
def test_parented_camera_receives_its_parent_local_matrix(parent_ops):
    stage = Usd.Stage.CreateInMemory()
    rig = UsdGeom.Xform.Define(stage, "/Rig")
    for kind, value in parent_ops:
        getattr(rig, f"Add{kind[0].upper()}{kind[1:]}Op")().Set(value)
    UsdGeom.Camera.Define(stage, "/Rig/Cam")
    world = world_tensor((0, -5, 2))
    local = adapter(stage)._runtime_camera_xform(world, "/Rig/Cam")
    parent = np.asarray(rig.ComputeLocalToWorldTransform(Usd.TimeCode.Default()))
    # USD row-vector convention: world = local * parentToWorld.
    np.testing.assert_allclose(local.reshape(4, 4) @ parent, world.reshape(4, 4), atol=1e-9)
    assert local.shape == (1, 4, 4) and local.flags["C_CONTIGUOUS"]


@pytest.mark.parametrize("path", ["/Cam", "/Identity/Cam", "/Reset/Cam", "/Missing"])
def test_world_matrix_is_written_unchanged_without_a_parent_transform(path):
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Camera.Define(stage, "/Cam")
    UsdGeom.Xform.Define(stage, "/Identity")
    UsdGeom.Camera.Define(stage, "/Identity/Cam")
    UsdGeom.Xform.Define(stage, "/Reset").AddTranslateOp().Set((5, 5, 5))
    UsdGeom.Camera.Define(stage, "/Reset/Cam").SetResetXformStack(True)
    world = world_tensor((0, -5, 2))
    assert adapter(stage)._runtime_camera_xform(world, path) is world

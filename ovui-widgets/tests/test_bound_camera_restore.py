# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""CI invariant: ``read_bound_camera`` resolves boundCamera Path 1 + Path 2.

Step 26 (Rev 4 §10.5 / pre-planning §10.3 scenario 6): the parser
:func:`ovui_data_adapters.openusd.bound_camera.read_bound_camera`
returns a :class:`BoundCameraPose` for stages that author
``customLayerData.cameraSettings.boundCamera`` (Path 1 — resolves to
an actual ``UsdGeom.Camera`` prim) or ``cameraSettings.Perspective``
(Path 2 — viewport-preset fallback when the named prim is absent).
Stages with neither yield ``None`` so the caller falls back to
bbox-based framing.

The Step 16 visual QA covered the round-trip; these unit tests pin
the parser's behavior at the data level so a future regression in
``customLayerData`` reading shows up in CI immediately.
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("pxr")

from ovui_data_adapters.common import BoundCameraPose
from ovui_data_adapters.openusd.bound_camera import read_bound_camera, read_camera_pose
from pxr import Gf, Sdf, Usd, UsdGeom

# ---------------------------------------------------------------------------
# Path 1: boundCamera resolves to a real Camera prim
# ---------------------------------------------------------------------------


def _stage_with_bound_camera_prim(
    eye=(0.0, 0.0, 10.0),
    coi=(0.0, 0.0, -10.0),
):
    """In-memory stage with a ``/World/Camera`` prim and a boundCamera entry."""
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.Xform.Define(stage, "/World")
    cam = UsdGeom.Camera.Define(stage, "/World/Camera")
    # Place the camera at ``eye`` looking down -Z.
    xformable = UsdGeom.Xformable(cam.GetPrim())
    xformable.AddTranslateOp().Set(Gf.Vec3d(*eye))
    # Author centerOfInterest so target derivation has data to work with.
    coi_attr = cam.GetPrim().CreateAttribute(
        "omni:kit:centerOfInterest", Sdf.ValueTypeNames.Vector3d
    )
    coi_attr.Set(Gf.Vec3d(*coi))
    cam.GetFocalLengthAttr().Set(50.0)
    cam.GetVerticalApertureAttr().Set(20.955)  # 35mm-equivalent vertical
    # Author cameraSettings.boundCamera in customLayerData.
    root_layer = stage.GetRootLayer()
    root_layer.customLayerData = {
        "cameraSettings": {
            "boundCamera": "/World/Camera",
        }
    }
    return stage


def test_path1_returns_pose_for_authored_bound_camera():
    """boundCamera → real prim → BoundCameraPose with eye + target + FOV."""
    stage = _stage_with_bound_camera_prim()
    pose = read_bound_camera(stage)
    assert pose is not None
    assert isinstance(pose, BoundCameraPose)
    assert pose.eye == pytest.approx((0.0, 0.0, 10.0))
    # Camera at +Z 10 with COI (0,0,-10) → target at world origin.
    assert pose.target == pytest.approx((0.0, 0.0, 0.0))
    assert pose.up_axis == "Y"
    assert pose.prim_path == "/World/Camera"
    # FOV: 2 * atan(20.955 / (2 * 50)) ≈ 23.7°
    expected_fov = 2.0 * math.degrees(math.atan(20.955 / (2.0 * 50.0)))
    assert pose.fov_degrees == pytest.approx(expected_fov, rel=1e-4)


def test_path1_uses_z_up_axis_when_authored():
    """Up-axis follows ``UsdGeom.GetStageUpAxis`` — caller uses it for orbit math."""
    stage = _stage_with_bound_camera_prim()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    pose = read_bound_camera(stage)
    assert pose is not None
    assert pose.up_axis == "Z"


def test_stage_adapter_reads_z_up_axis_without_bound_camera_metadata():
    """Stage up-axis is available even when no bound-camera pose exists."""
    from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.Xform.Define(stage, "/World")

    adapter = UsdStageAdapter(stage)

    assert adapter.read_bound_camera() is None
    assert adapter.read_stage_up_axis() == "Z"


def test_stage_adapter_defaults_to_y_up_axis():
    """USD default/effective up-axis remains Y for stages without Z metadata."""
    from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")

    assert UsdStageAdapter(stage).read_stage_up_axis() == "Y"


def test_read_camera_pose_returns_pose_for_explicit_camera_path():
    """Explicit camera selection reuses the same camera-prim pose math."""
    stage = _stage_with_bound_camera_prim(eye=(1.0, 2.0, 12.0), coi=(0.0, 0.0, -4.0))
    pose = read_camera_pose(stage, "/World/Camera")
    assert pose is not None
    assert isinstance(pose, BoundCameraPose)
    assert pose.eye == pytest.approx((1.0, 2.0, 12.0))
    assert pose.target == pytest.approx((1.0, 2.0, 8.0))
    assert pose.up_axis == "Y"
    assert pose.prim_path == "/World/Camera"


def test_read_camera_pose_returns_none_for_missing_path_even_with_preset():
    """Explicit camera reads do not use the bound-camera Perspective fallback."""
    stage = _stage_with_perspective_preset_only()
    assert read_camera_pose(stage, "/OmniverseKit_Persp") is None


def test_read_camera_pose_returns_none_for_non_camera_path():
    """Only real ``UsdGeom.Camera`` prims produce selectable camera poses."""
    stage = _stage_with_bound_camera_prim()
    UsdGeom.Xform.Define(stage, "/World/NotACamera")
    assert read_camera_pose(stage, "/World/NotACamera") is None


# ---------------------------------------------------------------------------
# Path 2: boundCamera names a missing prim → Perspective preset fallback
# ---------------------------------------------------------------------------


def _stage_with_perspective_preset_only(
    pos=(5.0, 7.0, 9.0), tgt=(0.0, 0.0, 0.0)
):
    """Stage where boundCamera names a non-existent prim but Perspective
    preset is authored — Kit's default OmniverseKit_Persp shape.
    """
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    root_layer = stage.GetRootLayer()
    root_layer.customLayerData = {
        "cameraSettings": {
            "boundCamera": "/OmniverseKit_Persp",  # not authored in this layer
            "Perspective": {
                "position": Gf.Vec3d(*pos),
                "target": Gf.Vec3d(*tgt),
            },
        }
    }
    return stage


def test_path2_falls_back_to_perspective_preset_when_prim_missing():
    """Missing prim → fallback uses the Perspective preset's pos/target."""
    stage = _stage_with_perspective_preset_only()
    pose = read_bound_camera(stage)
    assert pose is not None
    assert isinstance(pose, BoundCameraPose)
    assert pose.eye == pytest.approx((5.0, 7.0, 9.0))
    assert pose.target == pytest.approx((0.0, 0.0, 0.0))
    assert pose.up_axis == "Y"
    assert pose.fov_degrees == pytest.approx(45.0)
    # The fallback labels the prim_path so a debug overlay can show
    # it explicitly.
    assert "Perspective preset fallback" in pose.prim_path


def test_path2_returns_none_when_perspective_lacks_position_or_target():
    """Preset must carry both ``position`` and ``target`` to be usable."""
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    stage.GetRootLayer().customLayerData = {
        "cameraSettings": {
            "boundCamera": "/Missing",
            "Perspective": {"position": Gf.Vec3d(1, 2, 3)},  # no target
        }
    }
    assert read_bound_camera(stage) is None


# ---------------------------------------------------------------------------
# No-bound-camera case
# ---------------------------------------------------------------------------


def test_no_camera_settings_returns_none():
    """Stage without ``customLayerData.cameraSettings`` → ``None``."""
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    assert read_bound_camera(stage) is None


def test_empty_camera_settings_returns_none():
    """``cameraSettings`` present but empty → no bound camera, no preset → ``None``."""
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    stage.GetRootLayer().customLayerData = {"cameraSettings": {}}
    assert read_bound_camera(stage) is None

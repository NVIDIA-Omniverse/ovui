# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ovui_data_adapters.openusd._camera_writer.

Verifies that:
- View-matrix → camera world transform round-trips through USD within
  1e-5 tolerance.
- Projection-matrix decomposition and reconstruction round-trips
  within 1e-5.
- Identity view matrix places the camera at origin.
- Various FOV / aspect / near / far combinations decompose correctly.
- All writes land in the session layer; the root layer is unchanged.
- Idempotency — writing twice results in a single transform op and
  stable attribute values.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

pxr = pytest.importorskip("pxr")
from ovui_data_adapters.openusd._camera_writer import (  # noqa: E402
    _decompose_perspective,
    compute_camera_intrinsics,
    write_camera_from_matrices,
)
from ovui_data_adapters.openusd._session_authoring import ensure_camera  # noqa: E402
from pxr import Gf, Usd, UsdGeom  # noqa: E402

from ovwidgets.viewport.camera_controller import CameraController  # noqa: E402

CAMERA_PATH = "/OvGearSession/Cameras/Main"
TOL = 1e-5


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def stage():
    s = Usd.Stage.CreateInMemory()
    ensure_camera(s, CAMERA_PATH)
    return s


def _perspective(fovy_rad: float, aspect: float, near: float, far: float) -> np.ndarray:
    """Re-build a GL perspective matrix (mirror of CameraController._perspective)."""
    t = math.tan(fovy_rad / 2.0)
    m = np.zeros((4, 4), dtype=np.float64)
    m[0, 0] = 1.0 / (aspect * t)
    m[1, 1] = 1.0 / t
    m[2, 2] = -(far + near) / (far - near)
    m[2, 3] = -(2.0 * far * near) / (far - near)
    m[3, 2] = -1.0
    return m


def _gf_to_numpy_col_vector(m: Gf.Matrix4d) -> np.ndarray:
    """Gf (row-vector) → numpy (column-vector) = transpose."""
    arr = np.array([[m[i, j] for j in range(4)] for i in range(4)], dtype=np.float64)
    return arr.T


# ── _decompose_perspective ─────────────────────────────────────────────────


class TestDecomposePerspective:
    @pytest.mark.parametrize(
        "fovy_deg,aspect,near,far",
        [
            (45.0, 16.0 / 9.0, 0.01, 10000.0),
            (45.0, 1.0, 0.01, 10000.0),
            (60.0, 4.0 / 3.0, 0.1, 1000.0),
            (30.0, 2.0, 0.5, 500.0),
            (90.0, 1.777, 0.05, 50.0),
        ],
    )
    def test_roundtrip(self, fovy_deg, aspect, near, far):
        fovy = math.radians(fovy_deg)
        proj = _perspective(fovy, aspect, near, far)
        rt_fovy, rt_aspect, rt_near, rt_far = _decompose_perspective(proj)
        assert rt_fovy == pytest.approx(fovy, abs=TOL)
        assert rt_aspect == pytest.approx(aspect, abs=TOL)
        assert rt_near == pytest.approx(near, abs=TOL)
        assert rt_far == pytest.approx(far, abs=TOL)

    def test_matrix_reconstruction_roundtrip(self):
        proj = _perspective(math.radians(45.0), 16.0 / 9.0, 0.01, 10000.0)
        fovy, aspect, near, far = _decompose_perspective(proj)
        rebuilt = _perspective(fovy, aspect, near, far)
        assert np.allclose(proj, rebuilt, atol=TOL)

    def test_matches_camera_controller_defaults(self):
        """The real CameraController output round-trips fovy/aspect/near cleanly.

        ``far`` gets a loose tolerance: CameraController returns float32
        matrices, and for near=0.01 / far=10000 the entry ``proj[2,2] =
        -(f+n)/(f-n) ≈ -1.000002`` collapses to ~-1.0 under float32 rounding.
        A ~1-2% drift in the recovered far plane is therefore expected and
        harmless for rendering (the far plane only clips, it doesn't scale).
        """
        cc = CameraController()
        _, proj = cc.get_matrices(1920, 1080)
        fovy, aspect, near, far = _decompose_perspective(proj)
        assert fovy == pytest.approx(math.radians(45.0), abs=1e-4)
        assert aspect == pytest.approx(1920.0 / 1080.0, abs=1e-4)
        assert near == pytest.approx(0.01, abs=1e-4)
        assert far == pytest.approx(10000.0, rel=0.05)

    def test_rejects_non_square(self):
        with pytest.raises(ValueError, match="4x4"):
            _decompose_perspective(np.zeros((3, 3)))

    def test_rejects_orthographic(self):
        ortho = np.eye(4)
        # Orthographic matrices have proj[2,2] = -2/(f-n), small in magnitude.
        # But an identity matrix has proj[2,2]=1, which violates the A>1 check.
        with pytest.raises(ValueError):
            _decompose_perspective(ortho)

    def test_rejects_degenerate_zero_fov(self):
        proj = np.zeros((4, 4))
        proj[0, 0] = 0.0
        proj[1, 1] = 0.0
        with pytest.raises(ValueError):
            _decompose_perspective(proj)


# ── write_camera_from_matrices: world transform round-trip ─────────────────


class TestViewMatrixRoundTrip:
    def test_identity_view_places_camera_at_origin(self, stage):
        view = np.eye(4, dtype=np.float64)
        proj = _perspective(math.radians(45.0), 1.0, 0.01, 10000.0)
        write_camera_from_matrices(stage, CAMERA_PATH, view, proj, 512, 512)

        cam = UsdGeom.Camera(stage.GetPrimAtPath(CAMERA_PATH))
        xf = UsdGeom.Xformable(cam)
        gf_world = xf.GetLocalTransformation()
        translation = gf_world.ExtractTranslation()
        assert translation[0] == pytest.approx(0.0, abs=TOL)
        assert translation[1] == pytest.approx(0.0, abs=TOL)
        assert translation[2] == pytest.approx(0.0, abs=TOL)

    def test_view_from_camera_controller_roundtrip(self, stage):
        cc = CameraController()
        cc.state.target = [1.0, 2.0, 3.0]
        cc.state.distance = 7.5
        cc.state.azimuth = 0.6
        cc.state.elevation = 0.3
        view, proj = cc.get_matrices(1280, 720)

        write_camera_from_matrices(stage, CAMERA_PATH, view, proj, 1280, 720)

        # Read back via xformable; compare to inv(view) in column-vector form.
        xf = UsdGeom.Xformable(stage.GetPrimAtPath(CAMERA_PATH))
        gf_world = xf.GetLocalTransformation()
        world_read = _gf_to_numpy_col_vector(gf_world)
        world_expected = np.linalg.inv(np.asarray(view, dtype=np.float64))
        assert np.allclose(world_read, world_expected, atol=TOL)

    def test_translated_view_round_trips(self, stage):
        """Pure translation: camera at (10, 20, 30) looking down -Z."""
        view = np.eye(4, dtype=np.float64)
        view[0, 3] = -10.0  # view = inv(translate(10,20,30))
        view[1, 3] = -20.0
        view[2, 3] = -30.0
        proj = _perspective(math.radians(45.0), 1.0, 0.01, 10000.0)
        write_camera_from_matrices(stage, CAMERA_PATH, view, proj, 512, 512)

        xf = UsdGeom.Xformable(stage.GetPrimAtPath(CAMERA_PATH))
        gf_world = xf.GetLocalTransformation()
        t = gf_world.ExtractTranslation()
        assert t[0] == pytest.approx(10.0, abs=TOL)
        assert t[1] == pytest.approx(20.0, abs=TOL)
        assert t[2] == pytest.approx(30.0, abs=TOL)

    def test_camera_position_matches_eye(self, stage):
        """World transform translation equals CameraController eye position."""
        cc = CameraController()
        cc.state.target = [0.0, 0.0, 0.0]
        cc.state.distance = 10.0
        cc.state.azimuth = 0.0
        cc.state.elevation = 0.0
        view, proj = cc.get_matrices(100, 100)

        # Eye at (0, 0, 10) for az=0, el=0, distance=10.
        eye_expected = cc._get_eye()
        write_camera_from_matrices(stage, CAMERA_PATH, view, proj, 100, 100)

        xf = UsdGeom.Xformable(stage.GetPrimAtPath(CAMERA_PATH))
        t = xf.GetLocalTransformation().ExtractTranslation()
        assert t[0] == pytest.approx(float(eye_expected[0]), abs=TOL)
        assert t[1] == pytest.approx(float(eye_expected[1]), abs=TOL)
        assert t[2] == pytest.approx(float(eye_expected[2]), abs=TOL)


# ── write_camera_from_matrices: intrinsics ─────────────────────────────────


class TestIntrinsics:
    def test_focal_length_and_aperture_for_45_deg_16_9(self, stage):
        fovy = math.radians(45.0)
        aspect = 16.0 / 9.0
        proj = _perspective(fovy, aspect, 0.01, 10000.0)
        view = np.eye(4, dtype=np.float64)
        write_camera_from_matrices(stage, CAMERA_PATH, view, proj, 1920, 1080)

        cam = UsdGeom.Camera(stage.GetPrimAtPath(CAMERA_PATH))
        h_ap = cam.GetHorizontalApertureAttr().Get()
        v_ap = cam.GetVerticalApertureAttr().Get()
        focal = cam.GetFocalLengthAttr().Get()

        assert h_ap == pytest.approx(20.955, abs=TOL)
        assert v_ap == pytest.approx(20.955 / aspect, abs=TOL)

        # Reconstruct fovx from focal+h_ap, verify it matches expected fovx.
        fovx_expected = 2.0 * math.atan(math.tan(fovy / 2.0) * aspect)
        fovx_read = 2.0 * math.atan(0.5 * h_ap / focal)
        assert fovx_read == pytest.approx(fovx_expected, abs=TOL)

    def test_clipping_range_extraction(self, stage):
        near_in = 0.5
        far_in = 5000.0
        proj = _perspective(math.radians(60.0), 1.0, near_in, far_in)
        view = np.eye(4, dtype=np.float64)
        write_camera_from_matrices(stage, CAMERA_PATH, view, proj, 512, 512)

        cam = UsdGeom.Camera(stage.GetPrimAtPath(CAMERA_PATH))
        clip = cam.GetClippingRangeAttr().Get()
        assert clip[0] == pytest.approx(near_in, abs=1e-4)
        assert clip[1] == pytest.approx(far_in, abs=1e-2)

    @pytest.mark.parametrize(
        "fovy_deg,aspect",
        [
            (30.0, 1.0),
            (60.0, 1.777),
            (90.0, 2.0),
            (45.0, 0.5),  # tall aspect (portrait)
        ],
    )
    def test_various_fov_aspect_combos(self, stage, fovy_deg, aspect):
        fovy = math.radians(fovy_deg)
        proj = _perspective(fovy, aspect, 0.01, 10000.0)
        view = np.eye(4, dtype=np.float64)
        write_camera_from_matrices(stage, CAMERA_PATH, view, proj, 800, 600)

        cam = UsdGeom.Camera(stage.GetPrimAtPath(CAMERA_PATH))
        h_ap = cam.GetHorizontalApertureAttr().Get()
        v_ap = cam.GetVerticalApertureAttr().Get()
        focal = cam.GetFocalLengthAttr().Get()

        # Horizontal aperture is fixed.
        assert h_ap == pytest.approx(20.955, abs=TOL)
        # v_ap = h_ap / aspect by construction.
        assert v_ap == pytest.approx(h_ap / aspect, abs=TOL)
        # fovx recovery.
        fovx_expected = 2.0 * math.atan(math.tan(fovy / 2.0) * aspect)
        fovx_read = 2.0 * math.atan(0.5 * h_ap / focal)
        assert fovx_read == pytest.approx(fovx_expected, abs=1e-4)


# ── compute_camera_intrinsics (Issue #22) ─────────────────────────────────


class TestComputeCameraIntrinsics:
    """Pure-math helper that the renderer adapter pushes to ovrtx every
    frame. The aspect ratio in ``proj_matrix`` must round-trip into
    ``v_aperture = 20.955 / aspect`` so the rendered image and the
    SceneView overlay use the same camera at any widget aspect.
    """

    @pytest.mark.parametrize(
        "fovy_deg,aspect",
        [
            (45.0, 16.0 / 9.0),  # 1.778 — standard 16:9 (was bug repro)
            (45.0, 1.0),         # 1:1 square
            (45.0, 21.0 / 9.0),  # 2.333 — ultrawide
            (45.0, 9.0 / 16.0),  # 0.5625 — portrait
            (45.0, 1.5),         # arbitrary 3:2
            (45.0, 20.955 / 15.2908),  # 1.370 — the formerly-magic ratio
        ],
    )
    def test_v_aperture_tracks_aspect(self, fovy_deg, aspect):
        fovy = math.radians(fovy_deg)
        proj = _perspective(fovy, aspect, 0.01, 10000.0)
        focal, h_ap, v_ap, near, far = compute_camera_intrinsics(proj)
        assert h_ap == pytest.approx(20.955, abs=TOL)
        assert v_ap == pytest.approx(20.955 / aspect, abs=TOL)
        # focal length should reproduce the projection's horizontal FOV.
        fovx_expected = 2.0 * math.atan(math.tan(fovy / 2.0) * aspect)
        fovx_recovered = 2.0 * math.atan(0.5 * h_ap / focal)
        assert fovx_recovered == pytest.approx(fovx_expected, abs=1e-4)

    def test_near_far_passed_through(self):
        proj = _perspective(math.radians(60.0), 1.6, 0.5, 5000.0)
        focal, h_ap, v_ap, near, far = compute_camera_intrinsics(proj)
        assert near == pytest.approx(0.5, abs=1e-4)
        assert far == pytest.approx(5000.0, abs=1e-2)

    def test_returns_floats_not_ndarray_scalars(self):
        """Adapter pushes ``np.float32`` tensors; the helper must hand back
        plain Python floats so ``np.array([value], dtype=...)`` doesn't
        accidentally inherit a numpy dtype.
        """
        proj = _perspective(math.radians(45.0), 1.5, 0.01, 10000.0)
        result = compute_camera_intrinsics(proj)
        assert all(isinstance(v, float) for v in result)


# ── Session-layer isolation ────────────────────────────────────────────────


class TestSessionLayerIsolation:
    def test_root_layer_byte_identical_after_write(self, stage):
        # Capture root AFTER ensure_camera (done in the fixture) — ensure_camera
        # already promised session-only writes in Step A.1.
        before = stage.GetRootLayer().ExportToString()
        view = np.eye(4, dtype=np.float64)
        proj = _perspective(math.radians(45.0), 1.0, 0.01, 10000.0)
        write_camera_from_matrices(stage, CAMERA_PATH, view, proj, 512, 512)
        after = stage.GetRootLayer().ExportToString()
        assert before == after

    def test_transform_spec_lives_in_session(self, stage):
        view = np.eye(4, dtype=np.float64)
        proj = _perspective(math.radians(45.0), 1.0, 0.01, 10000.0)
        write_camera_from_matrices(stage, CAMERA_PATH, view, proj, 512, 512)

        session = stage.GetSessionLayer()
        cam_spec = session.GetPrimAtPath(CAMERA_PATH)
        assert cam_spec is not None
        attr_names = {a.name for a in cam_spec.properties}
        assert "xformOp:transform" in attr_names
        assert "xformOpOrder" in attr_names
        assert "focalLength" in attr_names
        assert "horizontalAperture" in attr_names
        assert "verticalAperture" in attr_names
        assert "clippingRange" in attr_names

    def test_no_root_spec_for_xform_op(self, stage):
        view = np.eye(4, dtype=np.float64)
        proj = _perspective(math.radians(45.0), 1.0, 0.01, 10000.0)
        write_camera_from_matrices(stage, CAMERA_PATH, view, proj, 512, 512)

        root = stage.GetRootLayer()
        assert root.GetPrimAtPath(CAMERA_PATH) is None


# ── Idempotency ─────────────────────────────────────────────────────────────


class TestIdempotency:
    def test_second_write_does_not_duplicate_xform_op(self, stage):
        view = np.eye(4, dtype=np.float64)
        proj = _perspective(math.radians(45.0), 1.0, 0.01, 10000.0)
        write_camera_from_matrices(stage, CAMERA_PATH, view, proj, 512, 512)
        write_camera_from_matrices(stage, CAMERA_PATH, view, proj, 512, 512)

        xf = UsdGeom.Xformable(stage.GetPrimAtPath(CAMERA_PATH))
        ops = xf.GetOrderedXformOps()
        assert len(ops) == 1
        assert ops[0].GetOpType() == UsdGeom.XformOp.TypeTransform

    def test_second_write_overwrites_transform_value(self, stage):
        proj = _perspective(math.radians(45.0), 1.0, 0.01, 10000.0)
        # First write: translate camera to (10, 0, 0).
        view1 = np.eye(4, dtype=np.float64)
        view1[0, 3] = -10.0
        write_camera_from_matrices(stage, CAMERA_PATH, view1, proj, 512, 512)

        # Second write: translate to (0, 0, -5).
        view2 = np.eye(4, dtype=np.float64)
        view2[2, 3] = 5.0
        write_camera_from_matrices(stage, CAMERA_PATH, view2, proj, 512, 512)

        xf = UsdGeom.Xformable(stage.GetPrimAtPath(CAMERA_PATH))
        t = xf.GetLocalTransformation().ExtractTranslation()
        assert t[0] == pytest.approx(0.0, abs=TOL)
        assert t[1] == pytest.approx(0.0, abs=TOL)
        assert t[2] == pytest.approx(-5.0, abs=TOL)

    def test_write_clobbers_preexisting_named_xform_ops(self, stage):
        """If the camera has translate/rotateXYZ ops (e.g. from a user USD),
        the writer clears them and drops in a single transform op."""
        xf = UsdGeom.Xformable(stage.GetPrimAtPath(CAMERA_PATH))
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            xf.ClearXformOpOrder()
            xf.AddTranslateOp().Set(Gf.Vec3d(1.0, 2.0, 3.0))
            xf.AddRotateXYZOp().Set(Gf.Vec3f(10.0, 20.0, 30.0))
        assert len(xf.GetOrderedXformOps()) == 2

        view = np.eye(4, dtype=np.float64)
        proj = _perspective(math.radians(45.0), 1.0, 0.01, 10000.0)
        write_camera_from_matrices(stage, CAMERA_PATH, view, proj, 512, 512)

        ops = xf.GetOrderedXformOps()
        assert len(ops) == 1
        assert ops[0].GetOpType() == UsdGeom.XformOp.TypeTransform


# ── Error handling ─────────────────────────────────────────────────────────


class TestErrors:
    def test_missing_camera_prim_raises(self, stage):
        view = np.eye(4, dtype=np.float64)
        proj = _perspective(math.radians(45.0), 1.0, 0.01, 10000.0)
        with pytest.raises(ValueError, match="no prim"):
            write_camera_from_matrices(
                stage, "/Does/Not/Exist", view, proj, 512, 512
            )

    def test_prim_not_camera_raises(self, stage):
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            UsdGeom.Scope.Define(stage, "/NotACam")
        view = np.eye(4, dtype=np.float64)
        proj = _perspective(math.radians(45.0), 1.0, 0.01, 10000.0)
        with pytest.raises(ValueError, match="not a UsdGeomCamera"):
            write_camera_from_matrices(stage, "/NotACam", view, proj, 512, 512)

    def test_non_4x4_view_raises(self, stage):
        proj = _perspective(math.radians(45.0), 1.0, 0.01, 10000.0)
        with pytest.raises(ValueError, match="view_matrix must be 4x4"):
            write_camera_from_matrices(
                stage, CAMERA_PATH, np.eye(3), proj, 512, 512
            )

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for CameraController — Step 41."""

import math

import numpy as np
import pytest

from ovui_widgets.viewport.camera_controller import (
    CameraController,
    _look_at,
    _perspective,
)


class TestDefaultState:
    def test_distance_default(self):
        cam = CameraController()
        assert cam.state.distance == 5.0

    def test_elevation_default(self):
        cam = CameraController()
        assert cam.state.elevation == pytest.approx(0.4)

    def test_target_default(self):
        cam = CameraController()
        assert cam.state.target == [0.0, 0.0, 0.0]

    def test_azimuth_default(self):
        cam = CameraController()
        assert cam.state.azimuth == pytest.approx(0.0)


class TestGetMatrices:
    def test_returns_two_arrays(self):
        cam = CameraController()
        result = cam.get_matrices(1280, 720)
        assert len(result) == 2

    def test_view_is_4x4_float32(self):
        cam = CameraController()
        view, _ = cam.get_matrices(1280, 720)
        assert view.shape == (4, 4)
        assert view.dtype == np.float32

    def test_proj_is_4x4_float32(self):
        cam = CameraController()
        _, proj = cam.get_matrices(1280, 720)
        assert proj.shape == (4, 4)
        assert proj.dtype == np.float32

    def test_proj_perspective_divide(self):
        cam = CameraController()
        _, proj = cam.get_matrices(1280, 720)
        assert proj[3, 2] == pytest.approx(-1.0)


class TestOrbit:
    def test_orbit_changes_view(self):
        cam = CameraController()
        view_before, _ = cam.get_matrices(800, 600)
        cam.orbit(0.5, 0.2)
        view_after, _ = cam.get_matrices(800, 600)
        assert not np.allclose(view_before, view_after)

    def test_orbit_changes_azimuth(self):
        cam = CameraController()
        cam.orbit(1.0, 0.0)
        assert cam.state.azimuth == pytest.approx(1.0)

    def test_orbit_changes_elevation(self):
        cam = CameraController()
        cam.orbit(0.0, 0.3)
        assert cam.state.elevation == pytest.approx(0.4 + 0.3)


class TestLook:
    @pytest.mark.parametrize("up_axis", ["Y", "Z"])
    def test_look_preserves_eye_for_stage_up_axis(self, up_axis):
        cam = CameraController()
        cam.set_pose(
            eye=(3.0, -5.0, 4.0),
            target=(0.5, 0.25, 1.0),
            up_axis=up_axis,
        )
        eye_before = cam._get_eye().copy()

        cam.look(0.25, -0.15)

        np.testing.assert_allclose(cam._get_eye(), eye_before, atol=1e-5)

    def test_z_up_look_changes_target_without_rotating_gimbal_to_y_up(self):
        cam = CameraController()
        cam.set_pose(
            eye=(3.0, -5.0, 4.0),
            target=(0.5, 0.25, 1.0),
            up_axis="Z",
        )
        target_before = np.asarray(cam.state.target, dtype=np.float32)

        cam.look(0.25, -0.15)

        assert cam.up_axis == [0.0, 0.0, 1.0]
        assert not np.allclose(cam.state.target, target_before)


class TestElevationClamp:
    def test_elevation_clamp_positive(self):
        cam = CameraController()
        cam.orbit(0.0, 10.0)
        assert cam.state.elevation == pytest.approx(1.5)

    def test_elevation_clamp_negative(self):
        cam = CameraController()
        cam.orbit(0.0, -10.0)
        assert cam.state.elevation == pytest.approx(-1.5)

    def test_elevation_clamp_exactly_at_limit(self):
        cam = CameraController()
        cam.state.elevation = 1.5
        cam.orbit(0.0, 0.0)
        assert cam.state.elevation == pytest.approx(1.5)


class TestPan:
    def test_pan_moves_target(self):
        cam = CameraController()
        original = list(cam.state.target)
        cam.pan(1.0, 0.0)
        assert cam.state.target != original

    def test_pan_zero_does_not_move_target(self):
        cam = CameraController()
        cam.pan(0.0, 0.0)
        assert cam.state.target == pytest.approx([0.0, 0.0, 0.0])

    def test_pan_changes_target_list(self):
        cam = CameraController()
        cam.pan(2.0, 3.0)
        assert isinstance(cam.state.target, list)
        assert len(cam.state.target) == 3

    def test_pan_uses_hot_basis_path(self, monkeypatch):
        cam = CameraController()

        def fail_if_called():
            raise AssertionError("_get_basis should not run during pan")

        monkeypatch.setattr(cam, "_get_basis", fail_if_called)
        cam.pan(2.0, 3.0)
        assert cam.state.target != pytest.approx([0.0, 0.0, 0.0])


class TestZoom:
    def test_zoom_changes_distance(self):
        cam = CameraController()
        cam.zoom(-2.0)
        assert cam.state.distance == pytest.approx(3.0)

    def test_zoom_increase(self):
        cam = CameraController()
        cam.zoom(1.0)
        assert cam.state.distance == pytest.approx(6.0)

    def test_zoom_clamp_min(self):
        cam = CameraController()
        cam.zoom(-1000.0)
        assert cam.state.distance == pytest.approx(0.01)

    def test_zoom_clamp_exactly_at_min(self):
        cam = CameraController()
        cam.state.distance = 0.01
        cam.zoom(-1.0)
        assert cam.state.distance == pytest.approx(0.01)

    def test_zoom_cannot_go_negative(self):
        cam = CameraController()
        cam.zoom(-9999.0)
        assert cam.state.distance > 0.0


class TestFocus:
    def test_focus_sets_target(self):
        cam = CameraController()
        cam.focus([1.0, 2.0, 3.0], 10.0)
        assert cam.state.target == pytest.approx([1.0, 2.0, 3.0])

    def test_focus_sets_distance(self):
        cam = CameraController()
        cam.focus([0.0, 0.0, 0.0], 7.5)
        assert cam.state.distance == pytest.approx(7.5)

    def test_focus_target_is_list(self):
        cam = CameraController()
        cam.focus((5.0, 6.0, 7.0), 3.0)
        assert isinstance(cam.state.target, list)


class TestLookAt:
    def test_eye_at_zero_zero_pos_z_looks_at_origin(self):
        # eye=(0,0,5), center=(0,0,0), up=(0,1,0)
        view = _look_at([0, 0, 5], [0, 0, 0], [0, 1, 0])
        assert view.shape == (4, 4)
        assert view.dtype == np.float32

    def test_eye_maps_to_origin(self):
        eye = np.array([0, 0, 5], dtype=np.float32)
        view = _look_at(eye, [0, 0, 0], [0, 1, 0])
        eye_h = np.array([0, 0, 5, 1], dtype=np.float32)
        result = view @ eye_h
        assert result[:3] == pytest.approx([0, 0, 0], abs=1e-5)

    def test_center_maps_to_neg_z_axis(self):
        eye = np.array([0, 0, 5], dtype=np.float32)
        view = _look_at(eye, [0, 0, 0], [0, 1, 0])
        center_h = np.array([0, 0, 0, 1], dtype=np.float32)
        result = view @ center_h
        # target should be on -Z axis from camera
        assert result[0] == pytest.approx(0.0, abs=1e-5)
        assert result[1] == pytest.approx(0.0, abs=1e-5)
        assert result[2] < 0.0

    def test_view_is_float32(self):
        view = _look_at([1, 2, 3], [0, 0, 0], [0, 1, 0])
        assert view.dtype == np.float32

    def test_last_row_is_homogeneous(self):
        view = _look_at([0, 0, 5], [0, 0, 0], [0, 1, 0])
        np.testing.assert_allclose(view[3], [0, 0, 0, 1], atol=1e-6)


class TestPerspective:
    def test_perspective_is_4x4_float32(self):
        proj = _perspective(math.radians(45), 16 / 9, 0.01, 1000.0)
        assert proj.shape == (4, 4)
        assert proj.dtype == np.float32

    def test_perspective_divide_row(self):
        proj = _perspective(math.radians(45), 16 / 9, 0.01, 1000.0)
        assert proj[3, 2] == pytest.approx(-1.0)

    def test_perspective_w_column_zeros_except_row3(self):
        proj = _perspective(math.radians(45), 16 / 9, 0.01, 1000.0)
        # column 3: only row 2 is non-zero (translation z)
        assert proj[0, 3] == pytest.approx(0.0)
        assert proj[1, 3] == pytest.approx(0.0)
        assert proj[3, 3] == pytest.approx(0.0)

    def test_perspective_asymmetric_aspect(self):
        proj_wide = _perspective(math.radians(45), 2.0, 0.01, 1000.0)
        proj_square = _perspective(math.radians(45), 1.0, 0.01, 1000.0)
        assert proj_wide[0, 0] != pytest.approx(proj_square[0, 0])

    def test_perspective_fov_affects_scale(self):
        proj_narrow = _perspective(math.radians(30), 1.0, 0.01, 1000.0)
        proj_wide = _perspective(math.radians(90), 1.0, 0.01, 1000.0)
        assert proj_narrow[1, 1] > proj_wide[1, 1]

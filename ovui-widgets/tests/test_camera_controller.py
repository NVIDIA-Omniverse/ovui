# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for CameraController — Step 41."""

import math

import numpy as np
import pytest

from ovui_widgets.viewport.camera_controller import (
    CameraController,
    _look_at,
    _perspective,
)
from ovui_widgets.viewport.camera_inertia import TumbleInertia


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

    def test_orthographic_projection_removes_depth_dependent_scale(self):
        cam = CameraController()
        assert cam.set_projection_mode("orthographic") is True
        _, proj = cam.get_matrices(1280, 720)

        near_point = np.array([1.0, 0.0, -2.0, 1.0], dtype=np.float32)
        far_point = np.array([1.0, 0.0, -20.0, 1.0], dtype=np.float32)
        near_clip = proj @ near_point
        far_clip = proj @ far_point

        assert proj[3, 3] == pytest.approx(1.0)
        assert proj[3, 2] == pytest.approx(0.0)
        assert near_clip[0] / near_clip[3] == pytest.approx(
            far_clip[0] / far_clip[3]
        )

    def test_projection_switch_restores_perspective_divide(self):
        cam = CameraController()
        assert cam.set_projection_mode("orthographic") is True
        assert cam.set_projection_mode("invalid") is False
        assert cam.projection_mode == "orthographic"
        assert cam.set_projection_mode("perspective") is True

        _, proj = cam.get_matrices(1280, 720)

        assert proj[3, 2] == pytest.approx(-1.0)
        assert proj[3, 3] == pytest.approx(0.0)


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


class TestExactPolePoses:
    """Authored top/bottom cameras navigate in the orientation they render."""

    @staticmethod
    def _screen_basis(cam):
        view, _projection = cam.get_matrices(640, 360)
        return np.asarray(view[0, :3]), np.asarray(view[1, :3])

    @pytest.mark.parametrize("up_axis", ["Z", "Y"])
    @pytest.mark.parametrize("pole", [1.0, -1.0])
    @pytest.mark.parametrize("noise", [0.0, 1.0e-9, -1.0e-9])
    def test_pan_basis_matches_the_rendered_image(self, up_axis, pole, noise):
        cam = CameraController()
        vertical = 2 if up_axis == "Z" else 1
        eye = [noise, -noise, noise]
        eye[vertical] = 10.0 * pole
        cam.set_pose(eye, [0.0, 0.0, 0.0], up_axis=up_axis)
        rendered_right, rendered_up = self._screen_basis(cam)
        pan_right, pan_up = cam._get_pan_basis()
        assert np.dot(rendered_right, pan_right) > 0.99
        assert np.dot(rendered_up, pan_up) > 0.99

    @pytest.mark.parametrize("up_axis", ["Z", "Y"])
    def test_first_orbit_from_a_top_view_does_not_flip_the_image(self, up_axis):
        cam = CameraController()
        eye = [0.0, 0.0, 10.0] if up_axis == "Z" else [0.0, 10.0, 0.0]
        cam.set_pose(eye, [0.0, 0.0, 0.0], up_axis=up_axis)
        before_right, before_up = self._screen_basis(cam)
        cam.orbit(0.0, -0.01)
        after_right, after_up = self._screen_basis(cam)
        assert np.dot(before_right, after_right) > 0.9
        assert np.dot(before_up, after_up) > 0.9


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class TestMotionInTime:
    def test_each_matrix_shows_the_camera_at_its_hand_over_time(self):
        cam = CameraController()
        cam.state.elevation = 0.0
        cam.clock = clock = _Clock()
        inertia = TumbleInertia(cam, time_constant=1.0e9)  # a constant 1 rad/s turn
        cam.processes = [inertia]
        cam.get_matrices(100, 100)
        inertia.start(1.0, 0.0)
        for now in (0.016, 0.020):
            clock.now = now
            view, _ = cam.get_matrices(100, 100, np.float64)
        # The view turned by exactly the time to its own hand-over.
        reference = CameraController()
        reference.state.elevation = 0.0
        reference.orbit(0.020, 0.0)
        expected, _ = reference.get_matrices(100, 100, np.float64)
        np.testing.assert_allclose(view, expected, atol=1e-9)

    def test_a_step_plays_evenly_over_its_duration(self):
        cam = CameraController()
        cam.clock = clock = _Clock()
        cam.smooth("orbit", 0.4, 0.0, duration=0.04)
        turned = []
        for _ in range(4):
            clock.now += 0.01
            cam.get_matrices(100, 100)
            turned.append(cam.state.azimuth)
        np.testing.assert_allclose(turned, [0.1, 0.2, 0.3, 0.4])

    def test_smoothing_eases_and_the_zoom_glides_faster(self):
        cam = CameraController()
        cam.clock = clock = _Clock()
        cam.smoothing_half_life = 0.06
        cam.zoom_glide_half_life = 0.04
        cam.smooth("orbit", 1.0, 0.0)
        cam.smooth("dolly", math.log(0.5))
        clock.now = 0.06
        cam.get_matrices(100, 100)
        assert cam.state.azimuth == pytest.approx(0.5)
        assert math.log(cam.state.distance / 5.0) == pytest.approx(math.log(0.5) * (1.0 - 0.5 ** 1.5))

    def test_the_pan_is_not_smoothed(self):
        cam = CameraController()
        cam.clock = _Clock()
        cam.smoothing_half_life = 0.06
        cam.smooth("pan", 1.0, 0.0)
        assert cam.state.target[0] != 0.0

    def test_focus_stops_every_motion(self):
        cam = CameraController()
        cam.clock = clock = _Clock()
        cam.smoothing_half_life = 0.06
        inertia = TumbleInertia(cam, time_constant=1.0)
        cam.processes = [inertia]
        cam.get_matrices(100, 100)
        inertia.start(2.0, 0.0)
        cam.smooth("orbit", 1.0, 0.0)
        cam.focus([1.0, 2.0, 3.0], 4.0)
        azimuth = cam.state.azimuth
        clock.now = 1.0
        cam.get_matrices(100, 100)
        assert cam.state.azimuth == azimuth  # neither the coast nor the queued step moves it
        assert cam.state.target == [1.0, 2.0, 3.0]

    def test_float64_matrices(self):
        cam = CameraController()
        cam.state.target = [1.0e6 + 0.123456, 0.0, 0.0]
        view, proj = cam.get_matrices(100, 100, np.float64)
        assert view.dtype == np.float64 and proj.dtype == np.float64
        eye = -view[:3, :3].T @ view[:3, 3]
        np.testing.assert_allclose(eye, cam._get_eye(), rtol=0.0, atol=1.0e-8)


class TestCursorPoint:
    @pytest.mark.parametrize("vertical", [1.0, -1.0])
    def test_the_cursor_point_is_under_the_cursor_even_straight_down_or_up(self, vertical):
        cam = CameraController()
        cam.set_pose(eye=[0.0, 10.0 * vertical, 0.0], target=[0.0, 0.0, 0.0], up_axis="Y")
        point = cam.cursor_point(0.5, -0.25, 2.0)
        view, proj = cam.get_matrices(200, 100, np.float64)
        clip = proj @ view @ np.append(point, 1.0)
        np.testing.assert_allclose(clip[:2] / clip[3], (0.5, -0.25), atol=1e-9)

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for Step B.2 camera navigation gestures.

Four architecture-aligned gesture classes replace the old orbit/pan/zoom
trio:

* ``TumbleGesture`` — RMB drag, pixel→angular math.
* ``PanGesture`` — MMB drag, pixel→world math using ``fov_y`` + ``distance``.
* ``ZoomScrollGesture`` — wheel, log10-curve dolly.
* ``LookGesture`` — Shift+RMB drag, same angular math but eye-fixed.

These tests don't require the ovui C++ event dispatcher to actually
fire — they drive the handlers directly by pre-setting
``raw_input.mouse`` / ``raw_input.mouse_wheel`` and invoking
``_on_began`` / ``_on_changed`` / ``_on_ended``. Synthesising events
this way lets the math be verified deterministically without a GL
context.
"""

import math
from typing import Tuple

import numpy as np
import pytest
from omni.ui_scene import scene as sc

from ovui_widgets.viewport import camera_gesture
from ovui_widgets.viewport.camera_controller import CameraController
from ovui_widgets.viewport.camera_gesture import (
    DEFAULT_FOV_Y,
    MOD_NONE,
    MOD_SHIFT,
    MOUSE_LEFT,
    MOUSE_MIDDLE,
    MOUSE_RIGHT,
    LookGesture,
    PanGesture,
    TumbleGesture,
    ZoomScrollGesture,
)
from ovui_widgets.viewport.camera_manipulator import CameraManipulatorModel

VIEWPORT_W = 1000
VIEWPORT_H = 500


def _size_fn() -> Tuple[int, int]:
    return (VIEWPORT_W, VIEWPORT_H)


def _set_mouse(gesture, x: float, y: float) -> None:
    """Write x/y into the gesture's raw_input mouse position in NDC.

    ``sc.SceneView`` exposes mouse coords in NDC (``[-1, +1]`` across
    the viewport width with +y up). Tests drive the handlers directly
    so we assign NDC values rather than pixel values — a "full-width
    drag" in these tests goes from x=-1 to x=+1 (dx_ndc = 2.0).
    """
    gesture.raw_input.mouse.x = x
    gesture.raw_input.mouse.y = y


def _set_wheel(gesture, y: float) -> None:
    gesture.raw_input.mouse_wheel.y = y


# ---------------------------------------------------------------------------
# TumbleGesture
# ---------------------------------------------------------------------------


class TestTumbleGestureConstruction:
    def test_is_drag_gesture(self):
        g = TumbleGesture(CameraController())
        assert isinstance(g, sc.DragGesture)

    def test_default_mouse_button_is_right(self):
        g = TumbleGesture(CameraController())
        assert g.mouse_button == MOUSE_RIGHT

    def test_default_modifiers_none(self):
        g = TumbleGesture(CameraController())
        assert g.modifiers == MOD_NONE

    def test_configurable_mouse_button(self):
        # Alt+LMB bindings — spec allows a caller to swap mouse_button.
        g = TumbleGesture(CameraController(), mouse_button=MOUSE_LEFT, modifiers=4)
        assert g.mouse_button == MOUSE_LEFT
        assert g.modifiers == 4

    def test_stores_camera(self):
        cam = CameraController()
        g = TumbleGesture(cam)
        assert g._camera is cam

    def test_callbacks_registered(self):
        g = TumbleGesture(CameraController())
        assert g.has_on_began_fn()
        assert g.has_on_changed_fn()
        assert g.has_on_ended_fn()


class TestTumbleGestureMath:
    def test_full_width_drag_yaws_minus_2pi(self):
        """A full-width drag = 2π radians of yaw (one full rotation).

        NDC runs [-1, +1] across the viewport, so a full-width drag
        gives ``dx_ndc = 2.0``; with ``rotate_y = -dx_ndc * π`` the
        result is ``-2π``. Per the architecture doc, dragging right
        rotates the camera counterclockwise around up (negative
        azimuth delta).
        """
        cam = CameraController()
        g = TumbleGesture(cam)
        _set_mouse(g, -1.0, 0.0)
        g._on_began()
        _set_mouse(g, 1.0, 0.0)
        g._on_changed()
        assert cam.state.azimuth == pytest.approx(-2 * math.pi, abs=1e-6)
        assert cam.state.elevation == pytest.approx(0.4, abs=1e-6)

    def test_full_height_drag_pitches_pi(self):
        cam = CameraController()
        # Start at elevation 0 so the full π delta isn't clamped.
        cam.state.elevation = 0.0
        g = TumbleGesture(cam)
        # NDC y = -1 (bottom) → +1 (top), so "drag up" is +2 NDC.
        _set_mouse(g, 0.0, -1.0)
        g._on_began()
        _set_mouse(g, 0.0, 1.0)
        g._on_changed()
        # Pitch is inverted (camera_gesture.py:213 — drag-up tilts the
        # scene up, which means the camera pitches *down*), so a full
        # +2 NDC drag-up requests −2π * 0.5 = −π, clamped to
        # ``-_ELEV_CLAMP``.
        from ovui_widgets.viewport.camera_controller import _ELEV_CLAMP
        assert cam.state.elevation == pytest.approx(-_ELEV_CLAMP, abs=1e-6)

    def test_half_width_drag_is_pi(self):
        """A half-width drag = π radians of yaw (half rotation)."""
        cam = CameraController()
        cam.state.azimuth = 0.0
        g = TumbleGesture(cam)
        _set_mouse(g, -0.5, 0.0)
        g._on_began()
        _set_mouse(g, 0.5, 0.0)
        g._on_changed()
        assert cam.state.azimuth == pytest.approx(-math.pi, abs=1e-6)

    def test_zero_move_leaves_angles_unchanged(self):
        cam = CameraController()
        az0, el0 = cam.state.azimuth, cam.state.elevation
        g = TumbleGesture(cam)
        _set_mouse(g, 0.3, 0.2)
        g._on_began()
        g._on_changed()
        assert cam.state.azimuth == pytest.approx(az0)
        assert cam.state.elevation == pytest.approx(el0)


class TestTumbleGestureGating:
    def test_gate_flag_disables_write(self):
        cam = CameraController()
        az0 = cam.state.azimuth
        model = CameraManipulatorModel()
        model.set_ints("disable_tumble", [1])
        g = TumbleGesture(cam, model=model)
        _set_mouse(g, -1.0, 0.0)
        g._on_began()
        _set_mouse(g, 1.0, 0.0)
        g._on_changed()
        assert cam.state.azimuth == az0

    def test_gate_not_set_allows_write(self):
        cam = CameraController()
        model = CameraManipulatorModel()
        g = TumbleGesture(cam, model=model)
        _set_mouse(g, -1.0, 0.0)
        g._on_began()
        _set_mouse(g, 1.0, 0.0)
        g._on_changed()
        assert cam.state.azimuth != 0.0


class TestTumbleGestureNdcFilter:
    """Bug 11 regression: reject cross-shape-dispatch events that arrive
    with the cursor reported outside the SceneView's NDC bounds.

    In the live app the tumble gesture sometimes receives ``on_changed``
    firings whose ``raw_input.mouse`` was computed against a sibling
    shape's frame (values like ``(-2.13, +2.24)``) interleaved with the
    real in-view events. Without a filter, ``rotate_y = -dx_ndc * π``
    multiplies those spikes by π and pegs the camera at a huge azimuth
    and the elevation clamp after a single drag step.
    """

    def test_out_of_bounds_changed_is_ignored(self):
        cam = CameraController()
        g = TumbleGesture(cam)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        az0 = cam.state.azimuth
        el0 = cam.state.elevation
        _set_mouse(g, -2.1308, 2.236)
        g._on_changed()
        assert cam.state.azimuth == az0
        assert cam.state.elevation == el0

    def test_in_bounds_after_out_of_bounds_uses_last_trusted_prev(self):
        """A phantom event must not corrupt ``_prev_x`` / ``_prev_y``.

        Sequence: began@(0,0) → phantom@(-2.13,+2.24) ignored →
        in-bounds@(0.5, 0). The dx for the in-bounds event must be
        measured against the *began* position (``0``), not the phantom's
        ``-2.13`` — so ``rotate_y = -0.5 * π``, not ``-2.63 * π``.
        """
        cam = CameraController()
        cam.state.azimuth = 0.0
        g = TumbleGesture(cam)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        _set_mouse(g, -2.1308, 2.236)
        g._on_changed()
        _set_mouse(g, 0.5, 0.0)
        g._on_changed()
        assert cam.state.azimuth == pytest.approx(-0.5 * math.pi, abs=1e-6)

    def test_began_with_out_of_bounds_defers_anchor(self):
        """A began firing with an invalid NDC mouse arms the gesture but
        defers ``_prev_x`` / ``_prev_y`` until the first in-bounds
        ``_on_changed`` — so the real begin from the camera shape does
        not get silently dropped when the sibling shape dispatches first.

        First in-bounds changed: anchors the prev, no delta applied.
        Second in-bounds changed: computes the real delta.
        """
        cam = CameraController()
        cam.state.azimuth = 0.0
        g = TumbleGesture(cam)
        _set_mouse(g, -2.1308, 2.236)
        g._on_began()
        assert g.is_active
        assert not g._prev_anchored
        _set_mouse(g, 0.0, 0.0)
        g._on_changed()
        assert cam.state.azimuth == 0.0  # just anchored, no delta
        assert g._prev_anchored
        _set_mouse(g, 0.5, 0.0)
        g._on_changed()
        assert cam.state.azimuth == pytest.approx(-0.5 * math.pi, abs=1e-6)


class TestPanGestureNdcFilter:
    """Bug 11 regression — same guard for :class:`PanGesture`."""

    def test_out_of_bounds_changed_is_ignored(self):
        cam = CameraController()
        cam.state.target = [0.0, 0.0, 0.0]
        g = PanGesture(cam, viewport_size_fn=_size_fn)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        target0 = list(cam.state.target)
        _set_mouse(g, -2.1308, 2.236)
        g._on_changed()
        assert cam.state.target == target0

    def test_began_with_out_of_bounds_defers_anchor(self):
        """Same deferred-anchor contract as tumble."""
        cam = CameraController()
        cam.state.target = [0.0, 0.0, 0.0]
        g = PanGesture(cam, viewport_size_fn=_size_fn)
        _set_mouse(g, -2.1308, 2.236)
        g._on_began()
        assert g.is_active
        assert not g._prev_anchored
        _set_mouse(g, 0.0, 0.0)
        g._on_changed()
        target_after_anchor = list(cam.state.target)
        assert target_after_anchor == [0.0, 0.0, 0.0]
        _set_mouse(g, 0.5, 0.0)
        g._on_changed()
        assert cam.state.target != target_after_anchor


class TestLookGestureNdcFilter:
    """Bug 11 regression — same guard for :class:`LookGesture`."""

    def test_out_of_bounds_changed_is_ignored(self):
        cam = CameraController()
        g = LookGesture(cam)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        az0 = cam.state.azimuth
        _set_mouse(g, -2.1308, 2.236)
        g._on_changed()
        assert cam.state.azimuth == az0


# ---------------------------------------------------------------------------
# LookGesture
# ---------------------------------------------------------------------------


class TestLookGestureConstruction:
    def test_is_drag_gesture(self):
        g = LookGesture(CameraController())
        assert isinstance(g, sc.DragGesture)

    def test_default_is_shift_right(self):
        g = LookGesture(CameraController())
        assert g.mouse_button == MOUSE_RIGHT
        assert g.modifiers == MOD_SHIFT

    def test_callbacks_registered(self):
        g = LookGesture(CameraController())
        assert g.has_on_began_fn()
        assert g.has_on_changed_fn()


class TestLookGestureMath:
    def test_eye_stays_fixed(self):
        """Look must not translate the camera — only the target moves."""
        cam = CameraController()
        eye_before = cam._get_eye().copy()
        g = LookGesture(cam)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        # Quarter-width drag (dx_ndc = 0.5) — keep elevation inside clamp.
        _set_mouse(g, 0.5, 0.0)
        g._on_changed()
        eye_after = cam._get_eye()
        assert eye_after[0] == pytest.approx(eye_before[0], abs=1e-3)
        assert eye_after[1] == pytest.approx(eye_before[1], abs=1e-3)
        assert eye_after[2] == pytest.approx(eye_before[2], abs=1e-3)

    def test_target_moves(self):
        cam = CameraController()
        target_before = list(cam.state.target)
        g = LookGesture(cam)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        _set_mouse(g, 0.6, 0.0)
        g._on_changed()
        assert cam.state.target != target_before

    def test_look_direction_changes(self):
        """Look gesture rotates azimuth/elevation like tumble."""
        cam = CameraController()
        az_before = cam.state.azimuth
        g = LookGesture(cam)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        _set_mouse(g, 1.0, 0.0)
        g._on_changed()
        assert cam.state.azimuth != az_before


class TestLookGestureGating:
    def test_disable_look_blocks_write(self):
        cam = CameraController()
        eye_before = cam._get_eye().copy()
        target_before = list(cam.state.target)
        az_before = cam.state.azimuth
        model = CameraManipulatorModel()
        model.set_ints("disable_look", [1])
        g = LookGesture(cam, model=model)
        _set_mouse(g, -1.0, 0.0)
        g._on_began()
        _set_mouse(g, 1.0, 0.0)
        g._on_changed()
        assert cam.state.azimuth == az_before
        assert cam.state.target == target_before
        eye_after = cam._get_eye()
        for a, b in zip(eye_before, eye_after):
            assert a == pytest.approx(b)


# ---------------------------------------------------------------------------
# PanGesture
# ---------------------------------------------------------------------------


class TestPanGestureConstruction:
    def test_is_drag_gesture(self):
        g = PanGesture(CameraController())
        assert isinstance(g, sc.DragGesture)

    def test_default_button_is_middle(self):
        g = PanGesture(CameraController())
        assert g.mouse_button == MOUSE_MIDDLE

    def test_default_modifiers_none(self):
        g = PanGesture(CameraController())
        assert g.modifiers == MOD_NONE

    def test_stores_camera(self):
        cam = CameraController()
        g = PanGesture(cam)
        assert g._camera is cam

    def test_fov_defaults_match_camera_controller(self):
        g = PanGesture(CameraController())
        assert g._fov_y == pytest.approx(DEFAULT_FOV_Y)

    @staticmethod
    def _pan_distance(make_gesture) -> float:
        cam = CameraController()
        g = make_gesture(cam)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        _set_mouse(g, 0.5, 0.0)
        g._on_changed()
        return math.dist(cam.state.target, (0.0, 0.0, 0.0))

    def test_the_fourth_argument_is_the_field_of_view_of_the_pan(self):
        narrow = self._pan_distance(lambda cam: PanGesture(cam, None, _size_fn, math.radians(45.0)))
        wide = self._pan_distance(lambda cam: PanGesture(cam, None, _size_fn, math.radians(90.0)))
        assert wide / narrow == pytest.approx(math.tan(math.radians(45.0)) / math.tan(math.radians(22.5)))

    def test_the_viewport_pan_follows_the_camera_field_of_view(self):
        def viewport_pan(fov):
            def make(cam):
                cam.fov_degrees = fov
                return camera_gesture.NavigationGesture(
                    cam, viewport_size_fn=_size_fn, mouse_button=MOUSE_MIDDLE, modes={0: "pan"})
            return make
        ratio = self._pan_distance(viewport_pan(90.0)) / self._pan_distance(viewport_pan(45.0))
        assert ratio == pytest.approx(math.tan(math.radians(45.0)) / math.tan(math.radians(22.5)))

    def test_callbacks_registered(self):
        g = PanGesture(CameraController())
        assert g.has_on_began_fn()
        assert g.has_on_changed_fn()


class TestPanGestureMath:
    def test_full_width_drag_translates_by_viewport_width_at_coi(self):
        """Dragging a full viewport width (dx_ndc = 2) moves the target
        by the full world-space width at the COI depth.

        world_per_ndc_y = distance * tan(fov_y / 2)
        world_per_ndc_x = world_per_ndc_y * (viewport_w / viewport_h)
        full_drag_world_x = 2 * world_per_ndc_x (NDC range is [-1, +1])
        """
        cam = CameraController()
        cam.state.target = [0.0, 0.0, 0.0]
        cam.state.azimuth = 0.0
        cam.state.elevation = 0.0
        cam.state.distance = 10.0
        g = PanGesture(cam, viewport_size_fn=_size_fn, fov_y=DEFAULT_FOV_Y)
        _set_mouse(g, -1.0, 0.0)
        g._on_began()
        _set_mouse(g, 1.0, 0.0)
        g._on_changed()
        half_world_y = cam.state.distance * math.tan(DEFAULT_FOV_Y * 0.5)
        half_world_x = half_world_y * (VIEWPORT_W / VIEWPORT_H)
        expected = 2.0 * half_world_x
        # With az=0, el=0 the right vector is (+1, 0, 0). Pan negates the
        # signed dx so dragging right slides the scene right (target moves left).
        assert cam.state.target[0] == pytest.approx(-expected, rel=1e-4)

    def test_zero_drag_leaves_target_unchanged(self):
        cam = CameraController()
        target_before = list(cam.state.target)
        g = PanGesture(cam, viewport_size_fn=_size_fn)
        _set_mouse(g, 0.5, 0.25)
        g._on_began()
        g._on_changed()
        assert cam.state.target == target_before

    def test_scales_with_distance(self):
        """Farther zoom → each NDC unit of pan moves the target more."""
        cam_near = CameraController()
        cam_near.state.azimuth = 0.0
        cam_near.state.elevation = 0.0
        cam_near.state.distance = 1.0
        cam_far = CameraController()
        cam_far.state.azimuth = 0.0
        cam_far.state.elevation = 0.0
        cam_far.state.distance = 100.0
        near = PanGesture(cam_near, viewport_size_fn=_size_fn)
        far = PanGesture(cam_far, viewport_size_fn=_size_fn)
        for g in (near, far):
            _set_mouse(g, 0.0, 0.0)
            g._on_began()
            _set_mouse(g, 0.1, 0.0)
            g._on_changed()
        near_move = abs(cam_near.state.target[0])
        far_move = abs(cam_far.state.target[0])
        assert far_move > near_move * 50

    def test_ignores_nonfinite_distance_and_sanitizes_aspect(self):
        cam = CameraController()
        cam.state.distance = float("nan")
        target_before = list(cam.state.target)
        g = PanGesture(cam, viewport_size_fn=lambda: (float("inf"), 500))
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        _set_mouse(g, 0.2, 0.0)
        g._on_changed()

        assert cam.state.target == target_before

        cam.state.distance = 10.0
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        _set_mouse(g, 0.2, 0.0)
        g._on_changed()

        assert all(math.isfinite(value) for value in cam.state.target)
        assert cam.state.target != target_before


class TestPanGestureGating:
    def test_disable_pan_blocks_write(self):
        cam = CameraController()
        target_before = list(cam.state.target)
        model = CameraManipulatorModel()
        model.set_ints("disable_pan", [1])
        g = PanGesture(cam, model=model, viewport_size_fn=_size_fn)
        _set_mouse(g, -1.0, 0.0)
        g._on_began()
        _set_mouse(g, 1.0, 0.0)
        g._on_changed()
        assert cam.state.target == target_before


# ---------------------------------------------------------------------------
# ZoomScrollGesture
# ---------------------------------------------------------------------------


class TestZoomScrollGestureConstruction:
    def test_is_scroll_gesture(self):
        g = ZoomScrollGesture(CameraController())
        assert isinstance(g, sc.ScrollGesture)

    def test_stores_camera(self):
        cam = CameraController()
        g = ZoomScrollGesture(cam)
        assert g._camera is cam

    def test_on_ended_callback_registered(self):
        g = ZoomScrollGesture(CameraController())
        assert g.has_on_ended_fn()


class TestZoomScrollGestureMath:
    def test_positive_scroll_zooms_in(self):
        cam = CameraController()
        cam.state.distance = 10.0
        g = ZoomScrollGesture(cam)
        _set_wheel(g, 1.0)
        g._on_ended()
        assert cam.state.distance < 10.0

    def test_negative_scroll_zooms_out(self):
        cam = CameraController()
        cam.state.distance = 10.0
        g = ZoomScrollGesture(cam)
        _set_wheel(g, -1.0)
        g._on_ended()
        assert cam.state.distance > 10.0

    def test_each_notch_covers_a_sixth_of_the_distance(self):
        cam = CameraController()
        cam.state.distance = 10.0
        g = ZoomScrollGesture(cam)
        _set_wheel(g, 2.0)
        g._on_ended()
        assert cam.state.distance == pytest.approx(10.0 * (5.0 / 6.0) ** 2, rel=1e-5)

    def test_a_notch_out_undoes_a_notch_in(self):
        cam = CameraController()
        cam.state.distance = 10.0
        g = ZoomScrollGesture(cam)
        _set_wheel(g, -2.0)
        g._on_ended()
        _set_wheel(g, 2.0)
        g._on_ended()
        assert cam.state.distance == pytest.approx(10.0, rel=1e-9)

    def test_zero_scroll_no_op(self):
        cam = CameraController()
        cam.state.distance = 10.0
        g = ZoomScrollGesture(cam)
        _set_wheel(g, 0.0)
        g._on_ended()
        assert cam.state.distance == 10.0

    def test_min_distance_clamp(self):
        """Repeated zoom-in cannot drop below ``_MIN_DIST``."""
        cam = CameraController()
        cam.state.distance = 0.02
        g = ZoomScrollGesture(cam)
        for _ in range(30):
            _set_wheel(g, 100.0)
            g._on_ended()
        from ovui_widgets.viewport.camera_controller import _MIN_DIST
        assert cam.state.distance >= _MIN_DIST

    def test_max_distance_clamp(self):
        """Repeated zoom-out cannot exceed ``_MAX_DIST``."""
        cam = CameraController()
        cam.state.distance = 1.0
        g = ZoomScrollGesture(cam)
        for _ in range(100):
            _set_wheel(g, -100.0)
            g._on_ended()
        from ovui_widgets.viewport.camera_controller import _MAX_DIST
        assert cam.state.distance <= _MAX_DIST


class TestZoomScrollGestureGating:
    def test_disable_zoom_blocks_write(self):
        cam = CameraController()
        cam.state.distance = 5.0
        model = CameraManipulatorModel()
        model.set_ints("disable_zoom", [1])
        g = ZoomScrollGesture(cam, model=model)
        _set_wheel(g, 5.0)
        g._on_ended()
        assert cam.state.distance == 5.0


# ---------------------------------------------------------------------------
# Callback-signature regression (Phase A QA)
# ---------------------------------------------------------------------------


class TestGestureCallbackSignaturesAcceptSender:
    """ovui invokes every drag/scroll callback with the owning shape as a
    positional argument. A zero-arg handler raises ``TypeError`` on every
    drag frame, so each handler takes ``sender=None``. Pin it down here."""

    def _screen(self):
        sv = sc.SceneView()
        with sv.scene:
            screen = sc.Screen()
        return screen

    def test_tumble_on_began_accepts_sender(self):
        g = TumbleGesture(CameraController(), viewport_size_fn=_size_fn)
        g._on_began(sc.SceneView())

    def test_tumble_on_changed_accepts_sender(self):
        g = TumbleGesture(CameraController(), viewport_size_fn=_size_fn)
        _set_mouse(g, 0.0, 0.0)
        g._on_began(None)
        _set_mouse(g, 0.1, 0.1)
        g._on_changed(sc.SceneView())

    def test_pan_on_began_accepts_sender(self):
        g = PanGesture(CameraController(), viewport_size_fn=_size_fn)
        g._on_began(sc.SceneView())

    def test_pan_on_changed_accepts_sender(self):
        g = PanGesture(CameraController(), viewport_size_fn=_size_fn)
        _set_mouse(g, 0.0, 0.0)
        g._on_began(None)
        _set_mouse(g, 0.1, 0.1)
        g._on_changed(sc.SceneView())

    def test_look_on_began_accepts_sender(self):
        g = LookGesture(CameraController(), viewport_size_fn=_size_fn)
        g._on_began(sc.SceneView())

    def test_look_on_changed_accepts_sender(self):
        g = LookGesture(CameraController(), viewport_size_fn=_size_fn)
        _set_mouse(g, 0.0, 0.0)
        g._on_began(None)
        _set_mouse(g, 0.1, 0.1)
        g._on_changed(sc.SceneView())

    def test_zoom_on_ended_accepts_sender(self):
        g = ZoomScrollGesture(CameraController())
        _set_wheel(g, 1.0)
        g._on_ended(sc.SceneView())

    def test_tumble_call_via_ovui_does_not_raise(self):
        """C++ dispatcher-style invocation — the real path at runtime."""
        cam = CameraController()
        g = TumbleGesture(cam, viewport_size_fn=_size_fn)
        screen = self._screen()
        g.call_on_began_fn(screen)
        g.call_on_changed_fn(screen)
        g.call_on_ended_fn(screen)

    def test_pan_call_via_ovui_does_not_raise(self):
        cam = CameraController()
        g = PanGesture(cam, viewport_size_fn=_size_fn)
        screen = self._screen()
        g.call_on_began_fn(screen)
        g.call_on_changed_fn(screen)
        g.call_on_ended_fn(screen)

    def test_look_call_via_ovui_does_not_raise(self):
        cam = CameraController()
        g = LookGesture(cam, viewport_size_fn=_size_fn)
        screen = self._screen()
        g.call_on_began_fn(screen)
        g.call_on_changed_fn(screen)
        g.call_on_ended_fn(screen)

    def test_zoom_call_via_ovui_does_not_raise(self):
        cam = CameraController()
        g = ZoomScrollGesture(cam)
        screen = self._screen()
        g.call_on_ended_fn(screen)


from types import SimpleNamespace


# ---------------------------------------------------------------------------
# The surface under the cursor
# ---------------------------------------------------------------------------


def _camera_space(cam: CameraController, point) -> np.ndarray:
    view, _ = cam.get_matrices(VIEWPORT_W, VIEWPORT_H, np.float64)
    return (view @ np.append(np.asarray(point, dtype=np.float64), 1.0))[:3]


def _ndc(cam: CameraController, point) -> Tuple[float, float]:
    view, proj = cam.get_matrices(VIEWPORT_W, VIEWPORT_H, np.float64)
    clip = proj @ view @ np.append(np.asarray(point, dtype=np.float64), 1.0)
    return clip[0] / clip[3], clip[1] / clip[3]


class _Renderer:
    """A renderer adapter that answers each surface query with ``hit`` once ``answer()`` runs."""

    def __init__(self, hit) -> None:
        self.hit = hit
        self.asked = 0
        self.answered = 0

    def query_surface(self, x: float, y: float) -> int:
        self.asked += 1
        return self.asked

    def surface_hit(self):
        return self.answered, self.hit

    def answer(self) -> None:
        self.answered = self.asked


def _surface(renderer, clock=lambda: 0.0) -> camera_gesture.SurfaceQuery:
    return camera_gesture.SurfaceQuery(lambda: renderer, clock=clock)


class TestSurfaceNavigation:
    def test_the_tumble_turns_about_the_surface_point(self):
        cam = CameraController()
        hit = cam.cursor_point(0.3, -0.2, VIEWPORT_W / VIEWPORT_H, depth=2.0)
        renderer = _Renderer(hit)
        g = TumbleGesture(cam, viewport_size_fn=_size_fn, surface=_surface(renderer))
        before = _camera_space(cam, hit)
        _set_mouse(g, 0.3, -0.2)
        g._on_began()
        _set_mouse(g, 0.5, 0.0)
        g._on_changed()
        assert cam.state.azimuth == 0.0  # waits for the surface point
        renderer.answer()
        cam.advance(0.0)
        assert cam.state.azimuth != 0.0
        np.testing.assert_allclose(_camera_space(cam, hit), before, atol=1e-9)

    def test_a_step_waits_for_the_surface_answer(self):
        cam = CameraController()
        hit = cam.cursor_point(0.0, 0.0, VIEWPORT_W / VIEWPORT_H, depth=1.0)
        renderer = _Renderer(hit)
        g = ZoomScrollGesture(cam, viewport_size_fn=_size_fn, surface=_surface(renderer))
        _set_wheel(g, 1.0)
        g._on_ended()
        assert cam.state.distance == pytest.approx(5.0)  # not answered yet
        renderer.answer()
        cam.advance(0.0)
        eye = cam._get_eye()
        # The eye came 1/6 closer to the surface point, not to the target.
        assert np.linalg.norm(eye - hit) == pytest.approx(5.0 / 6.0)

    def test_without_an_answer_the_step_uses_the_target_depth(self):
        cam = CameraController()
        now = [0.0]
        renderer = _Renderer(None)
        g = ZoomScrollGesture(cam, viewport_size_fn=_size_fn, surface=_surface(renderer, lambda: now[0]))
        _set_wheel(g, 1.0)
        g._on_ended()
        now[0] = camera_gesture.SURFACE_WAIT + 0.01
        cam.advance(0.0)
        assert cam.state.distance == pytest.approx(5.0 / 1.2)

    def test_the_wheel_never_passes_the_surface(self):
        cam = CameraController()
        hit = cam.cursor_point(-0.4, 0.3, VIEWPORT_W / VIEWPORT_H, depth=0.5)
        renderer = _Renderer(hit)
        g = ZoomScrollGesture(cam, viewport_size_fn=_size_fn, surface=_surface(renderer))
        _set_mouse(g, -0.4, 0.3)
        for _ in range(40):
            _set_wheel(g, 1.0)
            g._on_ended()
            renderer.answer()
            cam.advance(0.0)
        assert _camera_space(cam, hit)[2] < 0.0  # still in front
        np.testing.assert_allclose(_ndc(cam, hit), (-0.4, 0.3), atol=1e-6)
        assert renderer.asked == 1  # the answer is kept while the point stays under the cursor

    def test_the_pan_keeps_the_grabbed_surface_under_the_cursor(self):
        cam = CameraController()
        hit = cam.cursor_point(0.2, 0.1, VIEWPORT_W / VIEWPORT_H, depth=1.5)
        renderer = _Renderer(hit)
        g = PanGesture(cam, viewport_size_fn=_size_fn, surface=_surface(renderer))
        _set_mouse(g, 0.2, 0.1)
        g._on_began()
        renderer.answer()
        _set_mouse(g, 0.6, -0.3)
        g._on_changed()
        np.testing.assert_allclose(_ndc(cam, hit), (0.6, -0.3), atol=1e-9)

    def test_the_drag_zoom_approaches_the_point_under_the_press(self):
        cam = CameraController()
        g = camera_gesture.DollyGesture(cam, viewport_size_fn=_size_fn)
        _set_mouse(g, 0.5, 0.5)
        g._on_began()
        point = cam.cursor_point(0.5, 0.5, VIEWPORT_W / VIEWPORT_H)
        _set_mouse(g, 0.5, 0.75)
        g._on_changed()
        assert cam.state.distance < 5.0
        np.testing.assert_allclose(_ndc(cam, point), (0.5, 0.5), atol=1e-9)


class _Generation:
    effective = True


class TestStaleViewport:
    def test_a_stale_drag_zoom_does_nothing(self):
        cam = CameraController()
        generation = _Generation()
        g = camera_gesture.DollyGesture(cam, viewport_size_fn=_size_fn, generation=generation)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        generation.effective = False
        _set_mouse(g, 0.0, 0.5)
        g._on_changed()
        assert cam.state.distance == pytest.approx(5.0)

    def test_a_stale_fly_speed_wheel_does_nothing(self):
        steps = []
        generation = _Generation()
        g = camera_gesture.FlySpeedScrollGesture(SimpleNamespace(step_speed=steps.append), generation)
        generation.effective = False
        _set_wheel(g, 1.0)
        g._on_ended()
        assert steps == []


class TestNativeInput:
    def test_the_windows_own_cursor_events_drive_the_drag(self, monkeypatch):
        motion = [(0.0, 0.0, 0.0)]
        monkeypatch.setattr(camera_gesture, "_native_cursor_motion", lambda: motion.pop() if motion else (0.0, 0.0, 0.0))
        cam = CameraController()
        g = LookGesture(cam, viewport_size_fn=_size_fn, options=camera_gesture.NavigationOptions(rotation_gain_max=1.0))
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        motion.append((100.0, 0.0, 10.0))  # 100 px right: 1/10 of the width
        _set_mouse(g, 0.3, 0.0)  # ImGui's cursor saw more, but the window's events win
        g._on_changed()
        assert cam.state.azimuth == pytest.approx(-0.2 * math.pi)

    def test_injected_input_without_window_events_still_drags(self, monkeypatch):
        monkeypatch.setattr(camera_gesture, "_native_cursor_motion", lambda: (0.0, 0.0, 0.0))
        cam = CameraController()
        g = PanGesture(cam, viewport_size_fn=_size_fn)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        _set_mouse(g, 0.2, 0.0)
        g._on_changed()
        assert cam.state.target[0] != 0.0

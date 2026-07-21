# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :mod:`ovui_widgets.viewport.camera_flight_keyboard` — Step B.3.

``FlightModeKeyboard`` has no dependency on the ovui scene graph —
it consumes key-code ints, modifier masks, and RMB-held booleans and
writes to a pure-Python ``CameraController``. Tests drive the public
API directly (``handle_key_event`` / ``notify_rmb_*`` / ``integrate``)
and assert on ``CameraController.state.target``.

Coverage groups:

* construction — defaults match the plan, gate wiring.
* key tracking — CHAR/KEY_UP-style semantics via handle_key_event.
* is_flying gate — RMB × motion-key × disable_fly truth table.
* velocity direction — each of W/A/S/D/Space/C produces the right
  camera-basis axis.
* speed modifiers — Shift 2×, Ctrl 0.5×, default 1×.
* integration math — velocity × base_speed × dt scales linearly.
* Q/E roll keys — tracked but inactive (no CameraController roll
  axis yet).
* lifecycle — release clears keys, gesture-backed RMB state.
"""

from typing import Any, Tuple

import numpy as np
import pytest

from ovui_widgets.viewport.camera_controller import CameraController
from ovui_widgets.viewport.camera_flight_keyboard import (
    DEFAULT_BASE_SPEED,
    FLY_SPEED_SETTING,
    MOD_CTRL,
    MOD_SHIFT,
    SPEED_CTRL,
    SPEED_SHIFT,
    FlightModeKeyboard,
)
from ovui_widgets.viewport.camera_manipulator import CameraManipulatorModel

# Key codes the handler actually watches (uppercase ASCII — GLFW sends
# uppercase regardless of shift state; FlightModeKeyboard mirrors that).
KEY_W = ord("W")
KEY_A = ord("A")
KEY_S = ord("S")
KEY_D = ord("D")
KEY_Q = ord("Q")
KEY_E = ord("E")
KEY_C = ord("C")
KEY_SPACE = ord(" ")


def _make_flight(base_speed: float = 1.0, model=None) -> FlightModeKeyboard:
    """Build a FlightModeKeyboard with a fresh camera + optional model."""
    return FlightModeKeyboard(CameraController(), model=model, base_speed=base_speed)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_base_speed(self):
        f = FlightModeKeyboard(CameraController())
        assert f.base_speed == DEFAULT_BASE_SPEED == 1.0

    def test_custom_base_speed(self):
        f = FlightModeKeyboard(CameraController(), base_speed=5.0)
        assert f.base_speed == 5.0

    def test_base_speed_setter(self):
        f = _make_flight()
        f.base_speed = 2.5
        assert f.base_speed == 2.5

    def test_starts_not_flying(self):
        f = _make_flight()
        assert f.is_flying is False

    def test_starts_empty_active_keys(self):
        f = _make_flight()
        assert f.active_keys == set()

    def test_starts_zero_modifiers(self):
        f = _make_flight()
        assert f.modifiers == 0

    def test_rmb_held_starts_false(self):
        f = _make_flight()
        assert f.rmb_held is False

    def test_fly_speed_setting_name(self):
        # Pin the setting key so application config / user preferences
        # can reference it by a stable string.
        assert FLY_SPEED_SETTING == "viewport.navigation.fly_speed"


# ---------------------------------------------------------------------------
# handle_key_event — CHAR/KEY_UP-style tracking
# ---------------------------------------------------------------------------


class TestHandleKeyEvent:
    def test_press_adds_to_active_keys(self):
        f = _make_flight()
        f.handle_key_event(KEY_W, 0, pressed=True)
        assert KEY_W in f.active_keys

    def test_release_removes_from_active_keys(self):
        f = _make_flight()
        f.handle_key_event(KEY_W, 0, pressed=True)
        f.handle_key_event(KEY_W, 0, pressed=False)
        assert KEY_W not in f.active_keys

    def test_release_of_never_pressed_key_is_harmless(self):
        f = _make_flight()
        # Should not raise KeyError — the handler uses ``discard``.
        f.handle_key_event(KEY_W, 0, pressed=False)
        assert f.active_keys == set()

    def test_repeat_press_is_idempotent(self):
        # Key-repeat events fire pressed=True multiple times. Set
        # semantics make this a no-op.
        f = _make_flight()
        for _ in range(5):
            f.handle_key_event(KEY_W, 0, pressed=True)
        assert f.active_keys == {KEY_W}

    def test_non_tracked_key_is_ignored(self):
        # Arrow keys, letters outside WASD/QE/SpaceC must not leak in.
        f = _make_flight()
        f.handle_key_event(ord("X"), 0, pressed=True)
        f.handle_key_event(ord("Z"), 0, pressed=True)
        f.handle_key_event(261, 0, pressed=True)  # GLFW Delete
        assert f.active_keys == set()

    def test_modifiers_update_on_any_event(self):
        f = _make_flight()
        f.handle_key_event(KEY_W, MOD_SHIFT, pressed=True)
        assert f.modifiers == MOD_SHIFT
        f.handle_key_event(KEY_W, MOD_CTRL, pressed=False)
        assert f.modifiers == MOD_CTRL

    def test_modifiers_update_for_non_tracked_keys_too(self):
        # The user might hold only shift (no WASD) — we still want the
        # next motion-key press to see shift in the modifier mask.
        f = _make_flight()
        f.handle_key_event(ord("Z"), MOD_SHIFT, pressed=True)
        assert f.modifiers == MOD_SHIFT

    def test_space_and_c_are_tracked(self):
        f = _make_flight()
        f.handle_key_event(KEY_SPACE, 0, pressed=True)
        f.handle_key_event(KEY_C, 0, pressed=True)
        assert KEY_SPACE in f.active_keys
        assert KEY_C in f.active_keys

    def test_qe_are_tracked(self):
        # Q/E are reserved for roll (deferred) but must still be
        # tracked in the active-keys set so the release event can
        # remove them.
        f = _make_flight()
        f.handle_key_event(KEY_Q, 0, pressed=True)
        f.handle_key_event(KEY_E, 0, pressed=True)
        assert KEY_Q in f.active_keys
        assert KEY_E in f.active_keys


# ---------------------------------------------------------------------------
# is_flying — RMB × motion-key truth table
# ---------------------------------------------------------------------------


class TestIsFlying:
    def test_no_rmb_no_keys(self):
        f = _make_flight()
        assert f.is_flying is False

    def test_rmb_no_keys(self):
        f = _make_flight()
        f.notify_rmb_press()
        assert f.is_flying is False

    def test_keys_no_rmb(self):
        f = _make_flight()
        f.handle_key_event(KEY_W, 0, pressed=True)
        assert f.is_flying is False

    def test_rmb_plus_w(self):
        f = _make_flight()
        f.notify_rmb_press()
        f.handle_key_event(KEY_W, 0, pressed=True)
        assert f.is_flying is True

    @pytest.mark.parametrize("key", [KEY_W, KEY_A, KEY_S, KEY_D, KEY_SPACE, KEY_C])
    def test_each_motion_key_activates_flying(self, key):
        f = _make_flight()
        f.notify_rmb_press()
        f.handle_key_event(key, 0, pressed=True)
        assert f.is_flying is True

    def test_roll_only_does_not_activate(self):
        # Q/E are roll placeholders. Holding only Q+E with RMB must
        # NOT be considered "flying" — there's no motion without W/A/S/D.
        f = _make_flight()
        f.notify_rmb_press()
        f.handle_key_event(KEY_Q, 0, pressed=True)
        f.handle_key_event(KEY_E, 0, pressed=True)
        assert f.is_flying is False

    def test_disable_fly_gate_blocks(self):
        model = CameraManipulatorModel()
        model.set_ints("disable_fly", [1])
        f = FlightModeKeyboard(CameraController(), model=model)
        f.notify_rmb_press()
        f.handle_key_event(KEY_W, 0, pressed=True)
        assert f.is_flying is False

    def test_disable_fly_cleared_allows(self):
        model = CameraManipulatorModel()
        model.set_ints("disable_fly", [0])
        f = FlightModeKeyboard(CameraController(), model=model)
        f.notify_rmb_press()
        f.handle_key_event(KEY_W, 0, pressed=True)
        assert f.is_flying is True


# ---------------------------------------------------------------------------
# RMB lifecycle
# ---------------------------------------------------------------------------


class TestRmbLifecycle:
    def test_notify_press_sets_rmb_held(self):
        f = _make_flight()
        f.notify_rmb_press()
        assert f.rmb_held is True

    def test_notify_release_clears_rmb_held(self):
        f = _make_flight()
        f.notify_rmb_press()
        f.notify_rmb_release()
        assert f.rmb_held is False

    def test_release_clears_active_keys(self):
        # Acceptance: "Releasing either RMB or all keys exits flight
        # mode cleanly (no stuck velocity)". Clearing _active_keys on
        # RMB release enforces it.
        f = _make_flight()
        f.notify_rmb_press()
        f.handle_key_event(KEY_W, 0, pressed=True)
        f.handle_key_event(KEY_D, 0, pressed=True)
        f.notify_rmb_release()
        assert f.active_keys == set()
        assert f.is_flying is False

    def test_release_all_keys_stops_flying(self):
        f = _make_flight()
        f.notify_rmb_press()
        f.handle_key_event(KEY_W, 0, pressed=True)
        assert f.is_flying
        f.handle_key_event(KEY_W, 0, pressed=False)
        assert f.is_flying is False

    def test_gesture_backed_rmb(self):
        # When a gesture with ``is_active=True`` is attached, is_flying
        # treats that as RMB held — no manual notify_rmb_press needed.
        class FakeGesture:
            is_active = True

        f = FlightModeKeyboard(
            CameraController(), rmb_gestures=[FakeGesture()]
        )
        f.handle_key_event(KEY_W, 0, pressed=True)
        assert f.rmb_held is True
        assert f.is_flying is True

    def test_gesture_inactive_does_not_imply_rmb(self):
        class FakeGesture:
            is_active = False

        f = FlightModeKeyboard(
            CameraController(), rmb_gestures=[FakeGesture()]
        )
        f.handle_key_event(KEY_W, 0, pressed=True)
        assert f.rmb_held is False
        assert f.is_flying is False

    def test_set_rmb_gestures_replaces_list(self):
        # ViewportWidget attaches the tumble/look gestures after
        # construction — ``set_rmb_gestures`` is the public setter that
        # supports this pattern.
        class Active:
            is_active = True

        class Inactive:
            is_active = False

        f = _make_flight()
        f.set_rmb_gestures([Inactive()])
        f.handle_key_event(KEY_W, 0, pressed=True)
        assert f.rmb_held is False
        f.set_rmb_gestures([Active()])
        assert f.rmb_held is True
        assert f.is_flying is True


# ---------------------------------------------------------------------------
# Velocity integration — direction tests
#
# Camera defaults: azimuth=0, elevation=0.4, distance=5, target=(0,0,0).
# With az=0, the camera basis is:
#   forward ≈ (0, -sin(0.4), -cos(0.4)) (points into -Z quadrant)
#   right   ≈ (1, 0, 0)                  (world +X)
#   up      ≈ (0, cos(0.4), -sin(0.4))   (mostly world +Y)
# So W moves target in forward direction, D moves target in +X, etc.
# ---------------------------------------------------------------------------


def _setup_camera_for_math() -> Tuple[CameraController, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Return (camera at defaults, (right, up, forward))."""
    cam = CameraController()
    right, up, forward = cam._get_basis()
    return cam, (right, up, forward)


class TestIntegrationDirection:
    def test_w_moves_forward(self):
        cam, (_r, _u, forward) = _setup_camera_for_math()
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_W, 0, pressed=True)
        f.integrate(dt=1.0)
        expected = forward * 1.0
        np.testing.assert_allclose(
            cam.state.target, expected.tolist(), atol=1e-5
        )

    def test_s_moves_backward(self):
        cam, (_r, _u, forward) = _setup_camera_for_math()
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_S, 0, pressed=True)
        f.integrate(dt=1.0)
        expected = -forward * 1.0
        np.testing.assert_allclose(
            cam.state.target, expected.tolist(), atol=1e-5
        )

    def test_d_moves_right(self):
        cam, (right, _u, _f) = _setup_camera_for_math()
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_D, 0, pressed=True)
        f.integrate(dt=1.0)
        expected = right * 1.0
        np.testing.assert_allclose(
            cam.state.target, expected.tolist(), atol=1e-5
        )

    def test_a_moves_left(self):
        cam, (right, _u, _f) = _setup_camera_for_math()
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_A, 0, pressed=True)
        f.integrate(dt=1.0)
        expected = -right * 1.0
        np.testing.assert_allclose(
            cam.state.target, expected.tolist(), atol=1e-5
        )

    def test_space_moves_up(self):
        cam, (_r, up, _f) = _setup_camera_for_math()
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_SPACE, 0, pressed=True)
        f.integrate(dt=1.0)
        expected = up * 1.0
        np.testing.assert_allclose(
            cam.state.target, expected.tolist(), atol=1e-5
        )

    def test_c_moves_down(self):
        cam, (_r, up, _f) = _setup_camera_for_math()
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_C, 0, pressed=True)
        f.integrate(dt=1.0)
        expected = -up * 1.0
        np.testing.assert_allclose(
            cam.state.target, expected.tolist(), atol=1e-5
        )

    def test_w_plus_s_cancel(self):
        cam = CameraController()
        target0 = list(cam.state.target)
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_W, 0, pressed=True)
        f.handle_key_event(KEY_S, 0, pressed=True)
        f.integrate(dt=1.0)
        assert cam.state.target == target0

    def test_diagonal_w_plus_d(self):
        cam, (right, _u, forward) = _setup_camera_for_math()
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_W, 0, pressed=True)
        f.handle_key_event(KEY_D, 0, pressed=True)
        f.integrate(dt=1.0)
        expected = (forward + right) * 1.0
        np.testing.assert_allclose(
            cam.state.target, expected.tolist(), atol=1e-5
        )

    def test_qe_alone_does_not_move(self):
        cam = CameraController()
        target0 = list(cam.state.target)
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_Q, 0, pressed=True)
        f.handle_key_event(KEY_E, 0, pressed=True)
        f.integrate(dt=1.0)
        assert cam.state.target == target0


# ---------------------------------------------------------------------------
# Speed modifiers
# ---------------------------------------------------------------------------


class TestSpeedModifiers:
    def test_no_modifier_is_1x(self):
        cam = CameraController()
        f = FlightModeKeyboard(cam, base_speed=2.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_W, 0, pressed=True)
        f.integrate(dt=1.0)
        _r, _u, forward = CameraController()._get_basis()
        np.testing.assert_allclose(
            cam.state.target,
            (forward * 2.0).tolist(),
            atol=1e-5,
        )

    def test_shift_doubles_speed(self):
        cam = CameraController()
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_W, MOD_SHIFT, pressed=True)
        f.integrate(dt=1.0)
        _r, _u, forward = CameraController()._get_basis()
        expected = forward * SPEED_SHIFT  # 2×
        np.testing.assert_allclose(
            cam.state.target, expected.tolist(), atol=1e-5
        )

    def test_ctrl_halves_speed(self):
        cam = CameraController()
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_W, MOD_CTRL, pressed=True)
        f.integrate(dt=1.0)
        _r, _u, forward = CameraController()._get_basis()
        expected = forward * SPEED_CTRL  # 0.5×
        np.testing.assert_allclose(
            cam.state.target, expected.tolist(), atol=1e-5
        )

    def test_shift_wins_over_ctrl_when_both_held(self):
        cam = CameraController()
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_W, MOD_SHIFT | MOD_CTRL, pressed=True)
        f.integrate(dt=1.0)
        _r, _u, forward = CameraController()._get_basis()
        expected = forward * SPEED_SHIFT  # 2× (shift wins)
        np.testing.assert_allclose(
            cam.state.target, expected.tolist(), atol=1e-5
        )


# ---------------------------------------------------------------------------
# Integration math
# ---------------------------------------------------------------------------


class TestIntegrationMath:
    def test_dt_scales_linearly(self):
        cam_a = CameraController()
        cam_b = CameraController()
        fa = FlightModeKeyboard(cam_a, base_speed=1.0)
        fb = FlightModeKeyboard(cam_b, base_speed=1.0)
        for f in (fa, fb):
            f.notify_rmb_press()
            f.handle_key_event(KEY_W, 0, pressed=True)
        fa.integrate(dt=0.5)
        fb.integrate(dt=1.0)
        a = np.asarray(cam_a.state.target, dtype=np.float32)
        b = np.asarray(cam_b.state.target, dtype=np.float32)
        # Half the dt → half the displacement.
        np.testing.assert_allclose(a * 2.0, b, atol=1e-5)

    def test_base_speed_scales_linearly(self):
        cam_a = CameraController()
        cam_b = CameraController()
        fa = FlightModeKeyboard(cam_a, base_speed=1.0)
        fb = FlightModeKeyboard(cam_b, base_speed=3.0)
        for f in (fa, fb):
            f.notify_rmb_press()
            f.handle_key_event(KEY_W, 0, pressed=True)
        fa.integrate(dt=1.0)
        fb.integrate(dt=1.0)
        a = np.asarray(cam_a.state.target, dtype=np.float32)
        b = np.asarray(cam_b.state.target, dtype=np.float32)
        np.testing.assert_allclose(a * 3.0, b, atol=1e-5)

    def test_accumulates_over_multiple_frames(self):
        cam = CameraController()
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_W, 0, pressed=True)
        for _ in range(10):
            f.integrate(dt=0.1)
        _r, _u, forward = CameraController()._get_basis()
        # 10 frames × dt=0.1 × speed=1 = 1.0 unit total displacement.
        expected = forward * 1.0
        np.testing.assert_allclose(
            cam.state.target, expected.tolist(), atol=1e-5
        )

    def test_zero_dt_is_noop(self):
        cam = CameraController()
        target0 = list(cam.state.target)
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_W, 0, pressed=True)
        f.integrate(dt=0.0)
        assert cam.state.target == target0

    def test_negative_dt_is_noop(self):
        # Defensive: a paused frame could produce dt=0 or tiny dt. A
        # negative dt shouldn't run the integrator backwards.
        cam = CameraController()
        target0 = list(cam.state.target)
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_W, 0, pressed=True)
        f.integrate(dt=-0.5)
        assert cam.state.target == target0

    def test_integrate_without_flying_is_noop(self):
        cam = CameraController()
        target0 = list(cam.state.target)
        f = FlightModeKeyboard(cam, base_speed=1.0)
        # No RMB, no keys → not flying.
        f.integrate(dt=1.0)
        assert cam.state.target == target0

    def test_no_motion_keys_held_is_noop(self):
        # RMB held + only Q pressed → not flying (Q is roll-reserved).
        cam = CameraController()
        target0 = list(cam.state.target)
        f = FlightModeKeyboard(cam, base_speed=1.0)
        f.notify_rmb_press()
        f.handle_key_event(KEY_Q, 0, pressed=True)
        f.integrate(dt=1.0)
        assert cam.state.target == target0


# ---------------------------------------------------------------------------
# subscribe_to_window
# ---------------------------------------------------------------------------


class TestSubscribeToWindow:
    def test_subscribe_wires_key_fn(self):
        # Verify that ``subscribe_to_window`` calls
        # ``set_key_pressed_fn`` on the window with our handler.
        calls = []

        class FakeWindow:
            def set_key_pressed_fn(self, fn: Any) -> None:
                calls.append(fn)

        f = _make_flight()
        win = FakeWindow()
        f.subscribe_to_window(win)
        assert len(calls) == 1
        assert calls[0] == f.handle_key_event

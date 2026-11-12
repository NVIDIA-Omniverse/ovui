# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for :mod:`ovui_widgets.viewport.camera_inertia` — Step B.4.

Tumble inertia is a pure-math coaster: takes an angular velocity vector,
applies ``velocity * dt`` through :meth:`CameraController.orbit` each
tick, and decays the velocity exponentially. Tests drive the public API
directly (``start`` / ``tick`` / ``stop``) and assert on the controller
state and on the velocity magnitude.

A second test group verifies the gesture-to-inertia handoff end-to-end:
a synthetic drag on :class:`TumbleGesture` with an inertia instance
attached, followed by a frame-tick loop, must produce the ~85% decay
over 300 ms that the viewport behavior specifies.
"""

import math
import time
from typing import List

import pytest

from ovui_widgets.viewport.camera_controller import CameraController
from ovui_widgets.viewport.camera_gesture import NavigationOptions, TumbleGesture
from ovui_widgets.viewport.camera_inertia import (
    DEFAULT_MAX_HANDOFF_AGE,
    DEFAULT_MIN_SPEED,
    DEFAULT_TIME_CONSTANT,
    DT_CLAMP_MAX,
    TUMBLE_INERTIA_SETTING,
    AngularVelocityTracker,
    TumbleInertia,
)
from ovui_widgets.viewport.camera_manipulator import CameraManipulatorModel


class _FakeClock:
    """Monotonic clock whose ``now()`` returns a settable time."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += float(dt)


def _make_inertia(model=None, tc: float = DEFAULT_TIME_CONSTANT) -> TumbleInertia:
    return TumbleInertia(CameraController(), model=model, time_constant=tc)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_defaults(self):
        inertia = _make_inertia()
        assert inertia.time_constant == DEFAULT_TIME_CONSTANT
        assert inertia.min_speed == DEFAULT_MIN_SPEED
        assert inertia.is_enabled()
        assert not inertia.is_active
        assert inertia.velocity == (0.0, 0.0)

    def test_the_default_coast_decays_with_a_0_2_s_time_constant(self):
        cam = CameraController()
        cam.state.elevation = 0.0
        inertia = TumbleInertia(cam)  # the default time constant
        inertia.start(1.0, 0.0)
        for _ in range(20):
            inertia.tick(0.01)
        assert inertia.velocity[0] == pytest.approx(math.exp(-0.2 / 0.2), rel=1e-6)

    def test_dt_clamp_bounds(self):
        # the viewport behavior calls for clamping into [0.001, 0.1].
        assert DT_CLAMP_MAX == pytest.approx(0.1)

    def test_time_constant_from_model(self):
        model = CameraManipulatorModel()
        model.set_floats("tumble_inertia", [0.5])
        inertia = TumbleInertia(CameraController(), model=model)
        assert inertia.time_constant == pytest.approx(0.5)

    def test_time_constant_falls_back_without_model(self):
        inertia = TumbleInertia(CameraController(), time_constant=0.25)
        assert inertia.time_constant == pytest.approx(0.25)

    def test_is_enabled_false_when_tc_zero(self):
        model = CameraManipulatorModel()
        model.set_floats("tumble_inertia", [0.0])
        inertia = TumbleInertia(CameraController(), model=model)
        assert not inertia.is_enabled()

    def test_is_enabled_false_when_tc_negative(self):
        model = CameraManipulatorModel()
        model.set_floats("tumble_inertia", [-0.1])
        inertia = TumbleInertia(CameraController(), model=model)
        assert not inertia.is_enabled()


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


class TestStart:
    def test_arms_with_nonzero_velocity(self):
        inertia = _make_inertia()
        assert inertia.start(2.0, 1.0) is True
        assert inertia.is_active
        assert inertia.velocity == (2.0, 1.0)

    def test_zero_velocity_no_op(self):
        inertia = _make_inertia()
        assert inertia.start(0.0, 0.0) is False
        assert not inertia.is_active

    def test_below_min_speed_no_op(self):
        # min_speed = 0.001; velocity magnitude 0.0005 is below threshold.
        inertia = _make_inertia()
        assert inertia.start(0.0005, 0.0) is False
        assert not inertia.is_active

    def test_at_min_speed_no_op(self):
        # Threshold is strict-less-than via <= — exactly min_speed is no-op.
        inertia = _make_inertia()
        assert inertia.start(DEFAULT_MIN_SPEED, 0.0) is False

    def test_disabled_when_tc_zero(self):
        model = CameraManipulatorModel()
        model.set_floats("tumble_inertia", [0.0])
        inertia = TumbleInertia(CameraController(), model=model)
        assert inertia.start(5.0, 5.0) is False
        assert not inertia.is_active

    def test_restart_replaces_velocity(self):
        inertia = _make_inertia()
        inertia.start(1.0, 2.0)
        inertia.start(3.0, 4.0)
        assert inertia.velocity == (3.0, 4.0)


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


class TestStop:
    def test_clears_velocity(self):
        inertia = _make_inertia()
        inertia.start(5.0, 5.0)
        inertia.stop()
        assert not inertia.is_active
        assert inertia.velocity == (0.0, 0.0)

    def test_idempotent(self):
        inertia = _make_inertia()
        inertia.stop()
        inertia.stop()  # no crash
        assert not inertia.is_active


# ---------------------------------------------------------------------------
# tick() — the core of the decay behaviour
# ---------------------------------------------------------------------------


class TestTick:
    def test_inactive_no_op(self):
        cam = CameraController()
        inertia = TumbleInertia(cam)
        az0, el0 = cam.state.azimuth, cam.state.elevation
        assert inertia.tick(0.016) is False
        assert cam.state.azimuth == az0
        assert cam.state.elevation == el0

    def test_zero_dt_no_op(self):
        cam = CameraController()
        inertia = TumbleInertia(cam)
        inertia.start(1.0, 0.5)
        az0 = cam.state.azimuth
        assert inertia.tick(0.0) is True
        # velocity not touched, camera not orbited
        assert cam.state.azimuth == az0
        assert inertia.velocity == (1.0, 0.5)

    def test_negative_dt_no_op(self):
        cam = CameraController()
        inertia = TumbleInertia(cam)
        inertia.start(1.0, 0.5)
        az0 = cam.state.azimuth
        assert inertia.tick(-0.5) is True
        assert cam.state.azimuth == az0

    def test_applies_orbit_then_decays(self):
        cam = CameraController()
        cam.state.elevation = 0.0  # avoid clamp
        inertia = TumbleInertia(cam, time_constant=1.0)  # slow decay for clarity
        inertia.start(1.0, 0.5)
        dt = 0.1
        inertia.tick(dt)
        # Camera orbited by velocity * dt (applied before decay).
        assert cam.state.azimuth == pytest.approx(1.0 * dt, abs=1e-6)
        assert cam.state.elevation == pytest.approx(0.5 * dt, abs=1e-6)
        # Velocity decayed by exp(-dt / tc) = exp(-0.1).
        decay = math.exp(-dt / 1.0)
        assert inertia.velocity[0] == pytest.approx(1.0 * decay)
        assert inertia.velocity[1] == pytest.approx(0.5 * decay)

    def test_decay_over_time_constant(self):
        """After one time constant, velocity should be ~1/e of initial."""
        inertia = TumbleInertia(CameraController(), time_constant=0.2)
        inertia.start(10.0, 0.0)
        # Step through one time constant in small increments.
        remaining_dt = 0.2
        while remaining_dt > 0:
            step = min(DT_CLAMP_MAX, remaining_dt)
            inertia.tick(step)
            remaining_dt -= step
        assert inertia.velocity[0] == pytest.approx(10.0 / math.e, rel=0.05)

    def test_85_percent_decay_over_300ms(self):
        """the viewport behavior requires ~85% decay over 300ms (tc=0.15)."""
        inertia = TumbleInertia(CameraController(), time_constant=0.15)
        inertia.start(100.0, 0.0)
        # Integrate 300 ms in 1/60-second steps.
        for _ in range(18):  # 18 * 1/60 ≈ 0.3s
            inertia.tick(1.0 / 60.0)
        # exp(-0.3 / 0.15) = exp(-2) ≈ 0.1353 → ~86.5% decay.
        assert inertia.velocity[0] == pytest.approx(100.0 * math.exp(-2.0), rel=0.05)

    def test_stops_below_min_speed(self):
        inertia = TumbleInertia(CameraController(), time_constant=0.01, min_speed=0.1)
        inertia.start(0.2, 0.0)
        # After a few frames the fast decay pushes us below min_speed.
        for _ in range(20):
            if not inertia.tick(0.02):
                break
        assert not inertia.is_active
        assert inertia.velocity == (0.0, 0.0)

    def test_dt_clamped_high(self):
        """Very large dt is clamped — no camera teleport."""
        cam = CameraController()
        cam.state.elevation = 0.0
        inertia = TumbleInertia(cam, time_constant=10.0)  # slow decay
        inertia.start(1.0, 0.0)
        # Request dt=10s; should be clamped to DT_CLAMP_MAX.
        inertia.tick(10.0)
        # Camera orbited by velocity * DT_CLAMP_MAX, not by velocity * 10.
        assert cam.state.azimuth == pytest.approx(1.0 * DT_CLAMP_MAX, abs=1e-6)

    def test_many_small_ticks_coast_like_one(self):
        """The camera is evaluated several times a frame: tiny steps must add up exactly."""
        cams = [CameraController(), CameraController()]
        inertias = [TumbleInertia(cam, time_constant=1.0) for cam in cams]
        for inertia in inertias:
            inertia.start(1.0, 0.0)
        inertias[0].tick(0.01)
        for _ in range(100):
            inertias[1].tick(1e-4)
        assert cams[1].state.azimuth == pytest.approx(cams[0].state.azimuth, rel=1e-2)

    def test_returns_active_state(self):
        inertia = _make_inertia()
        assert inertia.tick(0.016) is False  # inactive
        inertia.start(1.0, 0.0)
        assert inertia.tick(0.016) is True  # still active after one step

    def test_live_setting_disable_stops_coast(self):
        """Flipping tumble_inertia to 0.0 during coast stops on next tick."""
        model = CameraManipulatorModel()
        model.set_floats("tumble_inertia", [0.5])
        cam = CameraController()
        inertia = TumbleInertia(cam, model=model)
        inertia.start(1.0, 0.0)
        assert inertia.is_active
        # User disables inertia via the setting pipeline.
        model.set_floats("tumble_inertia", [0.0])
        assert inertia.tick(0.016) is False
        assert not inertia.is_active


# ---------------------------------------------------------------------------
# AngularVelocityTracker
# ---------------------------------------------------------------------------


class TestAngularVelocityTracker:
    @staticmethod
    def _drag(tracker, clock, rates, step=0.005):
        """Record one step every ``step`` seconds at each rate (rad/s) of ``rates``."""
        for rate in rates:
            clock.advance(step)
            tracker.record(rate * step, 0.0)

    def test_steady_drag_hands_off_its_speed(self):
        clock = _FakeClock()
        t = AngularVelocityTracker(clock=clock)
        self._drag(t, clock, [3.0] * 30)
        assert t.pop_handoff()[0] == pytest.approx(3.0)

    def test_a_hand_slowing_down_before_the_release_hands_off_the_slower_speed(self):
        clock = _FakeClock()
        t = AngularVelocityTracker(clock=clock)
        self._drag(t, clock, [8.0] * 20 + [2.0] * 5)
        vy, _ = t.pop_handoff()
        assert vy < 4.0

    def test_a_hand_that_stopped_before_the_release_does_not_coast(self):
        clock = _FakeClock()
        t = AngularVelocityTracker(clock=clock)
        self._drag(t, clock, [8.0] * 20)
        clock.advance(0.04)  # still, with the button held
        vy, _ = t.pop_handoff()
        assert abs(vy) < 0.5 * 8.0

    def test_stale_motion_hands_off_nothing(self):
        clock = _FakeClock()
        t = AngularVelocityTracker(clock=clock, max_handoff_age=0.1)
        self._drag(t, clock, [8.0] * 20)
        clock.advance(1.0)
        assert t.pop_handoff() == (0.0, 0.0)

    def test_pop_handoff_starts_over(self):
        clock = _FakeClock()
        t = AngularVelocityTracker(clock=clock)
        self._drag(t, clock, [8.0] * 20)
        t.pop_handoff()
        assert t.pop_handoff() == (0.0, 0.0)


# ---------------------------------------------------------------------------
# TumbleGesture + TumbleInertia integration
# ---------------------------------------------------------------------------


def _set_mouse(g, x: float, y: float) -> None:
    g.raw_input.mouse.x = x
    g.raw_input.mouse.y = y


class TestTumbleGestureInertia:
    def test_flick_drag_hands_off_velocity(self):
        cam = CameraController()
        cam.state.elevation = 0.0
        inertia = TumbleInertia(cam, time_constant=0.5)
        clock = _FakeClock()
        g = TumbleGesture(cam, inertia=inertia, clock=clock, options=NavigationOptions(rotation_gain_max=1.0))

        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        clock.advance(0.016)
        _set_mouse(g, 0.2, 0.0)  # dx_ndc = 0.2 → rotate_y = -0.2*π
        g._on_changed()
        clock.advance(0.016)
        _set_mouse(g, 0.4, 0.0)  # second frame at same velocity
        g._on_changed()
        # Immediately release — last delta is fresh.
        g._on_ended()

        assert inertia.is_active
        # rotate_y per frame was -0.2π; per sec it's -0.2π / 0.016.
        expected_vy = -0.2 * math.pi / 0.016
        assert inertia.velocity[0] == pytest.approx(expected_vy, rel=1e-6)

    def test_slow_drag_no_inertia_below_min_speed(self):
        cam = CameraController()
        inertia = TumbleInertia(cam, time_constant=0.5, min_speed=50.0)
        clock = _FakeClock()
        g = TumbleGesture(cam, inertia=inertia, clock=clock)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        clock.advance(0.016)
        _set_mouse(g, 0.001, 0.0)  # tiny motion
        g._on_changed()
        g._on_ended()
        assert not inertia.is_active

    def test_release_after_pause_no_inertia(self):
        """User stopped moving for > max_handoff_age before release."""
        cam = CameraController()
        inertia = TumbleInertia(cam, time_constant=0.5)
        clock = _FakeClock()
        g = TumbleGesture(cam, inertia=inertia, clock=clock)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        clock.advance(0.016)
        _set_mouse(g, 0.5, 0.0)
        g._on_changed()
        # Long pause — user held the mouse still.
        clock.advance(1.0)
        g._on_ended()
        assert not inertia.is_active

    def test_static_hold_then_release_no_inertia(self):
        """Hold still for the whole drag (no _on_changed call) → no coast."""
        cam = CameraController()
        inertia = TumbleInertia(cam, time_constant=0.5)
        clock = _FakeClock()
        g = TumbleGesture(cam, inertia=inertia, clock=clock)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        g._on_ended()  # no _on_changed between — nothing to hand off
        assert not inertia.is_active

    def test_new_drag_stops_running_inertia(self):
        """Starting a fresh drag kills any previous coast instantly."""
        cam = CameraController()
        inertia = TumbleInertia(cam, time_constant=0.5)
        clock = _FakeClock()
        g = TumbleGesture(cam, inertia=inertia, clock=clock)
        # First drag seeds inertia.
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        clock.advance(0.016)
        _set_mouse(g, 0.5, 0.0)
        g._on_changed()
        clock.advance(0.016)
        _set_mouse(g, 1.0, 0.0)
        g._on_changed()
        g._on_ended()
        assert inertia.is_active
        # Start a new drag — inertia must stop even though we haven't
        # handed off new velocity yet.
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        assert not inertia.is_active

    def test_tick_loop_continues_after_release(self):
        """Synthetic gesture + frame-tick loop: camera keeps orbiting."""
        cam = CameraController()
        cam.state.elevation = 0.0
        inertia = TumbleInertia(cam, time_constant=0.15)
        clock = _FakeClock()
        g = TumbleGesture(cam, inertia=inertia, clock=clock)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        clock.advance(0.016)
        _set_mouse(g, 0.1, 0.0)
        g._on_changed()
        clock.advance(0.016)
        _set_mouse(g, 0.2, 0.0)
        g._on_changed()
        az_at_release = cam.state.azimuth
        g._on_ended()
        assert inertia.is_active
        # Tick 20 frames at 60fps.
        for _ in range(20):
            inertia.tick(1.0 / 60.0)
        # Camera should have orbited further than at release.
        assert cam.state.azimuth != az_at_release

    def test_inertia_disabled_no_coast(self):
        """Setting ``tumble_inertia`` to 0.0 prevents any coast."""
        cam = CameraController()
        model = CameraManipulatorModel()
        model.set_floats("tumble_inertia", [0.0])
        inertia = TumbleInertia(cam, model=model)
        clock = _FakeClock()
        g = TumbleGesture(cam, inertia=inertia, clock=clock)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        clock.advance(0.016)
        _set_mouse(g, 0.5, 0.0)
        g._on_changed()
        clock.advance(0.016)
        _set_mouse(g, 1.0, 0.0)
        g._on_changed()
        g._on_ended()
        assert not inertia.is_active

    def test_decay_over_n_frames(self):
        """the viewport behavior acceptance: assert inertia decays over N frames."""
        cam = CameraController()
        cam.state.elevation = 0.0
        inertia = TumbleInertia(cam, time_constant=0.15)
        clock = _FakeClock()
        g = TumbleGesture(cam, inertia=inertia, clock=clock)
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        clock.advance(0.016)
        _set_mouse(g, 0.1, 0.0)
        g._on_changed()
        clock.advance(0.016)
        _set_mouse(g, 0.2, 0.0)
        g._on_changed()
        g._on_ended()
        v0 = inertia.velocity[0]
        assert v0 != 0.0
        # Record velocity per frame for 20 frames and assert monotonic decay.
        velocities: List[float] = [v0]
        for _ in range(20):
            inertia.tick(1.0 / 60.0)
            velocities.append(inertia.velocity[0])
        # Strictly shrinking magnitude until stop.
        magnitudes = [abs(v) for v in velocities]
        for prev, nxt in zip(magnitudes, magnitudes[1:]):
            assert nxt <= prev + 1e-9  # never grows

    def test_gesture_without_inertia_still_works(self):
        """LookGesture and tests that skip inertia should be unaffected."""
        cam = CameraController()
        g = TumbleGesture(cam)  # inertia=None default
        _set_mouse(g, 0.0, 0.0)
        g._on_began()
        _set_mouse(g, 0.5, 0.0)
        g._on_changed()
        g._on_ended()
        # No exception, no tracker, and camera state updated as before.
        assert cam.state.azimuth != 0.0


from types import SimpleNamespace

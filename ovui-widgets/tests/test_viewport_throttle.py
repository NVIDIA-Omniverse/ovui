# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the viewport's update/render split and the central FrameClock.

Replaces the legacy ``test_viewport_throttle.py`` that exercised the now-removed
``ViewportWidget._on_frame`` self-throttle. The new contract:

* ``ViewportWidget.update(tick_dt)`` advances flight + tumble physics every
  outer-loop tick (no render gate).
* ``ViewportWidget.render(render_dt) -> bool`` runs the RTX render path and
  returns ``True`` iff a frame actually painted.
* ``ovui_widgets.app.frame_clock.FrameClock`` owns the cadence; the Application
  consults it once per tick and only commits on a successful render.

The few residual tests that still call the legacy ``_on_frame`` shim assert
that it routes through the new methods.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np

from ovui_widgets.app.frame_clock import FrameClock
from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
from ovui_widgets.viewport.viewport_widget import ViewportWidget

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vp() -> ViewportWidget:
    renderer = MockRendererAdapter()
    vp = ViewportWidget(services=None, renderer=renderer)
    vp._build_ui()
    return vp


def _vp_with_fake_image(renderer, w: float, h: float):
    """ViewportWidget whose ``_image`` reports the given size.

    Bypasses ``_build_ui`` so render() can run end-to-end against a renderer
    mock. Always returns a correctly-shaped zero array from ``render_frame``
    so the bridge update path doesn't choke on a MagicMock result.
    """
    import numpy as np
    vp = ViewportWidget(services=None, renderer=renderer)
    img = MagicMock()
    img.visible = True
    img.computed_width = w
    img.computed_height = h
    vp._image = img

    def _fake_render(rw, rh, _view, _proj):
        return np.zeros((int(rh), int(rw), 4), dtype=np.uint8)

    if hasattr(renderer, "render_frame") and hasattr(
        renderer.render_frame, "side_effect"
    ):
        renderer.render_frame.side_effect = _fake_render
    return vp


# ---------------------------------------------------------------------------
# Configured cap — the legacy 60/10 class constants are gone; every viewport
# cadence-adjacent path derives from the Kit-compatible rateLimitFrequency
# setting instead.
# ---------------------------------------------------------------------------


class TestConfiguredMaxFps:
    def test_legacy_constants_removed(self):
        assert not hasattr(ViewportWidget, "MAX_FPS_FOREGROUND")
        assert not hasattr(ViewportWidget, "MAX_FPS_BACKGROUND")

    def test_default_legacy_tick_path_never_defers_available_work(self):
        from ovui_widgets.common.settings import Settings

        Settings.set_instance(None)
        try:
            renderer = MagicMock()
            vp = _vp_with_fake_image(renderer, 800, 600)
            vp._on_frame(0.000001)
            vp._on_frame(0.000001)
            assert renderer.render_frame.call_count == 2
            vp.destroy()
        finally:
            Settings.set_instance(None)

    def test_honors_live_setting(self):
        from ovui_widgets.common.settings import (
            RATE_LIMIT_FPS_SETTING_KEY,
            Settings,
        )

        settings = Settings()
        settings.set(RATE_LIMIT_FPS_SETTING_KEY, 30)
        Settings.set_instance(settings)
        try:
            assert ViewportWidget._configured_max_fps() == 30.0
        finally:
            Settings.set_instance(None)

    def test_invalid_setting_falls_back_to_default(self):
        from ovui_widgets.common.settings import (
            RATE_LIMIT_FPS_SETTING_KEY,
            Settings,
        )

        settings = Settings()
        settings.set(RATE_LIMIT_FPS_SETTING_KEY, "bogus")
        Settings.set_instance(settings)
        try:
            assert ViewportWidget._configured_max_fps() is None
        finally:
            Settings.set_instance(None)


# ---------------------------------------------------------------------------
# MockRenderer call tracking — unchanged
# ---------------------------------------------------------------------------


class TestMockRendererTracking:
    def test_initial_count_zero(self):
        assert MockRendererAdapter().render_call_count == 0

    def test_render_frame_increments_count(self):
        renderer = MockRendererAdapter()
        renderer.render_frame(4, 4, None, None)
        assert renderer.render_call_count == 1


# ---------------------------------------------------------------------------
# FrameClock — central cadence helper
# ---------------------------------------------------------------------------


class TestFrameClock:
    def test_first_call_returns_zero_dt(self):
        """Very first ``should_render`` returns 0.0 — first frame paints
        immediately without a fake ``time.perf_counter() - 0.0`` interval."""
        clock = FrameClock(target_fps=60.0)
        assert clock.should_render(now=100.0) == 0.0

    def test_subsequent_call_blocks_below_target_period(self):
        clock = FrameClock(target_fps=60.0)
        clock.should_render(now=100.0)
        clock.commit(now=100.0)
        # 4ms later — well below 1/60 = 16.7ms
        assert clock.should_render(now=100.004) is None

    def test_subsequent_call_passes_at_or_above_target_period(self):
        clock = FrameClock(target_fps=60.0)
        clock.commit(now=100.0)
        # 17ms later — above 1/60s
        rendered_dt = clock.should_render(now=100.017)
        assert rendered_dt is not None
        assert abs(rendered_dt - 0.017) < 1e-9

    def test_uncommitted_skip_does_not_advance_clock(self):
        """If ``commit`` is never called the clock keeps returning the
        same elapsed value — a skipped render does not poison the cadence."""
        clock = FrameClock(target_fps=60.0)
        # First call — clock stays at None.
        assert clock.should_render(now=100.0) == 0.0
        # No commit. Next "due" call still passes.
        assert clock.should_render(now=100.020) == 0.0

    def test_reset_drops_last_committed(self):
        clock = FrameClock(target_fps=60.0)
        clock.commit(now=100.0)
        clock.reset()
        # After reset, clock is "first call" again.
        assert clock.should_render(now=100.0) == 0.0
        assert clock._next_due_time is None

    def test_target_fps_zero_disables_gate(self):
        """Pass-through behaviour when constructed with target_fps=0."""
        clock = FrameClock(target_fps=0.0)
        clock.commit(now=100.0)
        # Any time after commit returns elapsed (no minimum period).
        rendered_dt = clock.should_render(now=100.000001)
        assert rendered_dt is not None


# ---------------------------------------------------------------------------
# ViewportWidget.update(tick_dt) — physics advance every tick
# ---------------------------------------------------------------------------


class TestUpdatePhysics:
    def test_update_does_not_render(self):
        """update() never calls render_frame — it's pure physics."""
        renderer = MagicMock()
        vp = _vp_with_fake_image(renderer, 800, 600)
        vp.update(0.016)
        renderer.render_frame.assert_not_called()
        vp.destroy()

    def test_update_no_op_when_not_flying_or_inertia(self):
        vp = _make_vp()
        # No exceptions / no state mutation when both physics off.
        vp.update(0.016)
        vp.destroy()

    def test_a_stalled_frame_does_not_throw_the_camera(self):
        """However long a frame took, the next matrix flies at most 0.1 s further."""
        vp = _make_vp()
        camera, fly = vp._camera, vp._flight_keyboard
        now = [0.0]
        camera.clock = lambda: now[0]
        camera.get_matrices(800, 600)
        fly.notify_rmb_press()
        fly.handle_key_event(ord("W"), 0, True)
        for _ in range(300):  # 3 s: the heavy fly reaches its speed
            now[0] += 0.01
            camera.get_matrices(800, 600)
        before = np.array(camera.state.target)
        now[0] += 0.01
        camera.get_matrices(800, 600)
        speed = np.linalg.norm(np.array(camera.state.target) - before) / 0.01
        before = np.array(camera.state.target)
        now[0] += 5.0  # huge stall
        camera.get_matrices(800, 600)
        moved = np.linalg.norm(np.array(camera.state.target) - before)
        assert speed > 0.0
        assert abs(moved - speed * 0.1) <= 1e-3 * speed * 0.1
        vp.destroy()

    def test_update_runs_when_render_skips(self):
        """Even with a hidden image (render() would skip), update() runs."""
        renderer = MagicMock()
        vp = _vp_with_fake_image(renderer, 800, 600)
        vp._image.visible = False
        # update() takes no decisions about the image — just advances physics.
        vp.update(0.016)
        renderer.render_frame.assert_not_called()
        vp.destroy()

    def test_update_zero_dt_does_not_integrate_flight(self):
        """Codex review v2 item 2: tick_dt == 0.0 must NOT call
        FlightModeKeyboard.integrate. Non-positive dt is a documented no-op
        on the integrator, so clamping it to 1ms and forwarding violates the
        contract.
        """
        renderer = MagicMock()
        vp = _vp_with_fake_image(renderer, 800, 600)
        captured = []

        def _integrate(dt):
            captured.append(dt)

        type_fk = type(vp._flight_keyboard)
        original_property = type_fk.is_flying
        type_fk.is_flying = property(lambda self: True)
        try:
            vp._flight_keyboard.integrate = _integrate  # type: ignore[assignment]
            vp.update(0.0)
        finally:
            type_fk.is_flying = original_property
        assert captured == []
        vp.destroy()

    def test_update_negative_dt_does_not_integrate_flight(self):
        """Codex review v2 item 2: a negative tick_dt must short-circuit."""
        renderer = MagicMock()
        vp = _vp_with_fake_image(renderer, 800, 600)
        captured = []

        def _integrate(dt):
            captured.append(dt)

        type_fk = type(vp._flight_keyboard)
        original_property = type_fk.is_flying
        type_fk.is_flying = property(lambda self: True)
        try:
            vp._flight_keyboard.integrate = _integrate  # type: ignore[assignment]
            vp.update(-1.0)
        finally:
            type_fk.is_flying = original_property
        assert captured == []
        vp.destroy()

    def test_update_zero_dt_does_not_tick_tumble(self):
        """Companion to the flight guard: tumble inertia is also non-op for
        non-positive dt (camera_inertia.py:181-182), so don't even call it."""
        renderer = MagicMock()
        vp = _vp_with_fake_image(renderer, 800, 600)
        captured = []

        def _tick(dt):
            captured.append(dt)

        type_ti = type(vp._tumble_inertia)
        original_property = type_ti.is_active
        type_ti.is_active = property(lambda self: True)
        try:
            vp._tumble_inertia.tick = _tick  # type: ignore[assignment]
            vp.update(0.0)
        finally:
            type_ti.is_active = original_property
        assert captured == []
        vp.destroy()


# ---------------------------------------------------------------------------
# ViewportWidget.render(render_dt) — return value, FPS HUD, gating semantics
# ---------------------------------------------------------------------------


class TestRender:
    def test_render_returns_true_when_painted(self):
        renderer = MagicMock()
        vp = _vp_with_fake_image(renderer, 800, 600)
        assert vp.render(0.016) is True
        renderer.render_frame.assert_called_once()
        vp.destroy()

    def test_render_returns_false_when_image_none(self):
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        assert vp.render(0.016) is False
        vp.destroy()

    def test_render_returns_false_when_image_hidden(self):
        renderer = MagicMock()
        vp = _vp_with_fake_image(renderer, 800, 600)
        vp._image.visible = False
        assert vp.render(0.016) is False
        renderer.render_frame.assert_not_called()
        vp.destroy()

    def test_render_returns_false_when_zero_size(self):
        renderer = MagicMock()
        vp = _vp_with_fake_image(renderer, 0, 0)
        assert vp.render(0.016) is False
        renderer.render_frame.assert_not_called()
        vp.destroy()

    def test_render_returns_false_when_renderer_none(self):
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        img = MagicMock()
        img.visible = True
        img.computed_width = 800
        img.computed_height = 600
        vp._image = img
        # Drop the renderer to simulate post-shutdown state.
        vp._renderer = None
        assert vp.render(0.016) is False

    def test_first_render_does_not_show_fake_fps(self):
        """``render_dt == 0.0`` must NOT surface as ``inf FPS`` or boot-clock garbage."""
        renderer = MagicMock()
        # Build first so the FPS label exists, then swap the image in so the
        # render path sees a non-zero size and proceeds.
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        img = MagicMock()
        img.visible = True
        img.computed_width = 800
        img.computed_height = 600
        vp._image = img
        import numpy as np
        renderer.render_frame.side_effect = lambda rw, rh, _v, _p: np.zeros(
            (int(rh), int(rw), 4), dtype=np.uint8
        )
        # FPS label starts empty.
        if vp._fps_label is not None:
            vp._fps_label.text = ""
        vp.render(0.0)  # first frame: 0.0 render_dt
        if vp._fps_label is not None:
            assert vp._fps_label.text == ""
        vp.destroy()

    def test_render_updates_fps_label_on_subsequent_frames(self):
        renderer = MagicMock()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        img = MagicMock()
        img.visible = True
        img.computed_width = 800
        img.computed_height = 600
        vp._image = img
        import numpy as np
        renderer.render_frame.side_effect = lambda rw, rh, _v, _p: np.zeros(
            (int(rh), int(rw), 4), dtype=np.uint8
        )
        # 0.1s render_dt = 10 FPS
        vp.render(0.1)
        if vp._fps_label is not None:
            assert "10" in vp._fps_label.text
        vp.destroy()

    def test_render_fps_label_uses_one_second_rolling_average(self):
        renderer = MagicMock()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        img = MagicMock()
        img.visible = True
        img.computed_width = 800
        img.computed_height = 600
        vp._image = img
        import numpy as np
        renderer.render_frame.side_effect = lambda rw, rh, _v, _p: np.zeros(
            (int(rh), int(rw), 4), dtype=np.uint8
        )

        for _ in range(60):
            vp.render(1.0 / 60.0)
        vp.render(0.1)

        if vp._fps_label is not None:
            ui_text, _, render_text = vp._fps_label.text.partition("/")
            fps = int(ui_text)
            assert fps > 40
            assert fps != 10
            # No native pacing session here, so the render side stays honest
            # rather than repeating the UI rate.
            assert render_text == "-"
        vp.destroy()

    def test_render_clamps_resolution(self):
        """Below-min computed size still clamps to MIN_RENDER_WIDTH/HEIGHT."""
        renderer = MagicMock()
        vp = _vp_with_fake_image(renderer, 10, 20)
        vp.render(0.016)
        args, _ = renderer.render_frame.call_args
        w, h, _view, _proj = args
        assert w == ViewportWidget.MIN_RENDER_WIDTH == 64
        assert h == ViewportWidget.MIN_RENDER_HEIGHT == 64
        vp.destroy()


# ---------------------------------------------------------------------------
# Application-level integration: render gate at 230 FPS still hits ~60 FPS
# ---------------------------------------------------------------------------


class TestApplicationRenderCadence:
    """Codex review item 5: at 230 FPS tick rate the viewport should still
    render about every 1/60 s — the gate must not cause a freeze."""

    def test_60_renders_per_simulated_second_at_230_fps_ticks(self):
        """Drive 230 ticks across 1.0 s of simulated wall-clock time. The
        FrameClock should fire ~60 commits, not zero (the freeze) and not
        230 (no throttle)."""
        clock = FrameClock(target_fps=60.0)
        ticks = 230
        commits = 0
        period = 1.0 / ticks
        for i in range(ticks):
            now = i * period
            render_dt = clock.should_render(now=now)
            if render_dt is not None:
                commits += 1
                clock.commit(now=now)
        # 60 ± 5 — slightly under because the period 1/230 doesn't divide
        # evenly into 1/60.
        assert 55 <= commits <= 65, f"commits={commits} not in [55,65]"

    def test_render_dt_is_period_scale_not_tick_scale(self):
        """The dt that ``render()`` sees is render-period scale (~16.7 ms),
        not tick scale (~4.3 ms). Codex review item 5."""
        clock = FrameClock(target_fps=60.0)
        clock.commit(now=0.0)
        # First tick — 4.3 ms later (230 FPS) — gate blocks.
        assert clock.should_render(now=0.0043) is None
        # 4.3*4 = 17.2 ms — gate passes; render_dt should reflect render-period.
        rendered_dt = clock.should_render(now=0.0172)
        assert rendered_dt is not None
        assert rendered_dt > 0.015
        assert rendered_dt < 0.020

    def test_near_sixty_hz_ticks_do_not_collapse_to_thirty(self):
        """Windows often reports 60 Hz-ish ticks as about 16 ms. A strict
        1/60 threshold skips every other tick and visibly halves FPS."""
        clock = FrameClock(target_fps=60.0)
        ticks = 63
        commits = 0
        period = 1.0 / ticks
        for i in range(ticks):
            now = i * period
            render_dt = clock.should_render(now=now)
            if render_dt is not None:
                commits += 1
                clock.commit(now=now)

        assert commits >= 55

    def test_one_hundred_hz_ticks_do_not_collapse_to_fifty(self):
        """A 100 Hz UI pump can still sustain an average 60 FPS cadence.

        The clock has to preserve the scheduled phase; if it anchors every
        commit to the late 20 ms tick, it renders exactly every other tick and
        settles at 50 FPS.
        """
        clock = FrameClock(target_fps=60.0)
        ticks = 100
        commits = 0
        period = 1.0 / ticks
        for i in range(ticks):
            now = i * period
            render_dt = clock.should_render(now=now)
            if render_dt is not None:
                commits += 1
                clock.commit(now=now)

        assert 55 <= commits <= 65, f"commits={commits} not in [55,65]"


# ---------------------------------------------------------------------------
# Backward-compat _on_frame shim — preserved for legacy QA scripts
# ---------------------------------------------------------------------------


class TestLegacyOnFrameShim:
    def test_small_dt_skips_render(self):
        from ovui_widgets.common.settings import (
            RATE_LIMIT_FPS_SETTING_KEY,
            Settings,
        )

        settings = Settings()
        settings.set(RATE_LIMIT_FPS_SETTING_KEY, 120.0)
        Settings.set_instance(settings)
        renderer = MagicMock()
        vp = _vp_with_fake_image(renderer, 800, 600)
        try:
            vp._on_frame(1.0 / 240)  # below the explicit 120 FPS period
            renderer.render_frame.assert_not_called()
        finally:
            vp.destroy()
            Settings.set_instance(None)

    def test_dt_at_or_above_target_paints(self):
        renderer = MagicMock()
        vp = _vp_with_fake_image(renderer, 800, 600)
        vp._on_frame(0.1)  # 10 FPS dt → passes the shim's gate
        renderer.render_frame.assert_called_once()
        vp.destroy()

    def test_direct_render_stress_cannot_exceed_cap(self, monkeypatch):
        """Repeated resize/resolution-style direct renders share one cadence
        budget: a burst of events yields at most one render per period.

        The viewport reads the time from a clock that only the test moves,
        0.1 ms for each event, so the 50 events stay in one period of the
        120 FPS cap on any machine. With the real clock, a pause of the test
        process (a garbage collection, a busy machine) could put two periods
        in the burst.
        """
        import time as real_time

        from ovui_widgets.common.settings import (
            RATE_LIMIT_FPS_SETTING_KEY,
            Settings,
        )
        from ovui_widgets.viewport import viewport_widget as viewport_module

        class _TestClock:
            """The ``time`` module of the viewport, with a ``perf_counter`` that the test moves."""

            def __init__(self) -> None:
                self.now = real_time.perf_counter()

            def perf_counter(self) -> float:
                return self.now

            def __getattr__(self, name: str) -> Any:
                return getattr(real_time, name)

        settings = Settings()
        settings.set(RATE_LIMIT_FPS_SETTING_KEY, 120.0)
        Settings.set_instance(settings)
        renderer = MagicMock()
        vp = _vp_with_fake_image(renderer, 800, 600)
        clock = _TestClock()
        monkeypatch.setattr(viewport_module, "time", clock)
        try:
            for _ in range(50):  # rapid event burst, far faster than any cap
                vp._render_rate_limited()
                clock.now += 0.0001
            assert renderer.render_frame.call_count == 1
        finally:
            vp.destroy()
            Settings.set_instance(None)

    def test_direct_render_uses_injected_shared_clock(self):
        """With the Application's clock injected, direct renders draw from
        the same budget as the frame loop."""
        renderer = MagicMock()
        vp = _vp_with_fake_image(renderer, 800, 600)
        try:
            shared = FrameClock(target_fps=120.0)
            vp.set_shared_render_clock(shared)
            assert vp._render_rate_limited() is True
            # The commit landed on the shared clock: a frame-loop render
            # right now would be gated by the same budget.
            import time as _time
            assert shared.should_render(_time.perf_counter()) is None
            # And a second direct render in the same period is skipped.
            assert vp._render_rate_limited() is False
            assert renderer.render_frame.call_count == 1
        finally:
            vp.destroy()

    def test_gate_follows_rate_limit_setting(self):
        from ovui_widgets.common.settings import (
            RATE_LIMIT_FPS_SETTING_KEY,
            Settings,
        )

        settings = Settings()
        settings.set(RATE_LIMIT_FPS_SETTING_KEY, 30)
        Settings.set_instance(settings)
        try:
            renderer = MagicMock()
            vp = _vp_with_fake_image(renderer, 800, 600)
            vp._on_frame(1.0 / 60)  # below the configured 30 FPS period
            renderer.render_frame.assert_not_called()
            vp._on_frame(1.0 / 20)  # above it
            renderer.render_frame.assert_called_once()
            vp.destroy()
        finally:
            Settings.set_instance(None)

    def test_hidden_image_skips_render(self):
        renderer = MagicMock()
        vp = _vp_with_fake_image(renderer, 800, 600)
        vp._image.visible = False
        vp._on_frame(0.1)
        renderer.render_frame.assert_not_called()
        vp.destroy()

    def test_on_frame_before_build_is_safe(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._on_frame(0.016)  # _image is None — must not crash
        vp.destroy()


# ---------------------------------------------------------------------------
# HUD render-rate sampling
# ---------------------------------------------------------------------------


class TestHudRenderRate:
    """The right-hand HUD value must belong to this viewport and to the live
    pacing session, and must never survive the session or its own sampling."""

    OWNED = 7

    @staticmethod
    def _vp(token: int) -> ViewportWidget:
        renderer = MockRendererAdapter()
        renderer._frame_pacing_token = token
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._last_fps = 60.0
        return vp

    @staticmethod
    def _sample(vp: ViewportWidget, status, clock) -> None:
        import ovui_widgets.viewport.viewport_widget as module

        with patch.object(module.ui, "get_frame_pacing_status", status, create=True):
            with patch.object(module.time, "perf_counter", clock):
                vp._record_render_update_sample()

    @staticmethod
    def _text(vp: ViewportWidget, clock, status=None) -> str:
        """Read the HUD text the way the app does: live status is readable."""
        import ovui_widgets.viewport.viewport_widget as module

        reader = status if status is not None else dict
        with patch.object(module.ui, "get_frame_pacing_status", reader, create=True):
            with patch.object(module.time, "perf_counter", clock):
                return vp._hud_fps_text()

    @classmethod
    def _status(cls, session: dict) -> Any:
        return lambda: {
            "active": True,
            "session_token": session["token"],
            "renderer_completions": session["updates"],
        }

    def test_owner_reports_render_updates_over_wall_time(self):
        vp = self._vp(self.OWNED)
        session = {"token": self.OWNED, "updates": 1000}
        status = self._status(session)
        self._sample(vp, status, lambda: 100.0)
        assert self._text(vp, lambda: 100.0, status) == "60/-"  # anchor only
        session["updates"] = 1240
        self._sample(vp, status, lambda: 102.0)
        assert self._text(vp, lambda: 102.0, status) == "60/120"
        vp.destroy()

    def test_synchronous_renderer_reports_completions_while_pacing_is_off(self):
        vp = self._vp(0)
        status = {
            "active": False,
            "metrics_epoch": 3,
            "renderer_completions": 1000,
        }
        self._sample(vp, lambda: dict(status), lambda: 100.0)
        status["renderer_completions"] = 1240
        self._sample(vp, lambda: dict(status), lambda: 102.0)
        assert self._text(vp, lambda: 102.0, lambda: dict(status)) == "60/120"
        vp.destroy()

    def test_non_owner_never_shows_another_viewports_rate(self):
        """A second viewport sees the same process-global status but owns no
        borrow, so it must not report the owner's rendering updates."""
        session = {"token": self.OWNED, "updates": 1000}
        status = self._status(session)
        owner = self._vp(self.OWNED)
        bystander = self._vp(0)
        for vp in (owner, bystander):
            self._sample(vp, status, lambda: 100.0)
        session["updates"] = 1240
        for vp in (owner, bystander):
            self._sample(vp, status, lambda: 102.0)
        assert self._text(owner, lambda: 102.0, status) == "60/120"
        assert self._text(bystander, lambda: 102.0, status) == "60/-"
        owner.destroy()
        bystander.destroy()

    def test_foreign_active_session_is_not_reported(self):
        """Owning a stale token while a different session is active must not
        borrow that session's counters."""
        vp = self._vp(self.OWNED)
        session = {"token": self.OWNED, "updates": 1000}
        self._sample(vp, self._status(session), lambda: 100.0)
        session.update(token=self.OWNED + 1, updates=1240)
        self._sample(vp, self._status(session), lambda: 102.0)
        assert self._text(vp, lambda: 102.0, self._status(session)) == "60/-"
        vp.destroy()

    def test_session_restart_does_not_spike_across_the_old_anchor(self):
        """A restarted session brings a fresh counter that must not be
        differenced against the previous session's anchor."""
        vp = self._vp(self.OWNED)
        session = {"token": self.OWNED, "updates": 1000}
        self._sample(vp, self._status(session), lambda: 100.0)
        session["updates"] = 1240
        self._sample(vp, self._status(session), lambda: 102.0)
        assert self._text(vp, lambda: 102.0, self._status(session)) == "60/120"
        # Restart: new token, and a counter above the old anchor.
        vp._renderer._frame_pacing_token = self.OWNED + 1
        session.update(token=self.OWNED + 1, updates=5000)
        self._sample(vp, self._status(session), lambda: 103.0)
        assert self._text(vp, lambda: 103.0, self._status(session)) == "60/-"
        session["updates"] = 5060
        self._sample(vp, self._status(session), lambda: 104.0)
        assert self._text(vp, lambda: 104.0, self._status(session)) == "60/60"
        vp.destroy()

    def test_inactive_session_shows_placeholder(self):
        vp = self._vp(self.OWNED)
        self._sample(
            vp,
            lambda: {"active": False, "session_token": 0,
                     "renderer_completions": 900},
            lambda: 100.0,
        )
        assert self._text(vp, lambda: 100.0) == "60/-"
        vp.destroy()

    def test_malformed_update_counts_are_not_rendered_as_zero(self):
        vp = self._vp(self.OWNED)
        for value in ({}, {"renderer_completions": None},
                      {"renderer_completions": "120"},
                      {"renderer_completions": -3}):
            payload = {"active": True, "session_token": self.OWNED}
            payload.update(value)
            self._sample(vp, lambda p=payload: p, lambda: 100.0)
            self._sample(vp, lambda p=payload: p, lambda: 102.0)
            assert self._text(vp, lambda: 102.0, lambda p=payload: p) == "60/-", value
        vp.destroy()

    def test_status_failure_shows_placeholder(self):
        vp = self._vp(self.OWNED)

        def boom():
            raise RuntimeError("status unavailable")

        self._sample(vp, boom, lambda: 100.0)
        assert self._text(vp, lambda: 100.0, boom) == "60/-"
        vp.destroy()

    def test_rate_expires_when_an_update_stops_sampling_it(self):
        """Hidden/zero-sized/disposed updates never sample, so a previously
        real rate must not stay on screen."""
        vp = self._vp(self.OWNED)
        session = {"token": self.OWNED, "updates": 1000}
        status = self._status(session)
        self._sample(vp, status, lambda: 100.0)
        session["updates"] = 1240
        self._sample(vp, status, lambda: 102.0)
        assert self._text(vp, lambda: 102.0, status) == "60/120"
        # No further samples: the viewport update stopped succeeding.
        assert self._text(
            vp, lambda: 102.0 + vp.RENDER_FPS_MAX_AGE_SECONDS + 0.1, status
        ) == "60/-"
        vp.destroy()

    def test_losing_the_borrow_drops_the_rate_immediately(self):
        vp = self._vp(self.OWNED)
        session = {"token": self.OWNED, "updates": 1000}
        status = self._status(session)
        self._sample(vp, status, lambda: 100.0)
        session["updates"] = 1240
        self._sample(vp, status, lambda: 102.0)
        assert self._text(vp, lambda: 102.0, status) == "60/120"
        vp._renderer._frame_pacing_token = 0  # borrow revoked
        assert self._text(vp, lambda: 102.0, status) == "60/-"
        vp.destroy()

    def test_snapshot_render_fps_matches_the_displayed_value(self):
        """Backend readers must not see a rate the HUD refuses to show."""
        vp = self._vp(self.OWNED)
        session = {"token": self.OWNED, "updates": 1000}
        status = self._status(session)
        self._sample(vp, status, lambda: 100.0)
        session["updates"] = 1240
        self._sample(vp, status, lambda: 102.0)
        vp._renderer._frame_pacing_token = 0  # borrow revoked
        import ovui_widgets.viewport.viewport_widget as module

        with patch.object(module.ui, "get_frame_pacing_status", status, create=True):
            with patch.object(module.time, "perf_counter", lambda: 102.0):
                snapshot = vp._build_hud_state_snapshot()
        assert snapshot.render_fps is None
        assert snapshot.fps_text == "60/-"
        vp.destroy()


class TestHudRenderRateStaysHonestOnScreen:
    """A rate that has already been painted must disappear from the label the
    moment it stops being real, including on updates that return early and so
    never resample."""

    OWNED = 11

    @staticmethod
    def _painted(session: dict) -> Any:
        """Viewport whose label really shows a sampled rate, via the ordinary
        sampling path rather than by assigning the value."""
        import ovui_widgets.viewport.viewport_widget as module

        renderer = MockRendererAdapter()
        renderer._frame_pacing_token = TestHudRenderRateStaysHonestOnScreen.OWNED
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        vp._last_fps = 60.0
        status = lambda: dict(session)
        with patch.object(module.ui, "get_frame_pacing_status", status, create=True):
            for clock, updates in ((100.0, 1000), (102.0, 1240)):
                session["renderer_completions"] = updates
                with patch.object(module.time, "perf_counter", lambda c=clock: c):
                    vp._record_render_update_sample()
            with patch.object(module.time, "perf_counter", lambda: 102.0):
                vp._refresh_hud()
        assert vp._fps_value_label.text == "60/120"
        return vp

    @staticmethod
    def _update(vp: Any, session: dict, now: float) -> bool:
        """Run a viewport update that returns early (no visible image)."""
        import ovui_widgets.viewport.viewport_widget as module

        vp._image = None
        with patch.object(module.ui, "get_frame_pacing_status",
                          lambda: dict(session), create=True):
            with patch.object(module.time, "perf_counter", lambda: now):
                return vp.render(0.016)

    @staticmethod
    def _session() -> dict:
        return {
            "active": True,
            "session_token": TestHudRenderRateStaysHonestOnScreen.OWNED,
            "renderer_completions": 1240,
            "render_loop_fatal": False,
            "render_loop_exited": False,
        }

    def test_early_return_update_clears_painted_rate_when_session_goes_inactive(self):
        session = self._session()
        vp = self._painted(session)
        session["active"] = False
        assert self._update(vp, session, 102.0) is False
        assert vp._fps_value_label.text == "60/-"
        vp.destroy()

    def test_early_return_update_clears_painted_rate_when_borrow_is_revoked(self):
        session = self._session()
        vp = self._painted(session)
        vp._renderer._frame_pacing_token = 0
        assert self._update(vp, session, 102.0) is False
        assert vp._fps_value_label.text == "60/-"
        vp.destroy()

    def test_early_return_update_clears_painted_rate_after_expiry(self):
        session = self._session()
        vp = self._painted(session)
        expired = 102.0 + vp.RENDER_FPS_MAX_AGE_SECONDS + 0.1
        assert self._update(vp, session, expired) is False
        assert vp._fps_value_label.text == "60/-"
        vp.destroy()

    def test_early_return_update_clears_painted_rate_when_status_unavailable(self):
        import ovui_widgets.viewport.viewport_widget as module

        vp = self._painted(self._session())
        vp._image = None
        with patch.object(module.ui, "get_frame_pacing_status", None, create=True):
            with patch.object(module.time, "perf_counter", lambda: 102.0):
                assert vp.render(0.016) is False
        assert vp._fps_value_label.text == "60/-"
        vp.destroy()

    def test_early_return_update_clears_painted_rate_on_fatal_or_exited_session(self):
        for failure in ("render_loop_fatal", "render_loop_exited"):
            session = self._session()
            vp = self._painted(session)
            session[failure] = True
            assert self._update(vp, session, 102.0) is False
            assert vp._fps_value_label.text == "60/-", failure
            vp.destroy()

    def test_malformed_activity_and_token_fields_do_not_keep_the_rate(self):
        for malformed in ({"active": "false"}, {"session_token": "11"},
                          {"session_token": 11.0},
                          {"renderer_completions": "1300"}):
            session = self._session()
            vp = self._painted(session)
            session.update(malformed)
            assert self._update(vp, session, 102.0) is False
            assert vp._fps_value_label.text == "60/-", malformed
            vp.destroy()

    def test_live_session_keeps_the_painted_rate_across_early_returns(self):
        """The guard must not blank a rate that is still genuine."""
        session = self._session()
        vp = self._painted(session)
        assert self._update(vp, session, 102.5) is False
        assert vp._fps_value_label.text == "60/120"
        vp.destroy()

    def test_explicit_refresh_and_snapshot_drop_an_inactive_rate(self):
        """Reads that never go through an update — an explicit HUD refresh and
        a state snapshot — must not repaint or expose a dead session's rate."""
        import ovui_widgets.viewport.viewport_widget as module

        session = self._session()
        vp = self._painted(session)
        session["active"] = False
        with patch.object(module.ui, "get_frame_pacing_status",
                          lambda: dict(session), create=True):
            with patch.object(module.time, "perf_counter", lambda: 102.0):
                vp._refresh_hud()
                snapshot = vp._build_hud_state_snapshot()
        assert vp._fps_value_label.text == "60/-"
        assert snapshot.fps_text == "60/-"
        assert snapshot.render_fps is None
        assert snapshot.fps == 60.0  # left-hand rate untouched
        vp.destroy()

    def test_counter_reset_within_the_same_session_clears_the_rate(self):
        """A counter that rolls back under an unchanged token cannot be
        differenced against the existing anchor."""
        session = self._session()
        vp = self._painted(session)
        session["renderer_completions"] = 5  # restarted beneath us
        assert self._update(vp, session, 102.0) is False
        assert vp._fps_value_label.text == "60/-"
        vp.destroy()

    def test_failed_update_that_raises_clears_the_painted_rate(self):
        """The rate must not survive an update the application aborts with an
        exception while the session is fatal."""
        import ovui_widgets.viewport.viewport_widget as module

        session = self._session()
        vp = self._painted(session)
        # Healthy when the update starts; the session dies as the work fails.
        failed = {"yet": False}

        def status() -> dict:
            current = dict(session)
            current["render_loop_fatal"] = failed["yet"]
            return current

        def explode(_self):
            failed["yet"] = True
            raise RuntimeError("renderer lost")

        image = MagicMock()
        image.visible = True
        type(image).computed_width = property(explode)
        vp._image = image
        with patch.object(module.ui, "get_frame_pacing_status", status, create=True):
            with patch.object(module.time, "perf_counter", lambda: 102.0):
                try:
                    vp.render(0.016)
                except RuntimeError:
                    pass  # the application catches and continues
        assert failed["yet"] is True
        assert vp._fps_value_label.text == "60/-"
        assert vp._resolution_render_in_progress is False
        vp.destroy()

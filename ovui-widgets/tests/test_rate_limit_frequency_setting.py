# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the Kit-compatible FPS cap setting.

``app.runLoops.main.rateLimitFrequency`` mirrors the canonical Kit path
(``/app/runLoops/main/rateLimitFrequency`` from omni.kit.loop-default's
RunLoopRunner) — default 120, CLI-overridable via
``--/app/runLoops/main/rateLimitFrequency=N``, live-updatable through a
retained Settings subscription, and enforced Kit-style on the whole main
loop iteration (``Application._pace_main_loop_iteration``) as well as on
the viewport render gate.
"""

import inspect
import json
import math
import time

import pytest

from ovui_widgets.app.__main__ import _parse_args
from ovui_widgets.app.application import Application
from ovui_widgets.common.selection import SelectionBus

KEY = Application.RATE_LIMIT_FPS_SETTING_KEY
SLASH_ARG = "--/app/runLoops/main/rateLimitFrequency"


@pytest.fixture(autouse=True)
def reset_application():
    """Reset Application and SelectionBus singletons before and after each test."""
    Application._instance = None
    SelectionBus._instance = None
    yield
    Application._instance = None
    SelectionBus._instance = None


@pytest.fixture
def app():
    application = Application()
    yield application
    application.shutdown()


class _StubViewport:
    """Minimal render target for driving _on_frame_update."""

    def __init__(self):
        self.renders = 0

    def update(self, dt):
        pass

    def render(self, dt):
        self.renders += 1
        return True


class TestDefault:
    def test_setting_name_is_kit_canonical(self):
        assert KEY == "app.runLoops.main.rateLimitFrequency"

    def test_default_cap_is_120(self, app):
        assert app.settings.get(KEY) == 120.0
        assert app._viewport_render_clock.target_fps == 120.0

    def test_frame_pacing_reassertion_keeps_setting_value(self, app):
        app.settings.set(KEY, 75)
        app._use_viewport_frame_pacing()
        assert app._viewport_render_clock.target_fps == 75.0


class TestCliOverride:
    def test_slash_path_override_reaches_clock_before_frame_loop(self):
        args = _parse_args([f"{SLASH_ARG}=30"])
        assert args.settings_overrides == {KEY: 30}
        app = Application(settings_overrides=args.settings_overrides)
        try:
            # The clock is constructed with the override — active before any
            # cadence limiting begins.
            assert app._viewport_render_clock.target_fps == 30.0
            # run()'s pacing re-assertion must not clobber it back.
            app._use_viewport_frame_pacing()
            assert app._viewport_render_clock.target_fps == 30.0
        finally:
            app.shutdown()

    def test_override_preserves_usd_file_syntax(self):
        args = _parse_args(["scene.usda", f"{SLASH_ARG}=144"])
        assert args.usd_file == "scene.usda"
        assert args.settings_overrides == {KEY: 144}

    def test_override_stays_launch_local(self, tmp_path, monkeypatch):
        persisted = tmp_path / "settings.json"
        monkeypatch.setenv("OVUI_WIDGETS_SETTINGS_PATH", str(persisted))
        app = Application(settings_overrides={KEY: 30})
        assert app._viewport_render_clock.target_fps == 30.0
        app.shutdown()
        saved = json.loads(persisted.read_text())
        assert saved[KEY] == 120.0  # default persisted, not the CLI value


class TestLiveChange:
    def test_runtime_set_updates_clock_immediately(self, app):
        app.settings.set(KEY, 240)
        assert app._viewport_render_clock.target_fps == 240.0
        app.settings.set(KEY, 24.5)
        assert app._viewport_render_clock.target_fps == 24.5

    def test_frame_loop_does_no_settings_lookups(self, app):
        """The per-tick path must use the clock's cached target only."""
        stub = _StubViewport()
        app._viewport_window = stub
        calls = []
        real_get = app._settings.get
        app._settings.get = lambda *a, **kw: (calls.append(a), real_get(*a, **kw))[1]
        try:
            for _ in range(50):
                app._on_frame_update(0.001)
        finally:
            app._settings.get = real_get
            app._viewport_window = None
        assert stub.renders >= 1  # the path actually ran
        assert calls == []

    def test_subscription_cleaned_up_on_shutdown(self):
        app = Application()
        settings = app.settings
        clock = app._viewport_render_clock
        app.shutdown()
        before = clock.target_fps
        settings.set(KEY, 15)
        assert clock.target_fps == before


class TestLiveSchedulingImmediacy:
    """A live cap change governs the very next scheduling decision — no
    production-omitted reset in these tests."""

    def _next_render_delay(self, app, t0, fake, step=0.0005, horizon=0.5):
        """Simulated seconds from t0 until the next committed render."""
        stub = app._viewport_window
        n = stub.renders
        t = t0
        while t < t0 + horizon:
            t += step
            fake[0] = t
            app._on_frame_update(step)
            if stub.renders > n:
                return t - t0
        return horizon

    def test_faster_transition_adopts_new_period(self, app, monkeypatch):
        """10 -> 100 FPS two ms after a render: next render is due at the
        *new* 10 ms period from the last commit, not the stale 100 ms one."""
        stub = _StubViewport()
        app._viewport_window = stub
        fake = [0.0]
        monkeypatch.setattr(time, "perf_counter", lambda: fake[0])
        try:
            app.settings.set(KEY, 10)
            fake[0] = 0.0
            app._on_frame_update(0.001)  # commit at t=0
            fake[0] = 0.002
            app.settings.set(KEY, 100)
            delay = self._next_render_delay(app, 0.002, fake)
            assert delay <= 0.012, f"stale 100ms deadline retained: {delay*1000:.1f}ms"
        finally:
            app._viewport_window = None

    def test_slower_transition_adopts_new_period(self, app, monkeypatch):
        """100 -> 10 FPS two ms after a render: no render is allowed until
        the *new* 100 ms period elapses from the last commit."""
        stub = _StubViewport()
        app._viewport_window = stub
        fake = [0.0]
        monkeypatch.setattr(time, "perf_counter", lambda: fake[0])
        try:
            app.settings.set(KEY, 100)
            fake[0] = 1.0
            app._on_frame_update(0.001)  # commit at t=1.0
            fake[0] = 1.002
            app.settings.set(KEY, 10)
            delay = self._next_render_delay(app, 1.002, fake)
            # Due at 1.0 + 100ms => ~98ms after the change (2ms tolerance).
            assert delay >= 0.090, f"old 10ms deadline honored: {delay*1000:.1f}ms"
        finally:
            app._viewport_window = None


class TestInvalidValueCoherence:
    """Invalid values must never leave visible, effective, and persisted
    state in conflict."""

    @pytest.mark.parametrize(
        "bad", ["fast", 0, -5, float("nan"), float("inf"), None, True, [60]]
    )
    def test_runtime_invalid_reverts_visible_setting(self, app, bad):
        app.settings.set(KEY, 90)
        app.settings.set(KEY, bad)
        assert app._viewport_render_clock.target_fps == 90.0
        assert app.settings.get(KEY) == 90.0  # visible state snapped back

    def test_runtime_invalid_does_not_change_persistence(
        self, tmp_path, monkeypatch
    ):
        persisted = tmp_path / "settings.json"
        monkeypatch.setenv("OVUI_WIDGETS_SETTINGS_PATH", str(persisted))
        app = Application()
        app.settings.set(KEY, 90)
        app.settings.set(KEY, 0)
        app.shutdown()
        assert json.loads(persisted.read_text())[KEY] == 90.0

        Application._instance = None
        SelectionBus._instance = None
        app2 = Application()
        try:
            assert app2.settings.get(KEY) == 90.0
            assert app2._viewport_render_clock.target_fps == 90.0
        finally:
            app2.shutdown()

    def test_startup_invalid_persisted_value_heals_to_default(
        self, tmp_path, monkeypatch
    ):
        persisted = tmp_path / "settings.json"
        persisted.write_text(json.dumps({KEY: 0}))
        monkeypatch.setenv("OVUI_WIDGETS_SETTINGS_PATH", str(persisted))
        app = Application()
        assert app.settings.get(KEY) == 120.0
        assert app._viewport_render_clock.target_fps == 120.0
        app.shutdown()
        assert json.loads(persisted.read_text())[KEY] == 120.0

    def test_startup_invalid_cli_falls_back_to_persisted_value(
        self, tmp_path, monkeypatch
    ):
        persisted = tmp_path / "settings.json"
        persisted.write_text(json.dumps({KEY: 90}))
        monkeypatch.setenv("OVUI_WIDGETS_SETTINGS_PATH", str(persisted))
        args = _parse_args([f"{SLASH_ARG}=fast"])
        app = Application(settings_overrides=args.settings_overrides)
        assert app.settings.get(KEY) == 90.0
        assert app._viewport_render_clock.target_fps == 90.0
        app.shutdown()
        assert json.loads(persisted.read_text())[KEY] == 90.0


class TestPumpCapWiring:
    """The ovui standalone pump is the main-loop enforcer of the cap: it is
    initialised from the setting and live-updated via set_max_frame_rate."""

    def test_run_inits_pump_with_effective_cap(self):
        """Source contract (same style as test_application_run_async_finally):
        ui.init must receive the settings-derived cap, and run_async must
        not add its own nested pacing sleep."""
        run_source = inspect.getsource(Application.run)
        assert "max_fps=self._effective_rate_limit_fps()" in run_source
        loop_source = inspect.getsource(Application.run_async)
        assert "asyncio.sleep" not in loop_source

    def test_live_change_propagates_to_pump(self, app, monkeypatch):
        import omni.ui as ui

        calls = []
        monkeypatch.setattr(
            ui, "set_max_frame_rate", lambda fps: calls.append(fps),
            raising=False,
        )
        app.settings.set(KEY, 72)
        assert calls == [72.0]
        assert app._viewport_render_clock.target_fps == 72.0

    def test_invalid_change_does_not_touch_pump(self, app, monkeypatch):
        import omni.ui as ui

        calls = []
        monkeypatch.setattr(
            ui, "set_max_frame_rate", lambda fps: calls.append(fps),
            raising=False,
        )
        app.settings.set(KEY, "bogus")
        assert calls == []

    def test_run_async_applies_cap_before_first_controlled_tick(self):
        """Cooperative hosts (_main_async) skip run()'s ui.init bootstrap:
        run_async itself must install the effective cap on the (possibly
        already-initialized) pump before awaiting the first frame."""
        source = inspect.getsource(Application.run_async)
        apply_at = source.index(
            "self._apply_rate_limit_to_ui_pump(self._effective_rate_limit_fps())"
        )
        first_tick_at = source.index("next_frame")
        assert apply_at < first_tick_at

    def test_apply_rate_limit_updates_already_initialized_pump(self, app):
        """The embedded-pump scenario: library default 60 must become the
        settings-derived effective cap (120 default) even though the value
        never transitions in the Settings store."""
        import omni.ui as ui

        before = ui.get_max_frame_rate()
        try:
            ui.set_max_frame_rate(60.0)  # embedder-owned init default
            app._apply_rate_limit_to_ui_pump(app._effective_rate_limit_fps())
            assert ui.get_max_frame_rate() == 120.0
        finally:
            ui.set_max_frame_rate(before)

    def test_request_exit_wakes_pump(self, app, monkeypatch):
        import omni.ui as ui

        woke = []
        monkeypatch.setattr(
            ui, "request_wakeup", lambda: woke.append(True), raising=False
        )
        app.request_exit()
        assert app._running is False
        assert woke == [True]


class TestCliOverlayInvalidInteraction:
    """Reviewer scenario: persisted 90, CLI overlay 30, invalid runtime 0.
    The rejected write must preserve both the overlay's transience and the
    persisted baseline."""

    def test_invalid_write_preserves_overlay_and_baseline(
        self, tmp_path, monkeypatch
    ):
        persisted = tmp_path / "settings.json"
        persisted.write_text(json.dumps({KEY: 90}))
        monkeypatch.setenv("OVUI_WIDGETS_SETTINGS_PATH", str(persisted))

        app = Application(settings_overrides={KEY: 30})
        assert app._viewport_render_clock.target_fps == 30.0
        app.settings.set(KEY, 0)  # invalid: rejected at the store boundary
        # Overlay still visible and effective; nothing was committed.
        assert app.settings.get(KEY) == 30
        assert app._viewport_render_clock.target_fps == 30.0
        app.shutdown()

        # The overlay stayed launch-local: the persisted baseline survives.
        assert json.loads(persisted.read_text())[KEY] == 90

        Application._instance = None
        SelectionBus._instance = None
        app2 = Application()
        try:
            assert app2.settings.get(KEY) == 90
            assert app2._viewport_render_clock.target_fps == 90.0
        finally:
            app2.shutdown()

    def test_valid_runtime_change_still_commits_over_overlay(
        self, tmp_path, monkeypatch
    ):
        persisted = tmp_path / "settings.json"
        persisted.write_text(json.dumps({KEY: 90}))
        monkeypatch.setenv("OVUI_WIDGETS_SETTINGS_PATH", str(persisted))

        app = Application(settings_overrides={KEY: 30})
        app.settings.set(KEY, 60)  # explicit valid change: persists
        assert app._viewport_render_clock.target_fps == 60.0
        app.shutdown()
        assert json.loads(persisted.read_text())[KEY] == 60


class TestCadenceBehavior:
    def _run_simulated_second(self, app, stub, fake_now, start, ticks=1000):
        """Drive _on_frame_update across one simulated second of perf_counter
        time starting at ``start`` and return the number of committed renders."""
        stub.renders = 0
        for i in range(ticks):
            fake_now[0] = start + i / ticks
            app._on_frame_update(1.0 / ticks)
        return stub.renders

    def test_live_transition_changes_actual_cadence(self, app, monkeypatch):
        """No manual clock reset, and time runs continuously across the
        transition — production behavior only."""
        stub = _StubViewport()
        app._viewport_window = stub
        fake_now = [0.0]
        monkeypatch.setattr(time, "perf_counter", lambda: fake_now[0])
        try:
            app.settings.set(KEY, 10)
            first = self._run_simulated_second(app, stub, fake_now, start=0.0)
            # The clock's first should_render returns 0.0 (immediate paint),
            # so allow +1 on top of the 10 Hz cadence.
            assert 9 <= first <= 12
            app.settings.set(KEY, 100)
            second = self._run_simulated_second(app, stub, fake_now, start=1.0)
            assert 90 <= second <= 110
        finally:
            app._viewport_window = None


class TestValidator:
    def test_valid_rate_limit_fps(self):
        from ovui_widgets.common.settings import valid_rate_limit_fps

        assert valid_rate_limit_fps(120, default=None) == 120.0
        assert valid_rate_limit_fps("59.94", default=None) == 59.94
        assert valid_rate_limit_fps(0, default=None) is None
        assert valid_rate_limit_fps(-1, default=None) is None
        assert valid_rate_limit_fps(True, default=None) is None
        assert valid_rate_limit_fps(math.inf, default=None) is None
        assert valid_rate_limit_fps("x", default=42.0) == 42.0

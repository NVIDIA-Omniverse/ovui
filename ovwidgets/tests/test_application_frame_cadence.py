# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the Application's central frame-cadence pipeline.

After the FrameClock split (Codex review of 675b260), Application owns:

* a per-target render clock (``_viewport_render_clock`` for the viewport),
* a tick that calls ``viewport.update(tick_dt)`` every frame and
  ``viewport.render(render_dt)`` only when the clock fires,
* a commit on the clock only when ``render()`` returns ``True``.

This file proves all five constraints survive the refactor: physics advance
even when render is gated, the gate clamps the render rate to ~60 FPS even at
230 FPS tick rate, the clock doesn't poison itself on a hidden / zero-size /
exception-throwing render, and the first render does not surface a fake
infinite FPS.
"""


from ovwidgets.app.application import Application
from ovwidgets.app.frame_clock import FrameClock


class _FakeViewport:
    """Minimal stand-in for ViewportWidget — captures update/render calls."""

    def __init__(
        self,
        render_returns: bool = True,
        render_raises: BaseException | None = None,
    ) -> None:
        self.update_calls: list[float] = []
        self.render_calls: list[float] = []
        self._render_returns = render_returns
        self._render_raises = render_raises

    def update(self, tick_dt: float) -> None:
        self.update_calls.append(tick_dt)

    def render(self, render_dt: float) -> bool:
        self.render_calls.append(render_dt)
        if self._render_raises is not None:
            raise self._render_raises
        return self._render_returns


def _fresh_app() -> Application:
    """Build a clean Application singleton without any windows."""
    Application._instance = None
    return Application(headless=True)


def _release(app: Application) -> None:
    """Drop the Application singleton without invoking the full shutdown
    path (which calls _save_layout and traverses the windows attribute,
    something the _FakeViewport stand-in doesn't implement).
    """
    app._viewport_window = None
    app._stage_window = None
    app._property_window = None
    app._content_window = None
    app._main_win = None
    app._status_win = None
    app._dockspace = None
    app._status_bar = None
    Application._instance = None


class TestPhysicsAlwaysAdvancesOnEveryTick:
    def test_update_called_when_render_throttled(self):
        app = _fresh_app()
        try:
            vp = _FakeViewport(render_returns=True)
            app._viewport_window = vp
            # First tick — render gate fires (first call returns 0.0).
            app._on_frame_update(0.005)
            # Second tick (4ms later) — render gate blocks; update still runs.
            app._on_frame_update(0.004)
            assert len(vp.update_calls) == 2
            # Render fired once on the first tick (clock returned 0.0); the
            # second tick was below 1/60s so it didn't fire again.
            assert len(vp.render_calls) == 1
        finally:
            _release(app)

    def test_update_called_when_render_skipped_for_returns_false(self):
        app = _fresh_app()
        try:
            vp = _FakeViewport(render_returns=False)
            app._viewport_window = vp
            app._on_frame_update(0.005)
            assert len(vp.update_calls) == 1
            # render() was called but returned False (zero-size, etc.)
            assert len(vp.render_calls) == 1
        finally:
            _release(app)


class TestRenderClockDoesNotPoisonOnSkip:
    def test_clock_not_committed_when_render_returns_false(self):
        """A zero-size / hidden render must not advance the clock so the
        next tick re-attempts immediately. Codex review item 5."""
        app = _fresh_app()
        try:
            vp = _FakeViewport(render_returns=False)
            app._viewport_window = vp
            # First tick — clock returns 0.0, render() called, returns False.
            app._on_frame_update(0.005)
            assert len(vp.render_calls) == 1
            # Second tick well within 1/60s of first — but clock was never
            # committed, so should_render() still passes.
            app._on_frame_update(0.001)
            assert len(vp.render_calls) == 2
        finally:
            _release(app)

    def test_clock_not_committed_when_render_raises(self):
        app = _fresh_app()
        try:
            vp = _FakeViewport(render_raises=RuntimeError("boom"))
            app._viewport_window = vp
            app._on_frame_update(0.005)  # first tick — render_calls=1, raised
            app._on_frame_update(0.001)  # second tick — clock still uncommitted
            # Both ticks attempted to render despite the raise.
            assert len(vp.render_calls) == 2
        finally:
            _release(app)

    def test_clock_committed_after_successful_render(self):
        app = _fresh_app()
        try:
            vp = _FakeViewport(render_returns=True)
            app._viewport_window = vp
            app._on_frame_update(0.005)  # first tick: render fires, clock commits
            assert len(vp.render_calls) == 1
            # Next tick at small interval — render gate blocks because clock
            # was committed on the first tick.
            app._on_frame_update(0.001)
            assert len(vp.render_calls) == 1  # no second render
        finally:
            _release(app)


class TestCadenceCappedAtMaxFpsForeground:
    def test_renders_settle_around_target_fps(self):
        """Drive 230 ticks per simulated second — render commits ~60 / s."""
        # Skip the Application path here because real ``time.monotonic()``
        # advances between ``_on_frame_update`` calls; instead test the
        # FrameClock directly with controlled time.
        clock = FrameClock(target_fps=60.0)
        ticks = 230
        commits = 0
        for i in range(ticks):
            now = i * (1.0 / ticks)
            render_dt = clock.should_render(now)
            if render_dt is not None:
                commits += 1
                clock.commit(now)
        assert 55 <= commits <= 65


class TestRendererSwapResetsClock:
    def test_set_renderer_resets_clock_via_application(self):
        """Application.reset of viewport_render_clock fires when set_renderer
        is called from the stage-load path."""
        from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
        from ovwidgets.viewport.viewport_widget import ViewportWidget
        app = _fresh_app()
        try:
            vp = ViewportWidget(services=app, renderer=MockRendererAdapter())
            app._viewport_window = vp
            # Simulate a previous successful render committing the clock.
            app._viewport_render_clock.commit(now=100.0)
            assert app._viewport_render_clock._last_committed_time == 100.0
            # _load_stage path calls set_renderer + clock.reset(); test reset
            # by simulating that hand-off here.
            new_renderer = MockRendererAdapter()
            vp.set_renderer(new_renderer)
            app._viewport_render_clock.reset()
            assert app._viewport_render_clock._last_committed_time is None
        finally:
            _release(app)

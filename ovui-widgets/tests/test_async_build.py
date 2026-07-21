# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 7.5 — async build path (``build_items_async``) scaffolding.

Covers the task's Step 7.5 done-signal checklist:

* Widget overriding :meth:`build_items_async` to yield once → build
  completes within ~2 frames (the done-signal literal).
* Widget without an async override → the synchronous
  :meth:`_do_rebuild` path runs, calling ``frame.rebuild()`` as it
  did before Step 7.5.
* Multiple yield points complete in their expected frame count
  (N yields → N+1 advances before ``StopIteration``).
* Generator is ``.close()``-ed on :meth:`destroy` so ``finally`` blocks
  in the body run.
* A second :meth:`request_rebuild` before the prior generator exhausts
  closes the stale one (no leak between selection churns).
* :meth:`_is_async_build` detection: the base and non-overriding
  subclasses return ``False``; overriders return ``True``.

The tests are headless — no real :mod:`omni.ui` root required. A
``_FakeApp`` collects ``call_later`` handles; ``step()`` fires the
handles currently scheduled (as a snapshot) so one ``step()`` models
exactly one frame advance: any new handles scheduled during this
frame fire on the next ``step()``.
"""

from __future__ import annotations

from typing import Any, List

import omni.ui as ui
import pytest

# ---------------------------------------------------------------------------
# Helpers — fake UI primitives + fake Application singleton
# ---------------------------------------------------------------------------


class _FakeFrame:
    """Recording double for :class:`ui.CollapsableFrame`.

    Captures ``rebuild()`` calls so the sync-path regression test can
    assert that :meth:`_do_rebuild` still triggers a frame rebuild.
    ``__enter__`` / ``__exit__`` let :meth:`SimplePropertyWidget.build_items`
    run end-to-end.
    """

    instances: List["_FakeFrame"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.rebuild_calls = 0
        _FakeFrame.instances.append(self)

    def __enter__(self) -> "_FakeFrame":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def rebuild(self) -> None:
        self.rebuild_calls += 1


class _FakeVStack:
    """Recording double for :class:`ui.VStack` — mirrors :class:`_FakeFrame`."""

    instances: List["_FakeVStack"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        _FakeVStack.instances.append(self)

    def __enter__(self) -> "_FakeVStack":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


@pytest.fixture()
def fake_ui(monkeypatch):
    """Patch :class:`ui.CollapsableFrame` + :class:`ui.VStack` with doubles."""
    _FakeFrame.instances = []
    _FakeVStack.instances = []
    monkeypatch.setattr(ui, "CollapsableFrame", _FakeFrame)
    monkeypatch.setattr(ui, "VStack", _FakeVStack)
    return (_FakeFrame, _FakeVStack)


class _FakeHandle:
    """Recording double for :class:`ovui_widgets.app.application.CallbackHandle`.

    ``fire()`` invokes the stored callback once; ``cancel()`` flips
    ``cancelled`` so a subsequent :meth:`_FakeApp.step` skips it.
    """

    def __init__(self, callback: Any) -> None:
        self.callback = callback
        self.cancelled = False
        self.fired = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if self.cancelled or self.fired:
            return
        self.fired = True
        self.callback()


class _FakeApp:
    """Stand-in for :class:`ovui_widgets.app.application.Application`.

    Records every ``call_later`` handle. :meth:`step` fires every
    currently-scheduled handle (a snapshot taken at entry) so one call
    to :meth:`step` models exactly one frame tick — handles scheduled
    during the tick fire on the next tick, matching the real
    :meth:`Application._on_frame_update` loop.
    """

    def __init__(self) -> None:
        self.scheduled: List[_FakeHandle] = []

    def call_later(self, delay: float, callback: Any) -> _FakeHandle:
        h = _FakeHandle(callback)
        h.delay = delay  # type: ignore[attr-defined]
        self.scheduled.append(h)
        return h

    def step(self) -> int:
        """Fire all handles present at entry. Returns number fired."""
        pending = [h for h in self.scheduled if not h.fired and not h.cancelled]
        for h in pending:
            h.fire()
        return len(pending)

    def drain(self, max_steps: int = 20) -> int:
        """Step until no more pending handles. Returns step count."""
        steps = 0
        while steps < max_steps:
            fired = self.step()
            if fired == 0:
                return steps
            steps += 1
        raise RuntimeError(
            f"Async build did not complete within {max_steps} frames — "
            f"likely an infinite-yield bug."
        )


@pytest.fixture()
def fake_app(monkeypatch):
    """Install a fake :class:`Application` singleton that records ``call_later``.

    Also registers the fake's ``call_later`` with
    :func:`ovui_widgets.common.scheduler.set_call_later` so widget code that
    routes through ``common.scheduler.call_later`` (Rev 8 §5.5; Step 5)
    reaches the same fake. Both the legacy ``Application._instance``
    monkey-patch and the ``common.scheduler`` backend are restored on
    teardown.
    """
    from ovui_widgets.app.application import Application
    from ovui_widgets.common import scheduler as _scheduler
    prior_instance = Application._instance
    prior_call_later_fn = _scheduler._call_later_fn
    app = _FakeApp()
    monkeypatch.setattr(Application, "_instance", app)
    _scheduler.set_call_later(app.call_later)
    yield app
    Application._instance = prior_instance
    _scheduler.set_call_later(prior_call_later_fn)


# ---------------------------------------------------------------------------
# _is_async_build — override detection
# ---------------------------------------------------------------------------


class TestIsAsyncBuildDetection:
    def test_base_simple_property_widget_is_not_async(self):
        from ovui_widgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        assert w._is_async_build() is False

    def test_subclass_without_override_is_not_async(self):
        from ovui_widgets.property.widget import SimplePropertyWidget

        class _Plain(SimplePropertyWidget):
            pass

        assert _Plain(title="x")._is_async_build() is False

    def test_subclass_with_override_is_async(self):
        from ovui_widgets.property.widget import SimplePropertyWidget

        class _Async(SimplePropertyWidget):
            def build_items_async(self):  # type: ignore[override]
                yield

        assert _Async(title="x")._is_async_build() is True

    def test_multi_level_inheritance_preserves_async(self):
        """Override in an intermediate class is detected through the MRO."""
        from ovui_widgets.property.widget import SimplePropertyWidget

        class _Intermediate(SimplePropertyWidget):
            def build_items_async(self):  # type: ignore[override]
                yield

        class _Leaf(_Intermediate):
            pass

        assert _Leaf(title="x")._is_async_build() is True


# ---------------------------------------------------------------------------
# Sync-path regression — widget without async override
# ---------------------------------------------------------------------------


class TestSyncPathUnchanged:
    def test_no_override_schedules_sync_rebuild(self, fake_app, fake_ui):
        """Without an async override, :meth:`request_rebuild` schedules
        :meth:`_do_rebuild` exactly as before Step 7.5."""
        from ovui_widgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        w.build_items()
        assert w._frame is not None and w._frame.rebuild_calls == 0
        w.request_rebuild()
        # One frame later, the sync rebuild fires: frame.rebuild called.
        fired = fake_app.step()
        assert fired == 1
        assert w._frame.rebuild_calls == 1

    def test_no_override_does_not_set_async_generator(self, fake_app, fake_ui):
        """Sync path must not touch ``_async_generator``."""
        from ovui_widgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        w.build_items()
        w.request_rebuild()
        fake_app.step()
        assert w._async_generator is None


# ---------------------------------------------------------------------------
# Async path — single yield (done-signal)
# ---------------------------------------------------------------------------


class TestAsyncBuildSingleYield:
    def test_single_yield_completes_within_two_frames(self, fake_app, fake_ui):
        """Done-signal from the property inspector implementation §7.5: a widget overriding
        :meth:`build_items_async` to yield once still completes its
        build within ~2 frames."""
        from ovui_widgets.property.widget import SimplePropertyWidget

        trace: List[str] = []

        class _OneYield(SimplePropertyWidget):
            def build_items_async(self):  # type: ignore[override]
                trace.append("pre")
                yield
                trace.append("post")

        w = _OneYield(title="x")
        w.build_items()
        w.request_rebuild()

        # Frame 1 — _do_rebuild_async fires, creates the generator, advances
        # once (body runs to the ``yield``).
        fake_app.step()
        assert trace == ["pre"]
        assert w._async_generator is not None

        # Frame 2 — _advance_async_generator fires, generator resumes,
        # runs ``post`` then raises ``StopIteration``.
        fake_app.step()
        assert trace == ["pre", "post"]
        assert w._async_generator is None

        # Nothing more scheduled — no runaway loop.
        assert fake_app.step() == 0

    def test_drain_completes_in_two_steps(self, fake_app, fake_ui):
        """The generic :meth:`drain` helper pins the frame count."""
        from ovui_widgets.property.widget import SimplePropertyWidget

        class _OneYield(SimplePropertyWidget):
            def build_items_async(self):  # type: ignore[override]
                yield

        w = _OneYield(title="x")
        w.build_items()
        w.request_rebuild()
        steps = fake_app.drain()
        assert steps == 2


# ---------------------------------------------------------------------------
# Async path — multiple yields
# ---------------------------------------------------------------------------


class TestAsyncBuildMultipleYields:
    def test_three_yields_complete_in_four_steps(self, fake_app, fake_ui):
        """N yields → N+1 advances (each yield costs one extra frame,
        plus one initial ``_do_rebuild_async`` kick-off)."""
        from ovui_widgets.property.widget import SimplePropertyWidget

        trace: List[int] = []

        class _Three(SimplePropertyWidget):
            def build_items_async(self):  # type: ignore[override]
                trace.append(0)
                yield
                trace.append(1)
                yield
                trace.append(2)
                yield
                trace.append(3)

        w = _Three(title="x")
        w.build_items()
        w.request_rebuild()

        fake_app.step()
        assert trace == [0]
        fake_app.step()
        assert trace == [0, 1]
        fake_app.step()
        assert trace == [0, 1, 2]
        fake_app.step()
        assert trace == [0, 1, 2, 3]
        # Done.
        assert w._async_generator is None
        assert fake_app.step() == 0

    def test_zero_yields_completes_in_one_step(self, fake_app, fake_ui):
        """A generator body with no ``yield`` still works — the function
        runs to completion on the first advance and ``StopIteration`` fires
        immediately."""
        from ovui_widgets.property.widget import SimplePropertyWidget

        trace: List[str] = []

        class _Empty(SimplePropertyWidget):
            def build_items_async(self):  # type: ignore[override]
                trace.append("done")
                # ``if False: yield`` keeps the function a generator
                # function without actually yielding.
                if False:
                    yield  # pragma: no cover

        w = _Empty(title="x")
        w.build_items()
        w.request_rebuild()

        fake_app.step()
        assert trace == ["done"]
        assert w._async_generator is None
        assert fake_app.step() == 0


# ---------------------------------------------------------------------------
# request_rebuild — coalescing behavior under async path
# ---------------------------------------------------------------------------


class TestRequestRebuildCoalescing:
    def test_second_request_cancels_pending_kickoff(self, fake_app, fake_ui):
        """If a rebuild was scheduled but hasn't fired, the second request
        cancels the first handle and schedules a fresh one."""
        from ovui_widgets.property.widget import SimplePropertyWidget

        class _A(SimplePropertyWidget):
            def build_items_async(self):  # type: ignore[override]
                yield

        w = _A(title="x")
        w.request_rebuild()
        first = fake_app.scheduled[-1]
        w.request_rebuild()
        assert first.cancelled is True
        assert fake_app.scheduled[-1].cancelled is False

    def test_second_request_closes_in_flight_generator(self, fake_app, fake_ui):
        """A second :meth:`request_rebuild` after the generator has been
        advanced once but is still paused closes the stale generator."""
        from ovui_widgets.property.widget import SimplePropertyWidget

        finally_ran: List[int] = []

        class _Leaky(SimplePropertyWidget):
            def build_items_async(self):  # type: ignore[override]
                try:
                    yield
                    yield
                finally:
                    finally_ran.append(1)

        w = _Leaky(title="x")
        w.build_items()
        w.request_rebuild()
        fake_app.step()  # kick off + run to first yield
        assert finally_ran == []
        assert w._async_generator is not None

        w.request_rebuild()
        # Stale generator closed → its ``finally`` block ran.
        assert finally_ran == [1]
        # A fresh generator hasn't been created yet — we're waiting for
        # the next frame. ``_async_generator`` is None until the new
        # kick-off fires.
        assert w._async_generator is None

    def test_no_app_instance_is_noop_for_async(self, monkeypatch, fake_ui):
        """Without an :class:`Application` singleton, async path must not
        raise. Mirrors the existing sync-path guard."""
        from ovui_widgets.app.application import Application
        from ovui_widgets.property.widget import SimplePropertyWidget

        class _A(SimplePropertyWidget):
            def build_items_async(self):  # type: ignore[override]
                yield

        monkeypatch.setattr(Application, "_instance", None)
        w = _A(title="x")
        w.request_rebuild()  # must not raise
        assert w._pending_rebuild_handle is None
        assert w._async_generator is None


# ---------------------------------------------------------------------------
# destroy — generator cleanup
# ---------------------------------------------------------------------------


class TestDestroyClosesGenerator:
    def test_destroy_runs_generator_finally_block(self, fake_app, fake_ui):
        """``gen.close()`` injects a ``GeneratorExit`` into the paused
        body, which triggers any ``finally`` block."""
        from ovui_widgets.property.widget import SimplePropertyWidget

        finally_ran: List[int] = []

        class _Leaky(SimplePropertyWidget):
            def build_items_async(self):  # type: ignore[override]
                try:
                    yield
                    yield
                finally:
                    finally_ran.append(1)

        w = _Leaky(title="x")
        w.build_items()
        w.request_rebuild()
        fake_app.step()  # kick off + first advance → paused at first yield
        assert finally_ran == []

        w.destroy()
        assert finally_ran == [1]
        assert w._async_generator is None

    def test_destroy_cancels_pending_advance_handle(self, fake_app, fake_ui):
        """The deferred advance handle is also cancelled so a stale frame
        firing doesn't resurrect the closed generator."""
        from ovui_widgets.property.widget import SimplePropertyWidget

        class _A(SimplePropertyWidget):
            def build_items_async(self):  # type: ignore[override]
                yield
                yield

        w = _A(title="x")
        w.build_items()
        w.request_rebuild()
        fake_app.step()  # kick off + first advance scheduled advance #2
        pending = w._pending_rebuild_handle
        assert pending is not None and pending.cancelled is False

        w.destroy()
        assert pending.cancelled is True
        assert w._pending_rebuild_handle is None

    def test_destroy_idempotent_without_generator(self, fake_app, fake_ui):
        """``destroy`` on a sync-only widget doesn't touch the async slot."""
        from ovui_widgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="x")
        w.build_items()
        w.destroy()
        w.destroy()  # must not raise
        assert w._async_generator is None

    def test_destroy_survives_never_built_async_widget(self):
        """A widget with async override that never entered the build path
        destroys cleanly."""
        from ovui_widgets.property.widget import SimplePropertyWidget

        class _A(SimplePropertyWidget):
            def build_items_async(self):  # type: ignore[override]
                yield

        _A(title="x").destroy()  # must not raise


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_async_generator_is_none_on_construction(self):
        from ovui_widgets.property.widget import SimplePropertyWidget
        assert SimplePropertyWidget(title="x")._async_generator is None

    def test_async_generator_is_none_on_async_subclass_construction(self):
        from ovui_widgets.property.widget import SimplePropertyWidget

        class _A(SimplePropertyWidget):
            def build_items_async(self):  # type: ignore[override]
                yield

        assert _A(title="x")._async_generator is None


# ---------------------------------------------------------------------------
# build_items_async default — base ABC default still returns None
# ---------------------------------------------------------------------------


class TestBuildItemsAsyncDefault:
    def test_property_widget_default_returns_none(self):
        """The Step 6.1 ABC contract — default returns ``None`` — is
        preserved through the Step 7.5 signature refresh. Step 7.5
        changed the return-type annotation from :class:`Coroutine` to
        :class:`Iterator` but did not change the default return value."""
        from ovui_widgets.property.widget import SimplePropertyWidget
        w = SimplePropertyWidget(title="Foo")
        assert w.build_items_async() is None

    def test_async_override_returning_none_is_noop(self, fake_app, fake_ui):
        """A subclass that overrides :meth:`build_items_async` but
        explicitly returns ``None`` should not crash the driver — it
        routes through the async kick-off (because ``_is_async_build``
        returns ``True``) but :meth:`_do_rebuild_async` early-returns
        without scheduling any advance."""
        from ovui_widgets.property.widget import SimplePropertyWidget

        class _NullAsync(SimplePropertyWidget):
            def build_items_async(self):  # type: ignore[override]
                return None

        w = _NullAsync(title="x")
        w.build_items()
        w.request_rebuild()
        fake_app.step()  # _do_rebuild_async fires, returns early
        assert w._async_generator is None
        # No runaway — no advance scheduled.
        assert fake_app.step() == 0

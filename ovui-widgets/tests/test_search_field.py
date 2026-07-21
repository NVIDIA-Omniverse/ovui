# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`SearchField` (the content browser implementation step 27).

Coverage:

* Public surface — package re-export, ``__all__`` inclusion, module
  symbols, ``url.content_close`` registered by the style layer.
* Construction — widget refs populated, no spurious callback at build
  time, text starts empty.
* Text-property semantics — reads/writes via the :class:`ui.StringField`
  model, empty string after destroy.
* Debounce (no Application fallback) — handler-path dispatch exercised
  without the frame loop so the callback fires immediately.
* Debounce (with Application fixture) — rapid typing coalesces into a
  single ``on_search`` after the 200 ms delay; a frame tick BEFORE the
  delay lands does not yet fire.
* Clear button — blanks the field, fires ``on_search("")`` immediately,
  cancels any pending debounce so a stale partial text does not land.
* Destroy — idempotent, clears widget refs, cancels the debounce
  handle, late callbacks fall through silently.

Structure mirrors ``tests/test_filter_button.py`` and
``tests/test_zoom_bar.py``: a module-scoped ``ephemeral_window`` fixture
plus an ``in_window_frame`` context manager wraps widget construction
in a real ovui build context. The ``headless_app`` fixture is supplied
by ``tests/conftest.py``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List

import omni.ui as ui
import pytest

from ovui_widgets.content.widget import SearchField
from ovui_widgets.content.widget.search_field import (
    _DEBOUNCE_SECS,
)
from ovui_widgets.content.widget.search_field import (
    SearchField as _SearchField,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """Single ovui Window reused across every widget-build test."""
    win = ui.Window("_test_search_field", width=400, height=40)
    yield win
    win.destroy()


@contextmanager
def in_window_frame(window):
    """Enter ``window.frame`` as a build context and clear it on exit."""
    try:
        with window.frame:
            yield
    finally:
        window.frame.clear()


def _noop_search(_text: str) -> None:
    """Placeholder callback when a test does not care about the emitted text."""


# ──────────────────────────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestSurface:
    def test_search_field_reexported_from_widget_package(self):
        from ovui_widgets.content.widget import SearchField as SF

        assert SF is _SearchField

    def test_widget_package_all_contains_search_field(self):
        import ovui_widgets.content.widget as pkg

        assert "SearchField" in pkg.__all__

    def test_content_close_url_registered(self):
        """Clear-button icon URL reuses the existing ``close_x.png`` asset."""
        from ovui_widgets.common.style.urls import get_icon_path

        path = get_icon_path("content_close")
        assert path.endswith("close_x.png")

    def test_content_search_url_registered(self):
        """Left-side magnifying-glass icon URL resolves to the shared search asset.

        Bug 14 — ``content_search`` aliases ``search.png`` so the
        content browser and stage filter render the same magnifier
        glyph, same pattern as ``content_close`` → ``close_x.png``.
        """
        from ovui_widgets.common.style.urls import get_icon_path

        path = get_icon_path("content_search")
        assert path.endswith("search.png")

    def test_debounce_secs_is_200ms(self):
        """Task-brief constant — a regression test against an accidental
        bump of the debounce window would otherwise go unnoticed."""
        assert _DEBOUNCE_SECS == 0.2


# ──────────────────────────────────────────────────────────────────────────────
# Construction
# ──────────────────────────────────────────────────────────────────────────────


class TestConstruction:
    def test_builds_all_widget_refs(self, ephemeral_window):
        """Every handle populated — no ``None`` slots after build."""
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_noop_search)
        try:
            assert sf._frame is not None
            assert sf._background is not None
            assert sf._hstack is not None
            assert sf._search_icon is not None
            assert sf._field is not None
            assert sf._clear_button is not None
            assert sf._clear_icon is not None
            assert sf._value_changed_sub is not None
        finally:
            sf.destroy()

    def test_initial_text_is_empty(self, ephemeral_window):
        """Default state = no filter text."""
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_noop_search)
        try:
            assert sf.text == ""
        finally:
            sf.destroy()

    def test_build_does_not_fire_callback(self, ephemeral_window):
        """No spurious on_search at construction time."""
        calls: List[str] = []
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=calls.append)
        try:
            assert calls == []
        finally:
            sf.destroy()

    def test_initial_pending_handle_is_none(self, ephemeral_window):
        """No in-flight debounce handle at build time."""
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_noop_search)
        try:
            assert sf._pending_handle is None
        finally:
            sf.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Text property
# ──────────────────────────────────────────────────────────────────────────────


class TestTextProperty:
    def test_text_reads_from_stringfield_model(self, ephemeral_window):
        """Writing via the StringField model is visible through ``text``."""
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_noop_search)
        try:
            sf._field.model.set_value("hello")
            assert sf.text == "hello"
        finally:
            sf.destroy()

    def test_text_after_destroy_is_empty(self, ephemeral_window):
        """``text`` returns ``""`` after destroy — no AttributeError."""
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_noop_search)
        sf.destroy()
        assert sf.text == ""


# ──────────────────────────────────────────────────────────────────────────────
# Debounce (no Application) — immediate-fallback path
# ──────────────────────────────────────────────────────────────────────────────


class TestDebounceFallback:
    """Without a headless Application singleton, the scheduler falls back
    to immediate dispatch — same pattern
    :meth:`FileBrowserModel._schedule_item_changed` uses. These tests
    exercise the handler wiring directly without frame-loop mechanics."""

    def test_value_change_fires_callback_immediately(self, ephemeral_window):
        """No Application → value change dispatches synchronously."""
        calls: List[str] = []
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=calls.append)
        try:
            sf._field.model.set_value("demo")
            assert calls == ["demo"]
        finally:
            sf.destroy()

    def test_empty_text_fires_callback(self, ephemeral_window):
        """Transitions to the empty string emit an ``on_search("")``."""
        calls: List[str] = []
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=calls.append)
        try:
            sf._field.model.set_value("abc")
            sf._field.model.set_value("")
            assert calls == ["abc", ""]
        finally:
            sf.destroy()

    def test_multiple_value_changes_each_fire_in_fallback(
        self, ephemeral_window,
    ):
        """Without the Application singleton there is no debouncing —
        each keystroke dispatches synchronously. Confirms the
        fallback-path behaviour differs from the with-Application
        path that :class:`TestDebounceWithApplication` covers."""
        calls: List[str] = []
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=calls.append)
        try:
            sf._field.model.set_value("a")
            sf._field.model.set_value("ab")
            sf._field.model.set_value("abc")
            assert calls == ["a", "ab", "abc"]
        finally:
            sf.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Debounce (with Application) — exercises the deferred path
# ──────────────────────────────────────────────────────────────────────────────


class TestDebounceWithApplication:
    """With a headless Application in place,
    :meth:`Application.call_later` actually defers the fire. A frame
    tick before the 200 ms window elapses does not fire; a frame tick
    after it does."""

    def test_schedule_defers_to_next_frame(
        self, ephemeral_window, headless_app,
    ):
        calls: List[str] = []
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=calls.append)
        try:
            sf._field.model.set_value("abc")
            # The handle is pending; no fire yet.
            assert sf._pending_handle is not None
            assert calls == []

            # Advance internal clock past the debounce window by
            # mutating ``_due_time`` so the frame tick dispatches.
            # Avoids wall-clock sleep in tests.
            sf._pending_handle._due_time = 0.0
            headless_app._on_frame_update(0.0)
            assert calls == ["abc"]
            assert sf._pending_handle is None
        finally:
            sf.destroy()

    def test_rapid_typing_coalesces_to_one_fire(
        self, ephemeral_window, headless_app,
    ):
        """N keystrokes within the debounce window emit one callback.

        Each keystroke cancels the previous handle and schedules a new
        one; only the last one's callback runs. The argument is the
        text at fire time (i.e. the final committed value)."""
        calls: List[str] = []
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=calls.append)
        try:
            sf._field.model.set_value("d")
            sf._field.model.set_value("de")
            sf._field.model.set_value("dem")
            # Only the latest handle is in flight.
            assert sf._pending_handle is not None
            assert calls == []

            # Fire the current handle.
            sf._pending_handle._due_time = 0.0
            headless_app._on_frame_update(0.0)
            assert calls == ["dem"]
            assert sf._pending_handle is None
        finally:
            sf.destroy()

    def test_frame_before_debounce_window_does_not_fire(
        self, ephemeral_window, headless_app,
    ):
        """A frame update before the 200 ms due time leaves the handle
        pending — ``call_later`` uses ``monotonic()`` under the hood,
        so a ``_on_frame_update(0.0)`` with the original due time does
        not trigger the callback."""
        calls: List[str] = []
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=calls.append)
        try:
            sf._field.model.set_value("abc")
            assert sf._pending_handle is not None
            # Don't mutate _due_time — a natural frame tick arriving
            # within the 200 ms window should see the handle still
            # due in the future and leave it alone.
            headless_app._on_frame_update(0.0)
            assert calls == []
            assert sf._pending_handle is not None
        finally:
            sf.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Clear button
# ──────────────────────────────────────────────────────────────────────────────


class TestClearButton:
    def test_clear_resets_text_and_fires_empty(self, ephemeral_window):
        """Clear blanks the field AND fires ``on_search("")``."""
        calls: List[str] = []
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=calls.append)
        try:
            sf._field.model.set_value("abc")
            calls.clear()

            sf._on_clear()
            assert sf.text == ""
            assert calls == [""]
        finally:
            sf.destroy()

    def test_clear_fires_once_not_twice(self, ephemeral_window):
        """The ``_suppress_change`` latch prevents the StringField's
        own value-changed dispatch from firing a second ``on_search("")``
        behind the direct clear-handler fire."""
        calls: List[str] = []
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=calls.append)
        try:
            sf._field.model.set_value("abc")
            calls.clear()

            sf._on_clear()
            # One fire total (the direct clear), not two (direct +
            # suppressed value-changed).
            assert len(calls) == 1
            assert calls == [""]
        finally:
            sf.destroy()

    def test_clear_cancels_pending_debounce(
        self, ephemeral_window, headless_app,
    ):
        """A pending debounce from prior typing must not fire after
        the clear — the user explicitly asked for ``""``, not the
        half-typed partial text."""
        calls: List[str] = []
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=calls.append)
        try:
            sf._field.model.set_value("partial")
            assert sf._pending_handle is not None
            pending_before_clear = sf._pending_handle

            sf._on_clear()
            assert pending_before_clear.is_cancelled
            assert sf._pending_handle is None

            # A frame update after the fact must not resurrect the
            # cancelled handle's fire.
            headless_app._on_frame_update(0.0)
            # Exactly one fire — the direct clear.
            assert calls == [""]
        finally:
            sf.destroy()

    def test_clear_on_already_empty_field_fires(self, ephemeral_window):
        """Clicking clear when the field is already empty still fires
        ``on_search("")`` — the clear handler is unconditional so the
        downstream model filter can rely on a click meaning "definitely
        no filter" rather than "no filter iff I wasn't already empty"."""
        calls: List[str] = []
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=calls.append)
        try:
            sf._on_clear()
            assert calls == [""]
        finally:
            sf.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Bug 8 — handler exceptions are contained (no stderr traceback)
# ──────────────────────────────────────────────────────────────────────────────


class TestHandlerExceptionContainment:
    """Bug 8 regression: a raising ``on_search`` handler must not leak a
    Python traceback to the terminal. Without the guard in
    :meth:`SearchField._fire_callback` / :meth:`SearchField._on_clear`,
    the exception bubbles to :meth:`Application._on_frame_update` which
    catches via :meth:`ErrorReporter.log_error` and writes
    ``[ERROR] [Application] call_later callback raised`` + the exception
    chain to stderr — visible to the user on every keystroke. The guard
    routes the failure through :meth:`ErrorReporter.show_warning` instead
    (status-bar only), so the console stays quiet."""

    def test_raising_handler_is_contained_in_fire_callback(
        self, ephemeral_window,
    ):
        """``_fire_callback`` must swallow handler exceptions — the
        debounce fire lands on the frame loop's ``call_later`` path and
        a raise there produces a visible stderr traceback."""
        def _boom(_text: str) -> None:
            raise RuntimeError("search handler failure")

        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_boom)
        try:
            # No-Application fallback dispatches synchronously so the
            # raise would otherwise reach the test via the value_changed
            # subscription. The guard must contain it here too.
            sf._field.model.set_value("abc")
            # Reaching this line means the exception did not propagate.
        finally:
            sf.destroy()

    def test_raising_handler_is_contained_in_clear(self, ephemeral_window):
        """Same guard covers the clear button path — ``_on_clear`` fires
        the handler directly (no debounce), so a raise would otherwise
        propagate up through ovui's ``clicked_fn`` dispatch."""
        def _boom(_text: str) -> None:
            raise ValueError("clear handler failure")

        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_boom)
        try:
            sf._on_clear()  # must not raise
        finally:
            sf.destroy()

    def test_raising_handler_leaves_state_consistent(
        self, ephemeral_window, headless_app,
    ):
        """After a raising fire, the debounce state must be back to
        baseline so the next keystroke can schedule cleanly. A leaked
        ``_pending_handle`` would prevent the next debounce from
        scheduling (``_schedule_debounced_fire`` cancels the old handle,
        so this is actually safe in practice — but the invariant that a
        fire leaves ``_pending_handle`` as ``None`` is load-bearing for
        teardown races)."""
        calls: List[str] = []

        def _boom(text: str) -> None:
            calls.append(text)
            raise RuntimeError("boom")

        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_boom)
        try:
            sf._field.model.set_value("abc")
            sf._pending_handle._due_time = 0.0
            headless_app._on_frame_update(0.0)
            # Handler ran once with the typed text.
            assert calls == ["abc"]
            # State returned to baseline — _pending_handle cleared by
            # _fire_callback before the try block, and the guard
            # absorbed the raise so nothing un-cleared it.
            assert sf._pending_handle is None
        finally:
            sf.destroy()

    def test_raising_handler_does_not_print_traceback_to_stderr(
        self, ephemeral_window, capsys,
    ):
        """``ErrorReporter.show_warning`` may write a single
        ``[STATUS:warning] …`` line to stderr when no status bar is
        wired up (unit test fallback) — that's the intended, bounded
        surface. What it must NOT do is emit a multi-line Python
        traceback (``Traceback (most recent call last): …``) which
        would be what the user sees today."""
        def _boom(_text: str) -> None:
            raise RuntimeError("search handler failure")

        # Drain any captured output buffered before this test.
        capsys.readouterr()
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_boom)
        try:
            sf._field.model.set_value("abc")
        finally:
            sf.destroy()
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "Traceback" not in combined, (
            f"Search handler raise produced a traceback: {combined!r}"
        )

    def test_clear_fallthrough_still_blanks_field_even_if_handler_raises(
        self, ephemeral_window,
    ):
        """The field must still be blanked when the handler raises —
        the user's explicit clear-button click should not be undone by
        a downstream failure in a listener. This pins the ordering: the
        field blank in :meth:`_on_clear` happens before the handler
        invocation, so the raise cannot short-circuit it."""
        def _boom(_text: str) -> None:
            raise RuntimeError("boom")

        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_boom)
        try:
            sf._field.model.set_value("partial")
            sf._on_clear()
            assert sf.text == ""
        finally:
            sf.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Destroy
# ──────────────────────────────────────────────────────────────────────────────


class TestDestroy:
    def test_destroy_clears_widget_refs(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_noop_search)
        sf.destroy()
        assert sf._frame is None
        assert sf._background is None
        assert sf._hstack is None
        assert sf._search_icon is None
        assert sf._field is None
        assert sf._clear_button is None
        assert sf._clear_icon is None
        assert sf._value_changed_sub is None

    def test_destroy_clears_handler_ref(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_noop_search)
        sf.destroy()
        assert sf._on_search is None

    def test_destroy_is_idempotent(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_noop_search)
        sf.destroy()
        sf.destroy()  # must not raise

    def test_destroy_cancels_pending_debounce(
        self, ephemeral_window, headless_app,
    ):
        """A pending debounce handle must be cancelled on destroy so
        a late frame tick does not fire into a half-nulled widget."""
        calls: List[str] = []
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=calls.append)
        sf._field.model.set_value("abc")
        pending = sf._pending_handle
        assert pending is not None

        sf.destroy()
        assert pending.is_cancelled
        assert sf._pending_handle is None

        # Drain the frame loop — the cancelled handle must not
        # re-enter the (now destroyed) widget.
        calls.clear()
        headless_app._on_frame_update(0.0)
        assert calls == []

    def test_value_change_after_destroy_does_not_raise(
        self, ephemeral_window,
    ):
        """A late ``_on_value_changed`` dispatch from a destroyed
        field must fall through silently — the ``_on_search`` guard
        in :meth:`_fire_callback` catches it."""
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_noop_search)
        sf.destroy()
        # The value-changed handler is already unsubscribed via the
        # ref drop, but a straggling direct call must still be safe.
        sf._on_value_changed(None)

    def test_clear_after_destroy_does_not_raise(self, ephemeral_window):
        """A late clear-button click must fall through silently."""
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_noop_search)
        sf.destroy()
        sf._on_clear()

    def test_text_after_destroy_is_empty(self, ephemeral_window):
        """``text`` property returns ``""`` after destroy — already
        covered by TestTextProperty; this test pins the teardown-safe
        read path specifically."""
        with in_window_frame(ephemeral_window):
            sf = SearchField(on_search=_noop_search)
        sf._field.model.set_value("abc")
        sf.destroy()
        assert sf.text == ""

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`BrowserBar` / :class:`VisitedHistory`.

Step 19 (the content browser implementation step D, the content browser behavior).

Coverage:

* :class:`VisitedHistory` — insertion order, cursor tracking,
  consecutive-duplicate skip, historical-duplicate allowed, max-size
  cap, ``_is_navigating`` latch consumption, back/forward bounds.
* :class:`BrowserBar` — construction, :meth:`set_path` routes to the
  inner :class:`PathField` and records history, back/forward fire the
  apply handler, nav buttons enable/disable correctly across the
  navigation lifecycle, destroy is idempotent.

Structure mirrors ``tests/test_path_field.py`` — a module-scoped
``ephemeral_window`` fixture plus an ``in_window_frame`` context
manager wraps widget construction in a real ovui build context.
Most :class:`VisitedHistory` tests are pure-data and do not need the
ovui fixture; only the :class:`BrowserBar` tests enter the frame.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List

import omni.ui as ui
import pytest

from ovwidgets.content.widget import BrowserBar, VisitedHistory
from ovwidgets.content.widget.browser_bar import (
    BrowserBar as _BrowserBar,
)
from ovwidgets.content.widget.browser_bar import (
    VisitedHistory as _VisitedHistory,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """Single ovui Window reused across every widget-build test."""
    win = ui.Window("_test_browser_bar", width=600, height=40)
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


def _noop(_path: str) -> None:
    """Placeholder apply handler — used when the test does not care."""


# ──────────────────────────────────────────────────────────────────────────────
# Re-export surface
# ──────────────────────────────────────────────────────────────────────────────


class TestSurface:
    def test_browser_bar_reexported_from_widget_package(self):
        from ovwidgets.content.widget import BrowserBar as BB

        assert BB is _BrowserBar

    def test_visited_history_reexported_from_widget_package(self):
        from ovwidgets.content.widget import VisitedHistory as VH

        assert VH is _VisitedHistory

    def test_widget_package_all_contains_browser_bar(self):
        import ovwidgets.content.widget as pkg

        assert "BrowserBar" in pkg.__all__
        assert "VisitedHistory" in pkg.__all__


# ──────────────────────────────────────────────────────────────────────────────
# VisitedHistory — construction
# ──────────────────────────────────────────────────────────────────────────────


class TestVisitedHistoryConstruction:
    def test_default_max_size_is_100(self):
        """Matches the content browser implementation step 19 default (architecture §15.4)."""
        hist = VisitedHistory()
        assert hist._max_size == 100

    def test_accepts_custom_max_size(self):
        hist = VisitedHistory(max_size=20)
        assert hist._max_size == 20

    def test_max_size_zero_raises(self):
        """A zero-sized history is an invariant violation — raise up front."""
        with pytest.raises(ValueError):
            VisitedHistory(max_size=0)

    def test_max_size_negative_raises(self):
        with pytest.raises(ValueError):
            VisitedHistory(max_size=-5)

    def test_initial_history_is_empty(self):
        hist = VisitedHistory()
        assert hist.size() == 0

    def test_initial_cursor_is_negative_one(self):
        """Cursor ``-1`` signals empty — invariant across every method."""
        hist = VisitedHistory()
        assert hist._cursor == -1

    def test_initial_is_navigating_is_false(self):
        hist = VisitedHistory()
        assert hist._is_navigating is False

    def test_initial_can_go_back_false(self):
        hist = VisitedHistory()
        assert hist.can_go_back is False

    def test_initial_can_go_forward_false(self):
        hist = VisitedHistory()
        assert hist.can_go_forward is False


# ──────────────────────────────────────────────────────────────────────────────
# VisitedHistory — insert
# ──────────────────────────────────────────────────────────────────────────────


class TestVisitedHistoryInsert:
    def test_single_insert_lands_at_cursor_zero(self):
        hist = VisitedHistory()
        hist.insert("/a")
        assert hist._cursor == 0
        assert hist.size() == 1

    def test_second_insert_prepends(self):
        """Newest URL occupies index 0; older entries drift higher."""
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("/b")
        assert hist._history == ["/b", "/a"]
        assert hist._cursor == 0

    def test_insert_empty_string_is_noop(self):
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("")
        assert hist.size() == 1

    def test_insert_none_is_noop(self):
        """Defensive — ``None`` is a truthy-falsy skip, not a crash."""
        hist = VisitedHistory()
        hist.insert(None)  # type: ignore[arg-type]
        assert hist.size() == 0

    def test_consecutive_duplicate_skipped(self):
        """``insert(A); insert(A)`` → one entry, not two."""
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("/a")
        assert hist.size() == 1
        assert hist._history == ["/a"]

    def test_historical_duplicate_still_inserts(self):
        """``[A, B, A]`` produces three entries — only *consecutive* dedup."""
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("/b")
        hist.insert("/a")
        assert hist.size() == 3
        assert hist._history == ["/a", "/b", "/a"]

    def test_canonical_sequence_ababa_yields_five_entries(self):
        """``[A, B, A, B, A]`` → 5 entries (the content browser implementation step 19 brief)."""
        hist = VisitedHistory()
        for url in ["/A", "/B", "/A", "/B", "/A"]:
            hist.insert(url)
        assert hist.size() == 5

    def test_max_size_trims_oldest(self):
        """When adding past ``max_size``, the tail (oldest) is dropped."""
        hist = VisitedHistory(max_size=3)
        hist.insert("/a")
        hist.insert("/b")
        hist.insert("/c")
        hist.insert("/d")
        assert hist.size() == 3
        # ``/a`` was oldest — gone. Order is newest-first.
        assert hist._history == ["/d", "/c", "/b"]

    def test_max_size_one_keeps_only_newest(self):
        """Edge case — ``max_size=1`` is a single-slot history."""
        hist = VisitedHistory(max_size=1)
        hist.insert("/a")
        hist.insert("/b")
        hist.insert("/c")
        assert hist._history == ["/c"]

    def test_insert_while_navigating_is_noop(self):
        """``_is_navigating`` latches; insert consumes and skips."""
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("/b")
        hist.go_back()  # sets _is_navigating=True
        hist.insert("/a")  # would otherwise re-insert
        assert hist.size() == 2

    def test_insert_consumes_navigating_flag(self):
        """After one suppressed insert, a subsequent insert works normally.

        The fresh insert of ``/c`` after the back-to-``/a`` also
        truncates the abandoned forward entry ``/b`` — that trail is
        stale and must not re-surface through the next ``go_back``.
        """
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("/b")
        hist.go_back()  # sets _is_navigating=True; cursor at /a
        hist.insert("/a")  # consumed, flag cleared, no entry added
        assert hist._is_navigating is False
        hist.insert("/c")  # fresh insert at cursor=1 → truncates /b
        assert hist._history[0] == "/c"
        assert hist._cursor == 0
        # /b was the abandoned forward path; /c replaces it.
        assert hist._history == ["/c", "/a"]


# ──────────────────────────────────────────────────────────────────────────────
# VisitedHistory — go_back / go_forward
# ──────────────────────────────────────────────────────────────────────────────


class TestVisitedHistoryForwardTruncation:
    """Mid-history ``insert`` drops the forward trail (web-browser semantics).

    After a back click the cursor sits inside the trail. If the user
    then navigates to a *new* location, the entries newer than the
    cursor are abandoned — a subsequent back click must return to the
    pre-insert cursor position, not step into the stale branch.
    """

    def test_insert_after_go_back_truncates_forward(self):
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("/b")
        hist.go_back()  # cursor=1 at /a, _is_navigating=True
        hist._is_navigating = False  # bypass latch for direct test
        hist.insert("/c")
        # /b (the abandoned forward path) is dropped.
        assert hist._history == ["/c", "/a"]
        assert hist._cursor == 0

    def test_back_then_forward_nav_returns_to_expected(self):
        """The bug repro: back → navigate new → back must land on old cursor."""
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("/b")
        hist.insert("/c")  # history=[/c,/b,/a], cursor=0
        # Simulate back through apply round-trip.
        hist.go_back()  # cursor=1 at /b
        hist.insert("/b")  # apply round-trip — latch consumed
        # User navigates to a new location from /b.
        hist.insert("/d")
        # Back from /d must return to /b, not to the stale /c.
        assert hist._history[hist._cursor] == "/d"
        target = hist.go_back()
        assert target == "/b"
        # And no stale forward entry remains newer than /d.
        hist._is_navigating = False
        assert hist.go_forward() == "/d"
        hist._is_navigating = False
        assert hist.go_forward() is None  # nothing past /d

    def test_insert_at_mid_history_drops_all_newer_entries(self):
        hist = VisitedHistory()
        for url in ["/a", "/b", "/c", "/d", "/e"]:
            hist.insert(url)
        # history=[/e,/d,/c,/b,/a], cursor=0
        hist.go_back()
        hist.go_back()
        hist.go_back()  # cursor=3 at /b
        hist._is_navigating = False
        hist.insert("/z")
        # Everything newer than /b is gone.
        assert hist._history == ["/z", "/b", "/a"]
        assert hist._cursor == 0

    def test_insert_same_url_at_cursor_is_noop(self):
        """Re-inserting the cursor's URL — no churn, no forward trail loss."""
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("/b")
        hist.go_back()  # cursor=1 at /a
        hist._is_navigating = False
        hist.insert("/a")  # redundant — cursor already on /a
        # Forward trail (/b) should NOT be truncated by a no-op insert.
        assert hist._history == ["/b", "/a"]
        assert hist._cursor == 1


class TestVisitedHistoryBackForward:
    def test_go_back_returns_none_on_empty(self):
        hist = VisitedHistory()
        assert hist.go_back() is None

    def test_go_back_returns_none_when_at_oldest(self):
        """Single entry: cursor at 0, no older entries to step to."""
        hist = VisitedHistory()
        hist.insert("/a")
        assert hist.go_back() is None

    def test_go_back_advances_cursor(self):
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("/b")
        # History: ["/b", "/a"], cursor=0 at "/b". Back → cursor=1, "/a".
        assert hist.go_back() == "/a"
        assert hist._cursor == 1

    def test_go_back_sets_is_navigating(self):
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("/b")
        hist.go_back()
        assert hist._is_navigating is True

    def test_go_forward_returns_none_at_newest(self):
        """No forward entries when cursor is at 0."""
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("/b")
        assert hist.go_forward() is None

    def test_go_forward_returns_none_on_empty(self):
        hist = VisitedHistory()
        assert hist.go_forward() is None

    def test_go_forward_rewinds_cursor(self):
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("/b")
        hist.insert("/c")
        # History: ["/c", "/b", "/a"], cursor=0. Back twice → cursor=2.
        hist.go_back()
        hist.go_back()
        assert hist._cursor == 2
        # Forward → cursor=1 → "/b".
        assert hist.go_forward() == "/b"
        assert hist._cursor == 1

    def test_go_forward_sets_is_navigating(self):
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("/b")
        hist.go_back()
        # Clear the flag from go_back (simulate insert consumption).
        hist._is_navigating = False
        hist.go_forward()
        assert hist._is_navigating is True

    def test_can_go_back_reflects_cursor_state(self):
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("/b")
        assert hist.can_go_back is True
        hist.go_back()
        assert hist.can_go_back is False

    def test_can_go_forward_reflects_cursor_state(self):
        hist = VisitedHistory()
        hist.insert("/a")
        hist.insert("/b")
        assert hist.can_go_forward is False
        hist.go_back()
        assert hist.can_go_forward is True


# ──────────────────────────────────────────────────────────────────────────────
# BrowserBar — construction
# ──────────────────────────────────────────────────────────────────────────────


class TestBrowserBarConstruction:
    def test_instantiates_with_minimal_handler(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        assert isinstance(bar, BrowserBar)
        bar.destroy()

    def test_constructor_accepts_all_handlers(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(
                apply_path_handler=_noop,
                autocomplete_handler=lambda p, cb: cb([]),
                begin_edit_handler=lambda: None,
                visited_history_max=20,
            )
        assert bar._history._max_size == 20
        bar.destroy()

    def test_default_history_max_is_100(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        assert bar._history._max_size == 100
        bar.destroy()

    def test_path_field_is_constructed(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        assert bar._path_field is not None
        bar.destroy()

    def test_buttons_start_disabled(self, ephemeral_window):
        """Empty history → both nav buttons disabled at build time."""
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        assert bar._back_button.enabled is False
        assert bar._forward_button.enabled is False
        bar.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# BrowserBar — set_path
# ──────────────────────────────────────────────────────────────────────────────


class TestBrowserBarSetPath:
    def test_set_path_updates_path_field(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.set_path("/home/user")
        assert bar._path_field.path == "/home/user"
        bar.destroy()

    def test_set_path_records_in_history(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.set_path("/home/user")
        assert bar._history.size() == 1
        bar.destroy()

    def test_set_path_does_not_fire_apply_handler(self, ephemeral_window):
        """Caller is driving set_path — re-firing would cause a loop."""
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=received.append)
        bar.set_path("/home/user")
        assert received == []
        bar.destroy()

    def test_set_path_consecutive_dup_keeps_history_size(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.set_path("/a")
        bar.set_path("/a")
        assert bar._history.size() == 1
        bar.destroy()

    def test_set_path_multiple_updates_history_in_order(
        self, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.set_path("/a")
        bar.set_path("/b")
        bar.set_path("/c")
        # Newest-first ordering.
        assert bar._history._history == ["/c", "/b", "/a"]
        bar.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# BrowserBar — go_back / go_forward
# ──────────────────────────────────────────────────────────────────────────────


class TestBrowserBarGoBack:
    def test_go_back_with_empty_history_is_noop(self, ephemeral_window):
        """No entries to step to — button is a no-op, no apply fires."""
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=received.append)
        bar.go_back()
        assert received == []
        bar.destroy()

    def test_go_back_fires_apply_with_previous_url(self, ephemeral_window):
        """Back navigation dispatches the older URL through the apply handler.

        :meth:`BrowserBar.set_path` does not fire the apply handler —
        the caller drives that loop — so the received list records
        only the back-click dispatch. History is ``["/b", "/a"]`` with
        cursor at 0; back steps cursor to 1 and apply receives ``"/a"``.
        """
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=received.append)
        bar.set_path("/a")
        bar.set_path("/b")
        bar.go_back()
        assert received == ["/a"]
        bar.destroy()

    def test_go_back_updates_path_field_immediately(self, ephemeral_window):
        """Bar echoes the target into :class:`PathField` before apply fires."""
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.set_path("/a")
        bar.set_path("/b")
        bar.go_back()
        assert bar._path_field.path == "/a"
        bar.destroy()

    def test_go_back_does_not_insert_into_history(self, ephemeral_window):
        """Back navigation sets the ``_is_navigating`` latch that skips inserts."""
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.set_path("/a")
        bar.set_path("/b")
        size_before = bar._history.size()
        bar.go_back()
        assert bar._history.size() == size_before
        bar.destroy()

    def test_back_apply_triggers_set_path_does_not_re_insert(
        self, ephemeral_window,
    ):
        """Full round-trip: back → apply-handler → caller's set_path.

        Simulates Step 20's wiring where the caller's apply-path
        handler re-calls ``bar.set_path`` after backend navigation. The
        flag should keep the history from re-recording the target.
        """
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.set_path("/a")
        bar.set_path("/b")
        size_before = bar._history.size()
        bar.go_back()
        # Caller's apply would typically re-call set_path:
        bar.set_path("/a")
        assert bar._history.size() == size_before
        bar.destroy()


class TestBrowserBarGoForward:
    def test_go_forward_with_empty_history_is_noop(self, ephemeral_window):
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=received.append)
        bar.go_forward()
        assert received == []
        bar.destroy()

    def test_go_forward_at_newest_is_noop(self, ephemeral_window):
        """Cursor at 0 — no newer entries — apply handler not fired."""
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=received.append)
        bar.set_path("/a")
        bar.go_forward()
        assert received == []
        bar.destroy()

    def test_go_forward_after_go_back_returns_to_newest(self, ephemeral_window):
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=received.append)
        bar.set_path("/a")
        bar.set_path("/b")
        bar.go_back()     # → "/a"
        bar.go_forward()  # → "/b"
        assert received == ["/a", "/b"]
        bar.destroy()

    def test_go_forward_updates_path_field(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.set_path("/a")
        bar.set_path("/b")
        bar.go_back()
        bar.go_forward()
        assert bar._path_field.path == "/b"
        bar.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# BrowserBar — nav button enabled state
# ──────────────────────────────────────────────────────────────────────────────


class TestBrowserBarNavButtons:
    def test_empty_history_both_buttons_disabled(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        assert bar._back_button.enabled is False
        assert bar._forward_button.enabled is False
        bar.destroy()

    def test_single_entry_both_buttons_disabled(self, ephemeral_window):
        """One entry: nowhere to go back or forward to."""
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.set_path("/a")
        assert bar._back_button.enabled is False
        assert bar._forward_button.enabled is False
        bar.destroy()

    def test_two_entries_back_enabled_forward_disabled(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.set_path("/a")
        bar.set_path("/b")
        assert bar._back_button.enabled is True
        assert bar._forward_button.enabled is False
        bar.destroy()

    def test_after_go_back_forward_becomes_enabled(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.set_path("/a")
        bar.set_path("/b")
        bar.go_back()
        assert bar._back_button.enabled is False
        assert bar._forward_button.enabled is True
        bar.destroy()

    def test_middle_of_history_both_enabled(self, ephemeral_window):
        """At cursor=1 of a 3-entry history, both directions are reachable."""
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.set_path("/a")
        bar.set_path("/b")
        bar.set_path("/c")
        bar.go_back()  # cursor=1 of ["/c", "/b", "/a"]
        assert bar._back_button.enabled is True
        assert bar._forward_button.enabled is True
        bar.destroy()

    def test_after_go_forward_to_newest_forward_disabled(
        self, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.set_path("/a")
        bar.set_path("/b")
        bar.go_back()
        bar.go_forward()
        assert bar._forward_button.enabled is False
        assert bar._back_button.enabled is True
        bar.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# BrowserBar — destroy
# ──────────────────────────────────────────────────────────────────────────────


class TestBrowserBarDestroy:
    def test_destroy_clears_widget_refs(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.destroy()
        assert bar._hstack is None
        assert bar._back_button is None
        assert bar._forward_button is None
        assert bar._path_field is None

    def test_destroy_clears_handler_refs(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(
                apply_path_handler=_noop,
                autocomplete_handler=lambda p, cb: cb([]),
                begin_edit_handler=lambda: None,
            )
        bar.destroy()
        assert bar._apply_path_handler is None
        assert bar._autocomplete_handler is None
        assert bar._begin_edit_handler is None

    def test_destroy_is_idempotent(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.destroy()
        # Second call must not raise.
        bar.destroy()

    def test_destroy_after_set_path_does_not_crash(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.set_path("/home/user")
        bar.destroy()

    def test_destroy_after_go_back_does_not_crash(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            bar = BrowserBar(apply_path_handler=_noop)
        bar.set_path("/a")
        bar.set_path("/b")
        bar.go_back()
        bar.destroy()

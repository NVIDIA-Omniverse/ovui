# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`PathField` (the content browser implementation step 17).

Coverage:

* Tokenization of absolute paths, URL-prefixed paths, Windows drive
  letters, empty paths, and multi-slash edge cases.
* Breadcrumb-click dispatch — verifies the ``apply_path_handler``
  receives the correct accumulated URL for each segment, including
  the URL-prefix-only click and the drive-letter trailing-slash rule.
* :meth:`PathField.set_path` updates the :attr:`path` property and
  re-renders the breadcrumb strip without dispatching the handler
  (caller drives that loop).
* Empty path renders zero breadcrumbs and does not crash.
* :meth:`PathField.destroy` is idempotent and releases handler refs.

Structure matches ``tests/test_file_browser_widget.py`` — a single
module-scoped ``ephemeral_window`` fixture + an ``in_window_frame``
context manager so widget construction happens inside a real ovui
build context. Most tests cover pure-data paths that do not need a
running :class:`Application`; the widget itself doesn't call into the
singleton.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List

import omni.ui as ui
import pytest

from ovui_widgets.content.widget import PathField
from ovui_widgets.content.widget.path_field import (
    MODE_BREADCRUMB,
    MODE_EDIT,
)
from ovui_widgets.content.widget.path_field import (
    PathField as _PathField,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """Single ovui Window reused across every widget-build test.

    Same pattern as the other widget-level test modules — constructing
    a :class:`ui.Window` per test measurably slows the module down
    (docking registration, frame allocation); sharing one and clearing
    its frame between tests gives the same isolation at a fraction of
    the cost.
    """
    win = ui.Window("_test_path_field", width=600, height=60)
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
# Public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestSurface:
    def test_reexported_from_widget_package(self):
        from ovui_widgets.content.widget import PathField as PF

        assert PF is _PathField

    def test_widget_package_all_contains_path_field(self):
        import ovui_widgets.content.widget as pkg

        assert "PathField" in pkg.__all__

    def test_instantiates_with_minimal_handler(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        assert isinstance(widget, PathField)
        widget.destroy()

    def test_default_prefix_separator_is_file_scheme(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        assert widget._prefix_separator == "file://"
        widget.destroy()

    def test_initial_path_is_empty_string(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        assert widget.path == ""
        widget.destroy()

    def test_constructor_accepts_all_optional_handlers(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=lambda prefix, cb: cb([]),
                begin_edit_handler=lambda: None,
                prefix_separator="mock://",
            )
        assert widget._prefix_separator == "mock://"
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Tokenization
# ──────────────────────────────────────────────────────────────────────────────


class TestTokenization:
    """Tokenization cases — the content browser behavior table.

    The widget strips ``prefix_separator`` if present, splits the
    remainder on ``/``, and drops empty segments (absorbing the
    leading ``/`` on Linux absolute paths). The task brief's canonical
    case — ``/home/user/docs`` → ``["home", "user", "docs"]`` — is the
    dropping-empties rule in action.
    """

    def _make(self, prefix: str = "file://") -> PathField:
        # Tokenization is pure — no ovui build context required, so
        # skip the ``ephemeral_window`` fixture here. The constructor
        # does create an HStack etc. internally; those succeed because
        # the classes themselves are instantiable without a ``with``
        # context (ovui tolerates "detached" widgets during tests).
        return PathField(apply_path_handler=_noop, prefix_separator=prefix)

    def test_empty_path_tokenizes_to_empty_list(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = self._make()
        assert widget._tokenize("") == []
        widget.destroy()

    def test_linux_absolute_path_drops_leading_empty(self, ephemeral_window):
        """``/home/user/docs`` → ``["home", "user", "docs"]`` (task brief)."""
        with in_window_frame(ephemeral_window):
            widget = self._make()
        assert widget._tokenize("/home/user/docs") == ["home", "user", "docs"]
        widget.destroy()

    def test_file_url_preserves_scheme_as_first_token(self, ephemeral_window):
        """``file:///home/user`` → ``["file://", "home", "user"]``."""
        with in_window_frame(ephemeral_window):
            widget = self._make(prefix="file://")
        assert widget._tokenize("file:///home/user") == [
            "file://", "home", "user",
        ]
        widget.destroy()

    def test_file_url_with_single_segment(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = self._make(prefix="file://")
        assert widget._tokenize("file:///home") == ["file://", "home"]
        widget.destroy()

    def test_mock_url_with_custom_prefix(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = self._make(prefix="mock://")
        assert widget._tokenize("mock://Home/Documents") == [
            "mock://", "Home", "Documents",
        ]
        widget.destroy()

    def test_windows_drive_letter_preserves_colon(self, ephemeral_window):
        """``C:/Users/jack`` → ``["C:", "Users", "jack"]``."""
        with in_window_frame(ephemeral_window):
            widget = self._make(prefix="file://")
        assert widget._tokenize("C:/Users/jack") == ["C:", "Users", "jack"]
        widget.destroy()

    def test_empty_prefix_separator_keeps_path_intact(self, ephemeral_window):
        """No prefix to strip → raw split + empty-filter behaviour."""
        with in_window_frame(ephemeral_window):
            widget = self._make(prefix="")
        # A file:// URL passed in without a configured prefix is parsed
        # as ``file:`` + ``/home`` + ``user`` — the scheme is not
        # recognised and the colon sticks with the segment.
        assert widget._tokenize("file:///home/user") == [
            "file:", "home", "user",
        ]
        widget.destroy()

    def test_repeated_slashes_collapse(self, ephemeral_window):
        """``//a//b`` → ``["a", "b"]`` (empty-segment filter)."""
        with in_window_frame(ephemeral_window):
            widget = self._make()
        assert widget._tokenize("//a//b") == ["a", "b"]
        widget.destroy()

    def test_trailing_slash_is_dropped(self, ephemeral_window):
        """``/home/user/`` → ``["home", "user"]`` (no trailing empty)."""
        with in_window_frame(ephemeral_window):
            widget = self._make()
        assert widget._tokenize("/home/user/") == ["home", "user"]
        widget.destroy()

    def test_root_only_path_is_empty_breadcrumbs(self, ephemeral_window):
        """``/`` → ``[]`` (single empty segment filtered)."""
        with in_window_frame(ephemeral_window):
            widget = self._make()
        assert widget._tokenize("/") == []
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Accumulated path
# ──────────────────────────────────────────────────────────────────────────────


class TestAccumulatedPath:
    """Verify :meth:`_accumulated_path` reconstructs navigation URLs."""

    def _make_with(
        self,
        path: str,
        prefix: str = "file://",
    ) -> PathField:
        widget = PathField(
            apply_path_handler=_noop,
            prefix_separator=prefix,
        )
        widget.set_path(path)
        return widget

    def test_linux_first_segment_is_absolute(self, ephemeral_window):
        """Click ``home`` in ``/home/user/docs`` → ``/home``."""
        with in_window_frame(ephemeral_window):
            widget = self._make_with("/home/user/docs")
        assert widget._accumulated_path(0) == "/home"
        widget.destroy()

    def test_linux_middle_segment(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = self._make_with("/home/user/docs")
        assert widget._accumulated_path(1) == "/home/user"
        widget.destroy()

    def test_linux_last_segment_is_full_path(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = self._make_with("/home/user/docs")
        assert widget._accumulated_path(2) == "/home/user/docs"
        widget.destroy()

    def test_file_url_prefix_click_returns_prefix_only(self, ephemeral_window):
        """Click ``file://`` returns just the URL scheme."""
        with in_window_frame(ephemeral_window):
            widget = self._make_with("file:///home/user")
        assert widget._accumulated_path(0) == "file://"
        widget.destroy()

    def test_file_url_segment_prepends_prefix_and_slash(self, ephemeral_window):
        """Click ``home`` in ``file:///home/user`` → ``file:///home``."""
        with in_window_frame(ephemeral_window):
            widget = self._make_with("file:///home/user")
        assert widget._accumulated_path(1) == "file:///home"
        widget.destroy()

    def test_file_url_second_segment(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = self._make_with("file:///home/user")
        assert widget._accumulated_path(2) == "file:///home/user"
        widget.destroy()

    def test_mock_url_non_absolute_no_extra_slash(self, ephemeral_window):
        """``mock://Home/Docs`` — first segment click → ``mock://Home``."""
        with in_window_frame(ephemeral_window):
            widget = self._make_with("mock://Home/Docs", prefix="mock://")
        # index 0 = prefix, index 1 = "Home" → mock://Home (no extra /)
        assert widget._accumulated_path(1) == "mock://Home"
        widget.destroy()

    def test_windows_drive_letter_gets_trailing_slash(self, ephemeral_window):
        """``C:/Users/jack`` — click ``C:`` → ``C:/`` (trailing slash)."""
        with in_window_frame(ephemeral_window):
            widget = self._make_with("C:/Users/jack", prefix="file://")
        assert widget._accumulated_path(0) == "C:/"
        widget.destroy()

    def test_windows_drive_letter_second_segment(self, ephemeral_window):
        """Click ``Users`` → ``C:/Users`` (no trailing slash on sub-segments)."""
        with in_window_frame(ephemeral_window):
            widget = self._make_with("C:/Users/jack", prefix="file://")
        assert widget._accumulated_path(1) == "C:/Users"
        widget.destroy()

    def test_index_out_of_range_returns_current_path(self, ephemeral_window):
        """Defensive — out-of-range index returns the full path."""
        with in_window_frame(ephemeral_window):
            widget = self._make_with("/home/user")
        # Tokens = ["home", "user"], so index=99 is out of range.
        assert widget._accumulated_path(99) == "/home/user"
        widget.destroy()

    def test_empty_path_accumulates_to_empty(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        assert widget._accumulated_path(0) == ""
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Breadcrumb click dispatch
# ──────────────────────────────────────────────────────────────────────────────


class TestBreadcrumbClick:
    """Verify clicking a breadcrumb fires ``apply_path_handler``."""

    def test_click_fires_handler_with_accumulated_path(self, ephemeral_window):
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget.set_path("/home/user/docs")
        widget._on_breadcrumb_clicked(1)  # click "user"
        assert received == ["/home/user"]
        widget.destroy()

    def test_click_prefix_token_fires_prefix_only(self, ephemeral_window):
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget.set_path("file:///home/user")
        widget._on_breadcrumb_clicked(0)  # click "file://"
        assert received == ["file://"]
        widget.destroy()

    def test_click_last_breadcrumb_navigates_to_current_path(
        self, ephemeral_window,
    ):
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget.set_path("/a/b/c")
        widget._on_breadcrumb_clicked(2)  # click "c"
        assert received == ["/a/b/c"]
        widget.destroy()

    def test_multiple_clicks_dispatch_in_order(self, ephemeral_window):
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget.set_path("/a/b/c/d")
        widget._on_breadcrumb_clicked(0)
        widget._on_breadcrumb_clicked(2)
        widget._on_breadcrumb_clicked(1)
        assert received == ["/a", "/a/b/c", "/a/b"]
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# set_path / path property
# ──────────────────────────────────────────────────────────────────────────────


class TestSetPath:
    def test_set_path_updates_property(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/home/user")
        assert widget.path == "/home/user"
        widget.destroy()

    def test_set_path_multiple_updates_track_latest(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/a")
        widget.set_path("/b")
        widget.set_path("/c")
        assert widget.path == "/c"
        widget.destroy()

    def test_set_path_does_not_fire_apply_handler(self, ephemeral_window):
        """Caller drives the apply loop — ``set_path`` must not fire."""
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget.set_path("/home/user")
        assert received == []
        widget.destroy()

    def test_set_path_none_treated_as_empty(self, ephemeral_window):
        """``None`` / falsy input normalises to empty string."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path(None)  # type: ignore[arg-type]
        assert widget.path == ""
        widget.destroy()

    def test_set_path_rebuilds_breadcrumbs(self, ephemeral_window):
        """Subsequent ``set_path`` replaces the breadcrumb HStack contents."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/a/b")
        # Tokens should now reflect the new path.
        assert widget._tokenize(widget.path) == ["a", "b"]
        widget.set_path("/x/y/z")
        assert widget._tokenize(widget.path) == ["x", "y", "z"]
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Empty path
# ──────────────────────────────────────────────────────────────────────────────


class TestEmptyPath:
    def test_empty_path_renders_zero_breadcrumbs(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        # Default is empty — tokenize should yield an empty list.
        assert widget._tokenize(widget.path) == []
        widget.destroy()

    def test_empty_path_set_path_is_safe(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/a/b")
        widget.set_path("")
        assert widget.path == ""
        widget.destroy()

    def test_click_on_empty_path_does_not_crash(self, ephemeral_window):
        """Defensive — a click dispatched on an empty path just fires the
        current (empty) path without raising."""
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget._on_breadcrumb_clicked(0)
        assert received == [""]
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Destroy
# ──────────────────────────────────────────────────────────────────────────────


class TestDestroy:
    def test_destroy_clears_widget_refs(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.destroy()
        assert widget._scrolling_frame is None
        assert widget._zstack is None
        assert widget._edit_field is None
        assert widget._overlay_rect is None
        assert widget._breadcrumb_stack is None

    def test_destroy_clears_handler_refs(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=lambda p, cb: cb([]),
                begin_edit_handler=lambda: None,
            )
        widget.destroy()
        assert widget._apply_path_handler is None
        assert widget._autocomplete_handler is None
        assert widget._begin_edit_handler is None

    def test_destroy_is_idempotent(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.destroy()
        # Second call must not raise.
        widget.destroy()

    def test_destroy_after_set_path_does_not_crash(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/home/user/docs")
        widget.destroy()

    def test_destroy_without_entering_edit_mode_is_safe(self, ephemeral_window):
        """Edit mode was never entered — destroy path should still clean up."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        assert widget._mode == MODE_BREADCRUMB
        widget.destroy()
        assert widget._mode == MODE_BREADCRUMB


# ──────────────────────────────────────────────────────────────────────────────
# Inline edit mode (double-click → EDIT → Enter / Escape / focus-loss)
# ──────────────────────────────────────────────────────────────────────────────


class TestEditMode:
    """Exercise the BREADCRUMB → EDIT → BREADCRUMB state machine.

    Tests drive the transitions through the internal ``_enter_edit_mode``
    / ``_exit_edit_mode`` helpers rather than simulating mouse / keyboard
    events, so they run without a live :class:`Application`. Double-click
    routing is covered separately in :class:`TestOverlayDoubleClick`.
    """

    def test_initial_mode_is_breadcrumb(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        assert widget._mode == MODE_BREADCRUMB
        widget.destroy()

    def test_enter_edit_mode_flips_state_and_shows_field(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/home/user")
        widget._enter_edit_mode()
        assert widget._mode == MODE_EDIT
        assert widget._edit_field is not None
        assert widget._edit_field.visible is True
        assert widget._breadcrumb_frame is not None
        assert widget._breadcrumb_frame.visible is False
        assert widget._overlay_rect is not None
        assert widget._overlay_rect.visible is False
        widget.destroy()

    def test_enter_edit_mode_seeds_field_with_current_path(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("file:///tmp/project")
        widget._enter_edit_mode()
        assert widget._edit_field.model.get_value_as_string() == (
            "file:///tmp/project"
        )
        widget.destroy()

    def test_begin_edit_handler_called_on_enter(self, ephemeral_window):
        calls: List[int] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                begin_edit_handler=lambda: calls.append(1),
            )
        widget._enter_edit_mode()
        assert calls == [1]
        widget.destroy()

    def test_re_entrant_enter_edit_mode_is_noop(self, ephemeral_window):
        """A second enter while already in EDIT is a silent no-op."""
        calls: List[int] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                begin_edit_handler=lambda: calls.append(1),
            )
        widget._enter_edit_mode()
        widget._enter_edit_mode()
        # begin_edit_handler fires exactly once per BREADCRUMB→EDIT edge.
        assert calls == [1]
        widget.destroy()

    def test_exit_with_apply_fires_handler_with_typed_value(
        self, ephemeral_window,
    ):
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget.set_path("/home")
        widget._enter_edit_mode()
        # Simulate the user typing a new path.
        widget._edit_field.model.set_value("/tmp/new")
        widget._exit_edit_mode(apply=True)
        assert received == ["/tmp/new"]
        assert widget._mode == MODE_BREADCRUMB
        assert widget._edit_field.visible is False
        assert widget._breadcrumb_frame.visible is True
        assert widget._overlay_rect.visible is True
        widget.destroy()

    def test_exit_without_apply_drops_draft(self, ephemeral_window):
        """Escape / focus-loss → revert without dispatching."""
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/tmp/draft")
        widget._exit_edit_mode(apply=False)
        assert received == []
        assert widget._mode == MODE_BREADCRUMB
        widget.destroy()

    def test_exit_with_empty_typed_value_does_not_fire_handler(
        self, ephemeral_window,
    ):
        """Apply with an empty field is a no-op — no spurious navigate."""
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("")
        widget._exit_edit_mode(apply=True)
        assert received == []
        assert widget._mode == MODE_BREADCRUMB
        widget.destroy()

    def test_destroy_exits_active_edit_mode(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget._enter_edit_mode()
        assert widget._mode == MODE_EDIT
        widget.destroy()
        assert widget._mode == MODE_BREADCRUMB


class TestOverlayDoubleClick:
    """The transparent overlay rectangle routes double-clicks into edit mode."""

    def test_left_double_click_enters_edit_mode(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget._on_overlay_double_clicked(0, 0, 0, 0)  # button=0 → left
        assert widget._mode == MODE_EDIT
        widget.destroy()

    def test_right_double_click_ignored(self, ephemeral_window):
        """Button 1 (right) must not route into edit mode."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget._on_overlay_double_clicked(0, 0, 1, 0)
        assert widget._mode == MODE_BREADCRUMB
        widget.destroy()

    def test_middle_double_click_ignored(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget._on_overlay_double_clicked(0, 0, 2, 0)
        assert widget._mode == MODE_BREADCRUMB
        widget.destroy()

    def test_overlay_double_click_fn_is_wired(self, ephemeral_window):
        """``has_mouse_double_clicked_fn`` reads from the ovui C++ side
        which is only alive inside the active frame context — same
        constraint as :mod:`tests.test_file_card`'s
        ``test_click_callbacks_wired_on_rectangle``. The assertion and
        teardown therefore happen inside the frame.
        """
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
            try:
                assert widget._overlay_rect is not None
                assert widget._overlay_rect.has_mouse_double_clicked_fn() is True
            finally:
                widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Autocomplete (Step 18)
# ──────────────────────────────────────────────────────────────────────────────


# Raw key codes used to simulate key events against ``_on_popup_key_pressed``.
# Match the module-level constants in ``path_field.py`` — duplicating them
# here (rather than importing) keeps test intent visible at the call site
# ("press V with Ctrl") without having to jump to the implementation.
_GLFW_KEY_V = ord("V")
_GLFW_KEY_TAB = 258
_GLFW_KEY_DOWN = 264
_GLFW_KEY_UP = 265
_GLFW_KEY_ENTER = 257
_GLFW_MOD_CTRL = 1 << 1


class TestAutocompleteHandler:
    """Verify the popup wiring to the autocomplete handler (§15.6)."""

    def test_handler_fires_on_popup_value_change(self, ephemeral_window):
        captured_prefixes: List[str] = []

        def handler(prefix: str, cb) -> None:
            captured_prefixes.append(prefix)
            cb(["Documents/", "Textures/"])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=handler,
                prefix_separator="mock://",
            )
        widget._enter_edit_mode()
        # ovui dispatches ``value_changed`` on ``set_value``, which
        # drives our subscription back into ``_on_popup_value_changed``.
        widget._edit_field.model.set_value("mock://Home/")
        assert captured_prefixes == ["mock://Home/"]
        widget.destroy()

    def test_handler_receives_prefix_split_on_last_slash(
        self, ephemeral_window,
    ):
        """Input ``/home/use`` splits into prefix=``/home/`` + match=``use``."""
        captured: List[str] = []

        def handler(prefix: str, cb) -> None:
            captured.append(prefix)
            cb([])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/home/use")
        assert captured == ["/home/"]
        widget.destroy()

    def test_handler_results_populate_matches(self, ephemeral_window):
        def handler(prefix: str, cb) -> None:
            cb(["Documents/", "Textures/", "Scripts/"])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/home/")
        assert widget._autocomplete_matches == [
            "Documents/", "Textures/", "Scripts/",
        ]
        widget.destroy()

    def test_handler_results_filter_by_match_str_prefix(
        self, ephemeral_window,
    ):
        """Case-insensitive prefix match against the typed suffix."""
        def handler(prefix: str, cb) -> None:
            cb(["Documents/", "Downloads/", "Textures/"])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/home/do")
        # "do" matches "Documents/" and "Downloads/" case-insensitively;
        # "Textures/" drops out.
        assert widget._autocomplete_matches == [
            "Documents/", "Downloads/",
        ]
        widget.destroy()

    def test_handler_results_truncated_to_max_visible(
        self, ephemeral_window,
    ):
        """Dropdown caps at :data:`_AUTOCOMPLETE_MAX_VISIBLE` (10) entries."""
        def handler(prefix: str, cb) -> None:
            cb([f"folder{i}/" for i in range(25)])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/home/")
        assert len(widget._autocomplete_matches) == 10
        widget.destroy()

    def test_empty_results_hide_dropdown(self, ephemeral_window):
        def handler(prefix: str, cb) -> None:
            cb([])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/home/nothingmatches")
        assert widget._autocomplete_matches == []
        assert widget._autocomplete_container.visible is False
        widget.destroy()

    def test_non_matching_suffix_hides_dropdown(self, ephemeral_window):
        """Handler returns folders but none prefix-match — dropdown empty."""
        def handler(prefix: str, cb) -> None:
            cb(["Documents/", "Textures/"])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/home/xyz")
        assert widget._autocomplete_matches == []
        assert widget._autocomplete_container.visible is False
        widget.destroy()

    def test_no_handler_is_safe_on_value_change(self, ephemeral_window):
        """Without an autocomplete_handler, typing doesn't crash."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/home/")
        # No handler → short-circuit; must not raise.
        assert widget._autocomplete_matches == []
        widget.destroy()


class TestPasteShortCircuit:
    """§15.7 OM-75838: Ctrl+V skips the autocomplete network roundtrip."""

    def test_ctrl_v_press_sets_is_paste_flag(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget._enter_edit_mode()
        assert widget._is_paste is False
        widget._on_edit_key_pressed(
            _GLFW_KEY_V, _GLFW_MOD_CTRL, pressed=True,
        )
        assert widget._is_paste is True
        widget.destroy()

    def test_v_without_ctrl_does_not_set_flag(self, ephemeral_window):
        """Plain ``V`` is regular typing — no paste latch."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget._enter_edit_mode()
        widget._on_edit_key_pressed(_GLFW_KEY_V, 0, pressed=True)
        assert widget._is_paste is False
        widget.destroy()

    def test_paste_skips_autocomplete_handler(self, ephemeral_window):
        calls: List[str] = []

        def handler(prefix: str, cb) -> None:
            calls.append(prefix)
            cb(["Documents/"])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        # Simulate the paste sequence: key-down latches the flag,
        # then ovui's clipboard paste fires a value change.
        widget._on_edit_key_pressed(
            _GLFW_KEY_V, _GLFW_MOD_CTRL, pressed=True,
        )
        widget._edit_field.model.set_value("file:///etc/passwd.bak")
        # Handler must NOT have been called — the paste short-circuits.
        assert calls == []
        # Flag consumed on the value-change that it was meant for.
        assert widget._is_paste is False
        widget.destroy()

    def test_paste_hides_dropdown(self, ephemeral_window):
        """A paste clears any in-progress autocomplete dropdown."""
        def handler(prefix: str, cb) -> None:
            cb(["Documents/", "Textures/"])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        # Populate the dropdown via a normal typing cycle.
        widget._edit_field.model.set_value("/home/")
        assert widget._autocomplete_container.visible is True
        # Now paste — dropdown should collapse.
        widget._on_edit_key_pressed(
            _GLFW_KEY_V, _GLFW_MOD_CTRL, pressed=True,
        )
        widget._edit_field.model.set_value("file:///tmp")
        assert widget._autocomplete_container.visible is False
        widget.destroy()

    def test_subsequent_typing_re_enables_autocomplete(
        self, ephemeral_window,
    ):
        """Paste consumes the flag once; next typing event runs normally."""
        calls: List[str] = []

        def handler(prefix: str, cb) -> None:
            calls.append(prefix)
            cb([])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._on_edit_key_pressed(
            _GLFW_KEY_V, _GLFW_MOD_CTRL, pressed=True,
        )
        widget._edit_field.model.set_value("/paste/")
        # Paste dispatch absorbed — no handler call.
        assert calls == []
        # Typing another character → flag already cleared, handler fires.
        widget._edit_field.model.set_value("/paste/a")
        assert calls == ["/paste/"]
        widget.destroy()


class TestAutocompleteKeyboardNavigation:
    """Down/Up cycle the selection; Tab / Enter commits."""

    def _make_with_matches(self, ephemeral_window) -> PathField:
        def handler(prefix: str, cb) -> None:
            cb(["Documents/", "Textures/", "Scripts/"])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/home/")
        return widget

    def test_down_selects_first_entry_from_no_selection(
        self, ephemeral_window,
    ):
        widget = self._make_with_matches(ephemeral_window)
        assert widget._autocomplete_selected == -1
        widget._on_edit_key_pressed(_GLFW_KEY_DOWN, 0, pressed=False)
        assert widget._autocomplete_selected == 0
        widget.destroy()

    def test_up_selects_last_entry_from_no_selection(self, ephemeral_window):
        widget = self._make_with_matches(ephemeral_window)
        widget._on_edit_key_pressed(_GLFW_KEY_UP, 0, pressed=False)
        assert widget._autocomplete_selected == 2  # len - 1
        widget.destroy()

    def test_down_wraps_at_end(self, ephemeral_window):
        widget = self._make_with_matches(ephemeral_window)
        widget._autocomplete_selected = 2  # already on last
        widget._on_edit_key_pressed(_GLFW_KEY_DOWN, 0, pressed=False)
        assert widget._autocomplete_selected == 0
        widget.destroy()

    def test_up_wraps_at_start(self, ephemeral_window):
        widget = self._make_with_matches(ephemeral_window)
        widget._autocomplete_selected = 0
        widget._on_edit_key_pressed(_GLFW_KEY_UP, 0, pressed=False)
        assert widget._autocomplete_selected == 2
        widget.destroy()

    def test_down_on_empty_is_noop(self, ephemeral_window):
        """Down with no matches doesn't raise and leaves selection at -1."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget._enter_edit_mode()
        widget._on_edit_key_pressed(_GLFW_KEY_DOWN, 0, pressed=False)
        assert widget._autocomplete_selected == -1
        widget.destroy()

    def test_tab_commits_selected_entry_into_field(self, ephemeral_window):
        widget = self._make_with_matches(ephemeral_window)
        widget._autocomplete_selected = 1  # "Textures/"
        widget._on_edit_key_pressed(_GLFW_KEY_TAB, 0, pressed=False)
        assert widget._edit_field.model.get_value_as_string() == (
            "/home/Textures/"
        )
        widget.destroy()

    def test_tab_without_selection_is_noop(self, ephemeral_window):
        widget = self._make_with_matches(ephemeral_window)
        before = widget._edit_field.model.get_value_as_string()
        # selection still -1 — Tab should leave the field untouched.
        widget._on_edit_key_pressed(_GLFW_KEY_TAB, 0, pressed=False)
        assert widget._edit_field.model.get_value_as_string() == before
        # And edit mode remains active (Tab did NOT trigger an exit).
        assert widget._mode == MODE_EDIT
        widget.destroy()

    def test_enter_with_selection_commits_into_field(self, ephemeral_window):
        received: List[str] = []
        def handler(prefix: str, cb) -> None:
            cb(["Documents/", "Textures/"])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=received.append,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/home/")
        widget._autocomplete_selected = 0  # "Documents/"
        widget._on_edit_key_pressed(_GLFW_KEY_ENTER, 0, pressed=False)
        # First Enter commits the selection without applying.
        assert received == []
        assert widget._edit_field.model.get_value_as_string() == (
            "/home/Documents/"
        )
        assert widget._mode == MODE_EDIT
        widget.destroy()

    def test_enter_without_selection_applies_and_dismisses(
        self, ephemeral_window,
    ):
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/custom/path")
        widget._on_edit_key_pressed(_GLFW_KEY_ENTER, 0, pressed=False)
        assert received == ["/custom/path"]
        assert widget._mode == MODE_BREADCRUMB
        widget.destroy()

    def test_commit_clears_dropdown(self, ephemeral_window):
        widget = self._make_with_matches(ephemeral_window)
        widget._autocomplete_selected = 0
        widget._commit_autocomplete_selection()
        assert widget._autocomplete_matches == []
        assert widget._autocomplete_container.visible is False
        widget.destroy()


class TestAutocompleteSplit:
    """Verify the static ``_split_for_autocomplete`` contract."""

    def test_split_on_last_slash(self):
        assert PathField._split_for_autocomplete("/home/us") == (
            "/home/", "us",
        )

    def test_no_slash_returns_empty_prefix(self):
        assert PathField._split_for_autocomplete("home") == ("", "home")

    def test_trailing_slash_is_a_committed_prefix(self):
        assert PathField._split_for_autocomplete("/home/") == (
            "/home/", "",
        )

    def test_empty_string_is_empty_tuple(self):
        assert PathField._split_for_autocomplete("") == ("", "")

    def test_url_scheme_preserved_in_prefix(self):
        assert PathField._split_for_autocomplete("file:///etc") == (
            "file:///", "etc",
        )


class TestAutocompleteLifecycle:
    """Destroy and edit-mode exit should clean up autocomplete state."""

    def test_destroy_clears_autocomplete_state(self, ephemeral_window):
        def handler(prefix: str, cb) -> None:
            cb(["A/", "B/"])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/root/")
        widget._autocomplete_selected = 1
        widget.destroy()
        assert widget._autocomplete_container is None
        assert widget._autocomplete_matches == []
        assert widget._autocomplete_selected == -1
        assert widget._autocomplete_match_str == ""
        assert widget._edit_value_changed_sub is None
        assert widget._is_paste is False

    def test_exit_edit_mode_clears_autocomplete(self, ephemeral_window):
        def handler(prefix: str, cb) -> None:
            cb(["A/", "B/"])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/root/")
        assert widget._autocomplete_matches != []
        widget._exit_edit_mode(apply=False)
        assert widget._autocomplete_matches == []
        # The popup teardown also drops the container ref.
        assert widget._autocomplete_container is None
        widget.destroy()

    def test_reentering_edit_mode_rebuilds_autocomplete_container(
        self, ephemeral_window,
    ):
        """After exit, a fresh enter recreates the dropdown container."""
        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=lambda p, cb: cb([]),
            )
        widget._enter_edit_mode()
        widget._exit_edit_mode(apply=False)
        assert widget._autocomplete_container is None
        widget._enter_edit_mode()
        assert widget._autocomplete_container is not None
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Scroll direction after navigation (Bug 3)
# ──────────────────────────────────────────────────────────────────────────────


class TestScrollAfterNavigation:
    """Bug 3: ``_rebuild_breadcrumbs`` previously pinned
    ``scroll_x = scroll_x_max`` on every rebuild, which hid ancestor
    segments after navigating to a parent folder. The fix keeps the
    tail-pin when the user navigates deeper or to a sibling/unrelated
    path, but resets ``scroll_x = 0`` when the new path is a prefix of
    the previous one (parent navigation), so ancestor breadcrumbs
    remain visible and clickable.
    """

    def test_previous_tokens_empty_before_any_set_path(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        assert widget._previous_tokens == []
        widget.destroy()

    def test_previous_tokens_tracks_latest_tokenization(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/a/b/c")
        assert widget._previous_tokens == ["a", "b", "c"]
        widget.set_path("/x")
        assert widget._previous_tokens == ["x"]
        widget.destroy()

    def test_first_set_path_pins_scroll_to_tail(self, ephemeral_window):
        """Initial build (empty previous tokens) pins to tail so a
        freshly-opened deep path lands showing the current folder."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/a/b/c/d/e")
        frame = widget._scrolling_frame
        assert frame is not None
        assert frame.scroll_x == frame.scroll_x_max
        widget.destroy()

    def test_deeper_navigation_pins_scroll_to_tail(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/a")
        widget.set_path("/a/b/c")
        frame = widget._scrolling_frame
        assert frame is not None
        assert frame.scroll_x == frame.scroll_x_max
        widget.destroy()

    def test_parent_navigation_resets_scroll_to_zero(self, ephemeral_window):
        """Bug 3 core case: shortening the path to an ancestor must
        not auto-scroll to the right — ancestor segments must remain
        visible."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/a/b/c/d")
        widget.set_path("/a/b/c")
        frame = widget._scrolling_frame
        assert frame is not None
        assert frame.scroll_x == 0
        widget.destroy()

    def test_grandparent_navigation_resets_scroll_to_zero(self, ephemeral_window):
        """Going up multiple levels at once is still a parent nav."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/a/b/c/d/e")
        widget.set_path("/a/b")
        frame = widget._scrolling_frame
        assert frame is not None
        assert frame.scroll_x == 0
        widget.destroy()

    def test_sibling_navigation_pins_scroll_to_tail(self, ephemeral_window):
        """Same depth, different leaf — not a parent nav. Tail pin so
        the user sees the new current folder."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/a/b/c")
        widget.set_path("/a/b/d")
        frame = widget._scrolling_frame
        assert frame is not None
        assert frame.scroll_x == frame.scroll_x_max
        widget.destroy()

    def test_unrelated_shorter_path_pins_scroll_to_tail(self, ephemeral_window):
        """Shorter but not a prefix of the previous path — e.g.
        jumping from ``/a/b/c/d`` to ``/x``. Treated as fresh nav,
        tail pinned."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/a/b/c/d")
        widget.set_path("/x")
        frame = widget._scrolling_frame
        assert frame is not None
        assert frame.scroll_x == frame.scroll_x_max
        widget.destroy()

    def test_same_path_refresh_pins_scroll_to_tail(self, ephemeral_window):
        """Setting the same path twice is a refresh, not a parent nav —
        tail pin preserved."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/a/b/c")
        widget.set_path("/a/b/c")
        frame = widget._scrolling_frame
        assert frame is not None
        assert frame.scroll_x == frame.scroll_x_max
        widget.destroy()

    def test_parent_then_deeper_pins_scroll_to_tail(self, ephemeral_window):
        """Sequence: deep → parent → deeper again. The final step is
        a deeper nav relative to the parent, so the tail pin returns."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/a/b/c/d")
        widget.set_path("/a/b")
        widget.set_path("/a/b/e")
        frame = widget._scrolling_frame
        assert frame is not None
        assert frame.scroll_x == frame.scroll_x_max
        widget.destroy()

    def test_ancestor_breadcrumbs_clickable_after_parent_nav(
        self, ephemeral_window,
    ):
        """After a parent nav, clicking an ancestor breadcrumb still
        fires the correct accumulated URL — proxy for the visual
        clickability guarantee the scroll-reset gives the user."""
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget.set_path("file:///tmp/ovgear_bug_repro/level1/level2/level3")
        widget.set_path("file:///tmp/ovgear_bug_repro/level1/level2")
        # Tokens: ["file://", "tmp", "ovgear_bug_repro", "level1", "level2"]
        widget._on_breadcrumb_clicked(0)  # "file://"
        widget._on_breadcrumb_clicked(1)  # "tmp"
        widget._on_breadcrumb_clicked(2)  # "ovgear_bug_repro"
        assert received == [
            "file://",
            "file:///tmp",
            "file:///tmp/ovgear_bug_repro",
        ]
        widget.destroy()

    def test_empty_path_after_non_empty_still_tracks_tokens(
        self, ephemeral_window,
    ):
        """Clearing the path updates ``_previous_tokens`` so a later
        set-path lands with a clean slate (treated as initial build)."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/a/b")
        widget.set_path("")
        assert widget._previous_tokens == []
        widget.destroy()

    def test_destroy_clears_previous_tokens(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/a/b")
        assert widget._previous_tokens == ["a", "b"]
        widget.destroy()
        assert widget._previous_tokens == []


# ──────────────────────────────────────────────────────────────────────────────
# Deferred rebuild via ui.Frame (Bug 3 root cause)
# ──────────────────────────────────────────────────────────────────────────────


class TestDeferredRebuild:
    """Bug 3 fix: :meth:`PathField.set_path` defers the breadcrumb
    rebuild through :meth:`ui.Frame.rebuild` so clicking a breadcrumb
    button (whose ``clicked_fn`` runs inside ovui's draw dispatch) does
    not trigger an in-draw ``HStack.clear`` + ``with HStack:`` mutation
    — that combination emits ``Container::clear was called during an
    event or draw`` and leaves the rebuilt buttons at size ``(0, 0)``.
    These tests pin the architectural contract: :attr:`_breadcrumb_frame`
    is a :class:`ui.Frame` with a ``build_fn``, and :meth:`set_path`
    invokes :meth:`ui.Frame.rebuild` rather than calling the rebuild
    function directly.
    """

    def test_breadcrumb_container_is_a_frame(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        assert widget._breadcrumb_frame is not None
        assert isinstance(widget._breadcrumb_frame, ui.Frame)
        widget.destroy()

    def test_set_path_triggers_frame_rebuild(self, ephemeral_window):
        """:meth:`set_path` must route through :meth:`ui.Frame.rebuild`
        rather than calling :meth:`_rebuild_breadcrumbs` directly. The
        Frame-mediated rebuild is what makes clicks during draw safe.

        ``ui.Frame.rebuild`` is a C-bound read-only method, so the test
        swaps the whole :attr:`_breadcrumb_frame` for a stand-in shim
        that records the call — same end observation, different hook.
        """
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)

        calls: List[int] = []

        class _FrameStub:
            def rebuild(self_stub) -> None:
                calls.append(1)

        widget._breadcrumb_frame = _FrameStub()  # type: ignore[assignment]
        widget.set_path("/a/b/c")
        assert calls == [1]
        widget.destroy()

    def test_click_during_rebuild_does_not_crash(self, ephemeral_window):
        """Core Bug 3 scenario: a breadcrumb click fires
        ``apply_path_handler`` which calls ``set_path`` — which in turn
        must not re-enter an in-progress ``_rebuild_breadcrumbs``
        synchronously. The Frame-mediated defer guarantees this."""
        received: List[str] = []

        def handler(url: str) -> None:
            received.append(url)
            # Simulate the browser bar round-trip that calls set_path
            # back into the widget — in the real app this lands from
            # the button's clicked_fn callback chain.
            widget.set_path(url)

        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=handler)
        widget.set_path("/a/b/c/d")
        # Simulating a click on the "b" breadcrumb (index 1). Previously
        # this path triggered an in-place rebuild that collapsed the
        # HStack. With the Frame-mediated defer, the click handler can
        # re-enter set_path without destroying the rebuild in progress.
        widget._on_breadcrumb_clicked(1)
        assert received == ["/a/b"]
        assert widget.path == "/a/b"
        assert widget._previous_tokens == ["a", "b"]
        widget.destroy()

    def test_set_path_updates_state_synchronously(self, ephemeral_window):
        """The rebuild is deferred but the path / token / went-up state
        must be updated before :meth:`set_path` returns — callers that
        read those attributes immediately after (tests, the click
        handler) rely on the synchronous update."""
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        widget.set_path("/deep/path/here")
        # Read state right after set_path — must already be settled.
        assert widget.path == "/deep/path/here"
        assert widget._previous_tokens == ["deep", "path", "here"]
        assert widget._went_up is False
        widget.set_path("/deep/path")
        assert widget.path == "/deep/path"
        assert widget._previous_tokens == ["deep", "path"]
        assert widget._went_up is True
        widget.destroy()

    def test_destroy_clears_breadcrumb_frame(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=_noop)
        assert widget._breadcrumb_frame is not None
        widget.destroy()
        assert widget._breadcrumb_frame is None
        assert widget._went_up is False


# ──────────────────────────────────────────────────────────────────────────────
# Address bar bug fixes: Enter navigates, dropdown is styled + clickable
# ──────────────────────────────────────────────────────────────────────────────


_GLFW_KEY_ESCAPE = 256
_GLFW_KEY_KEYPAD_ENTER = 335


class TestEnterNavigation:
    """Bug A: Pressing Enter in the typed field must apply the draft,
    not revert it.

    The prior implementation handled Enter only on key-release; ovui
    fires ``end_edit`` synchronously for Enter *between* the press and
    release events. When ``end_edit`` routed to :meth:`_exit_edit_mode`
    with ``apply=False``, the draft was dropped and the release-side
    Enter handler found the widget already back in BREADCRUMB mode —
    short-circuiting without applying. The fix moves the Enter handler
    to act on both press and release, and makes :meth:`_on_edit_end_edit`
    apply rather than revert so focus-loss and the ovui Enter commit
    both land on the same path.
    """

    def test_end_edit_applies_typed_value(self, ephemeral_window):
        """ovui's Enter → end_edit path must apply, not revert."""
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget.set_path("/home")
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/tmp/typed")
        # Simulate ovui firing end_edit (e.g. Enter or focus-loss).
        widget._on_edit_end_edit(widget._edit_field.model)
        assert received == ["/tmp/typed"]
        assert widget._mode == MODE_BREADCRUMB
        widget.destroy()

    def test_enter_press_preempts_end_edit_revert(self, ephemeral_window):
        """Enter handled on press flips mode to BREADCRUMB so the ovui
        end_edit that follows short-circuits instead of reverting."""
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/from/press")
        widget._on_edit_key_pressed(_GLFW_KEY_ENTER, 0, pressed=True)
        assert received == ["/from/press"]
        assert widget._mode == MODE_BREADCRUMB
        # A subsequent end_edit fires (simulating ovui's post-commit
        # dispatch) — must be a silent no-op, not a second apply.
        widget._on_edit_end_edit(widget._edit_field.model)
        assert received == ["/from/press"]
        widget.destroy()

    def test_enter_release_still_applies(self, ephemeral_window):
        """Release-side Enter is the backstop path for unit-test
        dispatch patterns that never fire a press event."""
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/from/release")
        widget._on_edit_key_pressed(_GLFW_KEY_ENTER, 0, pressed=False)
        assert received == ["/from/release"]
        assert widget._mode == MODE_BREADCRUMB
        widget.destroy()

    def test_keypad_enter_also_applies(self, ephemeral_window):
        """Numpad Enter (GLFW key 335) shares the Enter codepath."""
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/numpad")
        widget._on_edit_key_pressed(_GLFW_KEY_KEYPAD_ENTER, 0, pressed=True)
        assert received == ["/numpad"]
        widget.destroy()

    def test_escape_press_preempts_end_edit_apply(self, ephemeral_window):
        """Escape on press reverts; the end_edit that ovui fires afterwards
        must short-circuit (no spurious apply of the dropped draft)."""
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/escape/draft")
        widget._on_edit_key_pressed(_GLFW_KEY_ESCAPE, 0, pressed=True)
        assert received == []
        assert widget._mode == MODE_BREADCRUMB
        # ovui dispatches end_edit afterwards — still no apply.
        widget._on_edit_end_edit(widget._edit_field.model)
        assert received == []
        widget.destroy()

    def test_escape_release_also_reverts(self, ephemeral_window):
        """Escape on release is a secondary path for symmetry with the
        existing test fixtures that fire ``pressed=False``."""
        received: List[str] = []
        with in_window_frame(ephemeral_window):
            widget = PathField(apply_path_handler=received.append)
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/esc2")
        widget._on_edit_key_pressed(_GLFW_KEY_ESCAPE, 0, pressed=False)
        assert received == []
        assert widget._mode == MODE_BREADCRUMB
        widget.destroy()


class TestAutocompleteRowClickNavigation:
    """Bug C: clicking a dropdown suggestion applies the extended path
    and navigates.

    The row widgets are :class:`ui.Button` with ``clicked_fn`` bound to
    :meth:`_on_autocomplete_row_clicked` — the click commits the selection
    into the field (so the extended path is ``<prefix><selected>``) then
    calls :meth:`_exit_edit_mode(apply=True)` to dispatch the apply
    handler.
    """

    def test_row_click_commits_and_applies(self, ephemeral_window):
        received: List[str] = []

        def handler(prefix: str, cb) -> None:
            cb(["level1/", "level2/"])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=received.append,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/root/")
        # Click the first row — "level1/".
        widget._on_autocomplete_row_clicked(0)
        assert received == ["/root/level1/"]
        assert widget._mode == MODE_BREADCRUMB
        widget.destroy()

    def test_row_click_with_bad_index_is_noop(self, ephemeral_window):
        received: List[str] = []

        def handler(prefix: str, cb) -> None:
            cb(["A/"])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=received.append,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/r/")
        widget._on_autocomplete_row_clicked(5)
        widget._on_autocomplete_row_clicked(-1)
        assert received == []
        assert widget._mode == MODE_EDIT
        widget.destroy()

    def test_row_click_replaces_match_str_tail(self, ephemeral_window):
        """Clicking picks the row — the typed match_str after the last
        slash gets replaced with the selected entry, not appended."""
        received: List[str] = []

        def handler(prefix: str, cb) -> None:
            cb(["Documents/", "Downloads/"])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=received.append,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/home/do")
        widget._on_autocomplete_row_clicked(0)
        assert received == ["/home/Documents/"]
        widget.destroy()


class TestAutocompleteCommitSuppression:
    """Bug-fix supporting invariant: committing a suggestion via Tab
    latches :attr:`_suppress_end_edit` so the ovui end_edit that follows
    does not reinterpret the committed value as an apply.
    """

    def test_commit_sets_suppress_flag(self, ephemeral_window):
        def handler(prefix: str, cb) -> None:
            cb(["Documents/"])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=_noop,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/home/")
        widget._autocomplete_selected = 0
        widget._commit_autocomplete_selection()
        assert widget._suppress_end_edit is True
        widget.destroy()

    def test_end_edit_consumes_suppress_flag(self, ephemeral_window):
        """After a Tab commit, end_edit must skip apply and leave the
        field visible so the user can continue drilling."""
        received: List[str] = []

        def handler(prefix: str, cb) -> None:
            cb(["Documents/"])

        with in_window_frame(ephemeral_window):
            widget = PathField(
                apply_path_handler=received.append,
                autocomplete_handler=handler,
            )
        widget._enter_edit_mode()
        widget._edit_field.model.set_value("/home/")
        widget._autocomplete_selected = 0
        widget._on_edit_key_pressed(258, 0, pressed=True)  # Tab press
        # end_edit fires (Tab / value-changed dispatch) — must be
        # suppressed; no apply, mode stays EDIT.
        widget._on_edit_end_edit(widget._edit_field.model)
        assert received == []
        assert widget._mode == MODE_EDIT
        # Flag is consumed — a second end_edit now applies as usual.
        assert widget._suppress_end_edit is False
        widget.destroy()


class TestAutocompleteDropdownStyling:
    """Bug B structural invariants for the autocomplete dropdown wiring."""

    def test_popup_flags_do_not_include_no_background(self):
        """The previous flags carried ``NO_BACKGROUND`` which stripped
        the window fill — the dropdown then rendered as ghost labels
        over the content area. The fix removes that flag so the window
        has an opaque ImGui backdrop AND stacks the theme-coloured
        Rectangle on top for branded chrome."""
        from ovui_widgets.content.widget.path_field import (
            _AUTOCOMPLETE_POPUP_FLAGS,
        )

        assert (_AUTOCOMPLETE_POPUP_FLAGS & ui.WINDOW_FLAGS_NO_BACKGROUND) == 0

    def test_autocomplete_styles_defined_in_theme(self):
        """``Content.PathBar.Autocomplete`` + ``.Item`` must exist in
        the content-browser style dict; otherwise the rectangle backdrop
        and clickable rows render with undefined colours."""
        from ovui_widgets.content.style import CONTENT_STYLES

        assert "Content.PathBar.Autocomplete" in CONTENT_STYLES
        assert "Content.PathBar.Autocomplete.Item" in CONTENT_STYLES
        assert (
            "Content.PathBar.Autocomplete.Item:hovered" in CONTENT_STYLES
        )
        assert (
            "Content.PathBar.Autocomplete.Item::selected" in CONTENT_STYLES
        )

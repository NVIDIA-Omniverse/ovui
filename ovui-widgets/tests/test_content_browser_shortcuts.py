# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 58 keyboard-shortcut dispatch — ContentBrowserWindow.

the content browser implementation step 58 adds five content-browser-scoped shortcuts to
:meth:`ContentBrowserWindow._on_key_pressed`:

* Alt+Up       — up one level (:meth:`go_up`)
* F5           — refresh detail pane (:meth:`refresh`)
* Ctrl+F       — focus search field (:meth:`focus_search`)
* Ctrl+Home    — navigate to ~ (:meth:`navigate_home`)
* Escape       — dismiss context menu / clear selection
                 (:meth:`clear_selection_or_dismiss`)

The existing shortcuts (Ctrl+C / X / V / D, Del, F2, Alt+Left / Right)
continue to dispatch directly from
:meth:`ovui_widgets.app.application.Application._on_key_pressed` via the matching
proxy methods on :class:`ContentBrowserWindow` — those are covered by
:file:`tests/test_keyboard_shortcuts.py` and
:file:`tests/test_content_browser_window.py` and re-verified here only
through the surface test.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import omni.ui as ui
import pytest

from ovui_widgets.app.testing.mock_backend import MockBackend
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.content import ContentBrowserWindow
from ovui_widgets.content.window.content_browser_window import (
    _KEY_ARROW_UP,
    _KEY_ESCAPE,
    _KEY_F5,
    _KEY_HOME,
    _MOD_ALT,
    _MOD_CTRL,
    _MOD_SHIFT,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Drop any leaked :class:`Application` / :class:`SelectionBus` singleton.

    Neighbour test modules (``test_keyboard_shortcuts.py`` in
    particular) stash a MagicMock into :attr:`Application._instance`
    and rely on a module-level ``teardown_function`` that does not
    trigger for class-based tests. Without this fixture those leaks
    bleed into the :class:`ContentBrowserWindow` constructor here and
    :meth:`_resolve_bookmarks` walks into the stale settings mock.
    """
    from ovui_widgets.app.application import Application
    Application._instance = None
    SelectionBus._instance = None
    yield
    Application._instance = None
    SelectionBus._instance = None


def _can_create_window() -> bool:
    try:
        w = ui.Window("__probe__", width=10, height=10)
        w.destroy()
        return True
    except Exception:
        return False


_WINDOW_AVAILABLE = _can_create_window()
_skip_no_window = pytest.mark.skipif(
    not _WINDOW_AVAILABLE,
    reason="ui.Window creation not available without ui.init()",
)


def _make_built_window() -> ContentBrowserWindow:
    """Construct a :class:`ContentBrowserWindow` with its widget built.

    Returns a window whose :meth:`_build_ui` already fired so the
    shortcut-dispatch tests can reach into the live
    :class:`FileBrowserWidget`.
    """
    w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
    with w._window.frame:
        w._build_ui()
    return w


# ──────────────────────────────────────────────────────────────────────────────
# Surface
# ──────────────────────────────────────────────────────────────────────────────


class TestSurface:
    def test_on_key_pressed_exists(self):
        assert hasattr(ContentBrowserWindow, "_on_key_pressed")

    def test_go_up_exists(self):
        assert hasattr(ContentBrowserWindow, "go_up")

    def test_refresh_exists(self):
        assert hasattr(ContentBrowserWindow, "refresh")

    def test_focus_search_exists(self):
        assert hasattr(ContentBrowserWindow, "focus_search")

    def test_navigate_home_exists(self):
        assert hasattr(ContentBrowserWindow, "navigate_home")

    def test_clear_selection_or_dismiss_exists(self):
        assert hasattr(ContentBrowserWindow, "clear_selection_or_dismiss")

    def test_proxy_methods_reuse_step_20_37_surfaces(self):
        # Sanity: the existing shortcuts land on the same proxy surface
        # :class:`ovui_widgets.app.application.Application` has been dispatching
        # through since Steps 20 / 36 / 37. Breaking any of these would
        # surface elsewhere; this test just verifies the symbols are
        # still on the class so a pre-Step-58 regression is caught here.
        for name in (
            "go_back",
            "go_forward",
            "begin_rename_selected",
            "delete_selected",
            "copy_selected",
            "cut_selected",
            "paste_into_current",
            "duplicate_selected",
        ):
            assert hasattr(ContentBrowserWindow, name), name


# ──────────────────────────────────────────────────────────────────────────────
# go_up — Alt+Up
# ──────────────────────────────────────────────────────────────────────────────


@_skip_no_window
class TestGoUp:
    def test_go_up_navigates_to_parent(self):
        w = _make_built_window()
        w.navigate_to("mock://Home/Documents/Projects")
        w.go_up()
        assert (
            w._widget.get_detail_model().root_url
            == "mock://Home/Documents"
        )
        w.destroy()

    def test_go_up_at_root_is_noop(self):
        # MockBackend's parent_url of a top-level root returns the same
        # URL (or None); in either case the call must not raise.
        w = _make_built_window()
        original = w._widget.get_detail_model().root_url
        w.go_up()
        w.go_up()  # repeat — still must not raise
        # The root may or may not change depending on backend
        # conventions; we only assert no exception.
        w.destroy()

    def test_go_up_before_build_is_noop(self):
        w = ContentBrowserWindow(
            backend=MockBackend(), start_url="mock://Home",
        )
        w.go_up()  # must not raise
        w.destroy()

    def test_go_up_after_destroy_is_noop(self):
        w = _make_built_window()
        w.destroy()
        w.go_up()  # must not raise


# ──────────────────────────────────────────────────────────────────────────────
# refresh — F5
# ──────────────────────────────────────────────────────────────────────────────


@_skip_no_window
class TestRefresh:
    def test_refresh_calls_detail_model_refresh_all(self):
        w = _make_built_window()
        model = w._widget._detail_model
        model.refresh_all = MagicMock()
        w.refresh()
        model.refresh_all.assert_called_once()
        w.destroy()

    def test_refresh_before_build_is_noop(self):
        w = ContentBrowserWindow(
            backend=MockBackend(), start_url="mock://Home",
        )
        w.refresh()  # must not raise
        w.destroy()

    def test_refresh_after_destroy_is_noop(self):
        w = _make_built_window()
        w.destroy()
        w.refresh()  # must not raise


# ──────────────────────────────────────────────────────────────────────────────
# focus_search — Ctrl+F
# ──────────────────────────────────────────────────────────────────────────────


@_skip_no_window
class TestFocusSearch:
    def test_focus_search_calls_field_focus_keyboard(self):
        # :class:`omni.ui._ui.StringField` disallows attribute override,
        # so instead of patching :meth:`focus_keyboard` in place we swap
        # the entire ``_field`` with a stub that records the call. The
        # dispatcher only looks for a ``focus_keyboard`` attribute via
        # :func:`getattr`, so a plain Python object works.
        w = _make_built_window()
        search = w._widget._search_field
        if search is None or search._field is None:
            pytest.skip("search field not built in this ovui variant")
        called = {"count": 0}

        class _StubField:
            def focus_keyboard(self_inner):
                called["count"] += 1

        search._field = _StubField()
        w.focus_search()
        assert called["count"] == 1
        w.destroy()

    def test_focus_search_without_field_is_noop(self):
        w = _make_built_window()
        w._widget._search_field = None
        w.focus_search()  # must not raise
        w.destroy()

    def test_focus_search_before_build_is_noop(self):
        w = ContentBrowserWindow(
            backend=MockBackend(), start_url="mock://Home",
        )
        w.focus_search()  # must not raise
        w.destroy()

    def test_focus_search_after_destroy_is_noop(self):
        w = _make_built_window()
        w.destroy()
        w.focus_search()  # must not raise

    def test_focus_search_without_focus_keyboard_api_is_noop(self):
        # A future ovui build without ``focus_keyboard`` on
        # ``ui.StringField`` must not crash the dispatcher.
        w = _make_built_window()
        search = w._widget._search_field
        if search is None or search._field is None:
            pytest.skip("search field not built in this ovui variant")
        # Point the field at an object lacking focus_keyboard.
        search._field = object()
        w.focus_search()  # must not raise
        w.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# navigate_home — Ctrl+Home
# ──────────────────────────────────────────────────────────────────────────────


@_skip_no_window
class TestNavigateHome:
    def test_navigate_home_routes_through_widget(self):
        w = _make_built_window()
        w.navigate_to("mock://Home/Documents")
        w.navigate_home()
        # MockBackend normalizes ``file://~`` to ``mock://Home`` — the
        # exact URL is backend-specific; we assert the detail model
        # re-rooted away from the prior location.
        assert (
            w._widget.get_detail_model().root_url
            != "mock://Home/Documents"
        )
        w.destroy()

    def test_navigate_home_before_build_is_noop(self):
        w = ContentBrowserWindow(
            backend=MockBackend(), start_url="mock://Home",
        )
        w.navigate_home()  # must not raise
        w.destroy()

    def test_navigate_home_after_destroy_is_noop(self):
        w = _make_built_window()
        w.destroy()
        w.navigate_home()  # must not raise


# ──────────────────────────────────────────────────────────────────────────────
# clear_selection_or_dismiss — Escape
# ──────────────────────────────────────────────────────────────────────────────


@_skip_no_window
class TestClearSelectionOrDismiss:
    def test_dismisses_open_context_menu_first(self):
        w = _make_built_window()
        menu_obj = w._widget._context_menu
        fake_menu = MagicMock()
        menu_obj._menu = fake_menu
        w.clear_selection_or_dismiss()
        fake_menu.hide.assert_called_once()
        assert menu_obj._menu is None
        w.destroy()

    def test_swallows_hide_exception(self):
        w = _make_built_window()
        menu_obj = w._widget._context_menu
        fake_menu = MagicMock()
        fake_menu.hide.side_effect = RuntimeError("already torn down")
        menu_obj._menu = fake_menu
        w.clear_selection_or_dismiss()  # must not raise
        assert menu_obj._menu is None
        w.destroy()

    def test_clears_detail_tree_selection_when_no_menu(self):
        w = _make_built_window()
        tree = w._widget._detail_tree_view
        tree.selection = []  # sanity
        # Ensure context menu has no live popup.
        w._widget._context_menu._menu = None
        w.clear_selection_or_dismiss()
        assert list(tree.selection) == []
        w.destroy()

    def test_clears_grid_selection_when_no_menu(self):
        w = _make_built_window()
        grid = w._widget._detail_grid_view
        original = grid.set_selection
        called = {"count": 0, "last_arg": None}

        def _spy(items):
            called["count"] += 1
            called["last_arg"] = items
            original(items)

        grid.set_selection = _spy
        try:
            w._widget._context_menu._menu = None
            w.clear_selection_or_dismiss()
            assert called["count"] == 1
            assert list(called["last_arg"]) == []
        finally:
            grid.set_selection = original
        w.destroy()

    def test_before_build_is_noop(self):
        w = ContentBrowserWindow(
            backend=MockBackend(), start_url="mock://Home",
        )
        w.clear_selection_or_dismiss()  # must not raise
        w.destroy()

    def test_after_destroy_is_noop(self):
        w = _make_built_window()
        w.destroy()
        w.clear_selection_or_dismiss()  # must not raise


# ──────────────────────────────────────────────────────────────────────────────
# _on_key_pressed — dispatch table
# ──────────────────────────────────────────────────────────────────────────────


@_skip_no_window
class TestOnKeyPressedDispatch:
    def test_alt_up_calls_go_up(self):
        w = _make_built_window()
        w.go_up = MagicMock()
        handled = w._on_key_pressed(_KEY_ARROW_UP, _MOD_ALT, True)
        assert handled is True
        w.go_up.assert_called_once()
        w.destroy()

    def test_f5_calls_refresh(self):
        w = _make_built_window()
        w.refresh = MagicMock()
        handled = w._on_key_pressed(_KEY_F5, 0, True)
        assert handled is True
        w.refresh.assert_called_once()
        w.destroy()

    def test_ctrl_f_calls_focus_search(self):
        w = _make_built_window()
        w.focus_search = MagicMock()
        handled = w._on_key_pressed(ord("F"), _MOD_CTRL, True)
        assert handled is True
        w.focus_search.assert_called_once()
        w.destroy()

    def test_ctrl_f_lowercase_calls_focus_search(self):
        w = _make_built_window()
        w.focus_search = MagicMock()
        handled = w._on_key_pressed(ord("f"), _MOD_CTRL, True)
        assert handled is True
        w.focus_search.assert_called_once()
        w.destroy()

    def test_ctrl_home_calls_navigate_home(self):
        w = _make_built_window()
        w.navigate_home = MagicMock()
        handled = w._on_key_pressed(_KEY_HOME, _MOD_CTRL, True)
        assert handled is True
        w.navigate_home.assert_called_once()
        w.destroy()

    def test_escape_calls_clear_selection_or_dismiss(self):
        w = _make_built_window()
        w.clear_selection_or_dismiss = MagicMock()
        handled = w._on_key_pressed(_KEY_ESCAPE, 0, True)
        assert handled is True
        w.clear_selection_or_dismiss.assert_called_once()
        w.destroy()

    def test_release_is_ignored(self):
        w = _make_built_window()
        w.go_up = MagicMock()
        handled = w._on_key_pressed(_KEY_ARROW_UP, _MOD_ALT, False)
        assert handled is False
        w.go_up.assert_not_called()
        w.destroy()

    def test_plain_up_does_not_go_up(self):
        # Up without Alt must not trigger go_up — Arrow keys are used
        # by the tree/grid for selection movement.
        w = _make_built_window()
        w.go_up = MagicMock()
        handled = w._on_key_pressed(_KEY_ARROW_UP, 0, True)
        assert handled is False
        w.go_up.assert_not_called()
        w.destroy()

    def test_ctrl_alt_up_does_not_go_up(self):
        # Ctrl+Alt+Up is not the go-up shortcut — must drop through.
        w = _make_built_window()
        w.go_up = MagicMock()
        handled = w._on_key_pressed(
            _KEY_ARROW_UP, _MOD_ALT | _MOD_CTRL, True,
        )
        assert handled is False
        w.go_up.assert_not_called()
        w.destroy()

    def test_ctrl_shift_f_does_not_focus_search(self):
        w = _make_built_window()
        w.focus_search = MagicMock()
        handled = w._on_key_pressed(
            ord("F"), _MOD_CTRL | _MOD_SHIFT, True,
        )
        assert handled is False
        w.focus_search.assert_not_called()
        w.destroy()

    def test_shift_f5_does_not_refresh(self):
        w = _make_built_window()
        w.refresh = MagicMock()
        handled = w._on_key_pressed(_KEY_F5, _MOD_SHIFT, True)
        assert handled is False
        w.refresh.assert_not_called()
        w.destroy()

    def test_shift_escape_does_not_dismiss(self):
        w = _make_built_window()
        w.clear_selection_or_dismiss = MagicMock()
        handled = w._on_key_pressed(_KEY_ESCAPE, _MOD_SHIFT, True)
        assert handled is False
        w.clear_selection_or_dismiss.assert_not_called()
        w.destroy()

    def test_alt_home_does_not_navigate_home(self):
        w = _make_built_window()
        w.navigate_home = MagicMock()
        handled = w._on_key_pressed(_KEY_HOME, _MOD_ALT, True)
        assert handled is False
        w.navigate_home.assert_not_called()
        w.destroy()

    def test_unknown_key_drops_through(self):
        w = _make_built_window()
        handled = w._on_key_pressed(ord("X"), 0, True)
        assert handled is False
        w.destroy()

    def test_modifier_noise_masked(self):
        # The top bit (``kModifierFlagWantCaptureKeyboard`` in ovui) is
        # stripped by the _REAL_MODS_MASK before dispatch, so a stray
        # high bit on Alt does not block Alt+Up.
        w = _make_built_window()
        w.go_up = MagicMock()
        handled = w._on_key_pressed(
            _KEY_ARROW_UP, _MOD_ALT | 0x1000, True,
        )
        assert handled is True
        w.go_up.assert_called_once()
        w.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Application-level integration (Step 58 fan-out)
# ──────────────────────────────────────────────────────────────────────────────


class TestApplicationForwardsToContentWindow:
    """The application-level dispatcher forwards unmatched keys.

    :meth:`Application._on_key_pressed` now ends with a
    ``_content_window._on_key_pressed(...)`` fan-out so the
    Step-58 shortcuts reach :class:`ContentBrowserWindow`'s own
    dispatcher. These tests mirror the pattern in
    :file:`test_keyboard_shortcuts.py`.
    """

    def _make_app(self):
        from unittest.mock import patch

        from ovui_widgets.app.application import Application

        Application._instance = None
        with patch("ovui_widgets.app.application.SnapSystem"), \
             patch("ovui_widgets.app.application.GridSnapProvider"), \
             patch("ovui_widgets.app.application.SurfaceSnapProvider"):
            app = Application.__new__(Application)
            app._settings = MagicMock()
            app._settings.get.return_value = "dark"
            app._settings.subscribe.return_value = MagicMock()
            app._undo_manager = MagicMock()
            app._selection_bus = MagicMock()
            app._stage_adapter = None
            app._main_win = None
            app._stage_window = None
            app._viewport_window = None
            app._pending_callbacks = []
            app._running = False
            app._dockspace = None
            app._status_bar = None
            app._property_window = None
            app._content_window = None
            app._current_stage_sub = None
            app._stage_change_listeners = []
            app._snap_system = MagicMock()
            app._snap_sub = MagicMock()
            app._theme_sub = MagicMock()
            Application._instance = app
        return app

    def teardown_method(self):
        from ovui_widgets.app.application import Application
        Application._instance = None

    def test_alt_up_forwards_to_content_window(self):
        app = self._make_app()
        app._content_window = MagicMock()
        app._on_key_pressed(_KEY_ARROW_UP, _MOD_ALT, True)
        app._content_window._on_key_pressed.assert_called_once_with(
            _KEY_ARROW_UP, _MOD_ALT, True,
        )

    def test_f5_forwards_to_content_window(self):
        app = self._make_app()
        app._content_window = MagicMock()
        app._on_key_pressed(_KEY_F5, 0, True)
        app._content_window._on_key_pressed.assert_called_once_with(
            _KEY_F5, 0, True,
        )

    def test_ctrl_home_forwards_to_content_window(self):
        app = self._make_app()
        app._content_window = MagicMock()
        app._on_key_pressed(_KEY_HOME, _MOD_CTRL, True)
        app._content_window._on_key_pressed.assert_called_once_with(
            _KEY_HOME, _MOD_CTRL, True,
        )

    def test_escape_forwards_to_content_window(self):
        app = self._make_app()
        app._content_window = MagicMock()
        app._on_key_pressed(_KEY_ESCAPE, 0, True)
        app._content_window._on_key_pressed.assert_called_once_with(
            _KEY_ESCAPE, 0, True,
        )

    def test_ctrl_z_does_not_forward_to_content_window(self):
        # Ctrl+Z still goes to the undo manager — it must not double-
        # dispatch to content_window._on_key_pressed.
        app = self._make_app()
        app._content_window = MagicMock()
        app._on_key_pressed(ord("Z"), _MOD_CTRL, True)
        app._undo_manager.undo.assert_called_once()
        app._content_window._on_key_pressed.assert_not_called()

    def test_alt_left_does_not_forward_to_on_key_pressed(self):
        # Alt+Left dispatches through the explicit go_back proxy; it
        # must NOT also bounce through content_window._on_key_pressed.
        from tests.test_keyboard_shortcuts import _KEY_ARROW_LEFT
        app = self._make_app()
        app._content_window = MagicMock()
        app._on_key_pressed(_KEY_ARROW_LEFT, _MOD_ALT, True)
        app._content_window.go_back.assert_called_once()
        app._content_window._on_key_pressed.assert_not_called()

    def test_release_does_not_forward_to_shortcut_dispatcher(self):
        # Release events still early-return in Application._on_key_pressed
        # before the shortcut-dispatch ``else`` branch -- so
        # ``content_window._on_key_pressed`` is NOT invoked on release.
        # Step 10/13 added a sibling forward_modifier_bits path that
        # IS called on release; that is exercised separately below.
        app = self._make_app()
        app._content_window = MagicMock()
        app._on_key_pressed(_KEY_F5, 0, False)
        app._content_window._on_key_pressed.assert_not_called()

    def test_release_forwards_modifier_bits_to_content_window(self):
        # Step 10/13: every key event (press AND release) must update
        # the content browser's modifier-bit snapshot via
        # ``forward_modifier_bits``, before the ``not pressed``
        # early-return that gates shortcut dispatch.
        app = self._make_app()
        app._content_window = MagicMock()
        app._on_key_pressed(_KEY_F5, 0, False)
        app._content_window.forward_modifier_bits.assert_called_once_with(0)

    def test_ctrl_press_then_release_updates_widget_modifier_bits(self):
        # End-to-end: Ctrl press through Application sets the widget's
        # _modifier_bits; a subsequent Ctrl release through Application
        # clears it. Drives the real ``forward_modifier_bits`` -> widget
        # path so the regression Codex flagged is locked down.
        from ovui_widgets.content.widget.file_browser_widget import _MOD_CTRL

        class _StubWidget:
            def __init__(self):
                self._modifier_bits = 0

            def set_modifier_bits(self, bits):
                self._modifier_bits = int(bits)

        class _StubContentWindow:
            def __init__(self, widget):
                self._widget = widget

            def forward_modifier_bits(self, bits):
                self._widget.set_modifier_bits(bits)

            def _on_key_pressed(self, key, mods, pressed):
                return False

        app = self._make_app()
        widget = _StubWidget()
        app._content_window = _StubContentWindow(widget)
        # Ctrl-down: widget gets Ctrl bit set.
        app._on_key_pressed(ord("A"), _MOD_CTRL, True)
        assert widget._modifier_bits & _MOD_CTRL == _MOD_CTRL
        # Ctrl-up: widget gets Ctrl bit cleared via the release path.
        app._on_key_pressed(ord("A"), 0, False)
        assert widget._modifier_bits & _MOD_CTRL == 0

    def test_forward_without_content_window_does_not_raise(self):
        app = self._make_app()
        app._content_window = None
        app._on_key_pressed(_KEY_F5, 0, True)  # must not raise

    def test_forward_modifier_bits_without_content_window_does_not_raise(self):
        # Release path also has a None-content-window guard.
        app = self._make_app()
        app._content_window = None
        app._on_key_pressed(_KEY_F5, 0, False)  # must not raise

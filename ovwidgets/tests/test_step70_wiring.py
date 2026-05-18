# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Integration tests for Step 70 — Final Wiring Pass.

Verifies that Application.__init__ creates all expected subsystems and that
keyboard shortcuts, drop handler, and open_stage are correctly wired.
"""

from unittest.mock import MagicMock, patch

import pytest

from ovwidgets.app.application import Application
from ovwidgets.common.recent_files import RecentFileList
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.snap import GridSnapProvider, SnapSystem, SurfaceSnapProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_singletons():
    Application._instance = None
    SelectionBus._instance = None
    yield
    if Application._instance is not None:
        Application._instance.shutdown()
    Application._instance = None
    SelectionBus._instance = None


@pytest.fixture
def app():
    a = Application()
    yield a
    a.shutdown()


# ---------------------------------------------------------------------------
# Subsystem wiring
# ---------------------------------------------------------------------------

class TestSubsystemWiring:
    def test_snap_system_is_snap_system(self, app):
        assert isinstance(app._snap_system, SnapSystem)

    def test_snap_system_property_exposed(self, app):
        assert app.snap_system is app._snap_system

    def test_snap_system_has_two_providers(self, app):
        assert len(app._snap_system._providers) == 2

    def test_first_provider_is_grid(self, app):
        assert isinstance(app._snap_system._providers[0], GridSnapProvider)

    def test_second_provider_is_surface(self, app):
        assert isinstance(app._snap_system._providers[1], SurfaceSnapProvider)

    def test_recent_file_list_is_recent_file_list(self, app):
        assert isinstance(app._recent_files, RecentFileList)

    def test_recent_file_list_empty_by_default(self, app):
        assert app._recent_files.get_ordered() == []

    def test_recent_file_list_initialized_with_settings_value(self, app):
        # RecentFileList reads initial list from settings at Application init.
        # Since Settings starts fresh, list is empty; adding a file updates it.
        app._recent_files.add("/test.usd")
        app._settings.set("ui.recent_files", app._recent_files.get_ordered())
        assert app._settings.get("ui.recent_files") == ["/test.usd"]

    def test_settings_dialog_created(self, app):
        from ovwidgets.app.settings_dialog import SettingsDialog
        assert isinstance(app._settings_dialog, SettingsDialog)

    def test_stage_adapter_starts_none(self, app):
        assert app._stage_adapter is None

    def test_stage_window_starts_none(self, app):
        assert app._stage_window is None

    def test_main_win_starts_none(self, app):
        assert app._main_win is None


# ---------------------------------------------------------------------------
# SnapSystem wiring via settings subscription
# ---------------------------------------------------------------------------

class TestSnapSystemSettings:
    def test_snap_disabled_by_default(self, app):
        assert not app._snap_system._enabled

    def test_snap_enabled_via_setting(self, app):
        app.settings.set("snap.enabled", True)
        assert app._snap_system._enabled

    def test_snap_disabled_via_setting_after_enable(self, app):
        app.settings.set("snap.enabled", True)
        app.settings.set("snap.enabled", False)
        assert not app._snap_system._enabled

    def test_on_snap_enabled_changed_enables(self, app):
        app._on_snap_enabled_changed("snap.enabled", True)
        assert app._snap_system._enabled

    def test_on_snap_enabled_changed_disables(self, app):
        app._snap_system.enable(True)
        app._on_snap_enabled_changed("snap.enabled", False)
        assert not app._snap_system._enabled

    def test_grid_provider_default_grid_size_one(self, app):
        provider = app._snap_system._providers[0]
        assert isinstance(provider, GridSnapProvider)
        assert provider._grid_size == 1.0


# ---------------------------------------------------------------------------
# Keyboard shortcut dispatch
# ---------------------------------------------------------------------------

class TestKeyboardShortcuts:
    _KEY_F2 = 291
    _KEY_DELETE = 261
    _KEY_BACKSPACE = 259
    _MOD_CTRL = 2
    _MOD_SHIFT = 1

    def test_key_release_is_noop(self, app):
        app._undo_manager = MagicMock()
        app._on_key_pressed(ord('Z'), self._MOD_CTRL, False)
        app._undo_manager.undo.assert_not_called()

    def test_ctrl_z_calls_undo(self, app):
        app._undo_manager = MagicMock()
        app._on_key_pressed(ord('z'), self._MOD_CTRL, True)
        app._undo_manager.undo.assert_called_once()

    def test_ctrl_uppercase_z_calls_undo(self, app):
        app._undo_manager = MagicMock()
        app._on_key_pressed(ord('Z'), self._MOD_CTRL, True)
        app._undo_manager.undo.assert_called_once()

    def test_ctrl_y_calls_redo(self, app):
        app._undo_manager = MagicMock()
        app._on_key_pressed(ord('y'), self._MOD_CTRL, True)
        app._undo_manager.redo.assert_called_once()

    def test_ctrl_shift_z_calls_redo(self, app):
        app._undo_manager = MagicMock()
        app._on_key_pressed(ord('z'), self._MOD_CTRL | self._MOD_SHIFT, True)
        app._undo_manager.redo.assert_called_once()

    def test_delete_calls_delete_selected(self, app):
        with patch.object(app, '_delete_selected') as mock_del:
            app._on_key_pressed(self._KEY_DELETE, 0, True)
            mock_del.assert_called_once()

    def test_backspace_calls_delete_selected(self, app):
        with patch.object(app, '_delete_selected') as mock_del:
            app._on_key_pressed(self._KEY_BACKSPACE, 0, True)
            mock_del.assert_called_once()

    def test_f_calls_frame_selected(self, app):
        with patch.object(app, '_frame_selected') as mock_frame:
            app._on_key_pressed(ord('f'), 0, True)
            mock_frame.assert_called_once()

    def test_uppercase_f_calls_frame_selected(self, app):
        with patch.object(app, '_frame_selected') as mock_frame:
            app._on_key_pressed(ord('F'), 0, True)
            mock_frame.assert_called_once()

    def test_f2_calls_begin_rename_selected(self, app):
        mock_stage_win = MagicMock()
        app._stage_window = mock_stage_win
        app._on_key_pressed(self._KEY_F2, 0, True)
        mock_stage_win.begin_rename_selected.assert_called_once()

    def test_f2_without_stage_window_no_crash(self, app):
        app._stage_window = None
        app._on_key_pressed(self._KEY_F2, 0, True)  # must not raise

    def test_unrecognized_key_is_noop(self, app):
        app._undo_manager = MagicMock()
        app._on_key_pressed(999, 0, True)
        app._undo_manager.undo.assert_not_called()
        app._undo_manager.redo.assert_not_called()


# ---------------------------------------------------------------------------
# Shortcut and drop handler registration
# ---------------------------------------------------------------------------

class TestShortcutRegistration:
    def test_register_shortcuts_wires_key_fn(self, app):
        mock_win = MagicMock()
        app._main_win = mock_win
        app._register_shortcuts()
        mock_win.set_key_pressed_fn.assert_called_once_with(app._on_key_pressed)

    def test_register_shortcuts_no_crash_when_win_none(self, app):
        app._main_win = None
        app._register_shortcuts()  # must not raise


class TestDropHandlerRegistration:
    def test_register_drop_handler_wires_drop_fn(self, app):
        mock_win = MagicMock()
        app._main_win = mock_win
        app._register_drop_handler()
        mock_win.set_drop_fn.assert_called_once_with(app._on_drop)

    def test_register_drop_handler_no_crash_when_set_drop_fn_absent(self, app):
        mock_win = MagicMock(spec=[])
        app._main_win = mock_win
        app._register_drop_handler()  # must not raise

    def test_register_drop_handler_no_crash_when_win_none(self, app):
        app._main_win = None
        app._register_drop_handler()  # must not raise


# ---------------------------------------------------------------------------
# delete_selected and frame_selected with no adapters
# ---------------------------------------------------------------------------

class TestNoAdapterSafety:
    def test_delete_selected_no_adapter_no_crash(self, app):
        app._stage_adapter = None
        app._delete_selected()  # must not raise

    def test_frame_selected_no_viewport_no_crash(self, app):
        app._viewport_window = None
        app._frame_selected()  # must not raise

    def test_delete_selected_empty_snapshot_no_crash(self, app):
        app._delete_selected()  # selection bus starts empty — must not raise


# ---------------------------------------------------------------------------
# open_stage wiring
# ---------------------------------------------------------------------------

class TestOpenStageWiring:
    def test_open_stage_sets_stage_adapter(self, app):
        pytest.importorskip("pxr", reason="pxr not available")
        mock_stage = MagicMock()
        with patch("ovui_data_adapters.openusd.stage_adapter.UsdStageAdapter", autospec=True), \
             patch("ovui_data_adapters.openusd.property_adapter.UsdPropertyAdapter", autospec=True):
            app.open_stage(mock_stage)
            assert app._stage_adapter is not None

    def test_open_stage_no_crash_without_windows(self, app):
        pytest.importorskip("pxr", reason="pxr not available")
        app._stage_window = None
        app._property_window = None
        mock_stage = MagicMock()
        with patch("ovui_data_adapters.openusd.stage_adapter.UsdStageAdapter", autospec=True), \
             patch("ovui_data_adapters.openusd.property_adapter.UsdPropertyAdapter", autospec=True):
            app.open_stage(mock_stage)  # must not raise

    def test_open_stage_twice_no_crash(self, app):
        pytest.importorskip("pxr", reason="pxr not available")
        mock_stage = MagicMock()
        with patch("ovui_data_adapters.openusd.stage_adapter.UsdStageAdapter", autospec=True), \
             patch("ovui_data_adapters.openusd.property_adapter.UsdPropertyAdapter", autospec=True):
            app.open_stage(mock_stage)
            app.open_stage(mock_stage)  # second call must not raise
            assert app._stage_adapter is not None


# ---------------------------------------------------------------------------
# Headless smoke
# ---------------------------------------------------------------------------

class TestHeadlessSmoke:
    def test_headless_instantiation_no_crash(self):
        app = Application()
        assert app is not None
        app.shutdown()

    def test_all_properties_accessible(self, app):
        _ = app.settings
        _ = app.undo_manager
        _ = app.selection_bus
        _ = app.snap_system

    def test_running_starts_false(self, app):
        assert not app._running

    def test_singleton_accessible_via_instance(self, app):
        assert Application.instance() is app

    def test_shutdown_clears_stage_adapter(self, app):
        app._stage_adapter = MagicMock()
        app.shutdown()
        assert app._stage_adapter is None

    def test_shutdown_clears_snap_subscription(self, app):
        app.shutdown()
        assert app._snap_sub is None

    def test_shutdown_clears_theme_subscription(self, app):
        app.shutdown()
        assert app._theme_sub is None

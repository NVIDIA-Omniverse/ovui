# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for keyboard shortcut handler (Step 53)."""

from unittest.mock import MagicMock, patch

import pytest

# GLFW key/modifier constants from application.py
_MOD_CTRL = 2
_MOD_SHIFT = 1
_MOD_ALT = 4
_KEY_DELETE = 261
_KEY_BACKSPACE = 259
_KEY_F2 = 291
_IMGUI_KEY_F = 546 + 5
# Arrow-key codes — used by the Alt+Left / Alt+Right content-browser
# back/forward shortcuts (Content-Browser Step 20).
_KEY_ARROW_RIGHT = 262
_KEY_ARROW_LEFT = 263


def _make_app():
    """Create a minimal Application-like object for testing shortcuts."""
    from ovwidgets.app.application import Application
    # Avoid singleton assertion by resetting _instance
    Application._instance = None
    with patch("ovwidgets.app.application.SnapSystem"), \
         patch("ovwidgets.app.application.GridSnapProvider"), \
         patch("ovwidgets.app.application.SurfaceSnapProvider"):
        app = Application.__new__(Application)
        app._settings = MagicMock()
        app._settings.get.return_value = "dark"
        app._settings.subscribe.return_value = MagicMock()
        app._undo_manager = MagicMock()
        app._selection_bus = MagicMock()
        app._stage_adapter = None
        app._layer_adapter = None
        app._main_win = None
        app._stage_window = None
        app._viewport_window = None
        app._pending_callbacks = []
        app._running = False
        app._dockspace = None
        app._status_bar = None
        app._stage_window = None
        app._property_window = None
        app._viewport_window = None
        app._content_window = None
        app._layer_window = None
        app._current_stage_sub = None
        app._stage_change_listeners = []
        app._snap_system = MagicMock()
        app._snap_sub = MagicMock()
        app._theme_sub = MagicMock()
        Application._instance = app
    return app


def teardown_function():
    from ovwidgets.app.application import Application
    Application._instance = None


class TestKeyPressedDispatch:

    def test_ctrl_z_calls_undo(self):
        app = _make_app()
        app._on_key_pressed(ord("Z"), _MOD_CTRL, True)
        app._undo_manager.undo.assert_called_once()
        app._undo_manager.redo.assert_not_called()

    def test_ctrl_z_lowercase_calls_undo(self):
        app = _make_app()
        app._on_key_pressed(ord("z"), _MOD_CTRL, True)
        app._undo_manager.undo.assert_called_once()

    def test_ctrl_y_calls_redo(self):
        app = _make_app()
        app._on_key_pressed(ord("Y"), _MOD_CTRL, True)
        app._undo_manager.redo.assert_called_once()
        app._undo_manager.undo.assert_not_called()

    def test_ctrl_shift_z_calls_redo(self):
        app = _make_app()
        app._on_key_pressed(ord("Z"), _MOD_CTRL | _MOD_SHIFT, True)
        app._undo_manager.redo.assert_called_once()
        app._undo_manager.undo.assert_not_called()

    def test_not_pressed_is_ignored(self):
        app = _make_app()
        app._on_key_pressed(ord("Z"), _MOD_CTRL, False)
        app._undo_manager.undo.assert_not_called()
        app._undo_manager.redo.assert_not_called()

    def test_delete_key_calls_delete_selected(self):
        app = _make_app()
        app._delete_selected = MagicMock()
        app._on_key_pressed(_KEY_DELETE, 0, True)
        app._delete_selected.assert_called_once()

    def test_backspace_key_calls_delete_selected(self):
        app = _make_app()
        app._delete_selected = MagicMock()
        app._on_key_pressed(_KEY_BACKSPACE, 0, True)
        app._delete_selected.assert_called_once()

    def test_f_key_calls_frame_selected(self):
        app = _make_app()
        app._frame_selected = MagicMock()
        app._on_key_pressed(ord("F"), 0, True)
        app._frame_selected.assert_called_once()

    def test_f_lowercase_calls_frame_selected(self):
        app = _make_app()
        app._frame_selected = MagicMock()
        app._on_key_pressed(ord("f"), 0, True)
        app._frame_selected.assert_called_once()

    def test_imgui_f_key_calls_frame_selected(self):
        """Inspector/remote input injects ImGuiKey_F, not ASCII 'F'."""
        app = _make_app()
        app._frame_selected = MagicMock()
        app._on_key_pressed(_IMGUI_KEY_F, 0, True)
        app._frame_selected.assert_called_once()

    def test_f2_calls_begin_rename_selected(self):
        app = _make_app()
        app._stage_window = MagicMock()
        app._on_key_pressed(_KEY_F2, 0, True)
        app._stage_window.begin_rename_selected.assert_called_once()

    def test_f2_without_stage_window_does_not_raise(self):
        app = _make_app()
        app._stage_window = None
        app._on_key_pressed(_KEY_F2, 0, True)  # Should not raise

    def test_unrecognized_key_does_nothing(self):
        app = _make_app()
        app._on_key_pressed(ord("X"), 0, True)
        app._undo_manager.undo.assert_not_called()
        app._undo_manager.redo.assert_not_called()

    def test_alt_left_calls_content_window_go_back(self):
        """Content-Browser Step 20: Alt+Left dispatches to the content window."""
        app = _make_app()
        app._content_window = MagicMock()
        app._on_key_pressed(_KEY_ARROW_LEFT, _MOD_ALT, True)
        app._content_window.go_back.assert_called_once()
        app._content_window.go_forward.assert_not_called()

    def test_alt_right_calls_content_window_go_forward(self):
        """Content-Browser Step 20: Alt+Right dispatches to the content window."""
        app = _make_app()
        app._content_window = MagicMock()
        app._on_key_pressed(_KEY_ARROW_RIGHT, _MOD_ALT, True)
        app._content_window.go_forward.assert_called_once()
        app._content_window.go_back.assert_not_called()

    def test_alt_left_without_content_window_does_not_raise(self):
        app = _make_app()
        app._content_window = None
        app._on_key_pressed(_KEY_ARROW_LEFT, _MOD_ALT, True)  # must not raise

    def test_alt_right_without_content_window_does_not_raise(self):
        app = _make_app()
        app._content_window = None
        app._on_key_pressed(_KEY_ARROW_RIGHT, _MOD_ALT, True)  # must not raise

    def test_plain_left_does_not_trigger_go_back(self):
        """Left arrow without Alt must not fire the content-browser nav."""
        app = _make_app()
        app._content_window = MagicMock()
        app._on_key_pressed(_KEY_ARROW_LEFT, 0, True)
        app._content_window.go_back.assert_not_called()

    def test_ctrl_alt_left_does_not_trigger_go_back(self):
        """Ctrl-Alt chord is not the back shortcut — must not fire."""
        app = _make_app()
        app._content_window = MagicMock()
        app._on_key_pressed(_KEY_ARROW_LEFT, _MOD_ALT | _MOD_CTRL, True)
        app._content_window.go_back.assert_not_called()


class TestDeleteSelected:

    def test_no_selection_does_nothing(self):
        app = _make_app()
        snap = MagicMock()
        snap.items = []
        app._selection_bus.get_snapshot.return_value = snap
        app._delete_selected()
        app._undo_manager.begin_group.assert_not_called()

    def test_no_stage_adapter_does_nothing(self):
        app = _make_app()
        snap = MagicMock()
        snap.items = [MagicMock(path="/Sphere")]
        app._selection_bus.get_snapshot.return_value = snap
        app._stage_adapter = None
        app._delete_selected()
        app._undo_manager.begin_group.assert_not_called()

    def test_with_selection_begins_group(self):
        pytest.importorskip("pxr", reason="pxr not available")
        app = _make_app()
        snap = MagicMock()
        item = MagicMock()
        item.path = "/Sphere"
        snap.items = [item]
        app._selection_bus.get_snapshot.return_value = snap

        mock_stage = MagicMock()
        mock_adapter = MagicMock()
        mock_adapter.stage = mock_stage
        app._stage_adapter = mock_adapter

        with patch("ovui_data_adapters.openusd.commands.DeletePrimCommand") as MockCmd, \
             patch("pxr.Sdf") as MockSdf:
            MockCmd.return_value = MagicMock()
            MockSdf.Path.return_value = MagicMock()
            app._delete_selected()

        app._undo_manager.begin_group.assert_called_once_with("Delete")
        app._undo_manager.end_group.assert_called_once()
        # Two commands pushed inside the Delete group (Codex final-UI-rerun
        # selection-clear fix): a ``_SelectionDuringDeleteCommand`` first
        # (clears the selection bus on do, restores it on undo) and the
        # ``DeletePrimCommand`` for the selected ``/Sphere`` second. The
        # selection-clear command is required so subscribers don't iterate
        # the deleted path on the next call_later notice flush.
        assert app._undo_manager.push.call_count == 2


class TestFrameSelected:

    def test_no_viewport_does_nothing(self):
        app = _make_app()
        snap = MagicMock()
        snap.items = [MagicMock(path="/Sphere")]
        app._selection_bus.get_snapshot.return_value = snap
        app._viewport_window = None
        app._frame_selected()  # should not raise

    def test_calls_frame_paths_with_selected_paths(self):
        app = _make_app()
        snap = MagicMock()
        item = MagicMock()
        item.path = "/Sphere"
        snap.items = [item]
        app._selection_bus.get_snapshot.return_value = snap

        viewport = MagicMock()
        app._viewport_window = viewport
        app._frame_selected()

        viewport.frame_paths.assert_called_once_with(["/Sphere"])

    def test_empty_snapshot_still_calls_frame_paths(self):
        app = _make_app()
        snap = MagicMock()
        snap.items = []
        app._selection_bus.get_snapshot.return_value = snap

        viewport = MagicMock()
        app._viewport_window = viewport
        app._frame_selected()

        viewport.frame_paths.assert_called_once_with([])


class TestRegisterShortcuts:

    def test_register_shortcuts_wires_key_pressed_fn(self):
        app = _make_app()
        win = MagicMock()
        app._main_win = win
        app._register_shortcuts()
        win.set_key_pressed_fn.assert_called_once_with(app._on_key_pressed)

    def test_register_shortcuts_no_window_does_not_raise(self):
        app = _make_app()
        app._main_win = None
        app._register_shortcuts()  # should not raise


# ── Step 59 · Layer save / toggle shortcuts ────────────────────────────


class TestLayerSaveShortcuts:
    """Ctrl+S / Ctrl+Shift+S / Ctrl+Alt+S / Ctrl+L dispatching."""

    def test_ctrl_s_dispatches_save_stage(self):
        app = _make_app()
        app.save_stage = MagicMock()
        app._on_key_pressed(ord("S"), _MOD_CTRL, True)
        app.save_stage.assert_called_once()

    def test_ctrl_s_lowercase_dispatches_save_stage(self):
        app = _make_app()
        app.save_stage = MagicMock()
        app._on_key_pressed(ord("s"), _MOD_CTRL, True)
        app.save_stage.assert_called_once()

    def test_ctrl_shift_s_dispatches_save_stage_as(self):
        app = _make_app()
        app.save_stage_as = MagicMock()
        app.save_stage = MagicMock()
        app._on_key_pressed(ord("S"), _MOD_CTRL | _MOD_SHIFT, True)
        app.save_stage_as.assert_called_once()
        app.save_stage.assert_not_called()

    def test_ctrl_alt_s_dispatches_save_focused_layer_as(self):
        app = _make_app()
        app.save_focused_layer_as = MagicMock()
        app.save_stage = MagicMock()
        app._on_key_pressed(ord("S"), _MOD_CTRL | _MOD_ALT, True)
        app.save_focused_layer_as.assert_called_once()
        app.save_stage.assert_not_called()

    def test_plain_s_does_not_save(self):
        app = _make_app()
        app.save_stage = MagicMock()
        app._on_key_pressed(ord("S"), 0, True)
        app.save_stage.assert_not_called()

    def test_ctrl_l_toggles_layers_window(self):
        app = _make_app()
        lw = MagicMock()
        lw.visible = False
        app._layer_window = lw
        app._on_key_pressed(ord("L"), _MOD_CTRL, True)
        assert lw.visible is True

    def test_ctrl_l_lowercase_toggles_layers_window(self):
        app = _make_app()
        lw = MagicMock()
        lw.visible = True
        app._layer_window = lw
        app._on_key_pressed(ord("l"), _MOD_CTRL, True)
        assert lw.visible is False

    def test_ctrl_l_no_layer_window_does_not_raise(self):
        app = _make_app()
        app._layer_window = None
        app._on_key_pressed(ord("L"), _MOD_CTRL, True)  # must not raise


class TestSaveStage:

    def test_no_stage_shows_error(self):
        app = _make_app()
        app._layer_adapter = None
        with patch("ovwidgets.common.error_reporter.ErrorReporter") as Reporter:
            app.save_stage()
        Reporter.show_error.assert_called_once_with("No stage open")

    def test_with_stage_calls_request_save_all(self):
        app = _make_app()
        app._layer_adapter = MagicMock()
        lw = MagicMock()
        lw._model = MagicMock()
        app._layer_window = lw
        app.save_stage()
        lw._model._request_save_all.assert_called_once()

    def test_no_model_does_not_raise(self):
        app = _make_app()
        app._layer_adapter = MagicMock()
        lw = MagicMock()
        lw._model = None
        app._layer_window = lw
        app.save_stage()  # must not raise


class TestSaveStageAs:

    def test_no_stage_shows_error(self):
        app = _make_app()
        app._layer_adapter = None
        with patch("ovwidgets.common.error_reporter.ErrorReporter") as Reporter:
            app.save_stage_as()
        Reporter.show_error.assert_called_once_with("No stage open")

    def test_with_stage_opens_save_as_on_root(self):
        app = _make_app()
        app._layer_adapter = MagicMock()
        root = MagicMock()
        model = MagicMock()
        model.root_item = root
        lw = MagicMock()
        lw._model = model
        app._layer_window = lw
        app.save_stage_as()
        model._request_save_as.assert_called_once_with(
            root, replace_in_parent=False
        )

    def test_no_root_item_does_not_raise(self):
        app = _make_app()
        app._layer_adapter = MagicMock()
        model = MagicMock()
        model.root_item = None
        lw = MagicMock()
        lw._model = model
        app._layer_window = lw
        app.save_stage_as()
        model._request_save_as.assert_not_called()


class TestSaveFocusedLayerAs:

    def test_layers_window_unfocused_noop(self):
        app = _make_app()
        app._layer_adapter = MagicMock()
        lw = MagicMock()
        lw.is_focused = False
        lw._model = MagicMock()
        app._layer_window = lw
        app.save_focused_layer_as()
        lw._model._request_save_as.assert_not_called()

    def test_no_layers_window_noop(self):
        app = _make_app()
        app._layer_window = None
        app.save_focused_layer_as()  # must not raise

    def test_no_stage_shows_error_even_when_focused(self):
        app = _make_app()
        app._layer_adapter = None
        lw = MagicMock()
        lw.is_focused = True
        app._layer_window = lw
        with patch("ovwidgets.common.error_reporter.ErrorReporter") as Reporter:
            app.save_focused_layer_as()
        Reporter.show_error.assert_called_once_with("No stage open")

    def test_single_layer_selection_uses_selected(self):
        app = _make_app()
        app._layer_adapter = MagicMock()
        from ovwidgets.layers.layer_item import LayerItem
        selected = MagicMock(spec=LayerItem)
        model = MagicMock()
        model.selected_items = [selected]
        model.root_item = MagicMock(spec=LayerItem)
        lw = MagicMock()
        lw.is_focused = True
        lw._model = model
        app._layer_window = lw
        app.save_focused_layer_as()
        model._request_save_as.assert_called_once_with(
            selected, replace_in_parent=True
        )

    def test_no_selection_falls_back_to_root(self):
        app = _make_app()
        app._layer_adapter = MagicMock()
        from ovwidgets.layers.layer_item import LayerItem
        root = MagicMock(spec=LayerItem)
        model = MagicMock()
        model.selected_items = []
        model.root_item = root
        lw = MagicMock()
        lw.is_focused = True
        lw._model = model
        app._layer_window = lw
        app.save_focused_layer_as()
        model._request_save_as.assert_called_once_with(
            root, replace_in_parent=True
        )

    def test_multi_layer_selection_falls_back_to_root(self):
        app = _make_app()
        app._layer_adapter = MagicMock()
        from ovwidgets.layers.layer_item import LayerItem
        root = MagicMock(spec=LayerItem)
        a, b = MagicMock(spec=LayerItem), MagicMock(spec=LayerItem)
        model = MagicMock()
        model.selected_items = [a, b]
        model.root_item = root
        lw = MagicMock()
        lw.is_focused = True
        lw._model = model
        app._layer_window = lw
        app.save_focused_layer_as()
        model._request_save_as.assert_called_once_with(
            root, replace_in_parent=True
        )


class TestToggleLayersWindow:

    def test_toggle_flips_visibility(self):
        app = _make_app()
        lw = MagicMock()
        lw.visible = False
        app._layer_window = lw
        app._toggle_layers_window()
        assert lw.visible is True
        app._toggle_layers_window()
        assert lw.visible is False

    def test_toggle_no_window_noop(self):
        app = _make_app()
        app._layer_window = None
        app._toggle_layers_window()  # must not raise

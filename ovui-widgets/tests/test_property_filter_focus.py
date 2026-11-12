# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Issue 203: Backspace in the Property Inspector filter deleted the prim.

A filter change used to rebuild the whole Property Inspector, including the
filter field. The new field had no keyboard focus, so the next Backspace or
Delete went to the application shortcuts and deleted the selected prim.
"""

from unittest.mock import MagicMock

import omni.ui as ui
import pytest

from tests.test_keyboard_shortcuts import _KEY_BACKSPACE, _KEY_DELETE, _make_app
from tests.test_property_filter import _two_group_adapter


@pytest.fixture(autouse=True)
def _no_application_instance():
    from ovui_widgets.app.application import Application

    yield
    Application._instance = None


@pytest.fixture
def scheduled(monkeypatch):
    """Collect ``call_later`` callbacks, so a test runs them when it chooses."""
    from ovui_widgets.common import scheduler

    pending = []

    def call_later(delay_secs, callback):
        handle = scheduler.CallbackHandle(delay_secs, callback)
        pending.append(handle)
        return handle

    monkeypatch.setattr(scheduler, "_call_later_fn", call_later)

    def run_all():
        while pending:
            handle = pending.pop(0)
            if not handle.is_cancelled:
                handle._callback()

    return run_all


class TestFilterFieldSurvivesFilterChange:
    @staticmethod
    def _window_with_selection():
        from ovui_widgets.property.window import PropertyWindow

        window = PropertyWindow()
        # The window builds its UI later, in the frame loop. Build it now.
        window._build_frame = ui.Frame()
        with window._build_frame:
            window._build_ui()
        window.set_adapter(_two_group_adapter())
        window.set_selection(["/World/Cube"])
        window._rebuild_content()
        return window

    def test_filter_field_is_kept_when_the_user_types(self, scheduled):
        window = self._window_with_selection()
        try:
            field = window._filter_field
            assert field is not None
            field.model.set_value("a")
            scheduled()
            assert window._filter_text == "a"
            # The field that holds the keyboard focus must stay the same
            # object. A new field has no focus, and Backspace then deletes
            # the selected prim.
            assert window._filter_field is field
            field.model.set_value("")
            scheduled()
            assert window._filter_text == ""
            assert window._filter_field is field
        finally:
            window.destroy()

    def test_rows_below_the_filter_follow_the_filter_text(self, scheduled):
        window = self._window_with_selection()
        try:
            before = sorted(window._inspector_attribute_rows)
            assert before
            window._filter_field.model.set_value("rotate")
            scheduled()
            assert sorted(window._inspector_attribute_rows) == ["xformOp:rotate"]
            window._filter_field.model.set_value("")
            scheduled()
            assert sorted(window._inspector_attribute_rows) == before
        finally:
            window.destroy()

    def test_new_selection_builds_a_new_filter_field(self, scheduled):
        window = self._window_with_selection()
        try:
            window._on_filter_begin_edit(None)
            assert window.is_filter_editing()
            window._rebuild_content()
            # The old field is gone, so its edit state must not stay on.
            assert not window.is_filter_editing()
        finally:
            window.destroy()

    def test_filter_editing_follows_begin_and_end_edit(self, scheduled):
        window = self._window_with_selection()
        try:
            assert not window.is_filter_editing()
            window._on_filter_begin_edit(None)
            assert window.is_filter_editing()
            window._on_filter_end_edit(None)
            assert not window.is_filter_editing()
        finally:
            window.destroy()


class TestApplicationKeepsPrimWhilePropertyFilterEdits:
    @staticmethod
    def _app(filter_editing, property_focused=False):
        app = _make_app()
        app._property_window = MagicMock()
        app._property_window.is_filter_editing.return_value = filter_editing
        app._property_window.is_focused = property_focused
        app._content_window = MagicMock()
        # The Content Browser has no focus, so a key press deletes the prim.
        app._content_window.is_focused = False
        app._delete_selected = MagicMock()
        app._delete_selected_prim_specs_in_layers = MagicMock(return_value=False)
        return app

    @pytest.mark.parametrize("key", [_KEY_BACKSPACE, _KEY_DELETE])
    def test_key_in_property_filter_deletes_nothing(self, key):
        app = self._app(filter_editing=True)
        app._on_key_pressed(key, 0, True)
        app._delete_selected_prim_specs_in_layers.assert_not_called()
        app._delete_selected.assert_not_called()
        app._content_window.delete_selected.assert_not_called()

    @pytest.mark.parametrize("key", [_KEY_BACKSPACE, _KEY_DELETE])
    def test_key_outside_property_filter_still_deletes(self, key):
        app = self._app(filter_editing=False)
        app._on_key_pressed(key, 0, True)
        app._delete_selected.assert_called_once()
        app._content_window.delete_selected.assert_not_called()

    @pytest.mark.parametrize("key", [_KEY_BACKSPACE, _KEY_DELETE])
    def test_key_with_property_inspector_focused_deletes_nothing(self, key):
        # OMPE-118431: a click on empty panel space or on the read-only Proxy
        # Prim field gives the Property Inspector focus with no text input.
        app = self._app(filter_editing=False, property_focused=True)
        app._on_key_pressed(key, 0, True)
        app._delete_selected_prim_specs_in_layers.assert_not_called()
        app._delete_selected.assert_not_called()
        app._content_window.delete_selected.assert_not_called()

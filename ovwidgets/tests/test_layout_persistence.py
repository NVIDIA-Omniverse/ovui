# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Application layout persistence (Step 55)."""

from unittest.mock import patch

import pytest

from ovwidgets.app.application import Application
from ovwidgets.common.selection import SelectionBus


@pytest.fixture(autouse=True)
def reset_singletons():
    Application._instance = None
    SelectionBus._instance = None
    yield
    Application._instance = None
    SelectionBus._instance = None


@pytest.fixture
def app():
    a = Application()
    yield a
    a.shutdown()


# ---------------------------------------------------------------------------
# LAYOUT_SETTINGS_KEY constant
# ---------------------------------------------------------------------------

class TestLayoutSettingsKey:
    def test_constant_exists(self):
        assert hasattr(Application, "LAYOUT_SETTINGS_KEY")

    def test_constant_value(self):
        assert Application.LAYOUT_SETTINGS_KEY == "ui.layout"

    def test_constant_is_string(self):
        assert isinstance(Application.LAYOUT_SETTINGS_KEY, str)


# ---------------------------------------------------------------------------
# _save_layout
# ---------------------------------------------------------------------------

class TestSaveLayout:
    def test_save_layout_method_exists(self, app):
        assert callable(getattr(app, "_save_layout", None))

    def test_save_layout_stores_window_data_in_settings(self, app):
        fake_data = {"Stage Browser": {"visible": True, "width": 320.0}}
        with patch("ovwidgets.app.layout._collect_layout", return_value=fake_data):
            with patch("ovwidgets.app.layout.save_layout_data"):
                app._save_layout()
        assert app._settings.get(Application.LAYOUT_SETTINGS_KEY) == fake_data

    def test_save_layout_empty_collect_does_not_update_settings(self, app):
        with patch("ovwidgets.app.layout._collect_layout", return_value={}):
            app._save_layout()
        assert app._settings.get(Application.LAYOUT_SETTINGS_KEY) is None

    def test_save_layout_calls_save_layout_data_file(self, app):
        with patch("ovwidgets.app.layout._collect_layout", return_value={"win": {}}):
            with patch("ovwidgets.app.layout.save_layout_data") as mock_save:
                app._save_layout()
        mock_save.assert_called_once()

    def test_save_layout_does_not_raise_on_file_exception(self, app):
        with patch("ovwidgets.app.layout._collect_layout", return_value={"win": {}}):
            with patch("ovwidgets.app.layout.save_layout_data", side_effect=IOError("disk full")):
                app._save_layout()  # Should not raise

    def test_save_layout_uses_settings_save_path(self, app):
        app._settings.set("layout.save_path", "/custom/path.json")
        with patch("ovwidgets.app.layout._collect_layout", return_value={"win": {}}):
            with patch("ovwidgets.app.layout.save_layout_data") as mock_save:
                app._save_layout()
        mock_save.assert_called_once_with("/custom/path.json", {"win": {}})


# ---------------------------------------------------------------------------
# _restore_layout
# ---------------------------------------------------------------------------

class TestRestoreLayout:
    def test_restore_layout_method_exists(self, app):
        assert callable(getattr(app, "_restore_layout", None))

    def test_restore_uses_settings_data_when_present(self, app):
        fake_data = {"Stage Browser": {"visible": True}}
        app._settings.set(Application.LAYOUT_SETTINGS_KEY, fake_data)
        with patch("ovwidgets.app.layout._restore_layout") as mock_apply:
            app._restore_layout()
        mock_apply.assert_called_once_with(fake_data)

    def test_restore_skips_file_when_settings_has_data(self, app):
        fake_data = {"Stage Browser": {"visible": True}}
        app._settings.set(Application.LAYOUT_SETTINGS_KEY, fake_data)
        with patch("ovwidgets.app.layout._restore_layout"):
            with patch("ovwidgets.app.layout.load_layout") as mock_load:
                app._restore_layout()
        mock_load.assert_not_called()

    def test_restore_falls_back_to_file_when_no_settings(self, app):
        with patch("os.path.exists", return_value=True):
            with patch("ovwidgets.app.layout.load_layout") as mock_load:
                app._restore_layout()
        mock_load.assert_called_once()

    def test_restore_falls_back_to_default_when_no_file(self, app):
        with patch("os.path.exists", return_value=False):
            with patch("ovwidgets.app.layout.apply_default_layout") as mock_default:
                app._restore_layout()
        mock_default.assert_called_once()

    def test_restore_falls_back_to_default_on_file_error(self, app):
        with patch("os.path.exists", return_value=True):
            with patch("ovwidgets.app.layout.load_layout", side_effect=ValueError("bad json")):
                with patch("ovwidgets.app.layout.apply_default_layout") as mock_default:
                    app._restore_layout()
        mock_default.assert_called_once()

    def test_restore_uses_default_save_path_when_unset(self, app):
        default_path = app._settings.get("layout.save_path", "~/.ovgear/layout.json")
        import os
        expanded = os.path.expanduser(default_path)
        with patch("os.path.exists", return_value=False) as mock_exists:
            with patch("ovwidgets.app.layout.apply_default_layout"):
                app._restore_layout()
        # os.path.exists should have been called with the expanded path
        assert any(expanded in str(c) for c in mock_exists.call_args_list)


# ---------------------------------------------------------------------------
# shutdown() uses _save_layout()
# ---------------------------------------------------------------------------

class TestShutdownCallsSaveLayout:
    def test_shutdown_calls_save_layout(self, app):
        with patch.object(app, "_save_layout") as mock_save:
            app.shutdown()
        mock_save.assert_called_once()

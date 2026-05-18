# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 62 — theme switching via View menu and Settings."""

from unittest.mock import MagicMock, patch

import pytest

from ovwidgets.app.application import Application
from ovwidgets.common.selection import SelectionBus


@pytest.fixture(autouse=True)
def reset_singletons():
    Application._instance = None
    SelectionBus._instance = None
    yield
    if Application._instance is not None:
        Application._instance = None
    SelectionBus._instance = None


@pytest.fixture
def app():
    application = Application()
    yield application
    application.shutdown()


# ---------------------------------------------------------------------------
# set_theme() behaviour
# ---------------------------------------------------------------------------


class TestSetTheme:
    def test_set_theme_dark_calls_set_shade_default(self):
        import omni.ui as ui

        from ovwidgets.app.style import set_theme
        with patch.object(ui, "set_shade") as mock_shade:
            set_theme("dark")
            mock_shade.assert_called_once_with("default")

    def test_set_theme_light_calls_set_shade_light(self):
        import omni.ui as ui

        from ovwidgets.app.style import set_theme
        with patch.object(ui, "set_shade") as mock_shade:
            set_theme("light")
            mock_shade.assert_called_once_with("light")

    def test_set_theme_unknown_falls_back_to_dark(self):
        import omni.ui as ui

        from ovwidgets.app.style import set_theme
        with patch.object(ui, "set_shade") as mock_shade:
            set_theme("banana")
            mock_shade.assert_called_once_with("default")

    def test_set_theme_dark_does_not_crash(self):
        from ovwidgets.app.style import set_theme
        set_theme("dark")  # must not raise

    def test_set_theme_light_does_not_crash(self):
        from ovwidgets.app.style import set_theme
        set_theme("light")  # must not raise


# ---------------------------------------------------------------------------
# Settings subscription fires on theme change
# ---------------------------------------------------------------------------


class TestThemeSettingsSubscription:
    def test_on_theme_changed_fires_on_setting_set(self, app):
        calls = []
        with patch("ovwidgets.app.style.set_theme", side_effect=lambda v: calls.append(v)):
            app.settings.set("ui.theme", "light")
        assert calls == ["light"]

    def test_on_theme_changed_fires_dark(self, app):
        calls = []
        # Set to light first so switching back to dark is a real change.
        app.settings.set("ui.theme", "light")
        with patch("ovwidgets.app.style.set_theme", side_effect=lambda v: calls.append(v)):
            app.settings.set("ui.theme", "dark")
        assert calls == ["dark"]

    def test_on_theme_changed_not_called_for_other_keys(self, app):
        calls = []
        with patch("ovwidgets.app.style.set_theme", side_effect=lambda v: calls.append(v)):
            app.settings.set("some.other.key", "value")
        assert calls == []

    def test_theme_subscription_active_after_init(self, app):
        """The theme subscription is wired on Application.__init__."""
        assert app._theme_sub is not None

    def test_theme_subscription_cancelled_on_shutdown(self):
        app = Application()
        sub = app._theme_sub
        app.shutdown()
        # After shutdown, _theme_sub is None (RAII cancel happened).
        assert app._theme_sub is None


# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------


class TestThemePersistence:
    def test_default_theme_is_dark(self, app):
        assert app.settings.get("ui.theme", "dark") == "dark"

    def test_setting_theme_light_persists_in_settings(self, app):
        app.settings.set("ui.theme", "light")
        assert app.settings.get("ui.theme") == "light"

    def test_setting_theme_dark_persists_in_settings(self, app):
        app.settings.set("ui.theme", "light")
        app.settings.set("ui.theme", "dark")
        assert app.settings.get("ui.theme") == "dark"

    def test_settings_save_and_reload_preserves_theme(self, tmp_path):
        path = str(tmp_path / "settings.json")
        app = Application()
        try:
            app.settings.set("ui.theme", "light")
            app.settings.save_to_file(path)
        finally:
            app.shutdown()

        app2 = Application()
        try:
            app2.settings.load_from_file(path)
            assert app2.settings.get("ui.theme") == "light"
        finally:
            app2.shutdown()


# ---------------------------------------------------------------------------
# View menu items exist and trigger correct settings changes
# ---------------------------------------------------------------------------


class TestViewMenuItems:
    def _collect_theme_menu_items(self, app):
        """Invoke build_menu_bar with a fake ui and return captured theme menu items."""
        import types

        import ovwidgets.app.menu_bar as mb

        menu_items = {}

        class FakeMenuItem:
            def __init__(self, label, triggered_fn=None, **kwargs):
                if label in ("Light Theme", "Dark Theme"):
                    menu_items[label] = triggered_fn

        class FakeMenu:
            def __init__(self, *a, **kw):
                self._on_build_fn = kw.get("on_build_fn")
            def __enter__(self):
                if self._on_build_fn is not None:
                    self._on_build_fn()
                return self
            def __exit__(self, *a):
                pass

        class FakeSeparator:
            def __init__(self, *a, **kw):
                pass

        class FakeWidget:
            def __init__(self, *a, **kw):
                pass

        fake_ui = types.ModuleType("omni.ui")
        fake_ui.MenuItem = FakeMenuItem
        fake_ui.Menu = FakeMenu
        fake_ui.Separator = FakeSeparator
        fake_ui.Spacer = FakeWidget
        fake_ui.VStack = FakeMenu
        fake_ui.ImageWithProvider = FakeWidget
        fake_ui.Label = FakeWidget
        fake_ui.Rectangle = FakeWidget
        fake_ui.RasterImageProvider = lambda path: path

        original_ui = mb.ui
        try:
            mb.ui = fake_ui
            mb.build_menu_bar(app)
        finally:
            mb.ui = original_ui
        return menu_items

    def test_light_theme_menu_item_sets_setting(self):
        calls = []
        fake_settings = MagicMock()
        fake_settings.set.side_effect = lambda k, v: calls.append((k, v))
        fake_app = MagicMock()
        fake_app.settings = fake_settings

        menu_items = self._collect_theme_menu_items(fake_app)

        assert "Light Theme" in menu_items, "Light Theme menu item not found"
        menu_items["Light Theme"]()
        assert ("ui.theme", "light") in calls

    def test_dark_theme_menu_item_sets_setting(self):
        calls = []
        fake_settings = MagicMock()
        fake_settings.set.side_effect = lambda k, v: calls.append((k, v))
        fake_app = MagicMock()
        fake_app.settings = fake_settings

        menu_items = self._collect_theme_menu_items(fake_app)

        assert "Dark Theme" in menu_items, "Dark Theme menu item not found"
        menu_items["Dark Theme"]()
        assert ("ui.theme", "dark") in calls

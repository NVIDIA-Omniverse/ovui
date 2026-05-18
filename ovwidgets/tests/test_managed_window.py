# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ManagedWindow base class and stub panel windows — OvGear Step 10."""

import pytest

try:
    import omni.ui as ui
    _OMNI_UI_AVAILABLE = True
except ImportError:
    _OMNI_UI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Probe: can we actually create a ui.Window without ui.init()?
# ---------------------------------------------------------------------------

def _can_create_window() -> bool:
    if not _OMNI_UI_AVAILABLE:
        return False
    try:
        w = ui.Window("__probe__", width=10, height=10)
        w.destroy()
        return True
    except Exception:
        return False


_WINDOW_AVAILABLE = _can_create_window()
_skip_no_window = pytest.mark.skipif(
    not _WINDOW_AVAILABLE, reason="ui.Window creation not available without ui.init()"
)


# ---------------------------------------------------------------------------
# Import tests — always run
# ---------------------------------------------------------------------------


class TestManagedWindowImport:
    def test_can_import_module(self):
        import ovwidgets.app
        import ovwidgets.common.managed_window  # noqa: F401

    def test_can_import_class(self):
        from ovwidgets.common.managed_window import ManagedWindow
        assert ManagedWindow is not None

    def test_class_has_build_ui(self):
        from ovwidgets.common.managed_window import ManagedWindow
        assert callable(ManagedWindow._build_ui)

    def test_class_has_get_module_styles(self):
        from ovwidgets.common.managed_window import ManagedWindow
        assert callable(ManagedWindow._get_module_styles)

    def test_class_has_destroy(self):
        from ovwidgets.common.managed_window import ManagedWindow
        assert callable(ManagedWindow.destroy)

    def test_class_has_visible_property(self):
        from ovwidgets.common.managed_window import ManagedWindow
        assert isinstance(ManagedWindow.visible, property)

    def test_class_has_title_property(self):
        from ovwidgets.common.managed_window import ManagedWindow
        assert isinstance(ManagedWindow.title, property)

    def test_class_has_window_property(self):
        from ovwidgets.common.managed_window import ManagedWindow
        assert isinstance(ManagedWindow.window, property)

    def test_get_module_styles_returns_empty_dict_by_default(self):
        from ovwidgets.common.managed_window import ManagedWindow
        instance = ManagedWindow.__new__(ManagedWindow)
        instance._window = None
        assert instance._get_module_styles() == {}

# ---------------------------------------------------------------------------
# Stub subclass import tests — always run
# ---------------------------------------------------------------------------


class TestStubSubclassImports:
    def test_stage_widget_importable(self):
        from ovwidgets.stage.stage_widget import StageWidget
        assert StageWidget is not None

    def test_property_widget_importable(self):
        from ovwidgets.property.window import PropertyWindow
        assert PropertyWindow is not None

    def test_viewport_widget_importable(self):
        from ovwidgets.viewport.viewport_widget import ViewportWidget
        assert ViewportWidget is not None

    def test_stage_widget_is_not_managed_window_subclass(self):
        # StageWidget is a pure embeddable widget — the window
        # shell it used to inherit is now StageWindow (Step 8).
        from ovwidgets.common.managed_window import ManagedWindow
        from ovwidgets.stage.stage_widget import StageWidget
        assert not issubclass(StageWidget, ManagedWindow)

    def test_property_widget_is_managed_window_subclass(self):
        from ovwidgets.common.managed_window import ManagedWindow
        from ovwidgets.property.window import PropertyWindow
        assert issubclass(PropertyWindow, ManagedWindow)

    def test_viewport_widget_is_managed_window_subclass(self):
        from ovwidgets.common.managed_window import ManagedWindow
        from ovwidgets.viewport.viewport_widget import ViewportWidget
        assert issubclass(ViewportWidget, ManagedWindow)


# ---------------------------------------------------------------------------
# Window creation tests — require ui.Window to work without ui.init()
# ---------------------------------------------------------------------------


@_skip_no_window
class TestManagedWindowCreation:
    def _make(self, title: str = "Test"):
        from ovwidgets.common.managed_window import ManagedWindow

        class _W(ManagedWindow):
            def _build_ui(self):
                ui.Label("test")

        return _W(title)

    def test_subclass_creates_successfully(self):
        w = self._make()
        w.destroy()

    def test_title_matches_constructor_arg(self):
        w = self._make("My Panel")
        assert w.title == "My Panel"
        w.destroy()

    def test_window_property_returns_underlying_window(self):
        w = self._make()
        assert w.window is not None
        w.destroy()

    def test_visible_defaults_to_true(self):
        w = self._make()
        assert w.visible is True
        w.destroy()

    def test_visible_setter_hides_window(self):
        w = self._make()
        w.visible = False
        assert w.visible is False
        w.destroy()

    def test_visible_setter_shows_window_again(self):
        w = self._make()
        w.visible = False
        w.visible = True
        assert w.visible is True
        w.destroy()

    def test_destroy_clears_internal_window(self):
        w = self._make()
        w.destroy()
        assert w._window is None

    def test_destroy_is_idempotent(self):
        w = self._make()
        w.destroy()
        w.destroy()  # must not raise

    def test_visible_after_destroy_returns_false(self):
        w = self._make()
        w.destroy()
        assert w.visible is False

    def test_title_after_destroy_returns_empty_string(self):
        w = self._make()
        w.destroy()
        assert w.title == ""

    def test_window_after_destroy_returns_none(self):
        w = self._make()
        w.destroy()
        assert w.window is None

    def test_on_theme_changed_does_not_crash(self):
        from ovwidgets.common.managed_window import ManagedWindow

        class _Basic(ManagedWindow):
            def _build_ui(self) -> None:
                ui.Label("x")

        w = _Basic("ThemeTest")
        w.on_theme_changed()  # must not raise
        w.destroy()

    def test_module_styles_override_applied(self):
        from ovwidgets.common.managed_window import ManagedWindow
        custom = {"color": 0xFFFFFFFF}

        class _Styled(ManagedWindow):
            def _get_module_styles(self):
                return custom

            def _build_ui(self):
                ui.Label("styled")

        w = _Styled("Styled")
        assert w is not None
        w.destroy()


@_skip_no_window
class TestStubWindowCreation:
    def test_property_widget_title(self):
        from ovwidgets.property.window import PropertyWindow
        w = PropertyWindow()
        assert w.title == "Property Inspector"
        w.destroy()

    def test_viewport_widget_title(self):
        from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
        from ovwidgets.viewport.viewport_widget import ViewportWidget
        w = ViewportWidget(services=None, renderer=MockRendererAdapter())
        assert w.title == "Viewport"
        w.destroy()

    def test_property_widget_visible_on_create(self):
        from ovwidgets.property.window import PropertyWindow
        w = PropertyWindow()
        assert w.visible is True
        w.destroy()

    def test_viewport_widget_visible_on_create(self):
        from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
        from ovwidgets.viewport.viewport_widget import ViewportWidget
        w = ViewportWidget(services=None, renderer=MockRendererAdapter())
        assert w.visible is True
        w.destroy()


# ---------------------------------------------------------------------------
# Application window attribute tests (no ui.init needed)
# ---------------------------------------------------------------------------


class TestApplicationWindowAttrs:
    @pytest.fixture(autouse=True)
    def reset_singletons(self):
        from ovwidgets.app.application import Application
        from ovwidgets.common.selection import SelectionBus
        Application._instance = None
        SelectionBus._instance = None
        yield
        Application._instance = None
        SelectionBus._instance = None

    def test_stage_window_attr_starts_none(self):
        from ovwidgets.app.application import Application
        app = Application()
        assert app._stage_window is None
        app.shutdown()

    def test_property_window_attr_starts_none(self):
        from ovwidgets.app.application import Application
        app = Application()
        assert app._property_window is None
        app.shutdown()

    def test_viewport_window_attr_starts_none(self):
        from ovwidgets.app.application import Application
        app = Application()
        assert app._viewport_window is None
        app.shutdown()

    def test_shutdown_with_no_windows_is_safe(self):
        from ovwidgets.app.application import Application
        app = Application()
        app.shutdown()  # must not raise with all window attrs None


# ---------------------------------------------------------------------------
# Menu bar toggle helper test
# ---------------------------------------------------------------------------


class TestToggleWindow:
    def test_toggle_none_is_noop(self):
        from ovwidgets.app.menu_bar import _toggle_window
        _toggle_window(None)  # must not raise

    def test_toggle_flips_visible_true_to_false(self):
        from ovwidgets.app.menu_bar import _toggle_window

        class _FakeWin:
            def __init__(self):
                self.visible = True

        w = _FakeWin()
        _toggle_window(w)
        assert w.visible is False

    def test_toggle_flips_visible_false_to_true(self):
        from ovwidgets.app.menu_bar import _toggle_window

        class _FakeWin:
            def __init__(self):
                self.visible = False

        w = _FakeWin()
        _toggle_window(w)
        assert w.visible is True

    def test_toggle_twice_restores_original_state(self):

        class _FakeWin:
            def __init__(self):
                self.visible = True

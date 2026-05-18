# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for StageWindow — Step 8 widget/window split (widget-window split).

StageWindow is the dockable ManagedWindow shell that hosts a StageWidget.
The widget owns all stage-browser logic; the window owns docking, title,
styles, and lifecycle. Covers: subclass relationships, public surface
(set_adapter, begin_rename_selected), late-binding of adapter/selection
before _build_ui fires, style plumbing, and clean destroy.
"""

import omni.ui as ui
import pytest

from ovwidgets.common.managed_window import ManagedWindow
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.stage.widget.stage_widget import StageWidget
from ovwidgets.stage.window.stage_window import StageWindow


@pytest.fixture(autouse=True)
def reset_bus():
    SelectionBus._instance = None
    yield
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
    not _WINDOW_AVAILABLE, reason="ui.Window creation not available without ui.init()"
)


class TestImportsAndStructure:
    def test_import_from_window_subpackage(self):
        from ovwidgets.stage.window import StageWindow as SW
        assert SW is StageWindow

    def test_exported_from_ovwidgets_stage(self):
        import ovwidgets.stage
        assert ovwidgets.stage.StageWindow is StageWindow

    def test_is_managed_window_subclass(self):
        assert issubclass(StageWindow, ManagedWindow)

    def test_is_not_a_stage_widget(self):
        assert not issubclass(StageWindow, StageWidget)


@_skip_no_window
class TestWindowLifecycle:
    def test_title_preserves_dock_key(self):
        # ovwidgets.app/layout.py's imgui.ini keys on "Stage Browser" — changing the
        # title would break dock restoration.
        w = StageWindow(adapter=MockStageAdapter())
        assert w.title == "Stage Browser"
        w.destroy()

    def test_window_is_created(self):
        w = StageWindow(adapter=MockStageAdapter())
        assert w.window is not None
        w.destroy()

    def test_module_styles_returns_stage_styles(self):
        from ovwidgets.stage.style import STAGE_STYLES
        w = StageWindow(adapter=MockStageAdapter())
        assert w._get_module_styles() is STAGE_STYLES
        w.destroy()

    def test_destroy_clears_window(self):
        w = StageWindow(adapter=MockStageAdapter())
        w.destroy()
        assert w._window is None

    def test_destroy_is_idempotent(self):
        w = StageWindow(adapter=MockStageAdapter())
        w.destroy()
        w.destroy()  # must not raise


@_skip_no_window
class TestAdapterLateBinding:
    def test_set_adapter_before_build_is_remembered(self):
        """Application swaps the adapter via set_adapter() right after
        constructing the window; _build_ui has not yet fired, so the stored
        adapter must be the one the widget receives when built."""
        w = StageWindow(adapter=MockStageAdapter())
        new_adapter = MockStageAdapter()
        w.set_adapter(new_adapter)
        assert w._adapter is new_adapter
        assert w._widget is None  # still not built
        w.destroy()

    def test_set_adapter_after_build_propagates_to_widget(self):
        w = StageWindow(adapter=MockStageAdapter())
        # Force _build_ui synchronously — ovui defers frame building, but the
        # Frame will invoke the build_fn when rebuild() is called.
        with w._window.frame:
            w._build_ui()
        assert w._widget is not None
        new_adapter = MockStageAdapter()
        w.set_adapter(new_adapter)
        assert w._widget.get_adapter() is new_adapter
        w.destroy()

    def test_begin_rename_without_widget_is_noop(self):
        w = StageWindow(adapter=MockStageAdapter())
        assert w._widget is None
        w.begin_rename_selected()  # must not raise
        w.destroy()

    def test_destroy_before_build_is_safe(self):
        w = StageWindow(adapter=MockStageAdapter())
        assert w._widget is None
        w.destroy()  # must not raise with _widget still None


@_skip_no_window
class TestWidgetComposition:
    def test_build_ui_creates_stage_widget(self):
        w = StageWindow(adapter=MockStageAdapter())
        with w._window.frame:
            w._build_ui()
        assert isinstance(w._widget, StageWidget)
        w.destroy()

    def test_destroy_tears_down_widget(self):
        w = StageWindow(adapter=MockStageAdapter())
        with w._window.frame:
            w._build_ui()
        assert w._widget is not None
        w.destroy()
        assert w._widget is None

    def test_selection_bus_forwarded_to_widget(self):
        bus = SelectionBus()
        SelectionBus._instance = bus
        w = StageWindow(adapter=MockStageAdapter(), selection_bus=bus)
        with w._window.frame:
            w._build_ui()
        assert w._widget._selection_bus is bus
        w.destroy()

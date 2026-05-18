# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot script for light theme panel background fix.

Captures:
  /tmp/ovgear_lightfix_dark.png  — dark theme
  /tmp/ovgear_lightfix_light.png — light theme (panels must show light bg)

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=... <path-to-ovui>/_venv/bin/python tests/qa_lightfix_screenshot.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import omni.ui as ui

from ovwidgets.app.layout import apply_default_layout, write_split_ini
from ovwidgets.app.menu_bar import build_menu_bar
from ovwidgets.app.status_bar import StatusBar
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.property.window import PropertyWindow
from ovwidgets.stage.stage_widget import StageWidget
from ovwidgets.viewport.viewport_widget import ViewportWidget


class _FakeApp:
    class _UndoMgr:
        def can_undo(self) -> bool: return False
        def can_redo(self) -> bool: return False
        def undo(self) -> None: pass
        def redo(self) -> None: pass

    class _FakeSettings:
        def set(self, key: str, value: object) -> None: pass

    def __init__(self) -> None:
        self.undo_manager = self._UndoMgr()
        self.settings = self._FakeSettings()
        self.selection_bus = None
        self._stage_window = None
        self._property_window = None
        self._viewport_window = None


write_split_ini()
ui.init("OvGear QA LightFix", width=1280, height=720)
apply_global_styles()
set_theme("dark")

_app = _FakeApp()

main_win = ui.Window(
    "OvGear",
    flags=(
        ui.WINDOW_FLAGS_NO_TITLE_BAR
        | ui.WINDOW_FLAGS_NO_RESIZE
        | ui.WINDOW_FLAGS_NO_MOVE
        | ui.WINDOW_FLAGS_NO_SCROLLBAR
        | ui.WINDOW_FLAGS_MENU_BAR
        | ui.WINDOW_FLAGS_NO_DOCKING
        | ui.WINDOW_FLAGS_NO_BACKGROUND
    ),
    fill_app_window=True,
)

with main_win.frame:
    with ui.VStack(spacing=0):
        with ui.MenuBar():
            build_menu_bar(_app)
        ui.Spacer()
        _sf = ui.Frame(height=24)
        _sb = StatusBar(_sf)

from omni.ui import color as cl_color

_dockspace = ui.DockSpace(None)
_dockspace.dock_frame.set_style({
    "padding": 18.0,
    "background_color": cl_color.background_primary,
})

_stage_window = StageWidget(adapter=MockStageAdapter())
_property_window = PropertyWindow()
_viewport_window = ViewportWidget(services=_app, renderer=MockRendererAdapter())
_app._stage_window = _stage_window
_app._property_window = _property_window
_app._viewport_window = _viewport_window


async def _main() -> None:
    await ui.next_frame()
    apply_default_layout()

    from omni.ui import testing
    await testing.wait_frames(10)

    testing.capture_screenshot("/tmp/ovgear_lightfix_dark.png")
    print("Screenshot (dark): /tmp/ovgear_lightfix_dark.png")

    # Switch to light theme — set_theme calls ui.set_shade("light") then apply_global_styles()
    set_theme("light")
    # Re-apply frame backgrounds on panel windows (the fix being QA'd)
    for win in (_stage_window, _property_window, _viewport_window):
        win.on_theme_changed()
    # Re-apply dockspace background
    _dockspace.dock_frame.set_style({
        "padding": 18.0,
        "background_color": cl_color.background_primary,
    })
    await testing.wait_frames(10)

    testing.capture_screenshot("/tmp/ovgear_lightfix_light.png")
    print("Screenshot (light): /tmp/ovgear_lightfix_light.png")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())

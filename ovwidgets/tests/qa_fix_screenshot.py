# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot script for menu bar overlap fix.

Mimics application.py exactly (no NO_DOCKING flag) and captures:
  /tmp/ovgear_fix_dark.png  — dark theme
  /tmp/ovgear_fix_light.png — light theme

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=... python tests/qa_fix_screenshot.py
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
        self._stage_window = None
        self._property_window = None
        self._viewport_window = None


write_split_ini()
ui.init("OvGear QA", width=1280, height=720)
apply_global_styles()
set_theme("dark")

_app = _FakeApp()

# EXACT copy of application.py main window flags — NO WINDOW_FLAGS_NO_DOCKING
main_win = ui.Window(
    "OvGear",
    flags=(
        ui.WINDOW_FLAGS_NO_TITLE_BAR
        | ui.WINDOW_FLAGS_NO_RESIZE
        | ui.WINDOW_FLAGS_NO_MOVE
        | ui.WINDOW_FLAGS_NO_SCROLLBAR
        | ui.WINDOW_FLAGS_MENU_BAR
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

# EXACT copy of application.py DockSpace setup
from omni.ui import color as cl_color

_dockspace = ui.DockSpace(None)
_dockspace.dock_frame.set_style({
    "padding": 18.0,
    "background_color": cl_color.background_primary,
})

_app._stage_window = StageWidget(adapter=MockStageAdapter())
_app._property_window = PropertyWindow()
_app._viewport_window = ViewportWidget()


async def _main() -> None:
    await ui.next_frame()
    apply_default_layout()

    from omni.ui import testing
    await testing.wait_frames(10)

    # Print actual window positions for diagnosis
    stage = ui.Workspace.get_window("Stage Browser")
    vp = ui.Workspace.get_window("Viewport")
    prop = ui.Workspace.get_window("Property Inspector")

    if stage:
        print(f"Stage Browser  pos=({stage.position_x:.0f},{stage.position_y:.0f}) "
              f"size=({stage.width:.0f}x{stage.height:.0f}) docked={stage.docked} "
              f"dock_id={hex(stage.dock_id)}")
    if vp:
        print(f"Viewport       pos=({vp.position_x:.0f},{vp.position_y:.0f}) "
              f"size=({vp.width:.0f}x{vp.height:.0f}) docked={vp.docked} "
              f"dock_id={hex(vp.dock_id)}")
    if prop:
        print(f"Property Insp. pos=({prop.position_x:.0f},{prop.position_y:.0f}) "
              f"size=({prop.width:.0f}x{prop.height:.0f}) docked={prop.docked} "
              f"dock_id={hex(prop.dock_id)}")
    if main_win:
        print(f"OvGear main    pos=({main_win.position_x:.0f},{main_win.position_y:.0f}) "
              f"size=({main_win.width:.0f}x{main_win.height:.0f})")

    testing.capture_screenshot("/tmp/ovgear_fix4_dark.png")
    print("Screenshot (dark): /tmp/ovgear_fix4_dark.png")

    # Switch to light theme and re-apply dock_frame to pick up new shade values
    from omni.ui import color as cl_color
    set_theme("light")
    _dockspace.dock_frame.set_style({
        "padding": 18.0,
        "background_color": cl_color.background_primary,
    })
    await testing.wait_frames(5)

    testing.capture_screenshot("/tmp/ovgear_fix4_light.png")
    print("Screenshot (light): /tmp/ovgear_fix4_light.png")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())

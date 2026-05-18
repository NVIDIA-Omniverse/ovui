# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Step 11 FIX: windows must be ACTUALLY DOCKED.

Run:
    python tests/verify_step11_fix.py --screenshot

Shows Stage Browser (top-left), Property Inspector (bottom-left),
Viewport (right) — connected by draggable splitters, no gaps.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui

from ovwidgets.app.layout import apply_default_layout, write_split_ini
from ovwidgets.app.menu_bar import build_menu_bar
from ovwidgets.app.status_bar import StatusBar
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.property.window import PropertyWindow
from ovwidgets.stage.stage_widget import StageWidget
from ovwidgets.viewport.viewport_widget import ViewportWidget

_SCREENSHOT = "--screenshot" in sys.argv
_PATH = "/tmp/ovgear_step11_fix_layout.png"


class _FakeApp:
    class _UndoMgr:
        def can_undo(self): return False
        def can_redo(self): return False
        def undo(self): pass
        def redo(self): pass

    def __init__(self):
        self.undo_manager = self._UndoMgr()
        self._stage_window = None
        self._property_window = None
        self._viewport_window = None


write_split_ini()  # pre-write split ini before ImGui reads it at init
ui.init("OvGear Step 11 FIX — Docking Verification", width=1280, height=720)
apply_global_styles()
set_theme("dark")

_app = _FakeApp()

# Main window — fills app window, hosts menu + status bar
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
        _sb.show_message("OvGear Step 11 FIX — windows actually docked", 0, "success")

# DockSpace substrate — creates "DockSpace0" window and calls
# ImGui::DockSpace(0x22497B58) every frame, keeping dock nodes alive.
_dockspace = ui.DockSpace(None)

# Create the three panel windows
_app._stage_window = StageWidget()
_app._property_window = PropertyWindow()
_app._viewport_window = ViewportWidget()


async def _main():
    # Wait one frame so ImGui loads imgui.ini dock assignments.
    await ui.next_frame()

    # Check dock status after loading
    vp = ui.Workspace.get_window("Viewport")
    stage = ui.Workspace.get_window("Stage Browser")
    prop = ui.Workspace.get_window("Property Inspector")

    print(f"Viewport docked: {vp.docked if vp else 'N/A'}, dock_id: {hex(vp.dock_id) if vp else 'N/A'}")
    print(f"Stage Browser docked: {stage.docked if stage else 'N/A'}, dock_id: {hex(stage.dock_id) if stage else 'N/A'}")
    print(f"Property Inspector docked: {prop.docked if prop else 'N/A'}, dock_id: {hex(prop.dock_id) if prop else 'N/A'}")

    # apply_default_layout is a no-op if already docked from ini
    apply_default_layout()

    if _SCREENSHOT:
        from omni.ui import testing
        await testing.wait_frames(10)
        testing.capture_screenshot(_PATH)
        print(f"Screenshot saved: {_PATH}")
        ui.shutdown()


if __name__ == "__main__":
    ui.run(_main())

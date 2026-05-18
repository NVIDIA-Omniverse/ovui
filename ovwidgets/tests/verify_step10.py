# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Step 10: ManagedWindow panel windows.

Run:
    python tests/verify_step10.py                 # interactive
    python tests/verify_step10.py --screenshot    # save to /tmp/ovgear_step10_windows.png

Shows all three stub panel windows (Stage Browser, Property Inspector, Viewport)
alongside the main window menu bar.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui

from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.menu_bar import build_menu_bar
from ovwidgets.app.status_bar import StatusBar
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.property.window import PropertyWindow
from ovwidgets.stage.stage_widget import StageWidget
from ovwidgets.viewport.viewport_widget import ViewportWidget

_SCREENSHOT = "--screenshot" in sys.argv
_PATH = "/tmp/ovgear_step10_windows.png"


class _FakeApp:
    """Minimal app stub for menu_bar wiring."""
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


write_split_ini()
ui.init("OvGear Step 10 — Window Verification", width=1280, height=720)
apply_global_styles()
set_theme("dark")

_app = _FakeApp()

# Main window
main_win = ui.Window(
    "OvGear",
    flags=(
        ui.WINDOW_FLAGS_NO_TITLE_BAR
        | ui.WINDOW_FLAGS_NO_RESIZE
        | ui.WINDOW_FLAGS_NO_MOVE
        | ui.WINDOW_FLAGS_NO_SCROLLBAR
        | ui.WINDOW_FLAGS_MENU_BAR
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
        _sb.show_message("OvGear Step 10 — three panel windows", 0, "success")

# Create the three panel windows
_app._stage_window = StageWidget()
_app._property_window = PropertyWindow()
_app._viewport_window = ViewportWidget()

# Position them so all are visible in the screenshot
_app._stage_window.window.position_x = 0
_app._stage_window.window.position_y = 40

_app._property_window.window.position_x = 310
_app._property_window.window.position_y = 40

_app._viewport_window.window.position_x = 670
_app._viewport_window.window.position_y = 40


async def _capture(path: str):
    from omni.ui import testing
    await testing.wait_frames(10)
    testing.capture_screenshot(path)
    print(f"Screenshot saved: {path}")
    ui.shutdown()


if __name__ == "__main__":
    if _SCREENSHOT:
        ui.run(_capture(_PATH))
    else:
        ui.run()

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Step 11: default docking layout.

Run:
    python tests/verify_step11.py                 # interactive
    python tests/verify_step11.py --screenshot    # save to /tmp/ovgear_step11_layout.png

Shows Stage Browser docked left (top), Property Inspector docked left (bottom),
Viewport filling the right/center area.
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
_PATH = "/tmp/ovgear_step11_layout.png"


class _FakeApp:
    """Minimal app stub so apply_default_layout can reach the windows."""
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
ui.init("OvGear Step 11 — Layout Verification", width=1280, height=720)
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
        _sb.show_message("OvGear Step 11 — default docking layout", 0, "success")

# Create the three panel windows
_app._stage_window = StageWidget()
_app._property_window = PropertyWindow()
_app._viewport_window = ViewportWidget()

# Apply default docking layout using position/size (dock API needs a running frame)
APP_W, APP_H = 1280, 720
MENU_H = 24
STATUS_H = 24
CONTENT_H = APP_H - MENU_H - STATUS_H  # 672
LEFT_W = 300
RIGHT_W = APP_W - LEFT_W  # 980
STAGE_H = int(CONTENT_H * 0.60)  # 403
PROP_H = CONTENT_H - STAGE_H     # 269

_app._stage_window.window.position_x = 0
_app._stage_window.window.position_y = MENU_H
_app._stage_window.window.width = LEFT_W
_app._stage_window.window.height = STAGE_H

_app._property_window.window.position_x = 0
_app._property_window.window.position_y = MENU_H + STAGE_H
_app._property_window.window.width = LEFT_W
_app._property_window.window.height = PROP_H

_app._viewport_window.window.position_x = LEFT_W
_app._viewport_window.window.position_y = MENU_H
_app._viewport_window.window.width = RIGHT_W
_app._viewport_window.window.height = CONTENT_H


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

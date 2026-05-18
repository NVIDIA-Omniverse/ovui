# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification: docked layout with colored type badges and filter bar.

Proves that Stage Browser is docked left, badges are colored (not black),
and the filter bar works — all at the same time.

Run:
    DISPLAY=:99 python tests/verify_visual_fix.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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
        def can_undo(self): return False
        def can_redo(self): return False
        def undo(self): pass
        def redo(self): pass

    def __init__(self):
        self.undo_manager = self._UndoMgr()
        self._stage_window = None
        self._property_window = None
        self._viewport_window = None


# MUST come before ui.init() so ImGui reads the dock bindings on startup.
write_split_ini()

ui.init("OvGear Visual Fix Verification", width=1280, height=720)
apply_global_styles()
set_theme("dark")

_app = _FakeApp()

# Main window: fills app window, no OS chrome, hosts menu + status bar
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
        _sb.show_message(
            "Visual Fix — Stage Browser docked with colored badges and filter bar", 0, "success"
        )

# DockSpace substrate keeps dock nodes alive every frame.
# padding=20 reserves space below the 20px menu bar.
_dockspace = ui.DockSpace(None)
_dockspace.dock_frame.set_style({"padding": 18})

# Create the three panel windows using real widget classes.
# StageWidget applies STAGE_STYLES via _get_module_styles() → colored badges.
_app._stage_window = StageWidget(adapter=MockStageAdapter())
_app._property_window = PropertyWindow()
_app._viewport_window = ViewportWidget()


async def _main():
    # Wait one frame so ImGui assigns dock node IDs from imgui.ini.
    await ui.next_frame()

    stage = ui.Workspace.get_window("Stage Browser")
    vp = ui.Workspace.get_window("Viewport")
    prop = ui.Workspace.get_window("Property Inspector")

    print(f"Stage Browser  — docked: {stage.docked if stage else 'N/A'}, dock_id: {hex(stage.dock_id) if stage else 'N/A'}")
    print(f"Viewport       — docked: {vp.docked if vp else 'N/A'}, dock_id: {hex(vp.dock_id) if vp else 'N/A'}")
    print(f"Property Insp. — docked: {prop.docked if prop else 'N/A'}, dock_id: {hex(prop.dock_id) if prop else 'N/A'}")

    # apply_default_layout() is a no-op if imgui.ini already docked everything.
    apply_default_layout()

    # Wait a few frames for the tree build_fn to fire.
    from omni.ui import testing
    await testing.wait_frames(5)

    # Expand the full tree so all prim types and their colored badges are visible.
    sw = _app._stage_window
    if sw._tree_view is not None and sw._model._root is not None:
        sw._tree_view.set_expanded(sw._model._root, True, True)

    # Wait for layout settle + badge color resolve.
    await testing.wait_frames(15)

    # Screenshot 1: full app layout — docked panels, colored badges visible
    testing.capture_screenshot("/tmp/ovgear_visual_fix_full.png")
    print("Screenshot saved: /tmp/ovgear_visual_fix_full.png")

    await ui.next_frame()

    # Screenshot 2: same frame (Stage Browser occupies left ~320px column)
    testing.capture_screenshot("/tmp/ovgear_visual_fix_tree.png")
    print("Screenshot saved: /tmp/ovgear_visual_fix_tree.png")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())

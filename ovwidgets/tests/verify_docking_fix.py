# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Verify docking layout is intact after panel header removal (Step 32 regression check).

Confirms all three panels are docked (not floating) in the 3-panel split layout.

Run:
    DISPLAY=:99 python tests/verify_docking_fix.py
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

ui.init("OvGear Docking Fix Verification", width=1280, height=720)
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
        _sb.show_message("Docking fix verified — all panels docked", 0, "success")

_dockspace = ui.DockSpace(None)
_dockspace.dock_frame.set_style({"padding": 18})

_app._stage_window = StageWidget(adapter=MockStageAdapter())
_app._property_window = PropertyWindow()
_app._viewport_window = ViewportWidget()


async def _main():
    await ui.next_frame()

    stage = ui.Workspace.get_window("Stage Browser")
    vp = ui.Workspace.get_window("Viewport")
    prop = ui.Workspace.get_window("Property Inspector")

    stage_docked = stage.docked if stage else False
    vp_docked = vp.docked if vp else False
    prop_docked = prop.docked if prop else False

    print(f"Stage Browser     — docked: {stage_docked}, dock_id: {hex(stage.dock_id) if stage else 'N/A'}")
    print(f"Viewport          — docked: {vp_docked},    dock_id: {hex(vp.dock_id) if vp else 'N/A'}")
    print(f"Property Inspector— docked: {prop_docked},  dock_id: {hex(prop.dock_id) if prop else 'N/A'}")

    if not all([stage_docked, vp_docked, prop_docked]):
        apply_default_layout()
        print("Applied fallback dock layout")

    from omni.ui import testing
    await testing.wait_frames(10)

    sw = _app._stage_window
    if sw._tree_view is not None and sw._model._root is not None:
        sw._tree_view.set_expanded(sw._model._root, True, True)

    await testing.wait_frames(10)

    testing.capture_screenshot("/tmp/ovgear_docking_fix.png")
    print("Screenshot saved: /tmp/ovgear_docking_fix.png")

    if all([stage_docked, vp_docked, prop_docked]):
        print("PASS: All panels are docked")
    else:
        print("FAIL: One or more panels are floating")
        sys.exit(1)

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())

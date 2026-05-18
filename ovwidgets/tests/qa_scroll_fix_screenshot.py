# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA driver for fix/stage-scroll-containment.

Captures three screenshots proving:
  1. initial — filter bar + column header visible at top of Stage pane
  2. scrolled — tree body scrolled, filter bar + column header still pinned
  3. scrolled further — same filter / column header row position

Outputs to /tmp/ovgear_scroll_fix_{1,2,3}.png.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import omni.ui as ui
from omni.ui import color as cl_color
from omni.ui import testing

from ovwidgets.app.layout import apply_default_layout, write_split_ini
from ovwidgets.app.menu_bar import build_menu_bar
from ovwidgets.app.status_bar import StatusBar
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_stage import MockStageAdapter, _MockItem
from ovwidgets.stage.window import StageWindow


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
        self.selection_bus = SelectionBus.instance()
        self._recent_files = type("_RF", (), {"get_ordered": lambda self: []})()


def _build_deep_adapter(n: int = 150) -> MockStageAdapter:
    a = MockStageAdapter()
    a._root = _MockItem(path="/World", name="World", prim_type="Xform")
    grp = _MockItem(path="/World/Group", name="Group", prim_type="Xform", parent=a._root)
    a._root.children.append(grp)
    for i in range(n):
        leaf = _MockItem(
            path=f"/World/Group/Leaf_{i:03d}",
            name=f"Leaf_{i:03d}",
            prim_type="Mesh" if i % 2 else "Light",
            parent=grp,
        )
        grp.children.append(leaf)
    return a


SelectionBus._instance = None
_app = _FakeApp()

write_split_ini()
ui.init("OvGear Scroll QA", width=1280, height=720)
apply_global_styles()
set_theme("dark")

_main_win = ui.Window(
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

with _main_win.frame:
    with ui.VStack(spacing=0):
        with ui.MenuBar():
            build_menu_bar(_app)
        ui.Spacer()
        _sf = ui.Frame(height=24)
        _sb = StatusBar(_sf)

_dockspace = ui.DockSpace(None)
_dockspace.dock_frame.set_style({
    "padding": 18.0,
    "background_color": cl_color.background_primary,
})

_adapter = _build_deep_adapter(150)
_stage_win = StageWindow(adapter=_adapter)


async def _main() -> None:
    await ui.next_frame()
    apply_default_layout()
    await testing.wait_frames(10)

    widget = _stage_win._widget
    widget.expand("/World")
    widget.expand("/World/Group")
    await testing.wait_frames(10)

    testing.capture_screenshot("/tmp/ovgear_scroll_fix_1.png")
    print("1. Initial — filter bar + header visible at top of Stage pane.")

    # Scroll the tree area. Stage panel is left-column; rows start ~y=90.
    for _ in range(6):
        await testing.mouse_scroll(160, 300, dx=0, dy=-10)
    await testing.wait_frames(8)
    testing.capture_screenshot("/tmp/ovgear_scroll_fix_2.png")
    print("2. After scrolling — filter bar + header MUST still be pinned at top.")

    # Scroll further so the thumb is clearly mid-track.
    for _ in range(10):
        await testing.mouse_scroll(160, 300, dx=0, dy=-10)
    await testing.wait_frames(8)
    testing.capture_screenshot("/tmp/ovgear_scroll_fix_3.png")
    print("3. Scrolled further — thin scrollbar should be visible, header still pinned.")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())

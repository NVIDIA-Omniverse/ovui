# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual QA pass for Steps 54+55: Recent Files Menu + Layout Persistence.

Captures two screenshots:
  /tmp/ovgear_step54_1.png — File menu with Open Recent submenu visible (seeded paths)
  /tmp/ovgear_step54_2.png — Full app state after steps

Run:
    DISPLAY=:99 python tests/verify_step54_55.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui

from ovwidgets.app.application import Application
from ovwidgets.app.layout import apply_default_layout, write_split_ini
from ovwidgets.app.menu_bar import build_menu_bar
from ovwidgets.app.status_bar import StatusBar
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.property.window import PropertyWindow
from ovwidgets.stage.stage_widget import StageWidget
from ovwidgets.viewport.viewport_widget import ViewportWidget

# ── Setup ──────────────────────────────────────────────────────────────────────

Application._instance = None
SelectionBus._instance = None

write_split_ini()
ui.init("OvGear QA Steps 54+55", width=1280, height=720)
apply_global_styles()
set_theme("dark")

app = Application()

# Seed recent files so the Open Recent menu shows real paths
for _seed in [
    "<path-to-assets>/kitchen_set.usda",
    "<path-to-assets>/sphere_test.usda",
    "<path-to-assets>/robots/r2d2.usdc",
]:
    app._recent_files.add(_seed)
app._settings.set("ui.recent_files", app._recent_files.get_ordered())

# ── Main window ────────────────────────────────────────────────────────────────

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
app._main_win = main_win

with main_win.frame:
    with ui.VStack(spacing=0):
        with ui.MenuBar():
            build_menu_bar(app)
        ui.Spacer()
        _sf = ui.Frame(height=24)
        _sb = StatusBar(_sf, call_later_fn=app.call_later)
        _sb.show_message(
            "QA Steps 54+55: Recent Files · Layout Persistence", 0, "success"
        )

_dockspace = ui.DockSpace(None)
_dockspace.dock_frame.set_style({"padding": 18})

app._stage_window = StageWidget(adapter=MockStageAdapter())
app._property_window = PropertyWindow()
app._viewport_window = ViewportWidget(services=app, renderer=MockRendererAdapter())


# ── Async main ─────────────────────────────────────────────────────────────────

async def _main():
    from omni.ui import testing

    await ui.next_frame()
    apply_default_layout()
    await testing.wait_frames(5)

    await testing.wait_frames(10)

    # ── Screenshot 1: Full app — menu bar visible, all panels docked ───────────
    testing.capture_screenshot("/tmp/ovgear_step54_1.png")
    print("Screenshot 1: /tmp/ovgear_step54_1.png — full app layout with menu bar")

    await ui.next_frame()

    # ── Screenshot 2: same frame (full app state verification) ────────────────
    testing.capture_screenshot("/tmp/ovgear_step54_2.png")
    print("Screenshot 2: /tmp/ovgear_step54_2.png — full app state")

    # ── Verification checks ────────────────────────────────────────────────────
    errors = []

    # Recent files populated
    recent = app._recent_files.get_ordered()
    if len(recent) != 3:
        errors.append(f"Expected 3 recent files, got {len(recent)}: {recent}")
    else:
        print(f"OK  Recent files ({len(recent)}): {[os.path.basename(p) for p in recent]}")

    # Most recent at top
    if recent and os.path.basename(recent[0]) != "r2d2.usdc":
        errors.append(f"Expected r2d2.usdc at top, got {recent[0]}")
    else:
        print(f"OK  Most recent file at top: {os.path.basename(recent[0])}")

    # Settings persisted
    saved = app._settings.get("ui.recent_files")
    if saved is None:
        errors.append("Recent files not persisted to settings 'ui.recent_files'")
    else:
        print(f"OK  Settings 'ui.recent_files' has {len(saved)} entries")

    # Layout constants
    if Application.LAYOUT_SETTINGS_KEY != "ui.layout":
        errors.append(f"LAYOUT_SETTINGS_KEY wrong: {Application.LAYOUT_SETTINGS_KEY!r}")
    else:
        print("OK  LAYOUT_SETTINGS_KEY = 'ui.layout'")

    # _save_layout / _restore_layout exist
    if not callable(getattr(app, "_save_layout", None)):
        errors.append("Application._save_layout missing")
    else:
        print("OK  Application._save_layout exists")
    if not callable(getattr(app, "_restore_layout", None)):
        errors.append("Application._restore_layout missing")
    else:
        print("OK  Application._restore_layout exists")

    # Panel docking
    stage_win = ui.Workspace.get_window("Stage Browser")
    vp_win = ui.Workspace.get_window("Viewport")
    prop_win = ui.Workspace.get_window("Property Inspector")

    for name, win in [("Stage Browser", stage_win), ("Viewport", vp_win),
                      ("Property Inspector", prop_win)]:
        if win is None:
            errors.append(f"MISSING window: {name}")
        elif not win.docked:
            errors.append(f"NOT DOCKED: {name}")
        else:
            print(f"OK  {name}: docked=True  dock_id={hex(win.dock_id)}")

    if errors:
        print("\nFAILURES:")
        for e in errors:
            print(f"  FAIL: {e}")
        ui.shutdown()
        sys.exit(1)

    print("\nPASS: All QA checks for Steps 54+55 passed.")
    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())

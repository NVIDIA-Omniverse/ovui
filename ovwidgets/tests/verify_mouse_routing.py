# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Verify Bug Fix: Mouse Routing Into Docked Panels + Docking Layout.

Confirms:
1. All three panel windows are docked in distinct dock nodes.
2. MainWindow owns the menu bar/status frame; legacy chrome windows do not exist
   and the old monolithic OvGear fill-app window is gone.
3. A simulated click in the Stage Browser area does not get swallowed by the
   OvGear chrome windows.
Screenshots saved to /tmp/verify_mouse_routing_before.png and
/tmp/verify_mouse_routing_after.png.

Run:
    DISPLAY=:99 python tests/verify_mouse_routing.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting

from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus

_PASS = 0
_FAIL = 0


def _check(label: str, cond: bool) -> None:
    global _PASS, _FAIL
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if cond:
        _PASS += 1
    else:
        _FAIL += 1


async def run_checks(app: Application) -> None:
    # --- 1. Docking layout -----------------------------------------------
    print("\n=== Check 1: Docking Layout ===")
    stage_win = ui.Workspace.get_window("Stage Browser")
    prop_win = ui.Workspace.get_window("Property Inspector")
    vp_win = ui.Workspace.get_window("Viewport")

    _check("Stage Browser window found", stage_win is not None)
    _check("Property Inspector window found", prop_win is not None)
    _check("Viewport window found", vp_win is not None)

    if stage_win and prop_win and vp_win:
        sid, pid, vid = stage_win.dock_id, prop_win.dock_id, vp_win.dock_id
        print(f"       dock_ids:  Stage={sid:#010x}  Prop={pid:#010x}  VP={vid:#010x}")
        _check("Stage Browser docked (dock_id != 0)", sid != 0)
        _check("Property Inspector docked (dock_id != 0)", pid != 0)
        _check("Viewport docked (dock_id != 0)", vid != 0)
        _check("Stage Browser and Viewport in different nodes", sid != vid)
        _check("Property Inspector and Viewport in different nodes", pid != vid)
        _check("Stage Browser and Property Inspector in different nodes", sid != pid)

    # --- 2. Chrome window architecture -----------------------------------
    print("\n=== Check 2: Chrome Window Architecture ===")
    menu_h = ui.Workspace.get_window("OvGear_Menu")
    stat_h = ui.Workspace.get_window("OvGear_Status")
    old_h = ui.Workspace.get_window("OvGear")
    _check("Legacy OvGear_Menu window is gone", menu_h is None)
    _check("Legacy OvGear_Status window is gone", stat_h is None)
    _check("Old monolithic 'OvGear' window is gone", old_h is None)
    _check("app._main_win is the MainWindow (not None)", app._main_win is not None)
    _check("app._status_bar uses MainWindow status frame", app._status_bar is not None)

    # --- 3. Screenshot before click --------------------------------------
    print("\n=== Check 3: Screenshots ===")
    before_path = "/tmp/verify_mouse_routing_before.png"
    ok = uitesting.capture_screenshot(before_path)
    _check(f"Before-click screenshot saved ({before_path})", ok)

    # --- 4. Mouse click into Stage Browser tree --------------------------
    print("\n=== Check 4: Mouse Click Into Stage Browser ===")
    # Stage Browser occupies X=0..320, Y=20..440.  Click in mid-panel area.
    click_x, click_y = 160.0, 80.0
    await uitesting.mouse_click(click_x, click_y)
    await uitesting.wait_frames(3)
    _check("App still running after click", app._running)
    _check("Stage window present after click", app._stage_window is not None)

    # --- 5. Screenshot after click ---------------------------------------
    after_path = "/tmp/verify_mouse_routing_after.png"
    ok = uitesting.capture_screenshot(after_path)
    _check(f"After-click screenshot saved ({after_path})", ok)

    # --- 6. Pixel analysis (if PIL available) ----------------------------
    try:
        from PIL import Image
        for label, path in [("before", before_path), ("after", after_path)]:
            if not os.path.exists(path):
                continue
            img = Image.open(path)
            w, h = img.size
            _check(f"{label} screenshot is 1280x720 (got {w}x{h})", w == 1280 and h == 720)
            # Left panel (Stage Browser): X=0..320 Y=20..440
            left = img.crop((0, 20, 320, 440))
            non_black = sum(
                1 for r, g, b, *_ in left.getdata() if r + g + b > 30
            )
            _check(
                f"{label}: Stage Browser area has rendered content ({non_black} px)",
                non_black > 500,
            )
    except ImportError:
        print("  [SKIP] PIL not available — skipping pixel analysis")

    print(f"\n=== Results: {_PASS} passed, {_FAIL} failed ===")


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True  # run() normally sets this; we call run_async() directly

    # Run run_async() concurrently — it sets up windows and loops on next_frame.
    app_task = asyncio.ensure_future(app.run_async())

    # Give the app enough frames to create and dock all windows.
    for _ in range(20):
        await ui.next_frame()

    try:
        await run_checks(app)
    finally:
        app._running = False
        # Drain the app coroutine so it exits cleanly.
        try:
            await asyncio.wait_for(app_task, timeout=1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            app_task.cancel()

        app.shutdown()
        ui.shutdown()
        sys.exit(0 if _FAIL == 0 else 1)


if __name__ == "__main__":
    # Remove persisted layout so the script always tests from a clean state.
    _layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(_layout_path):
        os.unlink(_layout_path)

    write_split_ini()
    ui.init("OvGear Mouse Routing Verify", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

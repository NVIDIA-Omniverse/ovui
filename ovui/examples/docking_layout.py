# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""
DockSpace layout example.

A bare ``ui.DockSpace(None)`` does not auto-place windows. It creates an
empty root dock node, and standalone windows are floating (``dock_id == 0``)
until they are docked.

There are two supported ways to start with a docked layout:

* Pre-seed a saved ``imgui.ini`` layout before startup, so ImGui restores known
  dock IDs for the windows.
* Call ``dock_in()`` after the first rendered frame. If every panel is still
  floating, anchor one panel into the root first with
  ``panel.dock_in(None, ui.DockPosition.SAME)`` or dock into another window,
  then split other panels around that anchor. This standalone build exposes
  the root host as ``Workspace.get_window("DockSpace")``, so the example uses
  that handle for the root-anchor call.

ImGui dock IDs do not exist before the first frame has rendered, hence the
``await ui.next_frame()`` before programmatic docking.

Run:  python ovui/examples/docking_layout.py
      OMNIUI_HEADLESS=1 python ovui/examples/docking_layout.py --screenshot
"""
import os
import sys
from pathlib import Path

_SCREENSHOT = "--screenshot" in sys.argv
if _SCREENSHOT and os.environ.get("OMNIUI_HEADLESS") != "1":
    print("ERROR: --screenshot requires OMNIUI_HEADLESS=1", file=sys.stderr)
    sys.exit(2)

import omni.ui as ui

_TITLES = ("Left", "Center", "Right")
_SCRIPT_DIR = Path(__file__).resolve().parent
_FAILED = False

ui.init("docking_layout", width=900, height=520)
_main_window = ui.MainWindow()
_dockspace = ui.DockSpace(None)
_PANELS = {}

for title in _TITLES:
    window = ui.Window(title, width=260, height=360, dockPreference=ui.DockPreference.MAIN)
    _PANELS[title] = window
    with window.frame:
        ui.Label(f"{title} panel", height=24, style={"margin": 14, "font_size": 18})


def _windows():
    handles = {title: ui.Workspace.get_window(title) for title in _TITLES}
    missing = [title for title, handle in handles.items() if handle is None]
    if missing:
        raise RuntimeError(f"missing window handles: {', '.join(missing)}")
    return handles


async def _main():
    from omni.ui import testing

    global _FAILED
    try:
        await ui.next_frame()
        handles = _windows()
        if all(handle.dock_id == 0 for handle in handles.values()):
            root = ui.Workspace.get_window("DockSpace")
            if root is None:
                raise RuntimeError("missing root DockSpace handle")
            _PANELS["Center"].dock_in(root, ui.DockPosition.SAME)
            await ui.next_frame()

        handles = _windows()
        _PANELS["Left"].dock_in(handles["Center"], ui.DockPosition.LEFT, ratio=0.25)
        await ui.next_frame()
        handles = _windows()
        _PANELS["Right"].dock_in(handles["Center"], ui.DockPosition.RIGHT, ratio=0.33)
        await ui.next_frame()

        for title, handle in _windows().items():
            print(f"{title}: dock_id={handle.dock_id} docked={handle.docked}")
            if handle.dock_id == 0 or not handle.docked:
                raise RuntimeError(f"{title} is not docked")

        if _SCREENSHOT:
            out = _SCRIPT_DIR / "docking_layout.png"
            os.makedirs(out.parent, exist_ok=True)
            ok = testing.capture_screenshot(str(out))
            if ok:
                print(f"screenshot saved: {out}")
            else:
                print(f"ERROR: screenshot capture failed: {out}", file=sys.stderr)
                _FAILED = True
            return

        while True:
            await ui.next_frame()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        _FAILED = True


if __name__ == "__main__":
    ui.run(_main())
    # Avoid late native callback teardown masking the one-shot smoke result.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1 if _FAILED else 0)

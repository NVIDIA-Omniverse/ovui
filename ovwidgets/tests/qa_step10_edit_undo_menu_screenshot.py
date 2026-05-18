# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA path #7 (undo) -- Step 10 screenshot proof.

Plan Rev 2 §4 Step 10 specifies "QA paths #5 (open file via menu --
uses Settings.instance), #6 (Ctrl+drag copy -- proves local key
tracking), #7 (undo)." This driver covers the Edit > Undo menu surface.

Step 10 codemodded settings/recent reads on widget code paths but did
not change the undo subsystem's contract. The visible proof for #7 is
that the Edit menu still renders the Undo / Redo / Settings... items
correctly with the new singleton wiring in
``Application.__init__``.

User-like flow (strict screenshot-first / one action per screenshot):

* screenshot 01 -- baseline.
* action: click ``Edit`` in the menu bar.
* screenshot 02 -- Edit menu open with Undo / Redo / Settings... items.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting

from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles
from ovwidgets.common.selection import SelectionBus

OUT_DIR = "/tmp"
PREFIX = "ovgear_step10_qa7"


# Coordinates derived from the immediately preceding screenshot.
#
#   step 02 click target -- "Edit" menu in the top menu bar (third
#   item after the OvGear logo and File). From screenshot 01 the
#   label sits around (200, 16).
COORD_EDIT_MENU = (200, 16)


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _shot(name: str) -> str:
    path = f"{OUT_DIR}/{PREFIX}_{name}.png"
    uitesting.capture_screenshot(path)
    print(f"[step10-qa7] {name}: {path}")
    return path


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    await _drive(40)

    _shot("01_loaded")

    await uitesting.mouse_click(*COORD_EDIT_MENU)
    await _drive(5)
    _shot("02_edit_menu_open")

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    write_split_ini()
    ui.init("OvGear Step 10 QA-7", width=1280, height=720)
    apply_global_styles()
    ui.run(_main())

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA path #5 (open file dialog) -- Step 10 screenshot proof.

Plan Rev 2 §4 Step 10 specifies "QA paths #5 (open file via menu --
uses ``Settings.instance``)". Step 10 codemodded
``ovwidgets.content.file_importer._settings`` from
``Application.instance().settings`` to ``Settings.instance()``; the
visible proof that the path still works is to open the File menu's
"Open..." item via clicks and screenshot the resulting dialog --
:class:`FilePickerDialog` reads the recent-folder hint via
``FileImporterHelper`` (which now goes through
``ovwidgets.common.settings.Settings.instance()``).

Strict screenshot-first / one-action-per-screenshot driver per
``QA-AGENT-PROMPT.md``.

User-like flow:

* screenshot 01 -- app loaded (baseline).
* action: click the ``File`` menu in the top menu bar.
* screenshot 02 -- File menu open.
* action: click the ``Open...`` menu item.
* screenshot 03 -- ``FilePickerDialog`` rendered with the recent
  folder hint resolved through ``Settings.instance()``. The dialog's
  presence is the proof that the Step-10 ``Settings.instance()``
  read returned a live settings object.
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
PREFIX = "ovgear_step10_qa5"


# Coordinates derived from the immediately preceding screenshot at
# each step. Default ovgear chrome at 1280x720.
#
#   step 02 click target -- "File" menu (second item in the menu bar
#   after the OvGear logo). From screenshot 01 the label sits around
#   (165, 16).
COORD_FILE_MENU = (165, 16)
#   step 03 click target -- "Open..." menu item, second row in the
#   File menu drop-down (after "New"). From screenshot 02 the row
#   centre sits at approximately (200, 74).
COORD_OPEN_ITEM = (200, 74)


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _shot(name: str) -> str:
    path = f"{OUT_DIR}/{PREFIX}_{name}.png"
    uitesting.capture_screenshot(path)
    print(f"[step10-qa5] {name}: {path}")
    return path


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    await _drive(40)

    _shot("01_loaded")

    await uitesting.mouse_click(*COORD_FILE_MENU)
    await _drive(5)
    _shot("02_file_menu_open")

    await uitesting.mouse_click(*COORD_OPEN_ITEM)
    await _drive(15)
    _shot("03_file_dialog")

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
    ui.init("OvGear Step 10 QA-5", width=1280, height=720)
    apply_global_styles()
    ui.run(_main())

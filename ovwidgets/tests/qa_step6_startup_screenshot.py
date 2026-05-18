# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA app-startup screenshot for Step 6 (dialogs.py + file_dialogs.py
moved to ovwidgets.common).

Plan Rev 2 §4 Step 6 explicitly requires "Runtime QA: app startup
screenshot." This driver launches the full ``ovwidgets.app.Application``
through ``ui.init`` + ``ui.run`` (the same pattern used by other
``qa_full_app_*_screenshot.py`` drivers), drives 40 frames so the dock
layout, status bar, mock viewport, and Property Inspector all settle,
then captures a single screenshot via
``omni.ui.testing.capture_screenshot``.

Step 6 only relocates two modules (``dialogs.py`` + ``file_dialogs.py``
→ ``common``) and rewrites callers; it does not reach a confirm-dialog
flow in headless CI on its own. The plan's parenthetical explicitly
allows this — "if a confirm dialog flow is reachable in headless CI,
add a screenshot proof; otherwise the next dialog-touching step covers
QA" — so the proof for Step 6 is simply that the application boots
cleanly with the new common dialog module locations and that the
Application import path that lazy-loads ``ovwidgets.common.dialogs`` /
``ovwidgets.common.file_dialogs`` (via ``icon_caches.register``) does
not regress startup.

Output: ``/tmp/ovgear_step6_startup.png``.
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
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus

OUT_PATH = "/tmp/ovgear_step6_startup.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Drive enough frames for the default dock layout, mock viewport,
    # and chrome to settle so the screenshot shows the full booted
    # window — top menu bar, Stage Browser, Viewport, Property
    # Inspector (No selection), Layers, Content Browser.
    await _drive(40)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"[step6] app-startup screenshot saved: {OUT_PATH}")

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
    ui.init("OvGear Step 6 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

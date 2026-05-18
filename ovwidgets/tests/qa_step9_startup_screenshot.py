# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA app-startup screenshot for Step 9 (5 mock adapters moved from
``ovwidgets.app.testing`` to ``ovwidgets.common.testing``).

Plan Rev 2 §4 Step 9 says "Runtime QA: app startup screenshot. The
``MockRendererAdapter`` / ``MockStageAdapter`` are constructed at
startup (``application.py:1035, 1037``) — so a successful startup
proves Step 9's mock-import codemod is correct."

This driver launches the full ``ovwidgets.app.Application`` through
``ui.init`` + ``ui.run``, drives 40 frames so the dock layout and
mock viewport settle, then captures a single screenshot via
``omni.ui.testing.capture_screenshot``. A clean booted application
window with the mock viewport scene visible is the proof that
``application.py:1016-1017`` (the codemodded mock-renderer / mock-
stage imports now resolving via ``ovwidgets.common.testing``) load
without error.

Output: ``/tmp/ovgear_step9_startup.png``.
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

OUT_PATH = "/tmp/ovgear_step9_startup.png"


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
    # window.
    await _drive(40)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"[step9] app-startup screenshot saved: {OUT_PATH}")

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
    ui.init("OvGear Step 9 QA", width=1280, height=720)
    apply_global_styles()
    ui.run(_main())

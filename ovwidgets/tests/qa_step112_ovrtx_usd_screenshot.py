# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA OvRTX + USD scene screenshot for Step 11.2.

Victor's request: "Next step, not now: I need to see ovrtx is actually
working. So ask to make a screenshot with usd scene opened."

Strategy: start the full :class:`ovwidgets.app.Application` with
``simple_scene.usda`` as the startup USD path, drive enough frames
for OvRTX to load and render the scene, then capture via
``omni.ui.testing.capture_screenshot``.

Output: ``/tmp/ovgear_step112_ovrtx_usd.png``.
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

USD_PATH = os.path.join(os.path.dirname(__file__), "data", "simple_scene.usda")
OUT_PATH = "/tmp/ovgear_step112_ovrtx_usd.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    app._startup_usd_path = USD_PATH
    task = asyncio.ensure_future(app.run_async())

    # Drive a generous number of frames so OvRTX can finish loading the
    # USD stage and accumulate path-traced samples.
    await _drive(120)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"[step11.2-ovrtx] screenshot saved: {OUT_PATH}")

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    write_split_ini()
    ui.init("OvGear Step 11.2 OvRTX QA", width=1280, height=720)
    apply_global_styles()
    ui.run(_main())

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Bug 12 reproduction — capture viewport frames across prim selection changes.

Clicks a prim in the stage window (via bus) multiple times, capturing frames
back-to-back to detect a viewport resize/flicker. If frames captured mid-rebuild
differ meaningfully from pre/post frames, that is the flicker.
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

USD_PATH = os.path.join(os.path.dirname(__file__), "data", "simple_scene.usda")


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

    await _drive(40)

    # Baseline: select the cube, let it settle.
    app.selection_bus.publish(["/World/Cube"], source="qa")
    await _drive(15)
    uitesting.capture_screenshot("/tmp/ovgear_bug12_before.png")

    # Now rapidly change selection — this is the scenario that causes
    # the viewport to flicker/resize briefly.
    app.selection_bus.publish(["/World/Sphere"], source="qa")
    # Capture immediately — if the viewport is being rebuilt, it will be
    # either blank or different size here.
    await _drive(1)
    uitesting.capture_screenshot("/tmp/ovgear_bug12_mid1.png")
    await _drive(1)
    uitesting.capture_screenshot("/tmp/ovgear_bug12_mid2.png")
    await _drive(15)
    uitesting.capture_screenshot("/tmp/ovgear_bug12_after.png")

    # One more rapid change — demonstrate the effect again.
    app.selection_bus.publish(["/World/Pyramid"], source="qa")
    await _drive(1)
    uitesting.capture_screenshot("/tmp/ovgear_bug12_mid3.png")
    await _drive(15)
    uitesting.capture_screenshot("/tmp/ovgear_bug12_after2.png")

    print("Saved Bug 12 reproduction screenshots under /tmp/ovgear_bug12_*.png")

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
    ui.init("OvGear Bug 12 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

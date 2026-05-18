# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Capture before/after screenshots proving a Property Inspector edit updates the viewport.

Drives the real Application end-to-end:
1. Load tests/data/simple_scene.usda
2. Select /World/Cube
3. Snapshot the viewport
4. Mutate xformOp:translate on the cube via the USD API (identical to what
   UsdPropertyAdapter.set_value() does when Victor types in the spinner)
5. Snapshot again
6. Compare pixels in the viewport area

Run:
    DISPLAY=:99 python tests/verify_live_update.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
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


def _force_render(app: Application) -> None:
    """Force a viewport render regardless of the FPS throttle.

    ViewportWidget._on_frame() skips draws when ``dt < 1/60`` — in headless
    test harnesses the tick loop spins far faster than that, so pumping
    ``next_frame()`` alone can leave the viewport never actually rendering.
    Passing a large ``dt`` bypasses the throttle so the screenshot captures
    the current renderer output.
    """
    if app._viewport_window is not None:
        app._viewport_window._on_frame(1.0)


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    app._startup_usd_path = USD_PATH
    task = asyncio.ensure_future(app.run_async())
    await _drive(60)  # let the UI build, load the stage, swap the renderer

    # Select the Cube so it's highlighted in both screenshots (easier to see movement).
    app.selection_bus.publish(["/World/Cube"], source="verify")
    await _drive(10)
    _force_render(app)
    await _drive(2)  # let the provider upload the new frame

    uitesting.capture_screenshot("/tmp/ovgear_live_update_before.png")
    print("before screenshot: /tmp/ovgear_live_update_before.png")

    # Mutate the USD attribute — mirrors Property Inspector path
    # (UsdPropertyAdapter.set_value calls attr.Set exactly like this).
    from pxr import Gf
    cube = app._stage_adapter.stage.GetPrimAtPath("/World/Cube")
    before_val = cube.GetAttribute("xformOp:translate").Get()
    new_val = Gf.Vec3d(4.0, 2.0, 0.0)
    cube.GetAttribute("xformOp:translate").Set(new_val)
    print(f"mutated xformOp:translate: {tuple(before_val)} -> {tuple(new_val)}")

    # Tf.Notice flushes through call_later(0.0) → wait some frames so the
    # stage adapter fires ChangeEvent → viewport.notify_stage_changed → renderer refresh.
    await _drive(10)
    _force_render(app)
    await _drive(2)

    uitesting.capture_screenshot("/tmp/ovgear_live_update_after.png")
    print("after screenshot:  /tmp/ovgear_live_update_after.png")

    # Pixel diff in the viewport region (right of x=320, below y=20).
    from PIL import Image
    a = np.array(Image.open("/tmp/ovgear_live_update_before.png"))[20:700, 320:1280]
    b = np.array(Image.open("/tmp/ovgear_live_update_after.png"))[20:700, 320:1280]
    diff = int(np.any(a != b, axis=-1).sum())
    total = a.shape[0] * a.shape[1]
    print(f"viewport pixel diff: {diff} / {total} ({100 * diff / total:.2f}%)")

    # The mutation should produce clearly visible movement (hundreds of pixel diffs minimum).
    if diff < 500:
        print(f"FAIL — viewport did NOT refresh (diff={diff}, expected >500)")
        status = 1
    else:
        print(f"PASS — viewport refreshed live after property edit (diff={diff})")
        status = 0

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()
    sys.exit(status)


if __name__ == "__main__":
    _layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(_layout_path):
        os.unlink(_layout_path)
    write_split_ini()
    ui.init("OvGear Live Update Verify", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

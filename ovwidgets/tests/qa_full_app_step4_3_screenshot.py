# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshot for Property Window Step 4.3 — ControlStateIndicator.

Launches the full ovwidgets.app application with ``tests/data/step4_3_scene.usda``
loaded and selects ``/World/StateSphere``. The scene exercises three of
the four built-in ``ControlStateManager`` handlers in a single row
layout:

* ``radius`` is time-sampled → TimeSampled (priority 30) → info icon.
* ``someLocked`` is locked → Locked (priority 20) → lock icon.
* ``xformOp:translate`` is authored → NotDefault (priority 40) →
  check icon, clickable (adapter.clear_value supported by USD).

The screenshot proves the round-trip: USD state → adapter →
``AttributeMetadata.{is_time_sampled,is_locked,is_authored}`` →
``ControlStateManager.get_active_state`` → right-side icon visible in
the row's 20 px indicator slot.

Output: /tmp/ovgear_full_app_step4_3.png

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=... python3.12 tests/qa_full_app_step4_3_screenshot.py
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

USD_PATH = os.path.join(os.path.dirname(__file__), "data", "step4_3_scene.usda")
OUT_PATH = "/tmp/ovgear_full_app_step4_3.png"


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
    app.selection_bus.publish(["/World/StateSphere"], source="qa")
    await _drive(15)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")

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
    ui.init("OvGear Step 4.3 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshot for Property Window Step 3.7 — relationship row.

Launches the full ovwidgets.app application with ``tests/data/step3_7_scene.usda``
loaded, selects the ``/World/GeoSphere`` prim so the Property Inspector
renders its three relationships (``proxyPrim``, ``singleProxy``,
``multiProxies``) as read-only ``ui.StringField`` rows. Captures the
entire 1280×720 window (Stage Browser + Property Inspector + Viewport).

Output: /tmp/ovgear_full_app_step3_7.png

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=... python3.12 tests/qa_full_app_step3_7_screenshot.py
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

USD_PATH = os.path.join(os.path.dirname(__file__), "data", "step3_7_scene.usda")
OUT_PATH = "/tmp/ovgear_full_app_step3_7.png"


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
    app.selection_bus.publish(["/World/GeoSphere"], source="qa")
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
    ui.init("OvGear Step 3.7 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

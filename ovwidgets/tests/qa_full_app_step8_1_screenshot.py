# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshot for Property Window Step 8.1 — component separators.

Step 8.1 adds thin 1-px vertical
:class:`ui.Rectangle` separators between adjacent channel drag widgets
in every vector / colour / matrix attribute row. The separators carry
``style_type_name_override="Property.ComponentSeparator"`` so the
``cl.border_default`` fill (same palette shade the search-field and
swatch borders use) attaches in both themes.

This script loads the Step 3.4 scene — a single Cube prim carrying a
``double3 xformOp:translate`` (Vec3, 2 separators), a
``color3f tintColor`` (Color3, 2 separators before the swatch), and a
``color4f fillColor`` (Color4, 3 separators before the swatch). Selecting
``/World/ColorCube`` draws all three row types in the Property Inspector
so the separator visual lands on every channel-grouped row type the
Step 8.1 change covers.

Output: /tmp/ovgear_full_app_step8_1.png

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_full_app_step8_1_screenshot.py
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

USD_PATH = os.path.join(os.path.dirname(__file__), "data", "step3_4_scene.usda")
OUT_PATH = "/tmp/ovgear_full_app_step8_1.png"


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
    app.selection_bus.publish(["/World/ColorCube"], source="qa")
    await _drive(20)

    pw = app._property_window
    if pw is None:
        raise RuntimeError("Application._property_window not initialised")
    if pw._selection != ["/World/ColorCube"]:
        raise RuntimeError(
            f"Expected selection ['/World/ColorCube'], got {pw._selection!r}"
        )
    print(f"Selection: {pw._selection}")

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
    ui.init("OvGear Step 8.1 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

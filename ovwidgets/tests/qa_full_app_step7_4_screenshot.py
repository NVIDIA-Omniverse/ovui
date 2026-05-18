# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshot for Property Window Step 7.4 —
large-selection gate.

Step 7.4 (the property inspector implementation) gates :meth:`PropertyWindow._rebuild_content`
on :meth:`PropertyPayload.is_large_selection`. When more than 100 paths
are selected, the window suppresses the full attribute build and
renders a "N items selected — property display suppressed. Click to
load anyway." banner with a "Load Anyway" button. Clicking the button
sets the override flag and forces a rebuild that takes the full-
attribute branch. The override resets on every new selection.

This QA script proves the banner visually:

1. Load a simple scene as the stage.
2. Publish 150 synthetic paths through the selection bus. The
   :class:`PropertyWindow`'s :meth:`set_selection` updates
   ``_selection`` with all 150 paths; the next rebuild sees
   ``is_large_selection(100) → True`` and the gate fires.
3. Drive a few frames for layout + style to settle.
4. Capture the 1280×720 full-app PNG.

Output: /tmp/ovgear_full_app_step7_4.png

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_full_app_step7_4_screenshot.py
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
OUT_PATH = "/tmp/ovgear_full_app_step7_4.png"


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

    # Drive past the startup load so the stage browser + inspector settle.
    await _drive(40)

    # Publish 150 synthetic paths — the gate only cares about the count,
    # not whether the paths resolve to prims, so the banner fires
    # regardless of whether simple_scene.usda has 150 authored prims.
    large_selection = [f"/World/Prim{i:04d}" for i in range(150)]
    app.selection_bus.publish(large_selection, source="qa")

    # Drive enough frames for the rebuild + banner layout to land.
    await _drive(20)

    # Runtime verification: the property window's gate should be on
    # (banner branch took), not off (full build with 150 fake-attribute
    # rows). If the override flag is True here something else flipped
    # it. If `_selection` is empty the bus publish never arrived.
    pw = app._property_window
    if pw is None:
        raise RuntimeError("Application._property_window not initialised")
    if len(pw._selection) != 150:
        raise RuntimeError(
            f"Expected 150 selected paths, got {len(pw._selection)}"
        )
    if pw._large_selection_override is not False:
        raise RuntimeError(
            "Large-selection override unexpectedly True at screenshot time"
        )
    print(
        f"Selection size: {len(pw._selection)}; "
        f"override flag: {pw._large_selection_override}; "
        f"banner branch: active"
    )

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
    ui.init("OvGear Step 7.4 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

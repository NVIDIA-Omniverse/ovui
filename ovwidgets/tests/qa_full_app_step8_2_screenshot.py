# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshot for Property Window Step 8.2 — header styling refresh.

Step 8.2 refines the group-frame
header palette:

* ``Property.GroupFrame:hovered`` and ``:pressed`` now lift ``color`` to
  ``cl.text_primary`` alongside the style-locked ``secondary_color`` shift
  so the chevron + title brighten with the header strip.
* ``Property.GroupFrame::inner`` + ``:hovered`` + ``:pressed`` — the
  nested-level variant — paints sub-group titles in ``cl.text_secondary``
  with the same hover/pressed brightening, subordinating the visual
  weight of deeply-nested frames.
* :class:`AttributeGroupWidget` accepts a ``level`` kwarg;
  :class:`AttributesWidget._build_group_children` threads it through the
  recursion. ``level=0`` at the top, increments per child level; the
  ``::inner`` variant activates for ``level >= 1``.

This script loads the Step 5.2 scene — a :class:`UsdGeom.Scope` with
``Transform:Translate``, ``Transform:Rotate``, and ``Geometry:Mesh``
nested display groups — so the inspector renders outer + inner frames
side-by-side and the level-based title shade is visible in the capture.

Output: /tmp/ovgear_full_app_step8_2.png

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_full_app_step8_2_screenshot.py
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

USD_PATH = os.path.join(os.path.dirname(__file__), "data", "step5_2_scene.usda")
OUT_PATH = "/tmp/ovgear_full_app_step8_2.png"


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
    app.selection_bus.publish(["/World/NestedScope"], source="qa")
    await _drive(20)

    pw = app._property_window
    if pw is None:
        raise RuntimeError("Application._property_window not initialised")
    if pw._selection != ["/World/NestedScope"]:
        raise RuntimeError(
            f"Expected selection ['/World/NestedScope'], got {pw._selection!r}"
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
    ui.init("OvGear Step 8.2 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

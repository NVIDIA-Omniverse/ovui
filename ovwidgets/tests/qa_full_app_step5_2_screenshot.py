# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshot for Property Window Step 5.2 — nested
:class:`UiDisplayGroup` frames.

Step 5.2 wires the Step-5.1 :class:`UiDisplayGroup` tree into
:meth:`PropertyWidget._build_groups`. The Property Inspector now emits
nested :class:`ui.CollapsableFrame` hierarchies for attributes whose
``group`` string is dot-separated (e.g. ``"Transform.Translate"`` →
outer ``Transform`` frame containing inner ``Translate`` frame).

This screenshot loads ``tests/data/step5_2_scene.usda`` and selects
``/World/NestedSphere``, which authors five attributes with
colon-separated ``displayGroup`` metadata that the USD adapter rewrites
to the dot form. The expected rendered tree inside the Property
Inspector:

    Attributes                   (unauthored schema attrs, Double Sided … Xform Op Order)
    Transform
    ├── Translate                (Offset X, Offset Y)
    └── Rotate                   (Spin Z)
    Geometry
    └── Mesh                     (Subdivision)
    Primvars                     (Display Color, Display Opacity)

Output: /tmp/ovgear_full_app_step5_2.png

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_full_app_step5_2_screenshot.py
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
OUT_PATH = "/tmp/ovgear_full_app_step5_2.png"


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
    ui.init("OvGear Step 5.2 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

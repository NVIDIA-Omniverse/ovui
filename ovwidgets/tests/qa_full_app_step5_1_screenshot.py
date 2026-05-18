# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshot for Property Window Step 5.1 — UiDisplayGroup tree.

Step 5.1 is a pure data-structure step: it introduces
:class:`ovwidgets.property.parts.UiDisplayGroup` as the recursive tree node
that Step 5.2 will use to render nested ``ui.CollapsableFrame``
hierarchies. Because Step 5.1 only adds the dataclass (and does not
wire it into ``PropertyWidget``), there is no pixel change compared
to Step 4.4 — the screenshot's role is continuity, proving the
import of the new module doesn't perturb application startup or
layout.

Reuses ``tests/data/step4_3_scene.usda`` for directly comparable
bytes against ``/tmp/ovgear_full_app_step4_4.png``.

Output: /tmp/ovgear_full_app_step5_1.png

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=... python3.12 tests/qa_full_app_step5_1_screenshot.py
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
OUT_PATH = "/tmp/ovgear_full_app_step5_1.png"


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
    ui.init("OvGear Step 5.1 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

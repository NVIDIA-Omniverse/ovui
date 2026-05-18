# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshot for Property Window Step 4.4 — SVG icons.

Step 4.4 adds the four production SVG assets (``mixed.svg``,
``locked.svg``, ``timesample.svg``, ``not_default.svg``) in
``ovwidgets.app/style/icons/``, registers them on ``omni.ui.url`` as
``control_state_*`` via :func:`ovwidgets.common.style.urls.register_urls`, and
retargets the built-in ``ControlStateManager`` handlers at the new
assets.

On the standalone omni.ui build used by the dev VM,
``ui._IN_KIT`` is False so ``_SVG_RENDERING_AVAILABLE`` gates the
``ui.Image`` construction off — the indicator falls back to the
Step-4.3 ``ui.Rectangle`` + per-state style selector. The Kit side of
the dual-render split cannot be screenshotted from this VM, so this
screenshot's role is regression-checking: proving the indicator
column still renders the three visible states (TimeSampled, Locked,
NotDefault) identically to Step 4.3 after the icon-path retarget.

Reuses ``tests/data/step4_3_scene.usda`` so the row layout is directly
comparable against ``/tmp/ovgear_full_app_step4_3.png``.

Output: /tmp/ovgear_full_app_step4_4.png

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=... python3.12 tests/qa_full_app_step4_4_screenshot.py
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
OUT_PATH = "/tmp/ovgear_full_app_step4_4.png"


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
    ui.init("OvGear Step 4.4 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

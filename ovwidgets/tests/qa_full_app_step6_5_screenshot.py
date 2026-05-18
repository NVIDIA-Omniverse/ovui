# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshot for Property Window Step 6.5 — the
:class:`ovwidgets.property.widget.PropertySchemeRegistry`.

Step 6.5 hoists widget registration out of :class:`PropertyWindow` and
into the process-wide :class:`PropertySchemeRegistry`. The module
registers :class:`~ovwidgets.property.widget.AttributesWidget` for scheme
``"default"`` at import; :meth:`PropertyWindow._rebuild_content` now
asks the registry for the widget list and lets each returned widget
decide whether to render. No visible behaviour should change: the
default :class:`AttributesWidget` still surfaces for every payload so
the property panel stays byte-for-byte identical to the Step 6.4
capture (a diff against ``/tmp/ovgear_full_app_step6_4.png`` verifies
that the registry-based rebuild path did not alter the default
render).

This screenshot reuses Step 5.3's ``step5_2_scene.usda`` fixture
(nested ``Transform → Translate / Rotate`` and ``Geometry → Mesh``
groups) and exercises the same selection (``/World/NestedScope``) as
Steps 6.1–6.4 so the visual continuity chain stays intact.

Output: /tmp/ovgear_full_app_step6_5.png

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_full_app_step6_5_screenshot.py
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
OUT_PATH = "/tmp/ovgear_full_app_step6_5.png"


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
    ui.init("OvGear Step 6.5 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

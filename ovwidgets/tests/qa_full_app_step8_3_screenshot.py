# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application dual-theme screenshot for Property Window Step 8.3.

Step 8.3 (the property inspector implementation §8.3) is the final verification pass: every
:mod:`ovwidgets.property` surface must render legibly under both dark and
light shades. ``ovwidgets.app/style/palette.py`` registers every palette name
with an explicit ``light=`` variant and ``ovwidgets.property/style.py``
references only ``cl.*`` / ``fl.*`` tokens (no hardcoded hex), so the
theme-switching foundation is already in place — this script proves
it end-to-end by capturing both shades of the same scene with the
Property Inspector populated.

Scene: ``step5_2_scene.usda`` — a :class:`UsdGeom.Scope` with nested
``Transform:Translate`` / ``Transform:Rotate`` / ``Geometry:Mesh``
display groups, so the capture exercises:

* The Step 0.3 ``Property.GroupFrame`` (outer headers).
* The Step 8.2 ``Property.GroupFrame::inner`` variant (nested headers
  paint in ``cl.text_secondary``).
* Float rows (``Offset X``, ``Offset Y``, ``Spin Z``) for
  ``Property.ChannelLabel.*`` / ``Property.ComponentSeparator`` coverage
  (Step 8.1) and the ``FloatDrag`` global style.
* Token rows (``Subdivision``, ``Purpose``, ``Visibility``) exercising
  the Step 3.3 ComboBox builder.
* ``Property.LabelColumn`` / ``Property.MixedOverlay`` baseline styling.

Outputs:
  /tmp/ovgear_full_app_step8_3_dark.png
  /tmp/ovgear_full_app_step8_3_light.png

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_full_app_step8_3_screenshot.py
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
OUT_DARK = "/tmp/ovgear_full_app_step8_3_dark.png"
OUT_LIGHT = "/tmp/ovgear_full_app_step8_3_light.png"


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

    # Capture dark shade first (the default). ``set_theme("dark")`` below
    # restores the same state, but running it explicitly keeps the script
    # reproducible even if a future Application default flips.
    set_theme("dark")
    apply_global_styles()
    await _drive(10)
    uitesting.capture_screenshot(OUT_DARK)
    print(f"Saved: {OUT_DARK}")

    # Theme switch through the Settings subscription so the full path runs:
    # Settings.set → _on_theme_changed → set_theme("light") → ui.set_shade →
    # apply_global_styles → panel.on_theme_changed on every window →
    # dockspace re-style. If any step of that chain regresses, the light
    # capture will surface it (e.g. a panel frozen at the dark background).
    app.settings.set("ui.theme", "light")
    await _drive(10)
    uitesting.capture_screenshot(OUT_LIGHT)
    print(f"Saved: {OUT_LIGHT}")

    # Leave the harness in the default shade so repeat runs do not leak
    # state into the next invocation via Settings persistence.
    app.settings.set("ui.theme", "dark")
    await _drive(5)

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
    ui.init("OvGear Step 8.3 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA chevron-render proof for Step 8 (style/urls.py + 3 icon dirs
moved to ``ovwidgets.common``).

Plan Rev 2 §4 Step 8 specifies "Runtime QA: omni.ui screenshot of any
panel containing chevrons (e.g., layer panel; QA path #2 + #3 viewing
prim hierarchy)." The proof that the chevron PNGs still resolve
through ``importlib.resources.files("ovwidgets.common")`` after the
move is to expand the Stage Browser tree and screenshot the visible
chevron glyphs.

Strict screenshot-first / one-action-per-screenshot driver per
``QA-AGENT-PROMPT.md``.

User-like flow:

* screenshot 01 — app loaded, ``World`` row collapsed (the chevron
  next to ``World`` paints in the right-pointing state).
* action: click the ``World`` row chevron.
* screenshot 02 — ``World`` expanded; ``Geometry``, ``Lights``,
  ``Camera`` rows visible, each with its own collapsed chevron. The
  ``World`` chevron now paints in the down-pointing state.
* action: click the ``Geometry`` row chevron.
* screenshot 03 — ``Geometry`` expanded; chevron paints down; child
  rows ``Ground / Sphere / Cube`` visible.

All input via ``omni.ui.testing`` only. Coordinates are read from the
preceding screenshot at each step. No OS-level screenshot/input tools.
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
from ovwidgets.app.style import apply_global_styles
from ovwidgets.common.selection import SelectionBus

OUT_DIR = "/tmp"
PREFIX = "ovgear_step8_chevrons"


# Coordinates derived from the immediately preceding screenshot at
# each step. Default ovgear chrome at 1280x720, layout from
# ``write_split_ini`` (no persisted layout).
#
#   step 02 click target — ``World`` row chevron (Stage Browser
#   leftmost column). From screenshot 01 the chevron sits at
#   approximately (18, 101).
COORD_WORLD_CHEVRON = (18, 101)
#   step 03 click target — ``Geometry`` row chevron, one indent
#   below World. From screenshot 02 the chevron at this indent is
#   around (35, 118).
COORD_GEOMETRY_CHEVRON = (35, 118)


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _shot(name: str) -> str:
    path = f"{OUT_DIR}/{PREFIX}_{name}.png"
    uitesting.capture_screenshot(path)
    print(f"[step8-chevrons] {name}: {path}")
    return path


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Drive enough frames for the dock layout, mock viewport, and
    # stage adapter to settle.
    await _drive(40)

    # State 1: loaded; ``World`` collapsed; right-pointing chevron
    # visible in its branch column. The chevron's PNG resolves via
    # ``importlib.resources.files("ovwidgets.common")`` after Step 8.
    _shot("01_collapsed")

    # Action 1: click the World row chevron.
    await uitesting.mouse_click(*COORD_WORLD_CHEVRON)
    await _drive(5)
    # State 2: World expanded; child rows visible with their own
    # right-pointing chevrons; the World chevron now down-pointing.
    _shot("02_world_expanded")

    # Action 2: click the Geometry row chevron.
    await uitesting.mouse_click(*COORD_GEOMETRY_CHEVRON)
    await _drive(5)
    # State 3: Geometry expanded; chevron paints down; Ground /
    # Sphere / Cube children visible. Three different chevron states
    # (right at top, down at expanded parents, right at leaves) all
    # render through the new common path.
    _shot("03_geometry_expanded")

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
    ui.init("OvGear Step 8 QA Chevrons", width=1280, height=720)
    apply_global_styles()
    ui.run(_main())

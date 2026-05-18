# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA path #11 (filter debounce) — Step 5 screenshot-first proof.

Strict screenshot-first / one-action-per-screenshot driver, per
``QA-AGENT-PROMPT.md``. Every state change a real user would care
about is preceded by a screenshot used to derive the next click /
type coordinate, then followed by a screenshot used to verify the
action landed before the next action begins.

User-like flow:

* screenshot 01 — app loaded with no selection (Stage Browser shows
  ``World`` collapsed; Property Inspector reads "No selection").
* action: click the chevron next to ``World`` (Stage Browser).
* screenshot 02 — ``World`` expanded; ``Geometry``, ``Lights``,
  ``Camera`` visible.
* action: click the chevron next to ``Geometry``.
* screenshot 03 — ``Geometry`` expanded; ``Ground``, ``Sphere``,
  ``Cube`` visible.
* action: click the ``Sphere`` row.
* screenshot 04 — ``Sphere`` selected (row highlight; viewport
  selection outline; Property Inspector populated with Transform,
  Display, Geometry groups).
* action: click the Property Inspector "Filter properties..." field.
* screenshot 05 — property filter focused (focus border on).
* action: type ``rad``.
* screenshot 06 — captured immediately after typing finishes; chrome
  reacts synchronously (text + active clear-X), but the content list
  still shows every attribute group because the 0.15 s
  ``ovwidgets.common.scheduler.call_later`` debounce timer is still
  pending.
* observation wait: ~30 frames (well past 0.15 s).
* screenshot 07 — post-debounce. ``_apply_filter`` ran via the
  registered scheduler backend; content list collapsed to
  ``Geometry / Radius``.

All input goes through ``omni.ui.testing`` exclusively. No
``SelectionBus.publish``, no internal selection APIs, no
programmatic UI shortcuts, no OS-level screenshot/input tools. Every
coordinate used here was read off the immediately preceding
screenshot during QA authoring (default ovgear dock layout from
``write_split_ini`` at 1280×720, no persisted layout).

Run from the repo root:

    _venv312/bin/python tests/qa_step5_filter_debounce_screenshot.py

Outputs (`/tmp/ovgear_step5_qa11_*.png`):

* ``01_loaded.png``
* ``02_world_expanded.png``
* ``03_geometry_expanded.png``
* ``04_sphere_selected.png``
* ``05_property_filter_focused.png``
* ``06_typed_predebounce.png``
* ``07_postdebounce.png``
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
OUT_DIR = "/tmp"
PREFIX = "ovgear_step5_qa11"


# Coordinates derived by reading the immediately preceding screenshot
# at each step. The application boots into the default
# ``write_split_ini`` dock layout (no persisted layout), so element
# positions are stable.
#
#   step 02 click target — ``World`` row chevron in the Stage Browser
#   left dock. From screenshot 01 the chevron column sits around
#   x=18 and the World row centre is at y=101.
COORD_WORLD_CHEVRON = (18, 101)
#   step 03 click target — ``Geometry`` row chevron, one indent below
#   World. From screenshot 02 the chevron at this indent is around
#   x=35 and the Geometry row centre is at y=118.
COORD_GEOMETRY_CHEVRON = (35, 118)
#   step 04 click target — ``Sphere`` row, one further indent below
#   Geometry. From screenshot 03 the row text centre is at
#   approximately (95, 150).
COORD_SPHERE_ROW = (95, 150)
#   step 05 click target — Property Inspector filter input. From
#   screenshot 04 it sits at y=58 on the right dock, input centre
#   around x=1080.
COORD_PROPERTY_FILTER = (1080, 58)


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _shot(name: str) -> str:
    """Capture one screenshot at a numbered checkpoint."""
    path = f"{OUT_DIR}/{PREFIX}_{name}.png"
    uitesting.capture_screenshot(path)
    print(f"[qa11] {name}: {path}")
    return path


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    app._startup_usd_path = USD_PATH
    task = asyncio.ensure_future(app.run_async())

    # Drive enough frames for the dock layout, mock viewport, and stage
    # adapter to settle so the Stage Browser actually shows ``World``.
    await _drive(40)

    # State 1: loaded, no selection.
    _shot("01_loaded")

    # Action 1: click the World chevron to expand the prim hierarchy.
    await uitesting.mouse_click(*COORD_WORLD_CHEVRON)
    await _drive(5)
    # State 2: World expanded; Geometry / Lights / Camera visible.
    _shot("02_world_expanded")

    # Action 2: click the Geometry chevron to expand it.
    await uitesting.mouse_click(*COORD_GEOMETRY_CHEVRON)
    await _drive(5)
    # State 3: Geometry expanded; Ground / Sphere / Cube visible.
    _shot("03_geometry_expanded")

    # Action 3: click the Sphere row to select it.
    await uitesting.mouse_click(*COORD_SPHERE_ROW)
    await _drive(15)
    # State 4: Sphere selected; Property Inspector populated with
    # Transform / Display / Geometry attribute groups.
    _shot("04_sphere_selected")

    # Action 4: click the Property Inspector filter field to focus it.
    await uitesting.mouse_click(*COORD_PROPERTY_FILTER)
    await _drive(5)
    # State 5: property filter focused — focus border on the field.
    _shot("05_property_filter_focused")

    # Action 5: type "rad" — a single user-like type action that
    # begins the 0.15 s debounce timer in
    # ``ovwidgets.common.scheduler``.
    await uitesting.type_text("rad")
    # State 6: captured immediately after typing finishes, while the
    # debounce is still pending. Chrome reacts synchronously; content
    # list has not yet rebuilt.
    _shot("06_typed_predebounce")

    # Observation wait: ~30 frames at 60 Hz, well past the 0.15 s
    # debounce window. This is not a user action, it is the user
    # looking at the screen until the rebuild lands.
    await _drive(30)
    # State 7: post-debounce. ``_apply_filter`` ran via the registered
    # scheduler backend; content list collapsed to
    # ``Geometry / Radius``.
    _shot("07_postdebounce")

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
    ui.init("OvGear Step 5 QA-11", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

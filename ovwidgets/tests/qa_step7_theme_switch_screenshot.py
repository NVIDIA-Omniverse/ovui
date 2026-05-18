# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA path #8 (theme switch) — Step 7 screenshot-first proof.

Strict screenshot-first / one-action-per-screenshot driver per
``QA-AGENT-PROMPT.md``. Step 7 moves
``ovwidgets/app/style/palette.py`` to
``ovwidgets/common/style/palette.py``; the visible proof that the
``cl.*`` shade ids still register correctly is the theme switching
through the View menu and seeing the palette re-resolve.

User-like flow:

* screenshot 01 — app loaded, default dark theme.
* action: click the ``View`` menu in the top menu bar.
* screenshot 02 — View menu open, "Light Theme" / "Dark Theme"
  items visible.
* action: click ``Light Theme``.
* screenshot 03 — light theme applied (chrome shades flipped).
* action: click the ``View`` menu again.
* screenshot 04 — View menu open in light theme.
* action: click ``Dark Theme``.
* screenshot 05 — dark theme restored.

All input goes through ``omni.ui.testing`` exclusively. No
internal-API shortcut for theme switching, no
``set_theme(...)`` direct call, no programmatic palette mutation.
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
PREFIX = "ovgear_step7_theme"


# Coordinates derived from the immediately preceding screenshot at
# each step. Default ovgear chrome at 1280x720, layout from
# ``write_split_ini`` (no persisted layout).
#
#   step 02 click target — "View" menu in the top menu bar. Menu
#   bar items (left to right): OvGear, File, Edit, Layer, Tools,
#   View, Window, Help. The "View" label is centred around (357, 16).
COORD_VIEW_MENU = (357, 16)
#   step 03 click target — "Light Theme" submenu item, second row
#   in the View menu (Focus Selected at y~58 / separator / Light
#   Theme / Dark Theme). Label centre sits at approximately (390, 74).
COORD_LIGHT_THEME = (390, 74)
#   step 05 click target — "Dark Theme" submenu item, one row below
#   "Light Theme" in the same View menu, ~y=90.
COORD_DARK_THEME = (390, 90)


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _shot(name: str) -> str:
    """Capture one screenshot at a numbered checkpoint."""
    path = f"{OUT_DIR}/{PREFIX}_{name}.png"
    uitesting.capture_screenshot(path)
    print(f"[step7-theme] {name}: {path}")
    return path


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    await _drive(40)

    # State 1: loaded, dark theme.
    _shot("01_dark")

    # Action 1: click the "View" menu in the menu bar.
    await uitesting.mouse_click(*COORD_VIEW_MENU)
    await _drive(5)
    # State 2: View menu open with Light/Dark theme items visible.
    _shot("02_view_menu_dark")

    # Action 2: click "Light Theme".
    await uitesting.mouse_click(*COORD_LIGHT_THEME)
    await _drive(15)
    # State 3: light theme applied.
    _shot("03_light")

    # Action 3: click the "View" menu again to re-open it.
    await uitesting.mouse_click(*COORD_VIEW_MENU)
    await _drive(5)
    # State 4: View menu open in light theme (proves palette
    # ``cl.*`` ids resolve correctly under both shades).
    _shot("04_view_menu_light")

    # Action 4: click "Dark Theme" to restore.
    await uitesting.mouse_click(*COORD_DARK_THEME)
    await _drive(15)
    # State 5: dark theme restored.
    _shot("05_dark_restored")

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
    ui.init("OvGear Step 7 QA-Theme", width=1280, height=720)
    # Register style sheets but do not call set_theme(...) here. Theme
    # state is changed exclusively through the View menu actions in
    # ``_main`` so the captured screenshots prove the user-visible
    # theme path, not a programmatic shortcut. ``apply_global_styles``
    # is the stylesheet registration step and is required before any
    # window opens; it does not switch the shade.
    apply_global_styles()
    ui.run(_main())

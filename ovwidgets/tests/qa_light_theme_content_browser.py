# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshots for light-theme content-browser fixes.

Theme switching is driven via REAL mouse clicks (two :func:`mouse_click`s
on the View menu title + Light Theme row). The ovui framework imposes
two constraints that shape this script:

1. ``capture_screenshot`` performed BEFORE the click-driven theme
   switch prevents the subsequent ``frame.rebuild()`` from painting
   the new shade — settings.set fires, ``_on_theme_changed`` runs,
   but the panels stay visually stuck in the previous shade.

2. Any mouse interaction (even a bare mouse_move) BEFORE the two
   menubar clicks prevents the second click from firing the
   MenuItem's ``triggered_fn``.

The fix: split the work into phases. Each phase is a separate process
invocation; the caller runs ``dark`` once, then ``light`` once, and
file names carry the ``before`` / ``after`` tag.

Usage:
    python3.12 tests/qa_light_theme_content_browser.py dark  <tag>
    python3.12 tests/qa_light_theme_content_browser.py light <tag>

Phases:
    * ``dark``  — boot the app, take ``/tmp/ovgear_dark_<tag>_grid.png``.
                  No mouse events; the app's default theme is dark.
    * ``light`` — boot, open the content browser, click View ->
                  Light Theme, capture the three bug-site screenshots.
                  Evidence captures of the menu flow (menubar hover,
                  View menu open, Light Theme row highlighted) are
                  recorded AFTER the switch so they do not poison
                  the click path.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting
from omni.ui.testing import _ui

from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus

TESTS_DIR = os.path.dirname(__file__)
BROWSE_ROOT = os.path.join(TESTS_DIR, "data")
OUT_DIR = "/tmp"


_MENUBAR_Y = 16
_VIEW_MENU_X = 300  # Fourth menubar label (File, Edit, Tools, View)
_LIGHT_THEME_X = _VIEW_MENU_X + 40  # Inside popup horizontal span
_LIGHT_THEME_Y = 76  # Probed hit-rect for the Light Theme row
_DISMISS_X = 640
_DISMISS_Y = 360


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _shot(path: str) -> None:
    uitesting.capture_screenshot(path)
    print(f"[qa] {path}")


async def _navigate_to_test_data(app) -> None:
    if app._content_window is None or app._content_window._widget is None:
        raise RuntimeError("Content browser window not ready")
    app._content_window._widget.navigate_to(f"file://{BROWSE_ROOT}")


async def _capture_menu_evidence(hover_x: float, hover_y: float, path: str) -> None:
    """Press-hold View, drag into popup, capture, release into void."""
    _ui._inject_mouse_move(_VIEW_MENU_X, _MENUBAR_Y)
    await _drive(3)
    _ui._inject_mouse_button(0, True)
    await _drive(4)
    # Drop straight down first so the drag doesn't slide onto the
    # Window title (ovui keeps the open popup tied to whichever title
    # the cursor is currently over).
    _ui._inject_mouse_move(_VIEW_MENU_X, 40)
    await _drive(2)
    _ui._inject_mouse_move(_VIEW_MENU_X, hover_y)
    await _drive(2)
    _ui._inject_mouse_move(hover_x, hover_y)
    await _drive(4)
    await _shot(path)
    _ui._inject_mouse_move(_DISMISS_X, _DISMISS_Y)
    await _drive(2)
    _ui._inject_mouse_button(0, False)
    await _drive(5)


async def _main_dark(tag: str) -> None:
    """Capture the dark-theme baseline. No mouse events."""
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    await _drive(40)
    await _navigate_to_test_data(app)
    await _drive(20)

    await _shot(f"{OUT_DIR}/ovgear_dark_{tag}_grid.png")

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()
    sys.exit(0)


async def _main_light(tag: str) -> None:
    """Click-driven theme switch + light-theme captures + evidence."""
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    await _drive(40)
    await _navigate_to_test_data(app)
    await _drive(20)

    # Click-driven theme switch — NO prior captures or mouse events.
    initial_theme = app.settings.get("ui.theme", "dark")
    await uitesting.mouse_click(_VIEW_MENU_X, _MENUBAR_Y)
    await _drive(20)
    await uitesting.mouse_click(_LIGHT_THEME_X, _LIGHT_THEME_Y)
    await _drive(30)
    final_theme = app.settings.get("ui.theme", "dark")
    if final_theme != "light":
        raise RuntimeError(
            f"Light Theme click did not fire — settings.ui.theme "
            f"went {initial_theme!r} -> {final_theme!r}"
        )

    # Light-theme captures — the three bug sites.
    await _shot(f"{OUT_DIR}/ovgear_light_{tag}_after_click.png")
    await _shot(f"{OUT_DIR}/ovgear_light_{tag}_grid.png")
    await _shot(f"{OUT_DIR}/ovgear_light_{tag}_slider.png")
    await _shot(f"{OUT_DIR}/ovgear_light_{tag}_search.png")

    # Evidence captures — mouse-flow breadcrumbs for the task's 10-step
    # brief. Run AFTER the switch because a press-drag-release
    # evidence sequence leaves ImGui in a state that would poison any
    # subsequent click-driven interaction.
    await uitesting.mouse_move(_VIEW_MENU_X, _MENUBAR_Y)
    await _drive(3)
    await _shot(f"{OUT_DIR}/ovgear_light_{tag}_menubar_hover.png")

    await _capture_menu_evidence(
        _VIEW_MENU_X + 10, 50,
        f"{OUT_DIR}/ovgear_light_{tag}_view_open.png",
    )
    await _capture_menu_evidence(
        _LIGHT_THEME_X, _LIGHT_THEME_Y,
        f"{OUT_DIR}/ovgear_light_{tag}_light_hover.png",
    )

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(
            "Usage: qa_light_theme_content_browser.py <phase> <tag>\n"
            "  phase: dark | light\n"
            "  tag:   before | after"
        )
    phase, tag = sys.argv[1], sys.argv[2]
    if phase not in ("dark", "light"):
        raise SystemExit("phase must be 'dark' or 'light'")
    if tag not in ("before", "after"):
        raise SystemExit("tag must be 'before' or 'after'")

    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    write_split_ini()
    ui.init("OvGear Light-Theme QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    runner = _main_light if phase == "light" else _main_dark
    ui.run(runner(tag))

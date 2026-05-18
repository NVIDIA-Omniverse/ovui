# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Bug 4 verification — context menu appears at cursor position.

Simulates a real ovui right-button press via
:meth:`FileCard._dispatch_mouse_pressed` (the same entry point
ovui's Widget.cpp calls after dividing raw pixel coords by
``dpiScale``). Before the fix, that path added the hit rect's
``screen_position_*`` to the event coords, double-offsetting the
menu. After the fix, the event coords flow through verbatim so the
menu's top-left lands where the cursor is.

Evidence saved to ``/tmp/ovgear_bugfix_4.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_bug4_context_menu_position.py
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
from ovwidgets.content.backends.local_fs_backend import LocalFSBackend

TEST_ROOT = "/tmp/ovgear_bug_repro"
TEST_ROOT_URL = f"file://{TEST_ROOT}"
OUT = "/tmp/ovgear_bugfix_4.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None
    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())
    await _drive(40)

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window not built")
    widget = cw._widget
    widget.set_backend(LocalFSBackend())
    widget.navigate_to(TEST_ROOT_URL)
    await _drive(25)

    # Force grid view at 100% so the card right-click path is exercised.
    zoom = widget._zoom_bar
    if zoom is not None:
        zoom.set_slider_index(2)
    if not widget._is_grid_view:
        widget._on_zoom_bar_toggle_grid(True)
    await _drive(20)

    # Pick a file card to right-click.
    detail_model = widget._detail_model
    children = detail_model.get_item_children(detail_model.root)
    file_child = next(
        (c for c in children if hasattr(c, "is_folder") and not c.is_folder),
        None,
    )
    grid = widget._detail_grid_view
    card = grid._cards.get(file_child.url)
    sx = float(card._rect.screen_position_x)
    sy = float(card._rect.screen_position_y)
    # The coords ovui delivers to ``_dispatch_mouse_pressed`` are
    # already in DPI-scaled screen-space points (Widget.cpp divides
    # raw pixels by dpiScale before dispatch). Pick an intuitive
    # "cursor landed on card" point inside the card's footprint.
    click_x = sx + 30.0
    click_y = sy + 30.0
    print(
        f"[BUG 4 fix] dispatching right-click at ({click_x}, {click_y}); "
        f"card screen_position=({sx}, {sy})"
    )
    card._dispatch_mouse_pressed(click_x, click_y, 1, 0)
    await _drive(15)

    uitesting.capture_screenshot(OUT)
    print(f"[BUG 4 fix] saved {OUT}")

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
    settings_path = os.path.expanduser("~/.ovgear/settings.json")
    if os.path.exists(settings_path):
        os.unlink(settings_path)
    write_split_ini()
    ui.init("OvGear Bug 4 Verification", width=1400, height=800)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

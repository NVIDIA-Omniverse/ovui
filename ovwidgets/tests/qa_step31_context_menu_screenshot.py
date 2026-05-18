# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 31 — right-click context menu.

One proof screenshot of the detail pane with a context menu showing:

* ``/tmp/ovgear_step31_1_context.png`` — content browser mounted at
  ``mock://Home/Documents/Projects``. A right-click on the
  ``demo.usda`` card pops the file context menu with Open, Copy URL,
  Cut, Copy, Rename, Delete entries.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step31_context_menu_screenshot.py
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
from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.common.selection import SelectionBus

OUT_CONTEXT = "/tmp/ovgear_step31_1_context.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Let the dockspace render, windows claim their dock nodes.
    await _drive(40)

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget

    # Swap to MockBackend and navigate to a folder that contains files
    # so the right-click target is a real file card.
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home/Documents/Projects")
    await _drive(15)
    widget._tree_tree_view.set_expanded(
        widget._tree_model._root, True, False,
    )
    await _drive(10)

    # Find the demo.usda item in the detail model.
    children = widget._detail_model.get_item_children(None)
    demo = next((c for c in children if c.name == "demo.usda"), None)
    if demo is None:
        raise RuntimeError("demo.usda not found in Projects folder")

    # Drive the widget's right-click handler directly. A real mouse
    # event would fire at the card's screen position; the standalone
    # screenshot harness does not synthesize mouse events reliably, so
    # we invoke the handler at plausible coordinates near the card.
    # The on_row_right_click path is the same one a delegate-row right-
    # click hits; it covers the menu-build + show_at pathway.
    grid = widget._detail_grid_view
    if grid is None or demo.url not in grid._cards:
        # Grid card not yet materialised — force a refresh tick.
        await _drive(10)
    card = grid._cards.get(demo.url) if grid is not None else None
    screen_x = 400.0
    screen_y = 300.0
    if card is not None and card._rect is not None:
        screen_x = float(card._rect.screen_position_x) + 20.0
        screen_y = float(card._rect.screen_position_y) + 20.0
    widget._on_grid_right_click(demo, screen_x, screen_y)
    # Give ovui a few frames to paint the popup before the screenshot.
    await _drive(10)

    uitesting.capture_screenshot(OUT_CONTEXT)
    print(f"Saved: {OUT_CONTEXT}")

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
    ui.init("OvGear Step 31 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

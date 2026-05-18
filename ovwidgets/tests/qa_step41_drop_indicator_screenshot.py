# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 41 — drop indicator.

Drives the indicator programmatically so the captured screenshot
shows the app mid-drag with one grid card in the
``Content.Card::drop_hover`` variant:

1. Launch the app, swap the content browser to :class:`MockBackend`,
   and navigate to ``mock://Home/Documents/Projects`` so the detail
   grid shows ``demo.usda`` / ``demo.usdc`` / ``readme.md``. The grid
   additionally holds a ``Textures`` folder sibling (visible after
   expand) so the screenshot can tint a folder card.
2. Reach into the widget's shared :class:`DropIndicator`, pick the
   ``Textures`` folder card from the grid's card dict, and call
   :meth:`DropIndicator.show_card_highlight(card)` so the card paints
   the drop-hover tint.
3. Screenshot the full app → ``/tmp/ovgear_step41_1_app.png`` with the
   ``Textures`` card clearly tinted in ``treeview_drop_indicator``
   colour — the same shade the Stage Browser's ``Stage.TreeView:drop``
   background uses.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step41_drop_indicator_screenshot.py
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

OUT_PATH = "/tmp/ovgear_step41_1_app.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Let the dockspace render.
    await _drive(40)

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget

    # Swap to MockBackend — the Home folder carries the Textures /
    # Documents / Models subtree which the screenshot uses to show a
    # real folder card lit up with the drop-hover tint.
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home")
    await _drive(20)
    widget._detail_model.get_item_children(None)
    await _drive(10)

    grid = widget._detail_grid_view
    if grid is None:
        raise RuntimeError("Grid view not built yet")

    # Pick the Textures folder card — a deterministic target the mock
    # backend always surfaces under mock://Home. The grid's card dict
    # is keyed by URL (see FileGridView._cards) so the lookup needs the
    # full URL, not the basename.
    target_url = "mock://Home/Textures"
    target_card = grid._cards.get(target_url)
    if target_card is None:
        # The grid builds cards lazily — nudge one more frame in case
        # the Textures tile hasn't materialised yet.
        await _drive(10)
        target_card = grid._cards.get(target_url)
    if target_card is None:
        raise RuntimeError(
            f"Target card for {target_url!r} not found in grid. "
            f"Available: {list(grid._cards)}"
        )

    # Light the card via the indicator — simulates the state the card
    # would be in during a drag-over when ``_accept_drop`` returns True.
    indicator = widget._drop_indicator
    if indicator is None:
        raise RuntimeError("DropIndicator missing on widget")
    indicator.show_card_highlight(target_card)
    await _drive(15)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")

    # Release the highlight so the app exits in a clean state.
    indicator.clear()
    await _drive(2)

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
    ui.init("OvGear Step 41 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

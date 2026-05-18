# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 24 — grid view + zoom bar wiring.

Three proof screenshots of the detail pane with the new grid view and
zoom-bar controls:

* ``/tmp/ovgear_step24_1_grid.png`` — content browser mounted at
  ``mock://Home``. Grid view is the default; file cards tile the
  detail pane; zoom-bar sits at the bottom with the slider at
  position 2 (100%) and the list-view toggle icon.
* ``/tmp/ovgear_step24_2_list.png`` — after the zoom-bar toggle flip
  to list view. The three-column TreeView (Name / Size / Date) now
  renders in the detail pane; the zoom-bar icon flips to grid.
* ``/tmp/ovgear_step24_3_zoomed.png`` — back in grid view with the
  slider moved to position 4 (scale 1.5, 150%). Cards are
  noticeably larger.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step24_grid_zoom_screenshot.py
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

OUT_GRID = "/tmp/ovgear_step24_1_grid.png"
OUT_LIST = "/tmp/ovgear_step24_2_list.png"
OUT_ZOOMED = "/tmp/ovgear_step24_3_zoomed.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Let the dockspace render, windows claim their dock nodes, the
    # two content models populate their initial LocalFS roots.
    await _drive(40)

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget

    # Swap to MockBackend so the screenshot doesn't depend on the
    # developer's local filesystem; mock://Home has Documents,
    # Textures, Scripts — enough variety to populate a grid of cards.
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home")
    await _drive(10)
    widget._tree_tree_view.set_expanded(widget._tree_model._root, True, False)
    await _drive(15)

    # Screenshot 1 — grid view with default scale (index 2 → 100%).
    uitesting.capture_screenshot(OUT_GRID)
    print(f"Saved: {OUT_GRID}")

    # Screenshot 2 — after the toggle-button click, list view is shown.
    widget._zoom_bar._on_toggle_click()
    await _drive(10)
    uitesting.capture_screenshot(OUT_LIST)
    print(f"Saved: {OUT_LIST}")

    # Screenshot 3 — back in grid view, slider at index 4 (scale 1.5,
    # 150%). Cards render larger than the default state.
    widget._zoom_bar._on_toggle_click()  # flip back to grid
    await _drive(5)
    widget._zoom_bar._slider.model.set_value(4)
    await _drive(15)
    uitesting.capture_screenshot(OUT_ZOOMED)
    print(f"Saved: {OUT_ZOOMED}")

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
    ui.init("OvGear Step 24 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

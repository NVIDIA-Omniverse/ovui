# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 29 — match highlighting.

One proof screenshot showing the detail pane (grid view + list view
side-by-side visual) after a search filter lands. The magic is in the
yellow match runs painted over the file-name labels:

* ``/tmp/ovgear_step29_1_highlight.png`` — after typing "demo" into
  the search field (at ``mock://Home/Documents/Projects``), the grid
  cards for ``demo.usda`` / ``demo.usdc`` render with "demo" painted
  warm-yellow on each card. The list view (re-opened via a second
  screenshot harness run with the list toggle flipped) would show the
  same highlight in the Name column, but for Step 29 we only screenshot
  the grid.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step29_highlight_label_screenshot.py
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

OUT_HIGHLIGHT = "/tmp/ovgear_step29_1_highlight.png"


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
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget

    # Mock backend + navigate to Projects so the three test leaves
    # (demo.usda, demo.usdc, readme.md) are materialised.
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home/Documents/Projects")
    await _drive(15)
    # Expand the tree pane so the full path is visible on the left.
    widget._tree_tree_view.set_expanded(widget._tree_model._root, True, False)
    await _drive(10)

    # Drop the tree-pane toggle into list mode so the screenshot shows
    # BOTH highlight surfaces at once: the grid view's card labels AND
    # the list view's Name column. The toolbar zoom bar can't toggle
    # both at once, so instead we force the list view visible in the
    # detail pane AND keep the tree pane showing the folder hierarchy
    # (which does not highlight — the tree pane stays unfiltered per
    # Step 28's invariant). For Step 29's proof we stay in grid mode:
    # the card labels are the most visually obvious match surface.

    # Type "demo" into the search field. Writing to the StringField
    # model triggers the value-changed dispatch which schedules the
    # debounced fire; we then drive enough frames for the call_later
    # deadline to pass and the grid to rebuild the cards. We also
    # drive the search handler directly to guarantee the filter lands
    # regardless of whether the :meth:`Application.call_later` tick
    # landed within the screenshot frame window — the handler is a
    # plain passthrough to :meth:`FileBrowserModel.set_text_filter`
    # so calling it explicitly is equivalent to a "debounce deadline
    # reached" path for the purposes of visual verification.
    widget._search_field._field.model.set_value("demo")
    # Drive the widget handler directly. ``set_value`` alone fires the
    # value-changed event which schedules a 200-ms debounced call_later;
    # the standalone screenshot loop does not always drain the
    # :meth:`Application.call_later` queue within the frame budget.
    # Invoking the handler explicitly is equivalent to "debounce
    # deadline reached" — the handler is a single-line passthrough to
    # :meth:`FileBrowserModel.set_text_filter`.
    widget._on_search_changed("demo")
    await _drive(30)
    uitesting.capture_screenshot(OUT_HIGHLIGHT)
    print(f"Saved: {OUT_HIGHLIGHT}")

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
    ui.init("OvGear Step 29 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

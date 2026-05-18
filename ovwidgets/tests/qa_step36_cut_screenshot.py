# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 36 — Cut style on a card.

Drives the Cut flow to capture the dimmed ``::cut`` style on a file
card:

1. Launch the app, swap to :class:`MockBackend`, navigate to
   ``mock://Home/Documents/Projects`` so the grid shows three files.
2. Cut ``demo.usda`` via :meth:`FileContextMenu._cut_items` — writes
   the URL into the clipboard with ``is_cut=True`` and refreshes the
   cut style so the card repaints dimmed.
3. Screenshot the grid with the cut card visible →
   ``/tmp/ovgear_step36_1_cut.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step36_cut_screenshot.py
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

OUT_CUT = "/tmp/ovgear_step36_1_cut.png"


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

    # Swap to MockBackend at mock://Home/Documents/Projects so the grid
    # shows the three demo files the default tree ships with.
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home/Documents/Projects")
    await _drive(15)
    widget._detail_model.get_item_children(None)
    await _drive(5)

    # Resolve ``demo.usda`` and fire the context-menu Cut helper — the
    # harness can't synthesize a real right-click, so drive the helper
    # directly. The downstream clipboard + refresh-cut-style path is
    # identical to what a real menu click runs.
    demo = widget._detail_model.resolve(
        "mock://Home/Documents/Projects/demo.usda",
    )
    if demo is None:
        raise RuntimeError("demo.usda did not resolve under mock tree")

    ctx = widget._context_menu
    if ctx is None:
        raise RuntimeError("Context menu not constructed")
    ctx._cut_items([demo])
    await _drive(15)

    uitesting.capture_screenshot(OUT_CUT)
    print(f"Saved: {OUT_CUT}")

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
    ui.init("OvGear Step 36 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

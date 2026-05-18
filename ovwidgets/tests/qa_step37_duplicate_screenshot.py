# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 37 — Duplicate.

Drives the Duplicate flow to capture the original + copy side-by-side
in the grid:

1. Launch the app, swap to :class:`MockBackend`, navigate to
   ``mock://Home/Documents/Projects`` so the grid shows three files.
2. Duplicate ``demo.usda`` via
   :meth:`FileContextMenu._duplicate_items` — copies into the same
   folder as ``demo Copy.usda``.
3. Refresh the detail model so the new row materialises, then
   screenshot the grid with both ``demo.usda`` and ``demo Copy.usda``
   visible → ``/tmp/ovgear_step37_1_duplicate.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step37_duplicate_screenshot.py
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

OUT_DUPLICATE = "/tmp/ovgear_step37_1_duplicate.png"


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

    # Resolve ``demo.usda`` and fire the context-menu Duplicate helper —
    # the harness can't synthesize a real right-click or Ctrl+D, so
    # drive the helper directly. The downstream file_ops.duplicate_items
    # path + detail-model refresh is identical to what the keyboard /
    # menu dispatch runs.
    demo = widget._detail_model.resolve(
        "mock://Home/Documents/Projects/demo.usda",
    )
    if demo is None:
        raise RuntimeError("demo.usda did not resolve under mock tree")

    ctx = widget._context_menu
    if ctx is None:
        raise RuntimeError("Context menu not constructed")
    ctx._duplicate_items([demo])
    await _drive(15)

    # Force a fresh populate so the new ``demo Copy.usda`` row shows in
    # the grid. ``_duplicate_items`` schedules a refresh of the parent
    # (via _refresh_parent_after_create); drive a few frames so the
    # refresh fires before we capture.
    widget._detail_model.refresh_all()
    await _drive(10)

    uitesting.capture_screenshot(OUT_DUPLICATE)
    print(f"Saved: {OUT_DUPLICATE}")

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
    ui.init("OvGear Step 37 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

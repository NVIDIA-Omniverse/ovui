# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 38 — internal drag-drop.

Drives a programmatic drop so the rendered grid shows a file that has
been moved from one folder to another via the Step-38 drop path:

1. Launch the app, swap to :class:`MockBackend`, navigate to
   ``mock://Home/Documents/Projects`` so the grid shows three files.
2. Invoke :meth:`FileBrowserModel.drop` with a source URL from
   ``mock://Home/Textures`` targeting the Projects folder (the model's
   root). This exercises the production drop code path end-to-end —
   the same method a user's mouse drop resolves to in the running app.
3. Refresh the detail model so the dropped row materialises, then
   screenshot the grid with the newly-moved file visible →
   ``/tmp/ovgear_step38_1_dragdrop.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step38_dragdrop_screenshot.py
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

OUT_DROP = "/tmp/ovgear_step38_1_dragdrop.png"


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

    # Swap to MockBackend at mock://Home/Documents/Projects. Grid shows
    # the Step-3 demo files (demo.usda, demo.usdc, readme.md).
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home/Documents/Projects")
    await _drive(15)
    widget._detail_model.get_item_children(None)
    await _drive(5)

    # Simulate a drag of concrete.png from mock://Home/Textures into
    # the current folder (Projects). The harness cannot synthesize a
    # real mouse drop but the drop method on the model is the same
    # entry point ovui's drop event routes to — the subsequent refresh
    # mirrors what the live UI does after a successful drop.
    src_url = "mock://Home/Textures/concrete.png"
    widget._dispatch_drop(target_item=None, mime=src_url)
    await _drive(15)

    # Refresh so the new row materialises immediately in the grid.
    widget._detail_model.refresh_all()
    await _drive(10)

    uitesting.capture_screenshot(OUT_DROP)
    print(f"Saved: {OUT_DROP}")

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
    ui.init("OvGear Step 38 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

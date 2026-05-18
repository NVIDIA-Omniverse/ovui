# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 34 — Delete dialog.

Drives the end-to-end Delete confirm flow:

1. Launch the app, swap to :class:`MockBackend`, navigate to
   ``mock://Home/Documents/Projects``.
2. Invoke :meth:`FileContextMenu._begin_delete` on the ``demo.usda``
   file — pops the live :class:`ConfirmDeleteDialog` with a single URL
   rendered in the scrollable list.
3. Screenshot the dialog open over the browser grid →
   ``/tmp/ovgear_step34_1_delete.png``.
4. Fire the dialog's Yes handler to commit the delete; screenshot the
   grid after the file vanishes → ``/tmp/ovgear_step34_2_after_delete.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step34_delete_screenshot.py
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

OUT_DIALOG = "/tmp/ovgear_step34_1_delete.png"
OUT_AFTER = "/tmp/ovgear_step34_2_after_delete.png"


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

    # Resolve the ``demo.usda`` file and open the confirm-delete dialog
    # via the context menu's helper. The harness can't synthesize a real
    # right-click reliably, so drive the helper directly — the downstream
    # dialog code path is the same one a real right-click follows.
    demo = widget._detail_model.resolve(
        "mock://Home/Documents/Projects/demo.usda",
    )
    if demo is None:
        raise RuntimeError(
            "demo.usda did not resolve under mock tree",
        )

    ctx = widget._context_menu
    if ctx is None:
        raise RuntimeError("Context menu not constructed")
    ctx._begin_delete(demo)
    await _drive(10)

    dlg = ctx._confirm_delete_dialog
    if dlg is None:
        raise RuntimeError("Confirm Delete dialog did not open")

    uitesting.capture_screenshot(OUT_DIALOG)
    print(f"Saved: {OUT_DIALOG}")

    # Fire Yes and screenshot the browser after the file lands in the
    # backend's deleted set.
    dlg._fire_yes_for_test()
    await _drive(15)
    uitesting.capture_screenshot(OUT_AFTER)
    print(f"Saved: {OUT_AFTER}")

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
    ui.init("OvGear Step 34 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

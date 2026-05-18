# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 32 — Create Folder dialog.

Drives the end-to-end Create Folder flow:

1. Launch the app, swap to :class:`MockBackend`, navigate to
   ``mock://Home/Documents``.
2. Invoke :meth:`FileContextMenu._open_create_folder_dialog` with
   ``item=None`` (empty-space create) — pops the live
   :class:`SimpleInputDialog`.
3. Overwrite the field value to ``"Step32Folder"`` and screenshot the
   dialog open over the browser grid → ``/tmp/ovgear_step32_1_create_folder.png``.
4. Fire the dialog's OK handler to commit the create; screenshot the
   grid showing the new ``Step32Folder`` card.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step32_create_folder_screenshot.py
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

OUT_DIALOG = "/tmp/ovgear_step32_1_create_folder.png"
OUT_AFTER = "/tmp/ovgear_step32_2_after_create.png"


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

    # Swap to MockBackend at mock://Home/Documents so the grid has a
    # recognisable set of children to sit behind the dialog.
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home/Documents")
    await _drive(15)
    widget._detail_model.get_item_children(None)
    await _drive(5)

    # Open the Create Folder dialog via the empty-space handler. The
    # harness can't synthesize a real right-click reliably, so drive the
    # context menu's helper directly — the downstream dialog code path
    # is the same one a real right-click follows.
    ctx = widget._context_menu
    if ctx is None:
        raise RuntimeError("Context menu not constructed")
    ctx._open_create_folder_dialog(None)
    await _drive(10)

    # Set the dialog's field value to a clearly-visible name and capture
    # the popup.
    dlg = ctx._input_dialog
    if dlg is None:
        raise RuntimeError("Create Folder dialog did not open")
    dlg._set_value_for_test("Step32Folder")
    await _drive(5)

    uitesting.capture_screenshot(OUT_DIALOG)
    print(f"Saved: {OUT_DIALOG}")

    # Fire OK and screenshot the browser after the new folder lands.
    dlg._fire_ok_for_test()
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
    ui.init("OvGear Step 32 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

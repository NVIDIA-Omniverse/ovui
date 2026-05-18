# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 52 — save-mode overwrite confirm.

Captures a screenshot of :class:`ConfirmOverwriteDialog` constructed
with the Step-52 save surface (``on_yes=...``), opened over a
:class:`FilePickerDialog` configured for save ("Save File" title,
"Save" Apply button) so the dialog renders with the expected "File
already exists. Overwrite?" prompt and Yes / No buttons only.

Saves to ``/tmp/ovgear_step52_1_overwrite.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step52_overwrite_screenshot.py
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
from ovwidgets.content import FilePickerDialog
from ovwidgets.content.widget import ConfirmOverwriteDialog

OUT_PATH = "/tmp/ovgear_step52_1_overwrite.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Wait for the main window panels to be built + docked.
    await _drive(40)

    backend = MockBackend()
    captured: list = []

    def _on_apply(filename: str, dirname: str) -> None:
        captured.append(("apply", filename, dirname))

    def _on_cancel(filename: str, dirname: str) -> None:
        captured.append(("cancel", filename, dirname))

    # Open a save-style file picker so the overwrite confirm lands in
    # context (modal on top of the picker, as it would during a real
    # Save-As flow — architecture §23.9).
    dialog = FilePickerDialog(
        title="Save File",
        backend=backend,
        start_url="mock://Home/Documents/Projects",
        apply_button_label="Save",
        cancel_button_label="Cancel",
        on_apply=_on_apply,
        on_cancel=_on_cancel,
        file_extension_types=[
            ("*.usd, *.usda, *.usdc, *.usdz", "USD Files"),
            ("*.*", "All files"),
        ],
        initial_filename="demo.usda",
    )
    dialog.show()

    # Let the picker's modal + embedded widget + FileBar render.
    await _drive(20)

    # Drive a grid selection on the existing demo.usda so the filename
    # field shows the collision-target and the picker painting matches
    # "user is about to Save over an existing file".
    detail_model = dialog.widget.get_detail_model()
    children = detail_model.get_item_children(detail_model.root)
    demo_usda = next(c for c in children if c.name == "demo.usda")
    dialog.widget._detail_grid_view.set_selection([demo_usda])
    dialog.widget._on_grid_click(demo_usda, 0, 0)
    await _drive(10)

    # Spawn the save-mode overwrite confirm. Step 54 will wire this
    # automatically from the save wrapper; here we drive it directly so
    # the screenshot shows exactly the Step-52 surface.
    overwrote: list = []

    def _on_yes() -> None:
        overwrote.append(True)

    confirm = ConfirmOverwriteDialog(
        url="demo.usda",
        on_yes=_on_yes,
    )
    confirm.show()

    # Let the modal paint over the picker.
    await _drive(15)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")
    print(f"Confirm dialog is_open: {confirm.is_open}")
    print(f"Confirm dialog message: {confirm.message!r}")
    print(f"Confirm dialog url: {confirm.url!r}")
    print(f"Confirm dialog multi: {confirm.multi}")

    await _drive(2)

    confirm.destroy()
    dialog.destroy()

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
    ui.init("OvGear Step 52 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

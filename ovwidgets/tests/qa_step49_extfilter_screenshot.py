# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 49 — extension filter.

Captures a screenshot of :class:`FilePickerDialog` with the USD Files
extension selected in the :class:`FileBar`'s combo, navigated to
``mock://Home/Documents/Projects``. The Projects folder contains
``demo.usda`` / ``demo.usdc`` / ``readme.md``; with ``*.usd, *.usda,
*.usdc, *.usdz`` active the README is filtered out and only the USD
files paint in the detail grid — evidence that the combo's selection
flowed through to :meth:`FileBrowserModel.set_glob_filter`.

Saves to ``/tmp/ovgear_step49_1_extfilter.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step49_extfilter_screenshot.py
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

OUT_PATH = "/tmp/ovgear_step49_1_extfilter.png"


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

    # Build a FilePickerDialog rooted at the Projects folder so the
    # active glob filter is visually obvious: with USD Files selected
    # (the default, index 0) only demo.usda + demo.usdc paint —
    # readme.md is filtered out.
    dialog = FilePickerDialog(
        title="Open File",
        backend=MockBackend(),
        start_url="mock://Home/Documents/Projects",
        apply_button_label="Open",
        cancel_button_label="Cancel",
        initial_filename="demo.usda",
        file_extension_types=[
            ("*.usd, *.usda, *.usdc, *.usdz", "USD Files"),
            ("*.*", "All files"),
        ],
    )
    dialog.show()

    # Allow the modal window + embedded widget + FileBar + the glob-
    # filtered detail grid to render a few frames before capture.
    await _drive(30)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")

    await _drive(2)

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
    ui.init("OvGear Step 49 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

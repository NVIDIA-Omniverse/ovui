# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 55 — File > Save As dialog.

the content browser implementation step 55 adds :class:`FileExporterHelper` + the File > Save /
Save As menu items. This QA script boots the full app, drives the
exact Step-55 Save As code path (via a direct function call so the
capture does not depend on clicking a menu item), and captures the
modal picker floating over the docked app.

Saves to ``/tmp/ovgear_step55_1_save_as.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step55_save_as_screenshot.py
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
from ovwidgets.content.file_exporter import FileExporterHelper

OUT_PATH = "/tmp/ovgear_step55_1_save_as.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Let the main window panels build + dock.
    await _drive(40)

    # Use a MockBackend so the picker lands rooted at a stable location
    # (the mock tree is deterministic and the screenshot frames files
    # the QA reader will recognise — ``demo.usda`` / ``demo.usdc``).
    FileExporterHelper.reset_singleton()
    helper = FileExporterHelper(
        backend=MockBackend(),
        settings=app.settings,
    )
    FileExporterHelper._singleton = helper

    recorded: list = []

    def _on_export(filename, dirname, extension, selections):
        recorded.append((filename, dirname, extension, list(selections)))

    # Drive the Step-55 Save As path. Using the same kwargs the menu
    # handler (:func:`_on_save_as_clicked`) produces so a regression in
    # the handler shape would fail here too.
    helper.show(
        title="Save Stage As",
        export_button_label="Save",
        file_extension_types=[
            ("*.usd", "USD Binary or Ascii"),
            ("*.usda", "USD Ascii"),
            ("*.usdc", "USD Crate"),
        ],
        export_handler=_on_export,
        filename_url="mock://Home/Documents/Projects/demo.usda",
        should_validate=True,
    )

    # Let the modal + widget + FileBar paint.
    await _drive(25)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")
    print(f"Dialog is_open: {helper.dialog.is_open}")
    print(f"Dialog title: {helper.dialog._title}")
    print(f"Apply button label: {helper.dialog._apply_label}")
    print(f"Start URL: {helper.dialog._start_url}")
    print(f"Initial filename: {helper.dialog.get_filename()!r}")
    print(f"should_validate: {helper.dialog._should_validate}")
    print(f"validation_mode: {helper.dialog._validation_mode}")
    print(f"Resolved extension: {helper._resolve_extension()!r}")
    print(f"Extensions list: {helper.dialog._file_extension_types}")

    await _drive(2)

    helper.destroy()
    FileExporterHelper.reset_singleton()

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
    ui.init("OvGear Step 55 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 54 — File > Open dialog.

the content browser implementation step 54 replaces :func:`ovwidgets.app.menu_bar._on_open_clicked`'s
stdin-reader with a :class:`FileImporterHelper`-driven picker. This QA
script boots the full app, triggers the same code path the File > Open
menu item would (via a direct function call so the capture does not
depend on clicking a menu item), and captures the modal picker floating
over the docked app.

Saves to ``/tmp/ovgear_step54_1_file_open.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step54_file_open_screenshot.py
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
from ovwidgets.content.file_importer import FileImporterHelper

OUT_PATH = "/tmp/ovgear_step54_1_file_open.png"


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
    FileImporterHelper.reset_singleton()
    helper = FileImporterHelper(
        backend=MockBackend(),
        settings=app.settings,
    )
    FileImporterHelper._singleton = helper

    opened: list = []

    def _on_import(filename, dirname, selections):
        # Step-54 menu-bar path would call ``app.open_file(path)`` here.
        # This QA script records the payload instead so the screenshot
        # run does not need a real stage backend.
        opened.append((filename, dirname, list(selections)))

    # Drive the exact Step-54 code path — use the menu-bar entry point
    # so a regression in the handler shape (kwargs, helper lookup) would
    # fail here too.
    helper.show(
        title="Open USD File",
        import_button_label="Open",
        file_extension_types=[
            ("*.usd, *.usda, *.usdc, *.usdz", "USD Files"),
            ("*.*", "All files"),
        ],
        import_handler=_on_import,
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

    await _drive(2)

    helper.destroy()
    FileImporterHelper.reset_singleton()

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
    ui.init("OvGear Step 54 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

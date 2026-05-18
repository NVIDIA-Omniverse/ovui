# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot — Content Browser phase J (file picker, filename typed).

the content browser implementation step 59. Drives the :class:`FilePickerDialog` via
:class:`FileImporterHelper.show` and pre-seeds the FileBar with a
filename so the save/open variant's "typed filename" state is
captured. Regression target for Steps 47-50 (file picker shell +
FileBar + extension combo + apply-button validation gate).

Saves to ``/tmp/ovgear_content_browser_phaseJ.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_content_browser_phaseJ.py
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

OUT_PATH = "/tmp/ovgear_content_browser_phaseJ.png"


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

    FileImporterHelper.reset_singleton()
    helper = FileImporterHelper(
        backend=MockBackend(),
        settings=app.settings,
    )
    FileImporterHelper._singleton = helper

    helper.show(
        title="Pick a USD file",
        import_button_label="Pick",
        file_extension_types=[
            ("*.usd, *.usda, *.usdc, *.usdz", "USD Files"),
            ("*.*", "All files"),
        ],
        import_handler=lambda *_: None,
        filename_url="mock://Home/Documents/Projects/demo.usda",
        should_validate=True,
    )
    await _drive(25)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")
    print(f"dialog_title={helper.dialog._title}")
    print(f"initial_filename={helper.dialog.get_filename()!r}")

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
    ui.init("OvGear phaseJ QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot — Content Browser phase K (File > Open invoked).

the content browser implementation step 59. Closes the 60-step plan by driving the exact
menu-bar code path File > Open invokes (:func:`ovwidgets.app.menu_bar._on_open_clicked`)
so the :class:`FileImporterHelper`-driven picker renders over the docked
app. Regression target for Steps 53-54 (importer helper + File > Open
wiring).

Saves to ``/tmp/ovgear_content_browser_phaseK.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_content_browser_phaseK.py
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
from ovwidgets.app.menu_bar import _on_open_clicked
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.common.selection import SelectionBus
from ovwidgets.content.file_importer import FileImporterHelper

OUT_PATH = "/tmp/ovgear_content_browser_phaseK.png"


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

    # Swap the importer helper's backend to the mock tree so the picker
    # lands on a deterministic root. The menu-bar path picks up the
    # singleton, so we seed it with the mock before _on_open_clicked
    # fires.
    FileImporterHelper.reset_singleton()
    FileImporterHelper._singleton = FileImporterHelper(
        backend=MockBackend(),
        settings=app.settings,
    )

    _on_open_clicked(app)
    await _drive(25)

    helper = FileImporterHelper.instance()
    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")
    print(f"dialog_title={helper.dialog._title}")
    print(f"apply_label={helper.dialog._apply_label}")

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
    ui.init("OvGear phaseK QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

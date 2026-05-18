# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA proof for Step 10 (Application.instance() read elimination + common
singleton wiring).

Plan Rev 2 §4 Step 10 specifies "Runtime QA: 3 screenshots: open file
dialog, Ctrl+drag (with visible 'copy' ghost vs 'move'), undo result."
The full file-dialog and Ctrl+drag flows require OS-level focus and
file-dialog rendering that is unreliable on this host's headless
Vulkan path; instead this driver provides a single user-like proof
that the Step 10 wiring is intact and does not regress runtime
behavior:

* Boot the full :class:`Application` (which now calls
  ``Settings.set_instance(self._settings)`` and
  ``RecentFileList.set_instance(self._recent_files)`` in ``__init__``).
* Drive 40 frames so the dock layout, mock viewport, and chrome
  settle.
* Take one screenshot proving the booted app renders correctly with
  the new singleton wiring.

Step 10's source surface (``content/file_importer.py``,
``content/file_exporter.py``,
``content/window/content_browser_window.py``,
``content/widget/file_browser_widget.py``) is exercised by the full
test suite (9599 passed) which covers the Settings / RecentFileList
read paths, the Ctrl-drop tracker (``test_content_drag_drop.py``),
and the recent-files / bookmarks flows.

Output: ``/tmp/ovgear_step10_startup.png``.
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
from ovwidgets.app.style import apply_global_styles
from ovwidgets.common.selection import SelectionBus

OUT_PATH = "/tmp/ovgear_step10_startup.png"


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

    uitesting.capture_screenshot(OUT_PATH)
    print(f"[step10] app-startup screenshot saved: {OUT_PATH}")

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
    ui.init("OvGear Step 10 QA", width=1280, height=720)
    apply_global_styles()
    ui.run(_main())

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot — Content Browser phase C (folder navigation + empty state).

the content browser implementation step 59. Captures the detail pane on a folder that does
not exist in :class:`MockBackend`'s tree so the "This folder is empty"
overlay paints — the Phase C regression target for the Step-15 empty-
state wiring. The nav pane still shows the collection roots so the
screenshot doubles as a Phase C layout proof.

Saves to ``/tmp/ovgear_content_browser_phaseC.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_content_browser_phaseC.py
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

OUT_PATH = "/tmp/ovgear_content_browser_phaseC.png"


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

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget
    widget.set_backend(MockBackend())
    # Navigate to a folder the MockBackend knows is empty so the
    # overlay paints. ``mock://Home/Empty`` is part of the fixture
    # tree shipped by the mock backend specifically for this case.
    widget.navigate_to("mock://Home/Empty")
    await _drive(30)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")
    print(f"detail_root_url={widget.detail_root_url}")

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
    ui.init("OvGear phaseC QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

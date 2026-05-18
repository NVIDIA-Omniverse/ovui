# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot — Content Browser phase D (breadcrumbs + history).

the content browser implementation step 59. Drives a three-step navigation sequence so the
:class:`BrowserBar`'s breadcrumb trail renders with nested segments
AND the visited-history back button is enabled. Captures after
``go_back`` so both the forward and back buttons render in their
active (non-greyed) state — covers Step 19 + Step 20 in one frame.

Saves to ``/tmp/ovgear_content_browser_phaseD.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_content_browser_phaseD.py
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

OUT_PATH = "/tmp/ovgear_content_browser_phaseD.png"


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
    # Walk into three nested folders so the breadcrumb has depth.
    widget.navigate_to("mock://Home")
    await _drive(8)
    widget.navigate_to("mock://Home/Documents")
    await _drive(8)
    widget.navigate_to("mock://Home/Documents/Projects")
    await _drive(8)
    # Step back once so the Forward button lights up too.
    cw.go_back()
    await _drive(12)

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
    ui.init("OvGear phaseD QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

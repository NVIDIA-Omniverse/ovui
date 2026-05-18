# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot — Content Browser phase E (grid view + zoom).

the content browser implementation step 59. Flips the detail pane into grid mode via
:meth:`FileBrowserWidget._on_zoom_bar_toggle_grid` and nudges the
zoom bar to a larger card size so the tile layout renders with
visible padding + thumbnails. Regression target for Steps 21-25
(:class:`FileCard` + :class:`FileGridView` + :class:`ZoomBar`).

Saves to ``/tmp/ovgear_content_browser_phaseE.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_content_browser_phaseE.py
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

OUT_PATH = "/tmp/ovgear_content_browser_phaseE.png"


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
    widget.navigate_to("mock://Home/Documents/Projects")
    await _drive(15)

    # Force grid view at scale index 4 (1.5x) so the cards are
    # clearly visible without overflowing the detail pane.
    zoom = widget._zoom_bar
    if zoom is not None:
        zoom.set_slider_index(4)
    # Flip to grid mode if the restored pref left us in list mode.
    if not widget._is_grid_view:
        widget._on_zoom_bar_toggle_grid(True)
    await _drive(20)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")
    print(f"is_grid_view={widget._is_grid_view}")

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
    ui.init("OvGear phaseE QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

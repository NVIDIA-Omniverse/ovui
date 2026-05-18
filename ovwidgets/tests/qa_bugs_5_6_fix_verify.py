# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA verification for Bugs 5+6 fix — label clipping at each zoom level.

Launches the app, navigates to /tmp/ovgear_bug_repro (the bug reproduction
tree with long filenames), sets zoom to each of 0, 1, 2, 3 (50% / 75% /
100% / 125%) and captures a screenshot of the grid showing long-named
cards. At zoom levels that host the grid view, no label should paint past
its card's edge into the next column.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_bugs_5_6_fix_verify.py
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
from ovwidgets.common.selection import SelectionBus
from ovwidgets.content.backends.local_fs_backend import LocalFSBackend

TEST_ROOT_URL = "file:///tmp/ovgear_bug_repro"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _capture_at_zoom(widget, slider_index: int, out_path: str) -> None:
    zoom = widget._zoom_bar
    if zoom is not None:
        zoom.set_slider_index(slider_index)
    # Zoom 0 is list view; all others are grid view. Force grid for the
    # grid-view-relevant indices so the toggle reflects the slider value
    # rather than whatever the previous navigate left behind.
    if slider_index >= 1 and not widget._is_grid_view:
        widget._on_zoom_bar_toggle_grid(True)
    elif slider_index == 0 and widget._is_grid_view:
        widget._on_zoom_bar_toggle_grid(False)
    await _drive(20)

    # Select short.usd so we get a selection-rect visual we can check
    # against the long-named neighbours.
    detail_model = widget._detail_model
    grid = widget._detail_grid_view
    if detail_model is not None and grid is not None and widget._is_grid_view:
        children = detail_model.get_item_children(detail_model.root)
        short = next(
            (c for c in children if getattr(c, "name", "") == "short.usd"),
            None,
        )
        if short is not None:
            grid.set_selection([short])
    await _drive(5)

    uitesting.capture_screenshot(out_path)
    print(f"  saved {out_path} (slider_index={slider_index})")


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None
    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())
    await _drive(40)

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window not built")
    widget = cw._widget
    widget.set_backend(LocalFSBackend())
    widget.navigate_to(TEST_ROOT_URL)
    await _drive(25)

    # Composite screenshot showing the fix at the canonical zoom the
    # bug report singled out (zoom 1 → slider index 2 → 100%).
    await _capture_at_zoom(widget, 2, "/tmp/ovgear_bugfix_5_6.png")

    # Per-zoom evidence: 0 = list view (unaffected, but verify no
    # regression), 1 = 75%, 2 = 100% (the reported defect), 3 = 125%.
    for slider_index in (0, 1, 2, 3):
        await _capture_at_zoom(
            widget,
            slider_index,
            f"/tmp/ovgear_bugfix_5_6_zoom{slider_index}.png",
        )

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
    settings_path = os.path.expanduser("~/.ovgear/settings.json")
    if os.path.exists(settings_path):
        os.unlink(settings_path)
    write_split_ini()
    ui.init("OvGear Bug 5/6 Fix Verify", width=1400, height=800)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

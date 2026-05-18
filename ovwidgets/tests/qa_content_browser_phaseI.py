# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot — Content Browser phase I (nav collections populated).

the content browser implementation step 59. Captures the Step 42-46 navigation tree with all
three collection roots visible. Uses a curated /proc/mounts fixture so
My Computer has a short, screenshot-friendly mount list, and a
curated :class:`RecentFileList` so the Recent collection has both
reachable and missing rows.

Saves to ``/tmp/ovgear_content_browser_phaseI.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_content_browser_phaseI.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting

from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.common.recent_files import RecentFileList
from ovwidgets.common.selection import SelectionBus
from ovwidgets.content.widget import NavigationModel
from ovwidgets.content.widget.collections import disk_partitions as _dp

OUT_PATH = "/tmp/ovgear_content_browser_phaseI.png"

_FIXTURE_MOUNTS = [
    "/dev/sda1 / ext4 rw,relatime 0 0",
    "/dev/sda2 /boot ext4 rw,relatime 0 0",
    "/dev/sda3 /home ext4 rw,relatime 0 0",
]

_FIXTURE_RECENTS = [
    "mock://Home/Scripts/test.py",
    "mock://Home/Textures/metal.hdr",
    "mock://Home/Documents/Projects/demo.usda",
]


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    mounts_fd = tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix="_proc_mounts",
    )
    mounts_fd.write("\n".join(_FIXTURE_MOUNTS) + "\n")
    mounts_fd.close()
    _dp.MOUNTS_PATH = mounts_fd.name

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())
    await _drive(40)

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home")
    await _drive(15)

    recent_files = RecentFileList()
    for url in _FIXTURE_RECENTS:
        recent_files.add(url)
    app._settings.set("ui.recent_files", recent_files.get_ordered())

    new_nav = NavigationModel(
        widget._backend,
        recent_files=recent_files,
        settings=app._settings,
    )
    new_nav.set_on_navigate(widget._navigate_to_url)
    widget._navigation_model = new_nav
    if widget._tree_tree_view is not None:
        widget._tree_tree_view.model = new_nav
    await _drive(15)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")
    print(f"nav_roots={[c.name for c in new_nav.get_item_children(None)]}")

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
    ui.init("OvGear phaseI QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 45 — Add / Remove
Bookmark actions.

Drives the Step 45 flow end-to-end:

1. Launch the full app with the content browser docked.
2. Swap in a :class:`MockBackend` so the detail pane is deterministic.
3. Navigate to ``mock://Home/Documents``.
4. Invoke the Add-Bookmark flow on the toolbar star, committing the
   name ``Documents (via star)`` through the input dialog's OK hook.
5. Expand the Bookmarks nav collection and capture a screenshot at
   ``/tmp/ovgear_step45_1_bookmark_added.png`` showing the freshly
   added bookmark as a child under the Bookmarks root.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step45_bookmarks_action_screenshot.py
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
from ovwidgets.common.selection import SelectionBus
from ovwidgets.content.bookmarks import BookmarksManager
from ovwidgets.content.widget import NavigationModel
from ovwidgets.content.widget.bookmark_button import BookmarkButton
from ovwidgets.content.widget.collections import disk_partitions as _dp

OUT_PATH = "/tmp/ovgear_step45_1_bookmark_added.png"


# Curated /proc/mounts fixture (inherited from Step 43 / 44 QA): keeps
# My Computer's enumeration short so the Bookmarks expansion stays
# above the fold on the 1280×720 layout.
_FIXTURE_MOUNTS = [
    "/dev/sda1 / ext4 rw,relatime 0 0",
    "/dev/sda2 /boot ext4 rw,relatime 0 0",
    "/dev/sda3 /home ext4 rw,relatime 0 0",
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
    await _drive(20)

    # Build a fresh :class:`BookmarksManager` against the app's settings
    # so the added bookmark persists for the duration of the app's life.
    # Swap it into the widget's nav model + attach it to the widget so
    # the toolbar star can write into the same instance the nav pane
    # subscribes to.
    manager = BookmarksManager(app.settings)
    # Start clean — previous runs may have left bookmarks on disk.
    for name in list(manager.list().keys()):
        manager.remove(name)

    new_nav = NavigationModel(widget._backend, bookmarks=manager)
    new_nav.set_on_navigate(widget._navigate_to_url)
    widget._navigation_model = new_nav
    if widget._tree_tree_view is not None:
        widget._tree_tree_view.model = new_nav
    widget._bookmarks = manager
    # Re-build the bookmark button against the real manager. The widget
    # built its own button against a ``None`` manager at construction
    # time (this QA drives into a live window *after* the widget is
    # built, so the constructor already ran).
    if widget._bookmark_button is not None:
        widget._bookmark_button.destroy()
        widget._bookmark_button = None
    await _drive(5)

    # Navigate to the folder we're about to bookmark so the toolbar
    # star + detail pane are both pointed at the same URL.
    widget.navigate_to("mock://Home/Documents")
    await _drive(10)

    # Build a headless BookmarkButton bound to the same manager so the
    # Add Bookmark flow runs identically to the real toolbar click.
    # (Re-adding a live toolbar button mid-session would require
    # re-entering the widget's build context; driving the flow through
    # the Step 45 API is equivalent and keeps the screenshot focused
    # on the *result* — a new child appearing under Bookmarks.)
    star = BookmarkButton(
        manager=manager,
        backend=widget._backend,
        current_url="mock://Home/Documents",
    )
    try:
        star._fire_click_for_test()
        dlg = star._input_dialog
        if dlg is None:
            raise RuntimeError("Add Bookmark dialog did not open")
        dlg._set_value_for_test("Documents (via star)")
        dlg._fire_ok_for_test()
    finally:
        star.destroy()

    print("Bookmarks after add:", manager.list())

    # Expand the Bookmarks collection's chevron so the newly added
    # child renders in the screenshot. The row y-coordinate matches
    # the Step 44 QA harness — collection roots pin to the top of the
    # nav pane so their positions are stable.
    await _drive(10)
    await uitesting.mouse_click(268.0, 540.0)
    await _drive(30)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")

    await _drive(2)

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
    ui.init("OvGear Step 45 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

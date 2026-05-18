# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 44 — BookmarksCollection.

Captures a screenshot of the full app with the content browser's left
pane showing the ``Bookmarks`` collection *expanded*, so the Step-44
child enumeration (one :class:`FileItem` per bookmark registered with
:class:`BookmarksManager`) is visible alongside the other two
collection roots. Saves to ``/tmp/ovgear_step44_1_bookmarks.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step44_bookmarks_screenshot.py
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
from ovwidgets.common.settings import Settings
from ovwidgets.content.bookmarks import BookmarksManager
from ovwidgets.content.widget import NavigationModel
from ovwidgets.content.widget.collections import disk_partitions as _dp

OUT_PATH = "/tmp/ovgear_step44_1_bookmarks.png"


# Curated /proc/mounts fixture (inherited from Step 43 QA): keeps My
# Computer's enumeration short so the Bookmarks expansion stays above
# the fold on the 1280×720 layout. Without this, the container dev
# box has ~50 bind mounts that push Bookmarks off-screen.
_FIXTURE_MOUNTS = [
    "/dev/sda1 / ext4 rw,relatime 0 0",
    "/dev/sda2 /boot ext4 rw,relatime 0 0",
    "/dev/sda3 /home ext4 rw,relatime 0 0",
]


# Step-44 bookmark set. URLs point into MockBackend's default tree so
# the stat-based ``is_folder`` inference returns ``True`` for all
# three and the children render with the folder glyph.
_FIXTURE_BOOKMARKS = [
    ("Home", "mock://Home"),
    ("Documents", "mock://Home/Documents"),
    ("Shared", "mock://Shared"),
]


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    # Install curated /proc/mounts fixture so My Computer's children
    # don't flood the nav pane below Bookmarks.
    mounts_fd = tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix="_proc_mounts",
    )
    mounts_fd.write("\n".join(_FIXTURE_MOUNTS) + "\n")
    mounts_fd.close()
    _dp.MOUNTS_PATH = mounts_fd.name

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Let the dockspace render.
    await _drive(40)

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget

    # MockBackend keeps the detail pane populated with deterministic
    # rows and gives the BookmarksCollection's stat path real data to
    # resolve ``is_folder`` against for each bookmark URL.
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home")
    await _drive(20)

    # Build the :class:`BookmarksManager` with the fixture bookmarks
    # and swap in a :class:`NavigationModel` that references it. The
    # default nav model built by :class:`FileBrowserWidget` constructs
    # a :class:`BookmarksCollection` with ``manager=None``; for the
    # screenshot we want the real manager so the children actually
    # render.
    settings = Settings()
    manager = BookmarksManager(settings)
    for name, url in _FIXTURE_BOOKMARKS:
        manager.add(name, url)

    new_nav = NavigationModel(widget._backend, bookmarks=manager)
    new_nav.set_on_navigate(widget._navigate_to_url)
    widget._navigation_model = new_nav
    if widget._tree_tree_view is not None:
        widget._tree_tree_view.model = new_nav
    await _drive(10)

    nav = widget._navigation_model
    if nav is None:
        raise RuntimeError("NavigationModel missing on widget")

    bookmarks = nav.find_collection("bookmarks")
    if bookmarks is None:
        raise RuntimeError("BookmarksCollection missing from nav model")

    tree_view = widget._tree_tree_view
    if tree_view is None:
        raise RuntimeError("Navigation TreeView missing from widget")

    # Expand the Bookmarks collection by clicking its chevron. The
    # nav pane's first row (Bookmarks) sits at y~540 on the 1280×720
    # layout; the chevron hit target is the first ~14px of the row.
    # Driving the click through :func:`uitesting.mouse_click` (rather
    # than :meth:`TreeView.set_expanded`) exercises the same ImGui
    # hover/press/release path a user click follows and invalidates
    # the TreeView's internal render cache — so the children actually
    # paint rather than just having their expanded flag set.
    await uitesting.mouse_click(268.0, 540.0)
    await _drive(30)

    children = bookmarks.get_children(widget._backend)
    print(
        "Bookmarks children ({}):".format(len(children)),
        [c.name for c in children],
    )
    await _drive(10)

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
    ui.init("OvGear Step 44 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

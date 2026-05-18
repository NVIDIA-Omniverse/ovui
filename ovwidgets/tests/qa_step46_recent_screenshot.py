# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 46 — RecentFilesCollection.

Captures a screenshot of the full app with the content browser's left
pane showing the ``Recent`` collection *expanded*, so the children
(one :class:`RecentFileItem` per entry in
:class:`ovwidgets.common.recent_files.RecentFileList`, most-recent-first) are
visible alongside the other two collection roots. Includes one missing
entry so the greyed-out variant also renders in the capture. Saves to
``/tmp/ovgear_step46_1_recent.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step46_recent_screenshot.py
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
from ovwidgets.content.widget.collections.recent import (
    RecentFilesCollection,
)

OUT_PATH = "/tmp/ovgear_step46_1_recent.png"


# Curated /proc/mounts fixture (inherited from Steps 43–45 QA): keeps
# My Computer's enumeration short so the Recent expansion stays above
# the fold on the 1280×720 layout.
_FIXTURE_MOUNTS = [
    "/dev/sda1 / ext4 rw,relatime 0 0",
    "/dev/sda2 /boot ext4 rw,relatime 0 0",
    "/dev/sda3 /home ext4 rw,relatime 0 0",
]


# Step-46 recent-files fixture. The first three URLs point into
# MockBackend's default tree — reachable, render as live rows. The
# fourth (``mock://gone/old_project.usd``) is intentionally unreachable
# so the greyed ``::missing`` variant also appears in the capture.
# :class:`RecentFileList.add` pushes to the head on every call, so the
# final ordering (top-down) is the reverse of the ``add`` sequence
# below.
_FIXTURE_RECENTS = [
    "mock://Home/Scripts/test.py",
    "mock://Home/Textures/metal.hdr",
    "mock://gone/old_project.usd",               # missing — greyed row
    "mock://Home/Documents/Projects/demo.usda",  # most recent
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

    # Swap in MockBackend so the Recent collection's stat probes hit a
    # deterministic tree (reachable URLs → ``is_missing=False``; the
    # synthetic ``mock://gone/…`` entry → ``is_missing=True``).
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home")
    await _drive(20)

    # Build a :class:`RecentFileList` with the fixture recents and
    # thread it through a fresh :class:`NavigationModel`. Mirrors
    # Step 45's swap pattern — the default widget builds with the
    # live :class:`Application._recent_files`, but the screenshot
    # wants a deterministic list that includes a missing entry.
    recent_files = RecentFileList()
    for url in _FIXTURE_RECENTS:
        recent_files.add(url)
    # Also write the snapshot into the real :class:`Settings` so a
    # future out-of-process repaint path is covered end-to-end.
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
    await _drive(10)

    nav = widget._navigation_model
    if nav is None:
        raise RuntimeError("NavigationModel missing on widget")

    recent = nav.find_collection("recent")
    if recent is None:
        raise RuntimeError("RecentFilesCollection missing from nav model")
    assert isinstance(recent, RecentFilesCollection)

    tree_view = widget._tree_tree_view
    if tree_view is None:
        raise RuntimeError("Navigation TreeView missing from widget")

    # Expand the Recent collection row. The default order is Bookmarks
    # / My Computer / Recent — Recent is the third root, so the
    # chevron sits ~44 px below Bookmarks' row. Click through
    # :func:`uitesting.mouse_click` so the TreeView's internal render
    # cache invalidates (same pattern as Step 44 / 45 QA harness).
    await uitesting.mouse_click(268.0, 584.0)
    await _drive(30)

    children = recent.get_children(widget._backend)
    print(
        "Recent children ({}):".format(len(children)),
        [(c.name, getattr(c, "is_missing", False)) for c in children],
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
    ui.init("OvGear Step 46 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

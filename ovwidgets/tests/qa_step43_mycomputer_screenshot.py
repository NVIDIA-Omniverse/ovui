# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 43 — MyComputerCollection.

Captures a screenshot of the full app with the content browser's left
pane showing the ``My Computer`` collection *expanded*, so the
Step-43 child enumeration (real mount points + user folders) is
visible alongside the other two (still-stub) collection roots. Saves to
``/tmp/ovgear_step43_1_mycomputer.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step43_mycomputer_screenshot.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tempfile

import omni.ui as ui
from omni.ui import testing as uitesting

from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.common.selection import SelectionBus
from ovwidgets.content.widget.collections import disk_partitions as _dp

OUT_PATH = "/tmp/ovgear_step43_1_mycomputer.png"

# Use a curated mount fixture for the screenshot so the nav pane
# shows a representative, pane-height-friendly list (a real desktop's
# /proc/mounts has ~5-10 entries; this CI / container dev box has 50+
# kernel bind mounts that would overflow the pane and hide the
# Step-43 feature under scrollable clutter). The fixture below
# mirrors what a typical Linux workstation would surface after the
# fstype filter runs: root + /boot + /home + an external mount.
_FIXTURE_MOUNTS = [
    "/dev/sda1 / ext4 rw,relatime 0 0",
    "/dev/sda2 /boot ext4 rw,relatime 0 0",
    "/dev/sda3 /home ext4 rw,relatime 0 0",
    "/dev/sdb1 /mnt/external ext4 rw,relatime 0 0",
    # Include a couple of fstype-filtered entries so the screenshot
    # implicitly proves the filter works (they should NOT appear in
    # the rendered tree).
    "tmpfs /run tmpfs rw 0 0",
    "proc /proc proc rw 0 0",
]


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    # Install curated mount fixture before the app / nav model reads
    # the module constant. Kept alive for the whole QA run via the
    # TemporaryDirectory held by the caller.
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
    # rows — the nav pane's MyComputerCollection enumerates the host's
    # real mounts / user folders regardless of which backend the
    # detail pane is rooted at.
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home")
    await _drive(20)

    nav = widget._navigation_model
    if nav is None:
        raise RuntimeError("NavigationModel missing on widget")

    my_computer = nav.find_collection("my-computer")
    if my_computer is None:
        raise RuntimeError("MyComputerCollection missing from nav model")

    tree_view = widget._tree_tree_view
    if tree_view is None:
        raise RuntimeError("Navigation TreeView missing from widget")

    # Expand My Computer by simulating a mouse click on its chevron.
    # The collection's first row (Bookmarks) sits at y~540 on the
    # 1280×720 layout — My Computer is the second root, so ~22px
    # below that; the chevron hit target is the first ~14px of the
    # row. Driving this through a real click (vs TreeView.set_expanded)
    # exercises the same ImGui hover/press/release path a user click
    # would follow and keeps the screenshot reproducible.
    await uitesting.mouse_click(268.0, 560.0)
    await _drive(30)

    children = my_computer.get_children(widget._backend)
    print(
        "My Computer children ({}):".format(len(children)),
        [c.name for c in children[:10]],
        "..." if len(children) > 10 else "",
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
    ui.init("OvGear Step 43 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

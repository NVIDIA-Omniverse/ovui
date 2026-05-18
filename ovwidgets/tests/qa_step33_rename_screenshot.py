# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 33 — Inline rename.

Drives the end-to-end rename flow:

1. Launch the app, swap to :class:`MockBackend`, navigate to
   ``mock://Home/Documents``.
2. Populate the detail model, resolve the ``Projects`` folder item.
3. Invoke :meth:`FileBrowserWidget.begin_rename(Projects)` — the grid
   card's label swaps for an inline :class:`ui.StringField` seeded
   with "Projects".
4. Screenshot the grid mid-rename ->
   ``/tmp/ovgear_step33_1_rename.png``.
5. Commit via :meth:`RenameController.commit_rename("ProjectsRenamed")`;
   screenshot the grid after the rename lands.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step33_rename_screenshot.py
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

OUT_RENAME = "/tmp/ovgear_step33_1_rename.png"
OUT_AFTER = "/tmp/ovgear_step33_2_after_rename.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Let the dockspace render.
    await _drive(40)

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget

    # Swap to MockBackend at mock://Home/Documents so the grid has a
    # recognisable set of children (Projects is the only folder there).
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home/Documents")
    await _drive(15)
    widget._detail_model.get_item_children(None)
    await _drive(5)

    # Find the Projects folder item, select it in the grid, and begin
    # the rename via the widget's public entry point — exercises the
    # exact same code path a Rename context-menu click would.
    projects = widget._detail_model.resolve(
        "mock://Home/Documents/Projects",
    )
    if projects is None:
        raise RuntimeError(
            "Projects folder not resolved in detail model",
        )
    widget._detail_grid_view.set_selection([projects])
    widget.begin_rename(projects)
    await _drive(10)

    uitesting.capture_screenshot(OUT_RENAME)
    print(f"Saved: {OUT_RENAME}")

    # Commit to "ProjectsRenamed" and screenshot the post-commit grid.
    widget._rename_controller.commit_rename("ProjectsRenamed")
    await _drive(15)
    uitesting.capture_screenshot(OUT_AFTER)
    print(f"Saved: {OUT_AFTER}")

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
    ui.init("OvGear Step 33 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

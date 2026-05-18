# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 15 — empty-state overlay.

Two proof screenshots of the detail-pane overlay:

* ``/tmp/ovgear_step15_1_normal.png`` — populated folder; the overlay
  is hidden and the TreeView shows the root's children.
* ``/tmp/ovgear_step15_2_empty.png`` — after navigating the widget to
  the ``mock://Shared`` empty folder. The overlay VStack renders the
  "This folder is empty" label (Content.EmptyState style) centered
  over the detail pane.

The MockBackend is swapped in via ``widget.set_backend`` so the
screenshot doesn't depend on the developer's local filesystem having
a predictably-empty folder.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step15_empty_state_screenshot.py
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

OUT_NORMAL = "/tmp/ovgear_step15_1_normal.png"
OUT_EMPTY = "/tmp/ovgear_step15_2_empty.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Let the dockspace render, windows claim their dock nodes, the
    # two content models populate their initial LocalFS roots.
    await _drive(40)

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget

    # Screenshot 1 — normal, populated folder. Swap to MockBackend and
    # navigate to Home so the detail pane shows Documents / Textures /
    # Scripts. The overlay should be hidden.
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home")
    await _drive(10)
    # Expand the root on both panes so their children are visible.
    widget._tree_tree_view.set_expanded(widget._tree_model._root, True, False)
    widget._detail_tree_view.set_expanded(
        widget._detail_model._root, True, False,
    )
    await _drive(10)

    uitesting.capture_screenshot(OUT_NORMAL)
    print(f"Saved: {OUT_NORMAL}")

    # Screenshot 2 — empty folder. Navigate to mock://Shared (the
    # designated empty folder in the default mock tree). The overlay
    # should show "This folder is empty" centered in the detail pane.
    widget.navigate_to("mock://Shared")
    await _drive(10)
    # Force an overlay re-evaluation so the label paints before the
    # screenshot is taken (model's deferred dispatch may still be
    # in-flight one frame after navigate_to).
    widget._update_empty_state()
    await _drive(10)

    uitesting.capture_screenshot(OUT_EMPTY)
    print(f"Saved: {OUT_EMPTY}")

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
    ui.init("OvGear Step 15 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

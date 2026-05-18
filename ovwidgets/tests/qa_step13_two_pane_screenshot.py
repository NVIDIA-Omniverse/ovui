# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 13 — two-pane layout.

Three proof screenshots:

* ``/tmp/ovgear_step13_1_initial.png`` — the full app with the Content
  panel showing the two-pane layout: folder-only tree on the left,
  three-column file detail on the right, 4px splitter between them.
* ``/tmp/ovgear_step13_2_expanded.png`` — after programmatically
  expanding root folders on both panes so the tree shows the folder
  hierarchy and the detail pane shows both files and folders with
  Name / Size / Date columns populated.
* ``/tmp/ovgear_step13_3_drilled.png`` — after navigating both panes
  to a sub-folder so the detail pane re-roots and the splitter's
  position is preserved.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step13_two_pane_screenshot.py
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

OUT_INITIAL = "/tmp/ovgear_step13_1_initial.png"
OUT_EXPANDED = "/tmp/ovgear_step13_2_expanded.png"
OUT_DRILLED = "/tmp/ovgear_step13_3_drilled.png"


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
    # two content models populate their initial roots.
    await _drive(40)

    # Screenshot 1 — initial state: both panes visible, splitter
    # between them, tree pane folder-only, detail pane three-column.
    uitesting.capture_screenshot(OUT_INITIAL)
    print(f"Saved: {OUT_INITIAL}")

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget

    # Expand the root on both panes so the hierarchy is visible.
    tree_view = widget._tree_tree_view
    detail_view = widget._detail_tree_view
    tree_model = widget._tree_model
    detail_model = widget._detail_model
    tree_root = tree_model._root if tree_model is not None else None
    detail_root = detail_model._root if detail_model is not None else None

    if tree_view is not None and tree_root is not None:
        tree_view.set_expanded(tree_root, True, False)
    if detail_view is not None and detail_root is not None:
        detail_view.set_expanded(detail_root, True, False)
    await _drive(8)

    # Expand one child folder on each pane to show nested hierarchy.
    if tree_model is not None and tree_view is not None:
        for child in tree_model.get_item_children(tree_root):
            if getattr(child, "is_folder", False):
                tree_view.set_expanded(child, True, False)
                break
    if detail_model is not None and detail_view is not None:
        for child in detail_model.get_item_children(detail_root):
            if getattr(child, "is_folder", False):
                detail_view.set_expanded(child, True, False)
                break
    await _drive(8)

    uitesting.capture_screenshot(OUT_EXPANDED)
    print(f"Saved: {OUT_EXPANDED}")

    # Screenshot 3 — navigate_to drills both panes to a sub-folder.
    # Pick a folder that exists in the home directory (Documents is
    # usually present; fall back to the root if not). The purpose is
    # to show the panes re-root together.
    candidate_paths = [
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~"),
    ]
    chosen = None
    for p in candidate_paths:
        if os.path.isdir(p):
            chosen = p
            break
    if chosen is not None:
        backend = widget._backend
        target_url = backend.normalize_url(f"file://{chosen}")
        widget.navigate_to(target_url)
        await _drive(8)
        # Expand the new root.
        tree_model = widget._tree_model
        detail_model = widget._detail_model
        tree_view = widget._tree_tree_view
        detail_view = widget._detail_tree_view
        if tree_view is not None and tree_model is not None:
            tree_view.set_expanded(tree_model._root, True, False)
        if detail_view is not None and detail_model is not None:
            detail_view.set_expanded(detail_model._root, True, False)
        await _drive(8)

    uitesting.capture_screenshot(OUT_DRILLED)
    print(f"Saved: {OUT_DRILLED}")

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
    ui.init("OvGear Step 13 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

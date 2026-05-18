# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 14 — selection sync.

Three proof screenshots showing the tree-click / detail-double-click
browsing loop:

* ``/tmp/ovgear_step14_1_initial.png`` — both panes show the home
  root. No tree-side selection; detail shows the root's direct
  children.
* ``/tmp/ovgear_step14_2_after_tree_click.png`` — after clicking a
  subfolder in the tree pane. The detail pane has re-rooted so its
  contents are the subfolder's children; the tree pane's own root is
  unchanged.
* ``/tmp/ovgear_step14_3_after_detail_dblclk.png`` — after double-
  clicking a deeper folder in the detail pane. Both panes have
  re-rooted (detail via ``set_root_url``, tree selection mirrored via
  ``FileBrowserModel.resolve``).

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step14_selection_sync_screenshot.py
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

OUT_INITIAL = "/tmp/ovgear_step14_1_initial.png"
OUT_AFTER_TREE_CLICK = "/tmp/ovgear_step14_2_after_tree_click.png"
OUT_AFTER_DETAIL_DBLCLK = "/tmp/ovgear_step14_3_after_detail_dblclk.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _first_subfolder(model, start_item):
    """Return the first folder child of ``start_item`` on ``model``."""
    for child in model.get_item_children(start_item):
        if getattr(child, "is_folder", False):
            return child
    return None


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Let the dockspace render, windows claim their dock nodes, the
    # two content models populate their initial roots.
    await _drive(40)

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget

    tree_view = widget._tree_tree_view
    detail_view = widget._detail_tree_view
    tree_model = widget._tree_model
    detail_model = widget._detail_model

    # Expand the root on the tree pane so a user-visible folder to
    # click is actually showing. Expand on the detail pane too so the
    # detail view is non-empty in the initial shot.
    tree_root = tree_model._root
    detail_root = detail_model._root
    tree_view.set_expanded(tree_root, True, False)
    detail_view.set_expanded(detail_root, True, False)
    await _drive(8)

    # Screenshot 1 — initial state.
    uitesting.capture_screenshot(OUT_INITIAL)
    print(f"Saved: {OUT_INITIAL}")

    # Screenshot 2 — simulate clicking a subfolder in the tree pane.
    # Prefer a folder that itself has subfolder children so screenshot
    # 3's drill-in step has something to drill into. Fall back to the
    # first folder child if none match.
    tree_children = tree_model.get_item_children(tree_root)

    def _has_nested_folder(node) -> bool:
        if not getattr(node, "is_folder", False):
            return False
        for grand in tree_model.get_item_children(node):
            if getattr(grand, "is_folder", False):
                return True
        return False

    tree_target = next(
        (c for c in tree_children if _has_nested_folder(c)),
        _first_subfolder(tree_model, tree_root),
    )
    if tree_target is None:
        raise RuntimeError("Tree root has no folder children")
    tree_view.selection = [tree_target]
    tree_view.call_selection_changed_fn([tree_target])
    await _drive(8)

    # Re-read widget pointers — ``set_root_url`` doesn't rebuild the
    # view / model, but ``_drive`` lets omni.ui flush the item-changed
    # dispatch so detail-pane children populate.
    detail_view = widget._detail_tree_view
    detail_model = widget._detail_model
    detail_view.set_expanded(detail_model._root, True, False)
    await _drive(8)

    uitesting.capture_screenshot(OUT_AFTER_TREE_CLICK)
    print(f"Saved: {OUT_AFTER_TREE_CLICK}")

    # Screenshot 3 — simulate double-clicking a deeper folder in the
    # detail pane. The detail pane is currently rooted at
    # ``tree_target``; pick the first subfolder under that. Setting
    # ``.selection`` is what a first mouse-press would do; invoking
    # ``call_mouse_double_clicked_fn`` then fires the Step 14 handler.
    detail_subfolder = _first_subfolder(detail_model, detail_model._root)
    if detail_subfolder is None:
        # No nested folders under the chosen tree target — surface a
        # clear error rather than silently screenshot the same state
        # as step 2. The selection above was picked to guarantee a
        # nested folder exists.
        raise RuntimeError(
            "No nested folder under the tree target — pick a different "
            "starting folder that contains at least one subdirectory."
        )
    detail_view.selection = [detail_subfolder]
    detail_view.call_mouse_double_clicked_fn(0, 0, 0, 0)
    await _drive(8)

    # Re-expand the new roots for a populated shot.
    detail_view = widget._detail_tree_view
    detail_model = widget._detail_model
    tree_view = widget._tree_tree_view
    tree_model = widget._tree_model
    detail_view.set_expanded(detail_model._root, True, False)
    await _drive(8)

    uitesting.capture_screenshot(OUT_AFTER_DETAIL_DBLCLK)
    print(f"Saved: {OUT_AFTER_DETAIL_DBLCLK}")

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
    ui.init("OvGear Step 14 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

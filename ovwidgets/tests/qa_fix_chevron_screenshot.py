# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification — Content Browser chevron matches Stage Browser.

One proof screenshot showing the Stage Browser and Content Browser
side-by-side with a mix of expanded and collapsed folders so the
expand/collapse chevron can be compared pixel-for-pixel across the
two panels.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_fix_chevron_screenshot.py
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

USD_PATH = os.path.join(os.path.dirname(__file__), "data", "simple_scene.usda")
OUT_SIDE_BY_SIDE = "/tmp/ovgear_fix_chevron_side_by_side.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _first_folder_child(model, node):
    for child in model.get_item_children(node):
        if getattr(child, "is_folder", False):
            return child
    return None


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    app._startup_usd_path = USD_PATH
    task = asyncio.ensure_future(app.run_async())

    await _drive(40)

    # Stage Browser — expand the root so its chevrons are visible for
    # comparison against the content-browser chevrons.
    if app._stage_window is not None and app._stage_window._widget is not None:
        stage = app._stage_window._widget
        stage_tree = getattr(stage, "_tree_view", None)
        stage_model = getattr(stage, "_model", None)
        if stage_tree is not None and stage_model is not None:
            for top in stage_model.get_item_children(None):
                stage_tree.set_expanded(top, True, False)
            await _drive(6)

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window not built")
    widget = cw._widget
    tree_view = widget._tree_tree_view
    detail_view = widget._detail_tree_view
    tree_model = widget._tree_model
    detail_model = widget._detail_model

    # Expand roots on both panes so their first-level chevrons are
    # visible. Then partially expand one child folder inside the detail
    # pane so the screenshot captures both chevron states (collapsed →
    # right-pointing, expanded → down-pointing).
    tree_view.set_expanded(tree_model._root, True, False)
    detail_view.set_expanded(detail_model._root, True, False)
    await _drive(8)

    detail_child = _first_folder_child(detail_model, detail_model._root)
    if detail_child is not None:
        detail_view.set_expanded(detail_child, True, False)
        await _drive(8)

    tree_child = _first_folder_child(tree_model, tree_model._root)
    if tree_child is not None:
        tree_view.set_expanded(tree_child, True, False)
        await _drive(8)

    uitesting.capture_screenshot(OUT_SIDE_BY_SIDE)
    print(f"Saved: {OUT_SIDE_BY_SIDE}")

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
    ui.init("OvGear Chevron Fix QA", width=1600, height=900)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

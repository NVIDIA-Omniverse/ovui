# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 16 — row selection highlight.

Uses a realistic sublayer stack (root → sub1 → sub2) driven by a
``MockLayerStackAdapter`` so the shots focus entirely on the Layers
window visuals. The full Application machinery is deliberately side-
stepped: it rebuilds docks on every file open, which churns the
``ui.TreeView`` instance and kills the programmatic ``tree_view.selection``
write before the paint lands. The probe earlier in the step confirmed
the style rules paint correctly; the same construction shape is used
here so the screenshot-capture loop sees the same state.

1. **Shot 1** — ``/tmp/ovgear_layers_step16_1.png``: tree rendered,
   no selection. Plain ``cl.background_primary`` under every row.
2. **Shot 2** — ``/tmp/ovgear_layers_step16_2.png``: root layer
   selected via ``tree_view.selection = [root_item]``. Row paints
   ``cl.layers_row_selected``.
3. **Shot 3** — ``/tmp/ovgear_layers_step16_3.png``: the first
   sublayer (``sub1``) is selected; the root reverts to unselected.

Runtime assertions pinned before each screenshot:

- ``LayerModel.selected_items`` reflects what the selection callback
  wrote (real click path; the TreeView setter does not fire the
  callback, so the harness mirrors it manually).
- ``tree_view.selection`` retains the programmatic write across a
  paint cycle — the ovui ``_getNode`` sync check only prunes items
  that aren't walked by the tree; our model returns top-level rows
  and (after ``set_expanded``) sublayer rows on the same frame.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting

from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.layers import LayerItem, LayerModel, LayerWindow

OUT_1 = "/tmp/ovgear_layers_step16_1.png"
OUT_2 = "/tmp/ovgear_layers_step16_2.png"
OUT_3 = "/tmp/ovgear_layers_step16_3.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    """Mirror the step-14 asset: root → sub1 → sub2, plus session layer."""
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./sub1.usda")
    adapter.add_sublayer("./sub1.usda", "./sub2.usda")
    return adapter


async def _main() -> None:
    adapter = _make_adapter()
    layer_window = LayerWindow(services=None, adapter=adapter)
    # Undock so the Layers window fills the canvas — the test harness
    # doesn't instantiate the full dock layout.
    if layer_window.window is not None:
        layer_window.window.undock()
        layer_window.window.position_x = 40
        layer_window.window.position_y = 40
        layer_window.window.width = 1200
        layer_window.window.height = 640
        layer_window.window.focus()

    await _drive(15)

    model = layer_window._model
    if not isinstance(model, LayerModel):
        raise RuntimeError(f"Expected LayerModel, got {type(model).__name__}")
    tree_view = layer_window._tree_view
    if tree_view is None:
        raise RuntimeError("TreeView not built — window may still be hidden")
    if model.selected_items:
        raise RuntimeError(
            f"Pre-selection: selected_items should be empty, got {model.selected_items!r}"
        )

    print(f"Shot 1 — no selection; rows={len(model.get_item_children(None))}")
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — select the root layer row.
    root_item = None
    for item in model.get_item_children(None):
        if not item.is_session_layer:
            root_item = item
            break
    if root_item is None or not isinstance(root_item, LayerItem):
        raise RuntimeError(f"Unexpected root item: {root_item!r}")

    tree_view.selection = [root_item]
    layer_window._on_tree_selection_changed([root_item])
    await _drive(5)

    live_sel = [getattr(s, "identifier", repr(s)) for s in tree_view.selection]
    if not live_sel:
        raise RuntimeError(
            "tree_view.selection empty after assignment — highlight will not paint"
        )
    if model.selected_items != [root_item]:
        raise RuntimeError(
            f"model.selected_items diverged: {model.selected_items!r}"
        )
    print(f"Shot 2 — root selected; tree_view.selection={live_sel!r}")
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Shot 3 — move selection to the first sublayer. Expand the root
    # first so the child row is actually painted; without expansion the
    # TreeView wouldn't have a visible row to highlight.
    if not root_item.sublayers:
        raise RuntimeError(
            "Root has no sublayers — expected ./sub1.usda"
        )
    sub1 = root_item.sublayers[0]
    try:
        tree_view.set_expanded(root_item, True, False)
    except Exception as exc:  # pragma: no cover — diagnostics only
        print(f"set_expanded failed: {exc}")
    await _drive(5)
    tree_view.selection = [sub1]
    layer_window._on_tree_selection_changed([sub1])
    await _drive(5)

    live_sel = [getattr(s, "identifier", repr(s)) for s in tree_view.selection]
    if not live_sel or sub1 not in tree_view.selection:
        raise RuntimeError(
            f"tree_view.selection does not contain sub1: {live_sel!r}"
        )
    if model.selected_items != [sub1]:
        raise RuntimeError(
            f"model.selected_items diverged: {model.selected_items!r}"
        )
    print(f"Shot 3 — sub1 selected; tree_view.selection={live_sel!r}")
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 16 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

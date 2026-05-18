# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 17 — seven-column TreeView.

The TreeView is now constructed with
``column_widths=[Fraction(1), Pixel(24), Pixel(24), Pixel(24), Pixel(24),
Pixel(24), Pixel(26)]`` and a :class:`LayerDelegate` that dispatches
cells per column. Only the name column (0) paints a real widget in this
step; columns 1-6 render ``ui.Spacer`` placeholders so the six fixed
icon cells on the right are visible as allocated blank space.

The three shots cover:

1. **Shot 1** — ``/tmp/ovgear_layers_step17_1.png``: tree collapsed,
   no selection. Rows show the name column stretching to fill and the
   six narrow blank cells on the right.
2. **Shot 2** — ``/tmp/ovgear_layers_step17_2.png``: root expanded so
   the nested ``sub1`` row is also visible. Column allocations must
   remain identical on the child row.
3. **Shot 3** — ``/tmp/ovgear_layers_step17_3.png``: root + sub1
   expanded, root selected. Confirms row highlight paints behind the
   full seven-column span.
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
from ovwidgets.layers import LayerDelegate, LayerModel, LayerWindow

OUT_1 = "/tmp/ovgear_layers_step17_1.png"
OUT_2 = "/tmp/ovgear_layers_step17_2.png"
OUT_3 = "/tmp/ovgear_layers_step17_3.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    """Mirror the Step 14 asset: root → sub1 → sub2, plus session layer."""
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
    delegate = layer_window._delegate
    if not isinstance(delegate, LayerDelegate):
        raise RuntimeError(
            f"Expected LayerDelegate, got {type(delegate).__name__}"
        )
    if model.get_item_value_model_count(model.root_item) != 7:
        raise RuntimeError(
            f"Expected 7 columns, got "
            f"{model.get_item_value_model_count(model.root_item)}"
        )

    print(f"Shot 1 — collapsed, no selection; columns={LayerModel.NUM_COLUMNS}")
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — expand root so the child row joins the paint tree; every
    # row must keep the same seven-column allocation.
    root_item = None
    for item in model.get_item_children(None):
        if not item.is_session_layer:
            root_item = item
            break
    if root_item is None:
        raise RuntimeError("Root layer row not found")
    tree_view.set_expanded(root_item, True, False)
    await _drive(5)

    print(f"Shot 2 — root expanded; sublayers={len(root_item.sublayers)}")
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Shot 3 — expand sub1 and select the root so the highlight spans
    # all seven columns (the six placeholder cells paint the row's
    # hover/selected background behind the Spacer).
    if root_item.sublayers:
        sub1 = root_item.sublayers[0]
        tree_view.set_expanded(sub1, True, False)
    tree_view.selection = [root_item]
    layer_window._on_tree_selection_changed([root_item])
    await _drive(5)

    print("Shot 3 — sub1 expanded, root selected")
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 17 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

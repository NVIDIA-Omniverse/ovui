# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 23 — row selection rectangle.

Step 23 overrides :meth:`LayerDelegate.build_branch` and wraps every
column's :meth:`build_widget` output in a ``Layers.TreeView.Row::row_bg``
:class:`ui.Rectangle`. ovui propagates the owning TreeView item's
``:hovered`` / ``:selected`` pseudo-states to every Rectangle in the
row, so selecting or hovering a row paints
``cl.layers_row_selected`` / ``cl.layers_row_hover`` across the branch
cell *and* all seven widget columns — the full-row selection strip
the plan's Verify step calls out.

The three shots together cover the complete interaction vocabulary:

1. **Shot 1** — ``/tmp/ovgear_layers_step23_1.png``: the stack at rest
   with no row selected. Every row's ``row_bg`` Rectangle is
   transparent; the seven columns render the Step 18-22 glyphs on a
   clean background. Used as the visual baseline to compare against
   Shot 2 and Shot 3.
2. **Shot 2** — ``/tmp/ovgear_layers_step23_2.png``: after selecting
   the ``./dirty.usda`` row via
   :meth:`ui.TreeView.selection = [item]`. The selected row paints
   ``cl.layers_row_selected`` across the branch cell, the name cell,
   the save dot (still amber), the mute eye, and every placeholder /
   lock column. Confirms the selection highlight is full-row wide and
   does not mask the per-column glyphs.
3. **Shot 3** — ``/tmp/ovgear_layers_step23_3.png``: after moving the
   selection to ``./locked.usda`` and exercising a mouse hover over
   ``./muted.usda`` via :func:`uitesting.mouse_move`. The selected row
   stays lit in ``cl.layers_row_selected`` while the hovered row
   paints the subtler ``cl.layers_row_hover`` tint — the two tokens
   are visually distinct, proving hover / selected are separate
   states rather than a single "highlighted" mode.
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
from ovwidgets.layers import (
    LayerDelegate,
    LayerModel,
    LayerWindow,
)

OUT_1 = "/tmp/ovgear_layers_step23_1.png"
OUT_2 = "/tmp/ovgear_layers_step23_2.png"
OUT_3 = "/tmp/ovgear_layers_step23_3.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    """Seed a stack with mixed state so selection paints across every column."""
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./dirty.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./locked.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./muted.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./missing.usda")
    adapter._layers["./dirty.usda"].dirty = True
    adapter._layers["./locked.usda"].locked = True
    adapter._layers["./muted.usda"].muted = True
    adapter._layers["./missing.usda"].missing = True
    return adapter


def _invalidate_all(model: LayerModel) -> None:
    for clone_list in model._sublayers_cache.values():
        for clone in clone_list:
            clone.invalidate_flags()


async def _main() -> None:
    adapter = _make_adapter()
    layer_window = LayerWindow(services=None, adapter=adapter)
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

    # Expand the root so the sublayers are visible — otherwise only the
    # session + root rows paint and the selection test has nothing to
    # hover / select in the interior of the tree.
    root_item = None
    for item in model.get_item_children(None):
        if not item.is_session_layer:
            root_item = item
            break
    if root_item is None:
        raise RuntimeError("Root layer row not found")
    tree_view.set_expanded(root_item, True, False)

    # Force value models to materialise so every column paints on the
    # very first visible frame — avoids a Shot 1 that has half the
    # columns blank because the lazy value models haven't spun up yet.
    for item_list in model._sublayers_cache.values():
        for item in item_list:
            for col in range(LayerModel.NUM_COLUMNS):
                model.get_item_value_model(item, col)
    model._item_changed(None)

    _invalidate_all(model)
    await _drive(6)
    print(
        "Shot 1 — stack at rest; row_bg Rectangle is transparent on "
        "every row; seven columns render their Step 18-22 glyphs on "
        "the clean TreeView background."
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — select the ./dirty.usda row. ovui propagates the
    # :selected pseudo-state to every Rectangle in the row's widget
    # tree; the full-row selection tint paints across branch + 7
    # columns.
    dirty_item = None
    for clone in model._sublayers_cache.get("./dirty.usda", ()):
        dirty_item = clone
        break
    if dirty_item is None:
        raise RuntimeError("./dirty.usda row not found")
    tree_view.selection = [dirty_item]
    model.set_selected_items([dirty_item])
    await _drive(6)
    print(
        "Shot 2 — ./dirty.usda selected; row_bg paints "
        "cl.layers_row_selected across all 7 columns + branch cell."
    )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Shot 3 — move selection to ./locked.usda and hover ./muted.usda
    # so both states paint at once. The two tint tokens
    # (layers_row_selected, layers_row_hover) are intentionally
    # different so the user can tell the two states apart at a glance.
    locked_item = None
    for clone in model._sublayers_cache.get("./locked.usda", ()):
        locked_item = clone
        break
    if locked_item is None:
        raise RuntimeError("./locked.usda row not found")
    tree_view.selection = [locked_item]
    model.set_selected_items([locked_item])
    await _drive(3)

    # Mouse-hover the ./muted.usda row by positioning the cursor over
    # its rough vertical midline. Row layout (ovui default row ~16 px):
    #   - title bar (~30 px) + session row + root row + dirty row +
    #     locked row + muted row
    # Target the vertical midline of the muted row so the hover tint
    # lights on that row specifically.
    _ROW_H = 16
    _TITLE_H = 34
    target_y = 40 + _TITLE_H + (4 * _ROW_H) + (_ROW_H // 2)
    target_x = 40 + 400  # middle of the name column
    await uitesting.mouse_move(target_x, target_y)
    await _drive(6)
    print(
        "Shot 3 — ./locked.usda selected; ./muted.usda hovered; "
        "selected tint and hover tint paint simultaneously in "
        "visually distinct colours."
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 23 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

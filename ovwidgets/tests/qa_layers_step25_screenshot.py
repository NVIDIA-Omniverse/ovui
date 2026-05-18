# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 25 — green edit-target row.

Step 24 plumbed ``_is_edit_target`` / ``_has_edit_target_descendant``
through the adapter's EDIT_TARGET_CHANGED event; Step 25 makes the
two flags visible. The authoring-layer row gets the
``cl.layers_row_edit_target`` green fill painted across the branch
cell and every column, a green leading "layers" glyph (three stacked
horizontal bars, ``Layers.LeadingIcon::edit_target``), and the
``(Authoring Layer)`` suffix from Step 18 paints green on top of
the green background because the tint on
``Layers.NameLabel::edit_target`` matches the icon tint — the label
reads more *saturated* than the fill, not *identical*, so it stays
legible.

Ancestor rows whose collapsed branches contain the edit target
(``_has_edit_target_descendant``) get a half-green leading glyph
via ``Layers.LeadingIcon::has_descendant`` — a subtler cue that
hints "edit target lives inside" without stealing the full-row
signal from the actual authoring layer.

Four shots cover the full visual vocabulary:

1. **Shot 1** — ``/tmp/ovgear_layers_step25_1.png``: baseline. Adapter
   default edit target is the root layer; the ``root`` row paints
   green end-to-end with the green leading-icon glyph. Session row
   sits unchanged above it, and the sublayer rows (``./sib.usda``,
   ``./mid.usda``) paint the neutral ``row_bg`` tint with normal
   leading icons.
2. **Shot 2** — ``/tmp/ovgear_layers_step25_2.png``: after
   ``adapter.set_edit_target("./deep.usda")``. The green row migrates
   off the root and onto ``./deep.usda`` (nested under ``./mid.usda``);
   the intermediate ``./mid.usda`` row keeps its neutral background
   but swaps its leading icon to the half-green ``has_descendant``
   state. Root's leading icon also flips to half-green because the
   edit target now lives somewhere below it.
3. **Shot 3** — ``/tmp/ovgear_layers_step25_3.png``: same edit target
   (``./deep.usda``) but with the ``./mid.usda`` row collapsed. The
   half-green icon is the only in-tree hint that an edit target
   sits below — the collapsed branch's green row is no longer
   visible, so the ancestor cue is the bridge.
4. **Shot 4** — ``/tmp/ovgear_layers_step25_4.png``: back on root, with
   ``./sib.usda`` selected so the Step-23 selection rectangle and the
   Step-25 green overlay paint on different rows without fighting.
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

OUT_1 = "/tmp/ovgear_layers_step25_1.png"
OUT_2 = "/tmp/ovgear_layers_step25_2.png"
OUT_3 = "/tmp/ovgear_layers_step25_3.png"
OUT_4 = "/tmp/ovgear_layers_step25_4.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    """Seed a deep hierarchy so ancestor propagation is visible.

    Layout::

        session
        root                              ← default edit target
          ├── ./sib.usda
          └── ./mid.usda
                └── ./deep.usda
    """
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./sib.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./mid.usda")
    adapter.add_sublayer("./mid.usda", "./deep.usda")
    return adapter


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

    # Expand root + mid so the sublayers + grandchild are visible.
    root_item = None
    for item in model.get_item_children(None):
        if not item.is_session_layer:
            root_item = item
            break
    if root_item is None:
        raise RuntimeError("Root layer row not found")
    tree_view.set_expanded(root_item, True, False)
    mid_item = model._items_by_id.get("./mid.usda")
    if mid_item is None:
        raise RuntimeError("./mid.usda row not found")
    tree_view.set_expanded(mid_item, True, False)

    # Materialise every column so no cell is lazily blank on first paint.
    for item_list in model._sublayers_cache.values():
        for item in item_list:
            for col in range(LayerModel.NUM_COLUMNS):
                model.get_item_value_model(item, col)
    model._item_changed(None)

    await _drive(6)
    print(
        "Shot 1 — baseline. Adapter default edit target = root. The "
        "root row paints end-to-end green (branch + all 7 columns) "
        "with a green leading layer-icon glyph and the "
        "'(Authoring Layer)' suffix."
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — move edit target to ./deep.usda (expanded tree visible).
    adapter.set_edit_target("./deep.usda")
    await _drive(6)
    print(
        "Shot 2 — edit target = ./deep.usda. Green row migrated from "
        "root to ./deep.usda. ./mid.usda's leading icon flips to the "
        "half-green 'has_descendant' state; root's leading icon does "
        "the same (edit target lives below root too)."
    )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Shot 3 — collapse mid so the half-green ancestor cue is the
    # only in-tree hint that an edit target sits below.
    tree_view.set_expanded(mid_item, False, False)
    await _drive(6)
    print(
        "Shot 3 — ./mid.usda collapsed; the actual green row "
        "(./deep.usda) is hidden. The half-green leading icon on "
        "./mid.usda is the only visual that tells the user the "
        "authoring layer lives below the collapsed branch."
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    # Shot 4 — restore edit target to root, re-expand mid, select sib
    # so the Step-23 selection rectangle composes with Step-25 styling.
    adapter.set_edit_target(ROOT_LAYER_IDENTIFIER)
    tree_view.set_expanded(mid_item, True, False)
    sib_item = model._items_by_id.get("./sib.usda")
    if sib_item is None:
        raise RuntimeError("./sib.usda row not found")
    tree_view.selection = [sib_item]
    model.set_selected_items([sib_item])
    await _drive(6)
    print(
        "Shot 4 — edit target = root (green row); ./sib.usda selected "
        "(neutral selection rectangle). Two different row backgrounds "
        "paint without fighting — the green signal stays scoped to "
        "the authoring layer row and the selection rectangle stays "
        "scoped to the selected row."
    )
    uitesting.capture_screenshot(OUT_4)
    print(f"Saved: {OUT_4}")

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 25 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

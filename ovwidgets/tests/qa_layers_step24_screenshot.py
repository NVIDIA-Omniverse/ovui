# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 24 — edit-target tracking.

Step 24 plumbs ``LayerModel._edit_target_identifier`` through the
``EDIT_TARGET_CHANGED`` event so every row on the affected clone set
flips its ``_is_edit_target`` flag in lockstep and the ancestor chain
picks up ``_has_edit_target_descendant``. Visually, the only surface
that changes here is the Step-18 name label: the edit-target row
gains the ``(Authoring Layer)`` suffix and paints in the
``Layers.NameLabel::edit_target`` tint. The row-background overlay
(green fill + pencil icon + bold font) lands in Step 25, and the
half-green ancestor glyph lands in Step 26 — so these shots are
the label-only baseline that Step 25's QA will compare its before /
after against.

The four shots cover the full interaction vocabulary:

1. **Shot 1** — ``/tmp/ovgear_layers_step24_1.png``: baseline. The
   adapter's default edit target is the root layer, so the row
   labeled ``root`` reads ``root (Authoring Layer)`` in the accent
   tint. Every other row (session + sublayers) renders its bare
   display name with no suffix.
2. **Shot 2** — ``/tmp/ovgear_layers_step24_2.png``: after
   ``adapter.set_edit_target("./deep.usda")`` where ``deep.usda`` is
   a grandchild under ``mid.usda``. The suffix migrates from
   ``root`` to ``./deep.usda``; the intermediate ``mid.usda`` row
   receives ``_has_edit_target_descendant = True`` (Step 26 will
   render the icon, but the flag is the contract Step 24 delivers).
3. **Shot 3** — ``/tmp/ovgear_layers_step24_3.png``: after moving
   the edit target back to ``./sib.usda`` (sibling of mid.usda).
   The suffix leaves ``./deep.usda``, the ``_has_edit_target_descendant``
   chain clears on ``mid.usda``, and ``./sib.usda`` gains the
   suffix. Confirms the clear-then-set propagation handles arbitrary
   jumps through the tree rather than just parent → child moves.
4. **Shot 4** — ``/tmp/ovgear_layers_step24_4.png``: back on the
   root layer. Selection vocabulary from Step 23 still paints
   around the edit-target row — the full-row selection rectangle
   and the authoring-layer suffix compose without either hiding
   the other.
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

OUT_1 = "/tmp/ovgear_layers_step24_1.png"
OUT_2 = "/tmp/ovgear_layers_step24_2.png"
OUT_3 = "/tmp/ovgear_layers_step24_3.png"
OUT_4 = "/tmp/ovgear_layers_step24_4.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    """Seed a stack with a deep hierarchy so ancestor propagation is visible.

    Layout:
        session
        root
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
        "'root (Authoring Layer)' label renders in the edit-target "
        "tint; every other row shows its bare display name."
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — move edit target to ./deep.usda. The suffix migrates.
    adapter.set_edit_target("./deep.usda")
    await _drive(6)
    print(
        "Shot 2 — edit target = ./deep.usda. The '(Authoring Layer)' "
        "suffix left the root row and now renders on ./deep.usda; "
        "./mid.usda carries _has_edit_target_descendant = True (icon "
        "treatment ships in Step 26)."
    )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Shot 3 — swap to a sibling subtree. The mid.usda descendant
    # flag clears; sib.usda gains the authoring suffix.
    adapter.set_edit_target("./sib.usda")
    await _drive(6)
    print(
        "Shot 3 — edit target = ./sib.usda. Suffix moved off "
        "./deep.usda, onto ./sib.usda; ./mid.usda's "
        "_has_edit_target_descendant flag clears as the subtree no "
        "longer contains the authoring layer."
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    # Shot 4 — restore edit target to root and select ./sib.usda so
    # the Step-23 selection rectangle composes with the Step-24 label
    # styling without either hiding the other.
    adapter.set_edit_target(ROOT_LAYER_IDENTIFIER)
    sib_item = model._items_by_id.get("./sib.usda")
    if sib_item is None:
        raise RuntimeError("./sib.usda row not found")
    tree_view.selection = [sib_item]
    model.set_selected_items([sib_item])
    await _drive(6)
    print(
        "Shot 4 — edit target back on root; ./sib.usda selected. "
        "Selection rectangle (Step 23) and authoring-layer suffix "
        "(Step 24) compose on different rows without fighting for "
        "the same paint surface."
    )
    uitesting.capture_screenshot(OUT_4)
    print(f"Saved: {OUT_4}")

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 24 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

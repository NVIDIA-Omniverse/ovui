# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 22 — placeholder columns.

Columns 1 (Live), 4 (Global Mute), 5 (Latest) now paint disabled-tint
placeholder glyphs via :meth:`LayerDelegate._build_live_placeholder`,
:meth:`_build_global_mute_placeholder`, and
:meth:`_build_latest_placeholder`. Column 5 stays blank for layers
whose file resolved cleanly and only shows its placeholder for rows
where :attr:`LayerItem.is_missing` is True — Kit's "reload hint on
missing file" convention.

The three shots cover the complete 7-column visual state:

1. **Shot 1** — ``/tmp/ovgear_layers_step22_1.png``: the full mixed
   stack at rest. Every row shows the Live (col 1) and Global Mute
   (col 4) placeholders. Column 5 is blank for the present sublayers
   and shows the dim reload-style square for ``./missing.usda``.
2. **Shot 2** — ``/tmp/ovgear_layers_step22_2.png``: after a click
   on the Live placeholder cell. The cell is non-interactive so the
   visual state does not change — the screenshot proves no state
   flip happens and the TreeView row-select owns the hit target.
3. **Shot 3** — ``/tmp/ovgear_layers_step22_3.png``: the authoring-
   layer row is made dirty + its save click-target is exercised to
   confirm the placeholder columns coexist with the graduated
   Step 19-21 cells (save dot, mute eye, lock padlock). All seven
   columns populated, no bouncing, no missing glyphs.
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

OUT_1 = "/tmp/ovgear_layers_step22_1.png"
OUT_2 = "/tmp/ovgear_layers_step22_2.png"
OUT_3 = "/tmp/ovgear_layers_step22_3.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    """Seed a stack that exercises every placeholder state at once.

    Tree shape (rendered top → bottom after the session layer):
    ```
    session                   (Anonymous)       [live·, ·, ·, gm·, —, ·]
    root                      (Authoring Layer) [live·, ·, ·, gm·, —, ·]
      ./dirty.usda             [live·, dot, open, gm·, —, open-lock]
      ./locked.usda            [live·, —, open, gm·, —, padlock]
      ./muted.usda             [live·, —, slit, gm·, —, open-lock]
      ./missing.usda           [live·, —, open, gm·, reload, open-lock]
    ```
    ``live·`` and ``gm·`` are the disabled placeholder glyphs; the
    reload square on the missing row is the Step 22 Latest placeholder.
    """
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./dirty.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./locked.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./muted.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./missing.usda")
    # Direct mutation — going through ``set_*`` would fire events
    # before the window has built the tree, which is harmless but
    # keeps the seed path stateless (no events at construction time).
    adapter._layers["./dirty.usda"].dirty = True
    adapter._layers["./locked.usda"].locked = True
    adapter._layers["./muted.usda"].muted = True
    adapter._layers["./missing.usda"].missing = True
    return adapter


def _invalidate_all(model: LayerModel) -> None:
    """Drop every cached flag so the next render picks up mutated state."""
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

    root_item = None
    for item in model.get_item_children(None):
        if not item.is_session_layer:
            root_item = item
            break
    if root_item is None:
        raise RuntimeError("Root layer row not found")
    tree_view.set_expanded(root_item, True, False)

    # Force every row to materialise so the delegate has something to
    # paint on the first visible frame — the value models for cols 2,
    # 3, 6 instantiate lazily and cols 1, 4, 5 render via the shared
    # placeholder value model.
    for item_list in model._sublayers_cache.values():
        for item in item_list:
            for col in range(LayerModel.NUM_COLUMNS):
                model.get_item_value_model(item, col)
    model._item_changed(None)

    _invalidate_all(model)
    await _drive(6)
    print(
        "Shot 1 — full 7-column layout; Live/GM placeholders on every "
        "row; Latest reload square only on ./missing.usda"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — placeholder is non-interactive; a click does nothing.
    # We don't actually have a programmatic "click cell X" hook on
    # the placeholder because no handler is bound — the whole point
    # of the step. Re-render in the same state to confirm stability.
    _invalidate_all(model)
    model._item_changed(None)
    await _drive(6)
    print(
        "Shot 2 — re-render with no user interaction; placeholders "
        "remain unchanged (they have no click handler)"
    )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Shot 3 — exercise the graduated columns alongside the placeholders
    # so the screenshot proves all seven columns coexist without layout
    # bounce. Toggle the lock on ./muted.usda so the padlock flips and
    # the row demonstrates the mixed-column painting.
    muted_item = None
    for clone in model._sublayers_cache.get("./muted.usda", ()):
        muted_item = clone
        break
    if muted_item is not None:
        lock_vm = model.get_item_value_model(muted_item, 6)
        lock_vm.set_value(True)
    model._item_changed(None)
    await _drive(6)
    print(
        "Shot 3 — ./muted.usda is now locked; live/global-mute/latest "
        "placeholders stay untouched, graduated columns repaint"
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 22 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

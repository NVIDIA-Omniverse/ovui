# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 19 — save-column indicator.

Column 2 now renders through :class:`SaveValueModel`: a centred amber
dot appears whenever the layer is dirty *and* saveable (not anonymous,
not missing). Clicking the dot calls :meth:`SaveValueModel.set_value`
which forwards to :meth:`LayerStackAdapter.save_layer` and clears the
dirty bit.

The three shots cover the full state machine:

1. **Shot 1** — ``/tmp/ovgear_layers_step19_1.png``: a mixed stack
   where ``./dirty.usda`` is dirty and saveable (amber dot visible),
   ``./clean.usda`` is clean (no dot), ``./anon`` is dirty but
   anonymous (no dot — clamped by the saveable guard), and
   ``./missing.usda`` is dirty but missing (no dot — same guard).
2. **Shot 2** — ``/tmp/ovgear_layers_step19_2.png``: after a
   simulated click on ``./dirty.usda``, the save path has cleared
   the dirty bit and the amber dot disappears from that row.
3. **Shot 3** — ``/tmp/ovgear_layers_step19_3.png``: flipping a
   second layer dirty (``./another.usda``) proves the per-row
   indicators refresh independently — the newly-dirty row shows the
   dot; the previously-saved ``./dirty.usda`` row stays clean.
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
from ovwidgets.layers import LayerDelegate, LayerModel, LayerWindow, SaveValueModel

OUT_1 = "/tmp/ovgear_layers_step19_1.png"
OUT_2 = "/tmp/ovgear_layers_step19_2.png"
OUT_3 = "/tmp/ovgear_layers_step19_3.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    """Seed a stack that exercises every save-indicator state at once.

    Tree shape (rendered top → bottom after the session layer):
    ```
    session                 (Anonymous)       [no dot — anonymous]
    root                    (Authoring Layer) [no dot — clean]
      ./dirty.usda                            [amber dot — dirty + saveable]
      ./clean.usda                            [no dot — clean]
      ./anon                                  [no dot — dirty + anonymous]
      ./missing.usda         (Missing)        [no dot — dirty + missing]
      ./another.usda                          [no dot initially — clean]
    ```
    """
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./dirty.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./clean.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./anon")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./missing.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./another.usda")
    # Mutate the mock records directly — going through ``set_missing``
    # or the other adapter mutators would fire INFO_CHANGED (structural)
    # and rebuild the tree mid-setup, reordering the sublayers.
    adapter._layers["./dirty.usda"].dirty = True
    adapter._layers["./anon"].anonymous = True
    adapter._layers["./anon"].dirty = True
    adapter._layers["./missing.usda"].missing = True
    adapter._layers["./missing.usda"].dirty = True
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

    # Force every row to materialise its save model so the delegate
    # has something to paint on the first visible frame.
    for item_list in model._sublayers_cache.values():
        for item in item_list:
            vm = model.get_item_value_model(item, 2)
            if vm is not None:
                assert isinstance(vm, SaveValueModel), (
                    f"expected SaveValueModel for col 2, got {type(vm).__name__}"
                )
    model._item_changed(None)

    _invalidate_all(model)
    await _drive(6)
    print(
        "Shot 1 — mixed dirty / clean / anon / missing rows; amber dot "
        "on ./dirty.usda only"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — simulate a click on the ./dirty.usda save dot. The
    # click path forwards through the value model into the adapter
    # (Phase F wraps it in a SaveLayerCommand); the mock clears the
    # dirty bit on success and fires DIRTY_STATE_CHANGED, which routes
    # back into LayerModel and refreshes the per-row SaveValueModel.
    dirty_item = None
    for clone in model._sublayers_cache.get("./dirty.usda", ()):
        dirty_item = clone
        break
    if dirty_item is None:
        raise RuntimeError("./dirty.usda row not in _sublayers_cache")
    dirty_vm = model.get_item_value_model(dirty_item, 2)
    dirty_vm.set_value(True)
    model._item_changed(None)
    await _drive(6)
    print("Shot 2 — after click on ./dirty.usda; amber dot cleared")
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Shot 3 — flip ./another.usda dirty so a DIFFERENT row shows the
    # dot. Proves the per-row indicators refresh independently after
    # DIRTY_STATE_CHANGED events.
    adapter.set_dirty("./another.usda", True)
    model._item_changed(None)
    await _drive(6)
    print("Shot 3 — ./another.usda now dirty; amber dot appears there")
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 19 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

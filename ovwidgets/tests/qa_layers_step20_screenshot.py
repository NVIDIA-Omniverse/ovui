# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 20 — local-mute eye column.

Column 3 now renders through :class:`LocalMuteValueModel`: a filled
:class:`ui.Circle` (``Layers.MuteIcon::open``) for unmuted layers and
a short horizontal :class:`ui.Rectangle` (``Layers.MuteIcon::muted``)
for locally muted layers. Left-clicking the cell toggles the bit via
``adapter.set_mute``; the resulting ``MUTE_STATE_CHANGED`` event
routes back through :meth:`LayerModel._on_layer_event` and the per-
row :meth:`LocalMuteValueModel._value_changed` repaints the cell.

The three shots cover the full state machine:

1. **Shot 1** — ``/tmp/ovgear_layers_step20_1.png``: a mixed stack
   where ``./muted.usda`` is muted (horizontal slit), every other
   layer shows the open-eye dot.
2. **Shot 2** — ``/tmp/ovgear_layers_step20_2.png``: after a
   simulated click on ``./open.usda``, that row flips to the muted
   slit while ``./muted.usda`` stays muted and the rest stay open.
3. **Shot 3** — ``/tmp/ovgear_layers_step20_3.png``: clicking
   ``./muted.usda`` again proves the toggle works in both directions
   — the row returns to the open-eye state and the previously-
   clicked ``./open.usda`` row remains muted.
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
    LocalMuteValueModel,
)

OUT_1 = "/tmp/ovgear_layers_step20_1.png"
OUT_2 = "/tmp/ovgear_layers_step20_2.png"
OUT_3 = "/tmp/ovgear_layers_step20_3.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    """Seed a stack that exercises every mute-indicator state at once.

    Tree shape (rendered top → bottom after the session layer):
    ```
    session                 (Anonymous)       [open eye — unmuted]
    root                    (Authoring Layer) [open eye — unmuted]
      ./muted.usda                            [muted slit]
      ./open.usda                             [open eye]
      ./another.usda                          [open eye]
    ```
    """
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./muted.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./open.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./another.usda")
    # Direct mutation — going through ``set_mute`` would fire
    # ``MUTE_STATE_CHANGED`` before the window has built the tree,
    # which is harmless here but mutating the record keeps the seed
    # path stateless (no events at construction time).
    adapter._layers["./muted.usda"].muted = True
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

    # Force every row to materialise its mute model so the delegate
    # has something to paint on the first visible frame.
    for item_list in model._sublayers_cache.values():
        for item in item_list:
            vm = model.get_item_value_model(item, 3)
            if vm is not None:
                assert isinstance(vm, LocalMuteValueModel), (
                    f"expected LocalMuteValueModel for col 3, "
                    f"got {type(vm).__name__}"
                )
    model._item_changed(None)

    _invalidate_all(model)
    await _drive(6)
    print(
        "Shot 1 — ./muted.usda shows closed slit, every other row shows open eye"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — simulate a click on the ./open.usda mute icon. The
    # click path reads the current value and writes its negation
    # through the value model, which forwards to ``adapter.set_mute``.
    # The mock fires MUTE_STATE_CHANGED and the per-row model refreshes.
    open_item = None
    for clone in model._sublayers_cache.get("./open.usda", ()):
        open_item = clone
        break
    if open_item is None:
        raise RuntimeError("./open.usda row not in _sublayers_cache")
    open_vm = model.get_item_value_model(open_item, 3)
    open_vm.set_value(not open_vm.get_value_as_bool())
    model._item_changed(None)
    await _drive(6)
    print("Shot 2 — after click on ./open.usda; that row now muted")
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Shot 3 — click ./muted.usda again to unmute it. Two round-trips
    # through the toggle path prove the write surface works in both
    # directions and the refresh hook fires independently per row.
    muted_item = None
    for clone in model._sublayers_cache.get("./muted.usda", ()):
        muted_item = clone
        break
    if muted_item is None:
        raise RuntimeError("./muted.usda row not in _sublayers_cache")
    muted_vm = model.get_item_value_model(muted_item, 3)
    muted_vm.set_value(not muted_vm.get_value_as_bool())
    model._item_changed(None)
    await _drive(6)
    print(
        "Shot 3 — ./muted.usda unmuted; ./open.usda still muted — "
        "toggles are per-row independent"
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 20 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

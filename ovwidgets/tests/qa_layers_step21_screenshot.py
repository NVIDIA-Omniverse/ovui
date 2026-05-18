# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 21 — lock padlock column.

Column 6 now renders through :class:`LockValueModel`: two stacked
:class:`ui.Rectangle` primitives (shackle + body) for a locked layer
(``Layers.LockIcon::locked``) and a single dimmed body for an unlocked
layer (``Layers.LockIcon::unlocked``). Left-clicking the cell toggles
the bit via ``adapter.set_lock``; the resulting ``LOCK_STATE_CHANGED``
event routes back through :meth:`LayerModel._on_layer_event` and the
per-row :meth:`LockValueModel._value_changed` repaints the cell.

The three shots cover the full state machine:

1. **Shot 1** — ``/tmp/ovgear_layers_step21_1.png``: a mixed stack
   where ``./locked.usda`` is locked (full padlock), every other
   layer shows the dimmed unlocked body.
2. **Shot 2** — ``/tmp/ovgear_layers_step21_2.png``: after a
   simulated click on ``./open.usda``, that row flips to the locked
   padlock while ``./locked.usda`` stays locked and the rest stay
   unlocked.
3. **Shot 3** — ``/tmp/ovgear_layers_step21_3.png``: clicking
   ``./locked.usda`` again proves the toggle works in both directions
   — the row returns to the unlocked state and the previously-
   clicked ``./open.usda`` row remains locked.
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
    LockValueModel,
)

OUT_1 = "/tmp/ovgear_layers_step21_1.png"
OUT_2 = "/tmp/ovgear_layers_step21_2.png"
OUT_3 = "/tmp/ovgear_layers_step21_3.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    """Seed a stack that exercises every lock-indicator state at once.

    Tree shape (rendered top → bottom after the session layer):
    ```
    session                   (Anonymous)       [unlocked body]
    root                      (Authoring Layer) [unlocked body]
      ./locked.usda                             [full padlock]
      ./open.usda                               [unlocked body]
      ./another.usda                            [unlocked body]
    ```
    """
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./locked.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./open.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./another.usda")
    # Direct mutation — going through ``set_lock`` would fire
    # ``LOCK_STATE_CHANGED`` before the window has built the tree,
    # which is harmless here but mutating the record keeps the seed
    # path stateless (no events at construction time).
    adapter._layers["./locked.usda"].locked = True
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

    # Force every row to materialise its lock model so the delegate
    # has something to paint on the first visible frame.
    for item_list in model._sublayers_cache.values():
        for item in item_list:
            vm = model.get_item_value_model(item, 6)
            if vm is not None:
                assert isinstance(vm, LockValueModel), (
                    f"expected LockValueModel for col 6, "
                    f"got {type(vm).__name__}"
                )
    model._item_changed(None)

    _invalidate_all(model)
    await _drive(6)
    print(
        "Shot 1 — ./locked.usda shows full padlock, every other row shows "
        "unlocked body"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — simulate a click on the ./open.usda lock icon. The
    # click path reads the current value and writes its negation
    # through the value model, which forwards to ``adapter.set_lock``.
    # The mock fires LOCK_STATE_CHANGED and the per-row model refreshes.
    open_item = None
    for clone in model._sublayers_cache.get("./open.usda", ()):
        open_item = clone
        break
    if open_item is None:
        raise RuntimeError("./open.usda row not in _sublayers_cache")
    open_vm = model.get_item_value_model(open_item, 6)
    open_vm.set_value(not open_vm.get_value_as_bool())
    model._item_changed(None)
    await _drive(6)
    print("Shot 2 — after click on ./open.usda; that row now locked")
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Shot 3 — click ./locked.usda again to unlock it. Two round-trips
    # through the toggle path prove the write surface works in both
    # directions and the refresh hook fires independently per row.
    locked_item = None
    for clone in model._sublayers_cache.get("./locked.usda", ()):
        locked_item = clone
        break
    if locked_item is None:
        raise RuntimeError("./locked.usda row not in _sublayers_cache")
    locked_vm = model.get_item_value_model(locked_item, 6)
    locked_vm.set_value(not locked_vm.get_value_as_bool())
    model._item_changed(None)
    await _drive(6)
    print(
        "Shot 3 — ./locked.usda unlocked; ./open.usda still locked — "
        "toggles are per-row independent"
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 21 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

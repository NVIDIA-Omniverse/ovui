# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 35 — Save-All toolbar.

Three shots prove the deliverable:

1. **Shot 1** — ``/tmp/ovgear_layers_step35_1.png``: clean stack.
   The header toolbar carries a Save-All button that is **disabled**
   (greyed) and the badge dot is **hidden** because no concrete
   layer is dirty.
2. **Shot 2** — ``/tmp/ovgear_layers_step35_2.png``: two dirty
   concrete layers (``./child_a.usda`` and ``./child_b.usda``).
   The button is **enabled** and the amber badge dot is visible in
   the top-right corner of the button. The per-row amber save dots
   also appear on the two dirty rows (Step 19 already provides those
   — shown here to confirm the badge matches the row-level signal).
3. **Shot 3** — ``/tmp/ovgear_layers_step35_3.png``: after clicking
   Save-All. Both rows are clean, the badge is gone, and the button
   has re-disabled itself through the Step-35 subscription. The
   undo stack is untouched (each inner ``SaveLayerCommand`` is
   ``non_undoable``; the ``Save All`` group ends empty and
   auto-discards).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting

from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.common.undo import UndoManager
from ovwidgets.layers import (
    LayerDelegate,
    LayerModel,
    LayerWindow,
    SaveAllValueModel,
)
from ovwidgets.layers.commands import SaveLayerCommand

OUT_1 = "/tmp/ovgear_layers_step35_1.png"
OUT_2 = "/tmp/ovgear_layers_step35_2.png"
OUT_3 = "/tmp/ovgear_layers_step35_3.png"


class _StubApp:
    """Minimal :class:`Application` surface for the Layers window.

    The Step-35 click path reads ``undo_manager`` + ``selection_bus``;
    ``call_later`` is omitted so events flush inline (fine for the
    screenshot harness — matches every other Layers QA script).
    """

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child_a.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child_b.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./clean.usda")
    return adapter


def _invalidate_all(model: LayerModel) -> None:
    for clone_list in model._sublayers_cache.values():
        for clone in clone_list:
            clone.invalidate_flags()


async def _main() -> None:
    adapter = _make_adapter()
    app = _StubApp()
    layer_window = LayerWindow(services=app, adapter=adapter)
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
        raise RuntimeError(
            f"Expected LayerModel, got {type(model).__name__}"
        )
    tree_view = layer_window._tree_view
    if tree_view is None:
        raise RuntimeError(
            "TreeView not built — window may still be hidden"
        )
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

    save_all_model = model.get_save_all_model()
    if not isinstance(save_all_model, SaveAllValueModel):
        raise RuntimeError(
            "LayerModel.get_save_all_model() must return "
            "SaveAllValueModel"
        )

    await _drive(6)

    # --- Shot 1 — clean stack: button disabled, badge invisible ---
    assert save_all_model.get_value_as_bool() is False
    assert layer_window._save_all_button is not None
    assert layer_window._save_all_button.enabled is False
    assert layer_window._save_all_badge.name == ""
    print(
        "Shot 1 — clean stack: Save-All button disabled (greyed), "
        "badge dot hidden"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # --- Shot 2 — two concrete layers dirty ---
    adapter.set_dirty("./child_a.usda", True)
    adapter.set_dirty("./child_b.usda", True)
    _invalidate_all(model)
    model._item_changed(None)
    await _drive(6)

    assert save_all_model.get_value_as_bool() is True
    assert layer_window._save_all_button.enabled is True
    assert layer_window._save_all_badge.name == "dirty"
    print(
        "Shot 2 — two dirty concrete rows; button enabled; amber "
        "badge dot visible in top-right of the button"
    )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # --- Shot 3 — click Save-All ---
    pushed: list = []
    original_push = app.undo_manager.push

    def _spy(cmd):
        pushed.append(cmd)
        return original_push(cmd)

    app.undo_manager.push = _spy

    layer_window._on_save_all_clicked()
    _invalidate_all(model)
    model._item_changed(None)
    await _drive(6)

    assert len(pushed) == 2, (
        f"expected 2 SaveLayerCommands pushed in the group, "
        f"got {len(pushed)}"
    )
    assert all(isinstance(c, SaveLayerCommand) for c in pushed)
    # Every dirty bit cleared; aggregate reports clean; button
    # re-disabled through the value-changed subscription.
    assert save_all_model.get_value_as_bool() is False
    assert layer_window._save_all_button.enabled is False
    assert layer_window._save_all_badge.name == ""
    # The group wrapper for Save-All is empty (every inner command is
    # non_undoable) and UndoGroup auto-discards on end_group so the
    # undo stack does not grow.
    assert len(app.undo_manager._undo_stack) == 0
    print(
        f"Shot 3 — clicked Save-All; pushed {len(pushed)} commands "
        f"in the group; every row clean; badge gone; undo stack "
        f"depth still {len(app.undo_manager._undo_stack)}"
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 35 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

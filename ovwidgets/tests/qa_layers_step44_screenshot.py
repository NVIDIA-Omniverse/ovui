# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 44 — drop indicator visual.

Step 44 teaches :class:`~ovwidgets.layers.layer_model.LayerModel.drop_accepted`
to record the current drag-over state on a
:class:`~ovwidgets.layers.drop_visual_controller.DropVisualController`, and
teaches :class:`~ovwidgets.layers.layer_delegate.LayerDelegate` to paint four
named indicator overlays based on that state (green outline for valid
drop-onto, red outline + tooltip for rejected hovers, 2-px blue
horizontal line for valid between-drops). ovui's headless test harness
cannot synthesise native drag gestures, so the QA script drives
:meth:`LayerModel.drop_accepted` at the same entry points the
TreeView would and captures the painted indicator after each call.

Shots:

1. **Shot 1** — ``/tmp/ovgear_layers_step44_1.png``: baseline tree
   with no drag active. No indicators visible.
2. **Shot 2** — ``/tmp/ovgear_layers_step44_2.png``: valid drop-onto
   hover — simulate the cursor over ``./a.usda`` with source
   ``./c.usda``. The row paints a green outline.
3. **Shot 3** — ``/tmp/ovgear_layers_step44_3.png``: valid
   between-drop hover — simulate inserting ``./c.usda`` between
   ``./a.usda`` and ``./b.usda``. A blue horizontal line appears
   on the target row.
4. **Shot 4** — ``/tmp/ovgear_layers_step44_4.png``: invalid
   hover — lock ``./a.usda`` first, then simulate dropping
   ``./b.usda`` onto it. The row paints a red outline and the
   rejection reason becomes a tooltip on the cell.
5. **Shot 5** — ``/tmp/ovgear_layers_step44_5.png``: after
   :meth:`LayerModel.drop` is called on a valid target, the
   indicator clears and the mutation lands on the tree.
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
from ovwidgets.layers import LayerModel, LayerWindow

OUT_1 = "/tmp/ovgear_layers_step44_1.png"
OUT_2 = "/tmp/ovgear_layers_step44_2.png"
OUT_3 = "/tmp/ovgear_layers_step44_3.png"
OUT_4 = "/tmp/ovgear_layers_step44_4.png"
OUT_5 = "/tmp/ovgear_layers_step44_5.png"


class _StubApp:
    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./a.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./b.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./c.usda")
    adapter.add_sublayer("./a.usda", "./nested.usda")
    return adapter


def _describe_indicator(model: LayerModel) -> str:
    dv = model.drop_visual
    target = dv.current_target
    target_id = (
        getattr(target, "identifier", None) if target is not None else None
    )
    return (
        f"target={target_id!r} drop_location={dv.current_drop_location} "
        f"is_valid={dv.is_valid} reason={dv.rejection_reason!r}"
    )


async def _main() -> None:
    adapter = _make_adapter()
    app = _StubApp()
    layer_window = LayerWindow(services=app, adapter=adapter)
    if layer_window.window is not None:
        layer_window.window.undock()
        layer_window.window.position_x = 40
        layer_window.window.position_y = 40
        layer_window.window.width = 560
        layer_window.window.height = 520
        layer_window.window.focus()

    await _drive(15)

    model = layer_window._model
    if not isinstance(model, LayerModel):
        raise RuntimeError(
            f"Expected LayerModel, got {type(model).__name__}"
        )

    root_item = model.root_item
    if root_item is None:
        raise RuntimeError("Root layer row not found")

    tree_view = layer_window._tree_view
    if tree_view is not None:
        tree_view.set_expanded(root_item, True, False)
        a_item = model._items_by_id["./a.usda"]
        tree_view.set_expanded(a_item, True, False)

    await _drive(6)

    # --- Shot 1 — baseline, no drag ---
    print(f"Shot 1 — baseline, no drag. {_describe_indicator(model)}")
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # --- Shot 2 — valid drop-onto: C → A ---
    a_item = model._items_by_id["./a.usda"]
    c_item = model._items_by_id["./c.usda"]
    accepted = model.drop_accepted(a_item, c_item, -1)
    assert accepted, "valid drop-onto was rejected unexpectedly"
    await _drive(4)
    print(f"Shot 2 — valid drop-onto C→A. {_describe_indicator(model)}")
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # --- Shot 3 — valid between-drop: insert C at slot 1 ---
    accepted = model.drop_accepted(a_item, c_item, 1)
    assert accepted, "valid between-drop was rejected unexpectedly"
    await _drive(4)
    print(
        f"Shot 3 — valid between-drop insert at slot 1. "
        f"{_describe_indicator(model)}"
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    # --- Shot 4 — invalid hover: locked parent ---
    adapter.set_lock("./a.usda", True)
    model._items_by_id["./a.usda"].invalidate_flags()
    b_item = model._items_by_id["./b.usda"]
    rejected = model.drop_accepted(a_item, b_item, -1)
    assert rejected is False, "locked-parent drop was accepted unexpectedly"
    await _drive(4)
    print(
        f"Shot 4 — invalid hover on locked target. "
        f"{_describe_indicator(model)}"
    )
    uitesting.capture_screenshot(OUT_4)
    print(f"Saved: {OUT_4}")

    # Release the lock so the subsequent valid drop can commit.
    adapter.set_lock("./a.usda", False)
    model._items_by_id["./a.usda"].invalidate_flags()

    # --- Shot 5 — drop commits: indicator clears, tree mutates ---
    accepted = model.drop_accepted(a_item, c_item, -1)
    assert accepted, "post-unlock drop-onto was rejected unexpectedly"
    model.drop(a_item, c_item, -1)
    await _drive(4)
    # Re-expand A so the new child is visible in the shot.
    if tree_view is not None:
        tree_view.set_expanded(a_item, True, False)
    await _drive(3)
    print(
        f"Shot 5 — after drop commit. Indicator cleared: "
        f"{_describe_indicator(model)}"
    )
    uitesting.capture_screenshot(OUT_5)
    print(f"Saved: {OUT_5}")

    print()
    print("Step 44 behaviour summary:")
    print(
        "  - DropVisualController tracks (target, drop_location, "
        "is_valid, rejection_reason); mutated by drop_accepted / drop."
    )
    print(
        "  - Delegate paints: green outline (drop_target), red outline + "
        "tooltip (drop_rejected), blue horizontal line "
        "(drop_above/drop_below)."
    )
    print(
        "  - Rejected release toasts via ErrorReporter.show_warning "
        "with the rejection reason from _can_move_layer."
    )

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 44 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

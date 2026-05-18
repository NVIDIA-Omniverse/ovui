# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 43 — internal drag-drop
reorder of sublayers.

Step 43 is a model-layer change: the ``ui.TreeView`` now calls
:meth:`~ovwidgets.layers.layer_model.LayerModel.get_drag_mime_data`,
:meth:`~ovwidgets.layers.layer_model.LayerModel.drop_accepted`, and
:meth:`~ovwidgets.layers.layer_model.LayerModel.drop` when the user drags a
row. ovui's headless test harness does not synthesise native drag
gestures, so the QA script *drives* the same entry points the TreeView
would invoke at runtime and captures the tree before / after each
action. Designers read the screenshots to confirm the row order
reshuffles cleanly.

Shots:

1. **Shot 1** — ``/tmp/ovgear_layers_step43_1.png``: baseline panel
   with the starting order ``[A, B, C]`` under root, ``A`` expanded to
   show ``./nested.usda``.
2. **Shot 2** — ``/tmp/ovgear_layers_step43_2.png``: after a same-
   parent reorder (``C`` dragged to slot 1), root's children read
   ``[A, C, B]``.
3. **Shot 3** — ``/tmp/ovgear_layers_step43_3.png``: after a cross-
   parent reparent (``./b.usda`` dropped onto ``./a.usda``), ``B``
   sits alongside ``./nested.usda`` as a child of ``A``.
4. **Shot 4** — ``/tmp/ovgear_layers_step43_4.png``: after ``Ctrl+Z``
   twice through :meth:`UndoManager.undo`, the starting order is
   restored — proves the drag-drop landed on the undo stack.
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

OUT_1 = "/tmp/ovgear_layers_step43_1.png"
OUT_2 = "/tmp/ovgear_layers_step43_2.png"
OUT_3 = "/tmp/ovgear_layers_step43_3.png"
OUT_4 = "/tmp/ovgear_layers_step43_4.png"


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


def _root_children(adapter: MockLayerStackAdapter) -> list:
    return adapter.get_sublayer_identifiers(adapter.get_root_layer())


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

    # --- Shot 1 — baseline order [A, B, C] ---
    print(
        "Shot 1 — starting order under root: "
        f"{_root_children(adapter)}; A expanded, nested visible."
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # --- Shot 2 — same-parent reorder: drop C at slot 1 -> [A, C, B] ---
    a_item = model._items_by_id["./a.usda"]
    c_item = model._items_by_id["./c.usda"]
    # Same call path the TreeView would take: drop_accepted gate then drop.
    accepted = model.drop_accepted(a_item, c_item, 1)
    print(
        f"Shot 2 — drop_accepted(target=A, source=C, drop_location=1): "
        f"{accepted}"
    )
    assert accepted, "Step 43 reorder was rejected unexpectedly"
    model.drop(a_item, c_item, 1)
    await _drive(4)
    print(
        "Shot 2 — after same-parent reorder (C -> slot 1); root order: "
        f"{_root_children(adapter)}"
    )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # --- Shot 3 — cross-parent reparent: drop B onto A ---
    b_item = model._items_by_id["./b.usda"]
    accepted = model.drop_accepted(a_item, b_item, -1)
    print(
        f"Shot 3 — drop_accepted(target=A, source=B, drop_location=-1): "
        f"{accepted}"
    )
    assert accepted, "Step 43 reparent was rejected unexpectedly"
    model.drop(a_item, b_item, -1)
    await _drive(4)
    print(
        "Shot 3 — after reparent (B dropped onto A); root: "
        f"{_root_children(adapter)}; A's sublayers: "
        f"{adapter.get_sublayer_identifiers(adapter.find_layer('./a.usda'))}"
    )
    # Ensure the new child is visible — re-expand A in case the rebuild
    # collapsed it (it shouldn't with set_adapter in-place, but guard).
    if tree_view is not None:
        tree_view.set_expanded(a_item, True, False)
    await _drive(3)
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    # --- Rejection check: circular drop must not mutate state ---
    nested_item = model._items_by_id["./nested.usda"]
    rejected = model.drop_accepted(nested_item, a_item, -1)
    print(
        "Rejection check — drop_accepted(target=./nested, source=A) "
        f"(circular) returned {rejected} (expect False)"
    )
    assert rejected is False, "Circular drop was incorrectly accepted"

    # --- Shot 4 — Ctrl+Z twice restores [A, B, C] ---
    app.undo_manager.undo()
    app.undo_manager.undo()
    await _drive(4)
    print(
        "Shot 4 — after two undos; root order: "
        f"{_root_children(adapter)}; A's sublayers: "
        f"{adapter.get_sublayer_identifiers(adapter.find_layer('./a.usda'))}"
    )
    if tree_view is not None:
        tree_view.set_expanded(a_item, True, False)
    await _drive(3)
    uitesting.capture_screenshot(OUT_4)
    print(f"Saved: {OUT_4}")

    print()
    print("Step 43 behaviour summary:")
    print(
        "  - Drag a LayerItem row: get_drag_mime_data returns the "
        "layer identifier (root / session return ''; non-draggable)."
    )
    print(
        "  - drop_accepted gates the move: rejects source==target, "
        "reserved rows, circular moves, and non-writable parents."
    )
    print(
        "  - drop pushes MoveSublayerCommand through UndoManager — "
        "Ctrl+Z restores the prior sublayer order."
    )

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 43 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

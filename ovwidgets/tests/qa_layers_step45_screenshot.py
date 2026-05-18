# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 45 — external file drop → sublayer.

Step 45 teaches :meth:`~ovwidgets.layers.layer_model.LayerModel.drop_accepted`
and :meth:`~ovwidgets.layers.layer_model.LayerModel.drop` to recognise a
file-path string (or list of strings) as a legal drag source. Valid
``.usd`` / ``.usda`` / ``.usdc`` paths push one
:class:`~ovwidgets.layers.commands.InsertSublayerCommand` per file through
:attr:`~ovwidgets.app.application.Application.undo_manager`; multi-file
drops are wrapped in a single ``"Insert files"`` undo group so one
Ctrl+Z rewinds the whole batch. Drops onto the TreeView's empty
padding route through
:meth:`LayerWindow._on_empty_area_dropped` and land as sublayers of
the root layer.

ovui's headless test harness cannot synthesise native OS file-drop
gestures, so the QA script drives the same entry points the
TreeView / empty-area rectangle would and captures the resulting
tree after each gesture.

Shots:

1. **Shot 1** — ``/tmp/ovgear_layers_step45_1.png``: baseline tree
   before any external drop.
2. **Shot 2** — ``/tmp/ovgear_layers_step45_2.png``: drop a single
   ``.usda`` file onto ``./a.usda`` — new sublayer appears beneath
   it.
3. **Shot 3** — ``/tmp/ovgear_layers_step45_3.png``: multi-file drop
   between ``./a.usda`` and ``./b.usda`` — both paths land at the
   target slot and share one undo entry.
4. **Shot 4** — ``/tmp/ovgear_layers_step45_4.png``: invalid
   extension rejection — drop-accepted paints the red outline and
   sets the rejection-reason tooltip.
5. **Shot 5** — ``/tmp/ovgear_layers_step45_5.png``: empty-area drop
   — the root layer absorbs the file via
   ``LayerWindow._on_empty_area_dropped``.
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

OUT_1 = "/tmp/ovgear_layers_step45_1.png"
OUT_2 = "/tmp/ovgear_layers_step45_2.png"
OUT_3 = "/tmp/ovgear_layers_step45_3.png"
OUT_4 = "/tmp/ovgear_layers_step45_4.png"
OUT_5 = "/tmp/ovgear_layers_step45_5.png"


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
    return adapter


def _describe_tree(adapter: MockLayerStackAdapter) -> str:
    children = adapter.get_sublayer_identifiers(adapter.get_root_layer())
    return f"root children: {children!r}"


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

    await _drive(6)

    # --- Shot 1 — baseline before any external drop ---
    print(f"Shot 1 — baseline. {_describe_tree(adapter)}")
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # --- Shot 2 — drop a single .usda onto ./a.usda ---
    a_item = model._items_by_id["./a.usda"]
    model.drop(a_item, "/tmp/dropped_one.usda", -1)
    if tree_view is not None:
        tree_view.set_expanded(a_item, True, False)
    await _drive(5)
    a_children = adapter.get_sublayer_identifiers(
        adapter.find_layer("./a.usda")
    )
    print(
        f"Shot 2 — after single-file drop onto A. A sublayers: "
        f"{a_children!r}"
    )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # --- Shot 3 — multi-file between-drop at slot 1 (between A and B) ---
    model.drop(
        a_item,
        ["/tmp/dropped_batch_a.usda", "/tmp/dropped_batch_b.usdc"],
        1,
    )
    await _drive(5)
    history_len = len(app.undo_manager._undo_stack)
    print(
        f"Shot 3 — after multi-file drop between A and B. "
        f"{_describe_tree(adapter)} undo_stack_len={history_len}"
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    # --- Shot 4 — invalid extension rejection indicator ---
    b_item = model._items_by_id["./b.usda"]
    accepted = model.drop_accepted(b_item, "/tmp/image.png", -1)
    assert accepted is False, "PNG drop was accepted unexpectedly"
    await _drive(4)
    print(
        f"Shot 4 — invalid extension rejection. "
        f"{_describe_indicator(model)}"
    )
    uitesting.capture_screenshot(OUT_4)
    print(f"Saved: {OUT_4}")

    # Release the rejected indicator before continuing so the final
    # shot shows a clean tree.
    model._clear_drop_visual()
    await _drive(3)

    # --- Shot 5 — empty-area drop lands under the root layer ---
    handled = layer_window._model.request_insert_file_sublayers_at_root(
        "/tmp/dropped_empty_area.usda"
    )
    assert handled is True, "empty-area drop was rejected unexpectedly"
    await _drive(5)
    print(
        f"Shot 5 — after empty-area drop. {_describe_tree(adapter)}"
    )
    uitesting.capture_screenshot(OUT_5)
    print(f"Saved: {OUT_5}")

    print()
    print("Step 45 behaviour summary:")
    print(
        "  - drop_accepted / drop recognise str + list sources; "
        "paths ending in .usd/.usda/.usdc pass, everything else is "
        "rejected with a red outline."
    )
    print(
        "  - Single-file drop pushes one InsertSublayerCommand; "
        "multi-file drop wraps the batch in a single "
        "'Insert files' undo group."
    )
    print(
        "  - Drops onto the TreeView's empty scroll area route "
        "through LayerWindow._on_empty_area_dropped and land as "
        "sublayers of the root."
    )

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 45 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

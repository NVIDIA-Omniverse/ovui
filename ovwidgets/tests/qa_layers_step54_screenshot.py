# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshots for LAYERS-PLAN Step 54 — Footer toolbar.

Step 54 adds a 28-px footer strip at the bottom of the Layers
window carrying three icon buttons (Insert / Create / Delete) that
mirror the context-menu trio and route through the same undoable
command pipeline.

Shots:

1. **Shot 1** — ``/tmp/ovgear_layers_step54_1.png``: footer at rest
   with nothing selected. All three buttons visible; Delete is
   disabled (no single-layer selection).
2. **Shot 2** — ``/tmp/ovgear_layers_step54_2.png``: after selecting
   a sublayer row — Delete lights up (enabled) because the tree
   selection collapses to a single non-root layer.
3. **Shot 3** — ``/tmp/ovgear_layers_step54_3.png``: after clicking
   the Create button with the root selected — a fresh anonymous
   sublayer appears under the root and lands in the tree list.
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
from ovwidgets.common.settings import Settings
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.common.undo import UndoManager
from ovwidgets.layers import LayerItem, LayerModel, LayerWindow

OUT_1 = "/tmp/ovgear_layers_step54_1.png"
OUT_2 = "/tmp/ovgear_layers_step54_2.png"
OUT_3 = "/tmp/ovgear_layers_step54_3.png"


class _StubApp:
    """Minimal app surface for the Step 54 footer screenshots."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()
        self.settings = Settings()


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    adapter = MockLayerStackAdapter(include_session=False)
    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "background_base.usda",
        display_name="background_base.usda",
    )
    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "props_base.usda",
        display_name="props_base.usda",
    )
    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "characters_base.usda",
        display_name="characters_base.usda",
    )
    return adapter


def _find_layer_item(model: LayerModel, identifier: str) -> LayerItem:
    stack = list(model.get_item_children(None))
    while stack:
        node = stack.pop()
        if isinstance(node, LayerItem) and node.identifier == identifier:
            return node
        stack.extend(model.get_item_children(node))
    raise KeyError(identifier)


async def _main() -> None:
    adapter = _make_adapter()
    app = _StubApp()
    layer_window = LayerWindow(services=app, adapter=adapter)
    if layer_window.window is not None:
        layer_window.window.undock()
        layer_window.window.position_x = 40
        layer_window.window.position_y = 40
        layer_window.window.width = 520
        layer_window.window.height = 520
        layer_window.window.focus()

    await _drive(15)

    model = layer_window._model
    if not isinstance(model, LayerModel):
        raise RuntimeError(f"Expected LayerModel, got {type(model).__name__}")

    tree_view = layer_window._tree_view
    root_item = model.root_item
    if tree_view is not None and root_item is not None:
        tree_view.set_expanded(root_item, True, False)

    await _drive(8)

    # --- Shot 1 — footer at rest; Delete disabled, Insert/Create live. ---
    print("Shot 1 — footer at rest (no selection).")
    print(
        f"  Insert enabled: {layer_window._insert_button.enabled} | "
        f"Create enabled: {layer_window._create_button.enabled} | "
        f"Delete enabled: {layer_window._delete_button.enabled}"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # --- Shot 2 — single sublayer selected; Delete lights up. ---
    child = _find_layer_item(model, "background_base.usda")
    model.set_selected_items([child])
    layer_window._refresh_footer_state()
    await _drive(5)
    print(
        "Shot 2 — single sublayer selected. "
        f"Delete enabled: {layer_window._delete_button.enabled}"
    )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # --- Shot 3 — click Create with root selected. ---
    model.set_selected_items([root_item])
    layer_window._refresh_footer_state()
    await _drive(3)
    root_handle = adapter.get_root_layer()
    before = list(adapter.get_sublayer_identifiers(root_handle))
    layer_window._on_footer_create_clicked()
    await _drive(12)
    after = list(adapter.get_sublayer_identifiers(root_handle))
    new_ids = [i for i in after if i not in before]
    print(
        "Shot 3 — Create clicked on root. "
        f"Sublayers went from {len(before)} to {len(after)}. "
        f"New identifier(s): {new_ids}"
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    print()
    print("Step 54 behaviour summary:")
    print(
        "  - Footer strip sits at the bottom of the Layers window "
        "carrying Insert / Create / Delete buttons."
    )
    print(
        "  - Insert opens the Step-36 file picker and pushes an "
        "InsertSublayerCommand under the target."
    )
    print(
        "  - Create mints a fresh anonymous sublayer under the target "
        "via CreateSublayerCommand (path='')."
    )
    print(
        "  - Delete routes through LayerModel._request_remove_sublayer, "
        "sharing the dirty-confirm flow with the context menu."
    )
    print(
        "  - All three buttons disable when the action is not "
        "applicable (e.g. Delete on root)."
    )

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 54 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

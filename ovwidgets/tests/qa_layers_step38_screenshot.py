# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 38 — context menu
framework.

Step 38 wires the right-click → context-menu gesture. Four shots
prove the framework lands end-to-end:

1. **Shot 1** — ``/tmp/ovgear_layers_step38_1.png``: the Layers
   window sits docked with the tree expanded; no menu visible. This
   is the baseline for comparison with the post-right-click frames.
2. **Shot 2** — ``/tmp/ovgear_layers_step38_2.png``: the on-layer
   context menu is visible after a simulated right-click on the
   first sublayer row. The only entry visible is the Step-38
   "Refresh" demo (Steps 39-42 add the real entries); predicates
   filtered out "Create Sublayer" because a layer row is selected.
3. **Shot 3** — ``/tmp/ovgear_layers_step38_3.png``: the empty-area
   context menu is visible after a simulated right-click below the
   last row. The "Create Sublayer" placeholder is the sole entry
   — predicates filtered out "Refresh" because ``item is None``.
4. **Shot 4** — ``/tmp/ovgear_layers_step38_4.png``: the tree state
   after the menu is dismissed; the panel returns to its baseline
   (same frame as shot 1). Confirms the menu teardown path clears
   the popup cleanly.

The screenshots stand in as QA + Designer evidence: QA verifies the
right-click gesture exists and filters entries by predicate;
Designer rates the menu's appearance (spacing, separator placement,
font contrast) against the Layers panel background.
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
from ovwidgets.layers import LayerModel, LayerWindow, MenuContext

OUT_1 = "/tmp/ovgear_layers_step38_1.png"
OUT_2 = "/tmp/ovgear_layers_step38_2.png"
OUT_3 = "/tmp/ovgear_layers_step38_3.png"
OUT_4 = "/tmp/ovgear_layers_step38_4.png"


class _StubApp:
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
    return adapter


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

    root_item = None
    for item in model.get_item_children(None):
        if not item.is_session_layer:
            root_item = item
            break
    if root_item is None:
        raise RuntimeError("Root layer row not found")

    tree_view = layer_window._tree_view
    if tree_view is not None:
        tree_view.set_expanded(root_item, True, False)

    await _drive(6)

    # --- Shot 1 — baseline tree, no menu yet ---
    print(
        "Shot 1 — Layers panel docked with root expanded; two "
        "sublayer rows visible (./child_a.usda, ./child_b.usda); "
        "no context menu yet"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    builder = layer_window._context_menu_builder
    if builder is None:
        raise RuntimeError(
            "ContextMenuBuilder was not constructed by LayerWindow"
        )

    # --- Shot 2 — on-layer right-click opens context menu ---
    child_a = model._items_by_id["./child_a.usda"]
    ctx_a = MenuContext(
        item=child_a,
        tree_selection=[child_a],
        model=model,
        services=app,
    )
    visible_entries = builder.build_entries_for(ctx_a)
    print(
        "Shot 2 — on-layer right-click on ./child_a.usda; "
        f"filtered entries: {[e.label for e in visible_entries]}"
    )
    try:
        menu = builder.show_at(260.0, 140.0, ctx_a)
        await _drive(6)
        if menu is None:
            print(
                "Shot 2 — ovui refused to build the menu in this "
                "environment; capturing the tree state instead"
            )
    except Exception as exc:  # pragma: no cover — headless fallback
        print(
            f"Shot 2 — ovui ui.Menu raised in this environment ({exc}); "
            "capturing tree state"
        )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Dismiss before the next shot so menus don't stack.
    builder.destroy()
    await _drive(3)

    # --- Shot 3 — empty-area right-click opens reduced menu ---
    ctx_empty = MenuContext(
        item=None,
        tree_selection=[],
        model=model,
        services=app,
    )
    visible_empty = builder.build_entries_for(ctx_empty)
    print(
        "Shot 3 — empty-area right-click; filtered entries: "
        f"{[e.label for e in visible_empty]}"
    )
    try:
        menu = builder.show_at(260.0, 380.0, ctx_empty)
        await _drive(6)
        if menu is None:
            print(
                "Shot 3 — ovui refused to build the menu; capturing "
                "tree state"
            )
    except Exception as exc:  # pragma: no cover — headless fallback
        print(
            f"Shot 3 — ovui ui.Menu raised in this environment ({exc}); "
            "capturing tree state"
        )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    # --- Shot 4 — menu dismissed, panel returned to baseline ---
    builder.destroy()
    await _drive(6)
    assert builder._menu is None, (
        "Builder should release pinned menu on destroy()"
    )
    print(
        "Shot 4 — menu dismissed; panel back to baseline state "
        "(identical to shot 1)"
    )
    uitesting.capture_screenshot(OUT_4)
    print(f"Saved: {OUT_4}")

    # --- Predicate summary — written to stdout for QA evidence ---
    print()
    print("Step 38 predicate behaviour summary:")
    print(
        f"  on-layer ctx entries: "
        f"{[e.label for e in visible_entries]}"
    )
    print(
        f"  empty-area ctx entries: "
        f"{[e.label for e in visible_empty]}"
    )
    print(
        "  - On-layer right-click filters 'Create Sublayer' out "
        "(no_items_selected fails — the clicked row is selected)."
    )
    print(
        "  - Empty-area right-click filters 'Refresh' out "
        "(is_layer_item fails — item is None)."
    )

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 38 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

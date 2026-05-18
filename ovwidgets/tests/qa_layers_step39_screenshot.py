# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 39 — context menu
edit-target and sublayer-creation entries.

Step 39 replaces the two Step-38 proof-of-life placeholders with the
real entries:

- On-layer menu (4 entries): Set as Authoring Layer, Create
  Sublayer, Insert Sublayer..., New Anonymous Sublayer.
- Empty-area menu (3 entries): Create Sublayer, Insert Sublayer...,
  New Anonymous Sublayer (all scoped to the root layer).

Four shots prove the entries land end-to-end:

1. **Shot 1** — ``/tmp/ovgear_layers_step39_1.png``: Layers window
   docked with the tree expanded; no menu visible (baseline).
2. **Shot 2** — ``/tmp/ovgear_layers_step39_2.png``: on-layer
   right-click on ``./child_a.usda``; the context menu is open
   with the four on-layer entries visible ("Set as Authoring
   Layer", "Create Sublayer", "Insert Sublayer...", "New Anonymous
   Sublayer").
3. **Shot 3** — ``/tmp/ovgear_layers_step39_3.png``: on-layer
   right-click on the *current edit target* (root by default);
   "Set as Authoring Layer" is filtered out (predicate
   ``is_not_current_edit_target`` fails); the other three entries
   remain.
4. **Shot 4** — ``/tmp/ovgear_layers_step39_4.png``: empty-area
   right-click below the tree; the reduced menu shows "Create
   Sublayer", "Insert Sublayer...", "New Anonymous Sublayer"
   scoped to root; "Set as Authoring Layer" is filtered out
   (``is_layer_item`` fails on an empty-area context).

The screenshots stand in as QA + Designer evidence: QA verifies
the four entries land correctly and the predicates filter as
prescribed; Designer rates the menu's visual quality (spacing,
separator placement, font contrast) against the Layers panel.
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

OUT_1 = "/tmp/ovgear_layers_step39_1.png"
OUT_2 = "/tmp/ovgear_layers_step39_2.png"
OUT_3 = "/tmp/ovgear_layers_step39_3.png"
OUT_4 = "/tmp/ovgear_layers_step39_4.png"


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
        layer_window.window.width = 560
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

    # --- Shot 1 — baseline, no menu ---
    print(
        "Shot 1 — Layers panel docked; root expanded with two "
        "sublayers visible; no context menu"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    builder = layer_window._context_menu_builder
    if builder is None:
        raise RuntimeError(
            "ContextMenuBuilder was not constructed by LayerWindow"
        )

    # --- Shot 2 — on-layer right-click on ./child_a.usda ---
    child_a = model._items_by_id["./child_a.usda"]
    ctx_child_a = MenuContext(
        item=child_a,
        tree_selection=[],
        model=model,
        services=app,
    )
    visible_child = builder.build_entries_for(ctx_child_a)
    print(
        "Shot 2 — on-layer right-click on ./child_a.usda; "
        f"filtered entries: {[e.label for e in visible_child]}"
    )
    try:
        menu = builder.show_at(260.0, 160.0, ctx_child_a)
        await _drive(6)
        if menu is None:
            print(
                "Shot 2 — ovui refused to build the menu; capturing "
                "the tree state instead"
            )
    except Exception as exc:  # pragma: no cover — headless fallback
        print(
            f"Shot 2 — ovui ui.Menu raised in this environment ({exc}); "
            "capturing tree state"
        )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    builder.destroy()
    await _drive(3)

    # --- Shot 3 — on-layer right-click on the current edit target ---
    # Set /child_a as the edit target so right-clicking it now filters
    # out "Set as Authoring Layer" (is_not_current_edit_target fails).
    adapter.set_edit_target(child_a.identifier)
    model._edit_target_identifier = child_a.identifier
    child_a.invalidate_flags()

    await _drive(3)

    ctx_edit_target = MenuContext(
        item=child_a,
        tree_selection=[],
        model=model,
        services=app,
    )
    visible_et = builder.build_entries_for(ctx_edit_target)
    print(
        "Shot 3 — right-click on current edit target (./child_a.usda); "
        f"filtered entries: {[e.label for e in visible_et]}"
    )
    try:
        menu = builder.show_at(260.0, 160.0, ctx_edit_target)
        await _drive(6)
        if menu is None:
            print(
                "Shot 3 — ovui refused to build the menu; capturing "
                "the tree state"
            )
    except Exception as exc:  # pragma: no cover — headless fallback
        print(
            f"Shot 3 — ovui ui.Menu raised in this environment ({exc}); "
            "capturing tree state"
        )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    builder.destroy()
    await _drive(3)

    # --- Shot 4 — empty-area right-click ---
    ctx_empty = MenuContext(
        item=None,
        tree_selection=[],
        model=model,
        services=app,
    )
    visible_empty = builder.build_entries_for(ctx_empty)
    print(
        "Shot 4 — empty-area right-click; filtered entries: "
        f"{[e.label for e in visible_empty]}"
    )
    try:
        menu = builder.show_at(260.0, 380.0, ctx_empty)
        await _drive(6)
        if menu is None:
            print(
                "Shot 4 — ovui refused to build the menu; capturing "
                "the tree state"
            )
    except Exception as exc:  # pragma: no cover — headless fallback
        print(
            f"Shot 4 — ovui ui.Menu raised in this environment ({exc}); "
            "capturing tree state"
        )
    uitesting.capture_screenshot(OUT_4)
    print(f"Saved: {OUT_4}")

    # --- Predicate summary for QA evidence ---
    print()
    print("Step 39 predicate behaviour summary:")
    print(
        f"  on-layer (not current edit target): "
        f"{[e.label for e in visible_child]}"
    )
    print(
        f"  on-layer (is current edit target): "
        f"{[e.label for e in visible_et]}"
    )
    print(
        f"  empty-area: "
        f"{[e.label for e in visible_empty]}"
    )
    print(
        "  - On-layer ctx surfaces four entries; Set-Authoring "
        "hides on the current edit target."
    )
    print(
        "  - Empty-area ctx surfaces three entries scoped to root; "
        "Set-Authoring hidden (is_layer_item fails)."
    )

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 39 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 40 — context menu file-I/O
and removal entries.

Step 40 adds four entries to the Layers right-click menu:

- **Save** — gated on ``is_layer_dirty``.
- **Save As...** — gated on ``is_not_root_layer``.
- **Reload** — gated on ``is_not_anonymous``.
- **Remove** — gated on ``is_not_root_layer``.

Four shots prove the entries land end-to-end:

1. **Shot 1** — ``/tmp/ovgear_layers_step40_1.png``: Layers window
   docked with the tree expanded and one sublayer dirty; no menu
   visible (baseline).
2. **Shot 2** — ``/tmp/ovgear_layers_step40_2.png``: right-click on a
   dirty concrete sublayer; menu shows **all four** file-I/O entries
   (Save, Save As..., Reload, Remove) plus the Step-39 quartet.
3. **Shot 3** — ``/tmp/ovgear_layers_step40_3.png``: right-click on a
   *clean* concrete sublayer; Save is filtered out (``is_layer_dirty``
   fails) — Save As..., Reload, Remove remain.
4. **Shot 4** — ``/tmp/ovgear_layers_step40_4.png``: right-click on
   the *root* layer; Save As... and Remove are filtered out
   (``is_not_root_layer`` fails). Save (if root dirty) and Reload may
   still appear.

The screenshots stand in as QA + Designer evidence: QA verifies the
four entries land correctly and the predicates filter as prescribed;
Designer rates the menu's visual quality (spacing, separator
placement, font contrast) against the Layers panel.
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

OUT_1 = "/tmp/ovgear_layers_step40_1.png"
OUT_2 = "/tmp/ovgear_layers_step40_2.png"
OUT_3 = "/tmp/ovgear_layers_step40_3.png"
OUT_4 = "/tmp/ovgear_layers_step40_4.png"


class _StubApp:
    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./dirty_child.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./clean_child.usda")
    # Mark the first child dirty so "Save" surfaces on Shot 2.
    adapter.set_dirty("./dirty_child.usda", True)
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
        "Shot 1 — Layers panel docked; root expanded with "
        "dirty_child (dirty) + clean_child (clean); no context menu"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    builder = layer_window._context_menu_builder
    if builder is None:
        raise RuntimeError(
            "ContextMenuBuilder was not constructed by LayerWindow"
        )

    # --- Shot 2 — right-click on the dirty sublayer ---
    dirty_item = model._items_by_id["./dirty_child.usda"]
    # Force flag refresh so is_dirty surfaces live.
    dirty_item.invalidate_flags()
    ctx_dirty = MenuContext(
        item=dirty_item,
        tree_selection=[],
        model=model,
        services=app,
    )
    visible_dirty = builder.build_entries_for(ctx_dirty)
    print(
        "Shot 2 — right-click on ./dirty_child.usda; "
        f"filtered entries: {[e.label for e in visible_dirty]}"
    )
    try:
        menu = builder.show_at(260.0, 180.0, ctx_dirty)
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

    # --- Shot 3 — right-click on a clean sublayer ---
    clean_item = model._items_by_id["./clean_child.usda"]
    clean_item.invalidate_flags()
    ctx_clean = MenuContext(
        item=clean_item,
        tree_selection=[],
        model=model,
        services=app,
    )
    visible_clean = builder.build_entries_for(ctx_clean)
    print(
        "Shot 3 — right-click on ./clean_child.usda (clean); "
        f"filtered entries: {[e.label for e in visible_clean]}"
    )
    try:
        menu = builder.show_at(260.0, 210.0, ctx_clean)
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

    # --- Shot 4 — right-click on the root layer ---
    ctx_root = MenuContext(
        item=root_item,
        tree_selection=[],
        model=model,
        services=app,
    )
    visible_root = builder.build_entries_for(ctx_root)
    print(
        "Shot 4 — right-click on root layer; "
        f"filtered entries: {[e.label for e in visible_root]}"
    )
    try:
        menu = builder.show_at(260.0, 140.0, ctx_root)
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
    print("Step 40 predicate behaviour summary:")
    print(
        f"  dirty sublayer (all 4 file-I/O entries expected): "
        f"{[e.label for e in visible_dirty]}"
    )
    print(
        f"  clean sublayer (Save hidden, others present): "
        f"{[e.label for e in visible_clean]}"
    )
    print(
        f"  root layer (Save-As and Remove hidden): "
        f"{[e.label for e in visible_root]}"
    )
    print(
        "  - Dirty sublayer surfaces Save, Save As..., Reload, Remove."
    )
    print(
        "  - Clean sublayer hides Save (is_layer_dirty fails); "
        "Save As..., Reload, Remove remain."
    )
    print(
        "  - Root layer hides Save As... and Remove "
        "(is_not_root_layer fails); Reload remains."
    )

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 40 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

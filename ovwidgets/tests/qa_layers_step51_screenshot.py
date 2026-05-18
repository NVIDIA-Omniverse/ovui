# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshots for LAYERS-PLAN Step 51 — search field with tree filter.

Step 51 adds a 30-px filter bar above the Save-All toolbar. Typing
filters the Layers tree by display name; ancestors of matches stay
visible; the X button clears the search; an overlay reads "No
matching layers" when a filter rejects everything.

Shots:

1. **Shot 1** — ``/tmp/ovgear_layers_step51_1.png``: pristine tree
   with no filter (every sublayer visible under the root).
2. **Shot 2** — ``/tmp/ovgear_layers_step51_2.png``: filter set to
   "background" — only the background branch survives, the props
   branch is hidden, and ancestor promotion keeps root + the
   parent layer expanded so the nested ``background_gradient``
   match is reachable.
3. **Shot 3** — ``/tmp/ovgear_layers_step51_3.png``: filter set
   to a token that matches nothing — the "No matching layers"
   empty-state overlay paints over the (now empty) tree body.
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

OUT_1 = "/tmp/ovgear_layers_step51_1.png"
OUT_2 = "/tmp/ovgear_layers_step51_2.png"
OUT_3 = "/tmp/ovgear_layers_step51_3.png"


class _StubApp:
    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "background_base.usda",
        display_name="background_base.usda",
    )
    adapter.add_sublayer(
        "background_base.usda",
        "background_gradient.usda",
        display_name="background_gradient.usda",
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
        raise RuntimeError(
            f"Expected LayerModel, got {type(model).__name__}"
        )

    tree_view = layer_window._tree_view
    root_item = model.root_item
    # Expand the root + background_base so Shot 2 shows the ancestor
    # chain down to the nested gradient match.
    if tree_view is not None and root_item is not None:
        tree_view.set_expanded(root_item, True, False)
        bg = next(
            (s for s in root_item.sublayers
             if s.identifier == "background_base.usda"),
            None,
        )
        if bg is not None:
            tree_view.set_expanded(bg, True, False)

    await _drive(8)

    # --- Shot 1 — no filter, full tree visible ---
    print("Shot 1 — no filter. Tree shows every sublayer under root.")
    print(f"  filter_text={model.filter_text!r}")
    print(
        "  top children: "
        f"{[c.identifier for c in model.get_item_children(None)]}"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # --- Shot 2 — filter "background" (matches bg branch, hides props) ---
    if layer_window._filter_field is not None:
        layer_window._filter_field.model.set_value("background")
    # Headless fallback path in the window's filter handler applies
    # synchronously when no Application singleton exists; the QA script
    # runs under a real ui.run() loop so we also drive a few frames to
    # let the debounced timer fire.
    await _drive(20)
    print("Shot 2 — filter=\"background\". Props + characters branches hidden.")
    print(f"  filter_text={model.filter_text!r}")
    print(
        "  has_any_filter_match="
        f"{model.has_any_filter_match()}"
    )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # --- Shot 3 — filter matches nothing → empty-state overlay ---
    if layer_window._filter_field is not None:
        layer_window._filter_field.model.set_value("zzz_nothing_here")
    await _drive(20)
    print("Shot 3 — filter=\"zzz_nothing_here\". Empty-state overlay visible.")
    print(f"  filter_text={model.filter_text!r}")
    print(
        "  has_any_filter_match="
        f"{model.has_any_filter_match()}"
    )
    if layer_window._empty_state_container is not None:
        print(
            "  empty_state_container.visible="
            f"{layer_window._empty_state_container.visible}"
        )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    print()
    print("Step 51 behaviour summary:")
    print(
        "  - Search field at top of the Layers window filters the tree "
        "by layer display name (case-insensitive substring)."
    )
    print(
        "  - Ancestors of matches stay visible so the expansion path "
        "to the match is preserved (child_filtered flag)."
    )
    print(
        "  - Clear X button (visible only while a filter is active) "
        "resets the field to the empty string."
    )
    print(
        "  - Filter apply is debounced 150ms via Application.call_later "
        "to avoid a rebuild per keystroke."
    )
    print(
        "  - \"No matching layers\" overlay replaces the tree body "
        "when the active filter rejects every row."
    )

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 51 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

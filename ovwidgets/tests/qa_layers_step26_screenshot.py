# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 26 — mid-session ancestor repaint.

Step 25 resolved the half-green leading icon
(``Layers.LeadingIcon::has_descendant``) on first paint from the
``_has_edit_target_descendant`` flag already set by Step 24. But the
flag is flipped inside ``LayerModel._update_edit_target`` *after* the
ancestor row has already been rendered, and the model fired
``_item_changed`` only on the target clones — so an already-visible
ancestor carried a stale icon until the user forced a repaint
(hover, scroll, expand).

Step 26 closes that gap by firing ``_item_changed(ancestor)`` on
every row whose ancestor flag flipped during the clear or set phase.
The half-green icon now tracks a mid-session edit-target swap in
realtime.

Four shots isolate the before-/after- contract:

1. **Shot 1** — ``/tmp/ovgear_layers_step26_1.png``: baseline. Default
   edit target = root. ``./mid.usda`` (ancestor of the future target)
   paints its neutral leading icon; root paints the full green row.
2. **Shot 2** — ``/tmp/ovgear_layers_step26_2.png``: immediately after
   ``adapter.set_edit_target("./deep.usda")``. Without Step 26 the
   ``./mid.usda`` row kept its Shot-1 neutral icon — now it flips to
   the half-green ``has_descendant`` state without any interaction.
   Root's leading icon also flips to half-green for the same reason.
3. **Shot 3** — ``/tmp/ovgear_layers_step26_3.png``: after
   ``adapter.set_edit_target(ROOT_LAYER_IDENTIFIER)``. The half-green
   icons on ``./mid.usda`` and root both clear without a hover-
   triggered repaint — the ancestor chain now returns to the neutral
   state in the same event dispatch that moved the target.
4. **Shot 4** — ``/tmp/ovgear_layers_step26_4.png``: sibling swap.
   From root → ``./sib.usda`` → ``./deep.usda`` and back to
   ``./sib.usda``. Root is the shared ancestor of both siblings; it
   must stay half-green across the entire sequence without flicker
   because Step 26's dedup suppresses the clear-phase fire on the
   shared ancestor when the set phase re-enters it.
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
)

OUT_1 = "/tmp/ovgear_layers_step26_1.png"
OUT_2 = "/tmp/ovgear_layers_step26_2.png"
OUT_3 = "/tmp/ovgear_layers_step26_3.png"
OUT_4 = "/tmp/ovgear_layers_step26_4.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    """Seed a hierarchy with an intermediate ancestor and a sibling.

    Layout::

        session
        root                              ← default edit target
          ├── ./sib.usda
          └── ./mid.usda
                └── ./deep.usda
    """
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./sib.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./mid.usda")
    adapter.add_sublayer("./mid.usda", "./deep.usda")
    return adapter


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
    mid_item = model._items_by_id.get("./mid.usda")
    if mid_item is None:
        raise RuntimeError("./mid.usda row not found")
    tree_view.set_expanded(mid_item, True, False)

    for item_list in model._sublayers_cache.values():
        for item in item_list:
            for col in range(LayerModel.NUM_COLUMNS):
                model.get_item_value_model(item, col)
    model._item_changed(None)

    await _drive(6)
    print(
        "Shot 1 — baseline. Edit target = root. Root row fully green; "
        "./mid.usda and ./sib.usda paint the neutral leading icon. "
        "This is the 'stale-icon risk' starting state — everything "
        "is already rendered."
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — move target deep. Ancestors must flip to half-green
    # *without* a hover / scroll. Notably we DO NOT call
    # ``model._item_changed(None)`` between the set_edit_target call
    # and the screenshot, so any repaint has to come from Step 26's
    # ancestor-fires.
    adapter.set_edit_target("./deep.usda")
    await _drive(6)
    print(
        "Shot 2 — after set_edit_target('./deep.usda'). No user "
        "interaction between set and capture; the half-green icons on "
        "./mid.usda + root are the proof Step 26 repainted the "
        "ancestor rows on its own."
    )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Shot 3 — clear the deep target back to root. The half-green
    # icons on ./mid.usda + root must disappear without a hover.
    adapter.set_edit_target(ROOT_LAYER_IDENTIFIER)
    await _drive(6)
    print(
        "Shot 3 — after set_edit_target(root). Half-green icons on "
        "./mid.usda + root clear in the same event dispatch that "
        "moved the target. Root row paints the full green again."
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    # Shot 4 — sibling swap exercising the dedup. Without dedup the
    # shared root ancestor would see back-to-back clear + set fires
    # on every swap; the test pins that behaviour for the dev logs
    # but the human signal here is "root stays half-green, no
    # flicker".
    adapter.set_edit_target("./sib.usda")
    await _drive(3)
    adapter.set_edit_target("./deep.usda")
    await _drive(3)
    adapter.set_edit_target("./sib.usda")
    await _drive(6)
    print(
        "Shot 4 — sibling swap. Edit target cycled sib → deep → sib. "
        "Root stays half-green throughout (shared ancestor of both "
        "siblings and deep); ./mid.usda transitions half-green → "
        "neutral as the target leaves its subtree."
    )
    uitesting.capture_screenshot(OUT_4)
    print(f"Saved: {OUT_4}")

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 26 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

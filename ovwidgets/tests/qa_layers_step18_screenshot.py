# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 18 — name column value model.

Name column now renders through :class:`LayerNameValueModel`: the label
picks up the state suffix (``(Authoring Layer)`` / ``(Missing)`` /
``(Anonymous)`` / ``(Read Only)``) and a color role mapped to the
``Layers.NameLabel::<role>`` style selector.

The three shots together cover every declared color role:

1. **Shot 1** — ``/tmp/ovgear_layers_step18_1.png``: stage with root
   edit target (green ``(Authoring Layer)`` label), an anonymous
   session layer, a normal sublayer, a missing sublayer (red), a
   muted sublayer (gray), and a locked sublayer (gray).
2. **Shot 2** — ``/tmp/ovgear_layers_step18_2.png``: edit target
   moved to the muted sublayer — disabled precedence means the row
   stays gray rather than turning green.
3. **Shot 3** — ``/tmp/ovgear_layers_step18_3.png``: edit target on
   the missing sublayer — missing wins over authoring so the row
   stays red and the suffix is ``(Missing)``, not
   ``(Authoring Layer)``.
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
from ovwidgets.layers import LayerDelegate, LayerModel, LayerWindow

OUT_1 = "/tmp/ovgear_layers_step18_1.png"
OUT_2 = "/tmp/ovgear_layers_step18_2.png"
OUT_3 = "/tmp/ovgear_layers_step18_3.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    """Seed a stack that exercises every name-label state at once.

    Tree shape (rendered top → bottom after the session layer):
    ```
    session                 (Anonymous)
    root                    (Authoring Layer)
      normal.usda
      broken.usda           (Missing)
      muted.usda            [muted → disabled]
      locked.usda           [locked → disabled]
    ```
    """
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./normal.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./broken.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./muted.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./locked.usda")
    # Poke state — ``set_missing`` would fire an ``INFO_CHANGED`` event
    # which is currently classified as structural; the rebuild is fine
    # for QA but we mutate the record directly to keep the shot order
    # deterministic (no sublayer reordering between shots).
    adapter._layers["./broken.usda"].missing = True
    adapter.set_mute("./muted.usda", True)
    adapter.set_lock("./locked.usda", True)
    return adapter


def _set_edit_target(model: LayerModel, identifier: str) -> None:
    """Stamp ``is_edit_target`` on every item matching ``identifier``.

    Step 21 lands the real marker walk; until then the QA script sets
    the flag directly so each shot can isolate a different color-role
    precedence rule. After mutating, emit ``_item_changed`` for every
    touched row so the ``TreeView`` rebuilds the name-column widget
    — a plain ``_item_changed(None)`` only re-queries children, not
    cell content.
    """
    touched = []
    for item_list in model._sublayers_cache.values():
        for item in item_list:
            new_state = item.identifier == identifier
            if item.is_edit_target != new_state:
                item.is_edit_target = new_state
                touched.append(item)
    for item in touched:
        model._item_changed(item)


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

    # Shot 1 — root is edit target. All four color roles visible.
    _set_edit_target(model, ROOT_LAYER_IDENTIFIER)
    model._item_changed(None)
    await _drive(6)
    print(
        "Shot 1 — root edit target; normal / authoring / missing / disabled "
        "states visible"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — edit target on the muted sublayer. Disabled wins over
    # edit_target so the row stays gray with the ``(Authoring Layer)``
    # suffix still appended (suffix precedence gives edit_target
    # lower than missing / anonymous / read_only — muted is a color
    # signal, not a suffix signal, so the suffix still shows).
    _set_edit_target(model, "./muted.usda")
    model._item_changed(None)
    await _drive(6)
    print(
        "Shot 2 — muted edit target; color is disabled, suffix is "
        "(Authoring Layer)"
    )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Shot 3 — edit target on the missing sublayer. Missing wins on
    # both color and suffix.
    _set_edit_target(model, "./broken.usda")
    model._item_changed(None)
    await _drive(6)
    print(
        "Shot 3 — missing edit target; color is missing, suffix is (Missing)"
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 18 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

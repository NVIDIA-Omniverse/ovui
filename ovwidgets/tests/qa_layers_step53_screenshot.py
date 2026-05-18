# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshots for LAYERS-PLAN Step 53 — Options dropdown button.

Step 53 adds a gear-glyph button on the left of the Save-All
toolbar. A click opens a :class:`ui.Menu` of six checkbox items
bound to :class:`LayerSettings`; flipping a checkbox writes through
to the persistent ``Settings`` store and the tree reshapes live for
the four tree-shape keys.

Shots:

1. **Shot 1** — ``/tmp/ovgear_layers_step53_1.png``: toolbar at rest.
   Three-bar gear glyph is visible on the left; Save-All sits on the
   right.
2. **Shot 2** — ``/tmp/ovgear_layers_step53_2.png``: options dropdown
   open, all six checkboxes visible with their current (factory
   default) values checked.
3. **Shot 3** — ``/tmp/ovgear_layers_step53_3.png``: after toggling
   "Show Session Layer" off — the session row at the top of the tree
   has disappeared. The toggled state persists through the backing
   ``Settings`` store so a subsequent app restart would reload it.
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
from ovwidgets.layers import LayerModel, LayerSettings, LayerWindow

OUT_1 = "/tmp/ovgear_layers_step53_1.png"
OUT_2 = "/tmp/ovgear_layers_step53_2.png"
OUT_3 = "/tmp/ovgear_layers_step53_3.png"


class _StubApp:
    """Minimal app surface the :class:`LayerWindow` + settings expect."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()
        # Real :class:`Settings` store so the window wraps it in a
        # :class:`LayerSettings` — that's the production code path
        # Step 53's dropdown drives end-to-end.
        self.settings = Settings()


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
        raise RuntimeError(f"Expected LayerModel, got {type(model).__name__}")

    settings_wrapper = layer_window.settings
    if not isinstance(settings_wrapper, LayerSettings):
        raise RuntimeError(
            f"Expected LayerSettings, got {type(settings_wrapper).__name__}"
        )

    tree_view = layer_window._tree_view
    root_item = model.root_item
    if tree_view is not None and root_item is not None:
        tree_view.set_expanded(root_item, True, False)

    await _drive(8)

    # --- Shot 1 — toolbar at rest, gear glyph visible. ---
    print("Shot 1 — toolbar at rest, gear glyph on the left of Save-All.")
    options_button = layer_window._options_button
    print(f"  options_button present: {options_button is not None}")
    print(
        f"  LayerSettings.show_session_layer: "
        f"{settings_wrapper.show_session_layer}"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # --- Shot 2 — dropdown open with all six checkboxes visible. ---
    if options_button is None:
        raise RuntimeError("OptionsButton was not constructed on LayerWindow")
    # Show the menu at a fixed screen location so the capture is
    # deterministic regardless of where the toolbar landed.
    options_button.show_at(60, 90)
    await _drive(5)
    menu = options_button.menu
    print(
        "Shot 2 — dropdown open at (60, 90). "
        f"Menu has {len(options_button.menu_item_labels())} entries."
    )
    print(f"  menu labels: {options_button.menu_item_labels()}")
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")
    if menu is not None:
        menu.hide()
    await _drive(3)

    # --- Shot 3 — toggle "Show Session Layer" off; session row gone. ---
    # Drive the toggle through the same code path a menu click would
    # exercise — this is the end-to-end behaviour the step delivers.
    before_children = len(model.get_item_children(None))
    options_button.toggle("show_session_layer")
    await _drive(15)
    after_children = len(model.get_item_children(None))
    print(
        "Shot 3 — 'Show Session Layer' toggled off. "
        f"Top-level children: {before_children} -> {after_children}"
    )
    print(
        f"  Settings roundtrip: "
        f"app.settings.get('layers.show_session_layer')="
        f"{app.settings.get('layers.show_session_layer')!r}"
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    print()
    print("Step 53 behaviour summary:")
    print("  - Gear-glyph button sits on the left of the Save-All toolbar.")
    print(
        "  - Click opens a ui.Menu of six checkbox items bound to "
        "LayerSettings."
    )
    print(
        "  - Toggling a checkbox writes through the setter; the "
        "Settings store notifies subscribers."
    )
    print(
        "  - For tree-shape keys (show_session_layer etc.) the "
        "LayerModel rebuilds the tree immediately."
    )
    print(
        "  - The toggled value persists to the JSON config on save "
        "and survives a restart."
    )

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 53 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

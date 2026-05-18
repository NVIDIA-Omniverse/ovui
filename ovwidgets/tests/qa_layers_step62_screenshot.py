# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshots for LAYERS-PLAN Step 62 — final polish.

Step 62 layers in the last round of polish: tooltips on every
interactive surface (save/mute/lock icons, Save-All, Options gear,
Insert/Create/Delete footer), a 1-px keyboard focus ring, a
placeholder hint inside the filter field, and a helpful empty-state
message when no stage is loaded.

Shots:

1. **Shot 1** — ``/tmp/ovgear_layers_step62_1.png``: default state
   with a focused row (focus ring on ``background_base.usda``) and
   the filter field showing the "Filter layers..." placeholder.
2. **Shot 2** — ``/tmp/ovgear_layers_step62_2.png``: same layout
   with the filter field active ("base") so the placeholder is
   hidden.
3. **Shot 3** — ``/tmp/ovgear_layers_step62_3.png``: empty-stage
   message — the window with ``adapter=None`` so the "Open a USD
   stage to see layers" copy is rendered.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

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
from ovwidgets.layers.layer_delegate import LayerDelegate

OUT_1 = "/tmp/ovgear_layers_step62_1.png"
OUT_2 = "/tmp/ovgear_layers_step62_2.png"
OUT_3 = "/tmp/ovgear_layers_step62_3.png"


class _StubApp:
    """Minimal app surface the Layers window reaches for."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()
        self.settings = Settings()
        self._layer_adapter: Optional[Any] = None
        self._layer_window: Optional[Any] = None


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
    # Mark one layer dirty so the save column paints the dot (whose
    # tooltip carries the Step 62 "Save <name> to disk" cue).
    adapter.set_dirty("background_base.usda", True)
    # Lock another one so the lock-column tooltip lands on the
    # "Unlock this layer" branch.
    adapter.set_lock("props_base.usda", True)
    return adapter


def _report_polish_state(model: LayerModel, window: LayerWindow) -> None:
    print("Step 62 polish surface summary:")
    print(f"  Filter placeholder text : {window.FILTER_PLACEHOLDER_TEXT!r}")
    print(f"  Empty-stage message     : {window.EMPTY_STAGE_MESSAGE!r}")
    print("  Delegate tooltip copy   :")
    print(f"    SAVE                   : {LayerDelegate.SAVE_TOOLTIP!r}")
    print(
        f"    MUTE / unmuted         : "
        f"{LayerDelegate.LOCAL_MUTE_TOOLTIP_UNMUTED!r}"
    )
    print(
        f"    MUTE / muted           : "
        f"{LayerDelegate.LOCAL_MUTE_TOOLTIP_MUTED!r}"
    )
    print(
        f"    LOCK / unlocked        : "
        f"{LayerDelegate.LOCK_TOOLTIP_UNLOCKED!r}"
    )
    print(f"    LOCK / locked          : {LayerDelegate.LOCK_TOOLTIP_LOCKED!r}")
    print(
        f"    READ-ONLY              : {LayerDelegate.READONLY_OVERLAY_TOOLTIP!r}"
    )
    root = model.root_item
    if root is None:
        return
    focused = [
        i for i in _walk(root) if isinstance(i, LayerItem) and i.is_focused
    ]
    print(f"  Focused rows            : {[i.identifier for i in focused]}")


def _walk(node: LayerItem):
    yield node
    for child in node._sublayers:
        yield from _walk(child)


async def _main() -> None:
    adapter = _make_adapter()
    app = _StubApp()
    app._layer_adapter = adapter

    layer_window = LayerWindow(services=app, adapter=adapter)
    app._layer_window = layer_window
    if layer_window.window is not None:
        layer_window.window.undock()
        layer_window.window.position_x = 40
        layer_window.window.position_y = 40
        layer_window.window.width = 520
        layer_window.window.height = 480
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

    # ── Shot 1 — focus ring on a single-selected row + placeholder ──────
    # Pick the first child so the focus ring sits on a clearly visible
    # row that is not the root (so the green edit-target overlay
    # doesn't share the row).
    target_id = "background_base.usda"
    target = model._items_by_id.get(target_id)
    if isinstance(target, LayerItem):
        layer_window._on_tree_selection_changed([target])
        # Force the TreeView selection too so the visual state matches
        # the focus flag (selection-highlight paints the row blue;
        # focus-ring overlays the accent-outline on top).
        if tree_view is not None:
            try:
                tree_view.selection = [target]
            except Exception:
                pass
    await _drive(6)
    print(
        "Shot 1 — focus ring on 'background_base.usda'; filter field shows "
        "the 'Filter layers...' placeholder."
    )
    _report_polish_state(model, layer_window)
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # ── Shot 2 — filter field active ("base"); placeholder hidden ────────
    if layer_window._filter_field is not None:
        layer_window._filter_field.model.set_value("base")
    await _drive(8)
    print("Shot 2 — filter text 'base'; placeholder hidden, clear-X visible.")
    if layer_window._filter_placeholder is not None:
        print(
            f"  placeholder.visible   : {layer_window._filter_placeholder.visible}"
        )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")
    # Clear the filter so the next shot is back in "default" state.
    if layer_window._filter_field is not None:
        layer_window._filter_field.model.set_value("")
    await _drive(4)

    # ── Shot 3 — empty-stage message (no adapter loaded) ────────────────
    # Tear down the current adapter so the window falls back to its
    # Step-62 polish empty-state copy. The window rebuilds the frame
    # on ``set_adapter(None)`` if visible, so one more drive pass is
    # enough to capture the new body.
    layer_window.set_adapter(None)
    await _drive(10)
    print("Shot 3 — empty-stage message rendered (no adapter loaded).")
    print(f"  EMPTY_STAGE_MESSAGE   : {layer_window.EMPTY_STAGE_MESSAGE!r}")
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    print()
    print("Step 62 behaviour summary:")
    print(
        "  - Save / mute / lock icons carry action-centred tooltips; the "
        "name column tooltip exposes the full identifier so a truncated "
        "display name is still recoverable on hover."
    )
    print(
        "  - Save All, Options gear, and Insert/Create/Delete footer "
        "buttons kept their prior tooltips (set in Steps 35 / 53 / 54); "
        "Step 62 adds the filter field tooltip + placeholder overlay."
    )
    print(
        "  - Focus ring paints a 1-px accent border on the single "
        "focused row (keyboard nav / single-select). Multi-select "
        "clears the ring because there is no single arrow target."
    )
    print(
        "  - Empty-stage body now reads 'Open a USD stage to see "
        "layers' — an actionable hint rather than a terse dash."
    )

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 62 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

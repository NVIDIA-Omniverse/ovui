# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshots for LAYERS-PLAN Step 60 — Theme & palette QA.

Step 60 asks for visual proof that both dark and light themes render
every row state correctly. This script:

1. Spins up a headless ``LayerWindow`` against a :class:`MockLayerStackAdapter`
   seeded with a layer stack that covers the full state matrix:
   - normal row
   - edit-target row (green row background, green text)
   - muted row (dimmed text / muted-eye icon)
   - locked row (padlock closed)
   - missing row (red text + X badge)
   - read-only row (padlock backdrop overlay)
   - anonymous session layer ([anon] suffix)
   - combined: edit-target + muted (green bg + disabled-gray label)
   - combined: missing + read-only (red label + backdrop)
2. Captures ``/tmp/ovgear_layers_step60_dark.png`` under the dark theme.
3. Switches to ``light`` via ``set_theme("light")`` and captures
   ``/tmp/ovgear_layers_step60_light.png``.

Both screenshots share the same stage content so a side-by-side
inspection reads the palette cascade directly.

A text summary of each row's resolved palette tokens is also printed —
useful as proof of coverage when a screenshot renderer is not
available in the execution environment.
"""

from __future__ import annotations

import os
import sys
from typing import Any, List, Optional

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

OUT_DARK = "/tmp/ovgear_layers_step60_dark.png"
OUT_LIGHT = "/tmp/ovgear_layers_step60_light.png"


class _StubApp:
    """Minimal app surface the LayerWindow expects."""

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
    """Build a state-matrix stack covering every row type Step 60 names."""
    adapter = MockLayerStackAdapter(include_session=True)
    # Edit target flipped to an explicit sublayer below so row 0 (root)
    # stays neutral for the "normal" state sample.

    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "edit_target_layer.usda",
        display_name="edit_target_layer.usda",
    )
    adapter.set_edit_target("edit_target_layer.usda")

    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "muted_layer.usda",
        display_name="muted_layer.usda",
    )
    adapter.set_mute("muted_layer.usda", True)

    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "locked_layer.usda",
        display_name="locked_layer.usda",
    )
    adapter.set_lock("locked_layer.usda", True)

    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "missing_layer.usda",
        display_name="missing_layer.usda",
    )
    adapter.set_missing("missing_layer.usda", True)

    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "readonly_layer.usda",
        display_name="readonly_layer.usda",
    )
    adapter.set_read_only("readonly_layer.usda", True)

    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "dirty_layer.usda",
        display_name="dirty_layer.usda",
    )
    adapter.set_dirty("dirty_layer.usda", True)

    # Combined state 1: edit_target + muted. This sublayer is not the
    # adapter's edit target (the first one above is) but the test helper
    # flips the item's ``_is_edit_target`` flag below so the delegate
    # paints the combined cascade on this row too — gives us a concrete
    # visual of the disabled-label-on-green-bg combination without
    # breaking the "one authoring layer" adapter rule.
    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "edit_target_muted.usda",
        display_name="edit_target_muted.usda",
    )
    adapter.set_mute("edit_target_muted.usda", True)

    # Combined state 2: missing + read-only. Both bits on one sublayer
    # so the red label sits next to the padlock backdrop on the same
    # row — the Step 27 SVG pack's combined signal.
    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "missing_readonly.usda",
        display_name="missing_readonly.usda",
    )
    adapter.set_missing("missing_readonly.usda", True)
    adapter.set_read_only("missing_readonly.usda", True)

    return adapter


def _find_layer_item(model: LayerModel, identifier: str) -> LayerItem:
    stack: List[LayerItem] = list(model.get_item_children(None))
    while stack:
        node = stack.pop()
        if isinstance(node, LayerItem) and node.identifier == identifier:
            return node
        stack.extend(model.get_item_children(node))
    raise KeyError(identifier)


def _print_row_palette_summary(model: LayerModel) -> None:
    """Print each row's resolved role tokens.

    Acts as a text-log proof-of-coverage the screenshot renderer can
    always emit, even when no PNG is written (the headless CI path
    lands here when the display buffer is unavailable).
    """
    from ovwidgets.layers.layer_delegate import LayerDelegate

    delegate = LayerDelegate()
    print("  Row state matrix:")
    stack: List[LayerItem] = list(model.get_item_children(None))
    rows: List[LayerItem] = []
    while stack:
        node = stack.pop(0)
        if isinstance(node, LayerItem):
            rows.append(node)
            stack = list(model.get_item_children(node)) + stack
    for item in rows:
        name_model = model.get_item_value_model(item, 0)
        row_bg = delegate._row_bg_name(item)
        icon = delegate._leading_icon_state(item)
        role = name_model.get_color_role()
        flags: List[str] = []
        if item.is_missing:
            flags.append("missing")
        if item.is_read_only:
            flags.append("read_only")
        if item.is_muted:
            flags.append("muted")
        if item.is_locked:
            flags.append("locked")
        if item.is_anonymous:
            flags.append("anonymous")
        if item.is_dirty:
            flags.append("dirty")
        if item._is_edit_target:
            flags.append("edit_target")
        print(
            f"    - {item.identifier:<30s} "
            f"row_bg={row_bg:<20s} icon={icon:<15s} "
            f"label_role={role:<13s} flags={','.join(flags) or '<none>'}"
        )


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
        layer_window.window.width = 620
        layer_window.window.height = 580
        layer_window.window.focus()

    await _drive(15)

    model = layer_window._model
    if not isinstance(model, LayerModel):
        raise RuntimeError(f"Expected LayerModel, got {type(model).__name__}")

    tree_view = layer_window._tree_view
    root_item = model.root_item
    if tree_view is not None and root_item is not None:
        tree_view.set_expanded(root_item, True, False)

    # Flip the combined-cascade row's edit-target flag post-build so the
    # delegate paints the green bg + disabled gray label on one row
    # (see the comment in ``_make_adapter`` — the adapter can only have
    # one "real" edit target at a time).
    try:
        combined = _find_layer_item(model, "edit_target_muted.usda")
        combined._is_edit_target = True
        combined.invalidate_flags()
    except KeyError:
        pass

    await _drive(8)

    # ── Dark theme ──────────────────────────────────────────────────
    set_theme("dark")
    await _drive(6)
    print("Shot 1 — dark theme.")
    _print_row_palette_summary(model)
    uitesting.capture_screenshot(OUT_DARK)
    print(f"Saved: {OUT_DARK}")

    # ── Light theme ─────────────────────────────────────────────────
    set_theme("light")
    await _drive(6)
    print("Shot 2 — light theme.")
    _print_row_palette_summary(model)
    uitesting.capture_screenshot(OUT_LIGHT)
    print(f"Saved: {OUT_LIGHT}")

    # Restore dark theme before teardown so any downstream windows in
    # the same process see the expected default.
    set_theme("dark")
    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 60 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

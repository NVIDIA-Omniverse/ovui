# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 36 — Save-As file picker.

Four shots prove the deliverable:

1. **Shot 1** — ``/tmp/ovgear_layers_step36_1.png``: anonymous
   sublayer present and dirty. The per-row save dot is **lit**
   (Step 36 flipped Step-19's anonymous clamp because the click
   has a valid destination now — the save-as file picker).
2. **Shot 2** — ``/tmp/ovgear_layers_step36_2.png``: the
   :func:`ovwidgets.common.file_dialogs.save_file_dialog` modal is open over
   the Layers panel with a default filename preloaded in the
   :class:`ui.StringField`.
3. **Shot 3** — ``/tmp/ovgear_layers_step36_3.png``: user clicks
   **Save**; the modal closes, the anonymous row is gone from the
   tree (replaced by the saved file path), and the
   :class:`SaveLayerAsCommand` is now on the undo stack.
4. **Shot 4** — ``/tmp/ovgear_layers_step36_4.png``: user clicks
   Undo; the parent-reference is restored to the original anonymous
   identifier (the file stays on disk per M5, but the stack now
   points back at the anon layer).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting

from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.file_dialogs import save_file_dialog
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.common.undo import UndoManager
from ovwidgets.layers import (
    LayerDelegate,
    LayerModel,
    LayerWindow,
)
from ovwidgets.layers.commands import SaveLayerAsCommand

OUT_1 = "/tmp/ovgear_layers_step36_1.png"
OUT_2 = "/tmp/ovgear_layers_step36_2.png"
OUT_3 = "/tmp/ovgear_layers_step36_3.png"
OUT_4 = "/tmp/ovgear_layers_step36_4.png"

SAVE_AS_PATH = "/tmp/ovgear_step36_saved.usda"


class _StubApp:
    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child.usda")
    # Anonymous dirty sublayer — the primary save-as target.
    adapter.create_sublayer(
        ROOT_LAYER_IDENTIFIER, position=-1, new_layer_path="",
    )
    anon_id = next(
        lid for lid in adapter._layers if lid.startswith("anon:")
    )
    adapter.set_dirty(anon_id, True)
    return adapter


def _anon_id(adapter: MockLayerStackAdapter) -> str:
    return next(
        lid for lid in adapter._layers if lid.startswith("anon:")
    )


def _invalidate_all(model: LayerModel) -> None:
    for clone_list in model._sublayers_cache.values():
        for clone in clone_list:
            clone.invalidate_flags()


async def _main() -> None:
    adapter = _make_adapter()
    app = _StubApp()
    layer_window = LayerWindow(services=app, adapter=adapter)
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
        raise RuntimeError("TreeView not built")
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

    await _drive(6)

    anon_identifier = _anon_id(adapter)
    anon_item = model._items_by_id[anon_identifier]

    # --- Shot 1 — anonymous dirty row, save dot lit ---
    vm = model.get_item_value_model(anon_item, 2)
    assert vm.get_value_as_bool() is True, (
        "Step 36 anonymous dirty layer must report saveable=True"
    )
    print(
        "Shot 1 — anonymous dirty layer; per-row save dot lit "
        "(Step 36 flipped the Step-19 anonymous clamp)"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # --- Shot 2 — open the save-as dialog directly ---
    captured_dialog = {"dlg": None, "selected": None}

    def _on_selected(path: str) -> None:
        captured_dialog["selected"] = path
        model._perform_save_as(
            anon_identifier, path, replace_in_parent=True,
        )

    dialog = save_file_dialog(
        title=f"Save '{anon_item.display_name}' as...",
        default_name="untitled.usda",
        on_selected=_on_selected,
    )
    captured_dialog["dlg"] = dialog
    if dialog is None:
        print(
            "Shot 2 — ovui refused to construct the Window modal in "
            "this environment; skipping dialog capture"
        )
    else:
        dialog.set_path(SAVE_AS_PATH)
        await _drive(6)
        print(
            "Shot 2 — Save-As modal open with default path "
            f"preloaded at {SAVE_AS_PATH}"
        )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # --- Shot 3 — confirm the save; command pushed, parent swapped ---
    if dialog is not None:
        dialog.confirm()
    else:
        # Fallback — drive the command seam directly so the rest of
        # the QA cycle still captures the post-save state.
        model._perform_save_as(
            anon_identifier, SAVE_AS_PATH, replace_in_parent=True,
        )
    _invalidate_all(model)
    model._item_changed(None)
    await _drive(6)

    root_layer = adapter._layers[ROOT_LAYER_IDENTIFIER]
    assert SAVE_AS_PATH in root_layer.sublayer_identifiers, (
        "root should reference the saved file after Save-As"
    )
    assert anon_identifier not in root_layer.sublayer_identifiers, (
        "root should no longer reference the anonymous layer"
    )
    assert app.undo_manager.can_undo(), (
        "SaveLayerAsCommand must land on the undo stack"
    )
    # The top-of-stack should be our SaveLayerAsCommand.
    top = app.undo_manager._undo_stack[-1]
    assert isinstance(top, SaveLayerAsCommand), (
        f"expected SaveLayerAsCommand on top, got {type(top).__name__}"
    )
    print(
        "Shot 3 — Save confirmed; parent reference swapped from "
        f"{anon_identifier!r} to {SAVE_AS_PATH!r}; undo stack carries "
        "the SaveLayerAsCommand"
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    # --- Shot 4 — Undo restores the parent reference ---
    app.undo_manager.undo()
    _invalidate_all(model)
    model._item_changed(None)
    await _drive(6)

    assert anon_identifier in root_layer.sublayer_identifiers, (
        "undo must restore the anonymous parent reference"
    )
    assert SAVE_AS_PATH in adapter._layers, (
        "file on disk must survive the undo (M5)"
    )
    print(
        "Shot 4 — Undo restored the anonymous parent reference; the "
        "file on disk survived (M5 — undo does not delete files)"
    )
    uitesting.capture_screenshot(OUT_4)
    print(f"Saved: {OUT_4}")

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 36 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

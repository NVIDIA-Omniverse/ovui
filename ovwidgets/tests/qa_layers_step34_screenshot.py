# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 34 — per-row save via command.

Column 2's floppy now routes the click through
:class:`~ovwidgets.layers.commands.SaveLayerCommand` on the owning
:class:`~ovwidgets.app.application.Application`'s :class:`UndoManager`
rather than calling :meth:`LayerStackAdapter.save_layer` directly.
The visible state machine is unchanged — the dot appears on a dirty +
saveable row, disappears after save — but the command path is the
Step-34 deliverable.

Three shots:

1. **Shot 1** — ``/tmp/ovgear_layers_step34_1.png``: two dirty +
   saveable rows (amber dots on ``./child_a.usda`` and
   ``./child_b.usda``). ``./clean.usda`` is clean, ``./anon`` is
   anonymous (no dot — Step 36 will route its click to save-as), and
   the session layer is anonymous too.
2. **Shot 2** — ``/tmp/ovgear_layers_step34_2.png``: after a save
   click on ``./child_a.usda``. The command ran through
   ``UndoManager.push``; the dot cleared on that row, but
   ``./child_b.usda`` stays dirty.
3. **Shot 3** — ``/tmp/ovgear_layers_step34_3.png``: after a save
   click on ``./child_b.usda`` as well. Every concrete layer is now
   clean and no dots remain; the anonymous rows are untouched
   because the value-model guard short-circuits their click.
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
from ovwidgets.layers import LayerDelegate, LayerModel, LayerWindow, SaveValueModel
from ovwidgets.layers.commands import SaveLayerCommand

OUT_1 = "/tmp/ovgear_layers_step34_1.png"
OUT_2 = "/tmp/ovgear_layers_step34_2.png"
OUT_3 = "/tmp/ovgear_layers_step34_3.png"


class _StubApp:
    """Minimal :class:`Application` surface for the Layers window.

    The Step-34 click path reads ``undo_manager`` + ``selection_bus``;
    the window's :meth:`LayerModel._on_layer_event` path only needs
    ``call_later`` if batched flushing is desired. We omit the latter
    so events flush inline (fine for the screenshot harness).
    """

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
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./clean.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./anon")
    adapter._layers["./child_a.usda"].dirty = True
    adapter._layers["./child_b.usda"].dirty = True
    adapter._layers["./anon"].anonymous = True
    adapter._layers["./anon"].dirty = True
    return adapter


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

    for item_list in model._sublayers_cache.values():
        for item in item_list:
            vm = model.get_item_value_model(item, 2)
            if vm is not None:
                assert isinstance(vm, SaveValueModel), (
                    f"expected SaveValueModel for col 2, "
                    f"got {type(vm).__name__}"
                )
    model._item_changed(None)

    # Track commands the window pushes so the log output proves the
    # click actually routed through UndoManager (Step-34's deliverable)
    # rather than reverting to Step-19's direct-adapter call.
    pushed: list = []
    original_push = app.undo_manager.push

    def _spy(cmd):
        pushed.append(cmd)
        return original_push(cmd)

    app.undo_manager.push = _spy

    _invalidate_all(model)
    await _drive(6)
    print(
        "Shot 1 — two dirty rows (./child_a.usda, ./child_b.usda) show "
        "amber save dots; anon / clean rows have none"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Click ./child_a.usda's save dot — drives the Step-34 path:
    # SaveValueModel.set_value → LayerModel._request_save → push a
    # SaveLayerCommand on the UndoManager → command's do_impl calls
    # adapter.save_layer, which clears the dirty bit and fires
    # DIRTY_STATE_CHANGED. The cached SaveValueModel re-reads False
    # and the dot disappears from the row.
    child_a = next(iter(model._sublayers_cache["./child_a.usda"]))
    vm_a = model.get_item_value_model(child_a, 2)
    vm_a.set_value(True)
    model._item_changed(None)
    await _drive(6)
    print(
        f"Shot 2 — clicked save on ./child_a.usda; pushed {len(pushed)} "
        f"SaveLayerCommand(s); ./child_b.usda still dirty"
    )
    assert len(pushed) == 1, f"expected 1 pushed command, got {len(pushed)}"
    assert isinstance(pushed[-1], SaveLayerCommand)
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Save the second dirty row too — proves independent rows push
    # independent commands and both paths clear cleanly.
    child_b = next(iter(model._sublayers_cache["./child_b.usda"]))
    vm_b = model.get_item_value_model(child_b, 2)
    vm_b.set_value(True)
    model._item_changed(None)
    await _drive(6)
    print(
        f"Shot 3 — clicked save on ./child_b.usda; total pushed: "
        f"{len(pushed)}; all concrete rows clean"
    )
    assert len(pushed) == 2, f"expected 2 pushed commands, got {len(pushed)}"
    assert all(isinstance(c, SaveLayerCommand) for c in pushed)
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 34 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

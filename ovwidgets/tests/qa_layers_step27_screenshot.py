# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 27 — missing / read-only /
anonymous visual treatments.

Step 27 polishes three less-common layer states so a quick scan of the
Layers window surfaces them without the user reading every label:

- **Missing** — the layer file could not be resolved. Row carries the
  Step-18 red ``Layers.NameLabel::missing`` label *and* the Step-27
  red ``Layers.MissingBadge`` "X" glyph between the leading icon and
  the label.
- **Read-only on disk** — the file exists but is not writable by the
  current user. Column 6 paints a non-interactive
  ``Layers.LockIcon::readonly_overlay`` Rectangle behind the clickable
  padlock. The user-driven lock toggle stays clickable on top; the
  backdrop reads as "this file is not writable regardless of the
  lock bit".
- **Anonymous** — in-memory only, no backing file. The ``[anon]``
  bracket suffix lands on the label and the ``anonymous`` color role
  paints the name in the softened ``cl.text_secondary`` tint so the
  row reads as "not yet committed" without a dedicated italic font.

Two shots cover the before / after contract. The seed stack is
deliberately multi-state so one screenshot surfaces every Step-27 cue
at once:

1. **Shot 1** — ``/tmp/ovgear_layers_step27_1.png``: default state.
   Session row shows ``session [anon]`` in soft grey. ``./missing.usda``
   shows the red badge + red label. ``./readonly.usda`` shows the
   dim read-only backdrop in column 6 behind the unlocked padlock.
   ``./normal.usda`` is a control row with nothing special — proof
   the new tints are row-scoped rather than leaking globally.
2. **Shot 2** — ``/tmp/ovgear_layers_step27_2.png``: after the user
   locks ``./readonly.usda``. The read-only backdrop persists (file
   permission is orthogonal to the lock bit) *and* the padlock
   primitive flips to the bright ``::locked`` state. Proves the
   backdrop and the interactive glyph compose correctly: a doubly-
   guarded row reads as "backdrop + bright lock on top", not one
   single blurry blob.
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
    LockValueModel,
)

OUT_1 = "/tmp/ovgear_layers_step27_1.png"
OUT_2 = "/tmp/ovgear_layers_step27_2.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    """Seed a stack that exercises every Step-27 visual cue at once.

    Tree shape (rendered top → bottom after the session layer)::

        session              [anon]              [soft grey label]
        root                 (Authoring Layer)   [green row]
          ├── ./normal.usda                      [control — nothing special]
          ├── ./missing.usda   (Missing)         [red badge + red label]
          └── ./readonly.usda  (Read Only)       [readonly backdrop in col 6]
    """
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./normal.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./missing.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./readonly.usda")
    # Direct record mutation — ``set_missing`` / ``set_read_only`` would
    # fire events before the window has built the tree; harmless but
    # the direct mutation keeps the seed path stateless at construction
    # time and matches the Step-21 QA convention.
    adapter._layers["./missing.usda"].missing = True
    adapter._layers["./readonly.usda"].read_only = True
    return adapter


def _invalidate_all(model: LayerModel) -> None:
    """Drop every cached flag so the next render picks up mutated state."""
    for clone_list in model._sublayers_cache.values():
        for clone in clone_list:
            clone.invalidate_flags()


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

    # Materialise every row's column models so the delegate has
    # something to paint on the first visible frame.
    for item_list in model._sublayers_cache.values():
        for item in item_list:
            for col in range(LayerModel.NUM_COLUMNS):
                model.get_item_value_model(item, col)
    model._item_changed(None)

    _invalidate_all(model)
    await _drive(6)
    print(
        "Shot 1 — baseline. Session reads 'session [anon]' in soft grey; "
        "./missing.usda shows the red X badge + red label; "
        "./readonly.usda shows the dim read-only backdrop behind the "
        "unlocked padlock in column 6. ./normal.usda is the control."
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — lock ./readonly.usda. Read-only backdrop persists (file
    # permission is orthogonal to the lock bit); the padlock primitive
    # flips to the bright ``::locked`` state on top. A doubly-guarded
    # row reads as "dim backdrop + bright lock on top", proving the
    # overlay and interactive glyph compose correctly.
    readonly_item = None
    for clone in model._sublayers_cache.get("./readonly.usda", ()):
        readonly_item = clone
        break
    if readonly_item is None:
        raise RuntimeError("./readonly.usda row not in _sublayers_cache")
    ro_vm = model.get_item_value_model(readonly_item, LayerDelegate.COL_LOCK)
    assert isinstance(ro_vm, LockValueModel)
    ro_vm.set_value(True)
    model._item_changed(None)
    await _drive(6)
    print(
        "Shot 2 — after locking ./readonly.usda. The read-only backdrop "
        "stays painted (file permission is independent from the lock "
        "bit) and the padlock primitive now shows the bright shackle + "
        "body on top. Doubly-guarded rows read as two distinct cues."
    )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 27 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

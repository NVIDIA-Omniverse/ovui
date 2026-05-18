# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 48 — PrimSpecItem tree integration.

Step 48 lights up prim-spec children under each :class:`LayerItem` in
the Layers tree: when ``LayerSettings.show_layer_contents`` is
enabled, :meth:`LayerModel.get_item_children` emits :class:`PrimSpecItem`
rows after the sublayer rows. Prim specs load lazily on first expand
and are rendered with the specifier tag (``def`` / ``over`` /
``class``) plus the prim name and USD type.

Shots:

1. **Shot 1** — ``/tmp/ovgear_layers_step48_1.png``: tree with the
   setting off (baseline). Only sublayer rows visible.
2. **Shot 2** — ``/tmp/ovgear_layers_step48_2.png``: setting toggled
   on; the root layer row shows chevrons and the top-level prim
   specs (``/World``, ``/Overrides``) appear as children.
3. **Shot 3** — ``/tmp/ovgear_layers_step48_3.png``: expand
   ``/World`` to reveal nested prim specs (``/World/Cube``,
   ``/World/Sphere``).
4. **Shot 4** — ``/tmp/ovgear_layers_step48_4.png``: setting toggled
   off again — prim specs disappear without tearing the tree down.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting
from ovui_data_adapters.common import PrimSpecifier

from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.common.undo import UndoManager
from ovwidgets.layers import LayerModel, LayerWindow, PrimSpecItem

OUT_1 = "/tmp/ovgear_layers_step48_1.png"
OUT_2 = "/tmp/ovgear_layers_step48_2.png"
OUT_3 = "/tmp/ovgear_layers_step48_3.png"
OUT_4 = "/tmp/ovgear_layers_step48_4.png"


class _StubApp:
    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./environment.usda")
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./characters.usda")
    # Seed prim specs on the root layer.
    adapter.set_prim_spec_descriptor(
        ROOT_LAYER_IDENTIFIER, "/World", type_name="Xform"
    )
    adapter.set_prim_spec_descriptor(
        ROOT_LAYER_IDENTIFIER,
        "/World/Cube",
        type_name="Cube",
        has_reference=True,
    )
    adapter.set_prim_spec_descriptor(
        ROOT_LAYER_IDENTIFIER,
        "/World/Sphere",
        type_name="Sphere",
        specifier=PrimSpecifier.OVER,
        has_payload=True,
    )
    adapter.set_prim_spec_descriptor(
        ROOT_LAYER_IDENTIFIER,
        "/Overrides",
        specifier=PrimSpecifier.CLASS,
    )
    return adapter


def _describe_children(model: LayerModel, item) -> str:
    children = model.get_item_children(item)
    parts = []
    for child in children:
        if isinstance(child, PrimSpecItem):
            parts.append(
                f"spec({child.specifier.name}:{child.path}"
                f":{child.type_name or '-'})"
            )
        else:
            parts.append(f"layer({child.identifier!r})")
    return ", ".join(parts) if parts else "<no children>"


async def _main() -> None:
    adapter = _make_adapter()
    app = _StubApp()
    layer_window = LayerWindow(services=app, adapter=adapter)
    if layer_window.window is not None:
        layer_window.window.undock()
        layer_window.window.position_x = 40
        layer_window.window.position_y = 40
        layer_window.window.width = 620
        layer_window.window.height = 560
        layer_window.window.focus()

    await _drive(15)

    model = layer_window._model
    if not isinstance(model, LayerModel):
        raise RuntimeError(
            f"Expected LayerModel, got {type(model).__name__}"
        )

    root_item = model.root_item
    if root_item is None:
        raise RuntimeError("Root layer row not found")

    tree_view = layer_window._tree_view
    if tree_view is not None:
        tree_view.set_expanded(root_item, True, False)

    # --- Shot 1 — setting off (baseline) ---
    model._settings.show_layer_contents = False
    model._item_changed(None)
    await _drive(6)
    print(
        f"Shot 1 — baseline (show_layer_contents=False). "
        f"root children: {_describe_children(model, root_item)}"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # --- Shot 2 — setting on: top-level prim specs visible ---
    model._settings.show_layer_contents = True
    model._item_changed(None)
    if tree_view is not None:
        tree_view.set_expanded(root_item, True, False)
    await _drive(8)
    print(
        f"Shot 2 — setting on. "
        f"root children: {_describe_children(model, root_item)}"
    )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # --- Shot 3 — expand /World to reveal nested prim specs ---
    world_spec = next(
        (
            c
            for c in model.get_item_children(root_item)
            if isinstance(c, PrimSpecItem) and c.path == "/World"
        ),
        None,
    )
    if world_spec is None:
        raise RuntimeError("/World prim spec not present under root layer")
    if tree_view is not None:
        tree_view.set_expanded(world_spec, True, False)
    await _drive(8)
    print(
        f"Shot 3 — /World expanded. "
        f"world children: {_describe_children(model, world_spec)}"
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    # --- Shot 4 — setting off again (prim specs hidden) ---
    model._settings.show_layer_contents = False
    model._item_changed(None)
    await _drive(8)
    print(
        f"Shot 4 — setting toggled off. "
        f"root children: {_describe_children(model, root_item)}"
    )
    uitesting.capture_screenshot(OUT_4)
    print(f"Saved: {OUT_4}")

    print()
    print("Step 48 behaviour summary:")
    print(
        "  - PrimSpecItem rows render as children of their LayerItem "
        "when LayerSettings.show_layer_contents is True."
    )
    print(
        "  - Column 0 shows the specifier tag (def/over/class), the "
        "prim name, and the USD type in parentheses. Columns 1-6 are "
        "intentionally blank for prim-spec rows."
    )
    print(
        "  - Children load lazily on first expand; toggling the "
        "setting off hides them without tearing the tree down."
    )

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 48 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

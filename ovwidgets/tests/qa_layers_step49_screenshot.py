# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-app screenshots for LAYERS-PLAN Step 49 — prim-spec specifier icons.

Step 49 graduates the Step-48 text tag into a provider-backed PNG
glyph per :class:`PrimSpecifier` (DEF / OVER / CLASS) and overlays
reference / payload / instance badges in the corners of the icon.

Shots:

1. **Shot 1** — ``/tmp/ovgear_layers_step49_1.png``: tree with
   ``show_layer_contents=True`` and the root layer expanded so
   ``/World`` (DEF + Xform), ``/Overrides`` (CLASS), and any other
   top-level specs render side by side. This captures DEF vs CLASS.
2. **Shot 2** — ``/tmp/ovgear_layers_step49_2.png``: ``/World``
   expanded, revealing ``/World/Cube`` (DEF + reference badge) and
   ``/World/Sphere`` (OVER + payload badge). Captures OVER + badges.
3. **Shot 3** — ``/tmp/ovgear_layers_step49_3.png``: row with the
   instance badge — ``/Instances/A`` (DEF, is_instanceable=True,
   has_reference=True). Confirms instance + reference render
   together in separate corners.
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

OUT_1 = "/tmp/ovgear_layers_step49_1.png"
OUT_2 = "/tmp/ovgear_layers_step49_2.png"
OUT_3 = "/tmp/ovgear_layers_step49_3.png"


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
    # Top-level prim specs covering DEF + CLASS kinds.
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
    adapter.set_prim_spec_descriptor(
        ROOT_LAYER_IDENTIFIER,
        "/Instances",
        type_name="Xform",
    )
    adapter.set_prim_spec_descriptor(
        ROOT_LAYER_IDENTIFIER,
        "/Instances/A",
        type_name="Xform",
        has_reference=True,
        is_instanceable=True,
    )
    return adapter


def _describe_children(model: LayerModel, item) -> str:
    children = model.get_item_children(item)
    parts = []
    for child in children:
        if isinstance(child, PrimSpecItem):
            d = child.descriptor
            flags = []
            if d.has_reference:
                flags.append("ref")
            if d.has_payload:
                flags.append("pl")
            if d.is_instanceable:
                flags.append("inst")
            flag_str = f" [{'/'.join(flags)}]" if flags else ""
            parts.append(
                f"spec({child.specifier.name}:{child.path}"
                f":{child.type_name or '-'}{flag_str})"
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
    model._settings.show_layer_contents = True
    model._item_changed(None)
    if tree_view is not None:
        tree_view.set_expanded(root_item, True, False)

    await _drive(10)

    # --- Shot 1 — top-level specs (DEF + CLASS) ---
    print(
        f"Shot 1 — root expanded. "
        f"root children: {_describe_children(model, root_item)}"
    )
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # --- Shot 2 — /World expanded: DEF+ref, OVER+payload ---
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
        f"Shot 2 — /World expanded. "
        f"world children: {_describe_children(model, world_spec)}"
    )
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # --- Shot 3 — /Instances expanded: instance badge ---
    instances_spec = next(
        (
            c
            for c in model.get_item_children(root_item)
            if isinstance(c, PrimSpecItem) and c.path == "/Instances"
        ),
        None,
    )
    if instances_spec is None:
        raise RuntimeError("/Instances prim spec not present under root layer")
    if tree_view is not None:
        tree_view.set_expanded(instances_spec, True, False)
    await _drive(8)
    print(
        f"Shot 3 — /Instances expanded. "
        f"children: {_describe_children(model, instances_spec)}"
    )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    print()
    print("Step 49 behaviour summary:")
    print(
        "  - Each prim-spec row draws a provider-backed PNG glyph "
        "per PrimSpecifier (DEF=solid cube, OVER=wireframe cube, "
        "CLASS=dashed 'C' card)."
    )
    print(
        "  - Composition badges (reference / payload) overlay the "
        "bottom-right corner; payload wins when both flags are set "
        "(LAYERS-PLAN Step 49 ordering)."
    )
    print(
        "  - Instance badge overlays the top-right corner whenever "
        "the descriptor is marked instanceable (orthogonal to the "
        "composition badge — both can coexist)."
    )

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 49 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

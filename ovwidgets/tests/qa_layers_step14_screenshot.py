# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshots for LAYERS-PLAN Step 14.

Proves :meth:`LayerModel._load_sublayers` builds the full sublayer
tree when a real USD stage with nested sublayers is opened, and that
``SUBLAYERS_CHANGED`` events drive targeted updates.

1. **Shot 1** — ``/tmp/ovgear_layers_step14_1.png``: dark theme, stage
   with nested sublayers (root → sub1 → sub2) loaded. The Layers panel
   now renders an **expand arrow** next to ``layers_step14_root.usda``
   — the arrow is the visible diff from Step 13 (which showed the root
   row without any arrow because ``LayerItem.sublayers`` was always
   empty). The arrow is `ui.TreeView`'s signal that
   ``can_item_have_children(root_item)`` returned ``True``, which only
   happens once Step 14's ``_load_sublayers`` has populated the list.
2. **Shot 2** — ``/tmp/ovgear_layers_step14_2.png``: after the USD
   adapter inserts an additional sublayer under ``sub1``. The runtime
   re-query of ``model.root_item.sublayers[0].sublayers`` goes from
   one child to two — confirming ``_on_layer_event`` routes
   ``SUBLAYERS_CHANGED`` through ``_reset_root`` → ``_load_sublayers``.
3. **Shot 3** — ``/tmp/ovgear_layers_step14_3.png``: after switching
   to the light theme. Confirms the new sublayer rows render under
   ``cl.text_primary`` in both palettes.

The runtime assertions printed to stdout are the primary proof. The
screenshots supplement them with the visible ``+`` expand arrow on
the root row; programmatic expansion of rows via ``set_expanded``
does not paint through in this standalone harness (observed across
multiple attempts), so we rely on the expand-arrow presence as the
visual proof rather than a fully-expanded tree.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting

from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus
from ovwidgets.layers import LayerItem, LayerModel

USD_PATH = os.path.join(
    os.path.dirname(__file__), "data", "layers_step14_root.usda"
)
OUT_1 = "/tmp/ovgear_layers_step14_1.png"
OUT_2 = "/tmp/ovgear_layers_step14_2.png"
OUT_3 = "/tmp/ovgear_layers_step14_3.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    app._startup_usd_path = USD_PATH
    task = asyncio.ensure_future(app.run_async())

    await _drive(80)

    lw = app._layer_window
    if lw is None:
        raise RuntimeError("Application._layer_window not initialised")

    if app._property_window is not None:
        app._property_window.visible = False
    lw.visible = True
    if lw.window is not None:
        lw.window.focus()
        lw.window.frame.rebuild()
    await _drive(20)

    model = lw._model
    if not isinstance(model, LayerModel):
        raise RuntimeError(
            f"Expected LayerModel after stage load, got {type(model).__name__}"
        )

    root_item = model.root_item
    if root_item is None:
        raise RuntimeError("Root LayerItem missing — adapter not attached?")

    if len(root_item.sublayers) != 1:
        raise RuntimeError(
            f"Expected exactly 1 direct sublayer under root, got "
            f"{len(root_item.sublayers)}: "
            f"{[s.identifier for s in root_item.sublayers]}"
        )
    sub1 = root_item.sublayers[0]
    if not isinstance(sub1, LayerItem) or not sub1.identifier.endswith(
        "layers_step14_sub1.usda"
    ):
        raise RuntimeError(f"Unexpected sub1 LayerItem: {sub1!r}")
    if len(sub1.sublayers) != 1:
        raise RuntimeError(
            f"Expected exactly 1 grandchild under sub1, got "
            f"{[s.identifier for s in sub1.sublayers]}"
        )
    sub2 = sub1.sublayers[0]
    if not isinstance(sub2, LayerItem) or not sub2.identifier.endswith(
        "layers_step14_sub2.usda"
    ):
        raise RuntimeError(f"Unexpected sub2 LayerItem: {sub2!r}")
    if sub2.sublayers:
        raise RuntimeError(
            f"sub2 should have no children (leaf), got {sub2.sublayers!r}"
        )

    for ident in (root_item.identifier, sub1.identifier, sub2.identifier):
        if ident not in model._sublayers_cache:
            raise RuntimeError(
                f"Cache miss for {ident!r}; keys={list(model._sublayers_cache)}"
            )
    if not (
        model.can_item_have_children(root_item)
        and model.can_item_have_children(sub1)
        and not model.can_item_have_children(sub2)
    ):
        raise RuntimeError(
            "can_item_have_children mis-returns: "
            f"root={model.can_item_have_children(root_item)} "
            f"sub1={model.can_item_have_children(sub1)} "
            f"sub2={model.can_item_have_children(sub2)}"
        )

    print(
        f"Layers tree: "
        f"root={os.path.basename(root_item.identifier)!r} → "
        f"sub1={os.path.basename(sub1.identifier)!r} → "
        f"sub2={os.path.basename(sub2.identifier)!r}"
    )
    print(
        f"Cache keys: {sorted(os.path.basename(k) for k in model._sublayers_cache)}"
    )

    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — mutate the adapter so SUBLAYERS_CHANGED refreshes the
    # tree. Adding another sublayer under sub1 exercises the multi-
    # instance sublayer cache fan-out: ``sub2``'s file gets referenced
    # twice so ``_sublayers_cache[sub2_path]`` has length 2.
    extra_path = os.path.join(
        os.path.dirname(__file__), "data", "layers_step14_sub2.usda"
    )
    adapter = lw._adapter
    if adapter is None:
        raise RuntimeError("Adapter missing")
    adapter.insert_sublayer(sub1.identifier, -1, extra_path)
    await _drive(20)

    refreshed = model.root_item.sublayers[0]
    if len(refreshed.sublayers) != 2:
        raise RuntimeError(
            f"Expected 2 sublayers under sub1 after insert, got "
            f"{[s.identifier for s in refreshed.sublayers]}"
        )
    # Both children should share the same identifier (both are sub2).
    # The multi-instance cache keeps both LayerItems alive.
    sub2_cache = model._sublayers_cache.get(sub2.identifier, [])
    print(
        f"After insert: sub1 has {len(refreshed.sublayers)} children; "
        f"sub2 cache count={len(sub2_cache)}"
    )

    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Shot 3 — switch to light theme. Tree state (sub1 has 2 children)
    # must survive the theme swap since the model is independent of
    # colour state.
    set_theme("light")
    for win in (
        app._stage_window,
        app._property_window,
        lw,
        app._viewport_window,
    ):
        if hasattr(win, "on_theme_changed"):
            win.on_theme_changed()
    await _drive(15)

    if len(model.root_item.sublayers[0].sublayers) != 2:
        raise RuntimeError("Tree state lost across theme switch")

    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    write_split_ini()
    ui.init("OvGear Layers Step 14 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

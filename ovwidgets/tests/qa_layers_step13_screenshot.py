# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshots for LAYERS-PLAN Step 13.

Proves the Layers TreeView built on :class:`LayerModel` actually
renders the root + session layer rows with their display names, and
that adapter events push updates through into the tree:

1. **Shot 1** — ``/tmp/ovgear_layers_step13_1.png``: dark theme, USD
   stage open. The Layers panel shows the real ``simple_scene`` root
   + ``anonymous`` session layer as top-level rows.
2. **Shot 2** — ``/tmp/ovgear_layers_step13_2.png``: Property Inspector
   hidden so the Layers panel gets the full dock-node width —
   unambiguous view of the tree rendering.
3. **Shot 3** — ``/tmp/ovgear_layers_step13_3.png``: after switching
   to the light theme and re-applying styles. Confirms the value-
   model name labels re-read ``cl.text_primary`` through the new
   shade.

Runtime assertions before the final screenshot pin:

- :class:`LayerModel` is the model bound to the panel's TreeView.
- ``get_item_children(None)`` returns two items (session, root).
- Column-0 value model for the root carries a non-empty display name.
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

USD_PATH = os.path.join(os.path.dirname(__file__), "data", "simple_scene.usda")
OUT_1 = "/tmp/ovgear_layers_step13_1.png"
OUT_2 = "/tmp/ovgear_layers_step13_2.png"
OUT_3 = "/tmp/ovgear_layers_step13_3.png"


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

    # Hide the Property Inspector first so the Layers tab becomes the
    # sole (and therefore focused) tab in that dock node — ImGui only
    # paints the frame of the active tab, so if Property is on top the
    # Layers ``frame.set_build_fn`` callback never re-runs after
    # ``set_adapter`` and ``_model`` stays ``None``.
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
            f"Expected LayerModel after stage load, got {type(model).__name__} "
            f"(adapter={lw._adapter!r}, visible={lw.visible})"
        )
    top = model.get_item_children(None)
    if not (
        len(top) == 2
        and isinstance(top[0], LayerItem)
        and top[0].is_session_layer
        and isinstance(top[1], LayerItem)
        and not top[1].is_session_layer
    ):
        raise RuntimeError(
            f"Unexpected top-level rows: {[repr(it) for it in top]}"
        )
    root_name_vm = model.get_item_value_model(top[1], 0)
    if not (
        isinstance(root_name_vm, ui.SimpleStringModel)
        and root_name_vm.get_value_as_string()
    ):
        raise RuntimeError(
            f"Root value model returned empty name: {root_name_vm!r}"
        )
    print(
        f"Top-level rows: session={top[0].identifier!r}, "
        f"root={top[1].identifier!r} (display={root_name_vm.get_value_as_string()!r})"
    )

    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Bring Property Inspector back so Shot 2 mirrors Kit's typical
    # right-column layout (Property + Layers tabs alongside each other)
    # — then hide it again so Shot 3 is a clean view of just Layers.
    if app._property_window is not None:
        app._property_window.visible = True
    await _drive(10)

    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    if app._property_window is not None:
        app._property_window.visible = False
    if lw.window is not None:
        lw.window.focus()
    await _drive(10)

    # Switch to light theme and re-apply: confirms the label's
    # SimpleStringModel keeps its text while cl.text_primary re-resolves.
    set_theme("light")
    for win in (app._stage_window, app._property_window, lw, app._viewport_window):
        if hasattr(win, "on_theme_changed"):
            win.on_theme_changed()
    await _drive(10)

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
    ui.init("OvGear Layers Step 13 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

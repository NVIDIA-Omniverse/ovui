# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshots for LAYERS-PLAN Step 9.

Proves Step 9 end-to-end by capturing three states with a real USD stage
loaded, so ``UsdLayerStackAdapter`` is constructed, attached, and handed
to the LayerWindow:

1. **Shot 1** — ``/tmp/ovgear_layers_step9_1.png``: default startup with
   ``simple_scene.usda`` loaded. Stage Browser / Viewport / Property
   Inspector populated; Layers tab docked next to Property (shares
   ``dock_id``). The runtime assertion also confirms the app's
   ``_layer_adapter`` is a ``UsdLayerStackAdapter`` bound to the stage.
2. **Shot 2** — ``/tmp/ovgear_layers_step9_2.png``: Property temporarily
   hidden so the Layers placeholder body is the visible window in its
   dock node. Proves ``set_adapter`` + ``frame.rebuild`` path does not
   break the placeholder render.
3. **Shot 3** — ``/tmp/ovgear_layers_step9_3.png``: theme toggled
   dark → light. The LayerWindow frame background re-applies to the
   light-theme shade via ``Application._on_theme_changed``.
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

USD_PATH = os.path.join(os.path.dirname(__file__), "data", "simple_scene.usda")
OUT_1 = "/tmp/ovgear_layers_step9_1.png"
OUT_2 = "/tmp/ovgear_layers_step9_2.png"
OUT_3 = "/tmp/ovgear_layers_step9_3.png"


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

    # 80 frames covers ovrtx first-frame warm-up on this VM.
    await _drive(80)

    lw = app._layer_window
    if lw is None:
        raise RuntimeError("Application._layer_window not initialised")
    from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter
    if not isinstance(app._layer_adapter, UsdLayerStackAdapter):
        raise RuntimeError(
            f"_layer_adapter is not UsdLayerStackAdapter: got {type(app._layer_adapter)!r}"
        )
    if lw._adapter is not app._layer_adapter:
        raise RuntimeError(
            "LayerWindow._adapter was not wired to Application._layer_adapter"
        )
    if app._layer_adapter._destroyed:
        raise RuntimeError("UsdLayerStackAdapter is still flagged _destroyed after attach_stage")

    layers_handle = ui.Workspace.get_window("Layers")
    prop_handle = ui.Workspace.get_window("Property Inspector")
    if layers_handle is None or prop_handle is None:
        raise RuntimeError("Layers or Property Inspector missing from workspace")
    if layers_handle.dock_id != prop_handle.dock_id:
        raise RuntimeError(
            f"Layers ({layers_handle.dock_id!r}) not tabbed with Property "
            f"({prop_handle.dock_id!r})"
        )
    print(
        f"Layers adapter={type(app._layer_adapter).__name__} "
        f"destroyed={app._layer_adapter._destroyed} "
        f"dock_id={layers_handle.dock_id!r}"
    )

    # Shot 1 — default with stage loaded.
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — hide Property so Layers is the visible tab body.
    app._property_window.visible = False
    await _drive(15)
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Shot 3 — toggle theme to light. Property still hidden so the
    # Layers tab keeps the foreground; the light-theme frame background
    # must paint correctly.
    app._property_window.visible = True
    await _drive(5)
    app.settings.set("ui.theme", "light")
    await _drive(15)
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
    ui.init("OvGear Layers Step 9 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

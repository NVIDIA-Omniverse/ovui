# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshots for LAYERS-PLAN Step 11.

Proves ``LAYERS_STYLES`` + the new ``cl.layers_*`` palette tokens
actually reach the live Layers window and re-resolve on theme switch:

1. **Shot 1** — ``/tmp/ovgear_layers_step11_1.png``: default (dark) start
   with the Layers panel docked next to Property and the placeholder
   label picking up ``cl.text_primary`` (dark).
2. **Shot 2** — ``/tmp/ovgear_layers_step11_2.png``: after switching to
   the light theme via ``set_theme("light")`` + re-apply. The Layers
   placeholder text flips to the light-variant ``cl.text_primary`` and
   the window chrome repaints through the re-resolved palette.
3. **Shot 3** — ``/tmp/ovgear_layers_step11_3.png``: back to dark, with
   Property Inspector hidden so the Layers panel is the only thing in
   its dock node — a clean, unambiguous view of the restyled panel.

Runtime assertions (before the final screenshot) pin that ``ui.style.default``
contains every required Step-11 selector, and that the resolved
``Layers.TreeView.Row:hovered`` background_color differs between dark
and light — that's the end-to-end theme-re-apply proof.
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
OUT_1 = "/tmp/ovgear_layers_step11_1.png"
OUT_2 = "/tmp/ovgear_layers_step11_2.png"
OUT_3 = "/tmp/ovgear_layers_step11_3.png"

REQUIRED_SELECTORS = [
    "Layers.TreeView",
    "Layers.TreeView.Row",
    "Layers.TreeView.Row:selected",
    "Layers.TreeView.Row:hovered",
    "Layers.NameLabel",
    "Layers.NameLabel::missing",
    "Layers.NameLabel::edit_target",
    "Layers.IconButton",
    "Layers.IconButton::muted",
]


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

    # Runtime assertion: every Step-11 selector is in ui.style.default.
    missing = [k for k in REQUIRED_SELECTORS if k not in ui.style.default]
    if missing:
        raise RuntimeError(
            f"ui.style.default missing Step-11 selectors: {missing}"
        )
    dark_hover = ui.style.default["Layers.TreeView.Row:hovered"][
        "background_color"
    ]
    print(
        f"All {len(REQUIRED_SELECTORS)} Step-11 selectors present in "
        f"ui.style.default; Layers.TreeView.Row:hovered (dark) = {hex(dark_hover)}"
    )

    # Shot 1 — dark theme, Layers panel docked next to Property.
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Switch to light theme. set_theme() triggers apply_global_styles()
    # internally — the LAYERS_STYLES merge path must re-resolve every
    # cl.* reference against the light shade table.
    set_theme("light")
    # on_theme_changed() fires per-window background re-paint.
    for win in (app._stage_window, app._property_window, lw, app._viewport_window):
        if hasattr(win, "on_theme_changed"):
            win.on_theme_changed()
    await _drive(10)

    light_hover = ui.style.default["Layers.TreeView.Row:hovered"][
        "background_color"
    ]
    if dark_hover == light_hover:
        raise RuntimeError(
            "Theme re-apply broken: Layers.TreeView.Row:hovered did not "
            f"change across dark→light (both {hex(dark_hover)})"
        )
    print(
        f"Theme switch re-resolved Layers.TreeView.Row:hovered: "
        f"dark={hex(dark_hover)} light={hex(light_hover)}"
    )

    # Shot 2 — light theme, full window view.
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Switch back to dark and hide Property so Layers owns its dock node.
    set_theme("dark")
    for win in (app._stage_window, app._property_window, lw, app._viewport_window):
        if hasattr(win, "on_theme_changed"):
            win.on_theme_changed()
    app._property_window.visible = False
    await _drive(10)

    # Shot 3 — Layers panel alone, dark theme restored.
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
    ui.init("OvGear Layers Step 11 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

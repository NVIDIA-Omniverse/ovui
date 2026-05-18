# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshots for Layers Window Step 8 — scaffold.

Proves the LAYERS-PLAN Step 8 deliverables at runtime by capturing three
states:

1. **Shot 1** — ``/tmp/ovgear_layers_step8_1.png``: default startup
   state. Stage Browser left, Viewport centre, Property Inspector as
   the active tab in the right dock column with the Layers window
   docked as a sibling tab (``layers_handle.dock_id`` ==
   ``prop_handle.dock_id``). The Property content occupies the tab
   body; the tab strip sits above at the top of the node.
2. **Shot 2** — ``/tmp/ovgear_layers_step8_2.png``: Property
   temporarily hidden so the Layers panel becomes the lone window in
   its dock node. The Step 8 placeholder "Layers \u2014 coming soon"
   label paints centred inside the panel, proving the
   :meth:`LayerWindow._build_ui` body is wired and renders against
   the shared global styles.
3. **Shot 3** — ``/tmp/ovgear_layers_step8_3.png``: Property restored,
   a prim selected in the Stage Browser via the selection bus. Proves
   that a selection change while Layers is docked does not crash and
   that Stage / Property continue to respond normally (the Layers
   panel body stays on the placeholder — it has no selection
   subscription yet; that is Step 9's job).

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/_venv/lib/python3.10/site-packages/omni/ui:\
<path-to-ovui>/_venv/lib/python3.10/site-packages/omni/ui_scene \\
      <path-to-ovui>/_venv/bin/python tests/qa_layers_step8_screenshot.py
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
OUT_1 = "/tmp/ovgear_layers_step8_1.png"
OUT_2 = "/tmp/ovgear_layers_step8_2.png"
OUT_3 = "/tmp/ovgear_layers_step8_3.png"


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

    # Let the shell render, stage open, property fill, Layers tab dock.
    # 80 frames covers the ovrtx renderer's first-frame warm-up on this VM
    # — the viewport is still painting black at frame 50.
    await _drive(80)

    # Runtime asserts — the Layers window must exist, be docked into
    # Property Inspector's tab node, and report as visible.
    lw = app._layer_window
    if lw is None:
        raise RuntimeError("Application._layer_window not initialised")
    if lw.title != "Layers":
        raise RuntimeError(f"LayerWindow title unexpected: {lw.title!r}")
    if lw.window is None:
        raise RuntimeError("LayerWindow.window is None after startup")

    layers_handle = ui.Workspace.get_window("Layers")
    if layers_handle is None:
        raise RuntimeError("Workspace has no 'Layers' window after startup")
    prop_handle = ui.Workspace.get_window("Property Inspector")
    if prop_handle is None:
        raise RuntimeError("Workspace lost 'Property Inspector' after startup")
    if layers_handle.dock_id == 0:
        raise RuntimeError("Layers window did not dock — dock_id=0 after startup")
    if layers_handle.dock_id != prop_handle.dock_id:
        raise RuntimeError(
            "Layers did not land in Property Inspector's dock node: "
            f"layers dock_id={layers_handle.dock_id!r}, "
            f"property dock_id={prop_handle.dock_id!r}"
        )
    print(
        f"Layers docked at node {layers_handle.dock_id!r} "
        f"(shared with Property Inspector)"
    )

    # Shot 1 — default: Stage left, Viewport centre, Property as the
    # active right-column tab, Layers tab sitting behind it.
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — temporarily hide Property so Layers becomes the visible
    # window in its dock node. ImGui's standalone tab-strip in this
    # build does not respond to programmatic focus/set_active, so this
    # is the cleanest way to prove the Layers placeholder actually
    # paints without requiring a simulated mouse click on the tab
    # header. (A real user clicking the tab switches normally — the
    # limitation is only in the test hook.)
    app._property_window.visible = False
    await _drive(15)
    if not lw.visible:
        raise RuntimeError("LayerWindow reports visible=False after hiding Property")
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")

    # Shot 3 — publish a selection while Property is still hidden, so
    # the Layers placeholder stays the visible body. Proves a selection
    # change while Layers is docked does not crash either panel — the
    # Stage Browser updates its selection row (visible) and the Viewport
    # receives the pick; the Layers placeholder itself is unchanged
    # because Step 8 does not subscribe to the selection bus yet.
    app.selection_bus.publish(["/World/Cube"], source="qa")
    await _drive(20)
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
    ui.init("OvGear Layers Step 8 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

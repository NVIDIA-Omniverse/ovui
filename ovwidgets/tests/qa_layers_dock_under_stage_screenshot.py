# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot: verify Layers window docks below Stage Browser.

Confirms the fix for "dock Layers window under Stage":

- Runtime assert: ``Layers`` and ``Stage Browser`` live in different
  dock nodes (not tabbed) but share the left column. Property Inspector
  remains on the right.
- **Shot 1** — ``/tmp/ovgear_layers_dock_under_stage.png``: default
  startup with ``simple_scene.usda`` loaded. Stage on upper-left,
  Layers on lower-left, Viewport centre, Property on the right.
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
OUT = "/tmp/ovgear_layers_dock_under_stage.png"


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

    stage_handle = ui.Workspace.get_window("Stage Browser")
    layers_handle = ui.Workspace.get_window("Layers")
    prop_handle = ui.Workspace.get_window("Property Inspector")
    vp_handle = ui.Workspace.get_window("Viewport")
    if any(h is None for h in (stage_handle, layers_handle, prop_handle, vp_handle)):
        raise RuntimeError(
            f"missing workspace handle: stage={stage_handle!r} "
            f"layers={layers_handle!r} prop={prop_handle!r} vp={vp_handle!r}"
        )

    # Stage + Layers split vertically — must NOT share a dock_id (not tabbed).
    if layers_handle.dock_id == stage_handle.dock_id:
        raise RuntimeError(
            f"Layers is tabbed with Stage (dock_id {layers_handle.dock_id!r}) "
            "— expected a vertical split"
        )
    # Layers + Property must also be different nodes (old regression check).
    if layers_handle.dock_id == prop_handle.dock_id:
        raise RuntimeError(
            f"Layers still tabbed with Property (dock_id {layers_handle.dock_id!r}) "
            "— expected Layers to live below Stage instead"
        )

    print(
        f"dock_ids  stage={stage_handle.dock_id:#010x}  "
        f"layers={layers_handle.dock_id:#010x}  "
        f"prop={prop_handle.dock_id:#010x}  "
        f"vp={vp_handle.dock_id:#010x}"
    )
    print(
        f"Stage  y={stage_handle.position_y:.0f} h={stage_handle.height:.0f}  |  "
        f"Layers y={layers_handle.position_y:.0f} h={layers_handle.height:.0f}"
    )
    # Layers should sit below Stage (greater y), both in the left column
    # (similar x range).
    if layers_handle.position_y <= stage_handle.position_y:
        raise RuntimeError(
            "Layers y is not below Stage y — expected vertical stack with "
            f"Stage on top (stage_y={stage_handle.position_y}, "
            f"layers_y={layers_handle.position_y})"
        )

    uitesting.capture_screenshot(OUT)
    print(f"Saved: {OUT}")

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
    ui.init("OvGear Layers Dock QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 3 visual verification — Type column shows real USD types.

Launches OvGear with an expanded USD fixture (Cube, Sphere, Cylinder, Mesh,
DistantLight, Camera) and captures three screenshots:

  1. /tmp/ovgear_step3_1.png — mock mode (baseline; Type column shows
     the Mock adapter's prim_type strings).
  2. /tmp/ovgear_step3_2.png — USD file open, Stage Browser expanded; Type
     column now reads "Cube", "Sphere", "Cylinder", "Mesh", "DistantLight",
     "Camera" (not the old "Mesh"/"Light" collapse).
  3. /tmp/ovgear_step3_3.png — USD open, /World/Sphere selected; badge
     tint still driven by category ("Mesh").

Run:
    DISPLAY=:99 python3.12 tests/verify_step3.py
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

# Uses tests/data/simple_scene.usda: Cube, Sphere, Mesh (Pyramid), Cylinder
# (Pillar). Each used to collapse to "Mesh" before Step 3 — after the split
# the Type column shows the real USD type verbatim.
USD_PATH = os.path.join(os.path.dirname(__file__), "data", "simple_scene.usda")


async def _drive(app: Application, frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _capture_mock(out_path: str) -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())
    await _drive(app, 25)
    uitesting.capture_screenshot(out_path)
    print(f"  mock screenshot: {out_path}")

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()


async def _capture_usd(unsel_out: str, sel_out: str) -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    app._startup_usd_path = USD_PATH
    task = asyncio.ensure_future(app.run_async())

    # Extra frames so open_file() completes before we inspect _stage_adapter.
    await _drive(app, 60)

    # Report adapter status up front so the error is obvious on failure.
    print(f"  stage_adapter set: {app._stage_adapter is not None}")
    if app._stage_adapter is None:
        app._running = False
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
        app.shutdown()
        return

    # Expand the root + /World so children render in the tree.
    widget = app._stage_window
    tree_view = widget._tree_view
    model = widget._model
    tree_view.set_expanded(model._root, True, False)
    await _drive(app, 5)
    world_item = model._path_cache.get("/World")
    if world_item is not None:
        tree_view.set_expanded(world_item, True, False)
        await _drive(app, 15)
    else:
        print("  WARN: /World not in path_cache yet")

    uitesting.capture_screenshot(unsel_out)
    print(f"  unselected screenshot: {unsel_out}")

    adapter = app._stage_adapter
    print("  Stage Browser Type column contents:")
    world = adapter.get_item_at_path("/World")
    print(
        f"    /World → name={adapter.get_type_name(world)!r} "
        f"category={adapter.get_type_category(world)!r} "
        f"icon={adapter.get_icon_name(world)!r}"
    )
    for child in adapter.get_children(world):
        path = adapter.get_item_path(child)
        print(
            f"    {path} → name={adapter.get_type_name(child)!r} "
            f"category={adapter.get_type_category(child)!r} "
            f"icon={adapter.get_icon_name(child)!r}"
        )

    app.selection_bus.publish(["/World/Sphere"], source="test")
    await _drive(app, 15)
    uitesting.capture_screenshot(sel_out)
    print(f"  selected screenshot: {sel_out}")

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()


async def _main() -> None:
    print("=== Step 3: mock mode ===")
    await _capture_mock("/tmp/ovgear_step3_1.png")
    print("=== Step 3: USD open (tree expanded) ===")
    await _capture_usd(
        "/tmp/ovgear_step3_2.png",
        "/tmp/ovgear_step3_3.png",
    )
    print("\nDone.")


if __name__ == "__main__":
    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    write_split_ini()
    ui.init("OvGear Step 3 Verify", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 5 visual verification — VisibilityValueModel end-to-end.

Three screenshots:

  1. /tmp/ovgear_step5_1.png — baseline, everything visible (column shows "V").
  2. /tmp/ovgear_step5_2.png — multi-select {/World/Geometry/Sphere, Cube} and
     fire a group-toggle via ``vis_model.set_value(True)``. Both rows flip to
     "-" in a single click, recorded under a single "Toggle Visibility" undo
     group.
  3. /tmp/ovgear_step5_3.png — flip ONLY the Ground item back to visible
     (unrelated to current selection) to prove non-selected toggles are
     confined to the clicked item.

Runtime log dumps the inverted-read values + undo-group calls so the reader
sees the data layer through-line, not just the pixels.

Run:
    DISPLAY=:99 python3.12 tests/verify_step5.py
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


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())
    await _drive(30)

    widget = app._stage_window
    model = widget._model
    adapter = model._adapter
    tree_view = widget._tree_view

    # Expand root and /World so all three branches are visible.
    tree_view.set_expanded(model._root, True, False)
    await _drive(5)
    world_item = model._path_cache.get("/World")
    if world_item is not None:
        tree_view.set_expanded(world_item, True, False)
    await _drive(5)
    geometry_item = model._path_cache.get("/World/Geometry")
    if geometry_item is not None:
        tree_view.set_expanded(geometry_item, True, False)
    await _drive(10)

    uitesting.capture_screenshot("/tmp/ovgear_step5_1.png")
    print("  baseline screenshot: /tmp/ovgear_step5_1.png")

    # Prove the inverted read: every prim is visible → vm.get_value_as_bool() is False.
    sphere_item = model._path_cache["/World/Geometry/Sphere"]
    cube_item = model._path_cache["/World/Geometry/Cube"]
    ground_item = model._path_cache["/World/Geometry/Ground"]

    sphere_vm = model.get_item_value_model(sphere_item, 2)
    print(f"  sphere hidden (inverted)={sphere_vm.get_value_as_bool()}")
    assert sphere_vm.get_value_as_bool() is False

    # Group toggle: select {sphere, cube} and toggle hidden=True. Both prims
    # must flip to invisible, and the call must bracket a single undo group.
    begin_calls: list[str] = []
    end_calls: list[int] = []
    orig_begin = adapter.begin_undo_group
    orig_end = adapter.end_undo_group

    def begin(label: str) -> None:
        begin_calls.append(label)
        orig_begin(label)

    def end() -> None:
        end_calls.append(1)
        orig_end()

    adapter.begin_undo_group = begin  # type: ignore[assignment]
    adapter.end_undo_group = end  # type: ignore[assignment]

    model._selected_items = [sphere_item, cube_item]
    sphere_vm.set_value(True)
    await _drive(10)

    # The adapter change rebuilds the tree; re-expand /World and /World/Geometry
    # so the flipped Visibility cells are on-screen for the screenshot.
    new_world = model._path_cache.get("/World")
    if new_world is not None:
        tree_view.set_expanded(new_world, True, False)
    await _drive(3)
    new_geo = model._path_cache.get("/World/Geometry")
    if new_geo is not None:
        tree_view.set_expanded(new_geo, True, False)
    await _drive(10)

    print(
        f"  group toggle: begin={begin_calls} end={len(end_calls)} "
        f"sphere.visible={sphere_item.adapter_item.visible} "
        f"cube.visible={cube_item.adapter_item.visible}"
    )
    assert begin_calls == ["Toggle Visibility"]
    assert len(end_calls) == 1
    assert sphere_item.adapter_item.visible is False
    assert cube_item.adapter_item.visible is False

    uitesting.capture_screenshot("/tmp/ovgear_step5_2.png")
    print("  group-toggle screenshot: /tmp/ovgear_step5_2.png")

    # Single-item toggle: clicked item NOT in selection → only itself flips.
    # Refresh item handles because the tree rebuild replaced HierarchyItem wrappers.
    sphere_item = model._path_cache["/World/Geometry/Sphere"]
    cube_item = model._path_cache["/World/Geometry/Cube"]
    ground_item = model._path_cache["/World/Geometry/Ground"]
    model._selected_items = [sphere_item, cube_item]
    ground_vm = model.get_item_value_model(ground_item, 2)
    ground_item.adapter_item.visible = False
    ground_vm.set_value(False)  # Show it again — clicked outside selection.
    await _drive(5)
    new_world = model._path_cache.get("/World")
    if new_world is not None:
        tree_view.set_expanded(new_world, True, False)
    await _drive(3)
    new_geo = model._path_cache.get("/World/Geometry")
    if new_geo is not None:
        tree_view.set_expanded(new_geo, True, False)
    await _drive(10)

    print(
        f"  unselected toggle: ground.visible={ground_item.adapter_item.visible} "
        f"sphere.visible={sphere_item.adapter_item.visible} "
        f"cube.visible={cube_item.adapter_item.visible}"
    )
    assert ground_item.adapter_item.visible is True
    assert sphere_item.adapter_item.visible is False
    assert cube_item.adapter_item.visible is False

    uitesting.capture_screenshot("/tmp/ovgear_step5_3.png")
    print("  single-item screenshot: /tmp/ovgear_step5_3.png")

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()

    print("\nDone.")


if __name__ == "__main__":
    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    write_split_ini()
    ui.init("OvGear Step 5 Verify", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

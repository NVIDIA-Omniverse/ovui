# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 6 visual verification — ``ovwidgets.stage/widget/`` subpackage carve-out.

Step 6 is a **pure refactor**: no behaviour changes, no visual changes.
These screenshots exist only to prove identity — every interaction that
worked before the carve-out still works after it, and every import path
(shim, canonical, top-level, direct-submodule) resolves to the same class.

Three screenshots:

  1. /tmp/ovgear_step6_1.png — baseline mock stage, tree expanded.
     Identical to Step 5's baseline screenshot.
  2. /tmp/ovgear_step6_2.png — after selecting /World/Geometry/Sphere via
     the SelectionBus. Selection sync through the moved hierarchy_model /
     stage_widget is unchanged.
  3. /tmp/ovgear_step6_3.png — after flipping Sphere's visibility via its
     VisibilityValueModel. Row flips to "-", proving the wiring through
     the moved StageDelegate is intact.

Runtime log verifies that the four canonical import paths
(``ovwidgets.stage.StageWidget`` / ``ovwidgets.stage.stage_widget.StageWidget`` /
``ovwidgets.stage.widget.StageWidget`` / ``ovwidgets.stage.widget.stage_widget.StageWidget``)
all resolve to the same class object.

Run:
    DISPLAY=:99 python3.12 tests/verify_step6.py
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
    tree_view = widget._tree_view

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

    uitesting.capture_screenshot("/tmp/ovgear_step6_1.png")
    print("  baseline screenshot: /tmp/ovgear_step6_1.png")

    # Selection sync through the moved StageWidget / HierarchyModel path.
    sphere_path = "/World/Geometry/Sphere"
    SelectionBus.instance().publish([sphere_path], source="verify_step6")
    await _drive(10)
    uitesting.capture_screenshot("/tmp/ovgear_step6_2.png")
    print(
        "  selection screenshot: /tmp/ovgear_step6_2.png; "
        f"selected={len(model._selected_items)}"
    )
    assert len(model._selected_items) == 1
    sphere_item = model._path_cache[sphere_path]
    assert model._selected_items[0] is sphere_item

    # Visibility flip through the moved StageDelegate / VisibilityValueModel path.
    sphere_vm = model.get_item_value_model(sphere_item, 2)
    pre_hidden = sphere_vm.get_value_as_bool()
    sphere_vm.set_value(True)
    await _drive(10)
    new_world = model._path_cache.get("/World")
    if new_world is not None:
        tree_view.set_expanded(new_world, True, False)
    await _drive(3)
    new_geo = model._path_cache.get("/World/Geometry")
    if new_geo is not None:
        tree_view.set_expanded(new_geo, True, False)
    await _drive(10)
    sphere_item = model._path_cache[sphere_path]
    sphere_vm = model.get_item_value_model(sphere_item, 2)
    post_hidden = sphere_vm.get_value_as_bool()
    uitesting.capture_screenshot("/tmp/ovgear_step6_3.png")
    print(f"  vis screenshot: /tmp/ovgear_step6_3.png; pre={pre_hidden} post={post_hidden}")
    assert pre_hidden is False
    assert post_hidden is True

    # Identity check across import entry points.
    from ovwidgets.stage import StageWidget as SW_pkg
    from ovwidgets.stage.stage_widget import StageWidget as SW_shim
    from ovwidgets.stage.widget import StageWidget as SW_canon
    from ovwidgets.stage.widget.stage_widget import StageWidget as SW_direct
    assert SW_pkg is SW_shim is SW_canon is SW_direct
    print(f"  StageWidget identity OK: {SW_pkg.__module__}")

    from ovwidgets.stage.hierarchy_model import HierarchyModel as HM_shim
    from ovwidgets.stage.widget.hierarchy_model import HierarchyModel as HM_direct
    assert HM_shim is HM_direct
    print(f"  HierarchyModel identity OK: {HM_direct.__module__}")

    from ovwidgets.stage.stage_delegate import _KEY_ESCAPE as KE_shim
    from ovwidgets.stage.widget.stage_delegate import _KEY_ESCAPE as KE_direct
    assert KE_shim == KE_direct == 256
    print(f"  _KEY_ESCAPE re-export OK: {KE_shim}")

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
    ui.init("OvGear Step 6 Verify", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

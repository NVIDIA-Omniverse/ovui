# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 4 visual verification — HierarchyItem flag cache has no visual impact.

Step 4 adds a lazy flag cache on ``HierarchyItem`` plus convenience accessors
(``is_default`` / ``is_inactive`` / ``is_instance_proxy`` / ``is_class_item`` /
``is_abstract``). The delegate does not yet *consume* these — that lands in
later steps — so no pixels should change.

This script captures three screenshots and also dumps adapter→cache round-trip
evidence so the reader sees the accessors resolving against real
``HierarchyModel`` state.

  1. /tmp/ovgear_step4_1.png — mock mode baseline (no default prim).
  2. /tmp/ovgear_step4_2.png — after marking ``/World/Geometry`` as the
     default prim via ``MockStageAdapter.set_default``; tree should look
     identical (no delegate consumer yet).
  3. /tmp/ovgear_step4_3.png — after selecting ``/World/Geometry/Sphere``;
     Property panel updates as usual.

Run:
    DISPLAY=:99 python3.12 tests/verify_step4.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting
from ovui_data_adapters.common import ItemFlags

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
    # In mock mode app._stage_adapter stays None — the live adapter sits on
    # the StageWidget's model. Grab it directly.
    adapter = model._adapter
    tree_view = widget._tree_view

    # Expand root and /World so all three branches are visible.
    tree_view.set_expanded(model._root, True, False)
    await _drive(5)
    world_item = model._path_cache.get("/World")
    if world_item is not None:
        tree_view.set_expanded(world_item, True, False)
    await _drive(10)

    uitesting.capture_screenshot("/tmp/ovgear_step4_1.png")
    print("  baseline screenshot: /tmp/ovgear_step4_1.png")

    # Prime the cache on a few known items, then flip the adapter's default
    # prim and show that mark_dirty propagated down to each cached item.
    cached_items = list(model._path_cache.values()) + [model._root]
    for item in cached_items:
        item._refresh_flags(adapter)
    clean_before = sum(1 for it in cached_items if not it._flags_dirty)
    print(f"  cached items clean before change: {clean_before}/{len(cached_items)}")

    adapter.set_default("/World/Geometry")
    await _drive(5)

    dirty_after = sum(1 for it in cached_items if it._flags_dirty)
    print(f"  cached items dirty after change: {dirty_after}/{len(cached_items)}")

    geometry = model._path_cache.get("/World/Geometry")
    if geometry is not None:
        print(
            f"  /World/Geometry → is_default={geometry.is_default(adapter)} "
            f"is_inactive={geometry.is_inactive(adapter)} "
            f"is_abstract={geometry.is_abstract(adapter)}"
        )
        print(f"  /World/Geometry item_flags={geometry.item_flags(adapter)!r}")
        assert geometry.is_default(adapter), "is_default should be True after set_default"
        assert not geometry.is_inactive(adapter)

    uitesting.capture_screenshot("/tmp/ovgear_step4_2.png")
    print("  default-marked screenshot: /tmp/ovgear_step4_2.png")

    # Also exercise IS_INACTIVE end-to-end and prove the accessor catches it
    # on the next call (mark_dirty invalidates — no stale cache).
    adapter.set_item_flags("/World/Lights", ItemFlags.IS_INACTIVE)
    await _drive(5)
    lights = model._path_cache.get("/World/Lights")
    if lights is not None:
        print(f"  /World/Lights → is_inactive={lights.is_inactive(adapter)}")
        assert lights.is_inactive(adapter), "is_inactive should be True"

    app.selection_bus.publish(["/World/Geometry/Sphere"], source="test")
    await _drive(15)
    uitesting.capture_screenshot("/tmp/ovgear_step4_3.png")
    print("  selection screenshot: /tmp/ovgear_step4_3.png")

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
    ui.init("OvGear Step 4 Verify", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

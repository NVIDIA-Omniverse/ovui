# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Bug 13 reproduction — manipulator drag steals selection on mouse-up.

Flow:
1. Load simple_scene.usda.
2. Publish ``/World/Cube`` on the selection bus. The gizmo appears at
   the Cube position, X-axis arrow pointing right toward the Sphere.
3. Drag the cube's X-axis arrow from its approximate screen position
   toward the Sphere's screen position. When the mouse is released,
   the cursor is over the Sphere.
4. Expected: Cube stays selected (drag moved the Cube; selection
   must not be affected by the mouse-up landing over another prim).
5. Pre-fix bug mode: Sphere becomes selected — the pick gesture's
   ``_on_ended`` fired after the gizmo's ``_on_ended`` cleared
   ``is_active``, so ``has_live_gizmo_drag()`` returned False and
   the selection raycast ran at the release point. The fix is a
   ``_drag_ended_this_cycle`` latch on each gizmo drag gesture that
   ``has_live_gizmo_drag()`` also consults — see
   :class:`ovwidgets.viewport.pick_gesture.GizmoAwarePickManager`.
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


# Pixel coordinates observed in the 1280x720 probe screenshot at the default
# camera: Cube gizmo pivot ≈ (582, 280), X-arrow tip ≈ (625, 280), Sphere
# centre ≈ (705, 280). Drag from the arrow shaft toward the Sphere so
# mouse-up lands over the Sphere's screen position.
CUBE_X_ARROW = (608, 280)
SPHERE_CENTER = (708, 280)


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _selected_paths(app: Application) -> list:
    snap = app.selection_bus.get_snapshot()
    return list(snap.paths()) if snap else []


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    app._startup_usd_path = USD_PATH
    asyncio.ensure_future(app.run_async())

    await _drive(60)

    # --- Step 1: select the Cube via the bus --------------------------------
    app.selection_bus.publish(["/World/Cube"], source="qa")
    await _drive(10)
    uitesting.capture_screenshot("/tmp/ovgear_bug13_before_drag.png")
    print(f"[BEFORE DRAG] selected = {_selected_paths(app)}")

    # --- Step 2: drag the X-axis arrow toward the Sphere --------------------
    await uitesting.mouse_drag(
        CUBE_X_ARROW[0], CUBE_X_ARROW[1],
        SPHERE_CENTER[0], SPHERE_CENTER[1],
        button=0, steps=20,
    )
    await _drive(10)
    uitesting.capture_screenshot("/tmp/ovgear_bug13_after_drag.png")

    # --- Step 3: check selection after drag ---------------------------------
    after = _selected_paths(app)
    print(f"[AFTER DRAG] selected = {after}")

    if after == ["/World/Cube"]:
        print("[PASS] Selection stayed on Cube — bug NOT reproduced.")
        outcome = 0
    elif after == ["/World/Sphere"]:
        print("[FAIL — BUG 13] Selection stole to Sphere after manipulator drag.")
        outcome = 13
    elif not after:
        print("[FAIL — BUG 13] Selection cleared after manipulator drag.")
        outcome = 13
    else:
        print(f"[FAIL — BUG 13] Selection changed unexpectedly: {after}")
        outcome = 13

    # Verification screenshot location per task brief.
    uitesting.capture_screenshot("/tmp/ovgear_bugfix_13.png")

    app._running = False
    ui.shutdown()
    sys.exit(outcome)


if __name__ == "__main__":
    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    write_split_ini()
    ui.init("OvGear Bug 13 Repro", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

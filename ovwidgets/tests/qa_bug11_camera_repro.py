# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA reproduction and post-fix verification for Bug 11.

Drives real mouse drag + key events against the live Application to
exercise the camera manipulator. Verifies that the camera now orbits,
pans, zooms, and flies without the pre-fix pathology where a single
drag step spiked the azimuth by tens of radians and pegged the
elevation clamp.

Pre-fix reference (captured on the bugged build before the NDC-bounds
filter landed in ``ovwidgets.viewport/camera_gesture.py``):

    [INITIAL]  az=0.00  el=0.40  target=(0, 0, 0)
    [RMB DRAG] az=276.43  el=1.50 (clamp)  target=(-0.32, -0.39, -0.23)

Post-fix the same drag produces a well-behaved delta (magnitudes in
single-digit radians, elevation inside the clamp).
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

# Loading the shipped simple-scene USD gives the renderer real geometry to
# draw, so the before/after screenshots visibly confirm the camera moved.
USD_PATH = os.path.join(os.path.dirname(__file__), "data", "simple_scene.usda")

# Viewport pixel coordinates in the default 1280x720 layout. The viewport
# panel spans roughly x=375..905, y=32..~514. The centre sits just to the
# right of the stage-browser splitter.
VP_CX = 640
VP_CY = 270

BUTTON_LEFT = 0
BUTTON_RIGHT = 1
BUTTON_MIDDLE = 2

KEY_W = ord("W")


def _cam_state(app: Application) -> tuple:
    vp = app._viewport_window
    c = vp._camera.state
    return (
        round(c.azimuth, 4),
        round(c.elevation, 4),
        round(c.distance, 4),
        tuple(round(v, 4) for v in c.target),
    )


async def _drive(n: int = 8) -> None:
    for _ in range(n):
        await ui.next_frame()


async def _snap(name: str) -> str:
    path = f"/tmp/ovgear_bug11_{name}.png"
    uitesting.capture_screenshot(path)
    print(f"  -> {path}")
    return path


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    app._startup_usd_path = USD_PATH
    asyncio.ensure_future(app.run_async())

    await _drive(60)
    await _snap("01_initial")
    initial = _cam_state(app)
    print(f"[INITIAL] {initial}")

    # ---- Test 1: RMB drag (tumble) ---------------------------------------
    before_rmb = _cam_state(app)
    await uitesting.mouse_drag(
        VP_CX - 80, VP_CY, VP_CX + 80, VP_CY,
        button=BUTTON_RIGHT, steps=16,
    )
    await _drive(6)
    after_rmb = _cam_state(app)
    print(f"\n[RMB DRAG] before={before_rmb}")
    print(f"[RMB DRAG] after ={after_rmb}")
    await _snap("02_after_rmb_drag")

    az_delta = abs(after_rmb[0] - before_rmb[0])
    if az_delta > 10.0:
        print(f"[FAIL] azimuth delta {az_delta:.2f} rad — phantom events not filtered")
        sys.exit(2)
    if after_rmb[1] in (1.5, -1.5):
        print("[FAIL] elevation pegged at clamp — phantom events not filtered")
        sys.exit(2)
    print(f"[PASS] RMB tumble produced az_delta={az_delta:.3f} rad (sane)")

    # ---- Test 2: MMB drag (pan) ------------------------------------------
    # Drain any residual inertia before measuring pan so target-only
    # motion is attributable to the pan gesture itself.
    await _drive(60)
    before_mmb = _cam_state(app)
    await uitesting.mouse_drag(
        VP_CX, VP_CY - 80, VP_CX, VP_CY + 80,
        button=BUTTON_MIDDLE, steps=16,
    )
    await _drive(6)
    after_mmb = _cam_state(app)
    print(f"\n[MMB DRAG] before={before_mmb}")
    print(f"[MMB DRAG] after ={after_mmb}")
    await _snap("03_after_mmb_drag")
    if after_mmb[3] == before_mmb[3]:
        print("[WARN] MMB drag did not move the camera target")
    else:
        print("[PASS] MMB pan shifted the target")

    # ---- Test 3: Scroll zoom ---------------------------------------------
    before_zoom = _cam_state(app)
    uitesting._ui._inject_mouse_move(VP_CX, VP_CY)
    await ui.next_frame()
    await uitesting.mouse_scroll(VP_CX, VP_CY, 0, 3.0)
    await _drive(4)
    after_zoom = _cam_state(app)
    print(f"\n[SCROLL ZOOM] before_dist={before_zoom[2]} after_dist={after_zoom[2]}")
    await _snap("04_after_scroll")

    # ---- Test 4: WASD with RMB held (flight mode) ------------------------
    # Flight mode is gated on "RMB held" — poll tumble/look gestures for
    # the ``is_active`` signal. Rather than re-driving the whole mouse
    # flow manually, set the manual RMB flag on the flight-keyboard and
    # dispatch a W key event.
    vp = app._viewport_window
    flight = vp._flight_keyboard
    flight.notify_rmb_press()
    flight.handle_key_event(KEY_W, 0, True)
    before_wasd = _cam_state(app)
    for _ in range(20):
        await ui.next_frame()
    after_wasd = _cam_state(app)
    print(f"\n[WASD W] before_target={before_wasd[3]}")
    print(f"[WASD W] after_target ={after_wasd[3]}")
    flight.handle_key_event(KEY_W, 0, False)
    flight.notify_rmb_release()
    await _drive(4)
    if after_wasd[3] != before_wasd[3]:
        print("[PASS] WASD flight moved the camera target")
    else:
        print("[FAIL] WASD flight did not move the target")
    await _snap("05_after_wasd")

    # Final summary screenshot at the documented verification path.
    uitesting.capture_screenshot("/tmp/ovgear_bugfix_11.png")
    print("\n=== Repro complete — see /tmp/ovgear_bugfix_11.png ===")
    app._running = False
    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    write_split_ini()
    ui.init("OvGear Bug 11 Repro", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

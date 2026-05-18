# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA reproduction for Back/Forward button hit-area bug.

Launches the full app, navigates to a subfolder so the Back button is
enabled, then measures the geometry of the Back button's click target vs
the painted icon and hovers at the icon centre to see whether the hover
highlight rect covers the icon.
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

TEST_ROOT = "/tmp/ovgear_bug_repro"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _dump_geometry(tag: str, bb) -> tuple:
    back_btn = bb._back_button
    bx = float(back_btn.screen_position_x)
    by = float(back_btn.screen_position_y)
    bw = float(back_btn.computed_width)
    bh = float(back_btn.computed_height)
    print(
        f"[{tag}] back_button screen=({bx:.1f},{by:.1f}) "
        f"size=({bw:.1f}x{bh:.1f}) enabled={back_btn.enabled}"
    )
    print(
        f"[{tag}] back ZStack frame / icon would be 28x28 at parent rect — "
        f"Button alone is the clickable area, icon is non-interactive overlay"
    )
    return bx, by, bw, bh


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    await _drive(30)

    widget = app._content_window._widget
    bb = widget._browser_bar

    widget.navigate_to(f"file://{TEST_ROOT}")
    await _drive(6)
    widget.navigate_to(f"file://{TEST_ROOT}/level1")
    await _drive(6)

    print("\n=== QA: Back button hit-area geometry ===")
    bx, by, bw, bh = _dump_geometry("after navigate", bb)

    # Hover at the centre of the nominal 28x28 icon region — compute based on
    # the ZStack parent where the icon centre should be.
    # The button (clickable) is at (bx,by). If the button has collapsed to a
    # smaller size than the icon, the hover will miss.
    # Icon is centred in a 28x28 frame; its centre is at (bx + 14, by + 14)
    # relative to the ZStack (but back_btn.screen_position_* is the Button's
    # own origin, which may differ from the ZStack's origin if the Button
    # was laid out at the origin of the ZStack but with no intrinsic size).
    icon_cx = bx + 14.0
    icon_cy = by + 14.0
    button_cx = bx + bw / 2.0
    button_cy = by + bh / 2.0
    print(
        f"icon_centre=({icon_cx:.1f},{icon_cy:.1f}) "
        f"button_centre=({button_cx:.1f},{button_cy:.1f})"
    )

    # Hover at the icon centre and capture.
    await uitesting.mouse_move(icon_cx, icon_cy)
    await _drive(10)
    uitesting.capture_screenshot("/tmp/ovgear_backfwd_hitarea_before.png")
    print("Saved: /tmp/ovgear_backfwd_hitarea_before.png (hover at icon centre)")

    # Also capture hover at the button rect centre (should be where hit area is)
    await uitesting.mouse_move(button_cx, button_cy)
    await _drive(10)
    uitesting.capture_screenshot("/tmp/ovgear_backfwd_hitarea_button_centre.png")
    print("Saved: /tmp/ovgear_backfwd_hitarea_button_centre.png")

    # Move mouse away and capture neutral
    await uitesting.mouse_move(640.0, 500.0)
    await _drive(10)
    uitesting.capture_screenshot("/tmp/ovgear_backfwd_hitarea_neutral.png")
    print("Saved: /tmp/ovgear_backfwd_hitarea_neutral.png")

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
    ui.init("OvGear Back/Forward Hit-Area QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

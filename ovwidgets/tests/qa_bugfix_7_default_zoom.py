# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Bug 7 verification — fresh-boot zoom must default to 100% (index 2)."""

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

OUT_PATH = "/tmp/ovgear_bugfix_7.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    await _drive(40)

    window = getattr(app, "_content_window", None)
    widget = getattr(window, "_widget", None) if window is not None else None

    if widget is not None:
        zoom_bar = getattr(widget, "_zoom_bar", None)
        idx = getattr(widget, "_grid_view_scale_index", None)
        cur = zoom_bar.current_slider_index if zoom_bar is not None else None
        print(
            "[BUG 7 VERIFY] "
            f"widget._grid_view_scale_index={idx} "
            f"zoom_bar.current_slider_index={cur}"
        )
        assert idx == 2, f"Expected default index 2 (100%), got {idx}"
    else:
        print("[BUG 7 VERIFY] Widget not discoverable via Application")

    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    for fname in ("layout.json", "settings.json"):
        path = os.path.expanduser(f"~/.ovgear/{fname}")
        if os.path.exists(path):
            os.unlink(path)
    write_split_ini()
    ui.init("OvGear Bug 7 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

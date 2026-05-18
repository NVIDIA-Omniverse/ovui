# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Capture OvGear screenshots in mock mode and USD-open mode.

Run:
    DISPLAY=:99 python tests/verify_usd_open.py
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


async def _drive(app: Application, frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _capture_mock() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    await _drive(app, 20)
    uitesting.capture_screenshot("/tmp/ovgear_usd_mock.png")
    print("  mock screenshot: /tmp/ovgear_usd_mock.png")

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()


async def _capture_usd() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    app._startup_usd_path = USD_PATH  # simulate CLI arg
    task = asyncio.ensure_future(app.run_async())

    await _drive(app, 30)  # extra frames so the stage loads and first render happens
    uitesting.capture_screenshot("/tmp/ovgear_usd_scene.png")
    print("  USD screenshot: /tmp/ovgear_usd_scene.png")

    # Sanity assertions
    print(f"  stage_adapter set: {app._stage_adapter is not None}")
    print(f"  stage_window adapter: {app._stage_window._model._adapter is not None if app._stage_window else 'no window'}")
    print(f"  renderer class: {type(app._viewport_window._renderer).__name__ if app._viewport_window else 'no viewport'}")

    # Select a prim to trigger property panel + selection highlight
    app.selection_bus.publish(["/World/Cube"], source="test")
    await _drive(app, 10)
    uitesting.capture_screenshot("/tmp/ovgear_usd_scene_selected.png")
    print("  selected screenshot: /tmp/ovgear_usd_scene_selected.png")

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()


async def _main() -> None:
    print("=== Mock mode ===")
    await _capture_mock()
    print("=== USD open mode ===")
    await _capture_usd()
    print("\nDone.")


if __name__ == "__main__":
    _layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(_layout_path):
        os.unlink(_layout_path)
    write_split_ini()
    ui.init("OvGear USD Verify", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

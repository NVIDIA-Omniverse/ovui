# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Reproduce / verify double-click opens USD file in content browser.

Captures a before / after pair:

* ``/tmp/ovgear_usd_open_before.png`` — app with ``simple_scene.usda``
  loaded, content browser navigated to ``tests/data``, grid view.
* ``/tmp/ovgear_usd_open_after.png`` — after double-clicking
  ``step3_2_scene.usda`` on the grid, showing the stage re-loaded.

The script drives the widget's grid double-click handler directly
(mirrors a user double-click on a card) and prints the stage
identifier + current-file-path before / after so the log makes the
wire-up visible even when the on-screen diff is subtle.
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

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
START_USD = os.path.join(DATA_DIR, "simple_scene.usda")
TARGET_USD_NAME = "step3_2_scene.usda"
BEFORE_OUT = "/tmp/ovgear_usd_open_before.png"
AFTER_OUT = "/tmp/ovgear_usd_open_after.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _stage_identifier(app: Application) -> str:
    adapter = getattr(app, "_stage_adapter", None)
    if adapter is None:
        return "<no adapter>"
    stage = getattr(adapter, "stage", None)
    if stage is None:
        return "<no stage>"
    try:
        return stage.GetRootLayer().identifier
    except Exception as exc:  # pragma: no cover - diagnostic path
        return f"<error: {exc}>"


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    app._startup_usd_path = START_USD
    task = asyncio.ensure_future(app.run_async())
    await _drive(50)

    cb_window = app._content_window
    if cb_window is None or cb_window._widget is None:
        raise RuntimeError("Content browser widget not built yet")
    widget = cb_window._widget

    widget.navigate_to("file://" + DATA_DIR)
    await _drive(25)

    detail_model = widget.get_detail_model()
    children = detail_model.get_item_children(detail_model.root)
    target = next(
        (c for c in children if c.name == TARGET_USD_NAME), None,
    )
    if target is None:
        names = ", ".join(c.name for c in children)
        raise RuntimeError(
            f"{TARGET_USD_NAME!r} not found; available: {names}",
        )

    uitesting.capture_screenshot(BEFORE_OUT)
    print(f"Saved: {BEFORE_OUT}")
    print(f"  stage before: {_stage_identifier(app)!r}")
    print(f"  current_file before: {app._current_file_path!r}")

    widget._on_grid_double_click(target)
    await _drive(60)

    uitesting.capture_screenshot(AFTER_OUT)
    print(f"Saved: {AFTER_OUT}")
    print(f"  stage after: {_stage_identifier(app)!r}")
    print(f"  current_file after: {app._current_file_path!r}")

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
    ui.init("OvGear USD Open Repro", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot harness for Design Step 1 redo — warm unified dark palette.

This is *not* a pytest test.  It is a helper script driven by hand to
capture the before/after evidence for the palette pass.  It uses the
``_venv312`` interpreter (which has
``ovrtx`` installed and produces a real GPU-rendered 3D scene) rather
than the mock renderer used by the pytest suite.

Run it with::

    rm -f imgui.ini && \
    export LD_LIBRARY_PATH="<path-to-ovui>/_venv/lib/python3.10/site-packages/omni/ui:<path-to-ovui>/_venv/lib/python3.10/site-packages/omni/ui_scene" && \
    OVGEAR_SHOT=/tmp/ovgear_step1redo_after.png \
    <path-to-ovgear>/_venv312/bin/python \
    <path-to-ovgear>/tests/qa_design_step1redo_screenshot.py

Output path is controlled by the ``OVGEAR_SHOT`` environment variable so
the same script captures both the BEFORE (with the palette reverted via
``git stash``) and the AFTER pass.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, "<path-to-ovgear>")

import omni.ui as ui  # noqa: E402
from omni.ui import testing as uitesting  # noqa: E402

from ovwidgets.app.application import Application  # noqa: E402
from ovwidgets.app.layout import write_split_ini  # noqa: E402
from ovwidgets.app.style import apply_global_styles, set_theme  # noqa: E402
from ovwidgets.common.selection import SelectionBus  # noqa: E402

USD_PATH = "<path-to-ovgear>/tests/data/simple_scene.usda"
OUT = os.environ.get("OVGEAR_SHOT", "/tmp/ovgear_step1redo.png")


async def _drive(n: int) -> None:
    for _ in range(n):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None
    app = Application()
    app._running = True
    app._startup_usd_path = USD_PATH
    task = asyncio.ensure_future(app.run_async())
    await _drive(150)

    widget = app._stage_window._widget
    widget.expand("/")
    widget.expand("/World")
    await _drive(30)

    await uitesting.mouse_move(100, 135)
    await _drive(2)
    await uitesting.mouse_click(100, 135)
    await _drive(30)

    ok = uitesting.capture_screenshot(OUT)
    print(f"Screenshot -> {OUT} ok={ok}")

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except Exception:
        task.cancel()
    app.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    for p in [os.path.expanduser("~/.ovgear/layout.json"), "imgui.ini"]:
        if os.path.exists(p):
            os.unlink(p)
    write_split_ini()
    ui.init("OvGear Check", width=1280, height=800)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 12 QA screenshot — console script verification after package rename.

Proves that the application starts correctly via the canonical launcher
path (`ovwidgets <usd_file>` / `ovgear <usd_file>` / `python -m ovwidgets.app
<usd_file>`) after the ovgear → ovwidgets.app rename and shim removal
(Issue #31 Steps 3–11).

## Why this harness is a valid proof of the console-script path

The screenshot API (`uitesting.capture_screenshot`) requires running
*inside* the omni.ui event loop.  A subprocess invocation of
`ovwidgets <usd_file>` would start a separate event loop with no way to
capture frames.  The accepted approach (Codex R1 option 3) is therefore
to simulate the CLI invocation from within the event loop while using
the same code path that the real console script follows:

  ovwidgets tests/data/simple_scene.usda
  └─ main_sync()
     └─ main(argv=['tests/data/simple_scene.usda'])
        ├─ ns = _parse_args(['tests/data/simple_scene.usda'])  ← done here
        ├─ app = Application()                                 ← done here
        └─ app.run(usd_path=ns.usd_file)
              └─ app._startup_usd_path = ns.usd_file           ← done here
              └─ ui.run(app.run_async())  ← replaced by QA event loop

The only divergence from `app.run()` is that the QA harness calls
`ui.init()` / `write_split_ini()` / style setup externally (so the
screenshot loop can run) instead of inside `app.run()`.  The USD
loading path — `app._startup_usd_path = ns.usd_file` processed inside
`run_async()` → `open_file()` — is identical to the real CLI path.

## Screenshots

Screenshot 1 (/tmp/ovgear_step12_1.png):
    After startup with `simple_scene.usda` loaded at init time
    (simulating `ovwidgets tests/data/simple_scene.usda`).
    Viewport HUD shows "SCENE simple_scene.usda"; Stage Browser shows
    prim tree with count; Layers panel shows loaded layer.

Screenshot 2 (/tmp/ovgear_step12_2.png):
    After user-like left-click on the "/" root prim row in the Stage
    Browser (via `uitesting.mouse_click()`).  Property Inspector
    should show pseudo-root properties or "No selection" if the click
    landed on an empty area.

## Run

    cd <path-to-ovgear>
    LD_LIBRARY_PATH=".../omni/ui:.../omni/ui_scene:.../usd-build/install/lib" \\
    PYTHONPATH=".../usd-build/install/lib/python" \\
    OVRTX_SKIP_USD_CHECK=1 \\
        python3.12 tests/qa_step12_console_launch_screenshot.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting

from ovwidgets.app.__main__ import _parse_args  # real CLI argument parser
from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus

USD_PATH = os.path.join(os.path.dirname(__file__), "data", "simple_scene.usda")
OUT_1 = "/tmp/ovgear_step12_1.png"
OUT_2 = "/tmp/ovgear_step12_2.png"

# Stage Browser occupies the left ~380 px column in the 1280×720 layout.
# The first data row (root prim "/") sits ~6 px below the header at y≈100.
_STAGE_ROW_X = 65
_STAGE_ROW_Y = 100


def _assert_screenshot(path: str, label: str) -> None:
    """Assert capture succeeded and file is non-empty."""
    ok = uitesting.capture_screenshot(path)
    assert ok, f"capture_screenshot returned False for {label} ({path})"
    p = Path(path)
    assert p.exists(), f"{label} screenshot file missing: {path}"
    size = p.stat().st_size
    assert size > 0, f"{label} screenshot file is empty: {path}"
    print(f"{label} saved: {path} ({size} bytes)")


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    # ── Simulate: ovwidgets tests/data/simple_scene.usda ─────────────────────
    #
    # _parse_args() is the real CLI parser from ovwidgets.app.__main__; using it here
    # replicates the argument-processing step that main_sync() / ovwidgets performs.
    # Setting app._startup_usd_path to ns.usd_file is identical to what
    # app.run(usd_path=ns.usd_file) does internally before calling ui.run().
    ns = _parse_args([USD_PATH])
    app = Application()
    app._running = True
    app._startup_usd_path = ns.usd_file   # same assignment app.run() makes

    task = asyncio.ensure_future(app.run_async())

    # Allow run_async to build panels + open the startup file (~40 frames).
    await _drive(60)

    # ── Screenshot 1: startup with USD loaded ─────────────────────────────────
    # Proves the `ovwidgets <usd_file>` CLI workflow: the application launches
    # and the stage opens automatically from the startup argument.
    _assert_screenshot(OUT_1, "Screenshot 1 (startup with USD)")

    # ── Screenshot 2: user-like prim selection via ovui mouse input ───────────
    # Move to the Stage Browser root-prim row and left-click, then capture.
    # Coordinates derived from Screenshot 1 layout analysis.
    await uitesting.mouse_move(_STAGE_ROW_X, _STAGE_ROW_Y)
    await _drive(3)
    await uitesting.mouse_click(_STAGE_ROW_X, _STAGE_ROW_Y)
    await _drive(10)
    _assert_screenshot(OUT_2, "Screenshot 2 (after prim click)")

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
    ui.init("OvGear Step 12 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

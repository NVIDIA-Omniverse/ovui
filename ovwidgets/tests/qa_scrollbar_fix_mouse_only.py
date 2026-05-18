# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA driver for fix/stage-scroll-containment — MOUSE/KEYBOARD ONLY.

Proves that:
  * the parent ui.Window for Stage Browser no longer shows a thick
    built-in scrollbar (WINDOW_FLAGS_NO_SCROLLBAR)
  * the inner ScrollingFrame still owns a thin scrollbar that appears
    when the tree body overflows
  * filter bar + column header stay pinned during scroll

All interaction happens through ``omni.ui.testing`` mouse / keyboard /
screenshot primitives. NO programmatic widget/model/selection calls.

Outputs: /tmp/ovgear_scrollbar_fix_{1..5}.png
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import omni.ui as ui
from omni.ui import testing

# Scene setup: patch MockStageAdapter so its default tree contains 160
# siblings under /World. This is *scene setup*, not widget-state
# mutation — analogous to choosing which USD file the app opens on
# startup. Once the app is running, every interaction below goes
# through mouse / keyboard only. Must happen BEFORE importing
# Application so that when Application builds its default StageWindow
# with ``MockStageAdapter()`` the patched adapter is the one wired in.
from ovwidgets.common.testing import mock_stage as _mock_stage

_PRIM_COUNT = 160
_orig_adapter_init = _mock_stage.MockStageAdapter.__init__


def _patched_adapter_init(self, prim_count: int = 0) -> None:
    _orig_adapter_init(self, prim_count if prim_count > 0 else _PRIM_COUNT)


_mock_stage.MockStageAdapter.__init__ = _patched_adapter_init

from ovwidgets.app.application import Application  # noqa: E402
from ovwidgets.app.layout import write_split_ini  # noqa: E402
from ovwidgets.app.style import apply_global_styles, set_theme  # noqa: E402
from ovwidgets.common.selection import SelectionBus  # noqa: E402


def shoot(n: int, label: str) -> None:
    path = f"/tmp/ovgear_scrollbar_fix_{n}.png"
    ok = testing.capture_screenshot(path)
    print(f"  screenshot {n}: {label:<45}  ok={ok}  -> {path}")


async def _main() -> None:
    app = Application()
    app._running = True
    app_task = asyncio.ensure_future(app.run_async())

    # Give Application enough frames to build and dock all windows.
    for _ in range(30):
        await ui.next_frame()
    await testing.wait_frames(5)

    # ── SHOT 1 — initial dock state ──────────────────────────────────
    shoot(1, "initial — all panels docked")

    # Stage Browser is docked top-left. The filter bar sits at y≈26-53,
    # the column header at y≈60-72, and the /World data row at y≈83-98.
    # The level-0 branch arrow (Stage.BranchArrow Triangle) sits in the
    # x=0..14 strip on the left of the row; visually its tip lands at
    # roughly (20, 91) — measured from the initial screenshot above.
    # Hover first so omni.ui marks the row as the hot item, then click.
    await testing.mouse_move(20, 91)
    await testing.wait_frames(3)
    await testing.mouse_click(20, 91, 0)
    await testing.wait_frames(20)

    # ── SHOT 2 — tree expanded ──────────────────────────────────────
    shoot(2, "tree expanded — no thick window scrollbar")

    # ── Scroll down inside the tree body ─────────────────────────────
    # Hover over the tree so omni.ui routes wheel events to the inner
    # ScrollingFrame. dy is in wheel ticks; negative = scroll content
    # up (view moves down). A handful of large ticks gets us clearly
    # mid-track so the thin Stage.ScrollingFrame thumb is visible.
    await testing.mouse_move(160, 200)
    await testing.wait_frames(3)
    for _ in range(15):
        await testing.mouse_scroll(160, 200, dx=0, dy=-3)
        await testing.wait_frames(2)
    await testing.wait_frames(10)

    # ── SHOT 3 — scrolled, thin scrollbar mid-track ─────────────────
    shoot(3, "scrolled — thin inner scrollbar, header pinned")

    # ── Click a visible row to select it ────────────────────────────
    await testing.mouse_click(120, 300, 0)
    await testing.wait_frames(8)

    # ── SHOT 4 — row selected ───────────────────────────────────────
    shoot(4, "row selected — highlight visible")

    # ── Scroll back up ───────────────────────────────────────────────
    await testing.mouse_move(160, 200)
    await testing.wait_frames(3)
    for _ in range(20):
        await testing.mouse_scroll(160, 200, dx=0, dy=3)
        await testing.wait_frames(2)
    await testing.wait_frames(10)

    # ── SHOT 5 — back at top ────────────────────────────────────────
    shoot(5, "back at top — filter + header pinned")

    app._running = False
    try:
        await asyncio.wait_for(app_task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        app_task.cancel()
    app.shutdown()
    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    # Clean persisted layout to ensure the split layout is rebuilt.
    _layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(_layout_path):
        os.unlink(_layout_path)

    Application._instance = None
    SelectionBus._instance = None

    write_split_ini()
    ui.init("OvGear Scrollbar QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

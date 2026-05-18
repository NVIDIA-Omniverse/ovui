# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 42 — NavigationModel.

Captures a screenshot of the full app with the content browser's left
pane showing the new :class:`NavigationModel` — three collection roots
(Bookmarks, My Computer, Recent) — rather than the pre-Step-42 folder
hierarchy. Saves to ``/tmp/ovgear_step42_1_collections.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step42_navigation_screenshot.py
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
from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.common.selection import SelectionBus

OUT_PATH = "/tmp/ovgear_step42_1_collections.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Let the dockspace render.
    await _drive(40)

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget

    # Swap to MockBackend so the detail pane has some populated rows
    # to show next to the new nav pane. The nav pane renders the same
    # three collection roots regardless of backend (stubs return ``[]``
    # for now — Steps 43/44/46 flesh them out).
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home")
    await _drive(20)

    nav = widget._navigation_model
    if nav is None:
        raise RuntimeError("NavigationModel missing on widget")

    print(
        "Nav collections:",
        [(c.identifier, c.title, c.icon_key) for c in nav.collections],
    )

    await _drive(10)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")

    await _drive(2)

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
    ui.init("OvGear Step 42 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

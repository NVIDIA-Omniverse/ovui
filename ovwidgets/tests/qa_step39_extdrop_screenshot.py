# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 39 — external OS drop.

Drives a programmatic external drop so the rendered grid shows a file
that has been copied into the current detail folder via the Step-39
``_on_external_drop`` path:

1. Launch the app, swap to :class:`MockBackend`, navigate to
   ``mock://Home/Documents/Projects`` so the grid shows three files.
2. Invoke :meth:`ContentBrowserWindow._on_external_drop` with a
   synthesised :class:`WidgetMouseDropEvent` whose ``mime_data`` is
   ``mock://Home/Textures/concrete.png``. This mirrors what ovui's
   drop event delivers when a user drags a file from the OS file
   manager onto the content browser window.
3. Refresh the detail model so the dropped row materialises, then
   screenshot the grid with the newly-copied file visible →
   ``/tmp/ovgear_step39_1_app.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step39_extdrop_screenshot.py
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

OUT_PATH = "/tmp/ovgear_step39_1_app.png"


class _FakeDropEvent:
    """Minimal stand-in for ovui's :class:`WidgetMouseDropEvent`."""

    def __init__(self, mime_data: str) -> None:
        self.mime_data = mime_data


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

    # Swap to MockBackend at mock://Home/Documents/Projects. Grid shows
    # the Step-3 demo files (demo.usda, demo.usdc, readme.md).
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home/Documents/Projects")
    await _drive(15)
    widget._detail_model.get_item_children(None)
    await _drive(5)

    # Simulate a drag from the OS file manager of concrete.png into the
    # current folder (Projects). The harness cannot synthesize a real
    # mouse drop but _on_external_drop is the same entry point ovui's
    # drop event routes to — the subsequent status line matches what
    # the live UI posts after a successful drop.
    evt = _FakeDropEvent("mock://Home/Textures/concrete.png")
    cw._on_external_drop(evt)
    await _drive(15)

    # Refresh so the new row materialises immediately in the grid.
    widget._detail_model.refresh_all()
    await _drive(10)

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
    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    write_split_ini()
    ui.init("OvGear Step 39 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

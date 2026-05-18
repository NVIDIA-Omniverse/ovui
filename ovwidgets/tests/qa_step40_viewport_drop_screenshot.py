# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 40 — viewport drop.

Drives a programmatic viewport drop so the rendered app shows the
state immediately after a ``.usd`` dragged from the content browser
has been routed through :meth:`ViewportWidget._on_drop` →
:meth:`Application._on_drop` with ``target="viewport"``:

1. Launch the app, swap the content browser to :class:`MockBackend`,
   and navigate to ``mock://Home/Documents/Projects`` so the detail
   grid shows ``demo.usda`` / ``demo.usdc`` / ``readme.md``.
2. Patch :meth:`Application.open_file` to a status-posting stub —
   ``mock://`` URLs are not backed by real disk USD files, so a
   real ``Usd.Stage.Open`` would fail the QA run.
3. Invoke :meth:`ViewportWidget._on_drop` with a synthesised
   :class:`WidgetMouseDropEvent` whose ``mime_data`` is the USD URL.
   This mirrors what ovui delivers when a user drags a file from
   the content browser onto the viewport widget.
4. Screenshot the full app → ``/tmp/ovgear_step40_1_app.png`` with
   the status bar showing "Drop routed → open_file(demo.usda)" in
   success green.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step40_viewport_drop_screenshot.py
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
from ovwidgets.common.error_reporter import ErrorReporter
from ovwidgets.common.selection import SelectionBus

OUT_PATH = "/tmp/ovgear_step40_1_app.png"


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

    # Patch open_file — the mock URL is not backed by disk so a real
    # Usd.Stage.Open would crash / noop. The stub posts a status so
    # the screenshot visibly proves the drop landed in open_file().
    def _stub_open_file(path: str) -> None:
        ErrorReporter.show_status(
            f"Drop routed → open_file({os.path.basename(path)})",
            level="success",
        )

    app.open_file = _stub_open_file  # type: ignore[assignment]

    # Simulate a drag from the content browser of demo.usda onto the
    # viewport. The drop fires on the viewport's per-window
    # ``set_drop_fn`` which delegates to :meth:`_on_drop` (our Step-40
    # shim) which in turn calls :meth:`Application._on_drop` with
    # ``target="viewport"``.
    vw = app._viewport_window
    if vw is None:
        raise RuntimeError("Viewport window not built yet")
    evt = _FakeDropEvent("mock://Home/Documents/Projects/demo.usda")
    vw._on_drop(evt)
    await _drive(15)

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
    ui.init("OvGear Step 40 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

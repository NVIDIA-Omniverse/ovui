# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 20 — BrowserBar wiring.

Three proof screenshots of the wired browser bar at the top of the
:class:`FileBrowserWidget`:

* ``/tmp/ovgear_step20_1_initial.png`` — content browser mounted at
  ``mock://Home``. Breadcrumb bar shows "mock://Home"; back / forward
  buttons are both disabled (only the seed entry in history).
* ``/tmp/ovgear_step20_2_drilled.png`` — after drilling into
  ``Documents`` via the programmatic drill path. Breadcrumb shows
  "mock://Home/Documents"; back button is now enabled.
* ``/tmp/ovgear_step20_3_back.png`` — after firing the back button.
  Breadcrumb re-rolls to "mock://Home"; back is now disabled, forward
  is enabled.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step20_browser_bar_screenshot.py
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

OUT_INITIAL = "/tmp/ovgear_step20_1_initial.png"
OUT_DRILLED = "/tmp/ovgear_step20_2_drilled.png"
OUT_BACK = "/tmp/ovgear_step20_3_back.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Let the dockspace render, windows claim their dock nodes, the
    # two content models populate their initial LocalFS roots.
    await _drive(40)

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget

    # Swap to MockBackend so the screenshot doesn't depend on the
    # developer's local filesystem, and navigate to a known root.
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home")
    await _drive(10)
    widget._tree_tree_view.set_expanded(widget._tree_model._root, True, False)
    widget._detail_tree_view.set_expanded(
        widget._detail_model._root, True, False,
    )
    await _drive(10)

    # Screenshot 1 — initial mount at mock://Home. Browser bar shows
    # breadcrumb for Home; back/forward are disabled.
    uitesting.capture_screenshot(OUT_INITIAL)
    print(f"Saved: {OUT_INITIAL}")

    # Screenshot 2 — after navigating into Documents via apply-path.
    # The breadcrumb should update to show "mock://Home/Documents" and
    # the back button should be enabled.
    widget._on_apply_path("mock://Home/Documents")
    await _drive(10)
    uitesting.capture_screenshot(OUT_DRILLED)
    print(f"Saved: {OUT_DRILLED}")

    # Screenshot 3 — after clicking back. The detail pane re-roots to
    # Home, breadcrumb rewinds, forward becomes enabled.
    widget.go_back()
    await _drive(10)
    uitesting.capture_screenshot(OUT_BACK)
    print(f"Saved: {OUT_BACK}")

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
    ui.init("OvGear Step 20 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

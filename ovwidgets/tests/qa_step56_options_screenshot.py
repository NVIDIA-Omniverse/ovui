# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 56 — Options menu.

the content browser implementation step 56 adds :class:`OptionsButton` — a gear-icon
toolbar button whose click pops a dropdown with:

* Show hidden files (checkbox)
* Show detail pane (checkbox)
* Sort by Name / Date / Size (radio)

This QA script boots the full app, reaches into the content-browser
widget to locate the live :class:`OptionsButton`, and programmatically
pops its dropdown so a screenshot captures the whole Path | Star |
Search | Filter | Gear row + the expanded menu.

Saves to ``/tmp/ovgear_step56_1_options.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step56_options_screenshot.py
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

OUT_PATH = "/tmp/ovgear_step56_1_options.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Let the main window panels build + dock.
    await _drive(40)

    # Reach into the content-browser window's widget and trigger the
    # options-menu button's click handler. Using the internal
    # ``_on_button_clicked`` drive point rather than a synthesised
    # mouse event so the screenshot is reproducible across runs.
    content_window = getattr(app, "_content_window", None)
    if content_window is None or getattr(content_window, "_widget", None) is None:
        raise RuntimeError(
            "QA harness could not locate the content browser window"
        )

    widget = content_window._widget
    options = widget._options_button
    if options is None:
        raise RuntimeError(
            "OptionsButton was not constructed on the FileBrowserWidget"
        )

    # Open the dropdown.
    options._on_button_clicked()
    await _drive(15)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")
    print("OptionsButton state:")
    print(f"  show_hidden={options.show_hidden}")
    print(f"  show_detail_pane={options.show_detail_pane}")
    print(f"  sort_policy={options.sort_policy}")
    print(f"Menu visible after click: {options._menu is not None}")

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
    ui.init("OvGear Step 56 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

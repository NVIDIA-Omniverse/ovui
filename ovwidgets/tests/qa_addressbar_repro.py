# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Address bar edit-mode reproduction + verification.

Launches the app, navigates to a deep folder, takes a screenshot of the
breadcrumb address bar, double-clicks on an empty area of the bar to
trigger edit mode, types a path, presses Enter, and captures the
result.

Saves three screenshots so before/edit/after can be compared:

  /tmp/ovgear_addressbar_before.png  (breadcrumb view)
  /tmp/ovgear_addressbar_edit.png    (edit mode after double-click)
  /tmp/ovgear_addressbar_after.png   (post-navigate breadcrumb view)

Run from <path-to-ovgear>/:

  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_addressbar_repro.py
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
from ovwidgets.content.backends.local_fs_backend import LocalFSBackend

TEST_ROOT = "/tmp/ovgear_bug_repro"
DEEP_URL = f"file://{TEST_ROOT}/level1/level2"
TARGET_URL = f"file://{TEST_ROOT}/level1"
BEFORE = "/tmp/ovgear_addressbar_before.png"
EDIT = "/tmp/ovgear_addressbar_edit.png"
AFTER = "/tmp/ovgear_addressbar_after.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None
    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())
    await _drive(40)

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window not built")
    widget = cw._widget
    widget.set_backend(LocalFSBackend())
    widget.navigate_to(DEEP_URL)
    await _drive(30)

    browser_bar = widget._browser_bar
    path_field = browser_bar._path_field

    print(f"[QA] Path before: {path_field.path!r}")
    print(f"[QA] Mode before: {getattr(path_field, '_mode', 'N/A')}")

    uitesting.capture_screenshot(BEFORE)
    print(f"[QA] saved {BEFORE}")

    # Find the path bar screen position via its scrolling frame.
    frame = path_field._scrolling_frame
    pbx = float(frame.screen_position_x) + float(frame.computed_width) - 60
    pby = float(frame.screen_position_y) + float(frame.computed_height) / 2
    print(f"[QA] Double-clicking at ({pbx:.1f}, {pby:.1f})")

    await uitesting.mouse_double_click(pbx, pby)
    await _drive(5)

    print(f"[QA] Mode after double-click: {getattr(path_field, '_mode', 'N/A')}")
    edit_field = getattr(path_field, "_edit_field", None)
    print(
        f"[QA] _edit_field: {edit_field!r} "
        f"visible={getattr(edit_field, 'visible', 'N/A')}"
    )
    breadcrumb_frame = path_field._breadcrumb_frame
    print(
        f"[QA] _breadcrumb_frame.visible="
        f"{getattr(breadcrumb_frame, 'visible', 'N/A')}"
    )

    uitesting.capture_screenshot(EDIT)
    print(f"[QA] saved {EDIT}")

    # Type the target path and press Enter.
    await uitesting.type_text(TARGET_URL)
    await _drive(3)
    # 257 is the Enter / Return key in GLFW.
    await uitesting.press_key(257)
    await _drive(15)

    print(f"[QA] Path after Enter: {path_field.path!r}")
    print(
        f"[QA] Mode after Enter: {getattr(path_field, '_mode', 'N/A')}"
    )

    uitesting.capture_screenshot(AFTER)
    print(f"[QA] saved {AFTER}")

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
    settings_path = os.path.expanduser("~/.ovgear/settings.json")
    if os.path.exists(settings_path):
        os.unlink(settings_path)
    write_split_ini()
    ui.init("OvGear Address Bar Repro", width=1400, height=800)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

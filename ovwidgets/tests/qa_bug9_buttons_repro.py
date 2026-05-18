# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Bug 9 verification — Filter/Settings/Bookmarks toolbar buttons.

Before the fix, the three right-edge toolbar buttons
(Bookmark star, Filter funnel, Options gear) appear visually active
— same hover affordance and color as the nav buttons — but for the
the content browser implementation V1 surface their dropdown behaviors are subtle or
no-op for homogeneous folders. This QA drives a simulated click at
each button's centre via :meth:`ui.Button.call_clicked_fn` (the
same entry point ovui's Widget.cpp invokes after a real mouse
press) and captures screenshots.

Evidence saved to:
  * /tmp/ovgear_bugfix_9_before.png — toolbar in active state
  * /tmp/ovgear_bugfix_9_filter_click.png — filter menu open
  * /tmp/ovgear_bugfix_9_options_click.png — options menu open
  * /tmp/ovgear_bugfix_9_bookmark_click.png — bookmark dialog open

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_bug9_buttons_repro.py
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
TEST_ROOT_URL = f"file://{TEST_ROOT}"


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
    widget.navigate_to(TEST_ROOT_URL)
    await _drive(25)

    filt = widget._filter_button
    opts = widget._options_button
    book = widget._bookmark_button
    f_btn = getattr(filt, "_button", None)
    o_btn = getattr(opts, "_button", None)
    b_btn = getattr(book, "_button", None)

    # Inspect enabled + tooltip state pre-fix
    print("[BUG 9 BEFORE] filter_button.enabled=",
          getattr(f_btn, "enabled", "?"),
          " tooltip=", repr(getattr(f_btn, "tooltip", "")))
    print("[BUG 9 BEFORE] options_button.enabled=",
          getattr(o_btn, "enabled", "?"),
          " tooltip=", repr(getattr(o_btn, "tooltip", "")))
    print("[BUG 9 BEFORE] bookmark_button.enabled=",
          getattr(b_btn, "enabled", "?"),
          " tooltip=", repr(getattr(b_btn, "tooltip", "")))

    uitesting.capture_screenshot("/tmp/ovgear_bugfix_9_before.png")
    print("[BUG 9] saved /tmp/ovgear_bugfix_9_before.png")

    # "Click" filter button and capture the menu popping up.
    if f_btn is not None:
        f_btn.call_clicked_fn()
    await _drive(15)
    uitesting.capture_screenshot("/tmp/ovgear_bugfix_9_filter_click.png")
    print("[BUG 9] saved /tmp/ovgear_bugfix_9_filter_click.png "
          "(menu should NOT appear after fix)")

    # Close any open menu before next click.
    if filt is not None and filt._menu is not None:
        filt._menu.hide()
    await _drive(5)

    # "Click" options button.
    if o_btn is not None:
        o_btn.call_clicked_fn()
    await _drive(15)
    uitesting.capture_screenshot("/tmp/ovgear_bugfix_9_options_click.png")
    print("[BUG 9] saved /tmp/ovgear_bugfix_9_options_click.png "
          "(menu should NOT appear after fix)")

    if opts is not None and opts._menu is not None:
        opts._menu.hide()
    await _drive(5)

    # "Click" bookmark button.
    if b_btn is not None:
        b_btn.call_clicked_fn()
    await _drive(15)
    uitesting.capture_screenshot("/tmp/ovgear_bugfix_9_bookmark_click.png")
    print("[BUG 9] saved /tmp/ovgear_bugfix_9_bookmark_click.png "
          "(dialog should NOT appear after fix)")

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    # Make sure test tree exists so navigation succeeds.
    os.makedirs(TEST_ROOT, exist_ok=True)

    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    settings_path = os.path.expanduser("~/.ovgear/settings.json")
    if os.path.exists(settings_path):
        os.unlink(settings_path)
    write_split_ini()
    ui.init("OvGear Bug 9 Verification", width=1400, height=800)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

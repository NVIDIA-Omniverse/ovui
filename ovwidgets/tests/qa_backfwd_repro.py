# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA reproduction script for Back/Forward navigation buttons.

Drives a real FileBrowserWidget through a sequence of folder drill-ins,
then exercises the back/forward buttons and asserts the observable
state (path field contents, button enabled/disabled flags).

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_backfwd_repro.py
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

TEST_ROOT = "/tmp/ovgear_bug_repro"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    await _drive(30)

    widget = app._content_window._widget
    bb = widget._browser_bar

    print("\n=== QA: Back/Forward buttons ===")

    # Drill through 3 folders.
    paths = [
        f"file://{TEST_ROOT}",
        f"file://{TEST_ROOT}/level1",
        f"file://{TEST_ROOT}/level1/level2",
    ]
    for p in paths:
        widget.navigate_to(p)
        await _drive(4)
        print(
            f"[nav] after navigate_to({p}): "
            f"path_field={bb._path_field.path!r} "
            f"history={bb._history._history!r} "
            f"cursor={bb._history._cursor} "
            f"back_enabled={bb._back_button.enabled} "
            f"forward_enabled={bb._forward_button.enabled}"
        )

    uitesting.capture_screenshot("/tmp/ovgear_backfwd_before.png")
    print("Saved: /tmp/ovgear_backfwd_before.png")

    # Click back (via go_back entry point).
    widget.go_back()
    await _drive(4)
    print(
        f"[back 1] path_field={bb._path_field.path!r} "
        f"cursor={bb._history._cursor} "
        f"back_enabled={bb._back_button.enabled} "
        f"forward_enabled={bb._forward_button.enabled}"
    )

    widget.go_back()
    await _drive(4)
    print(
        f"[back 2] path_field={bb._path_field.path!r} "
        f"cursor={bb._history._cursor} "
        f"back_enabled={bb._back_button.enabled} "
        f"forward_enabled={bb._forward_button.enabled}"
    )

    widget.go_forward()
    await _drive(4)
    print(
        f"[forward 1] path_field={bb._path_field.path!r} "
        f"cursor={bb._history._cursor} "
        f"back_enabled={bb._back_button.enabled} "
        f"forward_enabled={bb._forward_button.enabled}"
    )

    # Now test mid-history navigation. At this point we've: A, B, C (cursor=0=C),
    # went back twice (cursor=2=A), went forward once (cursor=1=B). Now navigate
    # to new D — should truncate the forward history (C).
    widget.navigate_to(f"file://{TEST_ROOT}/sibling1")
    await _drive(4)
    print(
        f"[mid-history nav] path_field={bb._path_field.path!r} "
        f"history={bb._history._history!r} "
        f"cursor={bb._history._cursor} "
        f"back_enabled={bb._back_button.enabled} "
        f"forward_enabled={bb._forward_button.enabled}"
    )

    # Now back. User expects to go to B (the one we were at before D was inserted).
    widget.go_back()
    await _drive(4)
    print(
        f"[back after mid-nav] path_field={bb._path_field.path!r} "
        f"cursor={bb._history._cursor} "
        f"EXPECTED: file://{TEST_ROOT}/level1"
    )

    # Check the direct button click path too (not just widget.go_back).
    print("\n=== Testing direct button clicks ===")
    # Use ovui testing to actually click the button widget.
    back_btn = bb._back_button
    print(f"back button enabled: {back_btn.enabled}")
    forward_btn = bb._forward_button
    print(f"forward button enabled: {forward_btn.enabled}")

    uitesting.capture_screenshot("/tmp/ovgear_backfwd_after.png")
    print("Saved: /tmp/ovgear_backfwd_after.png")

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
    ui.init("OvGear Back/Forward QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

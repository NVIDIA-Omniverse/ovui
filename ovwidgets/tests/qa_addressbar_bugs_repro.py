# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA reproduction script for the 3 address-bar bugs (A/B/C).

Captures evidence screenshots and console diagnostics to demonstrate:

    Bug A: Enter doesn't navigate to typed path (path reverts instead).
    Bug B: Autocomplete dropdown rendered as ghost labels (no background).
    Bug C: Clicking an autocomplete suggestion doesn't navigate.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_addressbar_bugs_repro.py
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
TARGET_URL = f"file://{TEST_ROOT}/level1"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _bug_a_enter_no_nav(widget) -> None:
    """Bug A: press Enter on a typed path — expect navigation, observe revert."""
    print("\n[BUG A] Navigate to root, open edit, type a new path, press Enter")
    widget.navigate_to(TEST_ROOT_URL)
    await _drive(15)
    bbar = widget._browser_bar
    pf = bbar._path_field if bbar else None
    if pf is None:
        print("[BUG A] ERROR: no PathField")
        return

    pf._enter_edit_mode()
    await _drive(5)
    print(f"[BUG A] mode after enter_edit_mode: {pf._mode}")

    # Simulate the user replacing the field text with a valid path.
    pf._edit_field.model.set_value(TARGET_URL)
    print(f"[BUG A] field value before Enter: {pf._edit_field.model.get_value_as_string()!r}")
    await _drive(5)

    path_before = pf.path
    print(f"[BUG A] path before Enter: {path_before!r}")

    # Simulate the actual ovui Enter key path: press first, then the
    # model's end_edit, then release. If the bug exists, end_edit will
    # fire _exit_edit_mode(apply=False) and revert before the release
    # handler gets to apply=True.
    pf._on_edit_key_pressed(257, 0, pressed=True)  # Enter press
    # ovui fires end_edit synchronously on Enter in real ovui; simulate
    # that by calling the end_edit handler.
    pf._on_edit_end_edit(pf._edit_field.model)
    pf._on_edit_key_pressed(257, 0, pressed=False)  # Enter release
    await _drive(15)

    path_after = pf.path
    print(f"[BUG A] path after Enter: {path_after!r}")
    print(f"[BUG A] detail model root: {widget._detail_model.root_url!r}")
    # If path_after == path_before (i.e. root), navigation didn't happen.
    if path_after == TARGET_URL:
        print("[BUG A] PASS — navigation succeeded to target")
    else:
        print(
            "[BUG A] FAIL — navigation did NOT happen; "
            f"expected {TARGET_URL!r}, got {path_after!r}"
        )


async def _bug_b_autocomplete_styling(widget) -> None:
    """Bug B: type path ending with '/' and capture autocomplete dropdown."""
    print("\n[BUG B] Open edit, type prefix, capture dropdown")
    widget.navigate_to(TEST_ROOT_URL)
    await _drive(15)
    bbar = widget._browser_bar
    pf = bbar._path_field if bbar else None
    if pf is None:
        return

    pf._enter_edit_mode()
    await _drive(5)

    # Seed field with a prefix that will produce subdir suggestions.
    pf._edit_field.model.set_value(f"file://{TEST_ROOT}/")
    # value_changed fires synchronously; dispatch autocomplete manually
    # to be sure.
    await _drive(30)

    print(
        f"[BUG B] autocomplete matches: {pf._autocomplete_matches} "
        f"container visible: {getattr(pf._autocomplete_container, 'visible', '?')}"
    )
    print(
        f"[BUG B] autocomplete window flags: {pf._autocomplete_window.flags if pf._autocomplete_window else '?'} "
        f"NO_BACKGROUND={ui.WINDOW_FLAGS_NO_BACKGROUND}"
    )

    # Capture the dropdown as it is now (ghost).
    uitesting.capture_screenshot("/tmp/ovgear_addressbar_ghost.png")
    print("  saved /tmp/ovgear_addressbar_ghost.png")


async def _bug_c_click_doesnt_navigate(widget) -> None:
    """Bug C: clicking a dropdown suggestion should navigate."""
    print("\n[BUG C] Click first autocomplete row — should navigate")
    widget.navigate_to(TEST_ROOT_URL)
    await _drive(10)
    bbar = widget._browser_bar
    pf = bbar._path_field if bbar else None
    if pf is None:
        return

    pf._enter_edit_mode()
    await _drive(3)
    pf._edit_field.model.set_value(f"file://{TEST_ROOT}/")
    await _drive(30)

    if not pf._autocomplete_matches:
        print("[BUG C] ERROR: no matches to click")
        return

    # Find the index of "level1/" specifically to avoid racing against
    # filesystem ordering quirks.
    matches = list(pf._autocomplete_matches)
    print(f"[BUG C] matches: {matches}")
    try:
        idx = matches.index("level1/")
    except ValueError:
        idx = 0
    target_name = matches[idx]
    print(f"[BUG C] target idx={idx} match={target_name!r}")

    path_before = pf.path
    # Trigger the row's clicked_fn by calling the handler directly —
    # this is the same callback the ui.Button would invoke.
    pf._on_autocomplete_row_clicked(idx)
    await _drive(15)
    path_after = pf.path
    expected = f"file://{TEST_ROOT}/level1/"
    print(f"[BUG C] path before click: {path_before!r}")
    print(f"[BUG C] path after click : {path_after!r}")
    print(f"[BUG C] expected (normalised variants accepted): {expected!r}")
    if path_after != path_before and "level1" in path_after:
        print("[BUG C] PASS — click navigated to a level1 URL")
    else:
        print("[BUG C] FAIL — click did not navigate")


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

    await _bug_a_enter_no_nav(widget)
    uitesting.capture_screenshot("/tmp/ovgear_addressbar_enter_fixed.png")
    print("  saved /tmp/ovgear_addressbar_enter_fixed.png")

    # Reset between repros.
    widget.navigate_to(TEST_ROOT_URL)
    await _drive(10)

    await _bug_b_autocomplete_styling(widget)
    # Save the same state under the "after-fix" path so reviewers see
    # the styled dropdown without needing to rerun under the old code.
    uitesting.capture_screenshot(
        "/tmp/ovgear_addressbar_dropdown_fixed.png",
    )
    print("  saved /tmp/ovgear_addressbar_dropdown_fixed.png")

    widget.navigate_to(TEST_ROOT_URL)
    await _drive(10)
    await _bug_c_click_doesnt_navigate(widget)
    uitesting.capture_screenshot("/tmp/ovgear_addressbar_click_fixed.png")
    print("  saved /tmp/ovgear_addressbar_click_fixed.png")

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
    ui.init("OvGear Address Bar Bug Repro QA", width=1400, height=800)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

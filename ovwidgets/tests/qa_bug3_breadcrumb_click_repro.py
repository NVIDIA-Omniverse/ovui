# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Bug 3 reproduction/verification — click a PARENT breadcrumb.

Launches the app, navigates to a depth-4 folder, screenshots the full
breadcrumb, clicks an ancestor breadcrumb via a real mouse event, and
screenshots the post-click state. Prints the :class:`PathField`'s
``path`` before/after, the visible breadcrumb button sizes, and the
scrollbar state so we can distinguish a "scroll pinned to tail" issue
from a "breadcrumbs collapse to zero size" issue (Bug 3's actual
failure mode before the fix).

Saves:
  /tmp/ovgear_bug3_before.png
  /tmp/ovgear_bug3_after.png

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_bug3_breadcrumb_click_repro.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting

from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus
from ovwidgets.content.backends.local_fs_backend import LocalFSBackend

TEST_ROOT = "/tmp/ovgear_bug_repro"
DEEP_URL = f"file://{TEST_ROOT}/level1/level2/level3"
BEFORE = "/tmp/ovgear_bug3_before.png"
AFTER = "/tmp/ovgear_bug3_after.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


# Global button-capture hook. Installed for the whole session so every
# time :class:`PathField` rebuilds its breadcrumbs, every button is
# recorded against its current label — the test then looks up the
# ancestor button by name after rendering settles.
_captured_breadcrumb_buttons: Dict[str, ui.Button] = {}
_original_button_cls = ui.Button

# Breadcrumb button label set from the deep-path URL. Only buttons
# whose label matches these get recorded — filters out every other
# ui.Button in the app (back/forward, zoom, toolbar, etc.).
_BREADCRUMB_LABELS = {
    "file://", "tmp", "ovgear_bug_repro", "level1", "level2", "level3",
}


def _tracking_button(*args, **kwargs):
    btn = _original_button_cls(*args, **kwargs)
    label = args[0] if args else kwargs.get("text", "")
    if label in _BREADCRUMB_LABELS:
        _captured_breadcrumb_buttons[label] = btn
    return btn


def _snapshot_breadcrumbs() -> List[Tuple[str, float, float, float, float]]:
    snap = []
    for label, btn in _captured_breadcrumb_buttons.items():
        snap.append((
            label,
            float(btn.screen_position_x),
            float(btn.screen_position_y),
            float(btn.computed_width),
            float(btn.computed_height),
        ))
    return snap


async def _main() -> None:
    ui.Button = _tracking_button  # type: ignore[assignment]

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

    print(f"[BUG 3 REPRO] Path before click: {path_field.path!r}")
    print(
        f"[BUG 3 REPRO] Tokens before click: "
        f"{path_field._tokenize(path_field.path)}"
    )
    print(
        f"[BUG 3 REPRO] Previous tokens: {path_field._previous_tokens}"
    )

    snap_before = _snapshot_breadcrumbs()
    print(f"[BUG 3 REPRO] Breadcrumb buttons before click (n={len(snap_before)}):")
    for label, sx, sy, w, h in snap_before:
        print(
            f"    label={label!r} pos=({sx:.1f}, {sy:.1f}) "
            f"size=({w:.1f}x{h:.1f})"
        )

    uitesting.capture_screenshot(BEFORE)
    print(f"[BUG 3 REPRO] saved {BEFORE}")

    target_label = "ovgear_bug_repro"
    target_button = _captured_breadcrumb_buttons.get(target_label)
    if target_button is None:
        raise RuntimeError(f"Could not find {target_label!r} breadcrumb button")

    bx = float(target_button.screen_position_x) + float(target_button.computed_width) / 2
    by = float(target_button.screen_position_y) + float(target_button.computed_height) / 2
    print(f"[BUG 3 REPRO] Clicking {target_label!r} at ({bx:.1f}, {by:.1f})")

    await uitesting.mouse_click(bx, by)
    await _drive(30)

    print(f"[BUG 3 REPRO] Path after click: {path_field.path!r}")
    print(
        f"[BUG 3 REPRO] Tokens after click: "
        f"{path_field._tokenize(path_field.path)}"
    )
    hist = browser_bar._history
    current_url = hist._history[hist._cursor] if hist._history else None
    print(f"[BUG 3 REPRO] BrowserBar history current: {current_url!r}")
    print(f"[BUG 3 REPRO] Detail model root URL: {widget._detail_model._root_url!r}")

    snap_after = _snapshot_breadcrumbs()
    print(f"[BUG 3 REPRO] Breadcrumb buttons after click (n={len(snap_after)}):")
    for label, sx, sy, w, h in snap_after:
        print(
            f"    label={label!r} pos=({sx:.1f}, {sy:.1f}) "
            f"size=({w:.1f}x{h:.1f})"
        )
    print(
        f"[BUG 3 REPRO] scrolling_frame.scroll_x="
        f"{path_field._scrolling_frame.scroll_x}, "
        f"scroll_x_max={path_field._scrolling_frame.scroll_x_max}"
    )

    # Acceptance check: after clicking an ancestor, the breadcrumbs for
    # ``file://`` / ``tmp`` / ``ovgear_bug_repro`` must all have
    # non-zero width (i.e., laid out and visible to the user). Before
    # the fix, these collapsed to size=(0,0) after a parent-navigation
    # click because the HStack.clear()+with-rebuild ran inside a draw
    # callback and failed to attach the new buttons.
    ancestor_labels = ["file://", "tmp", "ovgear_bug_repro"]
    visible_ancestors = [
        lbl for lbl in ancestor_labels
        if lbl in _captured_breadcrumb_buttons
        and _captured_breadcrumb_buttons[lbl].computed_width > 0.0
    ]
    print(
        f"[BUG 3 REPRO] Ancestor breadcrumbs with non-zero width: "
        f"{visible_ancestors}"
    )
    if visible_ancestors == ancestor_labels:
        print("[BUG 3 REPRO] PASS — all ancestor breadcrumbs laid out")
    else:
        print(
            "[BUG 3 REPRO] FAIL — some ancestors collapsed. Expected "
            f"{ancestor_labels}, got {visible_ancestors}"
        )

    uitesting.capture_screenshot(AFTER)
    print(f"[BUG 3 REPRO] saved {AFTER}")

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()
    ui.Button = _original_button_cls  # type: ignore[assignment]
    sys.exit(0)


if __name__ == "__main__":
    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    settings_path = os.path.expanduser("~/.ovgear/settings.json")
    if os.path.exists(settings_path):
        os.unlink(settings_path)
    write_split_ini()
    ui.init("OvGear Bug 3 Repro", width=1400, height=800)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

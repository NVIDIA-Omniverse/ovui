# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 11.

Three proof screenshots:

* ``/tmp/ovgear_step11_1_initial.png`` — the full app with the Content
  panel docked below the viewport, root row showing the user's home
  folder.
* ``/tmp/ovgear_step11_2_expanded.png`` — after programmatically
  expanding the root folder, so the tree view renders nested
  children in the three-column layout.
* ``/tmp/ovgear_step11_3_menu_toggle.png`` — after the "Content
  Browser" Window-menu handler hides the panel (equivalent to
  clicking the menu item). Proves the menu wiring actually toggles
  visibility.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step11_content_browser_screenshot.py
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

OUT_INITIAL = "/tmp/ovgear_step11_1_initial.png"
OUT_EXPANDED = "/tmp/ovgear_step11_2_expanded.png"
OUT_TOGGLED = "/tmp/ovgear_step11_3_menu_toggle.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Let the layout settle: dockspace renders, windows claim dock nodes,
    # the content model populates the root's initial children.
    await _drive(40)

    # Screenshot 1 — initial state
    uitesting.capture_screenshot(OUT_INITIAL)
    print(f"Saved: {OUT_INITIAL}")

    # Expand the root folder so the tree view renders nested children.
    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget
    tv = widget._tree_view
    model = widget._model
    root_item = model._root
    if tv is not None and root_item is not None:
        tv.set_expanded(root_item, True, False)
        await _drive(8)
        # Also expand the first folder child, if any, so the tree shows
        # two levels of nesting. This exercises the lazy-populate path.
        children = model.get_item_children(root_item)
        for child in children:
            if getattr(child, "is_folder", False):
                tv.set_expanded(child, True, False)
                break
        await _drive(8)

    uitesting.capture_screenshot(OUT_EXPANDED)
    print(f"Saved: {OUT_EXPANDED}")

    # Screenshot 3 — toggle visibility off via the menu-equivalent handler.
    # ``menu_bar._toggle_window`` flips ``managed_window.visible`` — the
    # same code path that the Window > Content Browser menu item runs.
    from ovwidgets.app.menu_bar import _toggle_window
    _toggle_window(app._content_window)
    await _drive(8)
    uitesting.capture_screenshot(OUT_TOGGLED)
    print(f"Saved: {OUT_TOGGLED}")

    # Leave the panel visible for any follow-up harness runs.
    _toggle_window(app._content_window)
    await _drive(4)

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
    ui.init("OvGear Step 11 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

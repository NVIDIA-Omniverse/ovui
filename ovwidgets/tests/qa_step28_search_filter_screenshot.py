# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Step 28 — search + filter toolbar.

Three proof screenshots of the toolbar row with the new search field
and filter button wired into the detail-pane filtering pipeline:

* ``/tmp/ovgear_step28_1_toolbar.png`` — the toolbar row at rest.
  BrowserBar on the left (back / forward / breadcrumb), SearchField in
  the middle with its magnifier + empty input + clear-X, FilterButton
  on the right showing the funnel icon.
* ``/tmp/ovgear_step28_2_search.png`` — after typing "demo" into the
  search field (at ``mock://Home/Documents/Projects``), the detail
  pane narrows to the two demo files; ``readme.md`` is hidden.
* ``/tmp/ovgear_step28_3_filter.png`` — after clearing the search and
  toggling the USD filter on, the detail pane again narrows to the USD
  files. Folders (none at this level) would always pass regardless.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step28_search_filter_screenshot.py
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
from ovwidgets.common.asset_types import AssetCategory
from ovwidgets.common.selection import SelectionBus

OUT_TOOLBAR = "/tmp/ovgear_step28_1_toolbar.png"
OUT_SEARCH = "/tmp/ovgear_step28_2_search.png"
OUT_FILTER = "/tmp/ovgear_step28_3_filter.png"


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
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget

    # Mock backend + navigate to Projects so both the Documents drill-in
    # and the Projects leaves are materialised when the screenshots fire.
    widget.set_backend(MockBackend())
    widget.navigate_to("mock://Home/Documents/Projects")
    await _drive(15)
    # Expand the tree pane so the full path is visible on the left.
    widget._tree_tree_view.set_expanded(widget._tree_model._root, True, False)
    await _drive(10)

    # Screenshot 1 — toolbar at rest. All three leaves visible in the
    # detail pane (demo.usda, demo.usdc, readme.md).
    uitesting.capture_screenshot(OUT_TOOLBAR)
    print(f"Saved: {OUT_TOOLBAR}")

    # Screenshot 2 — type "demo" into the search field. Writing to the
    # StringField model triggers the value-changed dispatch which
    # schedules the debounced fire; we then drive a handful of frames so
    # the call_later deadline passes and the handler lands.
    widget._search_field._field.model.set_value("demo")
    await _drive(30)
    uitesting.capture_screenshot(OUT_SEARCH)
    print(f"Saved: {OUT_SEARCH}")

    # Screenshot 3 — clear the search, then toggle the USD filter on.
    # The filter button's MenuItem would normally be checked by the user;
    # we drive :meth:`FilterButton._on_item_toggled` directly so the
    # screenshot captures the filter-only result without needing to pop
    # the dropdown (which would obscure the detail pane).
    widget._search_field._on_clear()
    widget._filter_button._on_item_toggled(AssetCategory.USD, True)
    # Mirror the menu-item state so the dropdown (if the designer opens
    # it manually) reads the same checked status.
    widget._filter_button._menu_items[AssetCategory.USD].checked = True
    await _drive(20)
    uitesting.capture_screenshot(OUT_FILTER)
    print(f"Saved: {OUT_FILTER}")

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
    ui.init("OvGear Step 28 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

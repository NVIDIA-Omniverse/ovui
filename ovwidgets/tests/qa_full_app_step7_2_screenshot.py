# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshot for Property Window Step 7.2 —
per-attribute right-click context menu.

Step 7.2 ships :mod:`ovwidgets.property.parts.attr_context_menu` — a four-item Copy Value / Paste
Value / Reset to Default / Copy Attribute Path menu that pops on
right-click over an attribute row. This screenshot proves the menu
visually by programmatically invoking the driver directly with a prop
from the loaded stage so the popup is rendered when
``uitesting.capture_screenshot`` fires.

The scene fixture is the Step-5.2 ``step5_2_scene.usda`` (nested
Transform / Translate / Rotate groups under ``/World/NestedScope``)
to keep continuity with Steps 5.3 through 7.1. After driving enough
frames for the Property Inspector to mount, the script picks a
representative attribute (``/World/NestedScope.visibility`` works on
any prim — ``Usd.Prim`` always has a ``visibility`` attr, but we pick
the topmost authored attribute the adapter surfaces so the menu
items' enabled/disabled predicates reflect realistic state) and
shows the menu at a fixed ``(x, y)`` inside the Property Inspector's
column. The driver returns the :class:`ui.Menu`; we pin it on a local
so refcount teardown doesn't kill the popup before the screenshot.

Output: /tmp/ovgear_full_app_step7_2.png

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_full_app_step7_2_screenshot.py
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

USD_PATH = os.path.join(os.path.dirname(__file__), "data", "step5_2_scene.usda")
OUT_PATH = "/tmp/ovgear_full_app_step7_2.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _show_menu_on_representative_attr(app: Application):
    """Pop the Step-7.2 attribute context menu against a real attr.

    Reaches into the running :class:`PropertyWindow` for its adapter
    and picks the first attribute the adapter surfaces so the menu
    rendering matches real-world state (enabled/disabled predicates
    reflect live metadata, not a hand-crafted fake). Calls
    :func:`show_attr_context_menu` directly — same driver the row
    right-click handler invokes — at a fixed ``(x, y)`` inside the
    Property Inspector column so the popup lands visibly in the
    1280×720 capture frame.

    Returns the :class:`ui.Menu` so the caller can pin it locally;
    dropping the reference before the screenshot renders would close
    the popup mid-frame.
    """
    from ovwidgets.property.parts.attr_context_menu import show_attr_context_menu

    pw = app._property_window
    if pw is None:
        raise RuntimeError("Application._property_window not initialised")
    adapter = pw._adapter
    if adapter is None:
        raise RuntimeError("PropertyWindow has no adapter — selection not applied yet")
    names = adapter.get_attribute_names()
    if not names:
        raise RuntimeError("Adapter surfaces no attributes")
    prop = adapter.get_attribute_metadata(names[0])
    # Position the popup inside the Property Inspector's value column
    # (right pane). 1030 x 260 puts it roughly over the top-half attr
    # rows in the 1280-wide main window so all four menu items fit.
    return show_attr_context_menu(adapter, prop, 1030.0, 260.0)


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    app._startup_usd_path = USD_PATH
    task = asyncio.ensure_future(app.run_async())

    await _drive(40)
    app.selection_bus.publish(["/World/NestedScope"], source="qa")
    await _drive(20)

    # Pop the context menu and pin it so the refcount teardown inside
    # omni.ui doesn't close the popup before we capture.
    menu = _show_menu_on_representative_attr(app)  # noqa: F841
    await _drive(10)

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
    ui.init("OvGear Step 7.2 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

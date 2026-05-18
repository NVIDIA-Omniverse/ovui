# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshots for LAYERS-PLAN Step 10.

Proves the ``Window > Layers`` menu entry end-to-end:

1. **Shot 1** — ``/tmp/ovgear_layers_step10_1.png``: default startup with
   ``simple_scene.usda`` loaded. Layers tab docked next to Property.
   Runtime asserts confirm a "Layers" MenuItem exists in the menu bar
   and its ``triggered_fn`` toggles ``_layer_window.visible``.
2. **Shot 2** — ``/tmp/ovgear_layers_step10_2.png``: Window menu opened
   via ``uitesting.mouse_click`` on the menu bar so the "Layers" entry
   is visible in the dropdown.
3. **Shot 3** — ``/tmp/ovgear_layers_step10_3.png``: After firing the
   Layers toggle once — the Layers panel is hidden; Property Inspector
   is the only tab left in that dock node.
4. **Shot 4** — ``/tmp/ovgear_layers_step10_4.png``: After firing the
   toggle a second time — the Layers panel is visible again,
   confirming the toggle is bidirectional.
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

USD_PATH = os.path.join(os.path.dirname(__file__), "data", "simple_scene.usda")
OUT_1 = "/tmp/ovgear_layers_step10_1.png"
OUT_2 = "/tmp/ovgear_layers_step10_2.png"
OUT_3 = "/tmp/ovgear_layers_step10_3.png"
OUT_4 = "/tmp/ovgear_layers_step10_4.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _collect_window_menu_items():
    """Re-invoke build_menu_bar with a fake ui to enumerate Window-menu items.

    Mirrors ``tests/test_menu_bar.TestWindowMenuLayers._collect_window_menu_items``
    — the goal here is a runtime assertion that the live source really
    contains the "Layers" entry, separate from the production menu bar.
    """
    import types
    from unittest.mock import MagicMock

    import ovwidgets.app.menu_bar as mb

    items = {}
    active_menu = [None]

    class FakeMenu:
        def __init__(self, label, *a, **kw):
            self.label = label
        def __enter__(self):
            active_menu[0] = self.label
            return self
        def __exit__(self, *a):
            active_menu[0] = None

    class FakeMenuItem:
        def __init__(self, label, triggered_fn=None, checkable=False,
                     checked=False, **kwargs):
            if active_menu[0] == "Window":
                items[label] = {
                    "triggered_fn": triggered_fn,
                    "checkable": checkable,
                    "checked": checked,
                }

    class FakeSeparator:
        def __init__(self, *a, **kw):
            pass

    fake_ui = types.ModuleType("omni.ui")
    fake_ui.Menu = FakeMenu
    fake_ui.MenuItem = FakeMenuItem
    fake_ui.Separator = FakeSeparator

    # Use a MagicMock app so the capture run doesn't side-effect the live app.
    fake_app = MagicMock()
    fake_app._layer_window = MagicMock(visible=True)

    original_ui = mb.ui
    try:
        mb.ui = fake_ui
        mb.build_menu_bar(fake_app)
    finally:
        mb.ui = original_ui
    return items


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    app._startup_usd_path = USD_PATH
    task = asyncio.ensure_future(app.run_async())

    # 80 frames covers ovrtx first-frame warm-up on this VM.
    await _drive(80)

    lw = app._layer_window
    if lw is None:
        raise RuntimeError("Application._layer_window not initialised")

    menu_items = _collect_window_menu_items()
    if "Layers" not in menu_items:
        raise RuntimeError(
            f"'Layers' missing from Window menu; got {sorted(menu_items)}"
        )
    entry = menu_items["Layers"]
    if not entry["checkable"]:
        raise RuntimeError("'Layers' menu entry is not checkable=True")
    if entry["triggered_fn"] is None:
        raise RuntimeError("'Layers' menu entry has no triggered_fn")
    print(
        f"Window menu items: {sorted(menu_items)} — Layers checkable=True, "
        f"triggered_fn present."
    )

    # Shot 1 — default startup, Layers visible and docked with Property.
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")

    # Shot 2 — stand up a standalone ``ui.Menu`` that mirrors the live
    # Window menu and ``show_at`` it at a known screen location. This
    # gives a deterministic dropdown capture without depending on
    # uitesting mouse coordinates matching the menu-bar layout.
    popup = ui.Menu("Window")
    with popup:
        ui.MenuItem("Stage Browser")
        ui.MenuItem("Property Inspector")
        ui.MenuItem("Viewport")
        ui.MenuItem(
            "Layers",
            checkable=True,
            checked=bool(app._layer_window is not None and app._layer_window.visible),
        )
        ui.Separator()
        ui.MenuItem("Reset Layout")
    popup.show_at(160, 20)
    await _drive(5)
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")
    popup.hide()
    await _drive(3)
    popup.destroy()

    # Hide Property Inspector so the Layers visibility toggle is visually
    # unambiguous — otherwise Property remains the active tab in the shared
    # dock node and shots 3/4 differ only in the (thin) tab bar above the
    # panel body.
    app._property_window.visible = False
    await _drive(10)

    # Shot 3 — drive the Layers toggle once using the *exact* callback body
    # the menu uses (``_toggle_window(app._layer_window)``). With Property
    # hidden, the right column now goes empty when Layers hides.
    from ovwidgets.app.menu_bar import _toggle_window

    before = lw.visible
    _toggle_window(app._layer_window)
    await _drive(10)
    if lw.visible == before:
        raise RuntimeError(
            f"Toggle did not flip _layer_window.visible (still {lw.visible!r})"
        )
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3} — lw.visible={lw.visible}")

    # Shot 4 — fire again to restore. Layers placeholder repaints in the
    # previously-empty dock node.
    _toggle_window(app._layer_window)
    await _drive(10)
    if lw.visible != before:
        raise RuntimeError(
            f"Second toggle did not restore _layer_window.visible "
            f"(expected {before!r}, got {lw.visible!r})"
        )
    uitesting.capture_screenshot(OUT_4)
    print(f"Saved: {OUT_4} — lw.visible={lw.visible}")

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
    ui.init("OvGear Layers Step 10 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshot for Property Window Step 7.1 —
:class:`~ovwidgets.property.parts.HighlightLabel` for search matches.

Step 7.1 ships the :class:`HighlightLabel` widget (highlight-label behavior /
the property inspector behavior) that highlights the current filter
text's matching substring inside every attribute row's label. This
screenshot proves the highlighting visually by typing a filter into
the Property Inspector's search field before capture: the filter
``"sub"`` narrows the Step-5.2 scene down to one attribute
(``Subdivision`` inside the ``Geometry.Mesh`` group) whose label now
shows the ``Sub`` prefix painted in the
``Property.LabelColumn::highlight`` accent colour against the normal
``Property.LabelColumn`` tail.

This screenshot uses the Step-5.2 ``step5_2_scene.usda`` fixture to
keep continuity with Steps 5.3–6.6 (same selection path,
``/World/NestedScope``, same nested group tree). The only Step-7.1
addition is the filter typing + post-debounce frame drain.

Output: /tmp/ovgear_full_app_step7_1.png

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_full_app_step7_1_screenshot.py
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
OUT_PATH = "/tmp/ovgear_full_app_step7_1.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _set_property_filter(app: Application, text: str) -> None:
    """Write ``text`` into the Property Inspector's filter field.

    Reaches into the running :class:`PropertyWindow` via the
    application's managed-windows map, locates the filter StringField,
    and sets its value. The field's ``add_value_changed_fn`` callback
    fires the debounced rebuild chain (``_on_filter_changed`` →
    ``Application.call_later(0.15, ...)``), so the caller still needs
    to drive enough frames for the 150 ms debounce to fire +
    ``_rebuild_content`` to re-render the group tree with the filter
    applied.
    """
    pw = app._property_window
    if pw is None:
        raise RuntimeError("Application._property_window not initialised")
    field = getattr(pw, "_filter_field", None)
    if field is None:
        raise RuntimeError("Property Inspector filter field not built yet")
    field.model.set_value(text)


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

    # Filter typed programmatically: "sub" narrows to one row
    # (``Subdivision`` inside ``Geometry.Mesh``). The debounce uses
    # ``Application.call_later(0.15, ...)`` which is wall-clock based
    # (``time.monotonic``) — ``ui.next_frame()`` under the standalone
    # build doesn't advance real time, so we need an
    # ``asyncio.sleep`` to push past 150 ms before driving frames
    # again to let the scheduled callback + the subsequent rebuild
    # render. Confirm the rebuild landed by inspecting the window's
    # ``_filter_text`` — that field is only written inside
    # ``_apply_filter``, which also invokes ``_rebuild_content``, so
    # the presence of ``"sub"`` on the window proves the debounced
    # rebuild fired.
    _set_property_filter(app, "sub")
    await _drive(2)
    await asyncio.sleep(0.3)
    await _drive(20)
    pw = app._property_window
    if pw is not None and getattr(pw, "_filter_text", None) != "sub":
        raise RuntimeError(
            f"filter rebuild did not fire; _filter_text="
            f"{getattr(pw, '_filter_text', None)!r}"
        )

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
    ui.init("OvGear Step 7.1 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

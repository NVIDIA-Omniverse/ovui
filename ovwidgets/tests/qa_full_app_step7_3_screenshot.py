# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshot for Property Window Step 7.3 —
:class:`~ovwidgets.property.widget.ScrollPreserver`.

Step 7.3 ships the :class:`ScrollPreserver` helper (property widget stack behavior,
the property inspector behavior, the property inspector step 7.3) that
saves :attr:`ui.ScrollingFrame.scroll_y` before
:meth:`PropertyWindow._rebuild_content` tears down the content stack
and restores it through a two-frame deferred
:meth:`Application.call_later` chain. The restore preserves the saved
position when the new payload's
:meth:`~ovwidgets.property.payload.PropertyPayload.get_scheme` matches the
prior payload's; the scroll resets to 0 on a scheme change.

This screenshot proves the preservation visually: the Step-5.2
``step5_2_scene.usda`` scene's ``/World/NestedScope`` surfaces enough
nested attribute groups (``Transform.Translate``, ``Transform.Rotate``,
``Geometry.Mesh.Subdivision``, etc.) that the Property Inspector
overflows the scrollable viewport. The QA flow:

1. Publish ``/World/NestedScope`` through the selection bus. The
   Property Inspector rebuilds with the full nested-group tree.
2. Write a non-zero ``scroll_y`` on the inspector's
   :attr:`_scroll_frame` (~100 px so rows from the second screenful
   are visible).
3. Force a rebuild (:meth:`PropertyWindow._rebuild_content`) — same
   selection + same scheme, so the preserver's preserve branch fires.
4. Drive enough frames + the two :meth:`Application.call_later` ticks
   for the deferred scroll restore to land before
   :meth:`uitesting.capture_screenshot` fires.

The captured frame shows the Property Inspector scrolled past the
first screenful: the ``Transform`` header is above the visible
viewport, and rows from later groups sit at the top. If the
preserver regressed, the rebuild would have snapped scroll_y back to
0 and the ``Transform`` header would have stayed at the top of the
column.

Output: /tmp/ovgear_full_app_step7_3.png

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_full_app_step7_3_screenshot.py
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
OUT_PATH = "/tmp/ovgear_full_app_step7_3.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _force_scroll_and_rebuild(app: Application, scroll_y: float) -> None:
    """Seed a non-zero ``scroll_y`` on the inspector frame, then rebuild.

    Reaches into the running :class:`PropertyWindow`, writes ``scroll_y``
    directly on its :class:`ui.ScrollingFrame`, and calls
    :meth:`_rebuild_content` — same code path as a real selection-
    triggered rebuild. The window's scheme does not change between
    calls (same selection, same adapter), so the Step-7.3
    :class:`ScrollPreserver` takes the preserve branch: saves the
    current scroll_y before clearing, schedules a two-frame deferred
    restore, and the deferred write lands the saved value back on the
    frame.
    """
    pw = app._property_window
    if pw is None:
        raise RuntimeError("Application._property_window not initialised")
    frame = getattr(pw, "_scroll_frame", None)
    if frame is None:
        raise RuntimeError("PropertyWindow._scroll_frame not built yet")
    frame.scroll_y = scroll_y
    pw._rebuild_content()


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

    # Seed a non-zero scroll position then force a rebuild on the same
    # scheme so the Step-7.3 preserver's preserve branch fires. The
    # two-frame deferred restore lands the saved scroll_y back onto
    # the frame after the two ``Application.call_later(0.0, ...)``
    # ticks the preserver chains internally.
    _force_scroll_and_rebuild(app, scroll_y=120.0)
    # Drive 10 frames: the call_later handles sit on
    # ``Application._pending_callbacks`` and fire inside
    # ``Application._on_frame_update``. The two preserver ticks + the
    # rebuild content + layout recomputation all need to complete
    # before the capture so the final screenshot reflects the restored
    # state rather than the post-clear ``scroll_y = 0`` intermediate.
    await _drive(10)

    pw = app._property_window
    if pw is not None and pw._scroll_frame is not None:
        restored = float(pw._scroll_frame.scroll_y)
        # A regression would show 0; assert non-zero so a broken
        # preserver loudly fails the screenshot script rather than
        # silently capturing a zero-scroll frame.
        if restored < 1.0:
            raise RuntimeError(
                f"ScrollPreserver did not restore scroll; scroll_y={restored}"
            )
        print(f"Restored scroll_y = {restored}")

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
    ui.init("OvGear Step 7.3 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

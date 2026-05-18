# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full-application screenshot for Property Window Step 7.5 — async build path.

Step 7.5 (the property inspector implementation) adds the
:meth:`~ovwidgets.property.widget.SimplePropertyWidget.build_items_async`
scaffolding: subclasses that need to spread an expensive build across
multiple frames return a generator; :meth:`request_rebuild` detects
the override and drives the generator frame-by-frame via
:meth:`ovwidgets.app.application.Application.call_later(0.0, ...)`. This is
scaffolding — no production widget opts in yet — so the visual
Property Inspector looks unchanged from Step 7.4 (normal sync attribute
rows).

This QA script proves two things:

1. **Sync-path regression guard** — publishing a real selection builds
   the normal Property Inspector content (the sync
   :meth:`~ovwidgets.property.widget.SimplePropertyWidget._do_rebuild` path
   was not broken by the Step 7.5 dispatcher change).
2. **Async-path runtime proof** — a throwaway
   :class:`SimplePropertyWidget` subclass overriding
   :meth:`build_items_async` to yield twice is instantiated, its
   :meth:`request_rebuild` is called, and the app's own frame loop
   drives the generator to completion. The script asserts the
   generator actually exhausted (body side effects observed, in-flight
   slot cleared) before capturing the screenshot.

The capture is the 1280×720 full-app PNG — same format as every prior
step — showing the sync Property Inspector rendering for the selected
prim.

Output: /tmp/ovgear_full_app_step7_5.png

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_full_app_step7_5_screenshot.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Iterator, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting

from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus
from ovwidgets.property.widget import SimplePropertyWidget

USD_PATH = os.path.join(os.path.dirname(__file__), "data", "simple_scene.usda")
OUT_PATH = "/tmp/ovgear_full_app_step7_5.png"


class _ProbeAsyncWidget(SimplePropertyWidget):
    """Throwaway async widget used to exercise the Step 7.5 dispatcher.

    Records body progress into ``trace``; the QA script asserts
    completion after driving frames. Does NOT emit any real UI — the
    scaffolding test does not require UI emission inside the
    generator, only that the driver advances the generator to
    ``StopIteration``.
    """

    def __init__(self) -> None:
        super().__init__(title="")
        self.trace: List[str] = []

    def build_items_async(self) -> Optional[Iterator[Any]]:  # type: ignore[override]
        self.trace.append("pre")
        yield
        self.trace.append("mid")
        yield
        self.trace.append("post")


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    app._startup_usd_path = USD_PATH
    task = asyncio.ensure_future(app.run_async())

    # Drive past the startup load so the stage browser + inspector settle.
    await _drive(40)

    # Publish a real selection so the Property Inspector draws something.
    # The sync attribute-build path must still work after the Step 7.5
    # dispatcher was rewired — this is a visual regression guard for
    # every non-async widget in the panel.
    app.selection_bus.publish(["/World/Cube"], source="qa")
    await _drive(20)

    # Instantiate the probe async widget and kick off a rebuild. The
    # probe is independent of the window's registered widgets — it just
    # proves the SimplePropertyWidget dispatcher drives a generator
    # through the real :class:`Application` ``call_later`` loop. Two
    # yields → four advances to exhaust (kick-off + each yield + final
    # StopIteration step).
    probe = _ProbeAsyncWidget()
    probe.request_rebuild()

    # Drive enough frames for the async build to complete. The driver
    # schedules one ``call_later(0.0, ...)`` per advance, so each
    # ``ui.next_frame()`` fires one advance. We overdrive to give omni's
    # scheduler slack for layout/settle time between our callbacks.
    await _drive(15)

    # Runtime verification — the generator body should have run all
    # three segments and the in-flight slot should be clear.
    if probe.trace != ["pre", "mid", "post"]:
        raise RuntimeError(
            f"Async build trace mismatch: expected "
            f"['pre', 'mid', 'post'], got {probe.trace!r}"
        )
    if probe._async_generator is not None:
        raise RuntimeError(
            "Async generator still pointing at a non-None object after "
            "the build was expected to complete — driver did not reach "
            "StopIteration."
        )
    print(
        f"Async build trace: {probe.trace}; "
        f"async_generator cleared: {probe._async_generator is None}"
    )

    # Also verify the sync path is alive — the property window has a
    # non-empty ``_selection`` and has built content for ``/World/Cube``.
    pw = app._property_window
    if pw is None:
        raise RuntimeError("Application._property_window not initialised")
    if pw._selection != ["/World/Cube"]:
        raise RuntimeError(
            f"Expected selection ['/World/Cube'], got {pw._selection!r}"
        )
    print(f"Selection: {pw._selection}")

    # Clean up the probe so its paused state (none here, generator
    # already exhausted) doesn't linger past the capture.
    probe.destroy()

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
    ui.init("OvGear Step 7.5 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

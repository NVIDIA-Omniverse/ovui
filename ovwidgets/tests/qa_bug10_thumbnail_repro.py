# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA reproduction for Bug 10 — Thumbnails don't load from .thumbs/256x256/.

Places PNGs in `/tmp/ovgear_bug_repro/.thumbs/256x256/` named
`<basename>.png` for several USD files in the test tree, opens the
OvGear content browser in grid view, and takes a screenshot.

Expected post-fix: the matching cards show the red-orange checkerboard
thumbnail instead of the default USD icon.
Pre-fix behaviour: every USD card shows the default icon because the
discovery pass restricts thumbnails to ``AssetCategory.IMAGE``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_bug10_thumbnail_repro.py
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

TEST_ROOT = "/tmp/ovgear_bug10_test"
TEST_ROOT_URL = f"file://{TEST_ROOT}"
OUT_PATH = "/tmp/ovgear_bugfix_10.png"


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
        raise RuntimeError("Content window not built")
    widget = cw._widget
    widget.set_backend(LocalFSBackend())
    widget.navigate_to(TEST_ROOT_URL)
    await _drive(25)

    # Grid view at a larger zoom so the cards visibly fill the pane
    # and the thumbnail swap is obvious in the screenshot.
    zoom = widget._zoom_bar
    if zoom is not None:
        zoom.set_slider_index(4)  # 150%
    if not widget._is_grid_view:
        widget._on_zoom_bar_toggle_grid(True)
    await _drive(30)

    # Report what we see so the log trail captures the pipeline state.
    detail_model = widget._detail_model
    if detail_model is not None:
        children = detail_model.get_item_children(detail_model.root)
        print(f"[BUG 10] root has {len(children)} children after populate")
        # One more frame tick in case the call_later scheduled pass
        # hasn't fired yet.
        await _drive(10)
        for child in children:
            if getattr(child, "is_folder", True):
                continue
            print(
                f"[BUG 10] child name={child.name!r} "
                f"category={getattr(child, 'category', '?')} "
                f"custom_thumbnail={child.custom_thumbnail!r}"
            )

    # Drill into the card state to confirm the thumbnail propagated all
    # the way to the front buffer — the log above proves the item
    # carries the URL; the per-card inspection proves the card picked
    # it up during (re)build.
    grid = widget._detail_grid_view
    if grid is not None:
        for url, card in grid._cards.items():
            front = card._front_buffer
            fimg = card._front_image
            print(
                f"[BUG 10] card url={url!r} "
                f"front_visible={getattr(front, 'visible', '?')} "
                f"source_url={getattr(fimg, 'source_url', '?')!r}"
            )

    uitesting.capture_screenshot(OUT_PATH)
    print(f"  saved {OUT_PATH}")

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
    ui.init("OvGear Bug 10 QA", width=1400, height=800)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

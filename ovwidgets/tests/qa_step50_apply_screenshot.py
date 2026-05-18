# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Content Browser Steps 50-51 — Apply handler + selection autofill.

Captures a screenshot of :class:`FilePickerDialog` with a file single-
clicked in the detail grid: its name has landed in the :class:`FileBar`'s
filename field via the Step-51 ``on_selection_changed`` callback, and
the Apply button is enabled (direct visual proof of the Step-50 Apply
contract + Step-51 selection autofill wired together).

Saves to ``/tmp/ovgear_step50_1_apply.png``.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_step50_apply_screenshot.py
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
from ovwidgets.common.selection import SelectionBus
from ovwidgets.content import FilePickerDialog

OUT_PATH = "/tmp/ovgear_step50_1_apply.png"


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    # Wait for the main window panels to be built + docked.
    await _drive(40)

    backend = MockBackend()
    captured = []

    def _on_apply(filename: str, dirname: str) -> None:
        captured.append(("apply", filename, dirname))

    def _on_cancel(filename: str, dirname: str) -> None:
        captured.append(("cancel", filename, dirname))

    dialog = FilePickerDialog(
        title="Open File",
        backend=backend,
        start_url="mock://Home/Documents/Projects",
        apply_button_label="Open",
        cancel_button_label="Cancel",
        on_apply=_on_apply,
        on_cancel=_on_cancel,
        should_validate=True,
        file_extension_types=[
            ("*.usd, *.usda, *.usdc, *.usdz", "USD Files"),
            ("*.*", "All files"),
        ],
    )
    dialog.show()

    # Let the modal + embedded widget + FileBar render.
    await _drive(20)

    # Step 51 — drive the grid selection + fire the post-click hook to
    # populate the FileBar with the selected filename. This is the
    # direct equivalent of a user single-click on the "demo.usda" card.
    detail_model = dialog.widget.get_detail_model()
    children = detail_model.get_item_children(detail_model.root)
    demo_usda = next(c for c in children if c.name == "demo.usda")
    dialog.widget._detail_grid_view.set_selection([demo_usda])
    dialog.widget._on_grid_click(demo_usda, 0, 0)

    # Let the FileBar re-render with the filename + the Apply-enabled
    # affordance repaint before capture.
    await _drive(10)

    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")
    print(f"FileBar filename after click: {dialog.get_filename()!r}")
    print(f"Apply enabled: {dialog._file_bar.apply_enabled}")

    await _drive(2)

    dialog.destroy()

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
    ui.init("OvGear Step 50 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())

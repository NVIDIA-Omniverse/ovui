# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification script for Step 17 — Stage Browser selection.

Usage:
    source <path-to-ovui>/_venv/bin/activate
    DISPLAY=:99 python tests/verify_step17.py --screenshot
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import omni.ui as ui

from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.stage.stage_widget import StageWidget

SCREENSHOT_PATH = "/tmp/ovgear_step17_selection.png"
_SCREENSHOT = "--screenshot" in sys.argv


async def run():
    write_split_ini()
    ui.init("OvGear Step 17 — Selection", width=900, height=700)
    apply_global_styles()
    set_theme("default")

    adapter = MockStageAdapter()
    stage_widget = StageWidget(adapter=adapter)
    stage_widget._window.position_x = 10
    stage_widget._window.position_y = 30
    stage_widget._window.width = 400
    stage_widget._window.height = 620

    # Wait for initial render
    from omni.ui import testing
    await testing.wait_frames(5)

    # Replace tree view with keep_expanded=True to show all nodes
    model = stage_widget._model
    delegate = stage_widget._delegate

    # Rebuild UI with expanded tree
    with stage_widget._window.frame:
        with ui.VStack():
            stage_widget._tree_view = ui.TreeView(
                model,
                delegate=delegate,
                root_visible=True,
                header_visible=True,
                keep_expanded=True,
                column_widths=[ui.Fraction(2), ui.Fraction(1), 32],
            )
            stage_widget._tree_view.set_selection_changed_fn(
                stage_widget._on_tree_selection_changed
            )

    await testing.wait_frames(5)

    # Select World and Geometry to demonstrate multi-select
    root = model.get_item_children(None)[0]
    children = model.get_item_children(root)
    geometry = children[0]

    stage_widget._tree_view.selection = [root, geometry]
    stage_widget._model._selected_items = [root, geometry]

    await testing.wait_frames(10)

    if _SCREENSHOT:
        testing.capture_screenshot(SCREENSHOT_PATH)
        await testing.wait_frames(2)
        print(f"Screenshot saved to {SCREENSHOT_PATH}")

    print(f"Selected items: {model.get_selected_paths()}")
    print(f"Bus snapshot: {SelectionBus.instance().get_snapshot().paths()}")

    stage_widget.destroy()
    ui.shutdown()


ui.run(run())

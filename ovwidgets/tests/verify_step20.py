# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 20 verification script — shows inline rename StringField in action."""

import sys

sys.path.insert(0, "<path-to-ovgear>")
sys.path.insert(0, "<path-to-ovui>/_venv/lib/python3.10/site-packages")

import omni.ui as ui

from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.stage.hierarchy_model import HierarchyModel
from ovwidgets.stage.rename_controller import RenameController
from ovwidgets.stage.stage_delegate import StageDelegate
from ovwidgets.stage.style import STAGE_STYLES


def main():
    from ovwidgets.app.layout import write_split_ini
    write_split_ini()
    ui.init("Step 20 — Inline Rename", width=400, height=500)
    apply_global_styles()
    set_theme("dark")

    # Combined STAGE_STYLES + RenameField style
    styles = dict(STAGE_STYLES)
    styles["Stage.RenameField"] = {
        "background_color": 0xFF2A3A4A,
        "border_color": 0xFFFFA040,
        "border_width": 1,
        "border_radius": 2,
    }

    win = ui.Window("Stage Browser — Step 20", width=380, height=460)
    ui.style.default = {**ui.style.default, **styles}

    adapter = MockStageAdapter()
    model = HierarchyModel(adapter)
    delegate = StageDelegate()
    rename_ctrl = RenameController(adapter, model, delegate)
    delegate.set_rename_controller(rename_ctrl)

    with win.frame:
        with ui.VStack():
            ui.Label(
                "Step 20: inline rename (StringField replacing label)",
                height=24,
                style={"font_size": 13, "color": 0xFFAAAAAA},
            )
            tree_view = ui.TreeView(
                model,
                delegate=delegate,
                root_visible=True,
                header_visible=True,
                keep_expanded=True,
                column_widths=[ui.Fraction(2), ui.Fraction(1), 32],
            )

    # Load children so we have items in path_cache
    root = model.get_item_children(None)[0]
    children = model.get_item_children(root)

    # Start rename on "Geometry" (first child)
    geometry = children[0]
    model._selected_items = [geometry]
    rename_ctrl.request_rename_f2(geometry)

    async def take_screenshot():
        import omni.ui as ui2
        from omni.ui import testing
        for _ in range(5):
            await ui2.next_frame()
        testing.capture_screenshot("/tmp/ovgear_step20_rename.png")
        await ui2.next_frame()
        ui2.shutdown()

    ui.run(take_screenshot())


if __name__ == "__main__":
    main()

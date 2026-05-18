# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Step 19: Filter bar with filtered tree."""

import sys

import omni.ui as ui

from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.stage.hierarchy_model import HierarchyModel
from ovwidgets.stage.stage_delegate import StageDelegate


async def main():
    window = ui.Window("Step 19 — Filter Bar", width=340, height=480)
    with window.frame:
        with ui.VStack():
            # Filter bar
            with ui.HStack(height=28):
                ui.Spacer(width=4)
                ui.Label("Filter:", width=36)
                field = ui.StringField()
                ui.Spacer(width=4)

            # Tree
            adapter = MockStageAdapter()
            model = HierarchyModel(adapter)
            delegate = StageDelegate()

            # Apply filter "sphere"
            model.set_filter("sphere")

            tree = ui.TreeView(
                model,
                delegate=delegate,
                root_visible=True,
                header_visible=True,
                keep_expanded=True,
            )

    # Show what's visible after filter
    field.model.set_value("sphere")

    await ui.next_frame()
    await ui.next_frame()
    await ui.next_frame()

    window.position_x = 80
    window.position_y = 80

    await ui.next_frame()

    from omni.ui import testing
    testing.capture_screenshot("/tmp/ovgear_step19_filter.png")
    await ui.next_frame()

    print("Screenshot saved: /tmp/ovgear_step19_filter.png")
    sys.exit(0)


write_split_ini()
ui.init("OvGear Step 19 screenshot", width=520, height=560)
apply_global_styles()
ui.run(main())

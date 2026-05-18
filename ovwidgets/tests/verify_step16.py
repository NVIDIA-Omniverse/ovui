# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Step 16 — three-column Stage Browser.

Run:
    DISPLAY=:99 python tests/verify_step16.py --screenshot
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui

from ovwidgets.app.layout import write_split_ini

_SCREENSHOT = "--screenshot" in sys.argv
_PATH = "/tmp/ovgear_step16_columns.png"

write_split_ini()
ui.init("OvGear Step 16 Verify", width=500, height=560)

from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.stage.hierarchy_model import HierarchyModel
from ovwidgets.stage.stage_delegate import StageDelegate
from ovwidgets.stage.style import STAGE_STYLES

apply_global_styles()
set_theme("dark")
ui.style.default = {**ui.style.default, **STAGE_STYLES}

adapter = MockStageAdapter()
model = HierarchyModel(adapter)
delegate = StageDelegate()

win = ui.Window("Stage Browser", width=480, height=530)
win.position_x = 10
win.position_y = 10

with win.frame:
    with ui.VStack():
        ui.TreeView(
            model,
            delegate=delegate,
            root_visible=True,
            header_visible=True,
            keep_expanded=True,
            column_widths=[ui.Fraction(2), ui.Fraction(1), 32],
        )


async def _capture(path: str):
    from omni.ui import testing
    await testing.wait_frames(10)
    testing.capture_screenshot(path)
    print(f"Screenshot saved: {path}")
    ui.shutdown()


if __name__ == "__main__":
    if _SCREENSHOT:
        ui.run(_capture(_PATH))
    else:
        ui.run()

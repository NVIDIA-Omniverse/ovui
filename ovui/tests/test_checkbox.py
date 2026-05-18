# SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Standalone port of Kit's test_checkbox.py"""

from test_base import OmniUiTest
import omni.ui as ui
from omni.ui import color as cl


class TestCheckBox(OmniUiTest):
    """Testing ui.CheckBox"""

    async def test_general(self):
        """Testing general properties of ui.CheckBox"""
        window = await self.create_test_window()

        no_border_style = {
            "CheckBox": {
                "color": cl.black,
                "background_color": cl.white,
                "border_radius": 1,
            }
        }

        border_style = {
            "CheckBox": {
                "color": cl.black,
                "background_color": cl.white,
                "secondary_background_color": cl.blue,
                "border_radius": 1,
                "border_width": 2,
            }
        }

        checked_style = {
            "CheckBox": {
                "background_color": cl.white,
                "border_radius": 1,
            },
            "CheckBox:checked": {
                "color": cl.black,
                "background_color": cl.red,
                "border_radius": 2,
            }
        }

        with window.frame:
            with ui.VStack(height=0):
                # Simple check box
                ui.CheckBox().model.set_value(False)
                ui.CheckBox().model.set_value(True)

                # Styled check box no border
                ui.CheckBox(enabled=True, style=no_border_style).model.set_value(False)
                ui.CheckBox(enabled=True, style=no_border_style).model.set_value(True)

                # Styled check box with border
                ui.CheckBox(enabled=True, style=border_style).model.set_value(False)
                ui.CheckBox(enabled=True, style=border_style).model.set_value(True)

                # Styled check box with different style in checked state
                ui.CheckBox(enabled=True, style=checked_style).model.set_value(False)
                ui.CheckBox(enabled=True, style=checked_style).model.set_value(True)

        await self.finalize_test()

# SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Standalone port of Kit's test_rectangle.py"""

from test_base import OmniUiTest
import omni.ui as ui


class TestRectangle(OmniUiTest):
    """Testing ui.Rectangle"""

    async def test_general(self):
        """Testing general properties of ui.Rectangle"""
        window = await self.create_test_window()

        with window.frame:
            with ui.VStack():
                with ui.HStack():
                    ui.Rectangle()
                    ui.Rectangle(style={"background_color": 0xFFFF0000})
                    ui.Rectangle(style={"Rectangle": {"background_color": 0x66FF0000}})
                with ui.HStack():
                    ui.Rectangle(
                        style={"background_color": 0x0, "border_color": 0xFF00FFFF, "border_width": 1, "margin": 5}
                    )
                    ui.Rectangle(
                        style={
                            "background_color": 0x0,
                            "border_color": 0xFFFFFF00,
                            "border_width": 2,
                            "border_radius": 20,
                            "margin_width": 5,
                        }
                    )
                    ui.Rectangle(
                        style={
                            "background_color": 0xFF00FFFF,
                            "border_color": 0xFFFFFF00,
                            "border_width": 2,
                            "border_radius": 5,
                            "margin_height": 5,
                        }
                    )
                with ui.HStack():
                    ui.Rectangle(
                        style={
                            "background_color": 0xFF00FFFF,
                            "border_color": 0xFFFFFF00,
                            "border_width": 1,
                            "border_radius": 10,
                            "corner_flag": ui.CornerFlag.LEFT,
                        }
                    )
                    ui.Rectangle(
                        style={
                            "background_color": 0xFFFF00FF,
                            "border_color": 0xFF00FF00,
                            "border_width": 1,
                            "border_radius": 10,
                            "corner_flag": ui.CornerFlag.RIGHT,
                        }
                    )
                    ui.Rectangle(
                        style={
                            "background_color": 0xFFFFFF00,
                            "border_color": 0xFFFF0000,
                            "border_width": 1,
                            "border_radius": 10,
                            "corner_flag": ui.CornerFlag.TOP,
                        }
                    )
                    ui.Rectangle(
                        style={
                            "background_color": 0xFF666666,
                            "border_color": 0xFF0000FF,
                            "border_width": 1,
                            "border_radius": 10,
                            "corner_flag": ui.CornerFlag.BOTTOM,
                        }
                    )

        await self.finalize_test()

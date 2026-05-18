# SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Standalone port of Kit's test_field.py"""

from test_base import OmniUiTest
import omni.ui as ui


STYLE = {
    "Field": {
        "background_color": 0xFF000000,
        "color": 0xFFFFFFFF,
        "border_color": 0xFFFFFFFF,
        "background_selected_color": 0xFFFF6600,
        "border_width": 1,
        "border_radius": 0,
    }
}


class TestField(OmniUiTest):
    """Testing fields"""

    async def test_general(self):
        """Testing general properties of ui.StringField"""
        window = await self.create_test_window()

        with window.frame:
            with ui.VStack(height=0, style=STYLE, spacing=2):
                # Simple field
                ui.StringField()
                ui.StringField().model.set_value("Hello World")

        await self.finalize_test()

    async def test_focus(self):
        """Testing the ability to focus in ui.StringField"""
        window = await self.create_test_window()

        with window.frame:
            with ui.VStack(height=0, style=STYLE, spacing=2):
                ui.StringField()
                field = ui.StringField()

        field.model.set_value("Hello World")
        field.focus_keyboard()

        await self.next_frame()
        await self.next_frame()

        await self.finalize_test()

    async def test_defocus(self):
        """Testing the ability to defocus in ui.StringField"""
        window = await self.create_test_window()

        with window.frame:
            with ui.VStack(height=0, style=STYLE, spacing=2):
                ui.StringField()
                field = ui.StringField()

        field.model.set_value("Hello World")
        field.focus_keyboard()

        await self.next_frame()
        await self.next_frame()

        field.focus_keyboard(False)

        await self.next_frame()

        await self.finalize_test()

    async def test_change_when_editing(self):
        """Testing the ability to change value while editing in ui.StringField"""
        window = await self.create_test_window()

        with window.frame:
            with ui.VStack(height=0, style=STYLE, spacing=2):
                ui.StringField()
                field = ui.StringField()

        field.model.set_value("Hello World")
        field.focus_keyboard()

        await self.next_frame()
        await self.next_frame()

        field.model.set_value("Data Change")

        await self.next_frame()

        await self.finalize_test()

    async def test_multifield_resize(self):
        """Testing general properties of ui.StringField"""
        window = await self.create_test_window(256, 64)

        with window.frame:
            stack = ui.VStack(height=0, width=100, style=STYLE, spacing=2)
            with stack:
                ui.MultiFloatField(1.0, 1.0, 1.0)

        await self.next_frame()
        await self.next_frame()

        stack.width = ui.Fraction(1)

        await self.next_frame()
        await self.next_frame()

        await self.finalize_test()

    async def test_stringfield_text_resize(self):
        """Testing general properties of ui.StringField"""
        window = await self.create_test_window(256, 64)

        with window.frame:
            s1 = ui.StringField()

        s1.model.set_value("Test")
        await self.next_frame()
        await self.next_frame()
        s1.model.set_value("")
        await self.next_frame()
        await self.next_frame()
        s1.focus_keyboard()
        await self.next_frame()
        await self.next_frame()
        await self.finalize_test()

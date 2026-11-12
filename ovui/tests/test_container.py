# SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Standalone port of Kit's test_container.py"""

from test_base import OmniUiTest
import omni.ui as ui


class TestContainer(OmniUiTest):
    """Testing ui.Container"""

    async def test_context_manager(self):
        """Testing general properties of ui.Container"""
        window = await self.create_test_window()

        with window.frame as win_frame:
            with ui.VStack() as v_stack:
                with ui.Frame(width=0, height=0) as sub_frame:
                    ui.Label("Label in Frame")
        assert isinstance(win_frame, ui.Frame)
        assert isinstance(v_stack, ui.VStack)
        assert isinstance(sub_frame, ui.Frame)
        await self.finalize_test_no_image()

    async def test_add_child(self):
        window = await self.create_test_window()
        v_stack = ui.VStack()
        window.frame.add_child(v_stack)
        assert v_stack in ui.Inspector.get_children(window.frame)
        await self.finalize_test_no_image()

    async def test_clear(self):
        window = await self.create_test_window()
        with window.frame as win_frame:
            with ui.VStack() as v_stack:
                with ui.Frame(width=0, height=0) as sub_frame:
                    ui.Label("Label in Frame")
        v_stack.clear()
        assert len(ui.Inspector.get_children(v_stack)) == 0
        await self.finalize_test_no_image()

    async def test_percent_child_after_sibling_hidden(self):
        """A Percent child gets the new available width when a sibling is hidden"""
        window = await self.create_test_window(400, 200)
        with window.frame:
            with ui.HStack(spacing=40):
                left = ui.Rectangle(width=ui.Percent(50))
                middle = ui.Rectangle(width=ui.Fraction(1))
                right = ui.Rectangle(width=ui.Fraction(2))
        await self.wait_n_updates(3)
        self.assertEqual(left.computed_width, 156)

        middle.visible = False
        await self.wait_n_updates(3)
        self.assertEqual(left.computed_width, 176)
        self.assertEqual(right.computed_width, 176)
        await self.finalize_test_no_image()

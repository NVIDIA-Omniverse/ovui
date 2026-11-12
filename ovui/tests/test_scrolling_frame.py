# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from test_base import OmniUiTest
import omni.ui as ui
from omni.ui.testing import mouse_click


class TestScrollingFrame(OmniUiTest):
    async def test_scroll_range_in_zoomed_canvas(self):
        """A list in a zoomed-out CanvasFrame scrolls exactly to its last row, with no horizontal scrollbar"""
        window = await self.create_test_window(600, 600)

        # Mouse wheel zoom gives 0.49999997, not 0.5.
        with window.frame:
            with ui.CanvasFrame(zoom=0.49999997, pan_x=236.4, pan_y=278.6):
                with ui.VStack(width=0, height=0):
                    ui.Spacer(height=110)
                    scrolling_frame = ui.ScrollingFrame(width=250, height=200)
                    with scrolling_frame:
                        with ui.VStack(height=0):
                            for _ in range(15):
                                ui.Rectangle(height=30)

        await self.wait_n_updates(5)

        self.assertEqual(scrolling_frame.scroll_x_max, 0.0)
        self.assertAlmostEqual(scrolling_frame.scroll_y_max, 250.0, places=3)

        await self.finalize_test_no_image()

    async def test_clipped_frame_adds_no_scroll_range(self):
        """Rows hidden by a clipping Frame do not add scroll range"""
        window = await self.create_test_window()

        with window.frame:
            scrolling_frame = ui.ScrollingFrame(
                horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED
            )
            with scrolling_frame:
                with ui.VStack(height=0):
                    ui.Rectangle(height=50)
                    with ui.Frame(height=50, vertical_clipping=True):
                        ui.Rectangle(height=1000)
                    with ui.Frame(width=100, height=50, horizontal_clipping=True):
                        ui.Rectangle(width=1000)

        await self.wait_n_updates(5)

        self.assertEqual(scrolling_frame.scroll_x_max, 0.0)
        self.assertEqual(scrolling_frame.scroll_y_max, 0.0)

        await self.finalize_test_no_image()

    async def test_scroll_to_end_after_adding_rows(self):
        """Rows added in the same click as a scroll to the end are shown"""
        window = await self.create_test_window()

        def add_rows():
            with stack:
                for _ in range(10):
                    ui.Rectangle(height=50)
            scrolling_frame.scroll_y = 1e6

        with window.frame:
            with ui.VStack():
                ui.Button("Add", height=20, clicked_fn=add_rows)
                scrolling_frame = ui.ScrollingFrame()
                with scrolling_frame:
                    stack = ui.VStack(height=0)
                    with stack:
                        for _ in range(10):
                            ui.Rectangle(height=50)

        await self.wait_n_updates(5)
        await mouse_click(20, 10)
        await self.wait_n_updates(5)

        self.assertEqual(scrolling_frame.scroll_y, scrolling_frame.scroll_y_max)

        await self.finalize_test_no_image()

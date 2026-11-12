# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ui.VGrid and ui.HGrid with a zero column or row count."""

import math

from test_base import OmniUiTest
import omni.ui as ui


class TestGrid(OmniUiTest):
    async def test_vgrid_zero_column_count(self):
        # A zero column count used to divide by zero (SIGFPE) in the first layout.
        window = await self.create_test_window()
        with window.frame:
            with ui.VGrid(column_count=0, row_height=24, width=240, height=120) as grid:
                child = ui.Label("child", height=20)
        await self.wait_n_updates(8)
        self.assertEqual(grid.column_count, 0)
        self.assertTrue(math.isfinite(child.computed_height))
        self.assertGreaterEqual(child.computed_height, 0.0)
        await self.finalize_test_no_image()

    async def test_hgrid_zero_row_count(self):
        # A zero row count used to divide by zero (SIGFPE) in the first layout.
        window = await self.create_test_window()
        with window.frame:
            with ui.HGrid(row_count=0, column_width=24, width=240, height=120) as grid:
                child = ui.Label("child", width=20)
        await self.wait_n_updates(8)
        self.assertEqual(grid.row_count, 0)
        self.assertTrue(math.isfinite(child.computed_width))
        self.assertGreaterEqual(child.computed_width, 0.0)
        await self.finalize_test_no_image()

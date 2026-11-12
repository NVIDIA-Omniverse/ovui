# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Check plot geometry in the rendered framebuffer."""

import math
import tempfile
from pathlib import Path

from PIL import Image

import pytest
import omni.ui as ui
from test_base import OmniUiTest


@pytest.mark.requires_gl
class TestPlot(OmniUiTest):
    async def _plot(self, kind, values):
        window = await self.create_test_window(128, 64)
        with window.frame:
            plot = ui.Plot(kind, mode=ui.PlotMode.INTERACTIVE, sparkline=True,
                             style={"background_color": 0xFF000000, "color": 0xFF0000FF,
                                    "padding": 0, "border_width": 0})
        plot.set_data(*values)
        return plot

    async def _red_at(self, plot, x_fraction, y_fraction):
        await self.wait_n_updates(3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plot.png"
            assert ui._ui._schedule_screenshot(str(path))
            await self.wait_n_updates(2)
            assert ui._ui._poll_screenshot_done()
            with Image.open(path) as image:
                x = round(plot.screen_position_x + plot.computed_content_width * x_fraction)
                y = round(plot.screen_position_y + plot.computed_content_height * y_fraction)
                red, green, blue = image.convert("RGB").getpixel((x, y))
        return red > 200 and green < 30 and blue < 30

    async def test_xy_bars_use_zero_baseline(self):
        plot = await self._plot(ui.PlotType.BARS, [])
        plot.set_xy_data([(2, -2), (8, 2)])
        plot.set_axis_limits(0, 10, -2, 2)
        assert await self._red_at(plot, 0.2, 0.75)
        assert not await self._red_at(plot, 0.2, 0.25)
        assert await self._red_at(plot, 0.8, 0.25)
        assert not await self._red_at(plot, 0.8, 0.75)

    async def test_histogram_counts_and_upper_edge(self):
        # Four Sturges bins: counts 3, 2, 0, 1. The maximum belongs in the last bin.
        plot = await self._plot(ui.PlotType.HISTOGRAM, [0, 0, 0, 1, 1, 3])
        plot.set_axis_limits(0, 3, 0, 3)
        assert await self._red_at(plot, 0.125, 0.2)
        assert not await self._red_at(plot, 0.375, 0.2)
        assert await self._red_at(plot, 0.375, 0.5)
        assert not await self._red_at(plot, 0.625, 0.8)
        assert await self._red_at(plot, 0.875, 0.8)

    async def test_equal_histogram_keeps_zero_width_bin(self):
        plot = await self._plot(ui.PlotType.HISTOGRAM, [5.0] * 8)
        plot.set_axis_limits(4.5, 5.5, 0, 8)
        assert await self._red_at(plot, 0.5, 0.1)
        assert not await self._red_at(plot, 0.525, 0.5)
        assert not await self._red_at(plot, 0.475, 0.5)

    async def test_nonfinite_sample_breaks_line(self):
        plot = await self._plot(ui.PlotType.LINE, [1, math.nan, 1])
        plot.set_axis_limits(0, 2, 0, 2)
        assert not await self._red_at(plot, 0.5, 0.5)
        plot.set_data(1, 1, 1)
        assert await self._red_at(plot, 0.5, 0.5)

    async def test_xy_samples_keep_time_precision(self):
        # Float storage would round base + 2 to base and move the first bar.
        base = 1.0e8
        plot = await self._plot(ui.PlotType.BARS, [])
        plot.set_xy_data([(base + 2, -2), (base + 8, 2)])
        plot.set_axis_limits(base, base + 10, -2, 2)
        assert await self._red_at(plot, 0.2, 0.75)
        assert not await self._red_at(plot, 0.2, 0.25)
        assert await self._red_at(plot, 0.8, 0.25)

    async def test_mode_switch_keeps_histogram_data(self):
        window = await self.create_test_window(128, 64)
        with window.frame:
            plot = ui.Plot(ui.Type.HISTOGRAM, 0.0, 2.0, 1.0, 1.0, 1.0,
                           sparkline=True,
                           style={"background_color": 0xFF000000, "color": 0xFF0000FF,
                                  "padding": 0, "border_width": 0})
        # Legacy bars show each value. Interactive bins show the sample count.
        assert await self._red_at(plot, 0.5, 0.75)
        assert not await self._red_at(plot, 0.5, 0.4)
        plot.mode = ui.PlotMode.INTERACTIVE
        plot.set_axis_limits(0, 2, 0, 4)
        assert await self._red_at(plot, 0.5, 0.4)
        plot.mode = ui.PlotMode.LEGACY
        assert not await self._red_at(plot, 0.5, 0.4)
        assert await self._red_at(plot, 0.5, 0.75)

    async def test_constructor_takes_int_values(self):
        # The legacy constructor used to drop Python int values. Each bar is then as high as the float bars above.
        window = await self.create_test_window(128, 64)
        with window.frame:
            plot = ui.Plot(ui.Type.HISTOGRAM, 0, 2, 1, 1, 1,
                           sparkline=True,
                           style={"background_color": 0xFF000000, "color": 0xFF0000FF,
                                  "padding": 0, "border_width": 0})
        assert await self._red_at(plot, 0.5, 0.75)
        assert not await self._red_at(plot, 0.5, 0.4)

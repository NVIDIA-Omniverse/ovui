# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A renderer image of another size is scaled to the viewport, pixel by pixel.

While a new viewport size waits until it settles, each renderer image still has
the old size, and the adapter scales it to the new size (nearest pixel). This runs
on the first frame after a window resize or maximize, so the scale moves each pixel
as one 32-bit value. These tests check the scaled pixels in both adapters: each
source pixel holds its own row and column, so a wrong row, column or channel order
shows.
"""

from __future__ import annotations

import numpy as np
import pytest

from ovui_data_adapters.openusd import renderer_adapter as openusd_adapter
from ovui_data_adapters.ovstage import renderer_adapter as ovstage_adapter

ADAPTERS = [
    pytest.param(openusd_adapter, id="openusd"),
    pytest.param(ovstage_adapter, id="ovstage"),
]
SIZES = [
    pytest.param((5, 7), (11, 9), id="bigger"),
    pytest.param((9, 11), (4, 3), id="smaller"),
    pytest.param((6, 4), (6, 9), id="wider-only"),
    pytest.param((1, 1), (3, 2), id="one-pixel"),
]


def _coded_image(rows: int, columns: int) -> np.ndarray:
    """Each pixel holds (row, column, 200 - row, 100 + column)."""
    row = np.arange(rows, dtype=np.uint8)[:, None]
    column = np.arange(columns, dtype=np.uint8)[None, :]
    image = np.empty((rows, columns, 4), dtype=np.uint8)
    image[..., 0] = row
    image[..., 1] = column
    image[..., 2] = 200 - row
    image[..., 3] = 100 + column
    return image


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("source, target", SIZES)
def test_each_scaled_pixel_is_one_source_pixel_in_order(adapter, source, target):
    rows, columns = source
    width, height = target
    scaled = adapter._normalize_rgba(_coded_image(rows, columns), width, height)

    assert scaled.shape == (height, width, 4)
    assert scaled.dtype == np.uint8
    assert scaled.flags.c_contiguous
    source_row = scaled[..., 0].astype(int)
    source_column = scaled[..., 1].astype(int)
    # All four channels come from the same source pixel, in their order.
    assert np.array_equal(scaled[..., 2].astype(int), 200 - source_row)
    assert np.array_equal(scaled[..., 3].astype(int), 100 + source_column)
    # Each output row is one source row and each output column one source column.
    assert (source_row == source_row[:, :1]).all()
    assert (source_column == source_column[:1, :]).all()
    # The order stays, and the corners map to the corners.
    assert (np.diff(source_row[:, 0]) >= 0).all()
    assert (np.diff(source_column[0, :]) >= 0).all()
    assert (source_row[0, 0], source_column[0, 0]) == (0, 0)
    assert (source_row[-1, -1], source_column[-1, -1]) == (rows - 1, columns - 1)
    # Every source row and column is used when the image gets bigger.
    if height >= rows:
        assert set(source_row[:, 0]) == set(range(rows))
    if width >= columns:
        assert set(source_column[0, :]) == set(range(columns))


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_an_image_of_the_viewport_size_is_returned_unchanged(adapter):
    image = _coded_image(4, 6)
    assert np.array_equal(adapter._normalize_rgba(image, 6, 4), image)

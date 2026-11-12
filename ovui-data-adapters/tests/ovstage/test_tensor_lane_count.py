# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One element size for both tensor layouts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ovui_data_adapters.ovstage._native import element_lanes


def _tensor(lanes: int, shape: tuple[int, ...]) -> SimpleNamespace:
    return SimpleNamespace(dtype=SimpleNamespace(lanes=lanes), shape_tuple=shape)


@pytest.mark.parametrize(
    ("lanes", "shape", "expected"),
    [
        # Components in DLPack lanes.
        (16, (1,), 16),
        (6, (4,), 6),
        (3, (3,), 3),
        (1, (1,), 1),
        # Components in trailing shape dimensions; lanes is 1.
        (1, (1, 4, 4), 16),
        (1, (4, 6), 6),
        (1, (3, 3), 3),
        (1, (0,), 1),
    ],
)
def test_lane_count_is_the_same_for_both_layouts(lanes, shape, expected):
    assert element_lanes(_tensor(lanes, shape)) == expected

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Provider-neutral livestream transport compatibility tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from ovui_data_adapters.common import _livestream_tap as common_tap
from ovui_data_adapters.common import _swap_kernel as common_swap
from ovui_data_adapters.openusd import _livestream_tap as legacy_tap
from ovui_data_adapters.openusd import _swap_kernel as legacy_swap


def _tensor(shape: tuple[int, ...], *, lanes: int, bits: int = 8) -> SimpleNamespace:
    return SimpleNamespace(
        data=0xCAFE,
        shape=shape,
        dtype=SimpleNamespace(lanes=lanes, bits=bits),
    )


def test_openusd_private_modules_alias_provider_neutral_implementations() -> None:
    assert legacy_tap is common_tap
    assert legacy_swap is common_swap
    assert legacy_tap.LivestreamTap is common_tap.LivestreamTap


@pytest.mark.parametrize(
    "tensor",
    [
        _tensor((6, 8), lanes=4),
        _tensor((6, 8, 4), lanes=1),
        SimpleNamespace(data=0xCAFE, shape=(6, 8)),
        SimpleNamespace(data=0xCAFE, shape=(6, 8, 4)),
    ],
)
def test_rgba8_mapping_accepts_legacy_and_channel_last_layouts(tensor) -> None:
    assert common_tap._validate_rgba8_mapping_tensor(tensor, 8, 6) == tuple(
        tensor.shape
    )


@pytest.mark.parametrize(
    "tensor",
    [
        _tensor((6, 8), lanes=1),
        _tensor((6, 8, 4), lanes=4),
        _tensor((6, 8, 3), lanes=1),
        _tensor((6, 8, 4), lanes=1, bits=16),
    ],
)
def test_rgba8_mapping_rejects_incompatible_layouts(tensor) -> None:
    with pytest.raises(ValueError, match="OVRTX LdrColor|LdrColor mapping"):
        common_tap._validate_rgba8_mapping_tensor(tensor, 8, 6)

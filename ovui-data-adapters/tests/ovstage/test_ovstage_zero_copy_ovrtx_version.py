# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""GPU image upload follows the ovrtx version of the ovstage renderer adapter."""

from __future__ import annotations

import pytest

from ovui_data_adapters.common import ZeroCopyState, _Mode
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter


@pytest.mark.parametrize(
    ("version", "gpu_pending"),
    [((0, 4, 1, 364340), False), ((0, 5, 1, 385782), True)],
)
def test_gpu_upload_only_with_ovrtx_0_5_or_newer(version, gpu_pending):
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    adapter._ovrtx_version = version
    state = ZeroCopyState(_Mode.ENABLED)

    adapter.set_zero_copy_state(state)

    assert state.gpu_pending is gpu_pending

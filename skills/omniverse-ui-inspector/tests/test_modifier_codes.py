# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest


os.environ["OVUIINSPECT_ENABLED"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ovuiinspect import _IMGUI_KEY_LEFT_CTRL, _IMGUI_KEY_LEFT_SUPER, _modifier_codes  # noqa: E402


def test_modifier_codes_maps_cmd_meta_to_super_once() -> None:
    assert _modifier_codes(["cmd"]) == [_IMGUI_KEY_LEFT_SUPER]
    assert _modifier_codes(["meta"]) == [_IMGUI_KEY_LEFT_SUPER]
    assert _modifier_codes(["super", "cmd", "meta"]) == [_IMGUI_KEY_LEFT_SUPER]


def test_modifier_codes_preserves_order_after_alias_normalization() -> None:
    assert _modifier_codes(["cmd", "control"]) == [
        _IMGUI_KEY_LEFT_CTRL,
        _IMGUI_KEY_LEFT_SUPER,
    ]


def test_modifier_codes_rejects_unknown_modifier() -> None:
    with pytest.raises(ValueError, match="unsupported modifier"):
        _modifier_codes(["hyper"])

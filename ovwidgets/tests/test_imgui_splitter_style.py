# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the ImGui-owned dock splitter style bridge."""

from __future__ import annotations

import pytest


def _rgba_from_store(color: int) -> tuple[float, float, float, float]:
    return (
        (color & 0xFF) / 255.0,
        ((color >> 8) & 0xFF) / 255.0,
        ((color >> 16) & 0xFF) / 255.0,
        ((color >> 24) & 0xFF) / 255.0,
    )


def test_imgui_splitter_style_no_context_is_noop():
    from ovwidgets.app.style.imgui_runtime import apply_imgui_splitter_style

    assert apply_imgui_splitter_style() is False


def test_imgui_splitter_style_applies_to_active_context():
    import omni.ui as ui

    from ovwidgets.app.style import apply_global_styles
    from ovwidgets.app.style.imgui_runtime import apply_imgui_splitter_style

    try:
        ui.init("splitter-style-test", width=20, height=20)
    except RuntimeError as exc:
        pytest.skip(f"ui.init() unavailable in this environment: {exc}")

    try:
        apply_global_styles()
        assert apply_imgui_splitter_style() is True
    finally:
        ui.shutdown()

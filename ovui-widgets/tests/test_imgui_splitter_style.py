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
    from ovui_widgets.app.style.imgui_runtime import apply_imgui_splitter_style

    assert apply_imgui_splitter_style() is False


def test_imgui_splitter_style_applies_to_active_context(monkeypatch):
    import omni.ui as ui
    import omni.ui.standalone as standalone

    from ovui_widgets.app.style import apply_global_styles
    from ovui_widgets.app.style.imgui_runtime import apply_imgui_splitter_style

    # Earlier headless-export tests intentionally force a Vulkan backend in
    # process-wide environment variables. This test owns a tiny interactive
    # context, so isolate it from that pollution instead of inheriting a
    # backend that may be unavailable on the test host.
    monkeypatch.delenv("OMNIUI_HEADLESS", raising=False)
    monkeypatch.delenv("OMNIUI_BACKEND", raising=False)

    try:
        ui.init("splitter-style-test", width=20, height=20)
    except RuntimeError as exc:
        pytest.skip(f"ui.init() unavailable in this environment: {exc}")

    try:
        if standalone.get_window_size() == (0, 0):
            pytest.skip(
                "standalone window size is (0, 0); "
                "no native window/ImGui context is available"
            )
        apply_global_styles()
        assert apply_imgui_splitter_style() is True
    finally:
        ui.shutdown()

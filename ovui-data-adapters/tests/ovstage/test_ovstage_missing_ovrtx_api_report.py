# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A missing ovrtx API is reported by name; the feature fails, the adapter keeps running."""

from __future__ import annotations

from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter


class _RendererWithoutSelectionApis:
    pass


def test_missing_selection_style_api_is_reported_by_name(capsys) -> None:
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    adapter._renderer = _RendererWithoutSelectionApis()

    adapter._configure_selection_outline_styles()

    assert "ovrtx.Renderer.set_selection_group_styles" in capsys.readouterr().err

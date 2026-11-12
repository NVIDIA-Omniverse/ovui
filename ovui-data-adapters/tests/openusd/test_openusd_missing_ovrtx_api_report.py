# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A missing ovrtx API is reported by name; the feature fails, the adapter keeps running."""

from __future__ import annotations

from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter


class _RendererWithoutSelectionApis:
    pass


def _adapter() -> OvRtxRendererAdapter:
    adapter = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    adapter._renderer = _RendererWithoutSelectionApis()
    return adapter


def test_missing_selection_style_api_is_reported_by_name(capsys) -> None:
    _adapter()._configure_selection_outline_styles()

    assert "ovrtx.Renderer.set_selection_group_styles" in capsys.readouterr().err


def test_missing_selection_membership_apis_are_reported_by_name(capsys) -> None:
    assert _adapter()._write_selection_outline_group(["/World/Cube"], 1) is False

    err = capsys.readouterr().err
    assert "ovrtx.Renderer.set_selection_outline_group_strings" in err
    assert "ovrtx.Renderer.set_selection_outline_group_strings_async" in err
    assert "ovrtx.Renderer.write_attribute" in err

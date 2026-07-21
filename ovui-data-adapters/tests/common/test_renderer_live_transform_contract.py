# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Common renderer contract for live local transform previews."""

from __future__ import annotations

import inspect
from typing import Any

from ovui_data_adapters.common import RendererAdapter


class _MinimalRenderer(RendererAdapter):
    """Concrete renderer that inherits the live-transform defaults."""

    def __init__(self) -> None:
        self.authoritative_scene_writes: list[tuple[str, Any]] = []

    def load_stage(self, stage: Any) -> None:
        return None

    def render_frame(
        self,
        width: int,
        height: int,
        view_matrix: Any,
        proj_matrix: Any,
    ) -> Any:
        return None

    def set_resolution(self, width: int, height: int) -> None:
        return None

    def pick(
        self,
        x: float,
        y: float,
        callback: Any,
        query_name: str,
    ) -> None:
        return None

    def cancel_pick(self, query_name: str) -> None:
        return None

    def pick_rect(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        callback: Any,
    ) -> None:
        return None

    def set_selection_highlight(self, paths: list[str]) -> None:
        return None

    def shutdown(self) -> None:
        return None


def test_renderer_adapter_exposes_live_transform_contract() -> None:
    assert isinstance(RendererAdapter.supports_live_local_transform, property)

    set_signature = inspect.signature(RendererAdapter.set_live_local_transform)
    assert tuple(set_signature.parameters) == ("self", "path", "matrix")
    assert set_signature.return_annotation in (bool, "bool")

    clear_signature = inspect.signature(RendererAdapter.clear_live_local_transforms)
    assert tuple(clear_signature.parameters) == ("self", "paths")
    assert clear_signature.return_annotation in (None, "None")


def test_default_live_transform_preview_declines_without_scene_write() -> None:
    renderer = _MinimalRenderer()
    matrix = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [3.0, 0.0, 0.0, 1.0],
    ]

    assert renderer.supports_live_local_transform is False
    assert renderer.set_live_local_transform("/World/Cube", matrix) is False
    assert renderer.authoritative_scene_writes == []


def test_default_live_transform_clear_is_noop() -> None:
    renderer = _MinimalRenderer()

    renderer.clear_live_local_transforms(["/World/Cube"])

    assert renderer.supports_live_local_transform is False
    assert renderer.authoritative_scene_writes == []

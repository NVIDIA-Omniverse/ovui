# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Runtime-free tests for the Kit OVRTX pick-query coordinate contract."""

from __future__ import annotations

from collections import deque
from typing import Any

from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter

_RP = "/_OvuiRuntime/Render/Viewport"


class _RecordingRenderer:
    def __init__(self) -> None:
        self.pick_queries: list[tuple] = []

    def enqueue_pick_query(
        self, render_product_path: str, left, top, right, bottom
    ) -> None:
        self.pick_queries.append((render_product_path, left, top, right, bottom))


def _adapter(renderer: Any) -> OvstageRendererAdapter:
    a = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    a._ovrtx = type("_O", (), {"__version__": "kit"})
    a._ovrtx_version = "kit"
    a._renderer = renderer
    a._attached_stage = object()
    a._render_product_path = _RP
    a._last_render_product_resolution = (1280, 720)
    a._last_resolution = (1280, 720)
    a._in_flight_pick_queries = deque()
    a._pick_seq = 0
    a._pick_enqueue_count = 0
    a._last_pick_pixel_rect = None
    return a


def test_uses_ndc_predicate() -> None:
    r = _RecordingRenderer()
    assert _adapter(r)._pick_query_uses_ndc() is True


def test_kit_ovrtx_040_pick_sends_normalized_ndc() -> None:
    r = _RecordingRenderer()
    adapter = _adapter(r)
    received: list = []
    adapter.pick(0.0, 0.0, lambda p, pos: received.append((p, pos)), "click")
    assert len(r.pick_queries) == 1
    rp, left, top, right, bottom = r.pick_queries[0]
    assert rp == _RP
    # Same centre pixel rect, normalized to [0, 1] top-left NDC.
    assert (left, top, right, bottom) == (640 / 1280, 360 / 720, 641 / 1280, 361 / 720)
    assert all(isinstance(v, float) for v in (left, top, right, bottom))


def test_pick_rect_uses_normalized_ndc() -> None:
    renderer = _RecordingRenderer()
    _adapter(renderer).pick_rect(-0.5, -0.5, 0.5, 0.5, lambda paths: None)
    assert renderer.pick_queries
    assert all(isinstance(v, float) for v in renderer.pick_queries[0][1:])

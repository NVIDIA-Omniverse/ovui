# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Runtime-free tests for ovrtx-version-aware pick-query coordinate dispatch in
the OpenUSD renderer adapter.

ovrtx >= 0.4.0 takes a normalized [0, 1] top-left NDC rectangle (and rejects
pixel values); ovrtx 0.3.x takes RenderProduct pixel-int rectangles. The adapter
must send the right one for the active runtime (matching the ovstage adapter).
"""
from __future__ import annotations

from collections import deque
from typing import Any

from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter

_RP = "/OvGearSession/Render/Viewport"


class _RecordingRenderer:
    def __init__(self) -> None:
        self.pick_queries: list[tuple] = []

    def enqueue_pick_query(self, render_product_path: str, left, top, right, bottom) -> None:
        self.pick_queries.append((render_product_path, left, top, right, bottom))


def _adapter(version: Any, renderer: Any) -> OvRtxRendererAdapter:
    a = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    a._ovrtx_version = version
    a._renderer = renderer
    a._stage = object()  # truthy; _active_render_product_resolution falls back
    a._usd_handle = object()
    a._render_product_path = _RP
    a._last_render_product_resolution = (1280, 720)
    a._last_resolution = (1280, 720)
    a._pending_resolution = (1280, 720)
    a._in_flight_pick_queries = deque()
    a._pick_seq = 0
    a._pick_enqueue_count = 0
    a._last_pick_pixel_rect = None
    return a


def test_uses_ndc_predicate() -> None:
    r = _RecordingRenderer()
    assert _adapter((0, 4, 0), r)._pick_query_uses_ndc() is True
    assert _adapter((0, 5, 2), r)._pick_query_uses_ndc() is True
    assert _adapter((0, 3, 0), r)._pick_query_uses_ndc() is False
    assert _adapter((0, 2, 9), r)._pick_query_uses_ndc() is False
    assert _adapter("unknown", r)._pick_query_uses_ndc() is True


def test_old_ovrtx_030_pick_sends_pixel_ints() -> None:
    r = _RecordingRenderer()
    adapter = _adapter((0, 3, 0), r)
    adapter.pick(0.0, 0.0, lambda p, pos: None, "click")
    assert len(r.pick_queries) == 1
    rp, left, top, right, bottom = r.pick_queries[0]
    assert rp == _RP
    assert (left, top, right, bottom) == (640, 360, 641, 361)
    assert all(isinstance(v, int) for v in (left, top, right, bottom))


def test_kit_ovrtx_040_pick_sends_normalized_ndc() -> None:
    r = _RecordingRenderer()
    adapter = _adapter((0, 4, 0), r)
    adapter.pick(0.0, 0.0, lambda p, pos: None, "click")
    assert len(r.pick_queries) == 1
    rp, left, top, right, bottom = r.pick_queries[0]
    assert rp == _RP
    assert (left, top, right, bottom) == (640 / 1280, 360 / 720, 641 / 1280, 361 / 720)
    assert all(isinstance(v, float) for v in (left, top, right, bottom))


def test_pick_rect_dispatch_matches_runtime() -> None:
    old = _RecordingRenderer()
    _adapter((0, 3, 0), old).pick_rect(-0.5, -0.5, 0.5, 0.5, lambda paths: None)
    new = _RecordingRenderer()
    _adapter((0, 4, 0), new).pick_rect(-0.5, -0.5, 0.5, 0.5, lambda paths: None)
    assert old.pick_queries and new.pick_queries
    assert all(isinstance(v, int) for v in old.pick_queries[0][1:])
    assert all(isinstance(v, float) for v in new.pick_queries[0][1:])

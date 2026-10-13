# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

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


def test_pending_picks_render_and_consume_their_own_products_after_view_switch():
    adapter = _adapter((0, 4, 0), _RecordingRenderer())
    hits = []
    for product in ("/Front", "/Left"):
        adapter._render_product_path = product
        adapter.pick(0, 0, lambda path, pos: hits.append(path), product)
    adapter._render_product_path = "/Perspective"
    assert adapter._render_products_for_step() == {"/Front", "/Left", "/Perspective"}
    adapter._read_pick_hits = lambda products, product_path=None: products[
        product_path or adapter._render_product_path
    ]
    adapter._dispatch_pending_pick_results(
        {"/Front": [("/Cube", (1, 2, 3))], "/Left": [("/Sphere", (4, 5, 6))]}
    )
    assert hits == ["/Cube", "/Sphere"]
    assert not adapter._in_flight_pick_queries and not adapter._pick_query_products


def test_same_name_replacement_never_inherits_hits_from_another_product():
    adapter = _adapter((0, 4, 0), _RecordingRenderer())
    hits = []
    adapter._render_product_path = "/Front"
    adapter.pick(0, 0, lambda path, pos: hits.append(path), "click")
    adapter._render_product_path = "/Left"
    adapter.pick(0, 0, lambda path, pos: hits.append(path), "click")
    adapter._read_pick_hits = lambda products, product_path=None: products[
        product_path or adapter._render_product_path
    ]
    adapter._dispatch_pending_pick_results({"/Front": [("/Wrong", (0, 0, 0))], "/Left": []})
    assert hits == [None]
    adapter.pick(0, 0, lambda *a: None, "cleanup")
    adapter._dispatch_pending_pick_misses()
    assert not adapter._pick_query_products


def test_missing_step_product_waits_then_resolves_or_times_out():
    adapter = _adapter((0, 4, 0), _RecordingRenderer())
    hits = []
    adapter.pick(0, 0, lambda path, pos: hits.append(path), "delayed")
    adapter._read_pick_hits = lambda products, **kw: [("/Cube", (0, 0, 0))]
    adapter._dispatch_pending_pick_results({})
    assert hits == [] and len(adapter._in_flight_pick_queries) == 1
    adapter._dispatch_pending_pick_results({_RP: object()})
    assert hits == ["/Cube"] and not adapter._pick_query_waits
    adapter.pick(0, 0, lambda path, pos: hits.append(path), "missing")
    for _ in range(3):
        adapter._dispatch_pending_pick_results({})
    assert hits == ["/Cube", None]
    assert not adapter._in_flight_pick_queries and not adapter._pick_query_products


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

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A host presenting several RenderProducts in turn steps them as one group.

ovrtx rebuilds per-product render state whenever the set of stepped products
changes (about 0.27 s of GPU work per product on an L40). A quad layout that
stepped one product per view therefore paid four rebuilds per frame. These
runtime-free tests drive the real ``render_frame`` path with a fake renderer
whose images encode the step, the product and the camera it rendered.
"""

from __future__ import annotations

import time
from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest

from ovui_data_adapters.common._ldr_overlap import LdrOverlapState
from ovui_data_adapters.openusd import renderer_adapter as mod
from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter

QUAD = ("/Products/front", "/Products/left", "/Products/top", "/Products/perspective")
CAMERAS = {product: "/Cameras/" + product.rsplit("/", 1)[1] for product in QUAD}
W, H = 64, 36


class _FakeOvrtx:
    Device = SimpleNamespace(CPU="cpu", CUDA="cuda")
    Semantic = SimpleNamespace(XFORM_MAT4x4="xform")


class _FakeMapping:
    def __init__(self, array):
        self.tensor = SimpleNamespace(numpy=lambda: array)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeRenderer:
    """ovrtx stand-in: Fabric camera transforms plus recorded steps."""

    def __init__(self):
        self.fabric = {}
        self.steps = []

    def write_attribute(self, prim_paths, attribute_name, tensor, semantic=None):
        if attribute_name == "omni:xform":
            self.fabric[prim_paths[0]] = np.array(tensor, dtype=np.float64).reshape(4, 4)

    def step(self, render_products, delta_time):
        self.steps.append(set(render_products))
        results = {}
        for product in render_products:
            # Pixels encode (step, product, camera x the product rendered).
            camera_x = self.fabric.get(CAMERAS.get(product), np.eye(4))[3, 0]
            pixels = np.empty((H, W, 4), dtype=np.uint8)
            pixels[...] = (len(self.steps), QUAD.index(product), int(camera_x), 255)
            var = SimpleNamespace(map=lambda device=None, p=pixels: _FakeMapping(p))
            results[product] = SimpleNamespace(frames=[SimpleNamespace(render_vars={"LdrColor": var})])
        return results


def _view(camera_x):
    view = np.eye(4)
    view[0, 3] = -float(camera_x)  # GL view of a camera at (camera_x, 0, 0)
    return view


_PROJ = np.array(
    [[1.0, 0, 0, 0], [0, 1.78, 0, 0], [0, 0, -1.0002, -0.020002], [0, 0, -1, 0]]
)


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setattr(mod, "_ovrtx", _FakeOvrtx)
    monkeypatch.setattr(OvRtxRendererAdapter, "_frame_pacing_bindings", staticmethod(lambda: None))
    a = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    a._renderer = _FakeRenderer()
    a._stage = object()
    a._usd_handle = object()
    a._default_render_product_path = mod._RENDER_PRODUCT_PATH
    a._default_camera_path = mod._CAMERA_PATH
    a._render_product_path = QUAD[0]
    a._camera_path = CAMERAS[QUAD[0]]
    a._last_resolution = (W, H)
    a._zero_copy_state = None
    a._ldr_overlap = LdrOverlapState()  # Production enables the overlap.
    a._in_flight_pick_queries = deque()
    a._dt_clock = time.monotonic()
    return a


def _render_pass(adapter, camera_x):
    """One host frame: declare the group, then bind and render each view."""
    adapter.set_render_product_group(QUAD)
    images = {}
    for product in QUAD:
        assert adapter.set_active_render_product_path(product)
        assert adapter.set_active_camera_path(CAMERAS[product])
        images[product] = adapter.render_frame(W, H, _view(camera_x[product]), _PROJ)
    return images


def _pixel(image):
    return tuple(int(v) for v in image[0, 0, :3])


def test_grouped_products_share_one_step_per_frame(adapter):
    renderer = adapter._renderer
    cameras = {product: index + 1 for index, product in enumerate(QUAD)}
    _render_pass(adapter, cameras)  # First frame: learns each view's camera.
    first = len(renderer.steps)
    for _ in range(3):
        images = _render_pass(adapter, cameras)
    # Every step renders the whole group, so ovrtx never rebuilds a product.
    assert all(step == set(QUAD) for step in renderer.steps)
    assert len(renderer.steps) - first == 3
    step = len(renderer.steps)
    for index, product in enumerate(QUAD):
        # Each view presents its own product, rendered with its own camera
        # by the latest step.
        assert _pixel(images[product]) == (step, index, cameras[product])


def test_moved_camera_renders_again_before_it_is_presented(adapter):
    renderer = adapter._renderer
    cameras = {product: index + 1 for index, product in enumerate(QUAD)}
    _render_pass(adapter, cameras)
    _render_pass(adapter, cameras)
    before = len(renderer.steps)
    cameras[QUAD[2]] = 9  # Navigation moved the top view between frames.
    images = _render_pass(adapter, cameras)
    assert len(renderer.steps) - before == 2
    assert _pixel(images[QUAD[2]]) == (before + 2, 2, 9)
    # Views after it present the newer step; none shows a stale camera.
    assert _pixel(images[QUAD[3]]) == (before + 2, 3, cameras[QUAD[3]])
    assert _pixel(images[QUAD[1]]) == (before + 1, 1, cameras[QUAD[1]])


def test_renderer_side_camera_write_invalidates_the_shared_image(adapter):
    renderer = adapter._renderer
    cameras = {product: index + 1 for index, product in enumerate(QUAD)}
    _render_pass(adapter, cameras)
    _render_pass(adapter, cameras)
    # A transform preview moves the left camera in the renderer only; the
    # view still requests its old pose and must not present the preview.
    matrix = np.eye(4)
    matrix[3, 0] = 7.0
    assert adapter.set_live_local_transform(CAMERAS[QUAD[1]], matrix)
    before = len(renderer.steps)
    images = _render_pass(adapter, cameras)
    assert _pixel(images[QUAD[1]])[2] == cameras[QUAD[1]]
    assert len(renderer.steps) - before == 2


def test_empty_group_restores_single_product_steps(adapter):
    renderer = adapter._renderer
    adapter.set_render_product_group(QUAD)
    adapter.set_render_product_group([])
    adapter.render_frame(W, H, _view(1), _PROJ)
    adapter.render_frame(W, H, _view(1), _PROJ)
    assert renderer.steps == [{QUAD[0]}, {QUAD[0]}]


def test_native_pacing_never_steps_a_single_product_of_a_group(adapter, monkeypatch):
    native = SimpleNamespace(_get_present_rate=lambda: 60.0)
    monkeypatch.setattr(OvRtxRendererAdapter, "_frame_pacing_bindings", staticmethod(lambda: native))
    adapter._frame_pacing_provider = object()
    adapter._livestream = None
    adapter._point_cloud_requests = {}
    adapter._render_var_output_requests = {}
    assert adapter._frame_pacing_eligible()
    adapter.set_render_product_group(QUAD)
    assert not adapter._frame_pacing_eligible()


def test_presented_frames_are_counted_for_inspector_state(adapter):
    cameras = {product: index + 1 for index, product in enumerate(QUAD)}
    _render_pass(adapter, cameras)  # Synchronous steps.
    _render_pass(adapter, cameras)  # Group-cached images.
    adapter.set_render_product_group([])
    adapter.render_frame(W, H, _view(1), _PROJ)  # Overlap presentation.
    assert adapter._successful_frame_count == 2 * len(QUAD) + 1
    assert adapter._last_frame_shape == (H, W, 4)
    assert adapter._last_frame_nonblack_pixels == W * H

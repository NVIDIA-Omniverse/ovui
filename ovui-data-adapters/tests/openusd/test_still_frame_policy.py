# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A still camera does not step ovrtx again under the ``on_change`` policy.

ovrtx keeps memory on every step, so an idle USD Viewer that stepped its
unchanged picture on every frame grew without end. With the
``on_change`` render policy the synchronous ``render_frame`` path steps for a
change, then for the settle frames, and then returns the output of its last
step again. Work that waits for a step (a pick) and every change (camera,
request, renderer-side write) steps again. These tests need no GPU: they
drive the real ``render_frame`` with a fake renderer whose images encode the
step.
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

W, H = 32, 18
SETTLE = 3


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
    """ovrtx stand-in that counts steps and writes the step number into the image."""

    def __init__(self):
        self.steps = 0
        self.writes = []
        self.camera = None
        self.camera_of_step = {}

    def write_attribute(self, prim_paths, attribute_name, tensor, semantic=None):
        self.writes.append((tuple(prim_paths), attribute_name))
        if attribute_name == "omni:xform":
            self.camera = np.asarray(tensor).tobytes()

    def step(self, render_products, delta_time):
        self.steps += 1
        self.camera_of_step[self.steps] = self.camera
        pixels = np.full((H, W, 4), self.steps % 256, dtype=np.uint8)
        var = SimpleNamespace(map=lambda device=None, p=pixels: _FakeMapping(p))
        frame = SimpleNamespace(render_vars={"LdrColor": var})
        return {product: SimpleNamespace(frames=[frame]) for product in render_products}


def _view(camera_x):
    view = np.eye(4)
    view[0, 3] = -float(camera_x)
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
    a._render_product_path = mod._RENDER_PRODUCT_PATH
    a._camera_path = mod._CAMERA_PATH
    a._last_resolution = (W, H)
    a._zero_copy_state = None
    a._ldr_overlap = LdrOverlapState()  # Production enables the overlap.
    a._in_flight_pick_queries = deque()
    a._dt_clock = time.monotonic()
    return a


def _on_change(adapter):
    # Through getattr, so that an adapter without the policy fails on behaviour.
    getattr(adapter, "set_render_policy", lambda *_args: None)("on_change", SETTLE)


def _frames(adapter, count, camera_x=1.0):
    return [adapter.render_frame(W, H, _view(camera_x), _PROJ) for _ in range(count)]


def test_a_still_camera_stops_stepping_after_the_settle_frames(adapter):
    _on_change(adapter)
    frames = _frames(adapter, 12)
    assert adapter._renderer.steps == 1 + SETTLE
    # After the settle frames the newest step, which the overlap still held,
    # is shown once; then the same output object comes back: the viewport
    # keeps its picture and uploads nothing.
    kept = frames[SETTLE + 1]
    assert kept is not frames[SETTLE]
    assert all(frame is kept for frame in frames[SETTLE + 2:])
    # The adapter says so, and only for those frames.
    assert adapter.last_frame_unchanged()
    _frames(adapter, 1, camera_x=2.0)
    assert not adapter.last_frame_unchanged()


def test_without_a_policy_every_frame_steps(adapter):
    _frames(adapter, 12)
    assert adapter._renderer.steps == 12


def test_a_moved_camera_a_request_and_a_renderer_side_write_step_again(adapter):
    _on_change(adapter)
    _frames(adapter, 10)
    settled = adapter._renderer.steps

    _frames(adapter, 10, camera_x=2.0)
    assert adapter._renderer.steps == settled + 1 + SETTLE

    getattr(adapter, "request_render", lambda: None)()
    _frames(adapter, 10, camera_x=2.0)
    assert adapter._renderer.steps == settled + 2 * (1 + SETTLE)

    adapter._release_retained_output()  # Every structural renderer change does this first.
    _frames(adapter, 10, camera_x=2.0)
    assert adapter._renderer.steps == settled + 3 * (1 + SETTLE)


def test_a_waiting_pick_gets_its_step(adapter):
    _on_change(adapter)
    _frames(adapter, 10)
    settled = adapter._renderer.steps
    answers = []
    adapter._in_flight_pick_queries.append(
        [1, "point", "pick", lambda *args: answers.append(args), None, None]
    )
    _frames(adapter, 1)
    # The still camera steps once more for the pick, which is then answered.
    assert adapter._renderer.steps == settled + 1
    assert not adapter._in_flight_pick_queries
    assert answers


def test_a_deferred_resize_steps_until_the_resolution_is_committed(adapter, monkeypatch):
    _on_change(adapter)
    _frames(adapter, 10)
    settled = adapter._renderer.steps
    # The debounce keeps the committed resolution while the user resizes.
    monkeypatch.setattr(OvRtxRendererAdapter, "_apply_resolution_if_allowed", lambda self, target: None)
    for _ in range(10):
        adapter.render_frame(W + 20, H, _view(1.0), _PROJ)
    assert adapter._renderer.steps == settled + 10


def test_an_overlap_toggle_does_not_step_a_still_camera(adapter):
    # Without native pacing hooks every frame tries to start native pacing and
    # turns the overlap off and on again; the renderer does not change.
    _on_change(adapter)
    _frames(adapter, 10)
    settled = adapter._renderer.steps
    for _ in range(5):
        adapter.set_ldr_overlap_enabled(False)
        adapter.set_ldr_overlap_enabled(True)
        _frames(adapter, 1)
    assert adapter._renderer.steps == settled


@pytest.mark.parametrize("settle", [0, 1, SETTLE])
def test_the_kept_picture_shows_the_final_camera(adapter, settle):
    # The overlap shows the image of the step before each step. When the
    # camera stops, the image of its final position must still be shown, also
    # with zero settle frames, and with no extra step.
    adapter.set_render_policy("on_change", settle)
    _frames(adapter, 10)
    for camera_x in (2.0, 3.0, 4.0):  # the camera moves, then stops and moves again
        _frames(adapter, 1, camera_x=camera_x)
        _frames(adapter, 5, camera_x=camera_x)
    final_step = adapter._renderer.steps - settle
    final_camera = adapter._renderer.camera_of_step[final_step]
    kept = _frames(adapter, 10, camera_x=4.0)
    shown = {adapter._renderer.camera_of_step[int(frame[0, 0, 0])] for frame in kept}
    assert shown == {final_camera}
    assert all(frame is kept[0] for frame in kept)
    assert adapter._renderer.steps == final_step + settle


def test_the_first_frame_of_a_maximize_keeps_the_picture_and_does_not_step(adapter):
    """The frame that gets a new window size must not wait for the renderer.

    That frame also makes the new swapchain, and until it is presented the new
    window area is black. So it gives the picture on screen again, at the new
    size, and does no step and no upload; the next frame renders.
    """
    clock = [100.0]
    adapter._clock = lambda: clock[0]
    _frames(adapter, 3)
    clock[0] += 1.0
    shown = np.array(adapter.render_frame(W, H, _view(1.0), _PROJ), copy=True)
    steps = adapter._renderer.steps

    kept = adapter.render_frame(W + 20, H + 10, _view(1.0), _PROJ)
    assert kept.shape == (H + 10, W + 20, 4), "the viewport always gets an image of its own size"
    assert np.array_equal(kept, mod._normalize_rgba(shown, W + 20, H + 10))
    assert adapter.last_frame_unchanged(), "the viewport must not upload the kept picture again"
    assert adapter._renderer.steps == steps

    clock[0] += 0.01
    rendered = adapter.render_frame(W + 20, H + 10, _view(1.0), _PROJ)
    assert adapter._renderer.steps == steps + 1
    assert rendered.shape == (H + 10, W + 20, 4)
    assert not adapter.last_frame_unchanged()


def test_a_drag_of_the_window_border_keeps_the_picture_only_on_its_first_frame(adapter):
    clock = [100.0]
    adapter._clock = lambda: clock[0]
    _frames(adapter, 3)
    clock[0] += 1.0
    steps = adapter._renderer.steps
    for step in range(1, 6):
        clock[0] += 0.03
        adapter.render_frame(W + 4 * step, H + 2 * step, _view(1.0), _PROJ)
    # The first size of the drag keeps the picture; each later frame steps.
    assert adapter._renderer.steps == steps + 4

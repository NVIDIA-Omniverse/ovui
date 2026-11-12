# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A new viewport size reaches the OVStage render product when the size has settled.

The same rule as the OpenUSD adapter. A window resize (a drag of the window
border, a maximize) asks for a new size on many frames, and the first step at a
new resolution (a renderer reset and new render buffers) is slow and runs on the
UI thread. Before, it ran on the first frame at the new size, so after a maximize
the new window area stayed black during that step. Now the size is applied when
the viewport asked for the same size for the settle time. Runs without the
ovstage package, with the ``__new__`` field harness of ``test_ldr_overlap``; the
native Stage write of the resolution is recorded.
"""

from __future__ import annotations

import numpy as np
import pytest
from test_ldr_overlap import PRODUCT, W, H, _adapter, _products, _view

from ovui_data_adapters.ovstage import renderer_adapter as mod


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    monkeypatch.delenv(mod._LDR_OVERLAP_ENV_VAR, raising=False)
    monkeypatch.delenv("OVUI_WIDGETS_REQUIRE_OVRTX", raising=False)


@pytest.fixture
def writes(monkeypatch):
    """The resolution writes that reach the OVStage Stage."""
    recorded = []

    class _Batch:
        def __init__(self, _stage, paths):
            self._paths = list(paths)

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def write_fixed(self, name, value, lanes):
            recorded.append((self._paths, name, [int(v) for v in np.asarray(value).reshape(-1)]))

    monkeypatch.setattr(mod, "StageWriteBatch", _Batch)
    return recorded


@pytest.fixture
def adapter(writes):
    adapter = _adapter()
    renderer = adapter._renderer
    renderer.resets = 0

    def step(**_kwargs):
        renderer.step_calls += 1
        return _products(renderer.step_calls)

    def reset():
        renderer.resets += 1

    renderer.step = step
    renderer.reset = reset
    adapter.clock = [10.0]
    adapter._clock = lambda: adapter.clock[0]
    adapter._resize_request = (W, H)  # The viewport has shown this size before.
    return adapter


def _frame(adapter, size, advance):
    adapter.clock[0] += advance
    frame = adapter.render_frame(size[0], size[1], _view(0.0), np.eye(4))
    assert frame.shape == (size[1], size[0], 4), "the viewport always gets an image of its own size"


def test_a_new_size_reaches_the_render_product_only_after_it_settled(adapter, writes):
    size = (W + 32, H + 18)
    _frame(adapter, size, 0.0)
    _frame(adapter, size, 0.1)
    assert writes == [], "the first frames at a new size do not wait for a renderer reset"
    assert adapter._renderer.resets == 0

    _frame(adapter, size, mod._RESIZE_SETTLE_S)
    assert writes == [([PRODUCT], "resolution", list(size))]
    assert adapter._renderer.resets == 1
    _frame(adapter, size, 0.1)
    assert len(writes) == 1


def test_a_drag_of_the_window_border_writes_only_the_size_where_it_stopped(adapter, writes):
    for step in range(1, 6):
        _frame(adapter, (W + 10 * step, H + 6 * step), 0.05)
    assert writes == [], "no size is written while the size changes"
    _frame(adapter, (W + 50, H + 30), mod._RESIZE_SETTLE_S + 0.05)
    assert writes == [([PRODUCT], "resolution", [W + 50, H + 30])]
    assert adapter._renderer.resets == 1


def test_the_first_frame_of_a_maximize_keeps_the_picture_and_does_not_step(adapter, writes):
    """The frame that gets a new window size must not wait for the renderer.

    That frame also makes the new swapchain, and until it is presented the new
    window area is black. So it gives the picture on screen again, at the new
    size, and does no step and no upload; the next frame renders.
    """
    adapter.clock[0] += 1.0
    shown = np.array(adapter.render_frame(W, H, _view(0.0), np.eye(4)), copy=True)
    steps = adapter._renderer.step_calls
    size = (W + 32, H + 18)

    kept = adapter.render_frame(size[0], size[1], _view(0.0), np.eye(4))
    assert kept.shape == (size[1], size[0], 4), "the viewport always gets an image of its own size"
    assert np.array_equal(kept, mod._normalize_rgba(shown, *size))
    assert adapter.last_frame_unchanged(), "the viewport must not upload the kept picture again"
    assert adapter._renderer.step_calls == steps

    _frame(adapter, size, 0.01)
    assert adapter._renderer.step_calls == steps + 1
    assert not adapter.last_frame_unchanged()
    assert writes == []


def test_a_drag_keeps_the_picture_only_on_its_first_frame(adapter):
    adapter.clock[0] += 1.0
    adapter.render_frame(W, H, _view(0.0), np.eye(4))
    steps = adapter._renderer.step_calls
    for step in range(1, 6):
        adapter.clock[0] += 0.03
        adapter.render_frame(W + 10 * step, H + 6 * step, _view(0.0), np.eye(4))
    # The first size of the drag keeps the picture; each later frame steps.
    assert adapter._renderer.step_calls == steps + 4

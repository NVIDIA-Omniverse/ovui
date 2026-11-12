# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A still camera does not step ovrtx again under the ``on_change`` policy (OVStage).

The same rule as the OpenUSD adapter: with the ``on_change``
render policy the synchronous ``render_frame`` path steps for a change, then
for the settle frames, and then returns the output of its last step again. A
new committed Stage ordinal (a Stage edit), a request, a renderer-side write
and a waiting pick step again. Runs without the ovstage package, with the
``__new__`` field harness of ``test_ldr_overlap``.
"""

from __future__ import annotations

import numpy as np
import pytest
from test_ldr_overlap import W, H, _adapter, _products, _view

from ovui_data_adapters.ovstage import renderer_adapter as mod

SETTLE = 3


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    monkeypatch.delenv(mod._LDR_OVERLAP_ENV_VAR, raising=False)
    monkeypatch.delenv("OVUI_WIDGETS_REQUIRE_OVRTX", raising=False)


@pytest.fixture
def adapter():
    adapter = _adapter()
    renderer = adapter._renderer

    def step(**_kwargs):
        renderer.step_calls += 1
        return _products(renderer.step_calls)

    renderer.step = step
    # Through getattr, so that an adapter without the policy fails on behaviour.
    getattr(adapter, "set_render_policy", lambda *_args: None)("on_change", SETTLE)
    return adapter


def _frames(adapter, count, offset=0.0):
    return [adapter.render_frame(W, H, _view(offset), np.eye(4)) for _ in range(count)]


def test_a_still_camera_stops_stepping_after_the_settle_frames(adapter):
    frames = _frames(adapter, 12)
    assert adapter._renderer.step_calls == 1 + SETTLE
    assert all(frame is frames[SETTLE] for frame in frames[SETTLE + 1:])
    # The adapter says so, and only for those frames.
    assert adapter.last_frame_unchanged()
    _frames(adapter, 1, offset=2.0)
    assert not adapter.last_frame_unchanged()


def test_a_stage_edit_a_moved_camera_and_a_request_step_again(adapter):
    _frames(adapter, 10)
    settled = adapter._renderer.step_calls

    adapter._scene.current_ordinal += 1  # A committed Stage edit.
    _frames(adapter, 10)
    assert adapter._renderer.step_calls == settled + 1 + SETTLE

    _frames(adapter, 10, offset=2.0)
    assert adapter._renderer.step_calls == settled + 2 * (1 + SETTLE)

    getattr(adapter, "request_render", lambda: None)()
    _frames(adapter, 10, offset=2.0)
    assert adapter._renderer.step_calls == settled + 3 * (1 + SETTLE)

    adapter._release_retained_output()  # Every renderer mutation does this first.
    _frames(adapter, 10, offset=2.0)
    assert adapter._renderer.step_calls == settled + 4 * (1 + SETTLE)


def test_a_waiting_pick_keeps_stepping(adapter):
    _frames(adapter, 10)
    settled = adapter._renderer.step_calls
    adapter._in_flight_pick_queries.append([1, "point", "pick", lambda *_args: None, None, None])
    adapter._dispatch_pending_pick_results = lambda products: None  # The answer is late.
    _frames(adapter, 5)
    assert adapter._renderer.step_calls == settled + 5


@pytest.mark.parametrize("settle", [0, 1, SETTLE])
def test_the_kept_picture_shows_the_final_camera(adapter, settle):
    # The overlap shows the image of the step before each step. When the
    # camera stops, the image of its final position must still be shown, also
    # with zero settle frames, and with no extra step.
    camera_of_step = {}
    renderer = adapter._renderer

    def step(**_kwargs):
        renderer.step_calls += 1
        camera_of_step[renderer.step_calls % 251] = float(adapter._last_view_matrix[0, 3])
        return _products(renderer.step_calls)

    renderer.step = step
    adapter.set_ldr_overlap_enabled(True)
    adapter.set_render_policy("on_change", settle)
    _frames(adapter, 10)
    for offset in (2.0, 3.0, 4.0):  # the camera moves, then stops and moves again
        _frames(adapter, 1, offset=offset)
        _frames(adapter, 5, offset=offset)
    steps = renderer.step_calls
    kept = _frames(adapter, 10, offset=4.0)
    assert {camera_of_step[int(frame[0, 0, 0])] for frame in kept} == {4.0}
    assert all(frame is kept[0] for frame in kept)
    assert renderer.step_calls == steps

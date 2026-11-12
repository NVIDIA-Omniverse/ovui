# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Asynchronous livestream pipeline: event-polled publisher and the renderer's on-demand CPU image."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from ovui_data_adapters.common import _livestream_tap as tap_module
from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter


class _Events:
    """Fake cudart events: an event completes when the test says so."""

    def __init__(self) -> None:
        self.done: set[int] = set()

    def event_query(self, event: int) -> bool:
        return event in self.done


def _publisher(events: _Events, fps: int = 60) -> tap_module._Publisher:
    # Built without its thread: the tests drive _next() directly.
    publisher = tap_module._Publisher.__new__(tap_module._Publisher)
    publisher._tap = SimpleNamespace(_cudart=events)
    publisher._lock = tap_module.threading.Lock()
    publisher._in_flight = []
    publisher._last = None
    publisher._ready_at = None
    publisher._copy_latency = []
    publisher._period = 1.0 / fps
    publisher.budget = publisher._period
    publisher.dropped_frames = 0
    publisher._wake = tap_module.threading.Event()
    return publisher


def _post(publisher, slot, produced, offset=0.0):
    publisher.post(slot, 100 + slot, 8, 6, slot, produced, offset)


def test_publisher_waits_for_a_frame_whose_copy_is_still_running() -> None:
    events = _Events()
    publisher = _publisher(events)
    now = tap_module.time.perf_counter()
    _post(publisher, 0, now)
    assert publisher._next() is None
    events.done.add(100)
    assert publisher._next()[0] == 0
    assert publisher._next() is None


def test_publisher_sends_in_order_and_a_later_frame_cannot_overtake() -> None:
    events = _Events()
    publisher = _publisher(events)
    now = tap_module.time.perf_counter()
    _post(publisher, 0, now)
    _post(publisher, 1, now)
    events.done.add(101)  # the newer copy finished first
    assert publisher._next() is None
    events.done.add(100)
    assert [publisher._next()[0], publisher._next()[0]] == [0, 1]


def test_frame_generation_frames_are_due_one_period_apart() -> None:
    events = _Events()
    publisher = _publisher(events, fps=120)
    produced = 10.0
    _post(publisher, 0, produced, 0.0)
    _post(publisher, 1, produced, 1 / 120)
    first, second = publisher._in_flight
    assert abs((publisher._due(second) - publisher._due(first)) - 1 / 120) < 1e-9
    assert abs(publisher._due(first) - (produced + publisher.budget)) < 1e-9


def test_publisher_skips_overdue_frames_after_a_stall_but_keeps_two() -> None:
    events = _Events()
    publisher = _publisher(events)
    old = tap_module.time.perf_counter() - 1.0  # a second behind
    for slot in range(4):
        _post(publisher, slot, old + slot / 60)
    events.done.update({100, 101, 102, 103})
    assert publisher._next()[0] == 2
    assert publisher.dropped_frames == 2
    assert publisher._next()[0] == 3


def test_budget_follows_copy_latency_within_one_to_four_periods() -> None:
    events = _Events()
    publisher = _publisher(events, fps=60)
    for latency in [0.030] * 40:
        publisher._ready_at = 1.0 + latency
        publisher._learn((0, 0, 8, 6, 0, 1.0, 0.0))
    assert abs(publisher.budget - 0.031) < 1e-6
    for latency in [0.030] * 98 + [0.045] * 2:  # rare slow copies stay below the 98th percentile
        publisher._ready_at = 1.0 + latency
        publisher._learn((0, 0, 8, 6, 0, 1.0, 0.0))
    assert abs(publisher.budget - 0.031) < 1e-6
    for latency in [0.5] * 200:
        publisher._ready_at = 1.0 + latency
        publisher._learn((0, 0, 8, 6, 0, 1.0, 0.0))
    assert publisher.budget == 4 / 60


def test_publisher_keeps_slots_in_flight_and_the_last_sent_one_busy() -> None:
    events = _Events()
    publisher = _publisher(events)
    _post(publisher, 3, 0.0)
    _post(publisher, 4, 0.0)
    publisher._last = (1, 101, 8, 6, 1, 0.0, 0.0)
    assert publisher.busy_slots() == {1, 3, 4}


def test_stream_trace_summarizes_a_second(tmp_path, monkeypatch) -> None:
    from ovui_data_adapters.common._stream_trace import StreamTrace

    monkeypatch.setenv("OVUI_STREAM_TRACE", "1")
    trace = StreamTrace(60, tmp_path)
    # A fixed start: (perf_counter() + 1.0) - perf_counter() can be a little below 1.0 for some clock values,
    # and then tick() does not roll the second.
    start = trace._second_start = 100.0
    for i in range(60):
        if i == 30:
            continue  # a frame that never came: one 33 ms send interval
        t = start + i / 60
        trace.produced(i, t)
        trace.sent(i, True, t - 0.017, t - 0.012, t, 0.0002, 1)
    trace.sent(60, False, start, None, start + 0.995, 0.0002, 0)  # the last frame again
    summary = trace.tick(start + 1.0)
    assert summary["new_fps"] == 59.0 and summary["repeats"] == 1
    assert summary["late_sends"] == 1
    assert abs(summary["queue_ms"]["p50"] - 17.0) < 0.5
    assert summary["produce_interval_ms"]["max"] > 30
    lines = trace.path.read_text().splitlines()
    assert '"event":"second"' in lines[-1]


def test_stream_trace_writes_no_file_unless_enabled(tmp_path, monkeypatch) -> None:
    from ovui_data_adapters.common._stream_trace import StreamTrace

    monkeypatch.delenv("OVUI_STREAM_TRACE", raising=False)
    trace = StreamTrace(60, tmp_path / "stream-trace")
    trace.tick(trace._second_start + 1.0)
    trace.close()
    assert trace.path is None and not (tmp_path / "stream-trace").exists()


class _Mapping:
    def __init__(self, ptr: int) -> None:
        self.tensor = SimpleNamespace(data=ptr, shape=(6, 8, 4), device=SimpleNamespace(id=0))
        self.waited = False
        self.unmapped_with = "open"

    def wait(self) -> None:
        self.waited = True

    def unmap(self, event=None) -> None:
        self.unmapped_with = event


class _RenderVar:
    def __init__(self, ptr: int, log: list) -> None:
        self.mapping = _Mapping(ptr)
        self.log = log

    def map(self, device, sync_stream=None):
        self.log.append(("map", self.mapping.tensor.data, sync_stream))
        return self.mapping


class _Tap:
    async_enabled = True
    cuda_stream = 77

    def __init__(self, log: list) -> None:
        self.log = log
        self._cudart = SimpleNamespace(d2h=self._d2h)

    def tee_async(self, tensor, width, height, index=0, frames=1):
        self.log.append(("tee", tensor.data))
        return 1000 + tensor.data

    def _d2h(self, host, ptr, nbytes, device=None):
        self.log.append(("d2h", ptr))
        host.fill(ptr & 0xFF)


def _adapter(on_demand: bool) -> OvRtxRendererAdapter:
    adapter = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    adapter.cpu_image_on_demand = on_demand
    adapter._cpu_image_requests = 0
    return adapter


def _patch(monkeypatch) -> None:
    from ovui_data_adapters.openusd import renderer_adapter

    monkeypatch.setattr(renderer_adapter, "_mapped_render_var_tensor", lambda mapping: mapping.tensor)
    monkeypatch.setattr(renderer_adapter, "_ovrtx", SimpleNamespace(Device=SimpleNamespace(CUDA="cuda")))


def test_streamed_frames_are_gpu_only_unless_a_cpu_image_is_requested(monkeypatch) -> None:
    _patch(monkeypatch)
    log: list = []
    adapter = _adapter(on_demand=True)
    rvs = [_RenderVar(1, log), _RenderVar(2, log)]  # frame generation: generated, then real
    assert adapter._tee_livestream_async(rvs, _Tap(log), 8, 6) is None
    assert log == [("map", 1, 77), ("tee", 1), ("map", 2, 77), ("tee", 2)]
    # Each mapping is released against its copy's event, never waited on by the host.
    assert [rv.mapping.unmapped_with for rv in rvs] == [1001, 1002]
    assert not any(rv.mapping.waited for rv in rvs)


def test_a_requested_cpu_image_is_the_real_frame_and_is_consumed(monkeypatch) -> None:
    _patch(monkeypatch)
    log: list = []
    adapter = _adapter(on_demand=True)
    adapter._cpu_image_requests = 1
    rvs = [_RenderVar(1, log), _RenderVar(2, log)]
    image = adapter._tee_livestream_async(rvs, _Tap(log), 8, 6)
    assert isinstance(image, np.ndarray) and image.shape == (6, 8, 4) and image[0, 0, 0] == 2
    assert ("d2h", 2) in log and ("d2h", 1) not in log
    assert rvs[1].mapping.waited and not rvs[0].mapping.waited
    assert adapter._cpu_image_requests == 0
    assert adapter._tee_livestream_async([_RenderVar(3, log)], _Tap(log), 8, 6) is None


def test_hosts_that_keep_cpu_images_get_one_every_frame(monkeypatch) -> None:
    _patch(monkeypatch)
    log: list = []
    adapter = _adapter(on_demand=False)
    image = adapter._tee_livestream_async([_RenderVar(5, log)], _Tap(log), 8, 6)
    assert isinstance(image, np.ndarray) and image[0, 0, 0] == 5

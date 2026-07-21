# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Performance harness for prim manipulator drag preview vs USD authoring."""

from __future__ import annotations

import statistics
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterable

from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
from ovui_widgets.common.testing.mock_stage import MockStageAdapter
from ovui_widgets.common.testing.mock_transform import MockTransformAdapter
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.viewport.prim_transform_model import PrimTransformModel, _apply_delta


_PATH = "/World/Cube"
_IDENTITY = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]
_FRAMES = 180
_REPEATS = 9
_WARMUPS = 3
_AUTHORED_EVENT_FANOUT = 80


@dataclass
class _MethodMetrics:
    calls: int = 0
    total_ms: float = 0.0

    @property
    def average_ms(self) -> float:
        return self.total_ms / self.calls if self.calls else 0.0

    def record(self, started_at: float) -> None:
        self.calls += 1
        self.total_ms += (time.perf_counter() - started_at) * 1000.0


class _CountingTransformAdapter(MockTransformAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.set_local_transform_metrics = _MethodMetrics()

    def set_local_transform(self, path: str, matrix: list[list[float]]) -> None:
        started_at = time.perf_counter()
        try:
            return super().set_local_transform(path, matrix)
        finally:
            self.set_local_transform_metrics.record(started_at)

    def reset_metrics(self) -> None:
        self.set_local_transform_metrics = _MethodMetrics()


class _CountingStageAdapter(MockStageAdapter):
    def __init__(
        self,
        *,
        transform: MockTransformAdapter | None = None,
        mirror_reads_per_event: int = 0,
    ) -> None:
        super().__init__()
        self.notify_transform_changed_metrics = _MethodMetrics()
        self.suppress_change_notifications_metrics = _MethodMetrics()
        self._transform = transform
        self._mirror_reads_per_event = int(mirror_reads_per_event)

    @contextmanager
    def suppress_change_notifications(self):
        started_at = time.perf_counter()
        try:
            with super().suppress_change_notifications():
                yield
        finally:
            self.suppress_change_notifications_metrics.record(started_at)

    def notify_transform_changed(
        self,
        paths: Iterable[str],
        *,
        source: str | None = None,
    ) -> None:
        started_at = time.perf_counter()
        try:
            if self._transform is not None:
                for _ in range(self._mirror_reads_per_event):
                    for path in paths:
                        matrix = self._transform.get_local_transform(str(path))
                        _ = [row[:] for row in matrix]
        finally:
            self.notify_transform_changed_metrics.record(started_at)

    def reset_metrics(self) -> None:
        self.notify_transform_changed_metrics = _MethodMetrics()
        self.suppress_change_notifications_metrics = _MethodMetrics()


class _CountingRendererAdapter(MockRendererAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.live_preview_metrics = _MethodMetrics()
        self.clear_preview_metrics = _MethodMetrics()

    def set_live_local_transform(self, path: str, matrix: list[list[float]]) -> bool:
        started_at = time.perf_counter()
        try:
            return True
        finally:
            self.live_preview_metrics.record(started_at)

    def clear_live_local_transforms(self, paths: list[str]) -> None:
        started_at = time.perf_counter()
        try:
            return None
        finally:
            self.clear_preview_metrics.record(started_at)

    def reset_metrics(self) -> None:
        self.live_preview_metrics = _MethodMetrics()
        self.clear_preview_metrics = _MethodMetrics()


def _delta(index: int) -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [float(index + 1) * 0.001, 0.0, 0.0, 1.0],
    ]


def _make_transform() -> _CountingTransformAdapter:
    transform = _CountingTransformAdapter()
    transform.set_local_transform(_PATH, [row[:] for row in _IDENTITY])
    transform.reset_metrics()
    return transform


def _run_deferred_drag_moves(
    frames: int,
    *,
    renderer_enabled: bool,
) -> float:
    transform = _make_transform()
    stage = _CountingStageAdapter(transform=transform)
    renderer = _CountingRendererAdapter() if renderer_enabled else None
    model = PrimTransformModel(
        transform,
        stage,
        UndoManager(),
        renderer=renderer,
    )
    model.set_selection([_PATH])
    model.on_drag_start()
    started_at = time.perf_counter()
    for index in range(frames):
        model.on_drag_moved(_delta(index))
    return (time.perf_counter() - started_at) * 1000.0 / float(frames)


def _run_authored_drag_moves(frames: int) -> float:
    transform = _make_transform()
    stage = _CountingStageAdapter(
        transform=transform,
        mirror_reads_per_event=_AUTHORED_EVENT_FANOUT,
    )
    initial = transform.get_local_transform(_PATH)
    started_at = time.perf_counter()
    for index in range(frames):
        matrix = _apply_delta(initial, _delta(index), "world")
        transform.set_local_transform(_PATH, matrix)
        stage.notify_transform_changed([_PATH], source="viewport-manipulator-live")
    return (time.perf_counter() - started_at) * 1000.0 / float(frames)


def _median_frame_ms(runner, frames: int) -> float:
    for _ in range(_WARMUPS):
        runner(frames)
    samples = [runner(frames) for _ in range(_REPEATS)]
    return float(statistics.median(samples))


def test_prim_drag_deferred_preview_meets_count_and_timing_gates() -> None:
    transform = _make_transform()
    stage = _CountingStageAdapter(transform=transform)
    renderer = _CountingRendererAdapter()
    model = PrimTransformModel(transform, stage, UndoManager(), renderer=renderer)
    model.set_selection([_PATH])
    model.on_drag_start()

    for index in range(_FRAMES):
        model.on_drag_moved(_delta(index))

    live_usd_writes = transform.set_local_transform_metrics.calls
    live_stage_events = stage.notify_transform_changed_metrics.calls
    live_stage_suppression = stage.suppress_change_notifications_metrics.calls
    renderer_preview_calls = renderer.live_preview_metrics.calls

    assert live_usd_writes == 0
    assert live_stage_events == 0
    assert live_stage_suppression == 0
    assert renderer_preview_calls == _FRAMES

    model.on_drag_ended()

    release_usd_writes = transform.set_local_transform_metrics.calls
    release_stage_events = stage.notify_transform_changed_metrics.calls
    release_stage_suppression = stage.suppress_change_notifications_metrics.calls
    release_clear_calls = renderer.clear_preview_metrics.calls

    assert release_usd_writes == 1
    assert release_stage_events == 1
    assert release_stage_suppression == 1
    assert release_clear_calls == 1

    control_ms = _median_frame_ms(
        lambda frames: _run_deferred_drag_moves(frames, renderer_enabled=False),
        _FRAMES,
    )
    deferred_ms = _median_frame_ms(
        lambda frames: _run_deferred_drag_moves(frames, renderer_enabled=True),
        _FRAMES,
    )
    authored_ms = _median_frame_ms(_run_authored_drag_moves, _FRAMES)
    authored_ratio = authored_ms / deferred_ms if deferred_ms else float("inf")
    deferred_control_pct = (
        (deferred_ms / control_ms) * 100.0
        if control_ms
        else float("inf")
    )

    # The authored comparison is a disclosed fanout model, not an old-code run.
    print(
        "MANIPULATOR_DRAG_BENCHMARK "
        f"frames={_FRAMES} repeats={_REPEATS} warmups={_WARMUPS} "
        f"live_usd_writes={live_usd_writes} "
        f"live_stage_events={live_stage_events} "
        f"renderer_preview_calls={renderer_preview_calls} "
        f"release_usd_writes={release_usd_writes} "
        f"release_stage_events={release_stage_events} "
        f"release_clear_calls={release_clear_calls} "
        f"control_ms={control_ms:.6f} "
        f"deferred_ms={deferred_ms:.6f} "
        f"authored_ms_modeled={authored_ms:.6f} "
        f"authored_over_deferred_modeled={authored_ratio:.2f}x "
        f"deferred_vs_control={deferred_control_pct:.1f}% "
        f"note=authored_is_modeled_fanout({_AUTHORED_EVENT_FANOUT})"
    )

    assert deferred_ms <= control_ms * 1.20
    assert authored_ratio >= 4.0

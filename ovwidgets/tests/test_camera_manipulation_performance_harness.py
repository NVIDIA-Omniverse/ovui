# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Measurement harness for selected-camera manipulation performance."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pytest
from ovui_data_adapters.common import (
    VIEWPORT_CAMERA_POSE_SOURCE,
    ChangeEvent,
    ChangeEventType,
)

from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
from ovwidgets.common.undo import UndoManager
from ovwidgets.viewport.viewport_widget import ViewportWidget

Gf = pytest.importorskip("pxr.Gf")
Sdf = pytest.importorskip("pxr.Sdf")
Usd = pytest.importorskip("pxr.Usd")
UsdGeom = pytest.importorskip("pxr.UsdGeom")
StageWidget = pytest.importorskip("ovwidgets.stage.widget.stage_widget").StageWidget
UsdStageAdapter = pytest.importorskip("ovui_data_adapters.openusd.stage_adapter").UsdStageAdapter


@dataclass
class _ViewportImage:
    visible: bool = True
    computed_width: int = 640
    computed_height: int = 360


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


@dataclass
class _RendererMetrics:
    render_calls: int = 0
    view_matrices: list[np.ndarray] = field(default_factory=list)
    projection_matrices: list[np.ndarray] = field(default_factory=list)


class _CountingRenderer(MockRendererAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.metrics = _RendererMetrics()

    def render_frame(self, width: int, height: int, view: Any, projection: Any) -> np.ndarray:
        self.metrics.render_calls += 1
        self.metrics.view_matrices.append(np.array(view, dtype=float, copy=True))
        self.metrics.projection_matrices.append(np.array(projection, dtype=float, copy=True))
        return np.zeros((height, width, 4), dtype=np.uint8)


class _CountingUsdStageAdapter(UsdStageAdapter):
    def __init__(self, stage: Usd.Stage, undo_manager: Any = None):
        self._scheduled_flushes: list[Any] = []
        super().__init__(
            stage,
            undo_manager=undo_manager,
            call_later=self._schedule_flush_for_test,
        )
        self.write_camera_pose = _MethodMetrics()
        self.flush = _MethodMetrics()
        self.notify = _MethodMetrics()
        self.compute_visibility_metrics = _MethodMetrics()
        self.get_children_metrics = _MethodMetrics()
        self.events: list[ChangeEvent] = []

    def _schedule_flush_for_test(self, _delay: float, callback: Any) -> None:
        self._scheduled_flushes.append(callback)

    def _drain_scheduled_flushes(self) -> None:
        while self._scheduled_flushes:
            callbacks = tuple(self._scheduled_flushes)
            self._scheduled_flushes.clear()
            for callback in callbacks:
                callback()

    def write_camera_pose_from_matrices(self, *args: Any, **kwargs: Any) -> bool:
        started_at = time.perf_counter()
        try:
            return super().write_camera_pose_from_matrices(*args, **kwargs)
        finally:
            self._drain_scheduled_flushes()
            self.write_camera_pose.record(started_at)

    def _flush(self, *args: Any, **kwargs: Any) -> Any:
        started_at = time.perf_counter()
        try:
            return super()._flush(*args, **kwargs)
        finally:
            self.flush.record(started_at)

    def _notify(self, *args: Any, **kwargs: Any) -> Any:
        started_at = time.perf_counter()
        try:
            if args:
                self.events.append(args[0])
            return super()._notify(*args, **kwargs)
        finally:
            self.notify.record(started_at)

    def compute_visibility(self, *args: Any, **kwargs: Any) -> Any:
        started_at = time.perf_counter()
        try:
            return super().compute_visibility(*args, **kwargs)
        finally:
            self.compute_visibility_metrics.record(started_at)

    def get_children(self, *args: Any, **kwargs: Any) -> Any:
        started_at = time.perf_counter()
        try:
            return super().get_children(*args, **kwargs)
        finally:
            self.get_children_metrics.record(started_at)

    def reset_metrics(self) -> None:
        self.write_camera_pose = _MethodMetrics()
        self.flush = _MethodMetrics()
        self.notify = _MethodMetrics()
        self.compute_visibility_metrics = _MethodMetrics()
        self.get_children_metrics = _MethodMetrics()
        self.events = []
        self._scheduled_flushes.clear()


class _CountingViewportWidget(ViewportWidget):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.author_active_camera_pose = _MethodMetrics()
        self.sync_active_camera_from_stage_change = _MethodMetrics()
        self.applied_active_camera_sync = _MethodMetrics()
        super().__init__(*args, **kwargs)

    def _author_active_camera_pose(self, *args: Any, **kwargs: Any) -> bool:
        started_at = time.perf_counter()
        try:
            return super()._author_active_camera_pose(*args, **kwargs)
        finally:
            self.author_active_camera_pose.record(started_at)

    def _sync_active_camera_from_stage_change(self, *args: Any, **kwargs: Any) -> bool:
        started_at = time.perf_counter()
        synced = False
        try:
            synced = bool(super()._sync_active_camera_from_stage_change(*args, **kwargs))
            return synced
        finally:
            self.sync_active_camera_from_stage_change.record(started_at)
            if synced:
                self.applied_active_camera_sync.record(started_at)

    def reset_metrics(self) -> None:
        self.author_active_camera_pose = _MethodMetrics()
        self.sync_active_camera_from_stage_change = _MethodMetrics()
        self.applied_active_camera_sync = _MethodMetrics()


class _HierarchyModelChangeSpy:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ovwidgets.stage.widget.hierarchy_model import HierarchyModel

        self.metrics = _MethodMetrics()
        original = HierarchyModel._on_adapter_changed

        def wrapped(instance: Any, *args: Any, **kwargs: Any) -> Any:
            started_at = time.perf_counter()
            try:
                return original(instance, *args, **kwargs)
            finally:
                self.metrics.record(started_at)

        monkeypatch.setattr(HierarchyModel, "_on_adapter_changed", wrapped)

    def reset_metrics(self) -> None:
        self.metrics = _MethodMetrics()


class _CountingStageWidget(StageWidget):
    def __init__(self, *stage_args: Any, **stage_kwargs: Any) -> None:
        self.refresh_footer_counts = _MethodMetrics()
        self.compute_stage_counts = _MethodMetrics()
        super().__init__(*stage_args, **stage_kwargs)

    def _refresh_footer_counts(self) -> None:
        started_at = time.perf_counter()
        try:
            return super()._refresh_footer_counts()
        finally:
            self.refresh_footer_counts.record(started_at)

    def _compute_stage_counts(self) -> tuple[int, int]:
        started_at = time.perf_counter()
        try:
            return super()._compute_stage_counts()
        finally:
            self.compute_stage_counts.record(started_at)

    def reset_metrics(self) -> None:
        self.refresh_footer_counts = _MethodMetrics()
        self.compute_stage_counts = _MethodMetrics()


def _make_stage(
    extra_prim_count: int = 0,
    *,
    include_second_camera: bool = False,
) -> Usd.Stage:
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    camera = UsdGeom.Camera.Define(stage, "/World/Camera1")
    camera.GetFocalLengthAttr().Set(35.0)
    UsdGeom.Xformable(camera.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(0.0, 3.0, 12.0))
    camera.GetPrim().CreateAttribute("omni:kit:centerOfInterest", Sdf.ValueTypeNames.Double3).Set(
        Gf.Vec3d(0.0, -3.0, -12.0)
    )
    if include_second_camera:
        camera2 = UsdGeom.Camera.Define(stage, "/World/Camera2")
        UsdGeom.Xformable(camera2.GetPrim()).AddTranslateOp().Set(
            Gf.Vec3d(8.0, 2.0, 10.0)
        )
        camera2.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
        ).Set(Gf.Vec3d(-8.0, -2.0, -10.0))
    for index in range(extra_prim_count):
        cube = UsdGeom.Cube.Define(stage, f"/World/Prim_{index:03d}")
        cube.AddTranslateOp().Set(Gf.Vec3d(float(index), 0.0, 0.0))
    return stage


def _make_viewport(
    adapter: _CountingUsdStageAdapter,
    renderer: _CountingRenderer,
) -> _CountingViewportWidget:
    viewport = _CountingViewportWidget(
        renderer=renderer,
        stage_adapter_provider=lambda: adapter,
    )
    viewport._image = _ViewportImage()
    viewport._camera_performance_subscription = adapter.subscribe_changes(
        viewport.notify_stage_changed
    )
    return viewport


def _destroy_viewport(viewport: _CountingViewportWidget) -> None:
    subscription = getattr(viewport, "_camera_performance_subscription", None)
    if subscription is not None:
        subscription.cancel()
        viewport._camera_performance_subscription = None
    viewport.destroy()


def _orbit_and_render(viewport: ViewportWidget, steps: int) -> None:
    for index in range(steps):
        viewport._camera.orbit(0.05 + (index * 0.01), 0.02)
        viewport.render(0.016)


def _assert_renderer_saw_live_motion(renderer: _CountingRenderer, expected_calls: int) -> None:
    assert renderer.metrics.render_calls == expected_calls
    assert len(renderer.metrics.view_matrices) == expected_calls
    assert len(renderer.metrics.projection_matrices) == expected_calls
    assert not np.allclose(renderer.metrics.view_matrices[0], renderer.metrics.view_matrices[-1])


def _active_camera_eye(viewport: ViewportWidget) -> tuple[float, float, float]:
    return tuple(float(v) for v in viewport._camera._get_eye())


def _active_camera_target(viewport: ViewportWidget) -> tuple[float, float, float]:
    return tuple(float(v) for v in viewport._camera.state.target)


def _set_camera_world_translation(
    stage: Usd.Stage,
    path: str,
    value: tuple[float, float, float],
) -> None:
    xformable = UsdGeom.Xformable(stage.GetPrimAtPath(path))
    for op in xformable.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            op.Set(Gf.Vec3d(*value))
            return
        if op.GetOpType() == UsdGeom.XformOp.TypeTransform:
            matrix = Gf.Matrix4d(1.0)
            matrix.SetTranslate(Gf.Vec3d(*value))
            op.Set(matrix)
            return
    xformable.AddTranslateOp().Set(Gf.Vec3d(*value))


def _set_camera_focal_length(stage: Usd.Stage, path: str, value: float) -> None:
    camera = UsdGeom.Camera(stage.GetPrimAtPath(path))
    camera.GetFocalLengthAttr().Set(value)


def _set_cube_size(stage: Usd.Stage, path: str, value: float) -> None:
    cube = UsdGeom.Cube(stage.GetPrimAtPath(path))
    cube.GetSizeAttr().Set(value)


def _set_prim_visibility(stage: Usd.Stage, path: str, visible: bool) -> None:
    imageable = UsdGeom.Imageable(stage.GetPrimAtPath(path))
    visibility = (
        UsdGeom.Tokens.inherited
        if visible
        else UsdGeom.Tokens.invisible
    )
    imageable.GetVisibilityAttr().Set(visibility)


def test_free_camera_navigation_measurement_keeps_usd_authoring_at_zero() -> None:
    adapter = _CountingUsdStageAdapter(_make_stage())
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)

    try:
        steps = 5
        _orbit_and_render(viewport, steps)

        assert viewport.author_active_camera_pose.calls == steps
        assert adapter.write_camera_pose.calls == 0
        assert adapter.flush.calls == 0
        assert adapter.notify.calls == 0
        assert viewport.sync_active_camera_from_stage_change.calls == 0
        _assert_renderer_saw_live_motion(renderer, expected_calls=steps)
    finally:
        _destroy_viewport(viewport)


def test_selected_camera_active_navigation_defers_usd_authoring() -> None:
    adapter = _CountingUsdStageAdapter(_make_stage())
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        viewport._select_camera_path("/World/Camera1")
        baseline_signature = viewport._last_authored_camera_signature
        adapter.reset_metrics()
        viewport.reset_metrics()

        steps = 5
        _orbit_and_render(viewport, steps)

        assert viewport.author_active_camera_pose.calls == steps
        assert adapter.write_camera_pose.calls == 0
        assert adapter.flush.calls == 0
        assert adapter.notify.calls == 0
        assert viewport.sync_active_camera_from_stage_change.calls == 0
        assert viewport.is_camera_navigation_active()
        assert viewport.has_dirty_camera_navigation()
        assert viewport._last_authored_camera_signature == baseline_signature
        _assert_renderer_saw_live_motion(renderer, expected_calls=steps)
    finally:
        _destroy_viewport(viewport)


def test_selected_camera_drag_then_settle_commits_one_write() -> None:
    adapter = _CountingUsdStageAdapter(_make_stage())
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        viewport._select_camera_path("/World/Camera1")
        baseline_signature = viewport._last_authored_camera_signature
        adapter.reset_metrics()
        viewport.reset_metrics()

        steps = 5
        _orbit_and_render(viewport, steps)
        changed_signature = viewport._camera_author_signature("/World/Camera1")
        assert changed_signature != baseline_signature
        assert viewport.is_camera_navigation_active()
        assert viewport.has_dirty_camera_navigation()
        assert adapter.write_camera_pose.calls == 0

        for _ in range(viewport.CAMERA_NAVIGATION_SETTLE_FRAMES):
            viewport.render(0.016)

        assert viewport.author_active_camera_pose.calls == (
            steps + viewport.CAMERA_NAVIGATION_SETTLE_FRAMES
        )
        assert adapter.write_camera_pose.calls == 1
        assert adapter.flush.calls == 1
        assert adapter.notify.calls == 1
        assert viewport.sync_active_camera_from_stage_change.calls == 0
        assert len(adapter.events) == 1
        assert adapter.events[0].source == VIEWPORT_CAMERA_POSE_SOURCE
        assert viewport._last_authored_camera_signature == changed_signature
        assert not viewport.is_camera_navigation_active()
        assert not viewport.has_dirty_camera_navigation()
        _assert_renderer_saw_live_motion(
            renderer,
            expected_calls=steps + viewport.CAMERA_NAVIGATION_SETTLE_FRAMES,
        )
    finally:
        _destroy_viewport(viewport)


def test_selected_camera_drag_creates_single_undo_entry() -> None:
    undo = UndoManager()
    adapter = _CountingUsdStageAdapter(_make_stage(), undo_manager=undo)
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        viewport._select_camera_path("/World/Camera1")
        adapter.reset_metrics()
        viewport.reset_metrics()

        _orbit_and_render(viewport, 5)

        assert adapter.write_camera_pose.calls == 0
        assert len(undo._undo_stack) == 0

        for _ in range(viewport.CAMERA_NAVIGATION_SETTLE_FRAMES + 1):
            viewport.render(0.016)

        assert adapter.write_camera_pose.calls == 1
        assert len(undo._undo_stack) == 1
        assert undo.can_undo() is True
        assert undo.can_redo() is False
        assert viewport.sync_active_camera_from_stage_change.calls == 0
    finally:
        _destroy_viewport(viewport)


def test_undo_restores_pre_drag_camera_pose() -> None:
    undo = UndoManager()
    adapter = _CountingUsdStageAdapter(_make_stage(), undo_manager=undo)
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        viewport._select_camera_path("/World/Camera1")
        initial_pose = adapter.read_camera_pose("/World/Camera1")
        adapter.reset_metrics()
        viewport.reset_metrics()

        _orbit_and_render(viewport, 5)
        for _ in range(viewport.CAMERA_NAVIGATION_SETTLE_FRAMES):
            viewport.render(0.016)

        dragged_pose = adapter.read_camera_pose("/World/Camera1")
        assert dragged_pose.eye != pytest.approx(initial_pose.eye)
        assert len(undo._undo_stack) == 1

        adapter.reset_metrics()
        viewport.reset_metrics()
        assert undo.undo() is True
        adapter._drain_scheduled_flushes()

        restored_pose = adapter.read_camera_pose("/World/Camera1")
        assert restored_pose.eye == pytest.approx(initial_pose.eye, rel=1e-5, abs=1e-5)
        assert restored_pose.target == pytest.approx(
            initial_pose.target,
            rel=1e-5,
            abs=1e-5,
        )
        assert adapter.write_camera_pose.calls == 0
        assert adapter.flush.calls == 1
        assert adapter.notify.calls == 1
        assert len(adapter.events) == 1
        assert adapter.events[0].source is None
        assert viewport.sync_active_camera_from_stage_change.calls == 1
        assert tuple(float(v) for v in viewport._camera._get_eye()) == pytest.approx(
            initial_pose.eye,
            rel=1e-5,
            abs=1e-5,
        )
        assert undo.can_redo() is True
    finally:
        _destroy_viewport(viewport)


def test_redo_reapplies_post_drag_camera_pose() -> None:
    undo = UndoManager()
    adapter = _CountingUsdStageAdapter(_make_stage(), undo_manager=undo)
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        viewport._select_camera_path("/World/Camera1")
        adapter.reset_metrics()
        viewport.reset_metrics()

        _orbit_and_render(viewport, 5)
        for _ in range(viewport.CAMERA_NAVIGATION_SETTLE_FRAMES):
            viewport.render(0.016)
        dragged_pose = adapter.read_camera_pose("/World/Camera1")

        assert undo.undo() is True
        adapter._drain_scheduled_flushes()
        adapter.reset_metrics()
        viewport.reset_metrics()

        assert undo.redo() is True
        adapter._drain_scheduled_flushes()

        redone_pose = adapter.read_camera_pose("/World/Camera1")
        assert redone_pose.eye == pytest.approx(dragged_pose.eye, rel=1e-5, abs=1e-5)
        assert redone_pose.target == pytest.approx(
            dragged_pose.target,
            rel=1e-5,
            abs=1e-5,
        )
        assert len(undo._undo_stack) == 1
        assert adapter.write_camera_pose.calls == 0
        assert adapter.flush.calls == 1
        assert adapter.notify.calls == 1
        assert len(adapter.events) == 1
        assert adapter.events[0].source is None
        assert viewport.sync_active_camera_from_stage_change.calls == 1
    finally:
        _destroy_viewport(viewport)


def test_self_authored_camera_notice_does_not_resync() -> None:
    adapter = _CountingUsdStageAdapter(_make_stage())
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        viewport._select_camera_path("/World/Camera1")
        adapter.reset_metrics()
        viewport.reset_metrics()

        _orbit_and_render(viewport, 4)
        assert adapter.write_camera_pose.calls == 0
        assert viewport.sync_active_camera_from_stage_change.calls == 0

        for _ in range(viewport.CAMERA_NAVIGATION_SETTLE_FRAMES):
            viewport.render(0.016)

        assert adapter.write_camera_pose.calls == 1
        assert adapter.notify.calls == 1
        assert len(adapter.events) == 1
        assert adapter.events[0].source == VIEWPORT_CAMERA_POSE_SOURCE
        assert viewport.sync_active_camera_from_stage_change.calls == 0
    finally:
        _destroy_viewport(viewport)


def test_camera_switch_during_active_drag_creates_one_undo_entry_for_committed_pose(
) -> None:
    undo = UndoManager()
    adapter = _CountingUsdStageAdapter(
        _make_stage(include_second_camera=True),
        undo_manager=undo,
    )
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        assert viewport._select_camera_path("/World/Camera1") is True
        adapter.reset_metrics()
        viewport.reset_metrics()

        _orbit_and_render(viewport, 3)

        assert adapter.write_camera_pose.calls == 0
        assert len(undo._undo_stack) == 0

        assert viewport._select_camera_path("/World/Camera2") is True

        assert adapter.write_camera_pose.calls == 1
        assert adapter.flush.calls == 1
        assert adapter.notify.calls == 1
        assert len(undo._undo_stack) == 1
        assert viewport.sync_active_camera_from_stage_change.calls == 0
    finally:
        _destroy_viewport(viewport)


def test_selected_camera_switch_during_active_drag_commits_dirty_pose() -> None:
    adapter = _CountingUsdStageAdapter(_make_stage(include_second_camera=True))
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        assert viewport._select_camera_path("/World/Camera1") is True
        assert adapter.write_camera_pose.calls == 0
        adapter.reset_metrics()
        viewport.reset_metrics()

        _orbit_and_render(viewport, 3)
        dragged_eye = _active_camera_eye(viewport)
        dragged_target = _active_camera_target(viewport)
        assert viewport.is_camera_navigation_active()
        assert viewport.has_dirty_camera_navigation()
        assert adapter.write_camera_pose.calls == 0

        assert viewport._select_camera_path("/World/Camera2") is True

        camera1_pose = adapter.read_camera_pose("/World/Camera1")
        assert camera1_pose.eye == pytest.approx(dragged_eye, rel=1e-5, abs=1e-5)
        assert camera1_pose.target == pytest.approx(
            dragged_target,
            rel=1e-5,
            abs=1e-5,
        )
        assert adapter.write_camera_pose.calls == 1
        assert adapter.flush.calls == 1
        assert adapter.notify.calls == 1
        assert viewport.sync_active_camera_from_stage_change.calls == 0
        assert viewport._active_camera_path == "/World/Camera2"
        assert not viewport.is_camera_navigation_active()
        assert not viewport.has_dirty_camera_navigation()
    finally:
        _destroy_viewport(viewport)


def test_external_camera_edit_does_not_inflate_undo_for_viewport_writes() -> None:
    undo = UndoManager()
    stage = _make_stage()
    adapter = _CountingUsdStageAdapter(stage, undo_manager=undo)
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        viewport._select_camera_path("/World/Camera1")

        _orbit_and_render(viewport, 3)
        for _ in range(viewport.CAMERA_NAVIGATION_SETTLE_FRAMES):
            viewport.render(0.016)
        assert len(undo._undo_stack) == 1

        adapter.reset_metrics()
        viewport.reset_metrics()
        _set_camera_world_translation(stage, "/World/Camera1", (6.0, 3.0, 12.0))
        adapter._drain_scheduled_flushes()

        assert len(undo._undo_stack) == 1
        assert adapter.write_camera_pose.calls == 0
        assert len(adapter.events) == 1
        assert adapter.events[0].source is None
        assert viewport.sync_active_camera_from_stage_change.calls == 1
    finally:
        _destroy_viewport(viewport)


def test_external_properties_edit_mid_drag_commits_dragged_pose() -> None:
    stage = _make_stage()
    adapter = _CountingUsdStageAdapter(stage)
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        assert viewport._select_camera_path("/World/Camera1") is True
        adapter.reset_metrics()
        viewport.reset_metrics()

        _orbit_and_render(viewport, 3)
        dragged_eye = _active_camera_eye(viewport)
        dragged_target = _active_camera_target(viewport)
        assert viewport.is_camera_navigation_active()
        assert viewport.has_dirty_camera_navigation()
        assert adapter.write_camera_pose.calls == 0

        # The stage-change sync path only resets navigation after the
        # deterministic settle detector leaves active state. Advance that
        # state directly so no render can author the dirty pose first.
        signature = viewport._camera_navigation_signature()
        viewport._camera_navigation_state.observe(signature)
        viewport._camera_navigation_state.observe(signature)
        assert not viewport.is_camera_navigation_active()
        assert viewport.has_dirty_camera_navigation()

        _set_camera_world_translation(stage, "/World/Camera1", (6.0, 3.0, 12.0))
        adapter._drain_scheduled_flushes()

        camera_pose = adapter.read_camera_pose("/World/Camera1")
        assert camera_pose.eye == pytest.approx(dragged_eye, rel=1e-5, abs=1e-5)
        assert camera_pose.target == pytest.approx(
            dragged_target,
            rel=1e-5,
            abs=1e-5,
        )
        assert adapter.write_camera_pose.calls == 1
        assert {event.source for event in adapter.events} == {
            None,
            VIEWPORT_CAMERA_POSE_SOURCE,
        }
        assert viewport.sync_active_camera_from_stage_change.calls == 1
        assert not viewport.is_camera_navigation_active()
        assert not viewport.has_dirty_camera_navigation()
    finally:
        _destroy_viewport(viewport)


def test_external_camera_edit_still_syncs() -> None:
    stage = _make_stage()
    adapter = _CountingUsdStageAdapter(stage)
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        assert viewport._select_camera_path("/World/Camera1") is True
        adapter.reset_metrics()
        viewport.reset_metrics()

        _set_camera_world_translation(stage, "/World/Camera1", (6.0, 3.0, 12.0))
        adapter._drain_scheduled_flushes()

        assert adapter.write_camera_pose.calls == 0
        assert adapter.notify.calls == 1
        assert len(adapter.events) == 1
        assert adapter.events[0].source is None
        assert viewport.sync_active_camera_from_stage_change.calls == 1
        assert viewport.applied_active_camera_sync.calls == 1
        assert tuple(float(v) for v in viewport._camera._get_eye()) == pytest.approx(
            (6.0, 3.0, 12.0),
            rel=1e-5,
            abs=1e-5,
        )
    finally:
        _destroy_viewport(viewport)


def test_external_camera_edit_followed_by_drag_authors_post_external_pose() -> None:
    stage = _make_stage()
    adapter = _CountingUsdStageAdapter(stage)
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        assert viewport._select_camera_path("/World/Camera1") is True
        adapter.reset_metrics()
        viewport.reset_metrics()

        _set_camera_world_translation(stage, "/World/Camera1", (6.0, 3.0, 12.0))
        adapter._drain_scheduled_flushes()

        assert adapter.write_camera_pose.calls == 0
        assert viewport.sync_active_camera_from_stage_change.calls == 1
        assert viewport.applied_active_camera_sync.calls == 1
        assert _active_camera_eye(viewport) == pytest.approx(
            (6.0, 3.0, 12.0),
            rel=1e-5,
            abs=1e-5,
        )
        assert _active_camera_target(viewport) == pytest.approx(
            (6.0, 0.0, 0.0),
            rel=1e-5,
            abs=1e-5,
        )

        adapter.reset_metrics()
        viewport.reset_metrics()
        _orbit_and_render(viewport, 4)
        dragged_eye = _active_camera_eye(viewport)
        dragged_target = _active_camera_target(viewport)

        assert adapter.write_camera_pose.calls == 0
        assert viewport.has_dirty_camera_navigation()
        assert dragged_eye != pytest.approx((6.0, 3.0, 12.0))
        assert dragged_target == pytest.approx(
            (6.0, 0.0, 0.0),
            rel=1e-5,
            abs=1e-5,
        )

        for _ in range(viewport.CAMERA_NAVIGATION_SETTLE_FRAMES):
            viewport.render(0.016)

        camera_pose = adapter.read_camera_pose("/World/Camera1")
        assert adapter.write_camera_pose.calls == 1
        assert len(adapter.events) == 1
        assert adapter.events[0].source == VIEWPORT_CAMERA_POSE_SOURCE
        assert viewport.sync_active_camera_from_stage_change.calls == 0
        assert camera_pose.eye == pytest.approx(dragged_eye, rel=1e-5, abs=1e-5)
        assert camera_pose.target == pytest.approx(
            dragged_target,
            rel=1e-5,
            abs=1e-5,
        )
    finally:
        _destroy_viewport(viewport)


def test_external_camera_edit_during_active_drag_wins_and_clears_dirty_on_settle() -> None:
    stage = _make_stage()
    adapter = _CountingUsdStageAdapter(stage)
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        assert viewport._select_camera_path("/World/Camera1") is True
        adapter.reset_metrics()
        viewport.reset_metrics()

        _orbit_and_render(viewport, 3)

        assert viewport.is_camera_navigation_active()
        assert viewport.has_dirty_camera_navigation()
        assert adapter.write_camera_pose.calls == 0

        _set_camera_world_translation(stage, "/World/Camera1", (6.0, 3.0, 12.0))
        adapter._drain_scheduled_flushes()

        assert adapter.write_camera_pose.calls == 0
        assert adapter.notify.calls == 1
        assert len(adapter.events) == 1
        assert adapter.events[0].source is None
        assert viewport.sync_active_camera_from_stage_change.calls == 1
        assert viewport.applied_active_camera_sync.calls == 1
        assert _active_camera_eye(viewport) == pytest.approx(
            (6.0, 3.0, 12.0),
            rel=1e-5,
            abs=1e-5,
        )
        assert _active_camera_target(viewport) == pytest.approx(
            (6.0, 0.0, 0.0),
            rel=1e-5,
            abs=1e-5,
        )

        for _ in range(viewport.CAMERA_NAVIGATION_SETTLE_FRAMES + 1):
            viewport.render(0.016)

        assert adapter.write_camera_pose.calls == 0
        assert not viewport.is_camera_navigation_active()
        assert not viewport.has_dirty_camera_navigation()
        assert adapter.read_camera_pose("/World/Camera1").eye == pytest.approx(
            (6.0, 3.0, 12.0),
            rel=1e-5,
            abs=1e-5,
        )
    finally:
        _destroy_viewport(viewport)


def test_external_camera_edit_with_no_selected_camera_does_not_apply_selected_sync() -> None:
    stage = _make_stage()
    adapter = _CountingUsdStageAdapter(stage)
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        adapter.reset_metrics()
        viewport.reset_metrics()

        _set_camera_world_translation(stage, "/World/Camera1", (6.0, 3.0, 12.0))
        adapter._drain_scheduled_flushes()

        assert viewport._active_camera_path is None
        assert adapter.write_camera_pose.calls == 0
        assert adapter.notify.calls == 1
        assert len(adapter.events) == 1
        assert adapter.events[0].source is None
        assert viewport.sync_active_camera_from_stage_change.calls == 1
        assert viewport.applied_active_camera_sync.calls == 0
        assert _active_camera_eye(viewport) != pytest.approx(
            (6.0, 3.0, 12.0),
            rel=1e-5,
            abs=1e-5,
        )
    finally:
        _destroy_viewport(viewport)


def test_multiple_external_camera_edits_sync_each_time_and_end_on_last_pose() -> None:
    stage = _make_stage()
    adapter = _CountingUsdStageAdapter(stage)
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        assert viewport._select_camera_path("/World/Camera1") is True
        adapter.reset_metrics()
        viewport.reset_metrics()

        _set_camera_world_translation(stage, "/World/Camera1", (6.0, 3.0, 12.0))
        adapter._drain_scheduled_flushes()
        _set_camera_world_translation(stage, "/World/Camera1", (9.0, 4.0, 10.0))
        adapter._drain_scheduled_flushes()

        assert adapter.write_camera_pose.calls == 0
        assert adapter.notify.calls == 2
        assert [event.source for event in adapter.events] == [None, None]
        assert viewport.sync_active_camera_from_stage_change.calls == 2
        assert viewport.applied_active_camera_sync.calls == 2
        assert _active_camera_eye(viewport) == pytest.approx(
            (9.0, 4.0, 10.0),
            rel=1e-5,
            abs=1e-5,
        )
        assert _active_camera_target(viewport) == pytest.approx(
            (9.0, 1.0, -2.0),
            rel=1e-5,
            abs=1e-5,
        )
    finally:
        _destroy_viewport(viewport)


def test_external_camera_edit_does_not_collide_with_self_authored_source() -> None:
    stage = _make_stage()
    adapter = _CountingUsdStageAdapter(stage)
    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        viewport._select_camera_path("/World/Camera1")
        adapter.reset_metrics()
        viewport.reset_metrics()

        _orbit_and_render(viewport, 3)
        for _ in range(viewport.CAMERA_NAVIGATION_SETTLE_FRAMES):
            viewport.render(0.016)

        assert adapter.write_camera_pose.calls == 1
        assert len(adapter.events) == 1
        assert adapter.events[0].source == VIEWPORT_CAMERA_POSE_SOURCE
        assert viewport.sync_active_camera_from_stage_change.calls == 0

        adapter.reset_metrics()
        viewport.reset_metrics()
        _set_camera_world_translation(stage, "/World/Camera1", (7.0, 3.0, 12.0))
        adapter._drain_scheduled_flushes()

        assert adapter.write_camera_pose.calls == 0
        assert len(adapter.events) == 1
        assert adapter.events[0].source is None
        assert viewport.sync_active_camera_from_stage_change.calls == 1
    finally:
        _destroy_viewport(viewport)


def test_self_authored_camera_notice_does_not_trigger_stage_widget_recount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hierarchy_spy = _HierarchyModelChangeSpy(monkeypatch)
    adapter = _CountingUsdStageAdapter(_make_stage(extra_prim_count=8))
    widget = _CountingStageWidget(adapter)
    adapter.reset_metrics()
    widget.reset_metrics()

    renderer = _CountingRenderer()
    viewport = _make_viewport(adapter, renderer)
    try:
        viewport._select_camera_path("/World/Camera1")
        adapter.reset_metrics()
        viewport.reset_metrics()
        viewport._camera.orbit(0.05, 0.02)
        viewport._reset_camera_navigation_state()
        viewport.render(0.016)

        assert adapter.write_camera_pose.calls == 1
        assert adapter.flush.calls == 1
        assert adapter.notify.calls == 1
        assert hierarchy_spy.metrics.calls == 0
        assert widget.refresh_footer_counts.calls == 0
        assert widget.compute_stage_counts.calls == 0
        assert adapter.compute_visibility_metrics.calls == 0
        assert adapter.get_children_metrics.calls == 0
    finally:
        _destroy_viewport(viewport)
        widget.destroy()


def test_external_camera_xform_info_change_does_not_trigger_stage_widget_recount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hierarchy_spy = _HierarchyModelChangeSpy(monkeypatch)
    stage = _make_stage(extra_prim_count=8)
    adapter = _CountingUsdStageAdapter(stage)
    widget = _CountingStageWidget(adapter)
    adapter.reset_metrics()
    widget.reset_metrics()
    hierarchy_spy.reset_metrics()

    try:
        _set_camera_world_translation(stage, "/World/Camera1", (6.0, 3.0, 12.0))
        adapter._drain_scheduled_flushes()

        assert adapter.write_camera_pose.calls == 0
        assert adapter.flush.calls == 1
        assert adapter.notify.calls == 1
        assert adapter.events[0].source is None
        assert hierarchy_spy.metrics.calls == 0
        assert widget.refresh_footer_counts.calls == 0
        assert widget.compute_stage_counts.calls == 0
        assert adapter.compute_visibility_metrics.calls == 0
        assert adapter.get_children_metrics.calls == 0
    finally:
        widget.destroy()


def test_external_camera_focal_length_info_change_does_not_trigger_stage_widget_recount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hierarchy_spy = _HierarchyModelChangeSpy(monkeypatch)
    stage = _make_stage(extra_prim_count=8)
    adapter = _CountingUsdStageAdapter(stage)
    widget = _CountingStageWidget(adapter)
    adapter.reset_metrics()
    widget.reset_metrics()
    hierarchy_spy.reset_metrics()

    try:
        _set_camera_focal_length(stage, "/World/Camera1", 50.0)
        adapter._drain_scheduled_flushes()

        assert adapter.write_camera_pose.calls == 0
        assert adapter.flush.calls == 1
        assert adapter.notify.calls == 1
        assert adapter.events[0].source is None
        assert hierarchy_spy.metrics.calls == 0
        assert widget.refresh_footer_counts.calls == 0
        assert widget.compute_stage_counts.calls == 0
        assert adapter.compute_visibility_metrics.calls == 0
        assert adapter.get_children_metrics.calls == 0
    finally:
        widget.destroy()


def test_non_camera_property_info_change_triggers_stage_widget_recount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hierarchy_spy = _HierarchyModelChangeSpy(monkeypatch)
    stage = _make_stage(extra_prim_count=8)
    adapter = _CountingUsdStageAdapter(stage)
    widget = _CountingStageWidget(adapter)
    adapter.reset_metrics()
    widget.reset_metrics()
    hierarchy_spy.reset_metrics()

    try:
        _set_cube_size(stage, "/World/Prim_000", 2.0)
        adapter._drain_scheduled_flushes()

        assert adapter.notify.calls == 1
        assert hierarchy_spy.metrics.calls == 1
        assert widget.refresh_footer_counts.calls == 1
        assert widget.compute_stage_counts.calls == 1
        assert adapter.compute_visibility_metrics.calls > 0
        assert adapter.get_children_metrics.calls > 0
    finally:
        widget.destroy()


def test_camera_visibility_info_change_triggers_stage_widget_recount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hierarchy_spy = _HierarchyModelChangeSpy(monkeypatch)
    stage = _make_stage(extra_prim_count=8)
    adapter = _CountingUsdStageAdapter(stage)
    widget = _CountingStageWidget(adapter)
    adapter.reset_metrics()
    widget.reset_metrics()
    hierarchy_spy.reset_metrics()

    try:
        _set_prim_visibility(stage, "/World/Camera1", visible=False)
        adapter._drain_scheduled_flushes()

        assert adapter.notify.calls == 1
        assert hierarchy_spy.metrics.calls == 1
        assert widget.refresh_footer_counts.calls == 1
        assert widget.compute_stage_counts.calls == 1
        assert adapter.compute_visibility_metrics.calls > 0
        assert adapter.get_children_metrics.calls > 0
    finally:
        widget.destroy()


def test_camera_resync_event_triggers_stage_widget_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hierarchy_spy = _HierarchyModelChangeSpy(monkeypatch)
    adapter = _CountingUsdStageAdapter(_make_stage(extra_prim_count=8))
    widget = _CountingStageWidget(adapter)
    adapter.reset_metrics()
    widget.reset_metrics()
    hierarchy_spy.reset_metrics()

    try:
        adapter._notify(ChangeEvent(
            changed_paths=(),
            resynced_paths=("/World/Camera1",),
            event_type=ChangeEventType.RESYNC,
        ))

        assert adapter.notify.calls == 1
        assert hierarchy_spy.metrics.calls == 1
        assert widget.refresh_footer_counts.calls == 1
        assert widget.compute_stage_counts.calls == 1
        assert adapter.compute_visibility_metrics.calls > 0
        assert adapter.get_children_metrics.calls > 0
    finally:
        widget.destroy()

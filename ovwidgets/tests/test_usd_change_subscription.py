# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for UsdStageAdapter Tf.Notice subscription (Step 24).

Tests are skipped if pxr (usd-core) is not installed.
"""

import pytest
from ovui_data_adapters.common import VIEWPORT_CAMERA_POSE_SOURCE

try:
    from pxr import Sdf, Usd, UsdGeom
    HAS_USD = True
except ImportError:
    HAS_USD = False

pytestmark = pytest.mark.skipif(not HAS_USD, reason="usd-core not installed")


def _make_adapter(stage, call_later=None):
    from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
    return UsdStageAdapter(stage, call_later=call_later)


def _make_stage_with_world():
    stage = Usd.Stage.CreateInMemory()
    stage.DefinePrim("/World", "Xform")
    return stage


class TestTfNoticeDelivery:
    def test_define_prim_delivers_change_event(self):
        """Defining a prim via raw stage triggers Tf.Notice → subscriber gets ChangeEvent."""
        events = []
        deferred = []

        def fake_call_later(delay, fn):
            deferred.append(fn)

        stage = _make_stage_with_world()
        adapter = _make_adapter(stage, call_later=fake_call_later)
        sub = adapter.subscribe_changes(events.append)

        stage.DefinePrim("/World/NewPrim", "Xform")

        assert len(deferred) == 1, "flush should be scheduled exactly once"
        deferred[0]()

        assert len(events) == 1
        assert events[0].source is None
        all_paths = set(events[0].changed_paths) | set(events[0].resynced_paths)
        assert any("/World/NewPrim" in p for p in all_paths)

    def test_multiple_changes_batched_into_single_event(self):
        """Multiple USD changes before flush produce a single batched ChangeEvent."""
        events = []
        deferred = []

        def fake_call_later(delay, fn):
            deferred.append(fn)

        stage = _make_stage_with_world()
        adapter = _make_adapter(stage, call_later=fake_call_later)
        sub = adapter.subscribe_changes(events.append)

        stage.DefinePrim("/World/A", "Xform")
        stage.DefinePrim("/World/B", "Xform")

        # Only one flush scheduled — second DefinePrim sees _flush_scheduled=True
        assert len(deferred) == 1
        deferred[0]()

        assert len(events) == 1, "two changes → one batched event"
        all_paths = set(events[0].changed_paths) | set(events[0].resynced_paths)
        assert any("/World/A" in p for p in all_paths)
        assert any("/World/B" in p for p in all_paths)

    def test_suppression_blocks_notifications(self):
        """suppress_change_notifications() prevents Tf.Notice from being collected."""
        events = []
        deferred = []

        def fake_call_later(delay, fn):
            deferred.append(fn)

        stage = _make_stage_with_world()
        adapter = _make_adapter(stage, call_later=fake_call_later)
        sub = adapter.subscribe_changes(events.append)

        with adapter.suppress_change_notifications():
            stage.DefinePrim("/World/Hidden", "Xform")

        assert len(deferred) == 0, "no flush should be scheduled during suppression"
        assert len(events) == 0

    def test_cancel_subscription_stops_delivery(self):
        """After Subscription.cancel(), no further events are delivered."""
        events = []
        deferred = []

        def fake_call_later(delay, fn):
            deferred.append(fn)

        stage = _make_stage_with_world()
        adapter = _make_adapter(stage, call_later=fake_call_later)
        sub = adapter.subscribe_changes(events.append)
        sub.cancel()

        stage.DefinePrim("/World/AfterCancel", "Xform")

        # Even if a flush was scheduled, cancelled subscriber gets nothing
        for fn in deferred:
            fn()

        assert len(events) == 0

    def test_resynced_vs_changed_info_only_paths_distinguished(self):
        """Attribute-value-only change produces INFO_CHANGE; prim define produces RESYNC."""
        from ovui_data_adapters.common import ChangeEventType

        # Pre-create prim and attribute before subscribing so CreateAttribute
        # does not itself fire as an observable change
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/World", "Xform")
        attr = prim.CreateAttribute("val", Sdf.ValueTypeNames.Float)
        attr.Set(0.0)

        info_events = []
        resync_events = []
        deferred = []

        def fake_call_later(delay, fn):
            deferred.append(fn)

        adapter = _make_adapter(stage, call_later=fake_call_later)

        def on_change(evt):
            if evt.event_type == ChangeEventType.RESYNC:
                resync_events.append(evt)
            else:
                info_events.append(evt)

        sub = adapter.subscribe_changes(on_change)

        # Pure attribute-value set → only ChangedInfoOnly paths
        attr.Set(42.0)

        assert len(deferred) >= 1
        for fn in deferred:
            fn()
        deferred.clear()

        assert len(info_events) == 1
        assert len(resync_events) == 0
        assert info_events[0].event_type == ChangeEventType.INFO_CHANGE
        # resynced_paths must be empty for an info-only change
        assert len(info_events[0].resynced_paths) == 0

    def test_camera_pose_write_tags_viewport_source(self):
        from ovwidgets.viewport.camera_controller import CameraController

        events = []
        deferred = []

        def fake_call_later(delay, fn):
            deferred.append(fn)

        stage = _make_stage_with_world()
        UsdGeom.Camera.Define(stage, "/World/Camera")
        adapter = _make_adapter(stage, call_later=fake_call_later)
        sub = adapter.subscribe_changes(events.append)

        controller = CameraController()
        controller.focus(target=[0.0, 0.0, 0.0], distance=12.0)
        view, projection = controller.get_matrices(640, 360)

        assert adapter.write_camera_pose_from_matrices(
            "/World/Camera",
            view,
            projection,
            640,
            360,
            tuple(controller.state.target),
            source=VIEWPORT_CAMERA_POSE_SOURCE,
        )

        assert len(deferred) == 1
        deferred[0]()

        assert len(events) == 1
        assert events[0].source == VIEWPORT_CAMERA_POSE_SOURCE
        sub.cancel()

    def test_mixed_source_batch_drops_viewport_source(self):
        from ovwidgets.viewport.camera_controller import CameraController

        events = []
        deferred = []

        def fake_call_later(delay, fn):
            deferred.append(fn)

        stage = _make_stage_with_world()
        UsdGeom.Camera.Define(stage, "/World/Camera")
        external_attr = stage.GetPrimAtPath("/World").CreateAttribute(
            "external",
            Sdf.ValueTypeNames.Int,
        )
        adapter = _make_adapter(stage, call_later=fake_call_later)
        sub = adapter.subscribe_changes(events.append)

        controller = CameraController()
        controller.focus(target=[0.0, 0.0, 0.0], distance=12.0)
        view, projection = controller.get_matrices(640, 360)

        assert adapter.write_camera_pose_from_matrices(
            "/World/Camera",
            view,
            projection,
            640,
            360,
            tuple(controller.state.target),
            source=VIEWPORT_CAMERA_POSE_SOURCE,
        )
        external_attr.Set(1)

        assert len(deferred) == 1
        deferred[0]()

        assert len(events) == 1
        assert events[0].source is None
        sub.cancel()

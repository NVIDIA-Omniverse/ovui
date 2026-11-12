# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Sparse real USD notices must remain sparse at the renderer boundary."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter
from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
from pxr import Sdf, Usd, UsdGeom


@pytest.mark.parametrize("kind", ["camera", "non_camera", "relationship", "camera_relationship", "mixed", "removed", "projection"])
def test_camera_lens_live_updates_do_not_relax_structural_edits(kind):
    stage = Usd.Stage.CreateInMemory()
    prim = (UsdGeom.Xform if kind in {"non_camera", "relationship"} else UsdGeom.Camera).Define(stage, "/Camera").GetPrim()
    if kind in {"relationship", "camera_relationship"}:
        prim.CreateRelationship("focalLength", custom=False).SetTargets(["/Other"])
    else:
        prim.CreateAttribute("focalLength", Sdf.ValueTypeNames.Float,
                             custom=kind == "non_camera").Set(18)
    paths = ("/Camera.focalLength",)
    if kind == "mixed":
        UsdGeom.Sphere.Define(stage, "/Sphere").GetPurposeAttr().Set("guide")
        paths += ("/Sphere.purpose",)
    if kind == "removed":
        stage.RemovePrim("/Camera")
    if kind == "projection":
        UsdGeom.Camera(prim).GetProjectionAttr().Set("orthographic")
        paths = ("/Camera.projection",)
    renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    renderer._stage = stage
    result = renderer._stage_change_sync_decision(SimpleNamespace(), paths, (), Sdf)
    assert result == ("live" if kind == "camera" else "reload")


def test_ten_parent_transforms_and_visibility_do_not_replay_static_scene():
    stage = Usd.Stage.CreateInMemory()
    moving = []
    for i in range(10):
        parent = UsdGeom.Xform.Define(stage, f"/Parcel{i}")
        op = parent.AddTranslateOp()
        op.Set((0, 0, 0))
        parent.CreateVisibilityAttr().Set("inherited")
        moving.append((parent, op))
        for j in range(100):
            UsdGeom.Cube.Define(stage, f"/Parcel{i}/Detail{j}")
    stage_adapter = UsdStageAdapter(stage, call_later=lambda delay, cb: queued.append(cb))
    queued = []
    renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    renderer._stage = stage
    renderer._renderer = SimpleNamespace(write_attribute=Mock())
    renderer._render_product_path = None
    renderer._stop_native_frame_pacing = Mock()
    renderer._reload_live_root_snapshot = Mock(return_value=True)
    renderer._sync_ovrtx_root_snapshot_overlay_from_stage = Mock(return_value=True)
    renderer._write_prim_transforms_to_ovrtx = Mock()
    events = []

    def publish(event):
        events.append(event)
        renderer.notify_stage_changed(event)

    subscription = stage_adapter.subscribe_changes(publish)
    try:
        # A parent transform affects descendants through renderer hierarchy,
        # without writing every descendant's transform or visibility token.
        with Sdf.ChangeBlock():
            for parent, op in moving:
                op.Set((1, 2, 3))
                parent.GetVisibilityAttr().Set("invisible")
        assert len(queued) == 1
        queued.pop()()
        assert len(events) == 1
        assert len(events[0].changed_paths) == 20
        assert not events[0].resynced_paths
        assert renderer._write_prim_transforms_to_ovrtx.call_count == 1
        assert renderer._renderer.write_attribute.call_count == 10
        assert [path for _prim, path in renderer._write_prim_transforms_to_ovrtx.call_args.args[0]] == [
            f"/Parcel{i}" for i in range(10)
        ]
        renderer._reload_live_root_snapshot.assert_not_called()
        renderer._sync_ovrtx_root_snapshot_overlay_from_stage.assert_not_called()

        # Transform-only follow-up must not emit redundant visibility writes.
        renderer._renderer.write_attribute.reset_mock()
        with Sdf.ChangeBlock():
            for parent, op in moving:
                op.Set((2, 3, 4))
        queued.pop()()
        renderer._renderer.write_attribute.assert_not_called()
        assert renderer._write_prim_transforms_to_ovrtx.call_count == 2
        assert len(renderer._write_prim_transforms_to_ovrtx.call_args.args[0]) == 10

        # Deletion still requires conservative structural synchronization.
        stage.RemovePrim("/Parcel0")
        queued.pop()()
        renderer._reload_live_root_snapshot.assert_called_once()
    finally:
        subscription.cancel()
        stage_adapter.dispose()

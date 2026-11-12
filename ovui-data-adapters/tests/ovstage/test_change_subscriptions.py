# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Dirty-ordinal subscriptions for the ovstage provider."""

from __future__ import annotations

import pathlib
from typing import Any, Iterator

import numpy as np
import pytest

import ovui_data_adapters.ovstage.change_stream as change_stream_module
from ovui_data_adapters.common import ChangeEvent, ChangeEventType
from ovui_data_adapters.ovstage.change_stream import OvstageChangeStream
from ovui_data_adapters.ovstage._scene import (
    _KitTopologySnapshot,
    _reconcile_native_write_floor,
)
from ovui_data_adapters.ovstage._stage_write import StageWriteBatch, wait_operation
from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    create_provider_session,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes
from ovui_data_adapters.ovstage.stage_adapter import OvstageStageAdapter
from ovui_data_adapters.ovstage.transform_adapter import OvstageTransformAdapter


pytestmark = [
    pytest.mark.requires_ovstage,
]

_CAMERA_PATH = "/World/Cameras/MainCamera"


@pytest.fixture()
def ovstage_runtime():
    return load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )


@pytest.fixture()
def open_scene(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_runtime: Any,
) -> Iterator[Any]:
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(ovstage_static_scene_path))
    try:
        yield scene
    finally:
        session.shutdown_scene()


def _write_frame(stage: Any, fn) -> None:
    ordinal = stage.begin_frame()
    fn(ordinal)
    stage.end_frame(ordinal)


def _write_fixed(
    stage: Any,
    ordinal: int,
    path: str,
    attr_name: str,
    values: Any,
    *,
    lanes: int = 1,
) -> None:
    with StageWriteBatch(
        stage,
        [path],
        ordinal=ordinal,
        commit=False,
    ) as batch:
        batch.write_fixed(attr_name, values, lanes=lanes)


def _write_token(
    stage: Any,
    ordinal: int,
    path: str,
    attr_name: str,
    value: str,
) -> None:
    with StageWriteBatch(
        stage,
        [path],
        ordinal=ordinal,
        commit=False,
    ) as batch:
        batch.write_tokens(attr_name, [value])


def _poll_one(scene: Any, events: list[ChangeEvent]) -> ChangeEvent:
    prior_count = len(events)
    emitted = scene.change_stream.poll()
    assert len(emitted) == 1
    assert len(events) == prior_count + 1
    assert events[-1] is emitted[0]
    assert scene.change_stream.poll() == ()
    assert len(events) == prior_count + 1
    return events[-1]


class _SequentialDirtyStage:
    def __init__(self) -> None:
        self.current_ordinal = 0
        self._paths_by_handle = {
            10: ("/World/AddedMesh",),
            11: ("/World/RemovedMesh",),
            12: ("/World/TypeDirty",),
            13: ("/World/TransformDirty",),
            14: ("/World/VisibilityDirty",),
            15: ("/World/AttributeDirty",),
        }

    def get_prim_paths(self, handle: int) -> tuple[str, ...]:
        return self._paths_by_handle[int(handle)]

    def query_prims(
        self,
        ordinal: int,
        *,
        since_ordinal: int = 0,
        attribute_filter: list[str] | None = None,
    ) -> dict[str, Any]:
        attrs = tuple(attribute_filter or ())
        if int(ordinal) <= int(since_ordinal):
            return {"groups": ()}
        if attrs:
            handle_by_attr = {
                "usd-schemas": 12,
                "xformOp:translate": 13,
                "visibility": 14,
                "test:ratio": 15,
            }
            handle = handle_by_attr.get(attrs[0])
            if handle is None:
                return {"groups": ()}
            return {
                "groups": (
                    {
                        "prim_list_handle": handle,
                        "attributes": list(attrs),
                        "dirty_count": 1,
                        "dirty_indices": [0],
                        "added_indices": [],
                        "removed_indices": [],
                    },
                )
            }
        return {
            "groups": (
                {
                    "prim_list_handle": 10,
                    "attributes": ["usd-prim-type"],
                    "dirty_count": 1,
                    "dirty_indices": [0],
                    "added_indices": [0],
                    "removed_indices": [],
                },
                {
                    "prim_list_handle": 11,
                    "attributes": ["usd-prim-type"],
                    "dirty_count": 0,
                    "dirty_indices": [],
                    "added_indices": [],
                    "removed_indices": [0],
                },
                {
                    "prim_list_handle": 12,
                    "attributes": ["usd-schemas"],
                    "dirty_count": 1,
                    "dirty_indices": [0],
                    "added_indices": [],
                    "removed_indices": [],
                },
                {
                    "prim_list_handle": 13,
                    "attributes": ["xformOp:translate"],
                    "dirty_count": 1,
                    "dirty_indices": [0],
                    "added_indices": [],
                    "removed_indices": [],
                },
                {
                    "prim_list_handle": 14,
                    "attributes": ["visibility"],
                    "dirty_count": 1,
                    "dirty_indices": [0],
                    "added_indices": [],
                    "removed_indices": [],
                },
                {
                    "prim_list_handle": 15,
                    "attributes": ["test:ratio"],
                    "dirty_count": 1,
                    "dirty_indices": [0],
                    "added_indices": [],
                    "removed_indices": [],
                },
            )
        }


class _SequentialDirtyScene:
    initial_ordinal = 0
    is_open = True

    def __init__(self) -> None:
        self._stage = _SequentialDirtyStage()
        self._change_stream = OvstageChangeStream(self)

    @property
    def current_ordinal(self) -> int:
        return int(self._stage.current_ordinal)

    @property
    def change_stream(self) -> OvstageChangeStream:
        return self._change_stream


class _RetryFloorOperation:
    def __init__(self, value: int) -> None:
        self._value = int(value)

    def wait(self) -> None:
        return None

    def fetch(self) -> int:
        return self._value

    def release(self) -> "_RetryFloorOperation":
        return _RetryFloorOperation(self._value)


class _RetryNativeStage:
    def __init__(self) -> None:
        self.current_ordinal = 0
        self.committed_ordinal = 0

    def get_attribute_write_floor(self) -> _RetryFloorOperation:
        return _RetryFloorOperation(self.committed_ordinal)

    def read_attributes(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("snapshot boundary was not patched")

    def fetch_read_next(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("snapshot boundary was not patched")


class _RetryNativeScene:
    initial_ordinal = 0
    is_open = True

    def __init__(self, stage: _RetryNativeStage) -> None:
        self._stage = stage
        self._topology_revision = 0
        self._change_stream = OvstageChangeStream(self)

    @property
    def current_ordinal(self) -> int:
        return _reconcile_native_write_floor(self._stage)

    @property
    def change_stream(self) -> OvstageChangeStream:
        return self._change_stream


def test_failed_external_topology_snapshot_retries_same_floor(monkeypatch) -> None:
    stage = _RetryNativeStage()
    baseline = _KitTopologySnapshot(0, ("/World",))
    replacement = _KitTopologySnapshot(
        1,
        ("/World", "/World/AddedMesh"),
    )
    stage._ovui_kit_topology_snapshot = baseline
    attempts = 0

    def snapshot(current_stage: Any, ordinal: int) -> _KitTopologySnapshot:
        nonlocal attempts
        assert current_stage is stage
        if int(ordinal) == 0:
            return baseline
        attempts += 1
        if attempts == 1:
            raise RuntimeError("snapshot failed")
        if attempts == 2:
            # No whole-stage surface answered.  This reports as an ordinary
            # empty result unless the unreadable case is carried through.
            return _KitTopologySnapshot(int(ordinal), (), readable=False)
        current_stage._ovui_kit_topology_snapshot = replacement
        return replacement

    monkeypatch.setattr(change_stream_module, "_kit_topology_snapshot", snapshot)
    monkeypatch.setattr(
        change_stream_module,
        "_native_dirty_paths_by_attribute",
        lambda *_args, **_kwargs: (
            {"usd-path": {"/World/AddedMesh"}},
            True,
        ),
    )
    scene = _RetryNativeScene(stage)
    stream = scene.change_stream
    monkeypatch.setattr(stream, "_physics_transform_paths_for_range", lambda **_kwargs: ())
    stage.committed_ordinal = 1

    with pytest.raises(RuntimeError, match="snapshot failed"):
        stream.poll()

    assert stream.last_ordinal == 0
    assert stream._topology_paths == {"/World"}
    assert stage._ovui_kit_topology_snapshot is baseline

    # A topology that could not be read must hold exactly the same ground as
    # one that raised: reporting it as an empty stage would publish /World as
    # removed, move the floor past this ordinal, and never re-read it.
    assert stream.poll() == ()
    assert stream.last_ordinal == 0
    assert stream._topology_paths == {"/World"}
    assert stage._ovui_kit_topology_snapshot is baseline

    emitted = stream.poll()

    assert emitted == (
        ChangeEvent(
            changed_paths=(),
            resynced_paths=("/World/AddedMesh",),
            event_type=ChangeEventType.RESYNC,
            source="ovstage:added",
        ),
    )
    assert stream.last_ordinal == 1
    assert stream._topology_paths == {"/World", "/World/AddedMesh"}
    assert stage._ovui_kit_topology_snapshot is replacement


def test_value_only_native_commit_reuses_topology_snapshot(monkeypatch) -> None:
    stage = _RetryNativeStage()
    baseline = _KitTopologySnapshot(0, ("/World", "/World/Camera"))
    stage._ovui_kit_topology_snapshot = baseline
    scene = _RetryNativeScene(stage)
    stream = scene.change_stream
    monkeypatch.setattr(
        stream,
        "_physics_transform_paths_for_range",
        lambda **_kwargs: (),
    )
    monkeypatch.setattr(
        change_stream_module,
        "_native_dirty_paths_by_attribute",
        lambda *_args, **_kwargs: (
            {
                "focalLength": {"/World/Camera"},
                "usd-path": set(),
            },
            True,
        ),
    )

    def unexpected_topology_scan(*_args: Any, **_kwargs: Any) -> set[str]:
        raise AssertionError("value-only commits must not scan whole-stage topology")

    monkeypatch.setattr(
        change_stream_module,
        "_native_topology_paths",
        unexpected_topology_scan,
    )
    stage.committed_ordinal = 1

    emitted = stream.poll()

    assert emitted == (
        ChangeEvent(
            changed_paths=("/World/Camera",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            source="ovstage:attribute",
        ),
    )
    assert stream.last_ordinal == 1
    assert stream._topology_paths == {"/World", "/World/Camera"}
    assert baseline.ordinal == 1


def _unreadable_snapshot_scene(monkeypatch, readable_paths: tuple[str, ...]):
    """A native scene whose topology starts unreadable and can be recovered."""

    stage = _RetryNativeStage()
    readable = _KitTopologySnapshot(0, readable_paths)
    state = {"readable": False}

    def snapshot(current_stage: Any, ordinal: int) -> _KitTopologySnapshot:
        if not state["readable"]:
            return _KitTopologySnapshot(int(ordinal), (), readable=False)
        current_stage._ovui_kit_topology_snapshot = readable
        return readable

    monkeypatch.setattr(change_stream_module, "_kit_topology_snapshot", snapshot)
    monkeypatch.setattr(
        change_stream_module,
        "_native_dirty_paths_by_attribute",
        lambda *_args, **_kwargs: ({}, True),
    )
    scene = _RetryNativeScene(stage)
    monkeypatch.setattr(
        scene.change_stream,
        "_physics_transform_paths_for_range",
        lambda **_kwargs: (),
    )
    return stage, scene, state


def test_stream_built_while_topology_unreadable_recovers_on_the_same_floor(
    monkeypatch,
) -> None:
    """Construction during an outage must not spend the recovery floor.

    A stream built before any topology could be read has no baseline.  If it
    keeps the floor anyway, ``poll()`` short-circuits as already-delivered and
    the stage stays empty until some unrelated edit moves the ordinal — which
    then reports the whole stage as newly added.
    """

    stage, scene, state = _unreadable_snapshot_scene(
        monkeypatch,
        ("/World", "/World/Mesh"),
    )
    stream = scene.change_stream
    delivered: list[ChangeEvent] = []
    stream.subscribe_stage(delivered.append)

    assert stream._topology_paths == set()
    assert stream.last_ordinal == 0

    state["readable"] = True
    adopted = stream.poll()

    assert stream._topology_paths == {"/World", "/World/Mesh"}
    assert stage._ovui_kit_topology_snapshot.path_order == ("/World", "/World/Mesh")
    # Exactly one rootmost resync so a model materialized during the outage
    # re-reads; naming both paths would be the bulk-add this must not become.
    assert [event.resynced_paths for event in adopted] == [("/World",)]
    assert delivered == list(adopted)

    stage.committed_ordinal = 1
    assert stream.poll() == ()
    assert len(delivered) == 1


def test_publication_while_topology_unreadable_is_not_replayed_after_recovery(
    monkeypatch,
) -> None:
    """An unreconcilable publication must stay exactly-once.

    ``publish_resync_change`` delivers its paths itself.  When the native
    topology cannot be read at that moment the set it would be reconciled
    against is stale, so diffing against it later replays those same paths as
    native additions on top of the delivery already made.
    """

    stage, scene, state = _unreadable_snapshot_scene(
        monkeypatch,
        ("/World", "/World/Published"),
    )
    stream = scene.change_stream
    delivered: list[ChangeEvent] = []
    stream.subscribe_stage(delivered.append)

    stage.committed_ordinal = 1
    published = stream.publish_resync_change(["/World/Published"], source="probe")

    assert published is not None
    assert published.resynced_paths == ("/World/Published",)
    assert stream.last_ordinal == 1

    state["readable"] = True
    stage.committed_ordinal = 2
    recovered = stream.poll()

    assert stream._topology_paths == {"/World", "/World/Published"}
    # The published path is never named again; recovery only resyncs the root
    # so an already-materialized model re-reads it.
    assert [event.resynced_paths for event in recovered] == [("/World",)]
    assert [event.resynced_paths for event in delivered] == [
        ("/World/Published",),
        ("/World",),
    ]


def test_external_value_only_commit_emits_no_resync(open_scene: Any) -> None:
    scene = open_scene
    stage = scene.native_stage
    path = "/World/Cameras/MainCamera"
    ordinal = int(scene.current_ordinal) + 1
    _write_fixed(
        stage,
        ordinal,
        path,
        "focalLength",
        np.asarray([61.0], dtype=np.float32),
    )
    wait_operation(stage.advance_write_floor(ordinal))

    emitted = scene.change_stream.poll()

    assert emitted
    assert all(event.event_type is not ChangeEventType.RESYNC for event in emitted)
    assert scene.change_stream.last_ordinal == ordinal


def test_subscribers_receive_classified_events_once_per_dirty_group(open_scene: Any) -> None:
    scene = open_scene
    stage = scene._stage
    stage_adapter = OvstageStageAdapter(scene)
    property_adapter = OvstagePropertyAdapter(
        scene,
        [_CAMERA_PATH],
        stage_adapter=stage_adapter,
    )
    stage_events: list[ChangeEvent] = []
    property_refreshes: list[str] = []

    stage_sub = stage_adapter.subscribe_changes(stage_events.append)
    property_sub = property_adapter.subscribe_changes(lambda: property_refreshes.append("refresh"))

    _write_frame(
        stage,
        lambda ordinal: stage.create_prims(
            ordinal,
            ["/World/SubscriptionCases/NewMesh"],
            "Mesh",
        ),
    )
    event = _poll_one(scene, stage_events)
    assert event.event_type is ChangeEventType.RESYNC
    assert event.source == "ovstage:added"
    assert event.resynced_paths == ("/World/SubscriptionCases/NewMesh",)
    assert property_refreshes == []

    _write_frame(
        stage,
        lambda ordinal: _write_fixed(
            stage,
            ordinal,
            "/World/TransformCases/TranslateOnly",
            "omni:xform",
            np.asarray(
                [
                    1.0, 0.0, 0.0, 0.0,
                    0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, 1.0, 0.0,
                    2.0, 4.0, 6.0, 1.0,
                ],
                dtype=np.float64,
            ),
            lanes=16,
        ),
    )
    event = _poll_one(scene, stage_events)
    assert event.event_type is ChangeEventType.INFO_CHANGE
    assert event.source == "ovstage:transform"
    assert event.changed_paths == ("/World/TransformCases/TranslateOnly",)
    assert property_refreshes == []

    _write_frame(
        stage,
        lambda ordinal: _write_token(
            stage,
            ordinal,
            "/World/SubscriptionCases/NewMesh",
            "visibility",
            "invisible",
        ),
    )
    event = _poll_one(scene, stage_events)
    assert event.event_type is ChangeEventType.INFO_CHANGE
    assert event.source == "ovstage:visibility"
    assert event.changed_paths == ("/World/SubscriptionCases/NewMesh",)
    assert property_refreshes == []

    _write_frame(
        stage,
        lambda ordinal: _write_fixed(
            stage,
            ordinal,
            _CAMERA_PATH,
            "focalLength",
            np.asarray([50.0], dtype=np.float32),
        ),
    )
    event = _poll_one(scene, stage_events)
    assert event.event_type is ChangeEventType.INFO_CHANGE
    assert event.source == "ovstage:attribute"
    assert event.changed_paths == (_CAMERA_PATH,)
    assert property_refreshes == ["refresh"]

    _write_frame(
        stage,
        lambda ordinal: stage.delete_prims(
            ordinal,
            ["/World/SubscriptionCases/NewMesh"],
        ),
    )
    event = _poll_one(scene, stage_events)
    assert event.event_type is ChangeEventType.RESYNC
    assert event.source == "ovstage:removed"
    assert event.resynced_paths == ("/World/SubscriptionCases/NewMesh",)
    assert property_refreshes == ["refresh"]

    stage_sub.cancel()
    property_sub.cancel()


def test_poll_classifies_each_dirty_group_and_delivers_no_duplicates() -> None:
    scene = _SequentialDirtyScene()
    scene._stage.current_ordinal = 1
    stage_events: list[ChangeEvent] = []
    property_refreshes: list[str] = []
    stage_sub = scene.change_stream.subscribe_stage(stage_events.append)
    property_sub = scene.change_stream.subscribe_property(
        ("/World/AttributeDirty",),
        lambda: property_refreshes.append("refresh"),
    )

    emitted = scene.change_stream.poll()

    assert stage_events == list(emitted)
    assert [(event.event_type, event.source) for event in emitted] == [
        (ChangeEventType.RESYNC, "ovstage:added"),
        (ChangeEventType.RESYNC, "ovstage:removed"),
        (ChangeEventType.RESYNC, "ovstage:topology"),
        (ChangeEventType.INFO_CHANGE, "ovstage:transform"),
        (ChangeEventType.INFO_CHANGE, "ovstage:visibility"),
        (ChangeEventType.INFO_CHANGE, "ovstage:attribute"),
    ]
    assert [event.resynced_paths for event in emitted[:3]] == [
        ("/World/AddedMesh",),
        ("/World/RemovedMesh",),
        ("/World/TypeDirty",),
    ]
    assert [event.changed_paths for event in emitted[3:]] == [
        ("/World/TransformDirty",),
        ("/World/VisibilityDirty",),
        ("/World/AttributeDirty",),
    ]
    assert property_refreshes == ["refresh"]
    assert scene.change_stream.poll() == ()
    assert stage_events == list(emitted)

    stage_sub.cancel()
    property_sub.cancel()


def test_suppression_drops_poll_driven_events(open_scene: Any) -> None:
    scene = open_scene
    stage = scene._stage
    stage_adapter = OvstageStageAdapter(scene)
    stage_events: list[ChangeEvent] = []
    subscription = stage_adapter.subscribe_changes(stage_events.append)

    with stage_adapter.suppress_change_notifications():
        _write_frame(
            stage,
            lambda ordinal: _write_fixed(
                stage,
                ordinal,
                _CAMERA_PATH,
                "focalLength",
                np.asarray([55.0], dtype=np.float32),
            ),
        )
        assert scene.change_stream.poll() == ()

    assert scene.change_stream.poll() == ()
    assert stage_events == []
    subscription.cancel()


def test_notify_transform_changed_preserves_source_after_suppressed_write(
    open_scene: Any,
) -> None:
    scene = open_scene
    stage_adapter = OvstageStageAdapter(scene)
    transform_adapter = OvstageTransformAdapter(scene)
    stage_events: list[ChangeEvent] = []
    subscription = stage_adapter.subscribe_changes(stage_events.append)

    with stage_adapter.suppress_change_notifications():
        transform_adapter.set_local_transform(
            "/World/TransformCases/NestedParent",
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [5.0, 6.0, 7.0, 1.0],
            ],
        )
        assert scene.change_stream.poll() == ()

    stage_adapter.notify_transform_changed(
        ["/World/TransformCases/NestedParent"],
        source="viewport-manipulator",
    )

    assert len(stage_events) == 1
    assert stage_events[0].event_type is ChangeEventType.INFO_CHANGE
    assert stage_events[0].source == "viewport-manipulator"
    assert "/World/TransformCases/NestedParent" in stage_events[0].changed_paths
    assert scene.change_stream.poll() == ()
    subscription.cancel()


def test_notify_transform_changed_publishes_after_poll_drops_preview(
    open_scene: Any,
) -> None:
    scene = open_scene
    path = "/World/TransformCases/NestedParent"
    moved = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [5.0, 6.0, 7.0, 1.0],
    ]
    scheduled: list[Any] = []

    def run_scheduled() -> None:
        callbacks = list(scheduled)
        scheduled.clear()
        for callback in callbacks:
            callback()

    stage_adapter = OvstageStageAdapter(
        scene,
        call_later=lambda _delay, callback: scheduled.append(callback),
    )
    transform_adapter = OvstageTransformAdapter(scene)
    stage_events: list[ChangeEvent] = []
    subscription = stage_adapter.subscribe_changes(stage_events.append)

    # A gizmo drag: the live preview writes the final matrix while
    # notifications are suppressed, and the scheduled poll drops that range.
    with scene.change_stream.suppress_notifications():
        transform_adapter.set_local_transform(path, moved)
    run_scheduled()
    assert stage_events == []

    # Mouse release: the commit writes the same matrix, so no ordinal is added.
    ordinal = scene.current_ordinal
    with stage_adapter.suppress_change_notifications():
        transform_adapter.set_local_transform(path, moved)
    assert scene.current_ordinal == ordinal

    stage_adapter.notify_transform_changed([path], source="viewport-manipulator")
    run_scheduled()

    assert len(stage_events) == 1
    assert stage_events[0].source == "viewport-manipulator"
    assert path in stage_events[0].changed_paths

    # The move is delivered now; a repeated hook call must not deliver it again.
    stage_adapter.notify_transform_changed([path], source="viewport-manipulator")
    run_scheduled()
    assert len(stage_events) == 1
    subscription.cancel()

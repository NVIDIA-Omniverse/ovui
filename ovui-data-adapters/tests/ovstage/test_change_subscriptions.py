# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this software, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Dirty-ordinal subscriptions for the ovstage provider."""

from __future__ import annotations

import pathlib
from typing import Any, Iterator

import numpy as np
import pytest

from ovui_data_adapters.common import ChangeEvent, ChangeEventType
from ovui_data_adapters.ovstage.change_stream import OvstageChangeStream
from ovui_data_adapters.ovstage._stage_write import StageWriteBatch
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

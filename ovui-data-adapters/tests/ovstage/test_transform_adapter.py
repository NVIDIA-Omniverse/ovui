# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovstage TransformAdapter runtime matrix reads and writes."""

from __future__ import annotations

import pathlib
import struct
from typing import Any, Iterator

import pytest

from ovui_data_adapters.common import ChangeEvent, ChangeEventType
from ovui_data_adapters.ovstage._scene import OvstageScene
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

_TRANSLATE_ONLY = "/World/TransformCases/TranslateOnly"
_MATRIX_ONLY = "/World/TransformCases/MatrixOnly"
_NESTED_PARENT = "/World/TransformCases/NestedParent"
_NESTED_CHILD = "/World/TransformCases/NestedParent/NestedChild"


@pytest.fixture()
def ovstage_runtime():
    return load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )


@pytest.fixture()
def ovstage_scene(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_runtime: Any,
) -> Iterator[OvstageScene]:
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(ovstage_static_scene_path))
    try:
        yield scene
    finally:
        session.shutdown_scene()


def test_transform_reads_return_local_and_world_matrices(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = OvstageTransformAdapter(ovstage_scene)

    assert _translation(adapter.get_local_transform(_TRANSLATE_ONLY)) == pytest.approx(
        (1.0, 2.0, 3.0)
    )
    assert _translation(adapter.get_world_transform(_TRANSLATE_ONLY)) == pytest.approx(
        (1.0, 2.0, 3.0)
    )
    assert _translation(adapter.get_local_transform(_MATRIX_ONLY)) == pytest.approx(
        (4.0, 5.0, 6.0)
    )


def test_runtime_local_write_updates_local_and_propagated_child_world_matrix(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = OvstageTransformAdapter(ovstage_scene)
    stage = ovstage_scene._stage
    before_ordinal = int(stage.current_ordinal)
    child_initial_world = adapter.get_world_transform(_NESTED_CHILD)
    new_parent_local = _translation_matrix(3.0, 20.0, 5.0)

    adapter.set_local_transform(_NESTED_PARENT, new_parent_local)

    assert int(stage.current_ordinal) > before_ordinal
    assert _translation(adapter.get_local_transform(_NESTED_PARENT)) == pytest.approx(
        (3.0, 20.0, 5.0)
    )
    assert _translation(adapter.get_world_transform(_NESTED_PARENT)) == pytest.approx(
        (3.0, 20.0, 5.0)
    )
    assert _translation(adapter.get_world_transform(_NESTED_CHILD)) == pytest.approx(
        (3.0, 20.0, 7.0)
    )
    assert _translation(adapter.get_world_transform(_NESTED_CHILD)) != pytest.approx(
        _translation(child_initial_world)
    )
    assert _translation(_mirrored_matrix(stage, _NESTED_CHILD, "worldMatrix")) == pytest.approx(
        (3.0, 20.0, 7.0)
    )


def test_runtime_local_write_emits_dirty_transform_event_after_world_update(
    ovstage_scene: OvstageScene,
) -> None:
    stage_adapter = OvstageStageAdapter(ovstage_scene)
    transform_adapter = OvstageTransformAdapter(ovstage_scene)
    stage_events: list[ChangeEvent] = []
    subscription = stage_adapter.subscribe_changes(stage_events.append)

    transform_adapter.set_local_transform(_NESTED_PARENT, _translation_matrix(-1.0, 9.0, 4.0))
    emitted = ovstage_scene.change_stream.poll()

    assert emitted == ()
    assert len(stage_events) == 1
    event = stage_events[0]
    assert event.event_type is ChangeEventType.INFO_CHANGE
    # Native transform writes publish their own event source; there is no
    # backing-USD synchronization channel in the native-only adapter.
    assert event.source == "transform:set"
    assert _NESTED_PARENT in event.changed_paths
    assert _NESTED_CHILD in event.changed_paths
    assert _translation(transform_adapter.get_world_transform(_NESTED_CHILD)) == pytest.approx(
        (-1.0, 9.0, 6.0)
    )
    subscription.cancel()


def test_stage_notify_transform_changed_drains_dirty_stream_once(
    ovstage_scene: OvstageScene,
) -> None:
    stage_adapter = OvstageStageAdapter(ovstage_scene)
    transform_adapter = OvstageTransformAdapter(ovstage_scene)
    stage_events: list[ChangeEvent] = []
    subscription = stage_adapter.subscribe_changes(stage_events.append)

    with stage_adapter.suppress_change_notifications():
        transform_adapter.set_local_transform(
            _NESTED_PARENT,
            _translation_matrix(8.0, 10.0, -3.0),
        )
    stage_adapter.notify_transform_changed([_NESTED_PARENT], source="viewport-manipulator")

    assert len(stage_events) == 1
    assert stage_events[0].source == "viewport-manipulator"
    assert _NESTED_PARENT in stage_events[0].changed_paths
    assert _NESTED_CHILD in stage_events[0].changed_paths
    assert ovstage_scene.change_stream.poll() == ()
    subscription.cancel()


def test_transform_eligibility_is_conservative_but_allows_runtime_matrices(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = OvstageTransformAdapter(ovstage_scene)

    assert adapter.can_transform(_TRANSLATE_ONLY) is True
    assert adapter.can_transform(_NESTED_CHILD) is True
    assert adapter.can_transform("/") is False
    assert adapter.can_transform("/World/DoesNotExist") is False



def _translation_matrix(x: float, y: float, z: float) -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [float(x), float(y), float(z), 1.0],
    ]


def _translation(matrix: list[list[float]]) -> tuple[float, float, float]:
    return (float(matrix[3][0]), float(matrix[3][1]), float(matrix[3][2]))


def _mirrored_matrix(stage: Any, path: str, attr_name: str) -> list[list[float]]:
    raw = bytes(stage.read_attribute(int(stage.current_ordinal), [path], attr_name))
    values = struct.unpack("<16d", raw)
    return [list(values[index:index + 4]) for index in range(0, 16, 4)]

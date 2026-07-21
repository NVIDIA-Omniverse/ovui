# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""OVStage runtime-safe native property writes."""

from __future__ import annotations

import pathlib
import struct
from typing import Any, Iterator

import pytest

from ovui_data_adapters.common import Command
from ovui_data_adapters.ovstage._scene import OvstageScene
from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    create_provider_session,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes
from ovui_data_adapters.ovstage.stage_adapter import OvstageStageAdapter


pytestmark = [
    pytest.mark.requires_ovstage,
]

_CAMERA_PATH = "/World/Cameras/MainCamera"
_MESH_PATH = "/World/Hierarchy/GroupB/TriangleMesh"


class _RecordingUndoManager:
    def __init__(self) -> None:
        self.commands: list[Command] = []
        self.open_groups = 0

    def begin_group(self, _label: str) -> None:
        self.open_groups += 1

    def push(self, command: Command) -> None:
        command.do()
        self.commands.append(command)

    def end_group(self) -> None:
        self.open_groups -= 1


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


def _raw(stage: Any, path: str, attr_name: str) -> bytes:
    return bytes(stage.read_attribute(int(stage.current_ordinal), [path], attr_name))


def _unpack_float(stage: Any, path: str, attr_name: str) -> float:
    return struct.unpack("<f", _raw(stage, path, attr_name))[0]


def test_runtime_safe_numeric_write_updates_ovstage_and_adapter_readback(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = OvstagePropertyAdapter(ovstage_scene, [_CAMERA_PATH])
    stage = ovstage_scene._stage
    starting_ordinal = int(stage.current_ordinal)

    adapter.begin_edit("focalLength")
    adapter.set_value("focalLength", 31.0)
    adapter.end_edit("focalLength")

    assert adapter.get_value("focalLength") == pytest.approx(31.0)
    assert _unpack_float(stage, _CAMERA_PATH, "focalLength") == pytest.approx(31.0)
    assert int(stage.current_ordinal) > starting_ordinal


def test_runtime_safe_vector_write_updates_live_mirrored_bytes(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = OvstagePropertyAdapter(ovstage_scene, [_CAMERA_PATH])
    stage = ovstage_scene._stage

    adapter.begin_edit("clippingRange")
    adapter.set_value("clippingRange", (4.0, 5000.0))
    adapter.end_edit("clippingRange")

    assert adapter.get_value("clippingRange") == pytest.approx((4.0, 5000.0))
    assert struct.unpack("<2f", _raw(stage, _CAMERA_PATH, "clippingRange")) == pytest.approx(
        (4.0, 5000.0)
    )


def test_runtime_safe_write_notifies_property_subscribers_after_ovstage_poll(
    ovstage_scene: OvstageScene,
) -> None:
    stage_adapter = OvstageStageAdapter(ovstage_scene)
    adapter = OvstagePropertyAdapter(
        ovstage_scene,
        [_CAMERA_PATH],
        stage_adapter=stage_adapter,
    )
    refreshes: list[str] = []
    subscription = adapter.subscribe_changes(lambda: refreshes.append("refresh"))

    adapter.begin_edit("focalLength")
    adapter.set_value("focalLength", 50.0)
    adapter.end_edit("focalLength")
    emitted = ovstage_scene.change_stream.poll()

    assert refreshes == ["refresh"]
    # The native value write publishes its change event for the known path
    # immediately; the subsequent poll must not duplicate the event.
    assert emitted == ()
    assert adapter.get_value("focalLength") == pytest.approx(50.0)
    subscription.cancel()


def test_runtime_safe_property_edit_records_undoable_runtime_command(
    ovstage_scene: OvstageScene,
) -> None:
    undo_manager = _RecordingUndoManager()
    adapter = OvstagePropertyAdapter(
        ovstage_scene,
        [_CAMERA_PATH],
        undo_manager=undo_manager,
    )

    adapter.begin_edit("focalLength")
    adapter.set_value("focalLength", 42.0)
    adapter.end_edit("focalLength")

    assert undo_manager.open_groups == 0
    assert len(undo_manager.commands) == 1
    assert adapter.get_value("focalLength") == pytest.approx(42.0)

    undo_manager.commands[0].undo()
    assert adapter.get_value("focalLength") == pytest.approx(35.0)

    undo_manager.commands[0].redo()
    assert adapter.get_value("focalLength") == pytest.approx(42.0)


def test_native_array_property_write_persists_exactly(
    ovstage_scene: OvstageScene,
) -> None:
    # Native value authoring supports array columns; the old hybrid design
    # kept USD-owned arrays read-only, which no longer applies.
    adapter = OvstagePropertyAdapter(ovstage_scene, [_MESH_PATH])
    before = adapter.get_value("faceVertexIndices")
    assert before == (0, 1, 2)

    metadata = adapter.get_attribute_metadata("faceVertexIndices")
    assert metadata.value_type == "array"
    adapter.set_value("faceVertexIndices", (2, 1, 0))

    assert adapter.get_value("faceVertexIndices") == (2, 1, 0)

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

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
from ovui_data_adapters.services.undo import UndoManager


pytestmark = [
    pytest.mark.requires_ovstage,
]

_CAMERA_PATH = "/World/Cameras/MainCamera"
_MESH_PATH = "/World/Hierarchy/GroupB/TriangleMesh"
_SPHERE_PATH = "/World/Hierarchy/GroupA/BallA"


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


def _unpack_double(stage: Any, path: str, attr_name: str) -> float:
    return struct.unpack("<d", _raw(stage, path, attr_name))[0]


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


def test_numeric_drag_authors_native_intermediates_and_undoes_as_one_edit(
    ovstage_scene: OvstageScene,
) -> None:
    undo_manager = UndoManager()
    adapter = OvstagePropertyAdapter(
        ovstage_scene,
        [_SPHERE_PATH],
        undo_manager=undo_manager,
    )
    stage = ovstage_scene._stage
    original = _unpack_double(stage, _SPHERE_PATH, "radius")
    starting_ordinal = int(stage.current_ordinal)

    assert adapter.get_attribute_metadata("radius").change_on_edit_end is False

    adapter.begin_edit("radius")
    adapter.set_value("radius", 0.75)
    first_ordinal = int(stage.current_ordinal)
    assert first_ordinal > starting_ordinal
    assert _unpack_double(stage, _SPHERE_PATH, "radius") == pytest.approx(0.75)
    assert adapter.get_value("radius") == pytest.approx(0.75)

    adapter.set_value("radius", 1.0)
    second_ordinal = int(stage.current_ordinal)
    assert second_ordinal > first_ordinal
    assert _unpack_double(stage, _SPHERE_PATH, "radius") == pytest.approx(1.0)
    assert adapter.get_value("radius") == pytest.approx(1.0)

    adapter.end_edit("radius")
    assert undo_manager.undo() is True
    assert undo_manager.can_undo() is False
    assert _unpack_double(stage, _SPHERE_PATH, "radius") == pytest.approx(original)
    assert adapter.get_value("radius") == pytest.approx(original)


def test_numeric_edit_ending_on_start_value_records_no_undo_step(
    ovstage_scene: OvstageScene,
) -> None:
    undo_manager = UndoManager()
    adapter = OvstagePropertyAdapter(
        ovstage_scene,
        [_SPHERE_PATH],
        undo_manager=undo_manager,
    )
    stage = ovstage_scene._stage
    original = _unpack_double(stage, _SPHERE_PATH, "radius")

    # Typing 9 then Escape: the field writes 9, then the start value.
    adapter.begin_edit("radius")
    adapter.set_value("radius", 9.0)
    assert _unpack_double(stage, _SPHERE_PATH, "radius") == pytest.approx(9.0)
    adapter.set_value("radius", original)
    adapter.end_edit("radius")

    assert undo_manager.can_undo() is False
    assert _unpack_double(stage, _SPHERE_PATH, "radius") == pytest.approx(original)


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



_TWO_CAMERAS_USDA = """#usda 1.0
(
    defaultPrim = "World"
    upAxis = "Y"
)

def Xform "World"
{
    def Camera "CameraA"
    {
        float2 clippingRange = (1, 1000)
    }

    def Camera "CameraB"
    {
        float2 clippingRange = (5, 2000)
    }
}
"""


def _clipping_range(stage: Any, path: str) -> tuple[float, ...]:
    return struct.unpack("<2f", _raw(stage, path, "clippingRange"))


def test_one_channel_write_keeps_the_other_channel_of_each_prim(
    tmp_path: pathlib.Path,
    ovstage_runtime: Any,
) -> None:
    scene_path = tmp_path / "two_cameras.usda"
    scene_path.write_text(_TWO_CAMERAS_USDA)
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(scene_path))
    try:
        undo_manager = UndoManager()
        paths = ["/World/CameraA", "/World/CameraB"]
        adapter = OvstagePropertyAdapter(scene, paths, undo_manager=undo_manager)
        stage = scene._stage
        assert adapter.get_per_component_ambiguity("clippingRange") == [True, True]

        adapter.begin_edit("clippingRange")
        adapter.set_component_value("clippingRange", 0, 3.0)
        adapter.end_edit("clippingRange")

        assert _clipping_range(stage, paths[0]) == pytest.approx((3.0, 1000.0))
        assert _clipping_range(stage, paths[1]) == pytest.approx((3.0, 2000.0))
        assert adapter.get_per_component_ambiguity("clippingRange") == [False, True]
        # The vector of the first camera: the row shows X = 3 and Y "Mixed".
        assert adapter.get_value("clippingRange") == pytest.approx((3.0, 1000.0))

        undo_manager.undo()
        assert _clipping_range(stage, paths[0]) == pytest.approx((1.0, 1000.0))
        assert _clipping_range(stage, paths[1]) == pytest.approx((5.0, 2000.0))
    finally:
        session.shutdown_scene()



def test_a_matrix_part_write_of_a_transform_matrix_is_refused_with_the_cause(
    ovstage_scene: OvstageScene,
) -> None:
    """ovstage refuses writes of its transform matrices (localMatrix) through
    the property surface, so the Translate, Rotate and Scale edit of a
    matrix is refused too, with the cause and with no write."""
    adapter = OvstagePropertyAdapter(ovstage_scene, [_SPHERE_PATH])
    stage = ovstage_scene._stage
    before = _raw(stage, _SPHERE_PATH, "localMatrix")
    assert adapter.get_attribute_metadata("localMatrix").type_name == "matrix4d"

    with pytest.raises(
        NotImplementedError, match="transform-control properties are not editable"
    ):
        adapter.set_matrix_part_value("localMatrix", "translate", 0, 5.0)

    assert _raw(stage, _SPHERE_PATH, "localMatrix") == before

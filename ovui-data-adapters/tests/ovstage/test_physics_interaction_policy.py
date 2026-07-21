# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovstage transform writes obey simulation ownership policy."""

from __future__ import annotations

import struct
from typing import Any

import pytest

from ovui_data_adapters.common import TransformEditMode
from ovui_data_adapters.ovstage.transform_adapter import OvstageTransformAdapter


_DYNAMIC = "/World/DynamicBody"
_KINEMATIC = "/World/KinematicBody"
_PLAIN = "/World/PlainBody"
_LOCAL_MATRIX = "localMatrix"
_WORLD_MATRIX = "worldMatrix"


class _FakeStage:
    def __init__(self) -> None:
        self.current_ordinal = 0
        self.direct_writes: list[tuple[str, tuple[float, ...]]] = []
        self._attributes = {
            _DYNAMIC: {
                _LOCAL_MATRIX: _pack_matrix(_translation_matrix(0.0)),
                _WORLD_MATRIX: _pack_matrix(_translation_matrix(0.0)),
                "physics:rigidBodyEnabled": bytes((1,)),
            },
            _KINEMATIC: {
                _LOCAL_MATRIX: _pack_matrix(_translation_matrix(0.0)),
                _WORLD_MATRIX: _pack_matrix(_translation_matrix(0.0)),
                "physics:rigidBodyEnabled": bytes((1,)),
                "physics:kinematicEnabled": bytes((1,)),
            },
            _PLAIN: {
                _LOCAL_MATRIX: _pack_matrix(_translation_matrix(0.0)),
                _WORLD_MATRIX: _pack_matrix(_translation_matrix(0.0)),
            },
        }

    def begin_frame(self) -> int:
        self.current_ordinal += 1
        return int(self.current_ordinal)

    def end_frame(self, ordinal: int) -> None:
        assert int(ordinal) == int(self.current_ordinal)

    def get_parent_path(self, path: str) -> str:
        if path in self._attributes:
            return "/World"
        raise KeyError(path)

    def read_attribute(self, _ordinal: int, paths: list[str], attr_name: str) -> bytes:
        try:
            return self._attributes[str(paths[0])][str(attr_name)]
        except KeyError as exc:
            raise RuntimeError(f"missing {paths[0]}.{attr_name}") from exc

    def write_matrix(self, path: str, matrix: tuple[float, ...]) -> None:
        self.direct_writes.append((path, matrix))
        payload = _pack_matrix(matrix)
        self._attributes[path][_LOCAL_MATRIX] = payload
        self._attributes[path][_WORLD_MATRIX] = payload


class _FakeHierarchy:
    def __init__(self, stage: _FakeStage) -> None:
        self._stage = stage
        self.update_calls: list[int] = []

    def get_local_xform(self, path: str) -> tuple[float, ...]:
        return _unpack_matrix(self._stage.read_attribute(0, [path], _LOCAL_MATRIX))

    def get_world_xform(self, path: str) -> tuple[float, ...]:
        return _unpack_matrix(self._stage.read_attribute(0, [path], _WORLD_MATRIX))

    def set_local_xform(self, _ordinal: int, path: str, matrix: list[float]) -> None:
        self._stage.write_matrix(path, tuple(float(value) for value in matrix))

    def update_world_xforms(self, ordinal: int) -> None:
        self.update_calls.append(int(ordinal))


class _FakePhysicsControls:
    enabled = True
    has_physics_scene = True

    def __init__(
        self,
        modes: dict[str, str],
        *,
        playing: bool,
        control_targets: set[str] | None = None,
    ) -> None:
        self._modes = dict(modes)
        self._control_targets = set(control_targets or ())
        self.playing = bool(playing)
        self.targets: list[tuple[str, tuple[float, ...]]] = []
        self.step_bound_states: list[tuple[str, bool]] = []

    def get_body_mode(self, path: str) -> str | None:
        return self._modes.get(path)

    def can_apply_kinematic_target(self, path: str) -> bool:
        return self.playing and (
            self._modes.get(path) == "kinematic" or path in self._control_targets
        )

    def has_control_target_mode(self, path: str) -> bool:
        return path in self._control_targets

    def set_kinematic_target(self, path: str, matrix: list[list[float]]) -> None:
        self.targets.append((path, tuple(value for row in matrix for value in row)))

    def apply_step_bound_edit(self, edit_fn: Any) -> Any:
        was_playing = self.playing
        self.step_bound_states.append(("before", self.playing))
        if was_playing:
            self.playing = False
        self.step_bound_states.append(("during", self.playing))
        try:
            return edit_fn()
        finally:
            self.playing = was_playing
            self.step_bound_states.append(("after", self.playing))


class _FakeScene:
    def __init__(self, controls: _FakePhysicsControls) -> None:
        self._stage = _FakeStage()
        self.hierarchy = _FakeHierarchy(self._stage)
        self.physics_controls = controls
        self.is_open = True


def test_paused_dynamic_body_accepts_runtime_transform_write() -> None:
    controls = _FakePhysicsControls({_DYNAMIC: "dynamic"}, playing=False)
    scene = _FakeScene(controls)
    adapter = OvstageTransformAdapter(scene)

    adapter.set_local_transform(_DYNAMIC, _matrix_rows(3.0))

    assert adapter.get_transform_edit_policy(_DYNAMIC).mode is TransformEditMode.DIRECT
    assert adapter.can_transform(_DYNAMIC) is True
    assert scene._stage.direct_writes[-1][0] == _DYNAMIC
    assert _translation(adapter.get_local_transform(_DYNAMIC)) == pytest.approx((3.0, 0.0, 0.0))
    assert controls.targets == []


def test_running_dynamic_body_is_read_only_and_not_written_to_ovstage() -> None:
    controls = _FakePhysicsControls({_DYNAMIC: "dynamic"}, playing=True)
    scene = _FakeScene(controls)
    adapter = OvstageTransformAdapter(scene)

    policy = adapter.get_transform_edit_policy(_DYNAMIC)

    assert policy.mode is TransformEditMode.BLOCKED
    assert "physics solver" in policy.reason
    assert adapter.can_transform(_DYNAMIC) is False
    with pytest.raises(NotImplementedError):
        adapter.set_local_transform(_DYNAMIC, _matrix_rows(5.0))
    assert scene._stage.direct_writes == []
    assert controls.targets == []


def test_running_kinematic_body_routes_edit_through_ovphysx_control_target() -> None:
    controls = _FakePhysicsControls({_KINEMATIC: "kinematic"}, playing=True)
    scene = _FakeScene(controls)
    adapter = OvstageTransformAdapter(scene)

    adapter.set_local_transform(_KINEMATIC, _matrix_rows(7.0))

    policy = adapter.get_transform_edit_policy(_KINEMATIC)
    assert policy.mode is TransformEditMode.REDIRECTED
    assert adapter.can_transform(_KINEMATIC) is True
    assert scene._stage.direct_writes == []
    assert controls.targets == [(_KINEMATIC, _translation_matrix(7.0))]
    assert _translation(adapter.get_local_transform(_KINEMATIC)) == pytest.approx((0.0, 0.0, 0.0))


def test_running_dynamic_body_with_explicit_control_target_redirects() -> None:
    controls = _FakePhysicsControls(
        {_DYNAMIC: "dynamic"},
        playing=True,
        control_targets={_DYNAMIC},
    )
    scene = _FakeScene(controls)
    adapter = OvstageTransformAdapter(scene)

    adapter.set_local_transform(_DYNAMIC, _matrix_rows(4.0))

    policy = adapter.get_transform_edit_policy(_DYNAMIC)
    assert policy.mode is TransformEditMode.REDIRECTED
    assert scene._stage.direct_writes == []
    assert controls.targets == [(_DYNAMIC, _translation_matrix(4.0))]


def test_reset_teleport_on_running_dynamic_body_is_pause_bounded() -> None:
    controls = _FakePhysicsControls({_DYNAMIC: "dynamic"}, playing=True)
    scene = _FakeScene(controls)
    adapter = OvstageTransformAdapter(scene)

    with pytest.raises(NotImplementedError):
        adapter.set_local_transform(_DYNAMIC, _matrix_rows(9.0))

    adapter.teleport_local_transform(_DYNAMIC, _matrix_rows(9.0))
    adapter.reset_local_transform(_DYNAMIC)

    assert controls.step_bound_states == [
        ("before", True),
        ("during", False),
        ("after", True),
        ("before", True),
        ("during", False),
        ("after", True),
    ]
    assert controls.playing is True
    assert scene._stage.direct_writes[0] == (_DYNAMIC, _translation_matrix(9.0))
    assert scene._stage.direct_writes[1] == (_DYNAMIC, _translation_matrix(0.0))
    assert _translation(adapter.get_local_transform(_DYNAMIC)) == pytest.approx((0.0, 0.0, 0.0))


def _matrix_rows(x: float) -> list[list[float]]:
    flat = _translation_matrix(x)
    return [list(flat[index:index + 4]) for index in range(0, 16, 4)]


def _translation_matrix(x: float) -> tuple[float, ...]:
    return (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        float(x), 0.0, 0.0, 1.0,
    )


def _pack_matrix(matrix: tuple[float, ...]) -> bytes:
    return struct.pack("<16d", *matrix)


def _unpack_matrix(payload: bytes) -> tuple[float, ...]:
    return struct.unpack("<16d", bytes(payload))


def _translation(matrix: list[list[float]]) -> tuple[float, float, float]:
    return (float(matrix[3][0]), float(matrix[3][1]), float(matrix[3][2]))

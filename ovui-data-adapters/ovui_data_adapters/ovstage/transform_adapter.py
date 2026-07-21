# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovstage transform adapter backed by ovhierarchy runtime matrices."""

from __future__ import annotations

import math
from typing import Any, Iterable, List, Sequence

from ovui_data_adapters.common import (
    TransformAdapter,
    TransformEditMode,
    TransformEditPolicy,
)

from ovui_data_adapters.ovstage._errors import raise_not_ready
from ovui_data_adapters.ovstage._authoring import (
    NativeValueDescriptor,
    NativeValueEditCommand,
)
from ovui_data_adapters.ovstage._native import read_matrix_attribute
from ovui_data_adapters.ovstage._scene import (
    kit_write_local_matrix,
    stage_supports_kit_matrix_write,
)


_ROOT_PATH = "/"
_IDENTITY: List[List[float]] = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]
_MATRIX_ATTR_NAMES = frozenset({"localMatrix", "worldMatrix"})
_DYNAMIC_BODY_MODE = "dynamic"
_KINEMATIC_BODY_MODE = "kinematic"
_CONTROL_TARGET_BODY_MODE = "control_target"
_RIGID_BODY_ENABLED_ATTR = "physics:rigidBodyEnabled"
_KINEMATIC_ENABLED_ATTR = "physics:kinematicEnabled"
_LOCAL_XFORM_DESCRIPTOR = NativeValueDescriptor(
    name="omni:xform",
    dtype=(2, 64, 16),
    semantic=10,
    native_is_array=False,
    logical_is_array=False,
)


class OvstageTransformAdapter(TransformAdapter):
    """Transform reads and runtime local writes over ovstage/ovhierarchy."""

    def __init__(self, scene: Any | None = None) -> None:
        self._scene = scene
        self._hierarchy: Any | None = None
        self._hierarchy_resolved = False

    def get_local_transform(self, path: str) -> List[List[float]]:
        return self._read_matrix(path, "localMatrix")

    def get_world_transform(self, path: str) -> List[List[float]]:
        return self._read_matrix(path, "worldMatrix")

    def set_local_transform(self, path: str, matrix: List[List[float]]) -> None:
        normalized_path = self._normalize_path(path)
        flat_matrix = _flatten_matrix(matrix)
        if _is_singular_matrix(flat_matrix):
            raise ValueError("transform matrix must be non-singular")
        policy = self.get_transform_edit_policy(normalized_path)
        if policy.mode is TransformEditMode.BLOCKED:
            reason = f": {policy.reason}" if policy.reason else ""
            raise_not_ready(f"transform local write{reason}")
        if policy.mode is TransformEditMode.REDIRECTED:
            self._set_control_target(normalized_path, _matrix_from_flat(flat_matrix))
            return
        self._write_stage_local_transform(normalized_path, flat_matrix)

    def teleport_local_transform(self, path: str, matrix: List[List[float]]) -> None:
        normalized_path = self._normalize_path(path)
        flat_matrix = _flatten_matrix(matrix)
        if _is_singular_matrix(flat_matrix):
            raise ValueError("transform matrix must be non-singular")
        if not self._can_write_runtime_matrix(normalized_path):
            raise_not_ready("transform teleport")
        controls = self._physics_controls()
        if _physics_is_running(controls):
            apply_step_bound_edit = getattr(controls, "apply_step_bound_edit", None)
            if not callable(apply_step_bound_edit):
                raise_not_ready("transform teleport step-bound edit")
            apply_step_bound_edit(
                lambda: self._write_runtime_local_transform(normalized_path, flat_matrix)
            )
            return
        self._write_stage_local_transform(normalized_path, flat_matrix)

    def get_transform_edit_policy(self, path: str) -> TransformEditPolicy:
        normalized_path = self._normalize_path(path)
        if not self._can_write_runtime_matrix(normalized_path):
            return TransformEditPolicy(
                TransformEditMode.BLOCKED,
                reason="path has no editable runtime transform",
            )
        controls = self._physics_controls()
        if not _physics_is_running(controls):
            return TransformEditPolicy(TransformEditMode.DIRECT)

        body_mode = _physics_body_mode(controls, self._stage_or_none(), normalized_path)
        if body_mode in {_KINEMATIC_BODY_MODE, _CONTROL_TARGET_BODY_MODE}:
            if _can_route_control_target(controls, normalized_path):
                return TransformEditPolicy(
                    TransformEditMode.REDIRECTED,
                    reason="running kinematic body uses ovphysx control targets",
                )
            return TransformEditPolicy(
                TransformEditMode.BLOCKED,
                reason="running kinematic body has no ovphysx control target",
            )
        if _has_explicit_control_target(controls, normalized_path):
            if _can_route_control_target(controls, normalized_path):
                return TransformEditPolicy(
                    TransformEditMode.REDIRECTED,
                    reason="running body uses an explicit ovphysx control target",
                )
            return TransformEditPolicy(
                TransformEditMode.BLOCKED,
                reason="control target mode is active but ovphysx controls are unavailable",
            )
        if body_mode == _DYNAMIC_BODY_MODE:
            return TransformEditPolicy(
                TransformEditMode.BLOCKED,
                reason="running dynamic body is owned by the physics solver",
            )
        return TransformEditPolicy(TransformEditMode.DIRECT)

    def can_transform(self, path: str) -> bool:
        return self.get_transform_edit_policy(path).is_editable

    def _write_stage_local_transform(self, normalized_path: str, flat_matrix: list[float]) -> None:
        stage = self._require_stage()
        hierarchy = self._optional_hierarchy()
        if hierarchy is not None or not callable(
            getattr(stage, "write_attributes", None)
        ):
            self._write_runtime_local_transform(normalized_path, flat_matrix)
            return
        if not stage_supports_kit_matrix_write(stage):
            self._require_hierarchy()
        old_matrix = tuple(
            component
            for row in self.get_local_transform(normalized_path)
            for component in row
        )
        new_matrix = tuple(float(component) for component in flat_matrix)
        if old_matrix == new_matrix:
            return
        NativeValueEditCommand(
            self._scene,
            (normalized_path,),
            _LOCAL_XFORM_DESCRIPTOR,
            (old_matrix,),
            (new_matrix,),
            category="transform",
            source="transform:set",
        ).do()

    def _write_runtime_local_transform(
        self,
        normalized_path: str,
        flat_matrix: list[float],
    ) -> None:
        stage = self._require_stage()
        # Legacy standalone ovstage runtime: write through ovhierarchy exactly
        # as before so existing source-layout roots keep their behavior.
        hierarchy = self._optional_hierarchy()
        if hierarchy is not None:
            ordinal = stage.begin_frame()
            try:
                hierarchy.set_local_xform(ordinal, normalized_path, flat_matrix)
                hierarchy.update_world_xforms(ordinal)
            finally:
                stage.end_frame(ordinal)
            return
        # Kit-integrated runtime: no ovhierarchy, but the Kit Stage exposes a
        # copy-in write path. Write the local matrix directly through fabric.
        if stage_supports_kit_matrix_write(stage):
            kit_write_local_matrix(stage, normalized_path, flat_matrix)
            return
        # Neither runtime can write — surface the legacy ovhierarchy error.
        self._require_hierarchy()

    def _can_write_runtime_matrix(self, normalized_path: str) -> bool:
        if normalized_path == _ROOT_PATH:
            return False
        stage = self._stage_or_none()
        if stage is None or not _path_exists(stage, normalized_path):
            return False
        if not _has_matrix_attribute(stage, normalized_path, "localMatrix"):
            return False
        # Edit policy must reflect a runtime that can actually write: the Kit
        # copy-in path, or the legacy ovhierarchy runtime.
        if stage_supports_kit_matrix_write(stage):
            return True
        return self._optional_hierarchy() is not None

    def _set_control_target(self, path: str, matrix: list[list[float]]) -> None:
        controls = self._physics_controls()
        for method_name in (
            "set_kinematic_target",
            "set_control_target",
            "set_rigid_body_kinematic_target",
        ):
            method = getattr(controls, method_name, None)
            if callable(method):
                method(path, matrix)
                return
        raise_not_ready("transform kinematic control target")

    def _read_matrix(self, path: str, attr_name: str) -> List[List[float]]:
        if attr_name not in _MATRIX_ATTR_NAMES:
            raise ValueError(f"unsupported transform matrix attribute: {attr_name!r}")
        normalized_path = self._normalize_path(path)
        stage = self._require_stage()
        if normalized_path == _ROOT_PATH or not _path_exists(stage, normalized_path):
            return _copy_identity()
        hierarchy = self._optional_hierarchy()
        if hierarchy is not None:
            try:
                flat = (
                    hierarchy.get_local_xform(normalized_path)
                    if attr_name == "localMatrix"
                    else hierarchy.get_world_xform(normalized_path)
                )
                return _matrix_from_flat(flat)
            except RuntimeError:
                # Non-xformable or partially populated prims may not have
                # hierarchy columns; fall through to OVStage attributes.
                pass
        raw = _read_matrix_attribute(stage, normalized_path, attr_name)
        if raw is None:
            return _copy_identity()
        return _matrix_from_flat(raw)

    def _require_stage(self) -> Any:
        stage = self._stage_or_none()
        if stage is None:
            raise_not_ready("transform stage")
        return stage

    def _stage_or_none(self) -> Any | None:
        scene = self._scene
        stage = getattr(scene, "_stage", None)
        if scene is None or stage is None or not getattr(scene, "is_open", False):
            return None
        return stage

    def _require_hierarchy(self) -> Any:
        scene = self._scene
        if scene is None or not getattr(scene, "is_open", False):
            raise_not_ready("transform hierarchy")
        try:
            return scene.hierarchy
        except (ImportError, RuntimeError) as exc:
            raise RuntimeError("ovhierarchy transform runtime is unavailable") from exc

    def _optional_hierarchy(self) -> Any | None:
        scene = self._scene
        if scene is None or not getattr(scene, "is_open", False):
            return None
        if not self._hierarchy_resolved:
            try:
                self._hierarchy = scene.hierarchy
            except (ImportError, RuntimeError):
                self._hierarchy = None
            self._hierarchy_resolved = True
        return self._hierarchy

    def _physics_controls(self) -> Any | None:
        scene = self._scene
        if scene is None or not getattr(scene, "is_open", False):
            return None
        controls = getattr(scene, "physics_controls", None)
        if controls is not None:
            return controls
        return getattr(scene, "_physics_controls", None)

    @staticmethod
    def _normalize_path(path: str) -> str:
        if not isinstance(path, str):
            return _ROOT_PATH
        value = path
        if value == _ROOT_PATH:
            return value
        if (
            not value.startswith(_ROOT_PATH)
            or value.endswith(_ROOT_PATH)
            or "//" in value
            or any(part in ("", ".", "..") for part in value.split("/")[1:])
        ):
            return _ROOT_PATH
        return value


def _copy_identity() -> List[List[float]]:
    return [row[:] for row in _IDENTITY]


def _matrix_from_flat(values: Iterable[Any]) -> List[List[float]]:
    try:
        flat = [float(value) for value in values]
    except (TypeError, ValueError):
        return _copy_identity()
    if len(flat) != 16 or not all(math.isfinite(value) for value in flat):
        return _copy_identity()
    return [flat[index:index + 4] for index in range(0, 16, 4)]


def _flatten_matrix(matrix: Sequence[Sequence[Any]]) -> list[float]:
    try:
        rows = [list(row) for row in matrix]
    except TypeError as exc:
        raise ValueError("transform matrix must be a 4x4 iterable") from exc
    if len(rows) != 4 or any(len(row) != 4 for row in rows):
        raise ValueError("transform matrix must be 4x4")
    try:
        values = [float(value) for row in rows for value in row]
    except (TypeError, ValueError) as exc:
        raise ValueError("transform matrix values must be numeric") from exc
    if not all(math.isfinite(value) for value in values):
        raise ValueError("transform matrix values must be finite")
    return values


def _is_singular_matrix(values: Sequence[float]) -> bool:
    rows = [
        [float(values[row * 4 + column]) for column in range(3)]
        for row in range(3)
    ]
    scale = max(1.0, *(abs(value) for row in rows for value in row))
    tolerance = 1.0e-12 * scale
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(rows[row][column]))
        if abs(rows[pivot][column]) <= tolerance:
            return True
        if pivot != column:
            rows[column], rows[pivot] = rows[pivot], rows[column]
        pivot_value = rows[column][column]
        for row in range(column + 1, 3):
            factor = rows[row][column] / pivot_value
            for index in range(column, 3):
                rows[row][index] -= factor * rows[column][index]
    return False


def _read_matrix_attribute(
    stage: Any,
    path: str,
    attr_name: str,
) -> tuple[float, ...] | None:
    return read_matrix_attribute(stage, path, attr_name)


def _has_matrix_attribute(stage: Any, path: str, attr_name: str) -> bool:
    return _read_matrix_attribute(stage, path, attr_name) is not None


def _path_exists(stage: Any, path: str) -> bool:
    try:
        stage.get_parent_path(path)
    except Exception:
        return False
    return True


def _physics_is_running(controls: Any | None) -> bool:
    return bool(getattr(controls, "playing", False))


def _physics_body_mode(
    controls: Any | None,
    stage: Any | None,
    path: str,
) -> str | None:
    for owner in (controls,):
        mode = _call_body_mode(owner, path)
        if mode is not None:
            return mode
    if stage is None:
        return None
    kinematic = _read_bool_attribute(stage, path, _KINEMATIC_ENABLED_ATTR)
    if kinematic is True:
        return _KINEMATIC_BODY_MODE
    dynamic = _read_bool_attribute(stage, path, _RIGID_BODY_ENABLED_ATTR)
    if dynamic is True:
        return _DYNAMIC_BODY_MODE
    return None


def _call_body_mode(owner: Any | None, path: str) -> str | None:
    if owner is None:
        return None
    for method_name in (
        "get_body_mode",
        "get_physics_body_mode",
        "get_transform_body_mode",
        "body_mode_for_path",
    ):
        method = getattr(owner, method_name, None)
        if not callable(method):
            continue
        mode = method(path)
        normalized = _normalize_body_mode(mode)
        if normalized is not None:
            return normalized
    return None


def _normalize_body_mode(mode: Any) -> str | None:
    value = str(getattr(mode, "value", mode) or "").strip().lower()
    if value in {"dynamic", "rigid", "rigid_body", "rigid-body"}:
        return _DYNAMIC_BODY_MODE
    if value in {"kinematic", "kinematic_body", "kinematic-body"}:
        return _KINEMATIC_BODY_MODE
    if value in {"control", "control_target", "control-target", "target"}:
        return _CONTROL_TARGET_BODY_MODE
    return None


def _has_explicit_control_target(controls: Any | None, path: str) -> bool:
    if controls is None:
        return False
    for method_name in (
        "has_control_target_mode",
        "has_kinematic_target_mode",
        "is_control_target_enabled",
    ):
        method = getattr(controls, method_name, None)
        if callable(method) and bool(method(path)):
            return True
    return False


def _can_route_control_target(controls: Any | None, path: str) -> bool:
    if controls is None:
        return False
    for method_name in ("can_apply_kinematic_target", "can_apply_control_target"):
        method = getattr(controls, method_name, None)
        if callable(method):
            return bool(method(path))
    for method_name in (
        "set_kinematic_target",
        "set_control_target",
        "set_rigid_body_kinematic_target",
    ):
        if callable(getattr(controls, method_name, None)):
            return True
    return False


def _read_bool_attribute(stage: Any, path: str, attr_name: str) -> bool | None:
    try:
        raw_value = stage.read_attribute(
            int(stage.current_ordinal),
            [str(path)],
            attr_name,
        )
    except (KeyError, RuntimeError):
        return None
    raw = bytes(raw_value)
    if not raw:
        return None
    return bool(raw[0])

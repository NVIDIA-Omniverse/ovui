# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION is strictly
# prohibited.

"""Scene-bound exact-public OVStage value authoring."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Sequence

import numpy as np

from ovui_data_adapters.common import Command
from ovui_data_adapters.ovstage._native import read_token_attribute
from ovui_data_adapters.ovstage._stage_write import wait_operation
from ovui_data_adapters.ovstage.runtime_import import import_ovstage_runtime_module


_DLPACK_INT = 0
_DLPACK_UINT = 1
_DLPACK_FLOAT = 2
_DLPACK_BOOL = 6

_SEMANTIC_NONE = 0
_SEMANTIC_ASSET_STRING = 1
_SEMANTIC_TOKEN_ID = 2
_SEMANTIC_PATH_EXPRESSION_STRING = 3
_SEMANTIC_RELATIONSHIP_PATH_ID = 4
_SEMANTIC_CONNECTION_PATH_ID = 12
_SEMANTIC_STRING = 13
_RELATIONSHIP_TARGET_TYPES = {
    "material:binding": frozenset({"Material"}),
    "camera": frozenset({"Camera"}),
    "orderedVars": frozenset({"RenderVar"}),
    "geomSubsets": frozenset({"GeomSubset"}),
}

MISSING = object()


@dataclass(frozen=True)
class NativeValueDescriptor:
    """Copied exact descriptor needed to validate and encode one column."""

    name: str
    dtype: tuple[int, int, int]
    semantic: int
    native_is_array: bool
    logical_is_array: bool


class NativeValueEditCommand(Command):
    """One scene-bound value edge with an exact Python-owned inverse."""

    def __init__(
        self,
        scene: Any,
        paths: Sequence[str],
        descriptor: NativeValueDescriptor,
        old_values: Sequence[Any],
        new_values: Sequence[Any],
        *,
        category: str = "attribute",
        source: str = "property:set",
    ) -> None:
        self._scene = scene
        self._stage = getattr(scene, "_stage", None)
        self._paths = tuple(str(path) for path in paths)
        self._descriptor = descriptor
        self._old_values = tuple(freeze_native_value(value) for value in old_values)
        self._new_values = tuple(freeze_native_value(value) for value in new_values)
        self._category = str(category)
        self._source = str(source)
        if len(self._paths) != len(self._old_values) or len(self._paths) != len(
            self._new_values
        ):
            raise ValueError("native value history must have one value per path")

    def do(self) -> None:
        self._apply(self._new_values, self._old_values)

    def undo(self) -> None:
        self._apply(self._old_values, self._new_values)

    def _apply(self, values: Sequence[Any], rollback: Sequence[Any]) -> None:
        if (
            self._stage is None
            or getattr(self._scene, "_stage", None) is not self._stage
            or not getattr(self._scene, "is_open", False)
        ):
            raise RuntimeError(
                "value history belongs to a closed or replaced OVStage scene"
            )
        apply_native_value_edit(
            self._scene,
            self._paths,
            self._descriptor,
            values,
            rollback_values=rollback,
            category=self._category,
            source=self._source,
        )


def freeze_native_value(value: Any) -> Any:
    """Return an immutable Python-owned history value."""

    if value is MISSING or value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, np.ndarray):
        return freeze_native_value(value.tolist())
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    try:
        return tuple(freeze_native_value(item) for item in value)
    except TypeError:
        return value


def validate_native_values(
    scene: Any,
    paths: Sequence[str],
    descriptor: NativeValueDescriptor,
    values: Sequence[Any],
) -> tuple[Any, ...]:
    """Validate and freeze values without beginning a native frame."""

    stage = _require_identical_open_stage(scene)
    normalized_paths = tuple(str(path) for path in paths)
    if not normalized_paths or len(normalized_paths) != len(values):
        raise ValueError("native value edit requires one value per current prim")
    for path in normalized_paths:
        if not _is_canonical_prim_path(path) or not _native_path_exists(stage, path):
            raise ValueError(f"OVStage value path is not a current native prim: {path!r}")
    frozen = tuple(freeze_native_value(value) for value in values)
    for value in frozen:
        if value is not MISSING:
            _validate_value(stage, descriptor, value)
    return frozen


def apply_native_value_edit(
    scene: Any,
    paths: Sequence[str],
    descriptor: NativeValueDescriptor,
    values: Sequence[Any],
    *,
    rollback_values: Sequence[Any],
    category: str,
    source: str,
) -> int:
    """Commit one exact value state with compensating rollback and one event."""

    stage = _require_identical_open_stage(scene)
    target = validate_native_values(scene, paths, descriptor, values)
    rollback = validate_native_values(scene, paths, descriptor, rollback_values)
    if getattr(scene, "_ovui_value_edit_active", False):
        raise RuntimeError("reentrant OVStage value edits are not allowed")

    scene._ovui_value_edit_active = True
    stream = scene.change_stream
    try:
        with stream.suppress_notifications():
            ordinal = _commit_state(
                stage,
                tuple(str(path) for path in paths),
                descriptor,
                target,
                rollback,
            )
        # Committed-edge publication: the native state is committed but the
        # history entry for this edge is recorded only when this call
        # returns (push/undo/redo/grouped finalization). The scope keeps an
        # interrupt-class observer failure from escaping between the two,
        # which would leave committed state without undo history.
        with stream.committed_edge_publication():
            if category == "transform":
                stream.publish_transform_change(list(paths), source=source)
            elif category == "visibility":
                stream.publish_visibility_change(list(paths), source=source)
            else:
                stream.publish_attribute_change(list(paths), source=source)
        return ordinal
    finally:
        scene._ovui_value_edit_active = False


def _commit_state(
    stage: Any,
    paths: tuple[str, ...],
    descriptor: NativeValueDescriptor,
    target: tuple[Any, ...],
    rollback: tuple[Any, ...],
) -> int:
    try:
        ordinal = int(stage.begin_frame())
    except Exception as exc:
        raise RuntimeError("failed to begin an OVStage value frame") from exc

    operation_error: BaseException | None = None
    try:
        _apply_state_at_ordinal(stage, paths, descriptor, target, ordinal)
    except BaseException as exc:
        operation_error = exc
        try:
            _apply_state_at_ordinal(stage, paths, descriptor, rollback, ordinal)
        except BaseException as rollback_error:
            _add_note(exc, "native value rollback failed", rollback_error)

    if operation_error is not None:
        try:
            abort = getattr(stage, "abort_frame", None)
            if callable(abort):
                abort(ordinal)
            else:
                wait_operation(stage.end_frame(ordinal))
        except BaseException as abort_error:
            _add_note(operation_error, "native value frame abort failed", abort_error)
        raise RuntimeError(
            f"failed to author OVStage attribute {descriptor.name!r}"
        ) from operation_error

    try:
        wait_operation(stage.end_frame(ordinal))
    except BaseException as exc:
        try:
            _apply_state_at_ordinal(stage, paths, descriptor, rollback, ordinal)
        except BaseException as rollback_error:
            _add_note(exc, "native value commit compensation failed", rollback_error)
        try:
            abort = getattr(stage, "abort_frame", None)
            if callable(abort):
                abort(ordinal)
        except BaseException as abort_error:
            _add_note(exc, "native value frame abort failed", abort_error)
        raise RuntimeError(
            f"OVStage value frame could not commit at ordinal {ordinal}"
        ) from exc
    return ordinal


def _apply_state_at_ordinal(
    stage: Any,
    paths: tuple[str, ...],
    descriptor: NativeValueDescriptor,
    values: tuple[Any, ...],
    ordinal: int,
) -> None:
    present_rows = tuple(
        (path, value)
        for path, value in zip(paths, values)
        if value is not MISSING
    )
    missing_paths = tuple(
        path for path, value in zip(paths, values) if value is MISSING
    )
    if present_rows:
        _write_rows(
            stage,
            tuple(path for path, _value in present_rows),
            descriptor,
            tuple(value for _path, value in present_rows),
            ordinal,
        )
    if missing_paths:
        _delete_column_rows(stage, missing_paths, descriptor.name, ordinal)


def _write_rows(
    stage: Any,
    paths: tuple[str, ...],
    descriptor: NativeValueDescriptor,
    values: tuple[Any, ...],
    ordinal: int,
) -> None:
    ovstage = import_ovstage_runtime_module("ovstage")
    with ovstage.PathDictionary(stage) as dictionary:
        path_list = dictionary.create_path_list_from_strings(paths)
        query = None
        try:
            query = stage.query_from_path_list(path_list)
            tensors = _make_tensors(ovstage, dictionary, descriptor, values)
            payload = tensors if descriptor.native_is_array else tensors[0]
            write = ovstage.WriteDesc(
                descriptor.name,
                payload,
                is_array=descriptor.native_is_array,
                semantic=int(descriptor.semantic),
            )
            operation = stage.write_attributes(
                query,
                (write,),
                int(ordinal),
                prim_mode=ovstage.PrimMode.UPSERT,
            )
            wait_operation(operation)
        finally:
            _release_query(stage, query)
            dictionary.destroy_path_list(path_list)


def _delete_column_rows(
    stage: Any,
    paths: tuple[str, ...],
    attribute_name: str,
    ordinal: int,
) -> None:
    ovstage = import_ovstage_runtime_module("ovstage")
    with ovstage.PathDictionary(stage) as dictionary:
        path_list = dictionary.create_path_list_from_strings(paths)
        query = None
        try:
            query = stage.query_from_path_list(path_list)
            wait_operation(
                stage.delete_attributes(query, (str(attribute_name),), int(ordinal))
            )
        finally:
            _release_query(stage, query)
            dictionary.destroy_path_list(path_list)


def _make_tensors(
    ovstage: Any,
    dictionary: Any,
    descriptor: NativeValueDescriptor,
    values: tuple[Any, ...],
) -> tuple[Any, ...]:
    code, bits, lanes = descriptor.dtype
    dtype = ovstage.DLDataType(code=int(code), bits=int(bits), lanes=int(lanes))
    if descriptor.native_is_array:
        return tuple(
            _make_array_tensor(ovstage, dictionary, descriptor, value, dtype)
            for value in values
        )

    rows = np.concatenate(
        tuple(_fixed_row(dictionary, descriptor, value) for value in values)
    )
    rows = np.ascontiguousarray(rows)
    return (
        ovstage.make_dltensor(
            rows,
            dtype=dtype,
            shape=[len(values)],
            ndim=1,
        ),
    )


def _fixed_row(
    dictionary: Any,
    descriptor: NativeValueDescriptor,
    value: Any,
) -> np.ndarray:
    code, bits, lanes = descriptor.dtype
    if descriptor.semantic == _SEMANTIC_TOKEN_ID:
        return np.asarray([dictionary.intern_token(str(value))], dtype=np.uint64)
    components = _flatten_components(value)
    if len(components) != int(lanes):
        raise ValueError(
            f"{descriptor.name!r} expects {lanes} component(s), got {len(components)}"
        )
    return _numeric_array(code, bits, components)


def _make_array_tensor(
    ovstage: Any,
    dictionary: Any,
    descriptor: NativeValueDescriptor,
    value: Any,
    dtype: Any,
) -> Any:
    if descriptor.semantic in {
        _SEMANTIC_STRING,
        _SEMANTIC_ASSET_STRING,
        _SEMANTIC_PATH_EXPRESSION_STRING,
    }:
        if descriptor.logical_is_array:
            encoded = b"\0".join(str(item).encode("utf-8") for item in value)
        else:
            encoded = str(value).encode("utf-8")
        array = np.frombuffer(encoded, dtype=np.uint8).copy()
    elif descriptor.semantic == _SEMANTIC_TOKEN_ID:
        array = np.asarray(
            [dictionary.intern_token(str(item)) for item in value],
            dtype=np.uint64,
        )
    elif descriptor.semantic == _SEMANTIC_RELATIONSHIP_PATH_ID:
        array = np.asarray(
            [dictionary.intern_path(str(item)) for item in value],
            dtype=np.uint64,
        )
    elif descriptor.semantic == _SEMANTIC_CONNECTION_PATH_ID:
        pairs: list[int] = []
        for item in value:
            prim_path, property_name = _split_connection_target(str(item))
            pairs.extend(
                (
                    dictionary.intern_path(prim_path),
                    dictionary.intern_token(property_name),
                )
            )
        array = np.asarray(pairs, dtype=np.uint64)
    else:
        code, bits, lanes = descriptor.dtype
        components = _flatten_components(value)
        if len(components) % int(lanes):
            raise ValueError(
                f"{descriptor.name!r} array component count is not divisible by {lanes}"
            )
        array = _numeric_array(code, bits, components)
    array = np.ascontiguousarray(array)
    lane_count = max(1, int(descriptor.dtype[2]))
    logical_count = int(array.size) // lane_count
    return ovstage.make_dltensor(
        array,
        dtype=dtype,
        shape=[logical_count],
        ndim=1,
    )


def _validate_value(stage: Any, descriptor: NativeValueDescriptor, value: Any) -> None:
    semantic = int(descriptor.semantic)
    if descriptor.name == "visibility" and value not in {"inherited", "invisible"}:
        raise ValueError("visibility expects 'inherited' or 'invisible'")
    if descriptor.native_is_array:
        if semantic in {
            _SEMANTIC_STRING,
            _SEMANTIC_ASSET_STRING,
            _SEMANTIC_PATH_EXPRESSION_STRING,
        } and not descriptor.logical_is_array:
            if not isinstance(value, str):
                raise ValueError(f"{descriptor.name!r} expects a string")
            value.encode("utf-8")
            return
        if isinstance(value, (str, bytes, bytearray, memoryview)):
            raise ValueError(f"{descriptor.name!r} expects an array value")
        try:
            items = tuple(value)
        except TypeError as exc:
            raise ValueError(f"{descriptor.name!r} expects an array value") from exc
        if semantic in {
            _SEMANTIC_RELATIONSHIP_PATH_ID,
            _SEMANTIC_CONNECTION_PATH_ID,
        }:
            targets = tuple(str(item) for item in items)
            if len(set(targets)) != len(targets):
                raise ValueError(f"{descriptor.name!r} relationship contains duplicate targets")
            for target in targets:
                prim_path = (
                    _split_connection_target(target)[0]
                    if semantic == _SEMANTIC_CONNECTION_PATH_ID
                    else target
                )
                if not _is_canonical_prim_path(prim_path) or not _native_path_exists(
                    stage, prim_path
                ):
                    raise ValueError(
                        f"{descriptor.name!r} target is not a current native target: {target!r}"
                    )
                required_types = _RELATIONSHIP_TARGET_TYPES.get(descriptor.name)
                if required_types is not None:
                    target_type = read_token_attribute(
                        stage,
                        prim_path,
                        "usd-prim-type",
                    )
                    if target_type not in required_types:
                        expected = ", ".join(sorted(required_types))
                        raise ValueError(
                            f"{descriptor.name!r} target {target!r} must be native {expected}"
                        )
            return
        if semantic == _SEMANTIC_TOKEN_ID:
            if not all(isinstance(item, str) for item in items):
                raise ValueError(f"{descriptor.name!r} expects token strings")
            return
        if semantic in {
            _SEMANTIC_STRING,
            _SEMANTIC_ASSET_STRING,
            _SEMANTIC_PATH_EXPRESSION_STRING,
        }:
            if not all(isinstance(item, str) for item in items):
                raise ValueError(f"{descriptor.name!r} expects string values")
            return
        _validate_numeric_components(descriptor, _flatten_components(items), array=True)
        return

    if semantic == _SEMANTIC_TOKEN_ID:
        if not isinstance(value, str):
            raise ValueError(f"{descriptor.name!r} expects a token string")
        return
    _validate_numeric_components(descriptor, _flatten_components(value), array=False)


def _validate_numeric_components(
    descriptor: NativeValueDescriptor,
    components: list[Any],
    *,
    array: bool,
) -> None:
    code, bits, lanes = descriptor.dtype
    if not array and len(components) != int(lanes):
        raise ValueError(
            f"{descriptor.name!r} expects {lanes} component(s), got {len(components)}"
        )
    if array and len(components) % int(lanes):
        raise ValueError(
            f"{descriptor.name!r} array component count is not divisible by {lanes}"
        )
    if code == _DLPACK_BOOL:
        if not all(isinstance(component, (bool, np.bool_)) for component in components):
            raise ValueError(f"{descriptor.name!r} expects boolean values")
        return
    if code == _DLPACK_FLOAT:
        try:
            numbers = tuple(float(component) for component in components)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{descriptor.name!r} expects numeric values") from exc
        if not all(math.isfinite(number) for number in numbers):
            raise ValueError(f"{descriptor.name!r} values must be finite")
        _numeric_array(code, bits, numbers)
        return
    if code in {_DLPACK_INT, _DLPACK_UINT}:
        if not all(
            isinstance(component, (int, np.integer))
            and not isinstance(component, (bool, np.bool_))
            for component in components
        ):
            raise ValueError(f"{descriptor.name!r} expects integer values")
        numbers = tuple(int(component) for component in components)
        array_value = _numeric_array(code, bits, numbers)
        if tuple(int(item) for item in array_value) != numbers:
            raise ValueError(f"{descriptor.name!r} integer value is out of range")
        return
    raise NotImplementedError(f"{descriptor.name!r} has an unsupported DLPack dtype")


def _numeric_array(code: int, bits: int, components: Iterable[Any]) -> np.ndarray:
    names = {
        (_DLPACK_INT, 8): "int8",
        (_DLPACK_INT, 16): "int16",
        (_DLPACK_INT, 32): "int32",
        (_DLPACK_INT, 64): "int64",
        (_DLPACK_UINT, 8): "uint8",
        (_DLPACK_UINT, 16): "uint16",
        (_DLPACK_UINT, 32): "uint32",
        (_DLPACK_UINT, 64): "uint64",
        (_DLPACK_FLOAT, 16): "float16",
        (_DLPACK_FLOAT, 32): "float32",
        (_DLPACK_FLOAT, 64): "float64",
        (_DLPACK_BOOL, 8): "bool",
    }
    name = names.get((int(code), int(bits)))
    if name is None:
        raise NotImplementedError("unsupported exact OVStage DLPack dtype")
    try:
        return np.asarray(tuple(components), dtype=np.dtype(name))
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("value cannot be represented by the native dtype") from exc


def _flatten_components(value: Any) -> list[Any]:
    if isinstance(value, (str, bytes, bytearray, memoryview)):
        return [value]
    try:
        values = tuple(value)
    except TypeError:
        return [value]
    result: list[Any] = []
    for item in values:
        if isinstance(item, (str, bytes, bytearray, memoryview)):
            result.append(item)
            continue
        try:
            result.extend(tuple(item))
        except TypeError:
            result.append(item)
    return result


def _split_connection_target(target: str) -> tuple[str, str]:
    if "." not in target:
        raise ValueError(f"connection target is not a property path: {target!r}")
    prim_path, property_name = target.rsplit(".", 1)
    if not property_name:
        raise ValueError(f"connection target has no property token: {target!r}")
    return prim_path, property_name


def _require_identical_open_stage(scene: Any) -> Any:
    stage = getattr(scene, "_stage", None)
    if scene is None or stage is None or not getattr(scene, "is_open", False):
        raise RuntimeError("no identical open OVStage scene is available for value authoring")
    return stage


def _native_path_exists(stage: Any, path: str) -> bool:
    if path == "/":
        return True
    parent = path.rsplit("/", 1)[0]
    try:
        return path in {str(value) for value in stage.get_child_paths(parent)}
    except (KeyError, RuntimeError):
        return False


def _is_canonical_prim_path(path: str) -> bool:
    return bool(
        path.startswith("/")
        and path != "/"
        and path == path.strip()
        and not path.endswith("/")
        and "//" not in path
        and all(part not in {"", ".", ".."} for part in path.split("/")[1:])
    )


def _release_query(stage: Any, query: Any | None) -> None:
    if query is None:
        return
    release = getattr(query, "release", None)
    wait_operation(release() if callable(release) else stage.release_query(query))


def _add_note(primary: BaseException, action: str, secondary: BaseException) -> None:
    add_note = getattr(primary, "add_note", None)
    if callable(add_note):
        add_note(f"{action}: {type(secondary).__name__}: {secondary}")


__all__ = [
    "MISSING",
    "NativeValueDescriptor",
    "NativeValueEditCommand",
    "apply_native_value_edit",
    "freeze_native_value",
    "validate_native_values",
]

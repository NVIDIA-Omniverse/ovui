# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Property adapter scaffold for the registered ovstage provider."""

from __future__ import annotations

from dataclasses import dataclass
import re
import struct
from typing import Any, Callable, Iterable, List, Optional, Sequence

from ovui_data_adapters.common import (
    AdapterCapability,
    AttributeMetadata,
    PropertyCapabilities,
    PropertyAdapter,
    SubscriptionProtocol,
)

from ovui_data_adapters.common._command import clear_history_consistent
from ovui_data_adapters.ovstage._authoring import (
    NativeValueDescriptor,
    NativeValueEditCommand,
    freeze_native_value,
    validate_native_values,
)
from ovui_data_adapters.ovstage._errors import raise_not_ready
from ovui_data_adapters.ovstage._native import resolve_query_names
from ovui_data_adapters.ovstage._native import resolve_token_id
_DLPACK_INT = 0
_DLPACK_UINT = 1
_DLPACK_FLOAT = 2
_DLPACK_BOOL = 6

_SEMANTIC_NONE = 0
_SEMANTIC_ASSET_STRING = 1
_SEMANTIC_TOKEN_ID = 2
_SEMANTIC_PATH_EXPRESSION_STRING = 3
_SEMANTIC_RELATIONSHIP_PATH_ID = 4
_SEMANTIC_POINT = 5
_SEMANTIC_VECTOR = 6
_SEMANTIC_NORMAL = 7
_SEMANTIC_COLOR = 8
_SEMANTIC_QUATERNION = 9
_SEMANTIC_MATRIX = 10
_SEMANTIC_TEXTURE_COORDINATE = 11
_SEMANTIC_CONNECTION_PATH_ID = 12
_SEMANTIC_STRING = 13
_KNOWN_SEMANTICS = frozenset(range(_SEMANTIC_STRING + 1))

_ROOT_PATH = "/"
_MISSING = object()
_BIG_ARRAY_COUNT = 64
_VECTOR_VALUE_TYPES = frozenset(
    {
        "float2",
        "float3",
        "float4",
        "color3f",
        "color4f",
        "int2",
        "int3",
        "int4",
    }
)

_WRITE_DISABLED_ATTRS = {
    "localMatrix",
    "worldMatrix",
    "worldVisibility",
    "xformOpOrder",
    "resetXformStack",
    "usd-prim-type",
    "usd-schemas",
    "omni:xform",
}
_WRITE_DISABLED_PREFIXES = ("xformOp:",)

_OVSTAGE_PROPERTY_CAPABILITIES = PropertyCapabilities(
    clear_values=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose the authored-opinion and "
        "default-value resolution required to clear a property value; select the "
        "OpenUSD data adapter to clear authored opinions"
    ),
)


@dataclass(frozen=True)
class _PathDescriptor:
    attributes: tuple[str, ...]
    prim_list_handle: int


@dataclass(frozen=True)
class _AttributeRecord:
    name: str
    display_name: str
    type_name: str
    value_type: Any
    group: str
    dtype: tuple[int, int, int]
    semantic: int = _SEMANTIC_NONE
    is_array: bool = False
    native_is_array: bool = False
    is_big_array: bool = False


@dataclass
class _EditSnapshot:
    values: tuple[Any, ...]
    pending_values: tuple[Any, ...] | None = None


class _NativeOvstagePropertyAdapter(PropertyAdapter):
    """Property access backed exclusively by OVStage-native attribute data."""

    def __init__(
        self,
        scene: Any | None = None,
        paths: List[str] | None = None,
        undo_manager: Any | None = None,
        stage_adapter: Any | None = None,
    ) -> None:
        self._scene = scene
        self._paths = list(paths or ())
        self._undo_manager = undo_manager
        self._stage_adapter = stage_adapter
        self._cache_key: tuple[int, int] | None = None
        self._path_descriptors: dict[str, _PathDescriptor] = {}
        self._attribute_names: list[str] = []
        self._attribute_records: dict[str, _AttributeRecord] = {}
        self._edit_snapshots: dict[str, _EditSnapshot] = {}

    def get_paths(self) -> List[str]:
        return list(self._paths)

    def is_valid(self) -> bool:
        self._ensure_cache_current()
        if not self._paths:
            return False
        normalized_paths = [self._normalize_path(path) for path in self._paths]
        return all(
            path is not None and path in self._path_descriptors
            for path in normalized_paths
        )

    def get_attribute_names(self) -> List[str]:
        self._ensure_cache_current()
        return list(self._attribute_names)

    def get_attribute_metadata(self, attr_name: str) -> AttributeMetadata:
        self._ensure_cache_current()
        record = self._attribute_records.get(attr_name)
        if record is None:
            raise_not_ready("property metadata")
        return AttributeMetadata(
            name=record.name,
            display_name=record.display_name,
            type_name=record.type_name,
            value_type=record.value_type,
            group=record.group,
            is_big_array=record.is_big_array,
            is_locked=not (
                _is_runtime_writable(record)
                and _supports_exact_value_writes(self._stage_or_none())
            ),
            # OVStage exposes the current native column value but no public
            # authored-opinion/default or time-sample-presence query.
            is_time_sampled=False,
            is_authored=False,
        )

    def get_value(self, attr_name: str) -> Any:
        self._ensure_cache_current()
        if attr_name not in self._attribute_records:
            raise_not_ready("property value read")
        values = self._values_for_attribute(attr_name)
        if self._values_are_ambiguous(values):
            return None
        if not values or values[0] is _MISSING:
            return None
        return values[0]

    def is_ambiguous(self, attr_name: str) -> bool:
        self._ensure_cache_current()
        return self._values_are_ambiguous(self._values_for_attribute(attr_name))

    @staticmethod
    def _values_are_ambiguous(values: Sequence[Any]) -> bool:
        if len(values) <= 1:
            return False
        first = values[0]
        return any(value != first for value in values[1:])

    def get_per_component_ambiguity(self, attr_name: str) -> Optional[List[bool]]:
        self._ensure_cache_current()
        record = self._attribute_records.get(attr_name)
        if record is None or record.is_array:
            return None
        if not (
            record.value_type in _VECTOR_VALUE_TYPES
            or record.type_name.startswith("matrix")
        ):
            return None
        values = self._values_for_attribute(attr_name)
        if len(values) <= 1:
            return None
        if any(value is _MISSING for value in values):
            return None
        if not all(_is_flat_component_tuple(value) for value in values):
            return None
        expected_len = len(values[0])
        if expected_len <= 1 or any(len(value) != expected_len for value in values):
            return None
        return [
            any(value[index] != values[0][index] for value in values[1:])
            for index in range(expected_len)
        ]

    def begin_edit(self, attr_name: str) -> None:
        record = self._runtime_write_record(attr_name)
        values = tuple(self._values_for_attribute(attr_name))
        if not values or any(value is _MISSING for value in values):
            raise_not_ready("property value write")
        self._edit_snapshots[attr_name] = _EditSnapshot(
            values=tuple(freeze_native_value(value) for value in values)
        )
        if self._undo_manager is not None:
            self._undo_manager.begin_group(f"Set {record.name}")

    def set_value(self, attr_name: str, value: Any) -> None:
        record = self._runtime_write_record(attr_name)
        paths = self._normalized_selected_paths()
        if not paths:
            raise_not_ready("property value write")
        values = tuple(freeze_native_value(value) for _ in paths)
        values = validate_native_values(
            self._scene,
            paths,
            _native_value_descriptor(record),
            values,
        )
        snapshot = self._edit_snapshots.get(attr_name)
        if snapshot is not None:
            snapshot.pending_values = values
            return
        old_values = tuple(self._values_for_attribute(attr_name))
        if not old_values or any(old is _MISSING for old in old_values):
            raise_not_ready("property value write")
        if tuple(old_values) == values:
            return
        self._push_value_command(
            paths,
            record,
            old_values,
            values,
        )

    def end_edit(self, attr_name: str) -> None:
        snapshot = self._edit_snapshots.pop(attr_name, None)
        undo_manager = self._undo_manager
        if snapshot is None:
            return
        try:
            record = self._runtime_write_record(attr_name)
            paths = self._normalized_selected_paths()
            new_values = snapshot.pending_values
            if (
                paths
                and new_values is not None
                and len(snapshot.values) == len(new_values)
                and snapshot.values != tuple(new_values)
            ):
                self._push_value_command(
                    paths,
                    record,
                    snapshot.values,
                    new_values,
                )
        finally:
            if undo_manager is not None:
                undo_manager.end_group()

    def _is_scene_visibility_write(
        self, record: _AttributeRecord, paths: Sequence[str]
    ) -> bool:
        """True only for the genuine Imageable scene-visibility attribute.

        A lookalike — a custom or wrongly-shaped property that merely
        shares the ``visibility`` name, or the real name on a
        non-Imageable prim — must publish as an ordinary attribute edit:
        the visibility category feeds the provider stream's PROVEN
        ``visibility_delta``, which consumers trust for precise
        visibility-only invalidation. Genuineness requires the scene
        visibility shape (scalar token) AND every edited prim to be a
        visibility-editable Imageable per the stage adapter.
        """
        if record.name != "visibility":
            return False
        if record.is_array or record.native_is_array:
            return False
        if record.semantic != _SEMANTIC_TOKEN_ID:
            return False
        stage_adapter = self._stage_adapter
        get_item = getattr(stage_adapter, "get_item_at_path", None)
        can_edit = getattr(stage_adapter, "can_edit_visibility", None)
        if not callable(get_item) or not callable(can_edit):
            return False
        for path in paths:
            try:
                item = get_item(str(path))
                if item is None or not can_edit(item):
                    return False
            except Exception:
                return False
        return True

    def _push_value_command(
        self,
        paths: Sequence[str],
        record: _AttributeRecord,
        old_values: Sequence[Any],
        new_values: Sequence[Any],
    ) -> None:
        command = NativeValueEditCommand(
            self._scene,
            paths,
            _native_value_descriptor(record),
            old_values,
            new_values,
            category=(
                "visibility"
                if self._is_scene_visibility_write(record, paths)
                else "attribute"
            ),
            source="property:set",
        )
        try:
            if self._undo_manager is not None:
                self._undo_manager.push(command)
            else:
                command.do()
        except BaseException as exc:
            # Consume the edge-internal history-consistent mark before the
            # interrupt escapes to application code (see stage_adapter
            # ``_dispatch_command``); the edit itself IS recorded.
            clear_history_consistent(exc)
            self._clear_cache()
            raise
        self._clear_cache()

    def subscribe_changes(self, callback: Callable[[], None]) -> SubscriptionProtocol:
        scene = self._scene
        if scene is None or not getattr(scene, "is_open", False):
            raise_not_ready("property change subscription")
        call_later = getattr(self._stage_adapter, "_call_later", None)
        return scene.change_stream.subscribe_property(
            tuple(self._paths),
            callback,
            call_later=call_later,
        )

    def get_scheme(self) -> str:
        return "ovstage"

    def get_capabilities(self) -> PropertyCapabilities:
        return _OVSTAGE_PROPERTY_CAPABILITIES

    def _ensure_cache_current(self) -> None:
        stage = self._stage_or_none()
        if stage is None:
            self._clear_cache()
            return
        cache_key = self._make_cache_key(stage)
        if self._cache_key == cache_key:
            return

        path_descriptors = self._copy_path_descriptors(stage)
        selected_paths = [self._normalize_path(path) for path in self._paths]
        attribute_names: list[str] = []
        attribute_records: dict[str, _AttributeRecord] = {}

        if selected_paths and all(
            path is not None and path in path_descriptors
            for path in selected_paths
        ):
            normalized = tuple(str(path) for path in selected_paths)
            first_descriptor = path_descriptors[normalized[0]]
            common_names = set(first_descriptor.attributes)
            for path in normalized[1:]:
                common_names &= set(path_descriptors[path].attributes)
            for attr_name in first_descriptor.attributes:
                if attr_name not in common_names:
                    continue
                record = self._build_attribute_record(
                    stage,
                    normalized[0],
                    first_descriptor.prim_list_handle,
                    attr_name,
                )
                if record is None:
                    continue
                if not self._record_matches_all_paths(
                    stage,
                    normalized,
                    attr_name,
                    record,
                ):
                    continue
                attribute_names.append(attr_name)
                attribute_records[attr_name] = record

        self._cache_key = cache_key
        self._path_descriptors = path_descriptors
        self._attribute_names = attribute_names
        self._attribute_records = attribute_records

    def _clear_cache(self) -> None:
        self._cache_key = None
        self._path_descriptors = {}
        self._attribute_names = []
        self._attribute_records = {}

    def _stage_or_none(self) -> Any | None:
        scene = self._scene
        stage = getattr(scene, "_stage", None)
        if scene is None or stage is None or not getattr(scene, "is_open", False):
            return None
        return stage

    def _stage_for_write(self) -> Any:
        stage = self._stage_or_none()
        if stage is None:
            raise_not_ready("property value write")
        return stage

    def _runtime_write_record(self, attr_name: str) -> _AttributeRecord:
        self._ensure_cache_current()
        record = self._attribute_records.get(attr_name)
        if record is None:
            raise_not_ready("property value write")
        _validate_runtime_writable(record)
        if not _supports_exact_value_writes(self._stage_or_none()):
            raise NotImplementedError(
                "the active OVStage runtime has no exact public value-write surface"
            )
        return record

    def _normalized_selected_paths(self) -> list[str]:
        paths = [self._normalize_path(path) for path in self._paths]
        if any(path is None for path in paths):
            return []
        return [str(path) for path in paths]

    @staticmethod
    def _make_cache_key(stage: Any) -> tuple[int, int]:
        ordinal = int(getattr(stage, "current_ordinal", 0) or 0)
        try:
            topology_version = int(stage.get_topology_version())
        except Exception:
            topology_version = -1
        return (ordinal, topology_version)

    @staticmethod
    def _copy_path_descriptors(stage: Any) -> dict[str, _PathDescriptor]:
        query_result = stage.query_prims(int(stage.current_ordinal))
        records: dict[str, _PathDescriptor] = {}
        for group in query_result.get("groups", ()):
            prim_list_handle = int(group.get("prim_list_handle") or 0)
            if not prim_list_handle:
                continue
            attributes = resolve_query_names(stage, group.get("attributes", ()))
            for path in _copy_strings(stage.get_prim_paths(prim_list_handle)):
                records[path] = _PathDescriptor(
                    attributes=attributes,
                    prim_list_handle=prim_list_handle,
                )
        return records

    def _build_attribute_record(
        self,
        stage: Any,
        path: str,
        prim_list_handle: int,
        attr_name: str,
    ) -> _AttributeRecord | None:
        info = _read_attribute_info(
            stage,
            path,
            prim_list_handle,
            attr_name,
        )
        if info is None:
            return None
        raw_value = _read_attribute_bytes(stage, path, attr_name)
        if raw_value is None:
            return None

        dtype, semantic, native_is_array = info
        if not raw_value and not (
            native_is_array
            or semantic
            in {
                _SEMANTIC_ASSET_STRING,
                _SEMANTIC_PATH_EXPRESSION_STRING,
                _SEMANTIC_RELATIONSHIP_PATH_ID,
                _SEMANTIC_CONNECTION_PATH_ID,
                _SEMANTIC_STRING,
            }
        ):
            return None

        type_name, value_type, is_array, item_count = _classify_attribute(
            dtype,
            semantic,
            native_is_array,
            raw_value,
        )
        return _AttributeRecord(
            name=attr_name,
            display_name=_display_name(attr_name),
            type_name=type_name,
            value_type=value_type,
            group=_group_name(attr_name),
            dtype=dtype,
            semantic=semantic,
            is_array=is_array,
            native_is_array=native_is_array,
            is_big_array=is_array and item_count > _BIG_ARRAY_COUNT,
        )

    @staticmethod
    def _record_matches_all_paths(
        stage: Any,
        paths: tuple[str, ...],
        attr_name: str,
        record: _AttributeRecord,
    ) -> bool:
        if not callable(getattr(stage, "read_attribute_info", None)):
            return True
        expected = (
            record.dtype,
            record.semantic,
            record.is_array,
            record.native_is_array,
        )
        for path in paths[1:]:
            info = _read_attribute_info(stage, path, 0, attr_name)
            raw_value = _read_attribute_bytes(stage, path, attr_name)
            if info is None or raw_value is None:
                return False
            dtype, semantic, native_is_array = info
            classified = _classify_attribute(
                dtype,
                semantic,
                native_is_array,
                raw_value,
            )
            if (dtype, semantic, classified[2], native_is_array) != expected:
                return False
        return True

    def _values_for_attribute(self, attr_name: str) -> list[Any]:
        record = self._attribute_records.get(attr_name)
        stage = self._stage_or_none()
        if record is None or stage is None:
            return []
        values: list[Any] = []
        for path in self._paths:
            normalized_path = self._normalize_path(path)
            if normalized_path is None:
                values.append(_MISSING)
                continue
            if record.semantic in {
                _SEMANTIC_RELATIONSHIP_PATH_ID,
                _SEMANTIC_CONNECTION_PATH_ID,
            }:
                targets = _read_path_targets(
                    stage,
                    normalized_path,
                    attr_name,
                )
                values.append(_MISSING if targets is None else targets)
                continue
            raw_value = _read_attribute_bytes(stage, normalized_path, attr_name)
            if raw_value is None or (
                not raw_value
                and not record.is_array
                and record.semantic
                not in {
                    _SEMANTIC_ASSET_STRING,
                    _SEMANTIC_PATH_EXPRESSION_STRING,
                    _SEMANTIC_STRING,
                }
            ):
                values.append(_MISSING)
                continue
            values.append(_decode_value(stage, record, raw_value))
        return values

    @staticmethod
    def _normalize_path(path: str) -> str | None:
        value = str(path)
        if value == _ROOT_PATH:
            return value
        if (
            not value.startswith(_ROOT_PATH)
            or value != value.strip()
            or value.endswith(_ROOT_PATH)
            or "//" in value
            or any(part in {"", ".", ".."} for part in value.split("/")[1:])
        ):
            return None
        return value


class OvstagePropertyAdapter(PropertyAdapter):
    """Property adapter backed exclusively by OVStage-native attribute data."""

    def __init__(
        self,
        scene: Any | None = None,
        paths: List[str] | None = None,
        undo_manager: Any | None = None,
        stage_adapter: Any | None = None,
    ) -> None:
        self._native = _NativeOvstagePropertyAdapter(
            scene,
            paths,
            undo_manager,
            stage_adapter,
        )

    @property
    def _active(self) -> Any:
        return self._native

    def get_paths(self) -> List[str]:
        return self._active.get_paths()

    def is_valid(self) -> bool:
        return self._active.is_valid()

    def get_attribute_names(self) -> List[str]:
        return list(self._native.get_attribute_names())

    def get_attribute_metadata(self, attr_name: str) -> AttributeMetadata:
        return self._native.get_attribute_metadata(attr_name)

    def get_value(self, attr_name: str) -> Any:
        return self._native.get_value(attr_name)

    def is_ambiguous(self, attr_name: str) -> bool:
        return self._native.is_ambiguous(attr_name)

    def get_per_component_ambiguity(self, attr_name: str) -> Optional[List[bool]]:
        return self._native.get_per_component_ambiguity(attr_name)

    def begin_edit(self, attr_name: str) -> None:
        self._native.begin_edit(attr_name)

    def set_value(self, attr_name: str, value: Any) -> None:
        self._native.set_value(attr_name, value)

    def end_edit(self, attr_name: str) -> None:
        self._native.end_edit(attr_name)

    def subscribe_changes(self, callback: Callable[[], None]) -> SubscriptionProtocol:
        return self._native.subscribe_changes(callback)

    def get_scheme(self) -> str:
        return "ovstage"

    def get_capabilities(self) -> PropertyCapabilities:
        return _OVSTAGE_PROPERTY_CAPABILITIES

    def clear_value(self, attr_name: str) -> None:
        raise NotImplementedError(
            _OVSTAGE_PROPERTY_CAPABILITIES.clear_values.reason
        )

    def get_resolved_asset_path(self, attr_name: str) -> Optional[str]:
        return self._active.get_resolved_asset_path(attr_name)


def _copy_strings(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(str(value) for value in values)


def _read_column_dtype(
    stage: Any,
    prim_list_handle: int,
    attr_name: str,
) -> tuple[int, int, int] | None:
    try:
        _items, dtype = stage.read_column(
            int(stage.current_ordinal),
            int(prim_list_handle),
            attr_name,
        )
    except Exception:
        return None
    try:
        code, bits, lanes = dtype
    except Exception:
        return None
    return (int(code), int(bits), int(lanes))


def _read_attribute_info(
    stage: Any,
    path: str,
    prim_list_handle: int,
    attr_name: str,
) -> tuple[tuple[int, int, int], int, bool] | None:
    reader = getattr(stage, "read_attribute_info", None)
    if callable(reader):
        try:
            info = reader(
                int(stage.current_ordinal),
                str(path),
                str(attr_name),
            )
            if not isinstance(info, dict):
                return None
            code, bits, lanes = info.get("dtype")
            return (
                (int(code), int(bits), int(lanes)),
                int(info.get("semantic", _SEMANTIC_NONE)),
                bool(info.get("is_array", False)),
            )
        except Exception:
            return None

    # Older public-shaped v1 surfaces expose only a column dtype.  Preserve
    # that compatibility without inferring a semantic from the property name.
    dtype = _read_column_dtype(stage, prim_list_handle, attr_name)
    if dtype is None:
        return None
    return (dtype, _SEMANTIC_NONE, False)


def _read_attribute_bytes(stage: Any, path: str, attr_name: str) -> bytes | None:
    try:
        value = stage.read_attribute(
            int(stage.current_ordinal),
            [str(path)],
            attr_name,
        )
    except Exception:
        return None
    if not isinstance(value, (bytes, bytearray, memoryview)):
        return None
    return bytes(value)


def _read_path_targets(
    stage: Any,
    path: str,
    attr_name: str,
) -> tuple[str, ...] | None:
    reader = getattr(stage, "read_path_targets", None)
    if not callable(reader):
        return None
    try:
        targets = reader(
            int(stage.current_ordinal),
            str(path),
            str(attr_name),
        )
    except Exception:
        return None
    if targets is None:
        return None
    return tuple(str(target) for target in targets)


def _is_runtime_writable(record: _AttributeRecord) -> bool:
    if record.type_name == "unknown":
        return False
    if record.name in _WRITE_DISABLED_ATTRS:
        return False
    if record.name.startswith(_WRITE_DISABLED_PREFIXES):
        return False
    code, bits, lanes = record.dtype
    if lanes <= 0 or record.semantic not in _KNOWN_SEMANTICS:
        return False
    if record.semantic in {
        _SEMANTIC_ASSET_STRING,
        _SEMANTIC_PATH_EXPRESSION_STRING,
        _SEMANTIC_STRING,
    }:
        return (
            code,
            bits,
            lanes,
            record.native_is_array,
        ) == (_DLPACK_UINT, 8, 1, True)
    if record.semantic == _SEMANTIC_TOKEN_ID:
        return (code, bits, lanes) == (_DLPACK_UINT, 64, 1)
    if record.semantic == _SEMANTIC_RELATIONSHIP_PATH_ID:
        return (
            code,
            bits,
            lanes,
            record.native_is_array,
        ) == (_DLPACK_UINT, 64, 1, True)
    if record.semantic == _SEMANTIC_CONNECTION_PATH_ID:
        return (
            code,
            bits,
            lanes,
            record.native_is_array,
        ) == (_DLPACK_UINT, 64, 2, True)
    if lanes not in {1, 2, 3, 4, 6, 9, 16}:
        return False
    return _struct_format_char(code, bits) is not None


def _supports_exact_value_writes(stage: Any | None) -> bool:
    return bool(
        stage is not None
        and callable(getattr(stage, "begin_frame", None))
        and callable(getattr(stage, "end_frame", None))
        and callable(getattr(stage, "query_from_path_list", None))
        and callable(getattr(stage, "write_attributes", None))
    )


def _validate_runtime_writable(record: _AttributeRecord) -> None:
    if record.name in _WRITE_DISABLED_ATTRS or record.name.startswith(_WRITE_DISABLED_PREFIXES):
        raise NotImplementedError(
            "ovstage reserved, computed, and transform-control properties are not "
            "editable through the generic property surface"
        )
    if not _is_runtime_writable(record):
        raise NotImplementedError(
            "ovstage property descriptor has no exact public write encoding"
        )


def _native_value_descriptor(record: _AttributeRecord) -> NativeValueDescriptor:
    return NativeValueDescriptor(
        name=record.name,
        dtype=record.dtype,
        semantic=record.semantic,
        native_is_array=record.native_is_array,
        logical_is_array=record.is_array,
    )


def _classify_attribute(
    dtype: tuple[int, int, int],
    semantic: int,
    is_array: bool,
    raw_value: bytes,
) -> tuple[str, Any, bool, int]:
    code, bits, lanes = (int(value) for value in dtype)
    item_count = len(raw_value) // max(1, _unit_size(dtype))

    if not _is_valid_native_layout(dtype, semantic, is_array, raw_value):
        return ("unknown", tuple, bool(is_array), item_count)

    if semantic in {
        _SEMANTIC_RELATIONSHIP_PATH_ID,
        _SEMANTIC_CONNECTION_PATH_ID,
    }:
        return ("relationship", "relationship", True, item_count)
    if semantic == _SEMANTIC_STRING:
        return ("string", str, False, 1)
    if semantic in {
        _SEMANTIC_ASSET_STRING,
        _SEMANTIC_PATH_EXPRESSION_STRING,
    }:
        decoded_parts = _decode_byte_strings(raw_value)
        if len(decoded_parts) > 1:
            return ("array", "array", True, len(decoded_parts))
        if semantic == _SEMANTIC_ASSET_STRING:
            return ("asset", "asset", False, 1)
        return ("string", str, False, 1)
    if semantic == _SEMANTIC_TOKEN_ID:
        if is_array:
            return ("array", "array", True, item_count)
        return ("token", str, False, 1)
    if is_array:
        return ("array", "array", True, item_count)
    if code == _DLPACK_BOOL:
        return ("bool", bool, False, 1)
    if semantic == _SEMANTIC_MATRIX:
        dimension = _matrix_dimension_or_none(lanes)
        if dimension is not None:
            return (f"matrix{dimension}d", tuple, False, 1)
        return ("unknown", tuple, False, 1)
    semantic_type = _semantic_numeric_type_name(semantic, bits, lanes)
    if semantic_type is not None:
        return (
            semantic_type,
            _semantic_value_type(semantic, lanes),
            False,
            1,
        )
    if code == _DLPACK_FLOAT:
        return (
            _float_type_name(bits, lanes),
            _float_value_type(lanes),
            False,
            1,
        )
    if code in (_DLPACK_INT, _DLPACK_UINT):
        if lanes in (2, 3, 4):
            return (f"int{lanes}", f"int{lanes}", False, 1)
        if lanes == 1:
            return ("int", int, False, 1)
        return (f"int{lanes}", tuple, False, 1)
    return ("unknown", tuple, False, 1)


def _decode_value(stage: Any, record: _AttributeRecord, raw_value: bytes) -> Any:
    dtype = record.dtype
    if record.type_name == "unknown":
        return tuple(raw_value)
    if record.type_name == "bool":
        return bool(raw_value and raw_value[0])
    if record.semantic == _SEMANTIC_TOKEN_ID and not record.is_array:
        if len(raw_value) == 8:
            return _resolve_token(stage, raw_value)
        return ""
    if record.semantic in {
        _SEMANTIC_STRING,
        _SEMANTIC_ASSET_STRING,
        _SEMANTIC_PATH_EXPRESSION_STRING,
    } and not record.is_array:
        values = _decode_byte_strings(raw_value)
        return values[0] if values else ""
    if record.type_name == "array":
        return _decode_array(stage, record, raw_value)
    if record.type_name.startswith("matrix"):
        return _decode_numeric_tuple(dtype, raw_value)
    code, _bits, lanes = dtype
    values = _decode_numeric_tuple(dtype, raw_value)
    if code == _DLPACK_FLOAT:
        if lanes == 1:
            return values[0]
        return values
    if code in (_DLPACK_INT, _DLPACK_UINT):
        if lanes == 1:
            return values[0]
        return values
    return tuple(raw_value)


def _decode_array(
    stage: Any,
    record: _AttributeRecord,
    raw_value: bytes,
) -> tuple[Any, ...]:
    dtype = record.dtype
    if record.semantic in {
        _SEMANTIC_STRING,
        _SEMANTIC_ASSET_STRING,
        _SEMANTIC_PATH_EXPRESSION_STRING,
    }:
        return _decode_byte_strings(raw_value)
    if record.semantic == _SEMANTIC_TOKEN_ID:
        if len(raw_value) % 8:
            return ()
        token_ids = struct.unpack(f"<{len(raw_value) // 8}Q", raw_value)
        return tuple(_resolve_token_id(stage, token_id) for token_id in token_ids)
    code, _bits, lanes = dtype
    values = _decode_numeric_tuple(dtype, raw_value)
    if lanes <= 1:
        return values
    return tuple(values[index:index + lanes] for index in range(0, len(values), lanes))


def _decode_numeric_tuple(
    dtype: tuple[int, int, int],
    raw_value: bytes,
) -> tuple[int | float, ...]:
    code, bits, _lanes = dtype
    if not raw_value:
        return ()
    format_char = _struct_format_char(code, bits)
    if format_char is None:
        return ()
    scalar_size = max(1, bits // 8)
    if len(raw_value) % scalar_size:
        return ()
    count = len(raw_value) // scalar_size
    return struct.unpack(f"<{count}{format_char}", raw_value)


def _struct_format_char(code: int, bits: int) -> str | None:
    if code == _DLPACK_FLOAT:
        if bits == 16:
            return "e"
        if bits == 32:
            return "f"
        if bits == 64:
            return "d"
    if code == _DLPACK_INT:
        return {8: "b", 16: "h", 32: "i", 64: "q"}.get(bits)
    if code == _DLPACK_UINT:
        return {8: "B", 16: "H", 32: "I", 64: "Q"}.get(bits)
    if code == _DLPACK_BOOL and bits == 8:
        return "?"
    return None


def _unit_size(dtype: tuple[int, int, int]) -> int:
    _code, bits, lanes = dtype
    return max(1, bits // 8) * max(1, lanes)


def _is_valid_native_layout(
    dtype: tuple[int, int, int],
    semantic: int,
    is_array: bool,
    raw_value: bytes,
) -> bool:
    code, bits, lanes = (int(value) for value in dtype)
    if semantic not in _KNOWN_SEMANTICS or bits <= 0 or lanes <= 0:
        return False
    if semantic in {
        _SEMANTIC_ASSET_STRING,
        _SEMANTIC_PATH_EXPRESSION_STRING,
        _SEMANTIC_STRING,
    }:
        return (code, bits, lanes, bool(is_array)) == (_DLPACK_UINT, 8, 1, True)
    if semantic == _SEMANTIC_TOKEN_ID:
        return (
            (code, bits, lanes) == (_DLPACK_UINT, 64, 1)
            and (
                len(raw_value) % 8 == 0
                if is_array
                else len(raw_value) == 8
            )
        )
    if semantic == _SEMANTIC_RELATIONSHIP_PATH_ID:
        return (
            (code, bits, lanes, bool(is_array)) == (_DLPACK_UINT, 64, 1, True)
            and len(raw_value) % 8 == 0
        )
    if semantic == _SEMANTIC_CONNECTION_PATH_ID:
        return (
            (code, bits, lanes, bool(is_array)) == (_DLPACK_UINT, 64, 2, True)
            and len(raw_value) % 16 == 0
        )
    if _struct_format_char(code, bits) is None:
        return False
    if semantic == _SEMANTIC_MATRIX:
        if code != _DLPACK_FLOAT or lanes not in {4, 9, 16}:
            return False
    elif semantic in {
        _SEMANTIC_POINT,
        _SEMANTIC_VECTOR,
        _SEMANTIC_NORMAL,
        _SEMANTIC_COLOR,
        _SEMANTIC_QUATERNION,
        _SEMANTIC_TEXTURE_COORDINATE,
    } and (code != _DLPACK_FLOAT or lanes not in {2, 3, 4}):
        return False

    unit_size = _unit_size(dtype)
    if is_array:
        return len(raw_value) % unit_size == 0
    return len(raw_value) == unit_size


def _resolve_token(stage: Any, raw_value: bytes) -> str:
    token_id = struct.unpack("<Q", raw_value)[0]
    return _resolve_token_id(stage, token_id)


def _resolve_token_id(stage: Any, token_id: int) -> str:
    return resolve_token_id(stage, token_id)


def _matrix_dimension_or_none(lanes: int) -> int | None:
    if lanes == 4:
        return 2
    if lanes == 9:
        return 3
    if lanes == 16:
        return 4
    return None


def _float_type_name(bits: int, lanes: int) -> str:
    prefix = _float_precision_name(bits)
    if lanes == 1:
        return prefix
    if lanes in (2, 3, 4):
        return f"{prefix}{lanes}"
    return f"{prefix}{lanes}"


def _float_precision_name(bits: int) -> str:
    if bits == 16:
        return "half"
    if bits == 64:
        return "double"
    return "float"


def _float_precision_suffix(bits: int) -> str:
    return {16: "h", 64: "d"}.get(bits, "f")


def _float_value_type(lanes: int) -> Any:
    if lanes == 1:
        return float
    if lanes in (2, 3, 4):
        return f"float{lanes}"
    return tuple


def _semantic_numeric_type_name(
    semantic: int,
    bits: int,
    lanes: int,
) -> str | None:
    prefix = {
        _SEMANTIC_POINT: "point",
        _SEMANTIC_VECTOR: "vector",
        _SEMANTIC_NORMAL: "normal",
        _SEMANTIC_COLOR: "color",
        _SEMANTIC_QUATERNION: "quat",
        _SEMANTIC_TEXTURE_COORDINATE: "texCoord",
    }.get(int(semantic))
    if prefix is None:
        return None
    suffix = _float_precision_suffix(bits)
    if semantic == _SEMANTIC_QUATERNION:
        return f"{prefix}{suffix}"
    return f"{prefix}{lanes}{suffix}"


def _semantic_value_type(semantic: int, lanes: int) -> Any:
    if semantic == _SEMANTIC_COLOR and lanes in (3, 4):
        return f"color{lanes}f"
    if semantic in {
        _SEMANTIC_POINT,
        _SEMANTIC_VECTOR,
        _SEMANTIC_NORMAL,
        _SEMANTIC_TEXTURE_COORDINATE,
    } and lanes in (2, 3, 4):
        return f"float{lanes}"
    return tuple


def _decode_byte_strings(raw_value: bytes) -> tuple[str, ...]:
    if not raw_value:
        return ()
    payload = raw_value[:-1] if raw_value.endswith(b"\x00") else raw_value
    return tuple(
        part.decode("utf-8", errors="replace")
        for part in payload.split(b"\x00")
    )


def _group_name(attr_name: str) -> str:
    if ":" not in attr_name:
        return "Attributes"
    namespace = attr_name.split(":", 1)[0]
    return _title_words(namespace)


def _display_name(attr_name: str) -> str:
    leaf = attr_name.rsplit(":", 1)[-1]
    return _title_words(leaf)


def _title_words(value: str) -> str:
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", value)
    spaced = spaced.replace("_", " ").replace("-", " ")
    return " ".join(word.capitalize() for word in spaced.split()) or value


def _is_flat_component_tuple(value: Any) -> bool:
    return (
        isinstance(value, tuple)
        and bool(value)
        and all(isinstance(component, (int, float)) for component in value)
    )

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Helpers for consuming native ovstage api_v2 query/read results."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
import struct
from importlib import import_module
from typing import Any, Iterable


_TOKEN_PLACEHOLDER_RE = re.compile(r"^<token ([0-9]+)>$")
_OVX_API_SUCCESS = 0
_POPULATION_STAGE_INFO_PATH = "/__ovstage_population_stage_info__"
_DLPACK_UINT = 1
_DLPACK_FLOAT = 2
_DLPACK_BOOL = 6
_ASSET_STRING_SEMANTIC = 1
_TOKEN_ID_SEMANTIC = 2
_PATH_EXPRESSION_STRING_SEMANTIC = 3
_RELATIONSHIP_PATH_ID_SEMANTIC = 4
_MATRIX_SEMANTIC = 10
_STRING_SEMANTIC = 13
_MATRIX_FABRIC_COLUMNS = {
    "localMatrix": "omni:fabric:localMatrix",
    "worldMatrix": "omni:fabric:worldMatrix",
}


@dataclass(frozen=True)
class NativePathAttributeRecord:
    """One Python-owned value copied from one exact native prim path."""

    name: str
    dtype: tuple[int, int, int]
    semantic: int
    native_is_array: bool
    value: Any


def read_paths_attribute_records(
    stage: Any,
    prim_paths: Iterable[str],
    attribute_names: Iterable[str],
) -> dict[str, dict[str, NativePathAttributeRecord]]:
    """Copy fixed columns for many exact paths in one native query/read pass."""

    if not (
        callable(getattr(stage, "query_from_path_list", None))
        and callable(getattr(stage, "read_attributes", None))
        and callable(getattr(stage, "release_group", None))
    ):
        return {}
    normalized_paths = tuple(
        dict.fromkeys(str(path) for path in prim_paths if str(path))
    )
    requested = tuple(
        dict.fromkeys(str(name) for name in attribute_names if str(name))
    )
    if not normalized_paths or not requested:
        return {}

    ovstage = import_module("ovstage")
    expected_paths = frozenset(normalized_paths)
    copied: dict[str, dict[str, NativePathAttributeRecord]] = {}
    with ovstage.PathDictionary(stage) as paths:
        path_list = paths.create_path_list_from_strings(normalized_paths)
        try:
            with stage.query_from_path_list(path_list) as query:
                query.wait()
                result = query.result()
                discovered = frozenset(
                    str(paths.token_to_string(int(token)))
                    for token in getattr(result, "attributes", ())
                )
                names = tuple(name for name in requested if name in discovered)
                if not names:
                    return {}
                tokens = {name: paths.intern_token(name) for name in names}
                token_names = {int(token): name for name, token in tokens.items()}
                ordinal_range = ovstage.OrdinalRange.latest(int(stage.current_ordinal))
                with stage.read_attributes(
                    query,
                    list(tokens.values()),
                    ordinal_range,
                ) as read:
                    read.wait()
                    for group in read.groups():
                        try:
                            name = token_names.get(
                                int(getattr(group, "attribute", 0) or 0)
                            )
                            if name is None:
                                continue
                            for path, record in _copy_path_attribute_group_rows(
                                paths,
                                group,
                                expected_paths,
                                name,
                            ).items():
                                copied.setdefault(path, {})[name] = record
                        finally:
                            stage.release_group(group)
        finally:
            paths.destroy_path_list(path_list)
    return copied


def read_path_attribute_records(
    stage: Any,
    path: str,
    attribute_names: Iterable[str] | None = None,
) -> dict[str, NativePathAttributeRecord]:
    """Copy selected columns for one exact path without a full-stage cache.

    When ``attribute_names`` is omitted, every attribute advertised by that
    one-path query is copied.  An empty result means no requested value was
    available; OVStage's query cardinality does not prove path existence.  No
    compatibility ``query_prims`` or property-adapter cache is involved.
    """

    if not (
        callable(getattr(stage, "query_from_path_list", None))
        and callable(getattr(stage, "read_attributes", None))
        and callable(getattr(stage, "release_group", None))
    ):
        return {}

    ovstage = import_module("ovstage")
    requested = (
        None
        if attribute_names is None
        else tuple(dict.fromkeys(str(name) for name in attribute_names if str(name)))
    )
    normalized_path = str(path)
    records: dict[str, NativePathAttributeRecord] = {}
    with ovstage.PathDictionary(stage) as paths:
        path_list = paths.create_path_list_from_strings([normalized_path])
        try:
            with stage.query_from_path_list(path_list) as query:
                query.wait()
                result = query.result()
                discovered = tuple(
                    str(paths.token_to_string(int(token)))
                    for token in getattr(result, "attributes", ())
                )
                names = (
                    discovered
                    if requested is None
                    else tuple(name for name in requested if name in discovered)
                )
                if not names:
                    return {}
                tokens = {name: paths.intern_token(name) for name in names}
                token_names = {int(token): name for name, token in tokens.items()}
                ordinal_range = ovstage.OrdinalRange.latest(int(stage.current_ordinal))
                with stage.read_attributes(
                    query,
                    list(tokens.values()),
                    ordinal_range,
                ) as read:
                    read.wait()
                    for group in read.groups():
                        try:
                            name = token_names.get(
                                int(getattr(group, "attribute", 0) or 0)
                            )
                            if name is None:
                                continue
                            record = _copy_path_attribute_group(
                                paths,
                                group,
                                normalized_path,
                                name,
                            )
                            if record is not None:
                                records[name] = record
                        finally:
                            stage.release_group(group)
        finally:
            paths.destroy_path_list(path_list)
    return records


def _copy_path_attribute_group(
    paths: Any,
    group: Any,
    expected_path: str,
    name: str,
) -> NativePathAttributeRecord | None:
    """Copy the row for ``expected_path`` from one native read group."""

    return _copy_path_attribute_group_rows(
        paths,
        group,
        frozenset({str(expected_path)}),
        name,
    ).get(str(expected_path))


def _copy_path_attribute_group_rows(
    paths: Any,
    group: Any,
    expected_paths: frozenset[str],
    name: str,
) -> dict[str, NativePathAttributeRecord]:
    """Copy all requested path rows from one native attribute group."""

    try:
        group_paths = tuple(
            str(path) for path in paths.get_path_strings(group.prim_list)
        )
        raw = getattr(group, "raw", None)
        semantic = int(getattr(raw, "semantic", 0) or 0)
        native_is_array = bool(getattr(raw, "is_array", False))
        tensor_count = int(getattr(group, "tensor_count", 0) or 0)
        data_count = int(getattr(group, "data_count", 0) or 0)
    except Exception:
        return {}

    copied: dict[str, NativePathAttributeRecord] = {}
    for local_index in range(int(group.prim_count)):
        try:
            prim_index = int(group.prim_index(local_index))
            path = group_paths[prim_index]
            if path not in expected_paths:
                continue
            data_index = int(group.data_row_index(local_index))
            if native_is_array:
                if data_index < 0 or data_index >= tensor_count:
                    continue
                tensor_index = data_index
                dtype_obj = group.tensor(tensor_index).dtype
                dtype = (
                    int(dtype_obj.code),
                    int(dtype_obj.bits),
                    int(dtype_obj.lanes),
                )
                array = group.array(tensor_index).reshape(-1)
                raw_values = array.tolist()
            else:
                if tensor_count != 1:
                    continue
                tensor_index = 0
                tensor = group.tensor(0)
                dtype_obj = tensor.dtype
                dtype = (
                    int(dtype_obj.code),
                    int(dtype_obj.bits),
                    int(dtype_obj.lanes),
                )
                array = group.array(0).reshape(-1)
                shape = tuple(
                    int(value)
                    for value in (getattr(tensor, "shape_tuple", ()) or ())
                )
                lanes = int(dtype[2])
                row_count = (
                    int(shape[0])
                    if shape
                    else int(array.size) // max(lanes, 1)
                )
                width = (
                    math.prod(shape[1:]) * lanes
                    if shape
                    else lanes
                )
                if width <= 0 or data_index < 0 or data_index >= row_count:
                    continue
                start = data_index * width
                if start < 0 or start + width > int(array.size):
                    continue
                raw_values = array[start:start + width].tolist()
            value = _decode_path_attribute_values(
                paths,
                raw_values,
                dtype,
                semantic,
                native_is_array,
            )
            # The Kit bridge exposes ``usd-prim-type`` as a scalar uint64
            # token id with semantic NONE.  Preserve the public logical type
            # value rather than leaking a stage-owned dictionary id.
            if name == "usd-prim-type" and isinstance(value, int):
                value = str(paths.token_to_string(value))
        except Exception:
            continue
        copied[path] = NativePathAttributeRecord(
            name=str(name),
            dtype=dtype,
            semantic=semantic,
            native_is_array=native_is_array,
            value=value,
        )
    return copied


def _decode_path_attribute_values(
    paths: Any,
    values: list[Any],
    dtype: tuple[int, int, int],
    semantic: int,
    native_is_array: bool,
) -> Any:
    """Decode the scalar/array kinds used by catalog and renderer metadata."""

    code, _bits, lanes = dtype
    if semantic in {
        _ASSET_STRING_SEMANTIC,
        _PATH_EXPRESSION_STRING_SEMANTIC,
        _STRING_SEMANTIC,
    }:
        raw = bytes(int(value) & 0xFF for value in values)
        payload = raw[:-1] if raw.endswith(b"\0") else raw
        decoded_strings = tuple(
            item.decode("utf-8", errors="replace")
            for item in payload.split(b"\0")
        )
        if semantic != _STRING_SEMANTIC and len(decoded_strings) > 1:
            return decoded_strings
        return decoded_strings[0] if decoded_strings else ""
    if semantic == _TOKEN_ID_SEMANTIC:
        decoded = tuple(paths.token_to_string(int(value)) for value in values)
    elif semantic == _RELATIONSHIP_PATH_ID_SEMANTIC:
        decoded = tuple(paths.path_to_string(int(value)) for value in values)
    elif code == _DLPACK_BOOL:
        decoded = tuple(bool(value) for value in values)
    elif code in (0, _DLPACK_UINT):
        decoded = tuple(int(value) for value in values)
    elif code == _DLPACK_FLOAT:
        decoded = tuple(float(value) for value in values)
    else:
        decoded = tuple(values)

    if native_is_array:
        if lanes <= 1:
            return decoded
        return tuple(
            decoded[index:index + lanes]
            for index in range(0, len(decoded), lanes)
        )
    if lanes <= 1:
        return decoded[0] if decoded else None
    return decoded


def resolve_query_names(stage: Any, names: Iterable[Any]) -> tuple[str, ...]:
    """Resolve ovstage ``<token N>`` query names through the native dictionary."""
    return tuple(resolve_query_name(stage, name) for name in names)


def resolve_query_name(stage: Any, name: Any) -> str:
    text = str(name)
    match = _TOKEN_PLACEHOLDER_RE.fullmatch(text)
    if match is None:
        return text
    resolved = resolve_token_id(stage, int(match.group(1)))
    return resolved or text


def read_token_attribute(stage: Any, path: str, attr_name: str) -> str | None:
    raw_value = _read_attribute_bytes(stage, path, attr_name)
    if not raw_value:
        return None
    try:
        text = raw_value.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    if text and "\x00" not in text:
        return text
    if len(raw_value) == 8:
        token_id = struct.unpack("<Q", raw_value)[0]
        resolved = resolve_token_id(stage, token_id)
        if resolved:
            return resolved
    return None


def read_population_up_axis(stage: Any) -> str | None:
    """Copy the populated stage up-axis through OVStage's public query API.

    ``ovstage.populate_from_file`` publishes source stage units on its reserved
    stage-info prim.  The prim is intentionally absent from the user hierarchy,
    so this narrow native read bypasses the user-facing compatibility cache
    while retaining the query/read/group ownership required by OVStage.
    """

    ovstage = import_module("ovstage")
    with ovstage.PathDictionary(stage) as paths:
        token = paths.intern_token("upAxis")
        with stage.query(None, [token]) as query:
            query.wait()
            ordinal_range = ovstage.OrdinalRange.latest(int(stage.current_ordinal))
            with stage.read_attributes(query, [token], ordinal_range) as read:
                read.wait()
                for group in read.groups():
                    try:
                        result = _copy_up_axis_group(paths, group, token)
                    finally:
                        stage.release_group(group)
                    if result is not None:
                        return result
    return None


def read_population_meters_per_unit(stage: Any) -> float | None:
    """Copy populated ``metersPerUnit`` from OVStage's reserved stage info."""

    records = read_path_attribute_records(
        stage,
        _POPULATION_STAGE_INFO_PATH,
        ("metersPerUnit",),
    )
    record = records.get("metersPerUnit")
    if record is None:
        return None
    try:
        value = float(record.value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0.0:
        return None
    return value


def read_matrix_attribute(
    stage: Any,
    path: str,
    attr_name: str,
) -> tuple[float, ...] | None:
    """Copy one validated native matrix for one path, or ``None``.

    On a Kit stage exposing the public query surface this is a narrow probe —
    one path, one attribute, at the latest ordinal — and never routes through
    the ordinal-keyed full-stage compatibility cache: held-drag preview
    writers probe transform columns on every write while each committed write
    advances the ordinal, so a cache-backed read here would rebuild the
    full-stage cache once per pointer move (the Outcome 1 frame-rate
    collapse).  Stages without that surface use the exposed read-attribute
    compatibility path.  Both validate the same descriptor: a non-array float
    16-lane MATRIX column with finite values.
    """

    if not (
        callable(getattr(stage, "query_from_path_list", None))
        and callable(getattr(stage, "read_attributes", None))
        and callable(getattr(stage, "release_group", None))
    ):
        return _read_matrix_attribute_compat(stage, path, attr_name)

    normalized_path = str(path)
    # The common matrix names are bridge-exposed aliases; the native columns
    # are the fabric names (kept in sync with _scene._KIT_MATRIX_ALIASES).
    native_attr = _MATRIX_FABRIC_COLUMNS.get(str(attr_name), str(attr_name))
    try:
        ovstage = import_module("ovstage")
        with ovstage.PathDictionary(stage) as paths:
            token = paths.intern_token(native_attr)
            path_list = paths.create_path_list_from_strings([normalized_path])
            try:
                with stage.query_from_path_list(path_list) as query:
                    query.wait()
                    ordinal_range = ovstage.OrdinalRange.latest(
                        int(stage.current_ordinal)
                    )
                    with stage.read_attributes(
                        query, [token], ordinal_range
                    ) as read:
                        read.wait()
                        for group in read.groups():
                            try:
                                values = _copy_matrix_group(group, token)
                            finally:
                                stage.release_group(group)
                            if values is not None:
                                return values
            finally:
                paths.destroy_path_list(path_list)
    except Exception:
        return None
    return None


def _read_matrix_attribute_compat(
    stage: Any,
    path: str,
    attr_name: str,
) -> tuple[float, ...] | None:
    """Matrix read for stages without the public query surface (fakes/legacy)."""

    info_reader = getattr(stage, "read_attribute_info", None)
    if callable(info_reader):
        try:
            info = info_reader(
                int(stage.current_ordinal),
                str(path),
                str(attr_name),
            )
        except Exception:
            return None
        if not _is_matrix_info(info):
            return None

    raw = _read_attribute_bytes(stage, path, attr_name)
    if len(raw) == 16 * 8:
        values = tuple(float(value) for value in struct.unpack("<16d", raw))
    elif len(raw) == 16 * 4:
        values = tuple(float(value) for value in struct.unpack("<16f", raw))
    else:
        return None
    if not all(math.isfinite(value) for value in values):
        return None
    return values


def _is_matrix_info(info: Any) -> bool:
    if not isinstance(info, dict):
        return False
    try:
        code, bits, lanes = info["dtype"]
        semantic = int(info["semantic"])
        is_array = bool(info["is_array"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        int(code) == _DLPACK_FLOAT
        and int(bits) in {32, 64}
        and int(lanes) == 16
        and semantic == _MATRIX_SEMANTIC
        and not is_array
    )


def _copy_matrix_group(group: Any, token: int) -> tuple[float, ...] | None:
    """Copy one validated 16-lane float MATRIX row from a read group."""

    if int(getattr(group, "attribute", 0) or 0) != int(token):
        return None
    raw = getattr(group, "raw", None)
    if bool(getattr(group, "is_array", False)) or bool(
        getattr(raw, "is_array", False)
    ):
        return None
    if int(getattr(raw, "semantic", 0) or 0) != _MATRIX_SEMANTIC:
        return None
    if int(getattr(group, "tensor_count", 0) or 0) != 1:
        return None
    try:
        dtype = group.tensor(0).dtype
        if (
            int(dtype.code) != _DLPACK_FLOAT
            or int(dtype.bits) not in {32, 64}
            or int(dtype.lanes) != 16
        ):
            return None
        prim_count = int(group.prim_count)
        data_count = int(group.data_count)
        if prim_count != 1 or data_count < 1:
            return None
        data_index = int(group.data_row_index(0))
        row = group.array(0).reshape(data_count, -1)[data_index]
        values = tuple(float(value) for value in row.reshape(-1).tolist())
    except Exception:
        return None
    if len(values) != 16:
        return None
    if not all(math.isfinite(value) for value in values):
        return None
    return values


def resolve_token_id(stage: Any, token_id: int) -> str:
    token = int(token_id)
    if token <= 0:
        return ""

    path_dict = getattr(stage, "_path_dict", None)
    if callable(path_dict):
        try:
            dictionary_bindings, dictionary_pointer = path_dict()
            status, resolved = dictionary_bindings.token_to_string(
                dictionary_pointer,
                token,
            )
        except Exception:
            resolved = ""
        else:
            if int(status) == _OVX_API_SUCCESS and resolved:
                return str(resolved)

    # Kit's api_v2 Stage deliberately does not expose the legacy private
    # ``_path_dict`` hook.  Token and path IDs belong to the OVStage that
    # produced them, so resolve them through OVStage's public dictionary
    # rather than involving the renderer's dictionary in BORROW mode.
    dictionary = None
    try:
        ovstage = import_module("ovstage")
        dictionary = ovstage.PathDictionary(stage)
        resolved = str(dictionary.token_to_string(token))
    except Exception:
        resolved = ""
    finally:
        destroy = getattr(dictionary, "destroy", None)
        if callable(destroy):
            try:
                destroy()
            except Exception:
                pass
    if resolved and _TOKEN_PLACEHOLDER_RE.fullmatch(resolved) is None:
        return resolved

    resolver = getattr(stage, "resolve_token", None)
    if callable(resolver):
        try:
            resolved = str(resolver(token))
        except Exception:
            return ""
        if resolved and _TOKEN_PLACEHOLDER_RE.fullmatch(resolved) is None:
            return resolved
        return resolved
    return ""


def _copy_up_axis_group(paths: Any, group: Any, token: int) -> str | None:
    if int(getattr(group, "attribute", 0) or 0) != int(token):
        return None
    if bool(getattr(group, "is_array", False)):
        return None
    if int(getattr(group, "tensor_count", 0) or 0) != 1:
        return None
    try:
        dtype = group.tensor(0).dtype
        if (
            int(dtype.code),
            int(dtype.bits),
            int(dtype.lanes),
        ) != (_DLPACK_UINT, 64, 1):
            return None
        group_paths = tuple(
            str(path) for path in paths.get_path_strings(group.prim_list)
        )
        values = group.array(0).reshape(-1).tolist()
        prim_count = int(group.prim_count)
        data_count = int(group.data_count)
    except Exception:
        return None
    if prim_count <= 0 or data_count <= 0 or len(values) != data_count:
        return None
    for local_index in range(prim_count):
        try:
            prim_index = int(group.prim_index(local_index))
            data_index = int(group.data_row_index(local_index))
            path = group_paths[prim_index]
            token_id = int(values[data_index])
        except (IndexError, TypeError, ValueError):
            continue
        if path != _POPULATION_STAGE_INFO_PATH:
            continue
        try:
            axis = str(paths.token_to_string(token_id)).upper()
        except Exception:
            return None
        return axis if axis in {"Y", "Z"} else None
    return None


def _read_attribute_bytes(stage: Any, path: str, attr_name: str) -> bytes:
    try:
        value = stage.read_attribute(
            int(stage.current_ordinal),
            [str(path)],
            str(attr_name),
        )
    except Exception:
        return b""
    if not isinstance(value, (bytes, bytearray, memoryview)):
        return b""
    return bytes(value)

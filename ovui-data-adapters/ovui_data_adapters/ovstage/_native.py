# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Helpers for consuming native ovstage api_v2 query/read results."""

from __future__ import annotations

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
_MATRIX_SEMANTIC = 10
_MATRIX_FABRIC_COLUMNS = {
    "localMatrix": "omni:fabric:localMatrix",
    "worldMatrix": "omni:fabric:worldMatrix",
}


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

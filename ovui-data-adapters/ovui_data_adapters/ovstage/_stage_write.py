# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Native Kit OVStage copy-in helpers.

The Kit OVStage Python API writes through a path-list query and DLPack.  This
module keeps that plumbing in one place so every ovui adapter authors the
OVStage owner directly.  In particular, renderer adapters must never fall back
to an OVRTX stage-data API while OVRTX is attached in BORROW mode.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Iterable, Sequence

import numpy as np

_WRITE_JOURNAL_ATTRIBUTE = "_ovui_native_write_journal"
_WRITE_JOURNAL_MAX_ORDINALS = 256


def recorded_stage_writes(
    stage: Any,
    *,
    since_ordinal: int,
    current_ordinal: int,
) -> dict[str, set[str]]:
    """Return successful copy-in writes in ``(since, current]``.

    OVStage is authoritative for dirty membership.  The small journal is a
    compatibility supplement for a current native edge case: the first write
    of a newly upserted column is readable at the committed ordinal, but may be
    absent from an ordinal-bounded ``read_attributes`` result.  Recording the
    already-known path and attribute keeps adapter subscriptions deterministic
    without inspecting or mutating OVRTX data.
    """

    since = int(since_ordinal)
    current = int(current_ordinal)
    if current <= since:
        return {}
    journal = getattr(stage, _WRITE_JOURNAL_ATTRIBUTE, None)
    if not isinstance(journal, dict):
        return {}
    result: dict[str, set[str]] = {}
    for raw_ordinal, writes in tuple(journal.items()):
        try:
            ordinal = int(raw_ordinal)
        except (TypeError, ValueError):
            continue
        if ordinal <= since or ordinal > current or not isinstance(writes, dict):
            continue
        for attribute_name, paths in writes.items():
            result.setdefault(str(attribute_name), set()).update(
                str(path) for path in paths if str(path)
            )
    return result


def discard_recorded_stage_writes(stage: Any, *, through_ordinal: int) -> None:
    """Discard journal entries consumed by the scene's shared change stream."""

    journal = getattr(stage, _WRITE_JOURNAL_ATTRIBUTE, None)
    if not isinstance(journal, dict):
        return
    through = int(through_ordinal)
    for raw_ordinal in tuple(journal):
        try:
            ordinal = int(raw_ordinal)
        except (TypeError, ValueError):
            journal.pop(raw_ordinal, None)
            continue
        if ordinal <= through:
            journal.pop(raw_ordinal, None)


def _record_stage_write(
    stage: Any,
    *,
    ordinal: int,
    attribute_name: str,
    prim_paths: Sequence[str],
) -> None:
    journal = getattr(stage, _WRITE_JOURNAL_ATTRIBUTE, None)
    if not isinstance(journal, dict):
        journal = {}
        setattr(stage, _WRITE_JOURNAL_ATTRIBUTE, journal)
    ordinal_writes = journal.setdefault(int(ordinal), {})
    attribute_paths = ordinal_writes.setdefault(str(attribute_name), set())
    attribute_paths.update(str(path) for path in prim_paths if str(path))

    # The shared change stream normally consumes entries every frame.  Keep a
    # bounded tail as protection for renderer-only sessions with no subscribers.
    if len(journal) > _WRITE_JOURNAL_MAX_ORDINALS:
        for stale_ordinal in sorted(journal)[: -_WRITE_JOURNAL_MAX_ORDINALS]:
            journal.pop(stale_ordinal, None)


def supports_native_stage_writes(stage: Any) -> bool:
    """Return whether *stage* exposes the Kit query/DLPack write surface."""

    return (
        stage is not None
        and callable(getattr(stage, "write_attribute", None))
        and callable(getattr(stage, "query_from_path_list", None))
        and callable(getattr(stage, "begin_frame", None))
        and callable(getattr(stage, "end_frame", None))
    )


def wait_operation(operation: Any) -> Any:
    """Wait for an OVStage operation when the wrapper returned one."""

    wait = getattr(operation, "wait", None)
    return wait() if callable(wait) else operation


class StageWriteBatch:
    """Write one or more fixed-width attributes at a single fresh ordinal.

    A batch owns one path-list query.  Each row corresponds to one path passed
    to the constructor; vector/matrix width is represented with DLPack lanes,
    matching the public Kit OVStage tests.
    """

    def __init__(
        self,
        stage: Any,
        prim_paths: Sequence[str],
        *,
        ordinal: int | None = None,
        commit: bool = True,
    ) -> None:
        if not supports_native_stage_writes(stage):
            raise RuntimeError("Kit OVStage copy-in write API is unavailable")
        paths = tuple(str(path) for path in prim_paths if str(path))
        if not paths:
            raise ValueError("at least one OVStage prim path is required")
        self.stage = stage
        self.prim_paths = paths
        self._requested_ordinal = None if ordinal is None else int(ordinal)
        self._commit = bool(commit)
        self.ordinal: int | None = None
        self._module: Any = None
        self._paths: Any = None
        self._path_list: Any = None
        self._query: Any = None

    def __enter__(self) -> "StageWriteBatch":
        try:
            self._module = import_module("ovstage")
            path_dictionary_type = getattr(self._module, "PathDictionary")
            self._paths = path_dictionary_type(self.stage)
            self._path_list = self._paths.create_path_list_from_strings(self.prim_paths)
            self._query = self.stage.query_from_path_list(self._path_list)
            self.ordinal = (
                int(self.stage.begin_frame())
                if self._requested_ordinal is None
                else self._requested_ordinal
            )
        except BaseException:
            self._release_resources(commit=False)
            raise
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        cleanup_error = self._release_resources(
            commit=self._commit and self.ordinal is not None
        )
        if exc is None and cleanup_error is not None:
            raise cleanup_error

    def _release_resources(self, *, commit: bool) -> BaseException | None:
        cleanup_error: BaseException | None = None
        try:
            if self._query is not None:
                release = getattr(self._query, "release", None)
                if callable(release):
                    wait_operation(release())
                else:
                    wait_operation(self.stage.release_query(self._query))
        except BaseException as release_error:  # preserve a write error first
            cleanup_error = release_error
        try:
            if self._paths is not None and self._path_list is not None:
                self._paths.destroy_path_list(self._path_list)
        except BaseException as path_error:
            cleanup_error = cleanup_error or path_error
        try:
            destroy = getattr(self._paths, "destroy", None)
            if callable(destroy):
                destroy()
        except BaseException as destroy_error:
            cleanup_error = cleanup_error or destroy_error
        try:
            if commit and self.ordinal is not None:
                self.stage.end_frame(self.ordinal)
        except BaseException as frame_error:
            cleanup_error = cleanup_error or frame_error
        self._query = None
        self._path_list = None
        self._paths = None
        return cleanup_error

    def write_fixed(
        self,
        attribute_name: str,
        values: Any,
        *,
        lanes: int = 1,
        semantic: Any = 0,
    ) -> None:
        """Write one fixed-width value per queried prim."""

        if self.ordinal is None or self._query is None:
            raise RuntimeError("StageWriteBatch must be entered before writing")
        lane_count = int(lanes)
        if lane_count <= 0:
            raise ValueError("DLPack lane count must be positive")
        array = np.ascontiguousarray(np.asarray(values)).reshape(-1)
        expected = len(self.prim_paths) * lane_count
        if int(array.size) != expected:
            raise ValueError(
                f"{attribute_name!r} requires {expected} scalar component(s) "
                f"for {len(self.prim_paths)} prim(s), got {int(array.size)}"
            )
        dtype = self._module.numpy_to_dldatatype(array.dtype, lanes=lane_count)
        tensor = self._module.make_dltensor(
            array,
            dtype=dtype,
            shape=[len(self.prim_paths)],
            ndim=1,
        )
        operation = self.stage.write_attribute(
            self._query,
            str(attribute_name),
            int(self.ordinal),
            tensor,
            is_array=False,
            semantic=int(semantic),
        )
        wait_operation(operation)
        _record_stage_write(
            self.stage,
            ordinal=int(self.ordinal),
            attribute_name=str(attribute_name),
            prim_paths=self.prim_paths,
        )

    def write_tokens(self, attribute_name: str, values: Iterable[str]) -> None:
        """Write one interned token value per queried prim."""

        token_values = tuple(str(value) for value in values)
        if len(token_values) != len(self.prim_paths):
            raise ValueError("token value count must match prim path count")
        ids = np.asarray(
            [self._paths.intern_token(value) for value in token_values],
            dtype=np.uint64,
        )
        semantic = getattr(self._module.AttributeSemantic, "TOKEN_ID")
        self.write_fixed(attribute_name, ids, semantic=semantic)

    def delete_prims(self) -> None:
        """Delete every queried prim at this batch's ordinal."""

        if self.ordinal is None or self._query is None:
            raise RuntimeError("StageWriteBatch must be entered before deleting")
        delete = getattr(self.stage, "delete_attributes", None)
        if not callable(delete):
            raise RuntimeError("Kit OVStage delete_attributes API is unavailable")
        wait_operation(delete(self._query, [], int(self.ordinal)))


def write_fixed_attribute(
    stage: Any,
    prim_paths: Sequence[str],
    attribute_name: str,
    values: Any,
    *,
    lanes: int = 1,
    semantic: Any = 0,
) -> int:
    """Write one fixed-width attribute and return the committed ordinal."""

    with StageWriteBatch(stage, prim_paths) as batch:
        batch.write_fixed(attribute_name, values, lanes=lanes, semantic=semantic)
        assert batch.ordinal is not None
        return int(batch.ordinal)


def write_matrix_attribute(
    stage: Any,
    prim_paths: Sequence[str],
    attribute_name: str,
    matrices: Any,
) -> int:
    """Write float64 matrix4d values with the OVStage MATRIX semantic."""

    ovstage = import_module("ovstage")
    semantic = getattr(ovstage.AttributeSemantic, "MATRIX")
    values = np.ascontiguousarray(np.asarray(matrices, dtype=np.float64)).reshape(-1)
    return write_fixed_attribute(
        stage,
        prim_paths,
        attribute_name,
        values,
        lanes=16,
        semantic=semantic,
    )


def write_token_attribute(
    stage: Any,
    prim_paths: Sequence[str],
    attribute_name: str,
    values: Sequence[str],
) -> int:
    """Write one token value per prim and return the committed ordinal."""

    with StageWriteBatch(stage, prim_paths) as batch:
        batch.write_tokens(attribute_name, values)
        assert batch.ordinal is not None
        return int(batch.ordinal)

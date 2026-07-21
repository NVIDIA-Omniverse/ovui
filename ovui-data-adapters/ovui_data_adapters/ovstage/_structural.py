# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION is strictly
# prohibited.

"""Owned snapshots and exact public OVStage structural mutation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np

from ovui_data_adapters.common import Command
from ovui_data_adapters.ovstage._native import read_token_attribute
from ovui_data_adapters.ovstage._stage_write import wait_operation
from ovui_data_adapters.ovstage.runtime_import import import_ovstage_runtime_module


_TYPE_ATTRIBUTE = "usd-prim-type"
_SCHEMA_ATTRIBUTE = "usd-schemas"
_LOCAL_MATRIX_ATTRIBUTE = "omni:xform"
_STRUCTURAL_ATTRIBUTE_NAMES = (
    _TYPE_ATTRIBUTE,
    _SCHEMA_ATTRIBUTE,
    "material:binding",
    "camera",
    "orderedVars",
)
_NON_TRANSFORMABLE_TYPES = frozenset(
    {
        "Material",
        "RenderProduct",
        "RenderSettings",
        "RenderVar",
        "Scope",
    }
)


@dataclass(frozen=True)
class NativeTensorSnapshot:
    """One Python-owned tensor copied from a live native read group."""

    values: np.ndarray
    code: int
    bits: int
    lanes: int
    shape: tuple[int, ...]

    def make_tensor(self, ovstage: Any) -> Any:
        values = np.ascontiguousarray(self.values).copy()
        dtype = ovstage.DLDataType(
            code=int(self.code),
            bits=int(self.bits),
            lanes=int(self.lanes),
        )
        return ovstage.make_dltensor(
            values,
            dtype=dtype,
            shape=list(self.shape),
            ndim=len(self.shape),
        )


@dataclass(frozen=True)
class NativeAttributeSnapshot:
    """One exact native attribute payload and its public descriptor."""

    name: str
    tensors: tuple[NativeTensorSnapshot, ...]
    is_array: bool
    semantic: int


@dataclass(frozen=True)
class NativePrimSnapshot:
    """All exact public native columns available for one prim."""

    path: str
    type_name: str
    attributes: tuple[NativeAttributeSnapshot, ...]


@dataclass(frozen=True)
class NativeSubtreeSnapshot:
    """Immutable inverse for one or more current-stage native subtrees."""

    stage_identity: int
    roots: tuple[str, ...]
    prims: tuple[NativePrimSnapshot, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(prim.path for prim in self.prims)


class _NativeStructuralCommand(Command):
    """One scene-bound structural history edge and semantic RESYNC."""

    def __init__(self, scene: Any, *, event_paths: Iterable[str], source: str) -> None:
        self._scene = scene
        self._stage = getattr(scene, "_stage", None)
        self._event_paths = tuple(dict.fromkeys(str(path) for path in event_paths))
        self._source = str(source)

    def _apply(self, operation: Any) -> None:
        if (
            self._stage is None
            or getattr(self._scene, "_stage", None) is not self._stage
            or not getattr(self._scene, "is_open", False)
        ):
            raise RuntimeError(
                "structural history belongs to a closed or replaced OVStage scene"
            )
        if getattr(self._scene, "_ovui_structural_edit_active", False):
            raise RuntimeError("reentrant OVStage structural edits are not allowed")
        self._scene._ovui_structural_edit_active = True
        stream = self._scene.change_stream
        try:
            with stream.suppress_notifications():
                operation()
            # Committed-edge publication: contain interrupt-class observer
            # failures so the pending history edge is still recorded.
            with stream.committed_edge_publication():
                stream.publish_resync_change(
                    self._event_paths,
                    source=self._source,
                )
        finally:
            self._scene._ovui_structural_edit_active = False


class NativeCreatePrimsCommand(_NativeStructuralCommand):
    """Create exact native prim rows and delete them as one undo edge."""

    def __init__(self, scene: Any, prims: Sequence[tuple[str, str]]) -> None:
        self._prims = tuple((str(path), str(type_name)) for path, type_name in prims)
        self._delete_roots = _outermost(path for path, _type_name in self._prims)
        super().__init__(
            scene,
            event_paths=(path for path, _type_name in self._prims),
            source="structural:create",
        )

    def do(self) -> None:
        def create_and_verify() -> None:
            self._scene.prepare_native_topology((), self._prims)
            stage = getattr(self._scene, "_stage", None)
            mismatches = []
            for path, expected in self._prims:
                actual = read_token_attribute(stage, path, _TYPE_ATTRIBUTE)
                if actual != expected:
                    mismatches.append((path, expected, actual))
            if not mismatches:
                return
            self._scene.delete_native_subtrees(self._delete_roots)
            details = ", ".join(
                f"{path}: expected {expected!r}, got {actual!r}"
                for path, expected, actual in mismatches
            )
            raise RuntimeError(f"native type verification failed: {details}")

        self._apply(create_and_verify)

    def undo(self) -> None:
        self._apply(lambda: self._scene.delete_native_subtrees(self._delete_roots))


class NativeDeletePrimsCommand(_NativeStructuralCommand):
    """Delete and restore complete exact-native subtree snapshots."""

    def __init__(self, scene: Any, roots: Iterable[str]) -> None:
        self._roots = _outermost(roots)
        self._snapshot: NativeSubtreeSnapshot | None = None
        super().__init__(
            scene,
            event_paths=self._roots,
            source="structural:delete",
        )

    def do(self) -> None:
        def delete() -> None:
            if self._snapshot is None:
                self._snapshot = self._scene.capture_native_subtrees(self._roots)
            self._scene.delete_native_subtrees(
                self._roots,
                snapshot=self._snapshot,
            )

        self._apply(delete)

    def undo(self) -> None:
        if self._snapshot is None:
            raise RuntimeError("native delete command has no inverse snapshot")
        self._apply(lambda: self._scene.restore_native_subtrees(self._snapshot))


class NativeMovePrimsCommand(_NativeStructuralCommand):
    """Clone/delete namespace edits whose inverse swaps source and target."""

    def __init__(
        self,
        scene: Any,
        edits: Sequence[tuple[str, str]],
        source_subtrees: dict[str, tuple[str, ...]],
    ) -> None:
        self._edits = tuple((str(old), str(new)) for old, new in edits)
        self._source_subtrees = {
            str(root): tuple(str(path) for path in paths)
            for root, paths in source_subtrees.items()
        }
        self._inverse_edits = tuple((new, old) for old, new in self._edits)
        self._inverse_subtrees = {
            new: tuple(new + path[len(old):] for path in self._source_subtrees[old])
            for old, new in self._edits
        }
        super().__init__(
            scene,
            event_paths=(path for edit in self._edits for path in edit),
            source="structural:namespace",
        )

    def do(self) -> None:
        self._apply(
            lambda: self._scene.move_native_paths(
                self._edits,
                self._source_subtrees,
            )
        )

    def undo(self) -> None:
        self._apply(
            lambda: self._scene.move_native_paths(
                self._inverse_edits,
                self._inverse_subtrees,
            )
        )


def collect_subtree_paths(stage: Any, roots: Iterable[str]) -> tuple[str, ...]:
    """Copy all native paths below canonical *roots* in parent-first order."""

    result: list[str] = []
    seen: set[str] = set()

    def visit(path: str) -> None:
        if path in seen:
            return
        seen.add(path)
        result.append(path)
        try:
            children = tuple(str(value) for value in stage.get_child_paths(path))
        except KeyError:
            children = ()
        for child in sorted(children):
            visit(child)

    for root in roots:
        visit(str(root))
    return tuple(result)


def capture_native_subtrees(
    stage: Any,
    roots: Iterable[str],
    *,
    ordinal: int,
) -> NativeSubtreeSnapshot:
    """Copy every public OVStage column for the requested native subtrees."""

    normalized_roots = tuple(dict.fromkeys(str(root) for root in roots))
    paths = collect_subtree_paths(stage, normalized_roots)
    wanted_paths = set(paths)
    prim_attributes: dict[str, dict[str, NativeAttributeSnapshot]] = {
        path: {} for path in paths
    }
    prim_types: dict[str, str] = {}
    ovstage = import_ovstage_runtime_module("ovstage")
    ordinal_range = ovstage.OrdinalRange.latest(int(ordinal))

    with ovstage.PathDictionary(stage) as dictionary:
        attribute_names = _discover_attribute_names(stage, dictionary)
        for name in _STRUCTURAL_ATTRIBUTE_NAMES:
            if name not in attribute_names:
                attribute_names.append(name)
        for attribute_name in attribute_names:
            token = dictionary.intern_token(attribute_name)
            with stage.query(None, [token]) as query:
                query.wait()
                with stage.read_attributes(query, [token], ordinal_range) as read:
                    read.wait()
                    while True:
                        group = stage.fetch_read_next(read)
                        if group is None:
                            break
                        try:
                            _copy_group_attributes(
                                stage,
                                dictionary,
                                group,
                                attribute_name,
                                wanted_paths,
                                prim_attributes,
                            )
                        finally:
                            stage.release_group(group)
        for path in paths:
            attribute = prim_attributes[path].get(_TYPE_ATTRIBUTE)
            if attribute is None or not attribute.tensors:
                continue
            values = attribute.tensors[0].values.reshape(-1)
            if values.size:
                prim_types[path] = str(
                    dictionary.token_to_string(int(values[0]))
                )

    prims = tuple(
        NativePrimSnapshot(
            path=path,
            type_name=prim_types.get(path, ""),
            attributes=tuple(
                prim_attributes[path][name]
                for name in sorted(prim_attributes[path])
            ),
        )
        for path in paths
    )
    return NativeSubtreeSnapshot(
        stage_identity=id(stage),
        roots=normalized_roots,
        prims=prims,
    )


def create_native_prims(
    stage: Any,
    prims: Sequence[tuple[str, str]],
    *,
    ordinal: int,
) -> None:
    """Insert exact native prim types and their structural identity matrices."""

    rows = tuple((str(path), str(type_name)) for path, type_name in prims)
    if not rows:
        return
    ovstage = import_ovstage_runtime_module("ovstage")
    paths = tuple(path for path, _type_name in rows)
    with ovstage.PathDictionary(stage) as dictionary:
        type_ids = np.asarray(
            [dictionary.intern_token(type_name) for _path, type_name in rows],
            dtype=np.uint64,
        )
        type_tensor = ovstage.make_dltensor(type_ids)
        _write_attributes_for_paths(
            stage,
            dictionary,
            paths,
            (
                ovstage.WriteDesc(
                    _TYPE_ATTRIBUTE,
                    type_tensor,
                    is_array=False,
                    semantic=ovstage.AttributeSemantic.NONE,
                ),
            ),
            ordinal=int(ordinal),
            prim_mode=ovstage.PrimMode.INSERT,
        )

        transform_paths = tuple(
            path
            for path, type_name in rows
            if type_name not in _NON_TRANSFORMABLE_TYPES
        )
        if transform_paths:
            values = np.tile(
                np.eye(4, dtype=np.float64).reshape(-1),
                len(transform_paths),
            )
            dtype = ovstage.numpy_to_dldatatype(values.dtype, lanes=16)
            matrix_tensor = ovstage.make_dltensor(
                values,
                dtype=dtype,
                shape=[len(transform_paths)],
                ndim=1,
            )
            _write_attributes_for_paths(
                stage,
                dictionary,
                transform_paths,
                (
                    ovstage.WriteDesc(
                        _LOCAL_MATRIX_ATTRIBUTE,
                        matrix_tensor,
                        is_array=False,
                        semantic=ovstage.AttributeSemantic.MATRIX,
                    ),
                ),
                ordinal=int(ordinal),
                prim_mode=ovstage.PrimMode.UPSERT,
            )


def restore_native_snapshot(
    stage: Any,
    snapshot: NativeSubtreeSnapshot,
    *,
    ordinal: int,
) -> None:
    """Restore one captured subtree snapshot at a caller-owned ordinal."""

    if snapshot.stage_identity != id(stage):
        raise RuntimeError("native structural snapshot belongs to another OVStage")
    ovstage = import_ovstage_runtime_module("ovstage")
    with ovstage.PathDictionary(stage) as dictionary:
        for prim in snapshot.prims:
            writes = tuple(
                ovstage.WriteDesc(
                    attribute.name,
                    tuple(tensor.make_tensor(ovstage) for tensor in attribute.tensors),
                    is_array=attribute.is_array,
                    semantic=attribute.semantic,
                )
                for attribute in prim.attributes
                if attribute.tensors
            )
            if not writes:
                raise RuntimeError(
                    f"native inverse snapshot has no restorable attributes for {prim.path!r}"
                )
            _write_attributes_for_paths(
                stage,
                dictionary,
                (prim.path,),
                writes,
                ordinal=int(ordinal),
                prim_mode=ovstage.PrimMode.INSERT,
            )


def delete_native_paths(
    stage: Any,
    paths: Iterable[str],
    *,
    ordinal: int,
) -> None:
    """Delete exact native prim rows at one caller-owned frame ordinal."""

    values = tuple(dict.fromkeys(str(path) for path in paths))
    if not values:
        return
    ovstage = import_ovstage_runtime_module("ovstage")
    with ovstage.PathDictionary(stage) as dictionary:
        path_list = dictionary.create_path_list_from_strings(values)
        query = None
        try:
            query = stage.query_from_path_list(path_list)
            wait_operation(stage.delete_attributes(query, [], int(ordinal)))
        finally:
            _release_query(stage, query)
            dictionary.destroy_path_list(path_list)


def _discover_attribute_names(stage: Any, dictionary: Any) -> list[str]:
    with stage.query(None, None) as query:
        query.wait()
        return list(
            dict.fromkeys(
                str(dictionary.token_to_string(int(token)))
                for token in query.result().attributes
            )
        )


def _copy_group_attributes(
    stage: Any,
    dictionary: Any,
    group: Any,
    attribute_name: str,
    wanted_paths: set[str],
    prim_attributes: dict[str, dict[str, NativeAttributeSnapshot]],
) -> None:
    try:
        group_paths = tuple(
            str(path) for path in dictionary.get_path_strings(group.prim_list)
        )
        prim_count = int(group.prim_count)
        data_count = int(group.data_count)
        tensor_count = int(group.tensor_count)
        is_array = bool(group.is_array)
        semantic = int(group.raw.semantic)
    except Exception as exc:
        raise RuntimeError(
            f"failed to copy native descriptor for {attribute_name!r}"
        ) from exc
    if prim_count <= 0 or data_count <= 0 or tensor_count <= 0:
        return

    for local_index in range(prim_count):
        try:
            prim_index = int(group.prim_index(local_index))
            data_index = int(group.data_row_index(local_index))
            path = group_paths[prim_index]
        except Exception as exc:
            raise RuntimeError(
                f"failed to map native row for {attribute_name!r}"
            ) from exc
        if path not in wanted_paths:
            continue
        tensors = (
            (_copy_whole_tensor(group, data_index),)
            if is_array
            else tuple(
                _copy_fixed_tensor_row(group, tensor_index, data_index, data_count)
                for tensor_index in range(tensor_count)
            )
        )
        prim_attributes[path][attribute_name] = NativeAttributeSnapshot(
            name=attribute_name,
            tensors=tensors,
            is_array=is_array,
            semantic=semantic,
        )


def _copy_whole_tensor(group: Any, tensor_index: int) -> NativeTensorSnapshot:
    if tensor_index < 0 or tensor_index >= int(group.tensor_count):
        raise RuntimeError("native array tensor index is out of range")
    tensor = group.tensor(tensor_index)
    values = np.ascontiguousarray(group.array(tensor_index)).copy()
    values.setflags(write=False)
    return NativeTensorSnapshot(
        values=values,
        code=int(tensor.dtype.code),
        bits=int(tensor.dtype.bits),
        lanes=int(tensor.dtype.lanes),
        shape=tuple(int(value) for value in tensor.shape_tuple),
    )


def _copy_fixed_tensor_row(
    group: Any,
    tensor_index: int,
    data_index: int,
    data_count: int,
) -> NativeTensorSnapshot:
    tensor = group.tensor(tensor_index)
    array = np.ascontiguousarray(group.array(tensor_index))
    flat = array.reshape(-1)
    if data_count <= 0 or flat.size % data_count:
        raise RuntimeError("native fixed-width tensor has inconsistent row count")
    width = int(flat.size) // int(data_count)
    start = int(data_index) * width
    values = np.ascontiguousarray(flat[start:start + width]).copy()
    values.setflags(write=False)
    lanes = int(tensor.dtype.lanes)
    if lanes <= 0 or width % lanes:
        raise RuntimeError("native fixed-width tensor has inconsistent lanes")
    logical_width = max(1, width // lanes)
    return NativeTensorSnapshot(
        values=values,
        code=int(tensor.dtype.code),
        bits=int(tensor.dtype.bits),
        lanes=lanes,
        shape=(logical_width,),
    )


def _write_attributes_for_paths(
    stage: Any,
    dictionary: Any,
    paths: Sequence[str],
    writes: Sequence[Any],
    *,
    ordinal: int,
    prim_mode: Any,
) -> None:
    path_list = dictionary.create_path_list_from_strings(tuple(paths))
    query = None
    try:
        query = stage.query_from_path_list(path_list)
        operation = stage.write_attributes(
            query,
            tuple(writes),
            int(ordinal),
            prim_mode=prim_mode,
        )
        wait_operation(operation)
    finally:
        _release_query(stage, query)
        dictionary.destroy_path_list(path_list)


def _release_query(stage: Any, query: Any | None) -> None:
    if query is None:
        return
    release = getattr(query, "release", None)
    wait_operation(release() if callable(release) else stage.release_query(query))


def _outermost(paths: Iterable[str]) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(str(path).rstrip("/") for path in paths))
    return tuple(
        path
        for path in values
        if not any(
            path.startswith(other + "/")
            for other in values
            if other != path
        )
    )


__all__ = [
    "NativeAttributeSnapshot",
    "NativeCreatePrimsCommand",
    "NativeDeletePrimsCommand",
    "NativeMovePrimsCommand",
    "NativePrimSnapshot",
    "NativeSubtreeSnapshot",
    "NativeTensorSnapshot",
    "capture_native_subtrees",
    "collect_subtree_paths",
    "create_native_prims",
    "delete_native_paths",
    "restore_native_snapshot",
]

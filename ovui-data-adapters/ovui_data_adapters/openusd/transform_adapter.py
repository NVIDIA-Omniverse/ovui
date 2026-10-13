# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""USD-backed TransformAdapter using UsdGeom.Xformable.

All matrices are plain Python list-of-lists (no pxr types cross the boundary).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

try:
    from pxr import Gf, Sdf, Usd, UsdGeom
    HAS_USD = True
except ImportError:
    HAS_USD = False
    Usd = UsdGeom = Gf = Sdf = None  # type: ignore[assignment]

from ovui_data_adapters.common import TransformAdapter

_IDENTITY: List[List[float]] = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


@dataclass(frozen=True)
class _UsdTransformState:
    layer: Any
    prim_path: Any
    snapshot: Any


class UsdTransformAdapter(TransformAdapter):
    """TransformAdapter backed by a Usd.Stage."""

    def __init__(self, stage: Any) -> None:
        self._stage = stage

    def get_local_transform(self, path: str) -> List[List[float]]:
        prim = self._stage.GetPrimAtPath(path)
        xformable = UsdGeom.Xformable(prim)
        if not xformable:
            return [row[:] for row in _IDENTITY]
        mat = xformable.GetLocalTransformation()
        return [list(row) for row in mat]

    def get_world_transform(self, path: str) -> List[List[float]]:
        prim = self._stage.GetPrimAtPath(path)
        xformable = UsdGeom.Xformable(prim)
        if not xformable:
            return [row[:] for row in _IDENTITY]
        time = Usd.TimeCode.Default()
        mat = xformable.ComputeLocalToWorldTransform(time)
        return [list(row) for row in mat]

    def set_local_transform(self, path: str, matrix: List[List[float]]) -> None:
        prim = self._stage.GetPrimAtPath(path)
        xformable = UsdGeom.Xformable(prim)
        if not xformable:
            return
        ops = xformable.GetOrderedXformOps()
        if (
            len(ops) == 1
            and ops[0].GetOpType() == UsdGeom.XformOp.TypeTranslate
            and _is_pure_translate_matrix(matrix)
        ):
            ops[0].Set(Gf.Vec3d(
                float(matrix[3][0]),
                float(matrix[3][1]),
                float(matrix[3][2]),
            ))
            return
        gf_mat = Gf.Matrix4d(*[v for row in matrix for v in row])
        # MakeMatrixXform clears existing ops and creates a single Matrix4d xformOp,
        # avoiding type mismatches with pre-existing translate/rotate ops.
        xformable.MakeMatrixXform().Set(gf_mat)

    def capture_local_transform_state(self, path: str) -> Any:
        edit_target = self._stage.GetEditTarget()
        layer = edit_target.GetLayer()
        prim_path = edit_target.MapToSpecPath(Sdf.Path(path))
        snapshot = Sdf.Layer.CreateAnonymous("transform-state")
        Sdf.CreatePrimInLayer(snapshot, prim_path)
        prim_spec = layer.GetPrimAtPath(prim_path)
        if prim_spec is not None:
            for prop in prim_spec.properties:
                if _is_xform_property(prop.name):
                    Sdf.CopySpec(layer, prop.path, snapshot, prop.path)
        return _UsdTransformState(layer, prim_path, snapshot)

    def restore_local_transform_state(self, path: str, state: Any) -> bool:
        if not isinstance(state, _UsdTransformState):
            return False
        with Sdf.ChangeBlock():
            prim_spec = state.layer.GetPrimAtPath(state.prim_path)
            if prim_spec is not None:
                edits = Sdf.BatchNamespaceEdit()
                for prop in list(prim_spec.properties):
                    if _is_xform_property(prop.name):
                        edits.Add(prop.path, Sdf.Path.emptyPath)
                if edits and not state.layer.Apply(edits):
                    raise RuntimeError("could not clear authored transform state")
            snapshot_spec = state.snapshot.GetPrimAtPath(state.prim_path)
            if snapshot_spec is not None:
                for prop in snapshot_spec.properties:
                    if not Sdf.CopySpec(
                        state.snapshot, prop.path, state.layer, prop.path
                    ):
                        raise RuntimeError("could not restore authored transform state")
        return True

    def can_transform(self, path: str) -> bool:
        prim = self._stage.GetPrimAtPath(path)
        return prim.IsValid() and not prim.IsInstanceProxy()


def _is_pure_translate_matrix(
    matrix: List[List[float]],
    *,
    tolerance: float = 1.0e-9,
) -> bool:
    if len(matrix) != 4 or any(len(row) != 4 for row in matrix):
        return False
    expected = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
    )
    for row_index, row in enumerate(expected):
        for column_index, expected_value in enumerate(row):
            if abs(float(matrix[row_index][column_index]) - expected_value) > tolerance:
                return False
    return abs(float(matrix[3][3]) - 1.0) <= tolerance


def _is_xform_property(name: str) -> bool:
    return name == "xformOpOrder" or name.startswith("xformOp:")

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""USD-backed TransformAdapter using UsdGeom.Xformable.

All matrices are plain Python list-of-lists (no pxr types cross the boundary).
"""

from __future__ import annotations

from typing import Any, List

try:
    from pxr import Gf, Usd, UsdGeom
    HAS_USD = True
except ImportError:
    HAS_USD = False
    Usd = UsdGeom = Gf = None  # type: ignore[assignment]

from ovui_data_adapters.common import TransformAdapter

_IDENTITY: List[List[float]] = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


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

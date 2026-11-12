# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The Translate, Rotate and Scale parts of a transform matrix.

A flat object (a zero scale) and a matrix with nan are cases that a user can
open: their parts must be true or marked as unknown, never an error.

The parts and the angles are checked against the matrices that OpenUSD makes
from real transform operations, so a wrong axis order or sign fails here.
The edit of one part through ``UsdPropertyAdapter.set_matrix_part_value``
keeps the other parts of each selected prim, gives one undo step, and does
not jump when a drag of Rotate Y passes 90 degrees.
"""

from __future__ import annotations

import itertools
import math

import pytest
from pxr import Gf, Usd, UsdGeom

from ovui_data_adapters.common.matrix_transform import (
    MatrixPartError,
    compose_matrix,
    decompose_matrix,
    euler_from_rotation,
    with_matrix_part,
)
from ovui_data_adapters.openusd.property_adapter import UsdPropertyAdapter
from ovui_data_adapters.services.undo import UndoManager

_ORDERS = ("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX")
_ANGLES = (
    (10.0, 20.0, 30.0),
    (-170.0, 85.0, 120.0),
    (45.0, -60.0, -135.0),
    (0.0, 100.0, 0.0),
    (30.0, 90.0, 10.0),
)


def _ops_matrix(translate, rotate, scale, order="XYZ"):
    """The local matrix that OpenUSD makes from translate, rotate and scale ops."""
    stage = Usd.Stage.CreateInMemory()
    xform = UsdGeom.Xform.Define(stage, "/X")
    xform.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(*translate))
    getattr(xform, f"AddRotate{order}Op")(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(*rotate))
    xform.AddScaleOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(*scale))
    matrix = xform.GetLocalTransformation()
    return tuple(matrix[r][c] for r in range(4) for c in range(4))


def _rotation(flat):
    return [flat[0:3], flat[4:7], flat[8:11]]


def _close(a, b, tolerance=1.0e-9):
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


def test_parts_of_a_matrix_are_the_values_of_its_operations():
    translate, rotate, scale = (-2.0, 0.75, 3.0), (10.0, 30.0, -40.0), (1.0, 1.5, 2.0)
    parts = decompose_matrix(_ops_matrix(translate, rotate, scale))
    assert parts.translate == pytest.approx(translate)
    assert parts.rotate == pytest.approx(rotate)
    assert parts.scale == pytest.approx(scale)
    assert parts.shear == pytest.approx((0.0, 0.0, 0.0), abs=1.0e-12)


@pytest.mark.parametrize("order, angles", list(itertools.product(_ORDERS, _ANGLES)))
def test_angles_of_each_rotation_order_give_the_matrix_of_openusd(order, angles):
    matrix = _ops_matrix((0.0, 0.0, 0.0), angles, (1.0, 1.0, 1.0), order)
    found = euler_from_rotation(_rotation(matrix), order)
    assert _close(_ops_matrix((0.0, 0.0, 0.0), found, (1.0, 1.0, 1.0), order), matrix)
    # With the old angles as the hint, the same angles come back: a turn
    # past 90 degrees keeps its form (Y 100, not X 180, Y 80, Z 180).
    assert euler_from_rotation(_rotation(matrix), order, hint=angles) == pytest.approx(angles)


def test_rotate_or_scale_edit_keeps_the_shear_the_translation_and_the_last_column():
    shear = Gf.Matrix4d(1.0)
    shear.SetRow(1, Gf.Vec4d(0.3, 1.0, 0.0, 0.0))
    shear.SetRow(2, Gf.Vec4d(0.2, 0.4, 1.0, 0.0))
    turn = Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1.0, 2.0, 3.0).GetNormalized(), 40.0))
    matrix = shear * Gf.Matrix4d().SetScale(Gf.Vec3d(2.0, 3.0, 4.0)) * turn
    matrix.SetTranslateOnly(Gf.Vec3d(1.0, 2.0, 3.0))
    flat = tuple(matrix[r][c] for r in range(4) for c in range(4))
    before = decompose_matrix(flat)

    turned = with_matrix_part(flat, "rotate", 0, before.rotate[0] + 10.0)
    stretched = with_matrix_part(turned, "scale", 2, 5.0)

    after = decompose_matrix(stretched)
    assert after.shear == pytest.approx(before.shear)
    assert after.scale == pytest.approx((2.0, 3.0, 5.0))
    assert after.rotate == pytest.approx((before.rotate[0] + 10.0, *before.rotate[1:]))
    assert stretched[12:16] == flat[12:16]
    assert (stretched[3], stretched[7], stretched[11]) == (0.0, 0.0, 0.0)


def test_a_mirror_shows_a_negative_scale_and_no_turn():
    parts = decompose_matrix(_ops_matrix((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (-1.0, 1.0, 1.0)))
    assert parts.scale == pytest.approx((-1.0, 1.0, 1.0))
    assert parts.rotate == pytest.approx((0.0, 0.0, 0.0))


def _two_matrix_prims():
    stage = Usd.Stage.CreateInMemory()
    matrices = {
        "/A": _ops_matrix((1.0, 2.0, 3.0), (0.0, 30.0, 0.0), (1.0, 1.5, 1.0)),
        "/B": _ops_matrix((-4.0, 0.0, 5.0), (20.0, 0.0, 0.0), (2.0, 2.0, 2.0)),
    }
    for path, flat in matrices.items():
        UsdGeom.Xform.Define(stage, path).AddTransformOp().Set(Gf.Matrix4d(*flat))
    undo = UndoManager()
    adapter = UsdPropertyAdapter(stage, list(matrices), undo_manager=undo)
    return stage, undo, adapter, matrices


def _stored(stage, path):
    matrix = stage.GetPrimAtPath(path).GetAttribute("xformOp:transform").Get()
    return tuple(matrix[r][c] for r in range(4) for c in range(4))


def test_one_part_edit_keeps_the_other_parts_of_each_prim_and_is_one_undo_step():
    stage, undo, adapter, matrices = _two_matrix_prims()

    adapter.begin_edit("xformOp:transform")
    adapter.set_matrix_part_value("xformOp:transform", "rotate", 1, 60.0)
    adapter.end_edit("xformOp:transform")

    a = decompose_matrix(_stored(stage, "/A"))
    b = decompose_matrix(_stored(stage, "/B"))
    assert a.rotate == pytest.approx((0.0, 60.0, 0.0))
    assert a.translate == pytest.approx((1.0, 2.0, 3.0))
    assert a.scale == pytest.approx((1.0, 1.5, 1.0))
    assert b.rotate == pytest.approx((20.0, 60.0, 0.0))
    assert b.translate == pytest.approx((-4.0, 0.0, 5.0))
    assert b.scale == pytest.approx((2.0, 2.0, 2.0))

    undo.undo()
    assert _stored(stage, "/A") == pytest.approx(matrices["/A"])
    assert _stored(stage, "/B") == pytest.approx(matrices["/B"])


def test_a_drag_of_rotate_y_past_90_degrees_gives_the_last_value_without_a_jump():
    stage, undo, adapter, matrices = _two_matrix_prims()
    adapter.begin_edit("xformOp:transform")
    for value in (80.0, 89.0, 95.0, 100.0):
        adapter.set_matrix_part_value("xformOp:transform", "rotate", 1, value)
    adapter.end_edit("xformOp:transform")

    expected = _ops_matrix((1.0, 2.0, 3.0), (0.0, 100.0, 0.0), (1.0, 1.5, 1.0))
    assert _stored(stage, "/A") == pytest.approx(expected, abs=1.0e-9)
    undo.undo()
    assert _stored(stage, "/A") == pytest.approx(matrices["/A"])
    assert not undo.can_undo()


def _flat(rows, translate=(-2.0, 0.75, 0.0)):
    return (*rows[0], 0.0, *rows[1], 0.0, *rows[2], 0.0, *translate, 1.0)


# Matrices of flat or collapsed objects: a zero scale in one, two or three
# axes, two parallel axes, and a turned object with one axis.
_DEGENERATE = {
    "scale 1 0 0": (_flat([(1, 0, 0), (0, 0, 0), (0, 0, 0)]), (1.0, 0.0, 0.0)),
    "scale 0 0 0": (_flat([(0, 0, 0), (0, 0, 0), (0, 0, 0)]), (0.0, 0.0, 0.0)),
    "scale 0 1 0": (_flat([(0, 0, 0), (0, 1, 0), (0, 0, 0)]), (0.0, 1.0, 0.0)),
    "scale 0 1 1": (_flat([(0, 0, 0), (0, 1, 0), (0, 0, 1)]), (0.0, 1.0, 1.0)),
    "parallel axes": (_flat([(1, 0, 0), (2, 0, 0), (0, 0, 1)]), (1.0, 0.0, 1.0)),
    "turned flat": (_ops_matrix((-2.0, 0.75, 0.0), (0.0, 30.0, 0.0), (1.0, 0.0, 0.0)), (1.0, 0.0, 0.0)),
}


@pytest.mark.parametrize("name", sorted(_DEGENERATE))
def test_a_collapsed_matrix_gives_true_parts_and_can_be_edited(name):
    matrix, scale = _DEGENERATE[name]
    parts = decompose_matrix(matrix)
    assert parts.translate == pytest.approx((-2.0, 0.75, 0.0))
    assert parts.scale == pytest.approx(scale)
    # The parts give the same matrix again: they are true.
    assert compose_matrix(parts) == pytest.approx(matrix, abs=1.0e-12)

    stretched = with_matrix_part(matrix, "scale", 0, 2.0)
    assert decompose_matrix(stretched).scale == pytest.approx((2.0, *scale[1:]))
    assert stretched[12:16] == matrix[12:16]
    turned = with_matrix_part(stretched, "rotate", 1, 45.0)
    assert decompose_matrix(turned).rotate[1] == pytest.approx(45.0)


def test_rotate_and_scale_of_a_matrix_with_nan_are_unknown_and_their_edit_is_refused():
    matrix = list(_flat([(1, 0, 0), (0, float("nan"), 0), (0, 0, 1)]))
    parts = decompose_matrix(matrix)
    assert parts.translate == (-2.0, 0.75, 0.0)
    assert all(math.isnan(v) for v in parts.rotate + parts.scale)
    with pytest.raises(MatrixPartError, match="not a finite number"):
        with_matrix_part(matrix, "scale", 0, 2.0)
    # The translation row is known, so a Translate edit works.
    assert with_matrix_part(matrix, "translate", 0, 5.0)[12] == 5.0

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The Translate, Rotate and Scale parts of a 4x4 transform matrix.

A matrix is 16 numbers, row by row, in the OpenUSD convention: a point is a
row vector, rows 0 to 2 are the X, Y and Z axes of the object and row 3 is
the translation. The parts are those of the transform operations
``translate``, ``rotateXYZ`` and ``scale``: the upper 3x3 matrix is
``shear x scale x rotation``. The shear part is kept as it is when Rotate or
Scale changes, so an edit of one part loses no other value of the matrix.

A matrix keeps no angles. :func:`decompose_matrix` gives one set of XYZ
angles for the rotation: Y is from -90 to 90 degrees, X and Z are from -180
to 180 degrees.

A matrix with a zero scale (a flat object) has an axis of length 0. Its
direction is not in the matrix, so the direction that completes the rotation
is used: the parts still give the same matrix again. A matrix with a value
that is not a finite number (nan, inf) has no known rotate, scale and shear
parts: they are nan, and an edit of them raises :class:`MatrixPartError`.

The module has no OpenUSD dependency: the Property Inspector and each data
adapter use it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

Vec3 = Tuple[float, float, float]

MATRIX_TRANSFORM_PARTS = ("translate", "rotate", "scale")

_TRANSFORM_OP_NAME = "xformOp:transform"
_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}
# Below this length, an axis row of the matrix has no direction (scale 0).
_DEGENERATE_LENGTH = 1.0e-12
# Values closer to zero than this are shown as 0.0, not as 1e-17 or -0.0.
_DISPLAY_ZERO = 1.0e-12


class MatrixPartError(ValueError):
    """An edit of a part that the matrix cannot give; the text is the cause."""


@dataclass(frozen=True)
class MatrixTransformParts:
    """The parts of a transform matrix.

    ``rotate`` is in degrees, applied X first, then Y, then Z (the
    ``rotateXYZ`` operation). ``shear`` is ``(xy, xz, yz)``: the parts of the
    Y and Z axes along the scaled X axis, and of the Z axis along the scaled Y
    axis. It is ``(0, 0, 0)`` for a matrix made of translate, rotate and
    scale only.
    """

    translate: Vec3
    rotate: Vec3
    scale: Vec3
    shear: Vec3 = (0.0, 0.0, 0.0)


def is_transform_matrix_op(attr_name: str) -> bool:
    """True for the attribute of a matrix transform operation.

    That is ``xformOp:transform`` and ``xformOp:transform:<suffix>``.
    """
    return attr_name == _TRANSFORM_OP_NAME or attr_name.startswith(
        _TRANSFORM_OP_NAME + ":"
    )


def decompose_matrix(matrix: Sequence[float]) -> MatrixTransformParts:
    """The Translate, Rotate, Scale and shear parts of ``matrix`` (16 numbers).

    The rotate, scale and shear parts of a matrix whose axis rows have a
    value that is not a finite number are nan.
    """
    values = _flat16(matrix)
    rows = [values[0:3], values[4:7], values[8:11]]
    if not all(math.isfinite(v) for row in rows for v in row):
        unknown = (math.nan, math.nan, math.nan)
        return MatrixTransformParts(_clean(values[12:15]), unknown, unknown, unknown)
    scale, rotation, shear = split_axes(rows)
    rotate = euler_from_rotation(rotation, "XYZ")
    return MatrixTransformParts(
        translate=_clean(values[12:15]),
        rotate=_clean(rotate),
        scale=_clean(scale),
        shear=_clean(shear),
    )


def compose_matrix(
    parts: MatrixTransformParts,
    last_column: Sequence[float] = (0.0, 0.0, 0.0, 1.0),
) -> Tuple[float, ...]:
    """The matrix (16 numbers) of ``parts``.

    ``last_column`` is column 3 of the matrix; it is ``(0, 0, 0, 1)`` for a
    transform that has no projection.
    """
    rotation = rotation_from_euler(parts.rotate, "XYZ")
    sx, sy, sz = (float(v) for v in parts.scale)
    xy, xz, yz = (float(v) for v in parts.shear)
    # Rows of scale x rotation, then the shear adds the scaled rows above.
    scaled = [[sx * v for v in rotation[0]], [sy * v for v in rotation[1]], [sz * v for v in rotation[2]]]
    axes = [
        scaled[0],
        [scaled[1][i] + xy * scaled[0][i] for i in range(3)],
        [scaled[2][i] + xz * scaled[0][i] + yz * scaled[1][i] for i in range(3)],
    ]
    column = [float(v) for v in last_column]
    translate = [float(v) for v in parts.translate]
    return (
        *axes[0], column[0],
        *axes[1], column[1],
        *axes[2], column[2],
        *translate, column[3],
    )


def with_matrix_part(
    matrix: Sequence[float], part: str, index: int, value: float
) -> Tuple[float, ...]:
    """``matrix`` with channel ``index`` of ``part`` set to ``value``.

    ``part`` is ``"translate"``, ``"rotate"`` or ``"scale"``. A Translate
    edit changes only that number of row 3. A Rotate or Scale edit keeps the
    translation row, the last column, the shear and the other channels.
    Raises :class:`MatrixPartError` for a Rotate or Scale edit of a matrix
    whose axis rows have a value that is not a finite number.
    """
    if part not in MATRIX_TRANSFORM_PARTS:
        raise ValueError(f"unknown transform part {part!r}; expected one of {MATRIX_TRANSFORM_PARTS}")
    if index not in (0, 1, 2):
        raise ValueError(f"transform part channel must be 0, 1 or 2, not {index!r}")
    values = list(_flat16(matrix))
    if part == "translate":
        values[12 + index] = float(value)
        return tuple(values)
    if not all(math.isfinite(values[i]) for i in (0, 1, 2, 4, 5, 6, 8, 9, 10)):
        raise MatrixPartError(
            "The matrix has a value that is not a finite number, so its "
            "Rotate and Scale are not known."
        )
    parts = decompose_matrix(values)
    channels = list(getattr(parts, part))
    channels[index] = float(value)
    if part == "rotate":
        parts = MatrixTransformParts(parts.translate, tuple(channels), parts.scale, parts.shear)
    else:
        parts = MatrixTransformParts(parts.translate, parts.rotate, tuple(channels), parts.shear)
    new_values = list(compose_matrix(parts, (values[3], values[7], values[11], values[15])))
    # The translation row is not changed by this edit: keep its exact numbers.
    new_values[12:15] = values[12:15]
    return tuple(new_values)


def rotation_from_euler(angles: Sequence[float], order: str) -> list:
    """The 3x3 rotation (row vectors) of the operation ``rotate<order>``.

    ``angles`` are the X, Y and Z angles in degrees. ``order`` is the order
    in which the axes apply, for example ``"XYZ"``: X first.
    """
    result = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for letter in order:
        axis = _AXIS_INDEX[letter]
        result = _multiply(result, _axis_rotation(axis, float(angles[axis])))
    return result


def euler_from_rotation(
    rotation: Sequence[Sequence[float]],
    order: str,
    hint: Optional[Sequence[float]] = None,
) -> Vec3:
    """The X, Y and Z angles in degrees of ``rotation`` for ``rotate<order>``.

    ``rotation`` is a 3x3 rotation of row vectors. Without ``hint``, the
    angle of the middle axis is from -90 to 90 degrees. With ``hint`` (old
    angles), the result is the set of angles nearest to the hint, so a small
    turn gives a small change of each angle.
    """
    if len(order) != 3 or sorted(order) != ["X", "Y", "Z"]:
        raise ValueError(f"rotation order must be a permutation of 'XYZ', not {order!r}")
    first, middle, last = (_AXIS_INDEX[letter] for letter in order)
    # In column-vector form the rotation is C = C_last x C_middle x C_first.
    column = [[float(rotation[c][r]) for c in range(3)] for r in range(3)]
    parity = 1.0 if (first, middle, last) in ((0, 1, 2), (1, 2, 0), (2, 0, 1)) else -1.0
    sine = max(-1.0, min(1.0, -parity * column[last][first]))
    middle_angle = math.asin(sine)
    if math.cos(middle_angle) > 1.0e-9:
        first_angle = math.atan2(parity * column[last][middle], column[last][last])
        last_angle = math.atan2(parity * column[middle][first], column[first][first])
    else:
        # Gimbal lock: only the sum or the difference of the first and the
        # last angle is known. Keep the last angle of the hint (or 0).
        last_angle = math.radians(float(hint[last])) if hint is not None else 0.0
        first_angle = _first_angle_after(column, first, middle, last, middle_angle, last_angle)
    angles = [0.0, 0.0, 0.0]
    angles[first] = math.degrees(first_angle)
    angles[middle] = math.degrees(middle_angle)
    angles[last] = math.degrees(last_angle)
    if hint is None:
        return (angles[0], angles[1], angles[2])
    other = list(angles)
    other[first] += 180.0
    other[middle] = 180.0 - other[middle]
    other[last] += 180.0
    best = None
    for candidate in (angles, other):
        near = [_nearest_turn(candidate[i], float(hint[i])) for i in range(3)]
        distance = sum(abs(near[i] - float(hint[i])) for i in range(3))
        if best is None or distance < best[0] - 1.0e-9:
            best = (distance, near)
    return (best[1][0], best[1][1], best[1][2])


def _first_angle_after(column, first, middle, last, middle_angle, last_angle) -> float:
    """The first angle when the middle and the last angle are known."""
    known = _multiply(
        _column_rotation(last, last_angle), _column_rotation(middle, middle_angle)
    )
    # C_first = (C_last x C_middle)^T x C
    rest = _multiply([[known[c][r] for c in range(3)] for r in range(3)], column)
    a = (first + 1) % 3
    b = (first + 2) % 3
    return math.atan2(rest[b][a], rest[a][a])


def split_axes(rows: Sequence[Sequence[float]]):
    """Split the three axis rows of a matrix into scale, rotation and shear.

    Returns ``(scale, rotation, shear)``: ``rows == shear x diag(scale) x
    rotation``, the rotation (3 row vectors) has a determinant of +1, and
    ``shear`` is as in :class:`MatrixTransformParts`. A mirror gives one
    negative scale. A row of length 0 (scale 0) gets the direction that
    completes the rotation.
    """
    directions = [None, None, None]
    lengths = [0.0, 0.0, 0.0]
    dots = {}
    for i, row in enumerate(rows):
        rest = list(row)
        for j in range(i):
            if directions[j] is None:
                continue
            dots[(i, j)] = _dot(row, directions[j])
            rest = [rest[k] - dots[(i, j)] * directions[j][k] for k in range(3)]
        length = math.sqrt(_dot(rest, rest))
        lengths[i] = length
        if length > _DEGENERATE_LENGTH:
            directions[i] = [v / length for v in rest]
    _complete_directions(directions)
    if _dot(directions[0], _cross(directions[1], directions[2])) < 0.0:
        # A mirror: one scale is negative. Flip the axis that leaves the
        # rotation nearest to no rotation (a mirror in X gives scale -1 in X).
        flip = min(range(3), key=lambda i: directions[i][i])
        directions[flip] = [-v for v in directions[flip]]
        lengths[flip] = -lengths[flip]
    # Row i holds ``dot * direction j`` of axis j. A flip changes the sign of
    # both the scale and the direction of j, so their product is the same:
    # the shear is the dot over the length before the flip.
    shear = [0.0, 0.0, 0.0]
    for (i, j), dot in dots.items():
        shear[{(1, 0): 0, (2, 0): 1, (2, 1): 2}[(i, j)]] = dot / abs(lengths[j])
    return tuple(lengths), directions, tuple(shear)


def _complete_directions(directions) -> None:
    """Fill the missing rows of an orthonormal basis (right-handed)."""
    missing = [i for i in range(3) if directions[i] is None]
    if not missing:
        return
    if len(missing) == 1:
        i = missing[0]
        directions[i] = _cross(directions[(i + 1) % 3], directions[(i + 2) % 3])
        return
    known = [d for d in directions if d is not None]
    for i in missing[:-1]:
        # The axis of X, Y or Z that is farthest from the known directions.
        # With at most one known direction, two of the three axes are always
        # at least 1/sqrt(2) from it, so the best length is never 0.
        best_length, best_rest = 0.0, None
        for axis in ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]):
            rest = list(axis)
            for d in known:
                rest = [rest[k] - _dot(axis, d) * d[k] for k in range(3)]
            length = math.sqrt(_dot(rest, rest))
            if length > best_length:
                best_length, best_rest = length, rest
        directions[i] = [v / best_length for v in best_rest]
        known.append(directions[i])
    i = missing[-1]
    directions[i] = _cross(directions[(i + 1) % 3], directions[(i + 2) % 3])


def _axis_rotation(axis: int, degrees: float) -> list:
    """Rotation about one axis, for row vectors (``v x R``)."""
    radians = math.radians(degrees)
    column = _column_rotation(axis, radians)
    return [[column[c][r] for c in range(3)] for r in range(3)]


def _column_rotation(axis: int, radians: float) -> list:
    """Right-handed rotation about one axis, for column vectors (``R x v``)."""
    c, s = math.cos(radians), math.sin(radians)
    result = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    a = (axis + 1) % 3
    b = (axis + 2) % 3
    result[a][a] = c
    result[a][b] = -s
    result[b][a] = s
    result[b][b] = c
    return result


def _nearest_turn(angle: float, hint: float) -> float:
    return angle + 360.0 * round((hint - angle) / 360.0)


def _multiply(a, b) -> list:
    return [[sum(a[r][k] * b[k][c] for k in range(3)) for c in range(3)] for r in range(3)]


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b) -> list:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _clean(values) -> Vec3:
    return tuple(0.0 if abs(v) < _DISPLAY_ZERO else float(v) for v in values)


def _flat16(matrix: Sequence[float]) -> Tuple[float, ...]:
    values = tuple(float(v) for v in matrix)
    if len(values) != 16:
        raise ValueError(f"a transform matrix has 16 numbers, not {len(values)}")
    return values


__all__ = [
    "MATRIX_TRANSFORM_PARTS",
    "MatrixPartError",
    "MatrixTransformParts",
    "compose_matrix",
    "decompose_matrix",
    "euler_from_rotation",
    "is_transform_matrix_op",
    "rotation_from_euler",
    "split_axes",
    "with_matrix_part",
]

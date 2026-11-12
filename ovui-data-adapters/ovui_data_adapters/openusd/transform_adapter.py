# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""USD-backed TransformAdapter using UsdGeom.Xformable.

All matrices are plain Python list-of-lists (no pxr types cross the boundary).
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from typing import Any, List

try:
    from pxr import Gf, Sdf, Usd, UsdGeom
    HAS_USD = True
except ImportError:
    HAS_USD = False
    Usd = UsdGeom = Gf = Sdf = None  # type: ignore[assignment]

from ovui_data_adapters.common import (
    TransformAdapter,
    TransformEditMode,
    TransformEditPolicy,
)
from ovui_data_adapters.common.matrix_transform import euler_from_rotation, split_axes

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

    def set_local_transform(self, path: str, matrix: List[List[float]]) -> str | None:
        """Write the local matrix of ``path`` into its transform operations.

        Return ``None``, or a note with the cause when the operations of the
        prim cannot hold the matrix and the adapter stores one matrix
        operation in their place (the object still gets the exact matrix).
        The caller reports the note.
        """
        prim = self._stage.GetPrimAtPath(path)
        xformable = UsdGeom.Xformable(prim)
        if not xformable:
            return None
        ops = xformable.GetOrderedXformOps()
        animated = _animated_op_names(ops)
        if animated:
            # A write here would put a default value under the time samples or replace the animated ops with one matrix.
            raise RuntimeError(
                f"set_local_transform is refused for {path}: {_animated_transform_reason(animated)}"
            )
        gf_mat = Gf.Matrix4d(*[v for row in matrix for v in row])
        if len(ops) == 1 and ops[0].GetOpType() == UsdGeom.XformOp.TypeTransform and not ops[0].IsInverseOp():
            # The prim stores its transform as one matrix: write it there.
            ops[0].Set(gf_mat)
            return None
        cause = _write_component_ops(xformable, ops, matrix)
        if cause is None:
            return None
        # The operations cannot give this matrix: MakeMatrixXform clears the
        # op order and writes one Matrix4d xformOp, so the object gets the
        # exact matrix. The old operations stay as attributes.
        xformable.MakeMatrixXform().Set(gf_mat)
        return f"{path} is stored as one matrix operation (xformOp:transform), because {cause}"

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

    def get_transform_edit_policy(self, path: str) -> TransformEditPolicy:
        policy = super().get_transform_edit_policy(path)
        if not policy.is_editable:
            return policy
        xformable = UsdGeom.Xformable(self._stage.GetPrimAtPath(path))
        animated = _animated_op_names(xformable.GetOrderedXformOps()) if xformable else []
        if animated:
            return TransformEditPolicy(
                TransformEditMode.BLOCKED,
                reason=_animated_transform_reason(animated),
            )
        return policy


# The sources of a resolved value that can change over time. A spline source exists only in newer OpenUSD releases.
_ANIMATED_VALUE_SOURCES = (
    frozenset(
        source
        for source in (
            Usd.ResolveInfoSourceTimeSamples,
            Usd.ResolveInfoSourceValueClips,
            getattr(Usd, "ResolveInfoSourceSpline", None),
        )
        if source is not None
    )
    if HAS_USD
    else frozenset()
)


def _animated_op_names(ops: List[Any]) -> List[str]:
    """The names of the ``ops`` whose value comes from time samples (also one: the Property Inspector shows it as
    animated), value clips or a spline."""
    # The edit policy of each selected prim comes here. The source of the resolved value costs the same for each length
    # of animation; a list or a count of the time samples costs more for a longer animation, also for value clips.
    return [
        op.GetOpName()
        for op in ops
        if op.GetAttr().GetResolveInfo().GetSource() in _ANIMATED_VALUE_SOURCES
    ]


def _animated_transform_reason(op_names: List[str]) -> str:
    return (
        f"The transform is animated ({', '.join(op_names)}). "
        "Move, Rotate and Scale would remove the animation."
    )


def _is_xform_property(name: str) -> bool:
    return name == "xformOpOrder" or name.startswith("xformOp:")


# The roles of the operations that a gizmo edit can write, in their order in
# the op stack: translate, pivot, rotate, scale, inverse pivot.
_ROLE_ORDER = ("translate", "pivot", "rotate", "scale", "pivot_inverse")
# A gizmo edit of a component stack must give the matrix within this part of
# the largest value of the matrix: a float operation keeps about 7 digits.
_COMPONENT_TOLERANCE = 1.0e-5
# A new rotate or scale value nearer than this part of the value to the old
# value keeps the old value, so a rotate gizmo edit leaves the scale exactly
# as it was.
_KEEP_TOLERANCE = 1.0e-9
# Rounding noise of a double in the axes of a matrix and in a turn or a
# scale: 16 steps of the value.
_NOISE_TOLERANCE = 16 * sys.float_info.epsilon
# Rounding noise of the gizmo math in a move channel, as a part of the largest
# move value of the matrix: the matrix of a drag mixes the channels, so a
# channel that the drag does not move can change by several hundred steps of
# a double of that value. A larger change is a real move.
_MOVE_NOISE_TOLERANCE = 4096 * sys.float_info.epsilon
# The noise of a move channel is also at most this part of the move: a move
# smaller than the noise of a large move value is still a move.
_MOVE_NOISE_SHARE = 1.0e-6
# A float or half operation rounds a new value. The edit is lost when the
# rounding takes away this part of the change or more (a float at 1e10 keeps
# steps of 1024, so it loses a move of 5).
_EDIT_TOLERANCE = 0.5

if HAS_USD:
    _OP = UsdGeom.XformOp
    _ROTATE_ORDERS = {
        _OP.TypeRotateXYZ: "XYZ",
        _OP.TypeRotateXZY: "XZY",
        _OP.TypeRotateYXZ: "YXZ",
        _OP.TypeRotateYZX: "YZX",
        _OP.TypeRotateZXY: "ZXY",
        _OP.TypeRotateZYX: "ZYX",
    }
    _SINGLE_AXES = {_OP.TypeRotateX: 0, _OP.TypeRotateY: 1, _OP.TypeRotateZ: 2}
    _VEC_TYPES = {_OP.PrecisionDouble: Gf.Vec3d, _OP.PrecisionFloat: Gf.Vec3f, _OP.PrecisionHalf: Gf.Vec3h}
    _QUAT_TYPES = {_OP.PrecisionDouble: Gf.Quatd, _OP.PrecisionFloat: Gf.Quatf, _OP.PrecisionHalf: Gf.Quath}
    _AXES = (Gf.Vec3d(1.0, 0.0, 0.0), Gf.Vec3d(0.0, 1.0, 0.0), Gf.Vec3d(0.0, 0.0, 1.0))
    # The operation that a gizmo edit adds when the stack has none of this
    # role: its attribute name, the Add method, the precision and the type.
    _ADDED_OPS = {
        "translate": ("xformOp:translate", "AddTranslateOp", _OP.PrecisionDouble, _OP.TypeTranslate),
        "rotate": ("xformOp:rotateXYZ", "AddRotateXYZOp", _OP.PrecisionFloat, _OP.TypeRotateXYZ),
        "scale": ("xformOp:scale", "AddScaleOp", _OP.PrecisionFloat, _OP.TypeScale),
    }
    _PRECISION_OF_TYPE = {"double3": _OP.PrecisionDouble, "float3": _OP.PrecisionFloat, "half3": _OP.PrecisionHalf}
    # The role of each op name that a gizmo edit can write. The name gives the
    # role in one lookup; a name with another suffix has no role.
    _ROLE_OF_NAME = {
        "xformOp:translate": "translate",
        "xformOp:translate:pivot": "pivot",
        "!invert!xformOp:translate:pivot": "pivot_inverse",
        "xformOp:scale": "scale",
        "xformOp:orient": "rotate",
    }
    _ROLE_OF_NAME.update({
        "xformOp:" + _OP.GetOpTypeToken(op_type): "rotate" for op_type in (*_ROTATE_ORDERS, *_SINGLE_AXES)
    })
else:
    _ROTATE_ORDERS = _SINGLE_AXES = _VEC_TYPES = _QUAT_TYPES = {}
    _ADDED_OPS = _PRECISION_OF_TYPE = _ROLE_OF_NAME = {}
    _AXES = ()
_AXIS_OF_LETTER = {"X": 0, "Y": 1, "Z": 2}


def _op_role(op: Any) -> str | None:
    """The role of ``op`` in a translate, pivot, rotate, scale stack, or ``None``."""
    return _ROLE_OF_NAME.get(op.GetOpName())


def _write_component_ops(xformable: Any, ops: List[Any], matrix: List[List[float]]) -> str | None:
    """Write ``matrix`` into the translate, rotate and scale operations of the prim.

    The prim keeps its separate move, rotate and scale values: each operation
    gets the value that gives ``matrix``; a channel whose value does not
    change keeps its exact old value. A missing translate, rotate or scale
    operation is added only when the matrix needs it. A pivot stays as it is.
    Return ``None`` when the operations hold the matrix. Return the cause,
    with nothing written, when they cannot give it (another kind of
    operation, a projection, a shear, or a turn that a one-axis rotate
    operation cannot hold); the caller then writes a matrix operation.
    """
    # The first operation applies last, so a move needs only its value,
    # whatever operations follow it.
    if ops and _op_role(ops[0]) == "translate":
        moved, cause = _write_move_only(xformable, ops[0], matrix)
        if moved:
            return cause
    roles = [_op_role(op) for op in ops]
    for op, role in zip(ops, roles):
        if role is None:
            if op.GetOpType() == UsdGeom.XformOp.TypeTransform:
                return f"it has the matrix operation {op.GetOpName()} with other operations"
            return f"a gizmo edit cannot write its operation {op.GetOpName()}"
    positions = [_ROLE_ORDER.index(role) for role in roles]
    if positions != sorted(set(positions)) or (("pivot" in roles) != ("pivot_inverse" in roles)):
        return "its operations are not in the order translate, pivot, rotate, scale, inverse pivot"
    by_role = dict(zip(roles, ops))
    rows = [[float(v) for v in row] for row in matrix]
    if len(rows) != 4 or any(len(row) != 4 for row in rows):
        return "the new matrix is not 4x4"
    if not all(math.isfinite(v) for row in rows for v in row):
        return "the new matrix has a value that is not a finite number"
    size = max(1.0, max(abs(v) for row in rows for v in row))
    if any(abs(rows[i][3]) > _COMPONENT_TOLERANCE * size for i in range(3)) or abs(rows[3][3] - 1.0) > _COMPONENT_TOLERANCE * size:
        return "the new matrix has a projection (its last column is not 0, 0, 0, 1)"

    old = {role: op.Get() for role, op in by_role.items()}
    if "pivot" in old and old["pivot"] is None:
        return f"its pivot operation {by_role['pivot'].GetOpName()} has no value"
    # A shear has no operation: the final check of the stack refuses it.
    scale, rotation, shear = split_axes([row[:3] for row in rows[:3]])
    scale = _scale_with_old_signs(scale, rotation, old.get("scale"))

    new_values = {}
    if "scale" in by_role or any(abs(v - 1.0) > _NOISE_TOLERANCE for v in scale):
        new_values["scale"] = _keep_or_new(old.get("scale"), scale)
    rotate_op = by_role.get("rotate")
    rotate_value = _rotate_value(rotate_op, rotation, old.get("rotate"))
    if rotate_op is not None or rotate_value != (0.0, 0.0, 0.0):
        new_values["rotate"] = rotate_value

    pivot = tuple(old["pivot"]) if "pivot" in old else (0.0, 0.0, 0.0)
    # matrix = inverse(pivot) x scale x rotate x pivot x translate (row vectors)
    translate = [
        rows[3][c] + pivot[0] * rows[0][c] + pivot[1] * rows[1][c] + pivot[2] * rows[2][c] - pivot[c]
        for c in range(3)
    ]
    if "translate" in by_role or any(abs(v) > _NOISE_TOLERANCE * size for v in translate):
        new_values["translate"] = _keep_or_new(old.get("translate"), translate, _MOVE_NOISE_TOLERANCE * size)

    stack, cause = _planned_stack(xformable, roles, ops, old, new_values)
    if cause is not None:
        return cause
    if not _stack_gives(stack, rows, size):
        return _why_not_held(shear, rotate_op, rotation)
    _author_stack(xformable, stack)
    return None


def _why_not_held(shear, rotate_op, rotation) -> str:
    """The cause when the planned operation values do not give the matrix."""
    if any(abs(k) > _COMPONENT_TOLERANCE for k in shear):
        return "the new matrix has a shear, and no operation of the prim holds a shear"
    axis = _SINGLE_AXES.get(rotate_op.GetOpType()) if rotate_op is not None else None
    if axis is not None:
        letter = "XYZ"[axis]
        return f"{rotate_op.GetOpName()} turns only about {letter}, and the edit turns about another axis"
    return "its operations cannot give the new matrix"


def _write_move_only(xformable, translate_op, matrix):
    """Write a move: when only the translation of the matrix changes, only
    the first operation ``translate_op`` changes, by the same distance.

    The other operations keep their values, so no other check is necessary.
    Return ``(False, None)``, with nothing written, when the matrix has
    another change or ``translate_op`` has no value. Return ``(True, None)``
    after the write, or ``(True, cause)`` with nothing written when the
    precision of ``translate_op`` cannot hold the move.
    """
    old_translate = translate_op.Get()
    if old_translate is None:
        return False, None
    rows = [[float(v) for v in row] for row in matrix]
    if len(rows) != 4 or any(len(row) != 4 for row in rows) or not all(math.isfinite(v) for row in rows for v in row):
        return False, None
    old_matrix = xformable.GetLocalTransformation()
    # The tolerance comes from the axes only: a large move value must not
    # hide a turn or a scale.
    tolerance = _NOISE_TOLERANCE * max(1.0, max(abs(old_matrix[r][c]) for r in range(3) for c in range(3)))
    for r in range(3):
        if any(abs(old_matrix[r][c] - rows[r][c]) > tolerance for c in range(4)):
            return False, None
    if abs(old_matrix[3][3] - rows[3][3]) > tolerance:
        return False, None
    moved = [rows[3][c] - old_matrix[3][c] for c in range(3)]
    # A channel that changes by no more than the rounding noise of the move
    # row keeps its exact old value.
    row_size = max(1.0, max(abs(old_matrix[3][c]) for c in range(3)), max(abs(rows[3][c]) for c in range(3)))
    limit = min(_MOVE_NOISE_TOLERANCE * row_size, _MOVE_NOISE_SHARE * max(abs(d) for d in moved))
    new = tuple(o + d if abs(d) > limit else o for o, d in zip(old_translate, moved))
    if new != tuple(old_translate):
        stored = _VEC_TYPES.get(translate_op.GetPrecision(), Gf.Vec3h)(*new)
        if not _holds(old_translate, new, stored):
            return True, _precision_cause(translate_op)
        translate_op.Set(stored)
    return True, None


def _scale_with_old_signs(scale, rotation, old_scale) -> List[float]:
    """``scale`` with the signs of ``old_scale`` where a pair of flips gives them.

    A flip of two axes (scale and rotation) gives the same matrix, so a
    mirrored object keeps the axis of its negative scale after a move.
    """
    scale = list(scale)
    if old_scale is None:
        return scale
    wrong = [i for i in range(3) if (scale[i] < 0.0) != (old_scale[i] < 0.0) and scale[i] != 0.0]
    if len(wrong) % 2 == 0:
        for i in wrong:
            scale[i] = -scale[i]
            rotation[i] = [-v for v in rotation[i]]
    return scale


def _rotate_value(rotate_op, rotation, old_value):
    """The value of the rotate operation for ``rotation``.

    Without a rotate operation: XYZ angles (``(0, 0, 0)`` for no turn). A
    one-axis operation gets the angle about its axis; the final check of the
    stack refuses a turn about another axis.
    """
    if rotate_op is None:
        if all(abs(rotation[r][c] - (1.0 if r == c else 0.0)) <= _NOISE_TOLERANCE for r in range(3) for c in range(3)):
            return (0.0, 0.0, 0.0)
        return euler_from_rotation(rotation, "XYZ", hint=(0.0, 0.0, 0.0))
    op_type = rotate_op.GetOpType()
    order = _ROTATE_ORDERS.get(op_type)
    if order is not None:
        hint = tuple(old_value) if old_value is not None else (0.0, 0.0, 0.0)
        return _keep_or_new(old_value, euler_from_rotation(rotation, order, hint=hint))
    axis = _SINGLE_AXES.get(op_type)
    if axis is not None:
        a, b = (axis + 1) % 3, (axis + 2) % 3
        # Row vectors: the turn of axis a towards axis b is rotation[a][b].
        angle = math.degrees(math.atan2(rotation[a][b], rotation[a][a]))
        if old_value is not None:
            angle += 360.0 * round((float(old_value) - angle) / 360.0)
        return _keep_or_new(old_value, angle)
    quat = Gf.Matrix4d(
        rotation[0][0], rotation[0][1], rotation[0][2], 0.0,
        rotation[1][0], rotation[1][1], rotation[1][2], 0.0,
        rotation[2][0], rotation[2][1], rotation[2][2], 0.0,
        0.0, 0.0, 0.0, 1.0,
    ).ExtractRotationQuat()
    if old_value is not None:
        old_quat = Gf.Quatd(old_value)
        if Gf.Dot(quat, old_quat) < 0.0:
            quat = -quat
        if abs(Gf.Dot(quat, old_quat) - 1.0) <= _NOISE_TOLERANCE:
            return old_value
    return quat


def _keep_or_new(old_value, new_value, limit=None):
    """``new_value`` with the exact old number in each channel that did not change.

    A move along X gives Y and Z with a rounding error of the matrix math
    (1.999999999999999 for 2): such a channel keeps its old number. Returns
    ``old_value`` itself when no channel changed. ``limit`` is the largest
    change that is rounding noise; without it a channel keeps its old number
    within one billionth of its value.
    """
    if old_value is None:
        return new_value
    if isinstance(new_value, float):
        return old_value if abs(old_value - new_value) <= _KEEP_TOLERANCE * max(1.0, abs(new_value)) else new_value
    # Each channel gets a tolerance from its own value: a large value in
    # one channel must not hide a small change in another.
    kept = []
    changed = False
    for o, n in zip(tuple(old_value), new_value):
        if abs(o - n) <= (_KEEP_TOLERANCE * max(1.0, abs(n)) if limit is None else limit):
            kept.append(o)
        else:
            kept.append(n)
            changed = True
    return tuple(kept) if changed else old_value


def _holds(old_value, new_value, stored) -> bool:
    """True when ``stored`` (``new_value`` in the precision of its operation)
    keeps the edit from ``old_value``.

    A float or half value rounds; the edit is lost when the largest rounding
    of a channel takes away half of the largest change or more.
    """
    error = max(abs(float(s) - n) for n, s in zip(new_value, stored))
    return error == 0.0 or error < _EDIT_TOLERANCE * max(abs(n - o) for o, n in zip(old_value, new_value))


def _precision_cause(op) -> str:
    precision = {_OP.PrecisionDouble: "double", _OP.PrecisionFloat: "float", _OP.PrecisionHalf: "half"}[op.GetPrecision()]
    return f"{op.GetOpName()} keeps {precision} values, which cannot hold this edit"


def _planned_stack(xformable, roles, ops, old, new_values):
    """The stack after the edit, in op order: ``(role, op or None, op type,
    precision, stored value, write)``.

    ``op`` is ``None`` for an operation to add; ``write`` is ``True`` for a
    value to write. Returns ``(stack, None)``, or ``(None, cause)`` when an
    operation cannot be added (an old attribute of that name has another
    type, or is animated) or cannot hold its new value in its precision.
    """
    prim = xformable.GetPrim()
    stack = []
    for role in _ROLE_ORDER:
        if role in roles:
            op = ops[roles.index(role)]
            precision = op.GetPrecision()
            op_type = op.GetOpType()
            value = new_values.get(role, old[role])
            if value is old[role]:
                stack.append((role, op, op_type, precision, value, False))
            else:
                stored = _stored(value, precision, op_type)
                # A move is written by the move path, which checks its own
                # value. Here the scale value is the edit of a scale drag; a
                # translate (moved by a pivot) and the angles of a turn are
                # judged by the final check of the stack.
                if role == "scale" and not _holds(old[role], value, stored):
                    return None, _precision_cause(op)
                stack.append((role, op, op_type, precision, stored, True))
        elif role in new_values:
            name, _add, precision, op_type = _ADDED_OPS[role]
            existing = prim.GetAttribute(name)
            if existing and existing.IsValid():
                # An old attribute that is not in the op order (for example
                # after an earlier matrix edit) is used again, with its type.
                precision = _PRECISION_OF_TYPE.get(str(existing.GetTypeName()))
                if precision is None:
                    return None, f"the edit needs {name}, and its old attribute has the type {existing.GetTypeName()}"
                if existing.GetResolveInfo().GetSource() in _ANIMATED_VALUE_SOURCES:
                    return None, f"the edit needs {name}, and its old attribute is animated"
            stack.append((role, None, op_type, precision, _stored(new_values[role], precision, op_type), True))
    return stack, None


def _stored(value, precision, op_type):
    """``value`` as the operation stores it (half and float keep fewer digits)."""
    if op_type == _OP.TypeOrient:
        return _QUAT_TYPES[precision](value)
    vec_type = _VEC_TYPES[precision]
    if isinstance(value, (int, float)):
        # A one-axis rotate operation holds one number of this precision.
        return float(vec_type(float(value), 0.0, 0.0)[0])
    return vec_type(*value)


def _op_matrix(role, op_type, value) -> Any:
    if role == "pivot_inverse":
        return Gf.Matrix4d().SetTranslate(-Gf.Vec3d(value))
    if op_type == _OP.TypeTranslate:
        return Gf.Matrix4d().SetTranslate(Gf.Vec3d(value))
    if op_type == _OP.TypeScale:
        return Gf.Matrix4d().SetScale(Gf.Vec3d(value))
    if op_type == _OP.TypeOrient:
        return Gf.Matrix4d().SetRotate(Gf.Quatd(value))
    axis = _SINGLE_AXES.get(op_type)
    if axis is not None:
        return Gf.Matrix4d().SetRotate(Gf.Rotation(_AXES[axis], float(value)))
    # rotate<order>: the first axis of the order applies first (row vectors).
    turn = Gf.Rotation()
    turn.SetIdentity()
    for letter in _ROTATE_ORDERS[op_type]:
        axis = _AXIS_OF_LETTER[letter]
        turn = turn * Gf.Rotation(_AXES[axis], float(value[axis]))
    return Gf.Matrix4d().SetRotate(turn)


def _stack_gives(stack, rows, size) -> bool:
    """True when the stored values of ``stack`` give the matrix ``rows``."""
    result = Gf.Matrix4d(1.0)
    for role, _op, op_type, _precision, value, _write in reversed(stack):
        result = result * _op_matrix(role, op_type, value)
    # The rows of the axes get a tolerance from the axes only: a large move
    # value must not hide a turn or a scale that the operations cannot give.
    axes_size = max(1.0, max(abs(rows[r][c]) for r in range(3) for c in range(3)))
    for r in range(3):
        if not Gf.IsClose(result.GetRow(r), Gf.Vec4d(*rows[r]), _COMPONENT_TOLERANCE * axes_size):
            return False
    return Gf.IsClose(result.GetRow(3), Gf.Vec4d(*rows[3]), _COMPONENT_TOLERANCE * size)


def _author_stack(xformable, stack) -> None:
    """Write the changed values of ``stack``; add its new operations in their place."""
    new_ops = []
    added = False
    for role, op, _op_type, precision, value, write in stack:
        if op is None:
            _name, add, _precision, _type = _ADDED_OPS[role]
            op = getattr(xformable, add)(precision)
            added = True
        new_ops.append(op)
        if write:
            op.Set(value)
    if added:
        # Add*Op appends; put each operation in its place in the order.
        xformable.SetXformOpOrder(new_ops, xformable.GetResetXformStack())

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""PrimTransformModel — manages multi-prim transform drag state.

Captures initial transforms on drag start, applies deltas during drag,
and brackets the operation in an undo group.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from ovui_data_adapters.common import StageAdapter, TransformAdapter

from ovwidgets.common.undo import BatchTransformCommand, UndoManager

if TYPE_CHECKING:
    from ovwidgets.common.snap import SnapSystem


_LIVE_TRANSFORM_CHANGE_SOURCE = "viewport-manipulator-live"
_FINAL_TRANSFORM_CHANGE_SOURCE = "viewport-manipulator"


class PrimTransformModel:
    """Manages multi-prim transform drag state."""

    def __init__(
        self,
        transform_adapter: Optional[TransformAdapter] = None,
        stage_adapter: Optional[StageAdapter] = None,
        undo: Optional[UndoManager] = None,
        snap_system: Optional["SnapSystem"] = None,
    ) -> None:
        self._transform = transform_adapter
        self._stage = stage_adapter
        self._undo = undo
        self._snap = snap_system
        self._selected_paths: List[str] = []
        self._initial_transforms: Dict[str, List[List[float]]] = {}
        self._mode = "world"
        # Label of the currently-open drag. Set by :meth:`on_drag_start` and
        # used by :meth:`on_drag_ended` so the undo group and the stage
        # adapter's change-block share a consistent name (``"Move Prims"``,
        # ``"Rotate Prims"``, …).
        self._drag_label: str = "Move Prims"

    def attach_adapters(
        self,
        transform_adapter: Optional[TransformAdapter] = None,
        stage_adapter: Optional[StageAdapter] = None,
        undo: Optional[UndoManager] = None,
        snap_system: Optional["SnapSystem"] = None,
    ) -> None:
        """Bind adapters after construction (Step C.2 wire-up).

        Step C.5 will replace this with full selection-bus driven
        instantiation; for now the ViewportWidget calls this when a stage
        loads so the translate gizmo can reach USD.
        """
        self._transform = transform_adapter
        self._stage = stage_adapter
        self._undo = undo
        self._snap = snap_system

    def has_adapters(self) -> bool:
        """True iff the minimum set of adapters needed for a drag is wired."""
        return (
            self._transform is not None
            and self._stage is not None
            and self._undo is not None
        )

    @property
    def transform_space(self) -> str:
        """Current transform coordinate space.

        OvGear currently exposes only world-space manipulation, but the mode is
        stored on the model so HUDs and future controls can read the same live
        state the drag math uses.
        """
        return self._mode

    def get_pivot_world(self) -> Tuple[float, float, float]:
        """World-space position of the first selected prim, or origin.

        Used by :class:`~ovwidgets.viewport.transform_manipulator.TransformManipulator`
        as its ``pivot_fn``. Reads the world transform from the attached
        :class:`TransformAdapter`; returns ``(0, 0, 0)`` when there is no
        selection or the adapter isn't wired.
        """
        if self._transform is None or not self._selected_paths:
            return (0.0, 0.0, 0.0)
        try:
            mat = self._transform.get_world_transform(self._selected_paths[0])
        except Exception:
            return (0.0, 0.0, 0.0)
        # Row-major: translation in row 3, columns 0..2.
        return (float(mat[3][0]), float(mat[3][1]), float(mat[3][2]))

    def set_selection(self, paths: List[str]) -> None:
        if self._transform is None:
            # Without a transform adapter we can't test ``can_transform`` —
            # keep the raw list so the manipulator still sees a selection
            # (the drag will become inert via ``has_adapters()``).
            self._selected_paths = list(paths)
            return
        self._selected_paths = [p for p in paths if self._transform.can_transform(p)]

    def on_drag_start(self, label: str = "Move Prims") -> None:
        self._drag_label = label
        self._initial_transforms = {
            path: self._transform.get_local_transform(path)
            for path in self._selected_paths
        }
        self._stage.begin_undo_group(label)

    def on_drag_moved(self, delta_matrix: List[List[float]]) -> None:
        written_paths: List[str] = []
        with self._stage.suppress_change_notifications():
            for path, initial in self._initial_transforms.items():
                new_local = _apply_delta(initial, delta_matrix, self._mode)
                if self._snap is not None:
                    pos = [new_local[3][0], new_local[3][1], new_local[3][2]]
                    snapped = self._snap.snap(pos, None)
                    new_local[3][0] = snapped[0]
                    new_local[3][1] = snapped[1]
                    new_local[3][2] = snapped[2]
                self._transform.set_local_transform(path, new_local)
                written_paths.append(path)
        self._notify_transform_changed(
            written_paths,
            source=_LIVE_TRANSFORM_CHANGE_SOURCE,
        )

    def on_drag_rotated(
        self, axis: Tuple[float, float, float], angle: float
    ) -> None:
        """Rotate each selected prim by ``angle`` radians around world ``axis``.

        The rotation pivots around each prim's own origin: the row-major
        upper-3×3 of its initial local transform is right-multiplied by the
        Rodrigues rotation matrix for ``(axis, angle)``; the translation row
        is copied unchanged. With the standard row-major convention
        ``world = local @ parent`` this rotates each prim's world axes by
        ``angle`` around ``axis`` while keeping its position fixed — the
        "rotate in place" behaviour Maya/Blender give you when the pivot is
        the object's own pivot (which is what the C.3 gizmo draws at).
        """
        rot = _rotation_matrix_row_major(axis, angle)
        written_paths: List[str] = []
        with self._stage.suppress_change_notifications():
            for path, initial in self._initial_transforms.items():
                new_local = _compose_rotation(initial, rot)
                self._transform.set_local_transform(path, new_local)
                written_paths.append(path)
        self._notify_transform_changed(
            written_paths,
            source=_LIVE_TRANSFORM_CHANGE_SOURCE,
        )

    def on_drag_scaled(
        self, axis: Tuple[float, float, float], factor: float
    ) -> None:
        """Scale each selected prim by ``factor`` along the marked local axes.

        ``axis`` is a scale-axis mask: every component ``!= 0`` receives
        the factor; components equal to zero keep scale 1.0. Pass
        ``(1, 0, 0)`` / ``(0, 1, 0)`` / ``(0, 0, 1)`` for the per-axis
        handles and ``(1, 1, 1)`` for the uniform handle.

        Row-major / row-vector convention: we pre-multiply the prim's
        initial local transform by ``S = diag(sx, sy, sz, 1)``. That
        scales each of the upper-3×3 rows (the prim's local X / Y / Z
        axes) while leaving the translation row (``initial[3]``) exactly
        as it was — i.e., the prim scales about its own origin, which
        is where the scale gizmo draws its cubes. Equivalent to editing
        the prim's ``xformOp:scale`` when all other local ops compose to
        identity, but we write the full matrix so the composition works
        for any xform stack.
        """
        sx = factor if axis[0] != 0.0 else 1.0
        sy = factor if axis[1] != 0.0 else 1.0
        sz = factor if axis[2] != 0.0 else 1.0
        written_paths: List[str] = []
        with self._stage.suppress_change_notifications():
            for path, initial in self._initial_transforms.items():
                new_local = _apply_scale(initial, sx, sy, sz)
                self._transform.set_local_transform(path, new_local)
                written_paths.append(path)
        self._notify_transform_changed(
            written_paths,
            source=_LIVE_TRANSFORM_CHANGE_SOURCE,
        )

    def on_drag_ended(self) -> None:
        label = self._drag_label
        changed_paths: List[str] = []
        self._undo.begin_group(label)
        for path, initial in self._initial_transforms.items():
            final = self._transform.get_local_transform(path)
            if not _matrices_close(initial, final):
                changed_paths.append(path)
            cmd = BatchTransformCommand(self._transform, path, initial, final)
            self._undo.push(cmd)
        self._undo.end_group()
        self._stage.end_undo_group()
        self._notify_transform_changed(
            changed_paths,
            source=_FINAL_TRANSFORM_CHANGE_SOURCE,
        )
        self._initial_transforms.clear()

    def _notify_transform_changed(self, paths: List[str], source: str) -> None:
        notify_transform_changed = getattr(self._stage, "notify_transform_changed", None)
        if paths and callable(notify_transform_changed):
            notify_transform_changed(paths, source=source)


def _apply_delta(
    initial: List[List[float]],
    delta: List[List[float]],
    mode: str,
) -> List[List[float]]:
    """4×4 row-major matrix multiply: initial × delta."""
    result = [[0.0] * 4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            for k in range(4):
                result[i][j] += initial[i][k] * delta[k][j]
    return result


def _rotation_matrix_row_major(
    axis: Tuple[float, float, float], angle: float
) -> List[List[float]]:
    """Row-major Rodrigues rotation matrix for ``(axis, angle)``.

    ``axis`` must be a unit vector. Shares the row-vector convention used
    throughout ovgear: rotate a point via ``p @ R``. Translation is zero —
    a pure rotation about the origin. Kept local to
    :mod:`prim_transform_model` so the USD write-through does not have to
    import the gizmo module.
    """
    ax, ay, az = axis
    c = math.cos(angle)
    s = math.sin(angle)
    t = 1.0 - c
    return [
        [c + ax * ax * t,       ay * ax * t + az * s,  az * ax * t - ay * s, 0.0],
        [ax * ay * t - az * s,  c + ay * ay * t,       az * ay * t + ax * s, 0.0],
        [ax * az * t + ay * s,  ay * az * t - ax * s,  c + az * az * t,      0.0],
        [0.0,                   0.0,                   0.0,                  1.0],
    ]


def _apply_scale(
    initial: List[List[float]], sx: float, sy: float, sz: float
) -> List[List[float]]:
    """Pre-multiply ``initial`` by ``diag(sx, sy, sz, 1)``: ``S @ initial``.

    Row-major row-vector convention. ``S`` is diagonal, so the product
    simplifies to a per-row scale of the upper-3×3 and an unchanged
    translation row. Called by :meth:`PrimTransformModel.on_drag_scaled`
    once per selected prim per drag frame; kept module-private since the
    scale gizmo talks to the model, not this helper.
    """
    factors = (sx, sy, sz)
    new = [[0.0] * 4 for _ in range(4)]
    for i in range(3):
        f = factors[i]
        for j in range(4):
            new[i][j] = f * initial[i][j]
    new[3][0] = initial[3][0]
    new[3][1] = initial[3][1]
    new[3][2] = initial[3][2]
    new[3][3] = 1.0
    return new


def _compose_rotation(
    initial: List[List[float]], rot: List[List[float]]
) -> List[List[float]]:
    """Right-multiply ``initial``'s upper-3×3 by ``rot``, preserving translation.

    Row-major: ``new_upper3x3 = initial_upper3x3 @ rot_upper3x3`` leaves
    the translation row (``initial[3]``) untouched. This rotates the prim
    around its own origin: the gizmo draws at the prim's world pivot
    (Step C.5 will refine the pivot source), so the visual and math agree.
    """
    new = [[0.0] * 4 for _ in range(4)]
    for i in range(3):
        for j in range(3):
            new[i][j] = sum(initial[i][k] * rot[k][j] for k in range(3))
    # Copy initial's translation row verbatim. Homogeneous column [x][3] and
    # row [3][3] follow the row-major affine convention (0, 0, 0, 1).
    new[3][0] = initial[3][0]
    new[3][1] = initial[3][1]
    new[3][2] = initial[3][2]
    new[3][3] = 1.0
    return new


def _matrices_close(
    left: List[List[float]],
    right: List[List[float]],
    *,
    tolerance: float = 1.0e-9,
) -> bool:
    if len(left) != len(right):
        return False
    for left_row, right_row in zip(left, right):
        if len(left_row) != len(right_row):
            return False
        for left_value, right_value in zip(left_row, right_row):
            if abs(float(left_value) - float(right_value)) > tolerance:
                return False
    return True

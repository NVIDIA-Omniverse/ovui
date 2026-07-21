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

from ovui_data_adapters.common import (
    RendererAdapter,
    StageAdapter,
    TransformAdapter,
    TransformEditPolicy,
)

from ovui_widgets.common.error_reporter import ErrorReporter
from ovui_widgets.common.undo import BatchTransformCommand, UndoManager

if TYPE_CHECKING:
    from ovui_widgets.common.snap import SnapSystem


_FINAL_TRANSFORM_CHANGE_SOURCE = "viewport-manipulator"


def _shielded_log(message: str, exc: Exception) -> None:
    """Diagnostics may never participate in lifecycle correctness."""
    try:
        ErrorReporter.log_error("PrimTransformModel", message, exc)
    except BaseException:
        pass


class PrimTransformModel:
    """Manages multi-prim transform drag state."""

    def __init__(
        self,
        transform_adapter: Optional[TransformAdapter] = None,
        stage_adapter: Optional[StageAdapter] = None,
        undo: Optional[UndoManager] = None,
        snap_system: Optional["SnapSystem"] = None,
        *,
        renderer: Optional[RendererAdapter] = None,
    ) -> None:
        self._transform = transform_adapter
        self._stage = stage_adapter
        self._undo = undo
        self._snap = snap_system
        self._renderer = renderer
        self._raw_selected_paths: List[str] = []
        self._selected_paths: List[str] = []
        self._selection_policies: Dict[str, TransformEditPolicy] = {}
        self._initial_transforms: Dict[str, List[List[float]]] = {}
        self._live_transforms: Dict[str, List[List[float]]] = {}
        self._live_parent_world_transforms: Dict[str, List[List[float]]] = {}
        self._drag_active = False
        # Paths whose preview write landed — cancellation owes these.
        self._preview_applied_paths: set[str] = set()
        # Cancel-rollback failures (path → drag-start matrix), retried.
        self._failed_preview_restores: Dict[str, List[List[float]]] = {}
        # Undo owners with an unproven begin/close, by identity; never
        # re-closed; drags on them stay blocked until replacement.
        self._contaminated_undo_owners: List[Any] = []
        self._undo_fail_closed = False
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
        *,
        renderer: Optional[RendererAdapter] = None,
    ) -> None:
        """Bind adapters after construction (Step C.2 wire-up).

        Step C.5 will replace this with full selection-bus driven
        instantiation; for now the ViewportWidget calls this when a stage
        loads so the translate gizmo can reach USD.

        Generation identity is object identity: any owner change is a
        boundary — the in-flight drag resolves against the outgoing
        adapters and pending cancel-restore state is discarded with them.
        """
        if (transform_adapter is self._transform
                and stage_adapter is self._stage
                and undo is self._undo and renderer is self._renderer):
            self._snap = snap_system
            return
        try:
            if self._drag_active:
                self.on_drag_cancelled()
        except Exception as exc:
            _shielded_log(
                "drag cancellation failed during stage re-attachment", exc
            )
        self._failed_preview_restores.clear()
        self._preview_applied_paths.clear()
        # Owner replacement is the sanctioned latched-contamination recovery.
        if stage_adapter is not self._stage or undo is not self._undo:
            self._undo_fail_closed = False
        self._transform = transform_adapter
        self._stage = stage_adapter
        self._undo = undo
        self._snap = snap_system
        self._renderer = renderer

    @property
    def renderer_adapter(self) -> Optional[RendererAdapter]:
        """Renderer available for interaction-time visual previews."""
        return self._renderer

    def set_renderer(self, renderer: Optional[RendererAdapter]) -> None:
        """Replace the interaction renderer (a generation boundary): the
        in-flight drag resolves against the outgoing renderer and owed
        recovery state is discarded with it."""
        if renderer is self._renderer:
            return
        try:
            if self._drag_active:
                self.on_drag_cancelled()
        except Exception as exc:
            _shielded_log(
                "drag cancellation failed during renderer replacement", exc
            )
        self._failed_preview_restores.clear()
        self._preview_applied_paths.clear()
        self._renderer = renderer

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

        Used by :class:`~ovui_widgets.viewport.transform_manipulator.TransformManipulator`
        as its ``pivot_fn``. Reads the world transform from the attached
        :class:`TransformAdapter`; returns ``(0, 0, 0)`` when there is no
        selection or the adapter isn't wired.
        """
        if self._transform is None or not self._selected_paths:
            return (0.0, 0.0, 0.0)
        path = self._selected_paths[0]
        if self._drag_active:
            live_local = self._live_transforms.get(path)
            if live_local is None:
                live_local = self._initial_transforms.get(path)
            if live_local is not None:
                mat = self._live_world_transform(path, live_local)
                return (float(mat[3][0]), float(mat[3][1]), float(mat[3][2]))
        try:
            mat = self._transform.get_world_transform(path)
        except Exception:
            return (0.0, 0.0, 0.0)
        # Row-major: translation in row 3, columns 0..2.
        return (float(mat[3][0]), float(mat[3][1]), float(mat[3][2]))

    def set_selection(self, paths: List[str]) -> None:
        # Selection clicks are the cheapest frequent repair point.
        if self._failed_preview_restores:
            self.retry_failed_preview_restores()
        self._raw_selected_paths = list(paths)
        self._selection_policies = {}
        if self._transform is None:
            # Without a transform adapter we can't test ``can_transform`` —
            # keep the raw list so the manipulator still sees a selection
            # (the drag will become inert via ``has_adapters()``).
            self._selected_paths = list(paths)
            return
        selected: List[str] = []
        for path in paths:
            policy_fn = getattr(self._transform, "get_transform_edit_policy", None)
            if callable(policy_fn):
                try:
                    policy = policy_fn(path)
                except Exception:
                    policy = None
                if policy is not None:
                    self._selection_policies[path] = policy
                    if getattr(policy, "is_editable", False):
                        selected.append(path)
                    continue
            if self._transform.can_transform(path):
                selected.append(path)
        self._selected_paths = selected

    def has_transformable_selection(self) -> bool:
        return bool(self._selected_paths)

    def transform_controls_enabled(self) -> bool:
        if not self._raw_selected_paths:
            return True
        return self.has_transformable_selection()

    def transform_controls_tooltip(self) -> str:
        if self.transform_controls_enabled():
            return ""
        for policy in self._selection_policies.values():
            reason = getattr(policy, "reason", "")
            if reason:
                return str(reason)
        return "Transform controls are unavailable for the current selection"

    def selection_edit_policies(self) -> Dict[str, TransformEditPolicy]:
        return dict(self._selection_policies)

    def on_drag_start(self, label: str = "Move Prims") -> None:
        # Retry owed restores before capturing new drag-start state.
        if self._failed_preview_restores:
            self.retry_failed_preview_restores()
        if self._undo_owner_contaminated():
            # Unproven closure: never re-close; block until replacement.
            raise RuntimeError(
                "transform drag blocked: this stage's undo owner has a "
                "group whose closure could not be proven; replace the "
                "stage/undo lifecycle to recover")
        self._drag_label = label
        self._live_transforms.clear()
        self._live_parent_world_transforms.clear()
        self._preview_applied_paths.clear()
        self._initial_transforms = {}
        for path in self._selected_paths:
            initial = self._transform.get_local_transform(path)
            self._initial_transforms[path] = initial
            parent_world = self._capture_parent_world_transform(path, initial)
            if parent_world is not None:
                self._live_parent_world_transforms[path] = parent_world
        try:
            self._stage.begin_undo_group(label)
        except BaseException:
            # Failed admission: rebind (infallibly) every capture a queued
            # callback could turn into a preview or commit, then contaminate.
            self._initial_transforms = {}
            self._live_transforms = {}
            self._live_parent_world_transforms = {}
            self._preview_applied_paths = set()
            # Infallible latch FIRST; identity recording may fail.
            self._undo_fail_closed = True
            try:
                self._record_undo_contamination()
                self._undo_fail_closed = False
            except BaseException as record_exc:
                _shielded_log("undo contamination recording failed", record_exc)
            raise
        self._drag_active = True

    def on_drag_moved(self, delta_matrix: List[List[float]]) -> None:
        for path, initial in self._initial_transforms.items():
            new_local = _apply_delta(initial, delta_matrix, self._mode)
            if self._snap is not None:
                pos = [new_local[3][0], new_local[3][1], new_local[3][2]]
                snapped = self._snap.snap(pos, None)
                new_local[3][0] = snapped[0]
                new_local[3][1] = snapped[1]
                new_local[3][2] = snapped[2]
            self._set_live_local_transform(path, new_local)

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
        for path, initial in self._initial_transforms.items():
            new_local = _compose_rotation(initial, rot)
            self._set_live_local_transform(path, new_local)

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
        for path, initial in self._initial_transforms.items():
            new_local = _apply_scale(initial, sx, sy, sz)
            self._set_live_local_transform(path, new_local)

    def on_drag_ended(self) -> None:
        label = self._drag_label
        changed_paths: List[str] = []
        live_preview_paths = list(self._live_transforms)
        operation_error: BaseException | None = None
        stage_group_open = self._drag_active
        try:
            with self._stage.suppress_change_notifications():
                self._undo.begin_group(label)
                undo_group_open = True
                try:
                    for path, initial in self._initial_transforms.items():
                        final = self._live_transforms.get(path)
                        if final is None:
                            final = self._transform.get_local_transform(path)
                        if not _matrices_close(initial, final):
                            changed_paths.append(path)
                        cmd = BatchTransformCommand(
                            self._transform,
                            path,
                            initial,
                            final,
                        )
                        self._undo.push(cmd)
                    self._undo.end_group()
                    undo_group_open = False
                except BaseException as commit_error:
                    if undo_group_open:
                        try:
                            self._undo.cancel_group()
                            undo_group_open = False
                        except BaseException as compensation_error:
                            add_note = getattr(commit_error, "add_note", None)
                            if callable(add_note):
                                add_note(
                                    "transform group compensation also failed: "
                                    f"{type(compensation_error).__name__}: "
                                    f"{compensation_error}"
                                )
                    raise
            if stage_group_open:
                self._stage.end_undo_group()
                stage_group_open = False
            self._notify_transform_changed(
                changed_paths,
                source=_FINAL_TRANSFORM_CHANGE_SOURCE,
            )
        except BaseException as exc:
            operation_error = exc
            raise
        finally:
            try:
                if stage_group_open:
                    try:
                        self._stage.end_undo_group()
                    except BaseException as close_error:
                        if operation_error is None:
                            raise
                        add_note = getattr(operation_error, "add_note", None)
                        if callable(add_note):
                            add_note(
                                "stage transform group cleanup also failed: "
                                f"{type(close_error).__name__}: {close_error}"
                            )
            finally:
                # Whether commit succeeded or was compensated, the backing
                # USD stage is authoritative. Remove every transient OVStage
                # ``omni:xform`` preview before releasing the drag lifecycle.
                self._clear_live_local_transforms(live_preview_paths)
                self._initial_transforms.clear()
                self._live_transforms.clear()
                self._live_parent_world_transforms.clear()
                self._preview_applied_paths.clear()
                self._drag_active = False

    def on_drag_cancelled(self) -> None:
        """Cancel the active drag; never authors USD. The ``finally``
        always finalizes drag state (a later mouse-up cannot commit)
        while the primary failure still propagates."""
        try:
            live_preview_paths = list(self._live_transforms)
            # Re-publish drag-start transforms through the preview channel
            # or the cancelled prim stays held; failed restores retried.
            failed: Dict[str, List[List[float]]] = {}
            for path in live_preview_paths:
                if path not in self._preview_applied_paths:
                    continue
                initial = self._initial_transforms.get(path)
                if initial is None:
                    continue
                if not self._set_live_local_transform(path, initial):
                    failed[path] = [row[:] for row in initial]
            self._clear_live_local_transforms(live_preview_paths)
            if failed:
                self._failed_preview_restores.update(failed)
            if self._drag_active:
                end_undo_group = getattr(self._stage, "end_undo_group", None)
                if callable(end_undo_group):
                    try:
                        end_undo_group()
                    except BaseException:
                        # Interrupt-class closes are equally unproven.
                        self._record_undo_contamination()
                        raise
        finally:
            self._initial_transforms.clear()
            self._live_transforms.clear()
            self._live_parent_world_transforms.clear()
            self._preview_applied_paths.clear()
            self._drag_active = False

    @property
    def contaminated_undo_owners(self) -> tuple:
        """Undo owners with a group whose closure could not be proven."""
        return tuple(self._contaminated_undo_owners)

    def _record_undo_contamination(self) -> None:
        """Record the drag's undo owners (real owner + wrapper) by identity."""
        real_owner = getattr(self._stage, "_undo_manager", None)
        for owner in (real_owner, self._undo, self._stage):
            if owner is not None and not any(
                    o is owner for o in self._contaminated_undo_owners):
                self._contaminated_undo_owners.append(owner)

    def _undo_owner_contaminated(self) -> bool:
        """True when any of the CURRENT wiring's owners is contaminated."""
        if self._undo_fail_closed:
            return True
        real_owner = getattr(self._stage, "_undo_manager", None)
        current = (real_owner, self._undo, self._stage)
        return any(
            o is owner
            for o in self._contaminated_undo_owners
            for owner in current
            if owner is not None
        )

    @property
    def failed_preview_restores(self) -> Dict[str, List[List[float]]]:
        """Cancel rollbacks still owed to the renderer (path → matrix)."""
        return {path: [row[:] for row in matrix]
                for path, matrix in self._failed_preview_restores.items()}

    def retry_failed_preview_restores(self) -> bool:
        """Retry renderer restores a previous cancel could not complete;
        True when nothing remains. Restores the CURRENT authoritative
        transform via the preview channel; never authors USD."""
        if not self._failed_preview_restores:
            return True
        set_live = getattr(self._renderer, "set_live_local_transform", None)
        get_local = getattr(self._transform, "get_local_transform", None)
        recovered: List[str] = []
        for path in list(self._failed_preview_restores):
            if not callable(get_local):
                break
            try:
                target = get_local(path)
            except Exception:
                continue
            if target is None or not callable(set_live):
                continue
            try:
                ok = bool(set_live(path, [row[:] for row in target]))
            except Exception:
                ok = False
            if ok:
                recovered.append(path)
        for path in recovered:
            self._failed_preview_restores.pop(path, None)
        if recovered:
            self._clear_live_local_transforms(recovered)
        return not self._failed_preview_restores

    def _notify_transform_changed(self, paths: List[str], source: str) -> None:
        notify_transform_changed = getattr(self._stage, "notify_transform_changed", None)
        if paths and callable(notify_transform_changed):
            notify_transform_changed(paths, source=source)

    def _set_live_local_transform(
        self,
        path: str,
        matrix: List[List[float]],
    ) -> bool:
        copied = [row[:] for row in matrix]
        self._live_transforms[path] = copied
        set_live = getattr(self._renderer, "set_live_local_transform", None)
        if not callable(set_live):
            return False
        try:
            applied = bool(set_live(path, copied))
        except Exception:
            return False
        if applied:
            # Cancellation owes exactly the landed preview writes.
            self._preview_applied_paths.add(path)
        return applied

    def _clear_live_local_transforms(self, paths: List[str]) -> None:
        if not paths:
            return
        clear = getattr(self._renderer, "clear_live_local_transforms", None)
        if not callable(clear):
            return
        try:
            clear(list(paths))
        except Exception:
            pass

    def _capture_parent_world_transform(
        self,
        path: str,
        local_matrix: List[List[float]],
    ) -> Optional[List[List[float]]]:
        get_world_transform = getattr(self._transform, "get_world_transform", None)
        if not callable(get_world_transform):
            return None
        try:
            world_matrix = get_world_transform(path)
        except Exception:
            return None
        inverse_local = _invert_matrix_4x4(local_matrix)
        if inverse_local is None:
            return None
        return _matrix_multiply(inverse_local, world_matrix)

    def _live_world_transform(
        self,
        path: str,
        local_matrix: List[List[float]],
    ) -> List[List[float]]:
        parent_world = self._live_parent_world_transforms.get(path)
        if parent_world is None:
            return [row[:] for row in local_matrix]
        return _matrix_multiply(local_matrix, parent_world)


def _matrix_multiply(
    left: List[List[float]],
    right: List[List[float]],
) -> List[List[float]]:
    result = [[0.0] * 4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            for k in range(4):
                result[i][j] += left[i][k] * right[k][j]
    return result


def _invert_matrix_4x4(matrix: List[List[float]]) -> Optional[List[List[float]]]:
    size = 4
    augmented = [
        [float(matrix[row][col]) for col in range(size)]
        + [1.0 if row == col else 0.0 for col in range(size)]
        for row in range(size)
    ]
    for col in range(size):
        pivot_row = max(
            range(col, size),
            key=lambda row: abs(augmented[row][col]),
        )
        if abs(augmented[pivot_row][col]) < 1e-12:
            return None
        if pivot_row != col:
            augmented[col], augmented[pivot_row] = (
                augmented[pivot_row],
                augmented[col],
            )
        pivot = augmented[col][col]
        augmented[col] = [value / pivot for value in augmented[col]]
        for row in range(size):
            if row == col:
                continue
            factor = augmented[row][col]
            if factor == 0.0:
                continue
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[col])
            ]
    return [row[size:] for row in augmented]


def _apply_delta(
    initial: List[List[float]],
    delta: List[List[float]],
    mode: str,
) -> List[List[float]]:
    """4×4 row-major matrix multiply: initial × delta."""
    return _matrix_multiply(initial, delta)


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

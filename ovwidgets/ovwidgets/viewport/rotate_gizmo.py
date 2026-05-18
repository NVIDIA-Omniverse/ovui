# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Rotate gizmo — axis rings with drag + hover highlight.

Step C.3 of the viewport behavior. Replaces the C.1 wireframe-arc
placeholder with real draggable rotation rings. Three responsibilities:

1. **Geometry** — :func:`build_rotate_gizmo` draws three ``sc.Arc`` rings
   (``wireframe=True``) perpendicular to the X / Y / Z world axes. Each ring
   owns a :class:`PrimRotateChangedGesture` (drag) and a
   :class:`~ovwidgets.viewport.translate_gizmo.HighlightGesture` (hover).
2. **Drag math** — :class:`PrimRotateChangedGesture` reads the arc's signed
   polar angle out of ``sc.Arc.gesture_payload.angle`` on each frame,
   subtracts the angle captured at ``on_began``, and hands the resulting
   signed rotation angle together with the world-space axis to
   :meth:`~ovwidgets.viewport.prim_transform_model.PrimTransformModel.on_drag_rotated`.
   The model composes the Rodrigues rotation matrix into each selected
   prim's local transform and handles the USD write-through + undo bracket.
3. **Highlight** — the same
   :class:`~ovwidgets.viewport.translate_gizmo.HighlightGesture` swaps the ring's
   colour for a brighter variant on hover; no reimplementation here.

The rings are drawn in gizmo-local space at unit radius — the parent
:class:`~ovwidgets.viewport.transform_manipulator.TransformManipulator` wraps
them in translate-to-pivot → uniform scale so the gizmo sits at the
selected prim at a constant screen size (``GIZMO_SIZE_SCALE``).
"""

from __future__ import annotations

import math
from typing import Any, List, Optional, Tuple

from omni.ui_scene import scene as sc

from ovwidgets.viewport.transform_manipulator import (
    AXIS_COLOR_X,
    AXIS_COLOR_Y,
    AXIS_COLOR_Z,
    TransformGestureBase,
)
from ovwidgets.viewport.translate_gizmo import (
    HIGHLIGHT_COLOR_X,
    HIGHLIGHT_COLOR_Y,
    HIGHLIGHT_COLOR_Z,
    HighlightGesture,
)

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

# Ring radius in gizmo-local space. Matches the translate-gizmo shaft length
# (``SHAFT_LENGTH = 1.0``) so the ring circumscribes the arrow tips — the
# standard Maya/Blender look where the rotation ring and translation arrow
# read as parts of one unified tool.
RING_RADIUS: float = 1.0

# Ring line thickness in pixels. Matches the translate shaft to keep the
# two tools visually consistent — thin, elegant, readable against a
# ray-traced background.
RING_THICKNESS: float = 2.0

# How wide the picking region is around the ring outline, in pixels.
# Generous enough that the thin 2 px outline is easy to grab without the
# hit region swallowing adjacent rings.
RING_INTERSECTION_THICKNESS: float = 10.0

# Mouse buttons + modifiers. Left-click-drag, no modifiers — matches the
# translate gizmo and every DCC convention.
_MOUSE_LEFT: int = 0
_NO_MODIFIERS: int = 0

# Per-axis ring table. ``arc_axis_idx`` picks the sc.Arc ``axis=`` argument:
# ``0`` → ring in the YZ plane (perpendicular to X, rotates around X),
# ``1`` → ring in the XZ plane (⊥ Y, rotates around Y),
# ``2`` → ring in the XY plane (⊥ Z, rotates around Z).
_AXES: Tuple[Tuple[str, Tuple[float, float, float], int, int, int], ...] = (
    ("x", (1.0, 0.0, 0.0), AXIS_COLOR_X, HIGHLIGHT_COLOR_X, 0),
    ("y", (0.0, 1.0, 0.0), AXIS_COLOR_Y, HIGHLIGHT_COLOR_Y, 1),
    ("z", (0.0, 0.0, 1.0), AXIS_COLOR_Z, HIGHLIGHT_COLOR_Z, 2),
)


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------


def rotation_matrix_row_major(
    axis: Tuple[float, float, float], angle: float
) -> List[List[float]]:
    """Return a 4×4 row-major Rodrigues rotation matrix.

    ``axis`` must be a unit vector; ``angle`` is in radians. The matrix
    follows ovgear's row-major convention — a row-vector point ``p`` is
    rotated via ``p @ R``. Translation row/column is identity so the
    matrix is a pure rotation about the origin. Callers compose it with
    each prim's initial local transform via matrix multiply.
    """
    ax, ay, az = axis
    c = math.cos(angle)
    s = math.sin(angle)
    t = 1.0 - c
    # Row-major Rodrigues — transpose of the textbook column-vector form so
    # ``(x, y, z) @ R`` gives the rotated point. Verified against the
    # cardinal cases (axis = (0,0,1), angle = π/2 sends +X → +Y).
    return [
        [c + ax * ax * t,       ay * ax * t + az * s,  az * ax * t - ay * s, 0.0],
        [ax * ay * t - az * s,  c + ay * ay * t,       az * ay * t + ax * s, 0.0],
        [ax * az * t + ay * s,  ay * az * t - ax * s,  c + az * az * t,      0.0],
        [0.0,                   0.0,                   0.0,                  1.0],
    ]


# ---------------------------------------------------------------------------
# Gesture
# ---------------------------------------------------------------------------


class PrimRotateChangedGesture(TransformGestureBase):
    """Axis-constrained rotation drag gesture.

    Reads ``sc.Arc.gesture_payload.angle`` — the signed polar angle of the
    mouse position on the arc, in radians — and pipes frame-to-frame
    deltas into
    :meth:`~ovwidgets.viewport.prim_transform_model.PrimTransformModel.on_drag_rotated`.

    Lifecycle
    ---------
    * ``on_began``: record ``gesture_payload.angle`` as the baseline; if
      the model has a non-empty selection, call
      :meth:`PrimTransformModel.on_drag_start` with label ``"Rotate Prims"``
      so the stage adapter opens a correspondingly-named undo group.
    * ``on_changed``: compute ``delta = current_angle - baseline_angle``
      and call
      :meth:`PrimTransformModel.on_drag_rotated(axis, delta)`. The model
      composes the rotation and writes the new local transform per prim.
      No undo entry is pushed during the drag.
    * ``on_ended``: call :meth:`PrimTransformModel.on_drag_ended` which
      pushes one :class:`BatchTransformCommand` per affected prim into
      the group and closes it. A single ``Ctrl+Z`` reverts the entire
      rotation.

    Guards: if ``on_drag_start`` raises (typically ``AttributeError`` from
    a ``None`` adapter), the gesture goes inert for the rest of the drag
    so subsequent callbacks become no-ops — same shape as the translate
    gesture.
    """

    _UNDO_LABEL = "Rotate Prims"

    def __init__(
        self,
        model: Any,
        axis: Tuple[float, float, float],
        mouse_button: int = _MOUSE_LEFT,
        modifiers: int = _NO_MODIFIERS,
    ) -> None:
        length = math.sqrt(axis[0] ** 2 + axis[1] ** 2 + axis[2] ** 2)
        if length == 0.0:
            raise ValueError("axis vector must be non-zero")
        self._axis: Tuple[float, float, float] = (
            axis[0] / length,
            axis[1] / length,
            axis[2] / length,
        )
        self._model = model
        self._active: bool = False
        # See the twin ``_drag_ended_this_cycle`` latch in
        # :class:`ovwidgets.viewport.translate_gizmo.PrimTranslateChangedGesture`.
        self._drag_ended_this_cycle: bool = False
        self._start_angle: float = 0.0
        self._delta_angle: float = 0.0
        # Subclass the virtual methods (not the ctor kwargs path) — see
        # ``ovwidgets.viewport.translate_gizmo.PrimTranslateChangedGesture`` for
        # the full rationale.
        super().__init__(mouse_button=mouse_button, modifiers=modifiers)

    def on_began(self) -> None:  # type: ignore[override]
        self._on_began()

    def on_changed(self) -> None:  # type: ignore[override]
        self._on_changed()

    def on_ended(self) -> None:  # type: ignore[override]
        self._on_ended()

    @property
    def axis(self) -> Tuple[float, float, float]:
        return self._axis

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def accumulated_angle(self) -> float:
        """Signed rotation angle accumulated since ``on_began``, in radians."""
        return self._delta_angle

    @staticmethod
    def _payload_angle(sender: Any, self_: "PrimRotateChangedGesture") -> float | None:
        """Pull ``gesture_payload.angle`` from sender, ``self_.sender`` or self_.

        The method-override dispatch path surfaces the shape as
        ``self.sender``; the legacy ``set_on_*_fn`` callback passed it as
        a positional arg; direct test invocations provide neither. Try
        each in turn.
        """
        shape = sender if sender is not None else getattr(self_, "sender", None)
        payload = getattr(shape, "gesture_payload", None) if shape is not None else None
        if payload is None:
            payload = getattr(self_, "gesture_payload", None)
        if payload is None:
            return None
        angle = getattr(payload, "angle", None)
        if angle is None:
            return None
        return float(angle)

    def _on_began(self, sender: Any = None) -> None:
        self._drag_ended_this_cycle = False
        paths = getattr(self._model, "_selected_paths", None)
        if not paths:
            self._active = False
            return
        angle = self._payload_angle(sender, self)
        self._start_angle = angle if angle is not None else 0.0
        self._delta_angle = 0.0
        try:
            self._model.on_drag_start(label=self._UNDO_LABEL)
        except Exception:
            self._active = False
            return
        self._active = True

    def _on_changed(self, sender: Any = None) -> None:
        if not self._active:
            return
        angle = self._payload_angle(sender, self)
        if angle is None:
            return
        self._delta_angle = angle - self._start_angle
        try:
            self._model.on_drag_rotated(self._axis, self._delta_angle)
        except Exception:
            # A bad adapter mid-drag must not crash the gesture; on_ended
            # still closes the undo group cleanly.
            pass

    def _on_ended(self, sender: Any = None) -> None:
        if not self._active:
            return
        self._active = False
        self._drag_ended_this_cycle = True
        try:
            self._model.on_drag_ended()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Geometry builder
# ---------------------------------------------------------------------------


class RotateGizmoHandles:
    """Bundle returned by :func:`build_rotate_gizmo`.

    Carries references to each ring and its gestures so callers (and tests)
    can introspect geometry and drive the gesture callbacks directly in
    headless environments. Attribute order matches ``_AXES`` (X, Y, Z).
    """

    def __init__(
        self,
        rings: List[Any],
        drag_gestures: List[PrimRotateChangedGesture],
        hover_gestures: List[HighlightGesture],
    ) -> None:
        self.rings = rings
        self.drag_gestures = drag_gestures
        self.hover_gestures = hover_gestures

    def gesture_for_axis(self, name: str) -> PrimRotateChangedGesture:
        """Look up a drag gesture by axis name (``"x"``, ``"y"``, ``"z"``)."""
        idx = {"x": 0, "y": 1, "z": 2}[name.lower()]
        return self.drag_gestures[idx]


def build_rotate_gizmo(
    model: Any,
    drag_gestures: Optional[List[PrimRotateChangedGesture]] = None,
    hover_gestures: Optional[List[HighlightGesture]] = None,
) -> RotateGizmoHandles:
    """Emit the rotate gizmo into the current ``sc.Transform`` scope.

    Must be called inside an ``sc.SceneView.scene`` (or enclosing
    ``sc.Transform``) context block. Returns a :class:`RotateGizmoHandles`
    bundle so tests can verify the emitted rings and drive their gestures
    without a real mouse.

    ``drag_gestures`` / ``hover_gestures`` are optional pre-built gestures
    reused across rebuilds to keep drags stable — see the note in
    :func:`~ovwidgets.viewport.translate_gizmo.build_translate_gizmo`.

    Each axis produces one ``sc.Arc`` wireframe circle of unit radius
    perpendicular to that axis, carrying one :class:`PrimRotateChangedGesture`
    and one :class:`HighlightGesture`.
    """
    rings: List[Any] = []
    drags: List[PrimRotateChangedGesture] = []
    hovers: List[HighlightGesture] = []

    for i, (_name, axis, base_color, highlight_color, arc_axis_idx) in enumerate(_AXES):
        if drag_gestures is not None and i < len(drag_gestures):
            drag = drag_gestures[i]
        else:
            drag = PrimRotateChangedGesture(model=model, axis=axis)
        if hover_gestures is not None and i < len(hover_gestures):
            hover = hover_gestures[i]
            hover._shapes = []
        else:
            hover = HighlightGesture(
                shapes=[],
                base_color=base_color,
                highlight_color=highlight_color,
            )
        ring = sc.Arc(
            RING_RADIUS,
            color=base_color,
            thickness=RING_THICKNESS,
            intersection_thickness=RING_INTERSECTION_THICKNESS,
            axis=arc_axis_idx,
            wireframe=True,
            sector=False,
            gestures=[drag, hover],
        )
        hover.add_shape(ring)
        rings.append(ring)
        drags.append(drag)
        hovers.append(hover)

    return RotateGizmoHandles(
        rings=rings, drag_gestures=drags, hover_gestures=hovers,
    )

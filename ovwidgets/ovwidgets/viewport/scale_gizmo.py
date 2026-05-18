# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Scale gizmo — axis cubes + uniform center cube with drag + hover highlight.

Step C.4 of the viewport behavior. Mirrors :mod:`translate_gizmo`
and :mod:`rotate_gizmo`: geometry builder, per-handle drag gesture, hover
highlight reuse, bundle returned to the parent
:class:`~ovwidgets.viewport.transform_manipulator.TransformManipulator`.

Three responsibilities:

1. **Geometry** — :func:`build_scale_gizmo` emits four handles:

   * Three axis handles (X / Y / Z): an ``sc.Line`` shaft from origin to
     unit vector along the axis plus a small ``sc.PolygonMesh`` solid
     cube at the shaft endpoint. The line is the pickable target (the
     cube is visual-only); hover highlights both.
   * One uniform handle at the origin: an ``sc.PolygonMesh`` solid cube
     in neutral grey, with a slightly-larger transparent ``sc.Rectangle``
     on top that carries the drag + hover gestures.

2. **Drag math** — :class:`PrimScaleChangedGesture` converts the frame's
   world-space ``gesture_payload.moved`` delta into a scalar scale factor
   and hands ``(axis_mask, factor)`` to
   :meth:`~ovwidgets.viewport.prim_transform_model.PrimTransformModel.on_drag_scaled`.

3. **Highlight** — reuses :class:`~ovwidgets.viewport.translate_gizmo.HighlightGesture`;
   the shared ``_apply`` handles both ``.color`` (Line, Rectangle) and
   per-vertex ``.colors`` (PolygonMesh), so one hover gesture flashes the
   shaft and its cube tip together.

Scale math notes
----------------
A local-axis scale is a pre-multiplication in the row-major row-vector
convention: ``new_local = S @ initial_local``. That scales the upper-3×3
rows (the prim's local X / Y / Z axes) while leaving the translation row
(``initial[3]``) untouched — the prim scales about its own origin.
:meth:`PrimTransformModel.on_drag_scaled` performs the composition; the
gesture only computes the ``(axis_mask, factor)`` pair each frame.
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

# Uniform handle colour (centre cube). Neutral light grey so it doesn't
# compete with the red/green/blue axis cubes — matches Maya/Blender's
# convention for the "uniform scale" handle.
UNIFORM_COLOR: int = 0xFFBBBBBB
HIGHLIGHT_COLOR_UNIFORM: int = 0xFFE8E8E8

# Matches :data:`translate_gizmo.SHAFT_LENGTH` — the axis cube sits at the
# tip of a unit-length shaft so the translate / scale tools read as the
# same gizmo with different caps.
SHAFT_LENGTH: float = 1.0

# Shaft line visuals. Thin pixel thickness = refined look against a
# ray-traced background; wide intersection thickness = forgiving picking.
SHAFT_THICKNESS: float = 2.0
SHAFT_INTERSECTION_THICKNESS: float = 10.0

# Cube handle half-edge in gizmo-local space. Small and elegant — per
# Victor's directive, "cube handles must be small, NOT chunky". At the
# 0.05 GIZMO_SIZE_SCALE this is ~0.4% of viewport, in line with the
# translate cone cap (``CONE_TIP_RADIUS = 0.06``).
CUBE_HALF: float = 0.07

# Uniform handle is slightly smaller so it reads as a distinct element
# when the gizmo is viewed from a 3/4 angle (otherwise it'd merge
# visually with the three axis cubes that emerge from the same origin).
UNIFORM_CUBE_HALF: float = 0.06

# Rectangle picking target covering the uniform cube. Oversized relative
# to the visible cube so the user isn't pixel-hunting. Transparent
# ``0x00000000`` color — invisible, still pickable.
UNIFORM_HIT_HALF: float = 0.11
_TRANSPARENT: int = 0x00000000

# Floor on the applied scale factor. Negative or near-zero factors produce
# mirrored / degenerate geometry that ovrtx can't render cleanly and that
# most users won't want during a drag. Matches Maya's "clamp to 0.01"
# behaviour on uniform scale drags.
MIN_SCALE_FACTOR: float = 0.01

# Mouse buttons + modifiers. Left-click-drag, no modifiers — matches the
# translate and rotate gizmos and every DCC convention.
_MOUSE_LEFT: int = 0
_NO_MODIFIERS: int = 0

# ---------------------------------------------------------------------------
# Axis table
# ---------------------------------------------------------------------------

# ``(name, axis_vec, base_color, highlight_color)`` per axis handle. The
# axis vec is both the scaling direction (one of (1,0,0), (0,1,0),
# (0,0,1)) and the projection axis used to turn the frame's world-space
# ``moved`` delta into a signed scalar.
_AXES: Tuple[Tuple[str, Tuple[float, float, float], int, int], ...] = (
    ("x", (1.0, 0.0, 0.0), AXIS_COLOR_X, HIGHLIGHT_COLOR_X),
    ("y", (0.0, 1.0, 0.0), AXIS_COLOR_Y, HIGHLIGHT_COLOR_Y),
    ("z", (0.0, 0.0, 1.0), AXIS_COLOR_Z, HIGHLIGHT_COLOR_Z),
)


# ---------------------------------------------------------------------------
# Cube mesh builder
# ---------------------------------------------------------------------------


# Canonical 8-vertex cube topology. Faces are quads (``vertex_counts =
# [4]*6``); indices wind counter-clockwise when viewed from outside so
# ovui's default culling keeps the solid fill. Defined once at module
# scope so ``build_scale_gizmo`` doesn't re-create them four times per
# build.
_CUBE_FACE_COUNTS: List[int] = [4] * 6
_CUBE_FACE_INDICES: List[int] = [
    0, 3, 2, 1,  # -Z face
    4, 5, 6, 7,  # +Z face
    0, 1, 5, 4,  # -Y face
    3, 7, 6, 2,  # +Y face
    0, 4, 7, 3,  # -X face
    1, 2, 6, 5,  # +X face
]


def _cube_positions(half: float) -> List[Tuple[float, float, float]]:
    """Eight corner positions for a cube of half-edge ``half`` centred at origin."""
    h = float(half)
    return [
        (-h, -h, -h),
        ( h, -h, -h),
        ( h,  h, -h),
        (-h,  h, -h),
        (-h, -h,  h),
        ( h, -h,  h),
        ( h,  h,  h),
        (-h,  h,  h),
    ]


def _make_cube_mesh(half: float, color: int) -> Any:
    """Emit an ``sc.PolygonMesh`` solid cube of half-edge ``half`` into the current transform scope."""
    positions = _cube_positions(half)
    return sc.PolygonMesh(
        positions,
        [color] * len(_CUBE_FACE_INDICES),
        _CUBE_FACE_COUNTS,
        _CUBE_FACE_INDICES,
        wireframe=False,
    )


# ---------------------------------------------------------------------------
# Transform helpers (flat 16-float row-major matrices)
# ---------------------------------------------------------------------------


def _translation_matrix_flat(tx: float, ty: float, tz: float) -> List[float]:
    """Flat 16-float row-major translation matrix — ``sc.Transform`` expects this form."""
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
         tx,  ty,  tz, 1.0,
    ]


# ---------------------------------------------------------------------------
# Gesture
# ---------------------------------------------------------------------------


class PrimScaleChangedGesture(TransformGestureBase):
    """Axis-constrained or uniform scale drag gesture.

    Reads the frame's world-space ``gesture_payload.moved`` delta,
    projects it onto the gesture's projection axis, accumulates over
    the drag, converts accumulated length into a scale factor, and
    hands ``(axis_mask, factor)`` to
    :meth:`~ovwidgets.viewport.prim_transform_model.PrimTransformModel.on_drag_scaled`.

    Parameters
    ----------
    model:
        The :class:`PrimTransformModel` that owns the selection.
    axis:
        Scale-axis mask. For axis-constrained handles pass a unit axis
        like ``(1, 0, 0)``; for the uniform handle pass ``(1, 1, 1)``.
        Model-side, any component ``!= 0`` receives the factor; other
        components stay at 1.0.
    projection_axis:
        Direction in world space onto which the mouse delta is
        projected to build the scalar drag signal. For axis-constrained
        this is the axis itself; for uniform a diagonal world direction
        (default: ``(1, 1, 0)/√2``) so "drag right or up = scale up"
        feels natural regardless of which axis of the uniform cube the
        user grabs.
    uniform:
        ``True`` for the centre handle. Affects the gesture's advertised
        :attr:`is_uniform` flag and the default projection axis; the
        same math runs either way.

    Lifecycle
    ---------
    * ``on_began``: if the model has a selection, call
      :meth:`PrimTransformModel.on_drag_start` with label ``"Scale
      Prims"`` to open an undo group. Resets the accumulated length.
    * ``on_changed``: read ``moved``, project onto the projection axis,
      add to the accumulated length, compute
      ``factor = 1 + accumulated / SHAFT_LENGTH`` (clamped at
      :data:`MIN_SCALE_FACTOR`), and call
      :meth:`PrimTransformModel.on_drag_scaled(axis, factor)`.
    * ``on_ended``: call :meth:`PrimTransformModel.on_drag_ended` which
      pushes one :class:`BatchTransformCommand` per affected prim into
      the open undo group and closes it. A single ``Ctrl+Z`` reverts
      the entire scale operation.
    """

    _UNDO_LABEL = "Scale Prims"

    def __init__(
        self,
        model: Any,
        axis: Tuple[float, float, float],
        projection_axis: Optional[Tuple[float, float, float]] = None,
        uniform: bool = False,
        mouse_button: int = _MOUSE_LEFT,
        modifiers: int = _NO_MODIFIERS,
    ) -> None:
        axis_length = math.sqrt(axis[0] ** 2 + axis[1] ** 2 + axis[2] ** 2)
        if axis_length == 0.0:
            raise ValueError("axis vector must be non-zero")
        self._axis: Tuple[float, float, float] = (
            axis[0], axis[1], axis[2],
        )
        # Projection axis defaults: unit direction for constrained handles,
        # diagonal for uniform so any right/up mouse motion scales up.
        if projection_axis is None:
            if uniform:
                inv = 1.0 / math.sqrt(2.0)
                proj = (inv, inv, 0.0)
            else:
                proj = (axis[0] / axis_length, axis[1] / axis_length, axis[2] / axis_length)
        else:
            proj_len = math.sqrt(
                projection_axis[0] ** 2
                + projection_axis[1] ** 2
                + projection_axis[2] ** 2
            )
            if proj_len == 0.0:
                raise ValueError("projection_axis must be non-zero")
            proj = (
                projection_axis[0] / proj_len,
                projection_axis[1] / proj_len,
                projection_axis[2] / proj_len,
            )
        self._projection_axis: Tuple[float, float, float] = proj
        self._uniform: bool = bool(uniform)
        self._model = model
        self._active: bool = False
        # See the twin ``_drag_ended_this_cycle`` latch in
        # :class:`ovwidgets.viewport.translate_gizmo.PrimTranslateChangedGesture`.
        self._drag_ended_this_cycle: bool = False
        self._accumulated: float = 0.0
        self._drag_start_point: Optional[Tuple[float, float, float]] = None
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
    def projection_axis(self) -> Tuple[float, float, float]:
        return self._projection_axis

    @property
    def is_uniform(self) -> bool:
        return self._uniform

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def accumulated_length(self) -> float:
        """Signed world-space length accumulated along ``projection_axis``. Exposed for tests."""
        return self._accumulated

    @property
    def current_factor(self) -> float:
        """The scale factor that would be applied on the current frame.

        Mirrors the math in ``_on_changed``; exposed so tests can assert
        the factor without round-tripping through the model.
        """
        return max(
            MIN_SCALE_FACTOR,
            1.0 + self._accumulated / SHAFT_LENGTH,
        )

    def _on_began(self, sender: Any = None) -> None:
        self._drag_ended_this_cycle = False
        paths = getattr(self._model, "_selected_paths", None)
        if not paths:
            self._active = False
            return
        self._accumulated = 0.0
        self._drag_start_point = None
        try:
            self._model.on_drag_start(label=self._UNDO_LABEL)
        except Exception:
            # Pre-adapter-wired model (unit tests, pre-C.5 scaffolding).
            # Stay inert — nothing to close at drag end.
            self._active = False
            return
        self._active = True

    def _on_changed(self, sender: Any = None) -> None:
        if not self._active:
            return
        shape = sender if sender is not None else getattr(self, "sender", None)
        payload = getattr(shape, "gesture_payload", None) if shape is not None else None
        if payload is None:
            payload = getattr(self, "gesture_payload", None)
        if payload is None:
            return
        # Use ``line_closest_point`` for axis handles — stable against
        # the frame-to-frame snap-back on ``moved`` (see the note in
        # :class:`ovwidgets.viewport.translate_gizmo.PrimTranslateChangedGesture`).
        # The uniform handle is on a Rectangle, which doesn't surface a
        # line closest-point; fall back to the ``moved`` delta in that
        # case (accumulation is tolerant of occasional zero frames for
        # the rectangle handle's drag).
        closest = getattr(payload, "line_closest_point", None)
        if closest is None:
            closest = getattr(payload, "ray_closest_point", None)
        if closest is not None:
            if hasattr(closest, "x"):
                cx, cy, cz = float(closest.x), float(closest.y), float(closest.z)
            else:
                cx, cy, cz = float(closest[0]), float(closest[1]), float(closest[2])
            if self._drag_start_point is None:
                self._drag_start_point = (cx, cy, cz)
                return
            if (
                abs(cx - self._drag_start_point[0]) < 1e-6
                and abs(cy - self._drag_start_point[1]) < 1e-6
                and abs(cz - self._drag_start_point[2]) < 1e-6
            ):
                return
            dx = cx - self._drag_start_point[0]
            dy = cy - self._drag_start_point[1]
            dz = cz - self._drag_start_point[2]
            px, py, pz = self._projection_axis
            self._accumulated = dx * px + dy * py + dz * pz
        else:
            moved = getattr(payload, "moved", None)
            if moved is None:
                return
            if hasattr(moved, "x"):
                mx, my, mz = float(moved.x), float(moved.y), float(moved.z)
            else:
                mx, my, mz = float(moved[0]), float(moved[1]), float(moved[2])
            px, py, pz = self._projection_axis
            self._accumulated += mx * px + my * py + mz * pz
        factor = max(
            MIN_SCALE_FACTOR,
            1.0 + self._accumulated / SHAFT_LENGTH,
        )
        try:
            self._model.on_drag_scaled(self._axis, factor)
        except Exception:
            # A bad adapter mid-drag must not crash the gesture; on_ended
            # still closes the undo group cleanly.
            pass

    def _on_ended(self, sender: Any = None) -> None:
        if not self._active:
            return
        self._active = False
        self._drag_start_point = None
        self._drag_ended_this_cycle = True
        try:
            self._model.on_drag_ended()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Geometry builder
# ---------------------------------------------------------------------------


class ScaleGizmoHandles:
    """Bundle returned by :func:`build_scale_gizmo`.

    Carries references to each shape and gesture so callers (QA
    harnesses, tests) can introspect the emitted geometry and drive
    gestures without a real mouse. Axis attributes are ordered X, Y, Z;
    ``uniform_*`` fields hold the centre handle.
    """

    def __init__(
        self,
        shafts: List[Any],
        cubes: List[Any],
        uniform_cube: Any,
        uniform_hit: Any,
        drag_gestures: List[PrimScaleChangedGesture],
        hover_gestures: List[HighlightGesture],
        uniform_drag: PrimScaleChangedGesture,
        uniform_hover: HighlightGesture,
    ) -> None:
        self.shafts = shafts
        self.cubes = cubes
        self.uniform_cube = uniform_cube
        self.uniform_hit = uniform_hit
        self.drag_gestures = drag_gestures
        self.hover_gestures = hover_gestures
        self.uniform_drag = uniform_drag
        self.uniform_hover = uniform_hover

    def gesture_for_axis(self, name: str) -> PrimScaleChangedGesture:
        """Look up an axis drag gesture by name (``"x"``, ``"y"``, ``"z"``)."""
        idx = {"x": 0, "y": 1, "z": 2}[name.lower()]
        return self.drag_gestures[idx]


def build_scale_gizmo(
    model: Any,
    drag_gestures: Optional[List[PrimScaleChangedGesture]] = None,
    hover_gestures: Optional[List[HighlightGesture]] = None,
    uniform_drag: Optional[PrimScaleChangedGesture] = None,
    uniform_hover: Optional[HighlightGesture] = None,
) -> ScaleGizmoHandles:
    """Emit the scale gizmo into the current ``sc.Transform`` scope.

    Must be called inside an ``sc.SceneView.scene`` (or enclosing
    ``sc.Transform``) context block. Returns a :class:`ScaleGizmoHandles`
    bundle so tests and QA harnesses can drive the gestures directly.

    Optional ``drag_gestures`` / ``hover_gestures`` / ``uniform_drag`` /
    ``uniform_hover`` let the parent manipulator pass in pre-built gesture
    instances so drag state survives a per-frame rebuild — same rationale
    as :func:`~ovwidgets.viewport.translate_gizmo.build_translate_gizmo`.

    Geometry layout
    ---------------
    * For each axis: an ``sc.Line`` shaft from origin to unit vector
      along the axis carrying drag + hover gestures, plus a small
      ``sc.PolygonMesh`` solid cube at the tip (visual only, non-
      interactive; hover highlight attaches to it so the cube flashes
      with the shaft).
    * At origin: an ``sc.PolygonMesh`` solid cube in neutral grey plus a
      slightly-larger transparent ``sc.Rectangle`` on top that carries
      the uniform drag + hover gestures.
    """
    shafts: List[Any] = []
    cubes: List[Any] = []
    drags: List[PrimScaleChangedGesture] = []
    hovers: List[HighlightGesture] = []

    for i, (_name, axis, base_color, highlight_color) in enumerate(_AXES):
        if drag_gestures is not None and i < len(drag_gestures):
            drag = drag_gestures[i]
        else:
            drag = PrimScaleChangedGesture(model=model, axis=axis)
        # Draw the cube at the shaft tip first so the hover gesture can
        # attach to both shapes at construction time.
        tx = axis[0] * SHAFT_LENGTH
        ty = axis[1] * SHAFT_LENGTH
        tz = axis[2] * SHAFT_LENGTH
        with sc.Transform(transform=_translation_matrix_flat(tx, ty, tz)):
            cube = _make_cube_mesh(CUBE_HALF, base_color)
        if hover_gestures is not None and i < len(hover_gestures):
            hover = hover_gestures[i]
            hover._shapes = [cube]
        else:
            hover = HighlightGesture(
                shapes=[cube],
                base_color=base_color,
                highlight_color=highlight_color,
            )
        shaft = sc.Line(
            [0.0, 0.0, 0.0],
            [tx, ty, tz],
            color=base_color,
            thickness=SHAFT_THICKNESS,
            intersection_thickness=SHAFT_INTERSECTION_THICKNESS,
            gestures=[drag, hover],
        )
        hover.add_shape(shaft)
        shafts.append(shaft)
        cubes.append(cube)
        drags.append(drag)
        hovers.append(hover)

    # Uniform handle — centre cube + transparent hit-target rectangle.
    uniform_cube = _make_cube_mesh(UNIFORM_CUBE_HALF, UNIFORM_COLOR)
    if uniform_drag is None:
        uniform_drag = PrimScaleChangedGesture(
            model=model, axis=(1.0, 1.0, 1.0), uniform=True,
        )
    if uniform_hover is None:
        uniform_hover = HighlightGesture(
            shapes=[uniform_cube],
            base_color=UNIFORM_COLOR,
            highlight_color=HIGHLIGHT_COLOR_UNIFORM,
        )
    else:
        uniform_hover._shapes = [uniform_cube]
    uniform_hit = sc.Rectangle(
        width=UNIFORM_HIT_HALF * 2.0,
        height=UNIFORM_HIT_HALF * 2.0,
        color=_TRANSPARENT,
        wireframe=False,
        gestures=[uniform_drag, uniform_hover],
    )

    return ScaleGizmoHandles(
        shafts=shafts,
        cubes=cubes,
        uniform_cube=uniform_cube,
        uniform_hit=uniform_hit,
        drag_gestures=drags,
        hover_gestures=hovers,
        uniform_drag=uniform_drag,
        uniform_hover=uniform_hover,
    )

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Translate gizmo — axis arrows with drag + hover highlight.

Step C.2 of the viewport behavior. Replaces the C.1 placeholder lines
with real draggable axis arrows. Three responsibilities:

1. **Geometry** — :func:`build_translate_gizmo` draws three axis shafts
   (``sc.Line``) and three pointed cone arrowheads
   (``sc.PolygonMesh``). Each shaft owns a
   :class:`PrimTranslateChangedGesture` (drag) and a :class:`HighlightGesture`
   (hover).
2. **Drag math** — :class:`PrimTranslateChangedGesture` projects the frame's
   world-space mouse delta onto the shaft's axis, accumulates, and hands the
   resulting translation to
   :meth:`~ovui_widgets.viewport.prim_transform_model.PrimTransformModel.on_drag_moved`.
   The model handles the USD write-through and undo bracketing.
3. **Highlight** — :class:`HighlightGesture` swaps the shaft+cone colour for a
   brighter variant while the mouse hovers the shaft, so the user can see which
   axis they're about to grab.

The gizmo itself is drawn in gizmo-local space (unit-length axes). The parent
:class:`~ovui_widgets.viewport.transform_manipulator.TransformManipulator` wraps this
geometry in translate-to-pivot → uniform scale transforms so it appears at the
selected prim at a constant screen size.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any, Callable, List, Optional, Tuple

from omni.ui_scene import scene as sc

from ovui_widgets.viewport.transform_manipulator import (
    AXIS_COLOR_X,
    AXIS_COLOR_Y,
    AXIS_COLOR_Z,
    TransformGestureBase,
)

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

# Brighter variants shown while the mouse hovers the handle. Derived by
# lightening the base axis colour toward white — keeps the red/green/blue
# identity readable while still flagging "you're hovering this one".
HIGHLIGHT_COLOR_X: int = 0xFF8888FF  # brighter red
HIGHLIGHT_COLOR_Y: int = 0xFFA8D8A8  # brighter green
HIGHLIGHT_COLOR_Z: int = 0xFFD8B488  # brighter blue

# Axis shaft: unit length in gizmo-local space. The parent
# TransformManipulator applies the uniform screen-size scale (see
# GIZMO_SIZE_SCALE), so the world-space shaft is that many units long.
# Matches the viewport behavior
SHAFT_LENGTH: float = 1.0

# Line thickness in pixels. Thin for a refined, professional look against
# a ray-traced background — compare Maya/Blender manipulator.transform.
# The intersection region stays generous so drag picking is forgiving even
# with a thin visual.
SHAFT_THICKNESS: float = 2.0
SHAFT_INTERSECTION_THICKNESS: float = 10.0

# Cone base radius (gizmo-local). The pointed cone extends beyond the shaft
# endpoint, so the visible terminal shape is an arrow tip rather than a round
# endpoint dot.
CONE_TIP_RADIUS: float = 0.06
CONE_TIP_LENGTH: float = 0.18
CONE_TIP_SEGMENTS: int = 4

# Mouse buttons + modifiers. Left-click-drag, no modifiers — matches the
# convention of every transform gizmo in every DCC we care about.
_MOUSE_LEFT: int = 0
_NO_MODIFIERS: int = 0

# Unit axes in gizmo-local space. The triple ``(name, axis_vec, base_color,
# highlight_color)`` drives :func:`build_translate_gizmo`.
_AXES: Tuple[Tuple[str, Tuple[float, float, float], int, int], ...] = (
    ("x", (1.0, 0.0, 0.0), AXIS_COLOR_X, HIGHLIGHT_COLOR_X),
    ("y", (0.0, 1.0, 0.0), AXIS_COLOR_Y, HIGHLIGHT_COLOR_Y),
    ("z", (0.0, 0.0, 1.0), AXIS_COLOR_Z, HIGHLIGHT_COLOR_Z),
)


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------


def _project_onto_axis(
    dx: float, dy: float, dz: float, axis: Tuple[float, float, float]
) -> Tuple[float, float, float]:
    """Project ``(dx, dy, dz)`` onto the unit vector ``axis``.

    Returns a vector of length ``|axis · d|`` aligned with ``axis``. Used to
    strip any off-axis drift out of ``sc.Line.gesture_payload.moved`` — the
    payload is already aligned with the line, but numerical noise from the
    closest-point solver can leak a few micrometres into the other two axes.
    Projecting kills it and guarantees exact axis constraint.
    """
    ax, ay, az = axis
    dot = dx * ax + dy * ay + dz * az
    return (dot * ax, dot * ay, dot * az)


def _axis_delta_matrix(dx: float, dy: float, dz: float) -> List[List[float]]:
    """Return a 4×4 row-major translation matrix: ``initial × delta → initial + d``.

    ``PrimTransformModel.on_drag_moved`` multiplies this matrix from the right
    with each prim's initial local transform, so the translation component
    lives in row 3, columns 0..2 (row-major convention used throughout
    ``ovgear``).
    """
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [dx,  dy,  dz,  1.0],
    ]


def _perpendicular_basis(
    axis: Tuple[float, float, float],
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """Return two unit vectors perpendicular to one of the cardinal axes."""
    ax, ay, az = axis
    if abs(ax) >= abs(ay) and abs(ax) >= abs(az):
        return (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    if abs(ay) >= abs(ax) and abs(ay) >= abs(az):
        return (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    return (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)


def _cone_positions(axis: Tuple[float, float, float]) -> List[Tuple[float, float, float]]:
    """Return a pointed cone arrowhead aligned to ``axis`` in gizmo-local space."""
    ax, ay, az = axis
    u, v = _perpendicular_basis(axis)
    base = (ax * SHAFT_LENGTH, ay * SHAFT_LENGTH, az * SHAFT_LENGTH)
    tip = (
        ax * (SHAFT_LENGTH + CONE_TIP_LENGTH),
        ay * (SHAFT_LENGTH + CONE_TIP_LENGTH),
        az * (SHAFT_LENGTH + CONE_TIP_LENGTH),
    )
    positions: List[Tuple[float, float, float]] = [tip]
    for i in range(CONE_TIP_SEGMENTS):
        angle = (2.0 * math.pi * i / CONE_TIP_SEGMENTS) + (math.pi / 4.0)
        ca = math.cos(angle) * CONE_TIP_RADIUS
        sa = math.sin(angle) * CONE_TIP_RADIUS
        positions.append((
            base[0] + u[0] * ca + v[0] * sa,
            base[1] + u[1] * ca + v[1] * sa,
            base[2] + u[2] * ca + v[2] * sa,
        ))
    return positions


_CONE_FACE_COUNTS: List[int] = [3] * CONE_TIP_SEGMENTS + [CONE_TIP_SEGMENTS]
_CONE_FACE_INDICES: List[int] = [
    idx
    for i in range(CONE_TIP_SEGMENTS)
    for idx in (0, 1 + i, 1 + ((i + 1) % CONE_TIP_SEGMENTS))
] + [1 + i for i in reversed(range(CONE_TIP_SEGMENTS))]


def _make_cone_mesh(axis: Tuple[float, float, float], color: int) -> Any:
    """Emit a solid pointed cone arrowhead into the current scene scope."""
    positions = _cone_positions(axis)
    return sc.PolygonMesh(
        positions,
        [color] * len(_CONE_FACE_INDICES),
        _CONE_FACE_COUNTS,
        _CONE_FACE_INDICES,
        wireframe=False,
    )


# ---------------------------------------------------------------------------
# Gestures
# ---------------------------------------------------------------------------


class PrimTranslateChangedGesture(TransformGestureBase):
    """Axis-constrained drag gesture.

    Pipes incremental world-space deltas from ``sc.Line.gesture_payload.moved``
    into :class:`~ovui_widgets.viewport.prim_transform_model.PrimTransformModel`.

    Lifecycle
    ---------
    * ``on_began``: if the model has a non-empty selection, call
      :meth:`PrimTransformModel.on_drag_start` which opens an undo group
      via the stage adapter (``stage.begin_undo_group("Move Prims")`` →
      ``UndoManager.begin_group``). The frame's accumulated delta resets to
      zero.
    * ``on_changed``: read ``sender.gesture_payload.moved`` (world-space
      incremental delta along the line since the previous intersect), project
      onto the stored axis to kill off-axis noise, add it to the running
      accumulated delta, and call
      :meth:`PrimTransformModel.on_drag_moved` with the resulting 4×4
      translation matrix. No undo entry is pushed during the drag.
    * ``on_ended``: call :meth:`PrimTransformModel.on_drag_ended`, which
      pushes one :class:`BatchTransformCommand` per affected prim into the
      existing undo group and closes the group (via the stage adapter). A
      single ``Ctrl+Z`` therefore reverts the entire drag.

    The gesture self-guards against a missing selection or missing adapter:
    if ``model.on_drag_start`` raises (typically ``AttributeError`` from a
    ``None`` adapter attribute), the gesture goes inert for the rest of the
    drag so the remaining ``on_changed``/``on_ended`` calls become no-ops.
    """

    def __init__(
        self,
        model: Any,
        axis: Tuple[float, float, float],
        mouse_button: int = _MOUSE_LEFT,
        modifiers: int = _NO_MODIFIERS,
        generation: Any = None,
    ) -> None:
        # ``super().__init__`` MUST be called first. ``sc.DragGesture``
        # is a pybind11 class and its ``trampoline`` routing for virtual
        # ``on_began`` / ``on_changed`` / ``on_ended`` overrides is only
        # wired once the C++ side has been fully initialised. Mutating
        # Python attributes before ``super().__init__`` leaves the
        # subclass in a state where ``on_began`` fires but ``on_changed``
        # / ``on_ended`` never route back to Python — which is exactly
        # the "drag only begins, never moves the prim" symptom.
        super().__init__(mouse_button=mouse_button, modifiers=modifiers)
        self._generation = generation
        length = math.sqrt(axis[0] ** 2 + axis[1] ** 2 + axis[2] ** 2)
        if length == 0.0:
            raise ValueError("axis vector must be non-zero")
        # Normalise up-front so we never have to again. Callers pass unit
        # axes already, but being defensive costs nothing.
        self._axis: Tuple[float, float, float] = (
            axis[0] / length,
            axis[1] / length,
            axis[2] / length,
        )
        self._model = model
        self._active: bool = False
        # Latch set by ``_on_ended`` so the pick gesture's guard in
        # :meth:`GizmoAwarePickManager.has_live_gizmo_drag` still
        # catches a just-completed drag when its ``_on_ended`` fires
        # after ours (the ordering isn't guaranteed — see the note in
        # :mod:`ovui_widgets.viewport.pick_gesture`).
        self._drag_ended_this_cycle: bool = False
        self._accumulated: List[float] = [0.0, 0.0, 0.0]
        # Drag baseline: the world-space closest-point on the shaft at
        # ``on_began``. ``_on_changed`` computes total displacement as
        # ``current_closest - baseline`` so a stationary mouse yields
        # zero rather than accumulating the ±300 sign-flip observed on
        # ``LineGesturePayload.moved``.
        self._drag_start_point: Optional[Tuple[float, float, float]] = None

    # The ``omni.ui_scene`` gesture dispatcher binds these hooks as C++
    # virtual methods on the subclass. Subclassing ``sc.DragGesture`` and
    # overriding them here is the pattern validated in
    # ``~/dev/ovui/tests/scene/test_interaction.py`` (TestInteraction.
    # test_drag_begin_changed_ended_sequence) — ``set_on_*_fn`` setters
    # and ``__init__`` kwargs fired ``on_began`` for us but silently
    # dropped ``on_changed`` / ``on_ended``, which left drags captured
    # at mouse-down and never released (the reported "drag only selects"
    # behaviour). The hooks take no arguments; we read the drag
    # payload off ``self.gesture_payload`` when needed.

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
    def accumulated_delta(self) -> Tuple[float, float, float]:
        """World-space drag delta accumulated since ``on_began``. Exposed for tests."""
        return (self._accumulated[0], self._accumulated[1], self._accumulated[2])

    def begin_with_line_closest_point(self, point: Tuple[float, float, float]) -> bool:
        """Begin this real gesture from a streamed-input closest point.

        ``omni.ui_scene`` normally supplies ``LineGesturePayload`` after
        shape hit testing. The streamed viewport bridge has already chosen this
        real handle from the ovui-owned viewport geometry, so it forwards the
        same closest-point datum into the existing gesture/model lifecycle.
        """

        self._on_began()
        if not self._active:
            return False
        self._drag_start_point = (
            float(point[0]),
            float(point[1]),
            float(point[2]),
        )
        return True

    def update_with_line_closest_point(self, point: Tuple[float, float, float]) -> bool:
        """Advance this real gesture from a streamed-input closest point."""

        if not self._active:
            return False
        payload = SimpleNamespace(
            line_closest_point=(
                float(point[0]),
                float(point[1]),
                float(point[2]),
            )
        )
        self._on_changed(SimpleNamespace(gesture_payload=payload))
        return True

    def end_streamed_drag(self) -> bool:
        """End a streamed-input drag through the regular gesture commit path."""

        if not self._active:
            return False
        self._on_ended()
        return True

    def cancel_streamed_drag(self) -> bool:
        """Streamed-bridge alias of :meth:`cancel_active_drag`."""
        return self.cancel_active_drag()

    def _on_began(self, sender: Any = None) -> None:
        if self._generation is not None and not self._generation.effective:
            return
        # Clear the "drag just ended" latch at the start of every new
        # drag — the latch is a one-shot that suppresses the matching
        # pick gesture's mouse-up, not a permanent block.
        self._drag_ended_this_cycle = False
        paths = getattr(self._model, "_selected_paths", None)
        if not paths:
            self._active = False
            return
        self._accumulated = [0.0, 0.0, 0.0]
        # Reset the drag-start baseline; the first ``_on_changed`` will
        # capture the current closest-point, so total displacement starts
        # at zero.
        self._drag_start_point = None
        try:
            self._model.on_drag_start()
        except Exception:
            # Adapter not yet wired (pre-C.5 scaffolding, unit tests with a
            # bare model, etc.). Stay inert — nothing to commit at end.
            self._active = False
            return
        self._active = True

    def _on_changed(self, sender: Any = None) -> None:
        if self._generation is not None and not self._generation.effective:
            return
        if not self._active:
            return
        # Resolve the shape that owns the gesture payload. When the
        # subclassed ``on_changed`` method override fires, the event
        # dispatcher exposes the shape as ``self.sender``; the legacy
        # ``set_on_*_fn`` callback path passed it as a positional arg,
        # so we accept both for backward compat with existing tests.
        shape = sender if sender is not None else getattr(self, "sender", None)
        payload = getattr(shape, "gesture_payload", None) if shape is not None else None
        if payload is None:
            payload = getattr(self, "gesture_payload", None)
        if payload is None:
            return
        # ``LineGesturePayload`` exposes two 3-vectors of interest:
        # ``line_closest_point`` (absolute world-space closest point on
        # the shaft to the current mouse ray) and ``moved`` (per-frame
        # delta of that closest point). The absolute-point path is
        # preferred because ``moved`` oscillates on real mouse drags —
        # ``omni.ui_scene`` fires ``on_changed`` twice per mouse_drag
        # step (once for the moved mouse, once for the re-pressed
        # button state) and the two events alternate between the
        # current closest point and the drag-start point, so
        # accumulating ``moved`` cancels out. Tests that synthesise a
        # payload with only ``moved`` fall back to the accumulation
        # path, which is correct because the test harness never fires
        # a "snap back to baseline" event.
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
                # "Snap back to baseline" — a stale payload between real
                # mouse moves. Preserve the last good accumulator so the
                # USD write doesn't revert mid-drag.
                return
            dx = cx - self._drag_start_point[0]
            dy = cy - self._drag_start_point[1]
            dz = cz - self._drag_start_point[2]
            px, py, pz = _project_onto_axis(dx, dy, dz, self._axis)
            # Overwrite (not add) — ``dx/dy/dz`` is already cumulative
            # from drag start, so each frame's accumulator is the full
            # displacement, not an increment.
            self._accumulated[0] = px
            self._accumulated[1] = py
            self._accumulated[2] = pz
        else:
            moved = getattr(payload, "moved", None)
            if moved is None:
                return
            if hasattr(moved, "x"):
                mx, my, mz = float(moved.x), float(moved.y), float(moved.z)
            else:
                mx, my, mz = float(moved[0]), float(moved[1]), float(moved[2])
            px, py, pz = _project_onto_axis(mx, my, mz, self._axis)
            self._accumulated[0] += px
            self._accumulated[1] += py
            self._accumulated[2] += pz
        delta = _axis_delta_matrix(
            self._accumulated[0], self._accumulated[1], self._accumulated[2],
        )
        try:
            self._model.on_drag_moved(delta)
        except Exception:
            # A bad adapter must not crash the drag. Subsequent frames will
            # retry; on_ended will still close the undo group cleanly.
            pass

    def _on_ended(self, sender: Any = None) -> None:
        if self._generation is not None and not self._generation.effective:
            return
        if not self._active:
            return
        self._active = False
        self._drag_start_point = None
        # Latch for the pick gesture's guard — see ``__init__`` note.
        self._drag_ended_this_cycle = True
        try:
            self._model.on_drag_ended()
        except Exception:
            pass


class HighlightGesture(sc.HoverGesture):
    """Hover-driven colour swap for a translate handle.

    Omni ui-scene fires ``on_began`` on mouse-enter and ``on_ended`` on
    mouse-leave for a ``HoverGesture``. On enter we replace the attached
    shapes' colour with the supplied highlight; on leave we restore the
    baseline. One gesture can drive multiple shapes (the shaft line +
    the cone-tip arc) — callers pass both via ``shapes``.
    """

    def __init__(
        self,
        shapes: List[Any],
        base_color: int,
        highlight_color: int,
        on_state_change: Optional[Callable[[bool], None]] = None,
        generation: Any = None,
    ) -> None:
        self._generation = generation
        self._shapes: List[Any] = list(shapes)
        self._base_color = int(base_color)
        self._highlight_color = int(highlight_color)
        self._on_state_change = on_state_change
        self._hovered: bool = False
        # Subclass the virtual methods below rather than passing
        # ``on_began_fn`` / ``on_ended_fn``. The kwargs path fires the
        # first enter but not subsequent hovers (the user-reported
        # "hover blinks white once then stops"); the virtual-override
        # pattern matches ``~/dev/ovui/tests/scene/test_interaction.py``
        # ``test_hover_state_changes`` and delivers every enter / leave.
        super().__init__()

    def on_began(self) -> None:  # type: ignore[override]
        self._on_began()

    def on_ended(self) -> None:  # type: ignore[override]
        self._on_ended()

    @property
    def is_hovered(self) -> bool:
        return self._hovered

    def add_shape(self, shape: Any) -> None:
        """Attach an additional shape whose colour should swap with the shaft's.

        Used by :func:`build_translate_gizmo` to bind the arrow-tip cap
        after both shapes exist.
        """
        self._shapes.append(shape)

    def _apply(self, color: int) -> None:
        for shape in self._shapes:
            if shape is None:
                continue
            try:
                shape.color = color
                continue
            except (TypeError, ValueError, AttributeError):
                pass
            # ``sc.PolygonMesh`` has no ``.color`` — per-vertex ``colors``
            # instead. DrawBuffer consumes one color per face-vertex index,
            # not one per unique point, so keep the color array the same
            # length as ``vertex_indices`` to avoid undefined color reads.
            try:
                vertex_indices = getattr(shape, "vertex_indices", None)
                if vertex_indices is not None:
                    shape.colors = [color] * len(vertex_indices)
                    continue
                positions = getattr(shape, "positions", None)
                if positions is not None:
                    shape.colors = [color] * len(positions)
            except (TypeError, ValueError, AttributeError):
                pass

    def _on_began(self, sender: Any = None) -> None:
        if self._generation is not None and not self._generation.effective:
            return
        self._hovered = True
        self._apply(self._highlight_color)
        if self._on_state_change is not None:
            self._on_state_change(True)

    def _on_ended(self, sender: Any = None) -> None:
        if self._generation is not None and not self._generation.effective:
            return
        self._hovered = False
        self._apply(self._base_color)
        if self._on_state_change is not None:
            self._on_state_change(False)


# ---------------------------------------------------------------------------
# Geometry builder
# ---------------------------------------------------------------------------


class TranslateGizmoHandles:
    """Bundle returned by :func:`build_translate_gizmo`.

    Carries references to each shape/gesture so callers (and tests) can
    introspect geometry and drive the gesture callbacks directly in headless
    environments. Attribute order matches ``_AXES`` (X, Y, Z).
    """

    def __init__(
        self,
        shafts: List[Any],
        caps: List[Any],
        drag_gestures: List[PrimTranslateChangedGesture],
        hover_gestures: List[HighlightGesture],
    ) -> None:
        self.shafts = shafts
        self.caps = caps
        self.drag_gestures = drag_gestures
        self.hover_gestures = hover_gestures

    def gesture_for_axis(self, name: str) -> PrimTranslateChangedGesture:
        """Look up a drag gesture by axis name (``"x"``, ``"y"``, ``"z"``)."""
        idx = {"x": 0, "y": 1, "z": 2}[name.lower()]
        return self.drag_gestures[idx]


def build_translate_gizmo(
    model: Any,
    drag_gestures: Optional[List[PrimTranslateChangedGesture]] = None,
    hover_gestures: Optional[List[HighlightGesture]] = None,
) -> TranslateGizmoHandles:
    """Emit the translate gizmo into the current ``sc.Transform`` scope.

    Must be called inside an ``sc.SceneView.scene`` (or an enclosing
    ``sc.Transform``) context block. Returns a :class:`TranslateGizmoHandles`
    bundle so tests can verify the resulting shapes and drive their gestures
    without a real mouse.

    ``drag_gestures`` / ``hover_gestures`` are optional lists of pre-built
    gestures (one per axis, ordered X/Y/Z). When provided the builder
    reuses them instead of constructing new instances — essential when the
    manipulator invalidates every frame (for camera-distance scaling) so a
    live drag isn't dropped when the scene graph rebuilds. The official
    omni.ui.scene example keeps gesture identity stable across rebuilds
    for the same reason.

    Each axis produces:

    * One ``sc.Line`` shaft from origin to unit vector along the axis,
      carrying one :class:`PrimTranslateChangedGesture` + one
      :class:`HighlightGesture`.
    * One ``sc.PolygonMesh`` pointed cone arrowhead whose base sits at the
      shaft endpoint and whose tip extends beyond it. The arrowhead is
      non-interactive; hover/drag events go to the shaft.
    """
    shafts: List[Any] = []
    caps: List[Any] = []
    drags: List[PrimTranslateChangedGesture] = []
    hovers: List[HighlightGesture] = []

    for i, (_name, axis, base_color, highlight_color) in enumerate(_AXES):
        if drag_gestures is not None and i < len(drag_gestures):
            drag = drag_gestures[i]
        else:
            drag = PrimTranslateChangedGesture(model=model, axis=axis)
        # The arrowhead mesh is visual-only. Hover + drag events stay on the
        # shaft, whose intersection thickness remains the forgiving pick target.
        cap = _make_cone_mesh(axis, base_color)
        if hover_gestures is not None and i < len(hover_gestures):
            hover = hover_gestures[i]
            # Reset the highlight's shape list so stale references to
            # the previous build's shapes don't leak into ``_apply``.
            hover._shapes = [cap]
        else:
            hover = HighlightGesture(
                shapes=[cap],
                base_color=base_color,
                highlight_color=highlight_color,
            )
        shaft = sc.Line(
            [0.0, 0.0, 0.0],
            [axis[0] * SHAFT_LENGTH, axis[1] * SHAFT_LENGTH, axis[2] * SHAFT_LENGTH],
            color=base_color,
            thickness=SHAFT_THICKNESS,
            intersection_thickness=SHAFT_INTERSECTION_THICKNESS,
            gestures=[drag, hover],
        )
        hover.add_shape(shaft)
        shafts.append(shaft)
        caps.append(cap)
        drags.append(drag)
        hovers.append(hover)

    return TranslateGizmoHandles(
        shafts=shafts, caps=caps,
        drag_gestures=drags, hover_gestures=hovers,
    )

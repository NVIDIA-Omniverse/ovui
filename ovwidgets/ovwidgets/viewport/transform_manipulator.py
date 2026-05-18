# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""TransformManipulator — ``sc.Manipulator`` subclass for the transform gizmo.

Step C.1 (Phase C — Transform Manipulators) of the viewport behavior. Replaces the
former free-standing gizmo helper class with a proper ``sc.Manipulator``
subclass that plugs into the ``SceneView`` draw pipeline.

Public surface:

* :data:`GIZMO_SIZE_SCALE` — 0.15 (viewport manipulator style rules).
  Multiplier applied to the viewport-scale transform that wraps the gizmo so
  it appears at roughly constant screen-size regardless of camera distance.
  A future refinement (the viewport manipulator behavior "Gotcha 8")
  will recompute the effective world size from camera distance every frame;
  C.1 uses the simple fixed scale the plan prescribes.
* :data:`TOOL_TRANSLATE`, :data:`TOOL_ROTATE`, :data:`TOOL_SCALE` — string
  constants for the three modes the manipulator toggles between. Matches
  Maya / Blender's ``W/E/R`` hotkey contract wired up by :class:`ToolRegistry`
  in :mod:`ovwidgets.viewport.manipulator_registry`.
* :class:`TransformManipulator(sc.Manipulator)` — the manipulator itself.

Geometry for the three tools is intentionally minimal — Step C.1 is the
scaffold. Steps C.2 / C.3 / C.4 replace the private ``_build_*_placeholder``
methods with real axis arrows (translate), rings (rotate), and cubes (scale).
The placeholders draw three coloured axis lines so that the tool-switch is
visible during QA without pre-empting the real gizmo work.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from omni.ui_scene import scene as sc


class TransformGestureBase(sc.DragGesture):
    """Marker + common ancestor for every gizmo drag gesture.

    The gizmo's translate / rotate / scale drag gestures inherit from
    this class so the :class:`PreventOthers` gesture manager can
    cleanly identify "is this a gizmo gesture?" via ``isinstance``.
    That's the same pattern Kit uses in
    ``omni.kit.manipulator.transform.gestures.TransformGesture`` — any
    gesture that extends the marker wins LMB arbitration against
    non-gizmo drag gestures (e.g., the Screen-level selection /
    marquee pick gestures).
    """


class PreventOthers(sc.GestureManager):
    """Mirror of Kit's ``omni.kit.manipulator.transform.gestures.PreventOthers``.

    Installed on every gizmo drag gesture so that a live gizmo drag
    takes precedence over any non-gizmo drag (selection click / marquee)
    sharing the same LMB mouse-down. The scene consults this manager
    when deciding whether to let one gesture prevent another; the
    verbatim Kit logic is:

    * **``can_be_prevented``** — return ``False`` once the gesture is
      ``CHANGED`` / ``ENDED`` / ``CANCELED`` so an in-flight drag can
      never be interrupted by a later gesture.
    * **``should_prevent``** — return ``True`` when the preventer is a
      :class:`TransformGestureBase` in ``BEGAN`` / ``CHANGED`` state
      and the ``gesture`` being evaluated is *not* a gizmo gesture.
      Kit's selection manipulator defers to this by using a
      low-priority selection gesture; we lean entirely on this
      manager because the viewport's ``PickGesture`` /
      ``PickRectGesture`` don't need an order of their own.

    The manager is stateless — one instance can be shared across every
    gesture in the gizmo, which keeps construction cheap.
    """

    def can_be_prevented(self, gesture: Any) -> bool:
        state = gesture.state
        return (
            state != sc.GestureState.CHANGED
            and state != sc.GestureState.ENDED
            and state != sc.GestureState.CANCELED
        )

    def should_prevent(self, gesture: Any, preventer: Any) -> bool:
        if (
            isinstance(preventer, TransformGestureBase)
            and preventer.state in (sc.GestureState.BEGAN, sc.GestureState.CHANGED)
        ):
            if isinstance(gesture, TransformGestureBase):
                # Two gizmo gestures competing — let both fire (no order
                # semantics in OvGear yet; Kit's ``order`` / ``ray_distance``
                # comparison would go here).
                return False
            return True
        return False

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

# Viewport-scale multiplier for constant screen-size gizmos. See module
# docstring and the viewport behavior Tuned for a refined look against a
# ray-traced background — reference Maya/Blender manipulator proportions.
GIZMO_SIZE_SCALE: float = 0.05

TOOL_TRANSLATE = "translate"
TOOL_ROTATE = "rotate"
TOOL_SCALE = "scale"

VALID_TOOLS: Tuple[str, ...] = (TOOL_TRANSLATE, TOOL_ROTATE, TOOL_SCALE)

# Axis colours from style naming rules Pattern 3 (manipulator hex values).
# Packed 0xAABBGGRR as the ``sc`` binding expects.
AXIS_COLOR_X: int = 0xFF6060AA
AXIS_COLOR_Y: int = 0xFF76A371
AXIS_COLOR_Z: int = 0xFFA07D4F


def _scale_matrix(s: float) -> List[float]:
    """Return a flat 16-float row-major uniform scale matrix."""
    return [
        s,   0.0, 0.0, 0.0,
        0.0, s,   0.0, 0.0,
        0.0, 0.0, s,   0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _translation_matrix(tx: float, ty: float, tz: float) -> List[float]:
    """Return a flat 16-float row-major translation matrix."""
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        tx,  ty,  tz,  1.0,
    ]


class TransformManipulator(sc.Manipulator):
    """Transform gizmo manipulator — translate / rotate / scale scaffolding.

    The manipulator reuses :class:`~ovwidgets.viewport.prim_transform_model.PrimTransformModel`
    as its ``sc.Manipulator`` model. When nothing is selected the manipulator's
    ``on_build`` emits no geometry — the gizmo is invisible until a prim is
    selected (C.5 will wire selection-bus updates to the model).

    When a selection exists, ``on_build`` wraps the active tool's geometry
    in an ``sc.Transform`` whose matrix is a uniform scale of
    :data:`GIZMO_SIZE_SCALE`, satisfying the "constant screen-size" requirement
    from the viewport behavior

    Parameters
    ----------
    model:
        The :class:`PrimTransformModel` instance that holds the current
        selection and (eventually, C.5) the selected prim's pivot transform.
    tool:
        Initial tool — one of :data:`TOOL_TRANSLATE`, :data:`TOOL_ROTATE`,
        :data:`TOOL_SCALE`. Defaults to translate.
    pivot_fn:
        Optional callable that returns a 3-float world-space pivot. When
        provided and the model has a selection, the gizmo is positioned
        there. Defaults to returning ``(0, 0, 0)`` — C.5 will supply the
        real pivot from ``TransformAdapter.get_world_matrix``.
    """

    def __init__(
        self,
        model: Any,
        tool: str = TOOL_TRANSLATE,
        pivot_fn: Optional[Any] = None,
        size_fn: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        if tool not in VALID_TOOLS:
            raise ValueError(
                f"tool must be one of {VALID_TOOLS!r}, got {tool!r}"
            )
        self._prim_model = model
        self._tool: str = tool
        self._pivot_fn = pivot_fn or (lambda: (0.0, 0.0, 0.0))
        # Optional callable returning the per-frame world-scale factor.
        # When provided, it overrides :data:`GIZMO_SIZE_SCALE` so the gizmo
        # can track camera distance for constant on-screen size. Returning
        # a non-positive value falls back to the constant — defensive
        # against a transient camera / viewport state with no info yet.
        self._size_fn = size_fn
        # ── Persistent gesture instances ────────────────────────────────
        #
        # The camera-distance gizmo scaling invalidates this manipulator
        # once per frame so the world-scale stays in lock-step with the
        # camera. If ``build_*_gizmo`` created a fresh ``DragGesture``
        # every rebuild, any in-flight drag would be torn down on the
        # very next frame — matching the user report "drag only changes
        # selection instead of moving the object". The reference
        # ``examples/scene_manipulator.py`` sidesteps this by creating
        # gesture objects once in ``__init__`` and reusing them across
        # rebuilds. We follow that pattern: owning the gesture list here
        # and handing it to the builder each draw keeps drags alive in
        # their ``eBegan`` / ``eChanged`` state through ``invalidate()``.
        from ovwidgets.viewport.rotate_gizmo import PrimRotateChangedGesture
        from ovwidgets.viewport.scale_gizmo import (
            HIGHLIGHT_COLOR_UNIFORM,
            UNIFORM_COLOR,
            PrimScaleChangedGesture,
        )
        from ovwidgets.viewport.translate_gizmo import (
            AXIS_COLOR_X as _TX_COL_X,  # noqa: F401 — unused, kept for clarity
        )
        from ovwidgets.viewport.translate_gizmo import (
            HIGHLIGHT_COLOR_X as _TX_HI_X,
        )
        from ovwidgets.viewport.translate_gizmo import (
            HIGHLIGHT_COLOR_Y as _TX_HI_Y,
        )
        from ovwidgets.viewport.translate_gizmo import (
            HIGHLIGHT_COLOR_Z as _TX_HI_Z,
        )
        from ovwidgets.viewport.translate_gizmo import (
            HighlightGesture,
            PrimTranslateChangedGesture,
        )
        _axes = (
            ((1.0, 0.0, 0.0), AXIS_COLOR_X, _TX_HI_X),
            ((0.0, 1.0, 0.0), AXIS_COLOR_Y, _TX_HI_Y),
            ((0.0, 0.0, 1.0), AXIS_COLOR_Z, _TX_HI_Z),
        )
        self._translate_drags = [
            PrimTranslateChangedGesture(model=model, axis=axis)
            for axis, _, _ in _axes
        ]
        self._translate_hovers = [
            HighlightGesture(shapes=[], base_color=col, highlight_color=hi)
            for _, col, hi in _axes
        ]
        self._rotate_drags = [
            PrimRotateChangedGesture(model=model, axis=axis)
            for axis, _, _ in _axes
        ]
        self._rotate_hovers = [
            HighlightGesture(shapes=[], base_color=col, highlight_color=hi)
            for _, col, hi in _axes
        ]
        self._scale_drags = [
            PrimScaleChangedGesture(model=model, axis=axis)
            for axis, _, _ in _axes
        ]
        self._scale_hovers = [
            HighlightGesture(shapes=[], base_color=col, highlight_color=hi)
            for _, col, hi in _axes
        ]
        self._uniform_scale_drag = PrimScaleChangedGesture(
            model=model, axis=(1.0, 1.0, 1.0), uniform=True,
        )
        self._uniform_scale_hover = HighlightGesture(
            shapes=[],
            base_color=UNIFORM_COLOR,
            highlight_color=HIGHLIGHT_COLOR_UNIFORM,
        )
        # Shared :class:`PreventOthers` manager installed on every gizmo
        # drag gesture (not the hovers — only drags carry the arbitration
        # semantics). Kit keeps one instance per gesture; sharing is
        # safe because :class:`PreventOthers` is stateless.
        self._gesture_manager = PreventOthers()
        for g in (
            *self._translate_drags,
            *self._rotate_drags,
            *self._scale_drags,
            self._uniform_scale_drag,
        ):
            try:
                g.manager = self._gesture_manager
            except Exception:
                pass
        # Populated by ``_build_translate_placeholder`` each frame so QA
        # harnesses can address individual axis gestures without synthesising
        # mouse events. ``None`` when the gizmo hasn't been built yet or when
        # the current tool isn't translate.
        self._translate_handles: Any = None
        # Populated by ``_build_rotate`` — same pattern as translate, for the
        # rotate tool's three ring gestures. ``None`` until the first build
        # or when the active tool is not rotate.
        self._rotate_handles: Any = None
        # Populated by ``_build_scale`` — bundle for the scale tool's three
        # axis handles plus the uniform centre handle. ``None`` until the
        # first build or when the active tool is not scale.
        self._scale_handles: Any = None
        super().__init__(**kwargs)

    # -- public API --------------------------------------------------------

    @property
    def tool(self) -> str:
        return self._tool

    @tool.setter
    def tool(self, value: str) -> None:
        if value not in VALID_TOOLS:
            raise ValueError(
                f"tool must be one of {VALID_TOOLS!r}, got {value!r}"
            )
        if value == self._tool:
            return
        self._tool = value
        # Trigger ``on_build`` on the next draw so the new geometry is emitted.
        self.invalidate()

    @property
    def prim_model(self) -> Any:
        return self._prim_model

    def has_selection(self) -> bool:
        """True iff the attached :class:`PrimTransformModel` has any prim selected."""
        paths = getattr(self._prim_model, "_selected_paths", None)
        return bool(paths)

    @property
    def translate_handles(self) -> Any:
        """Return the last-built translate gizmo handle bundle, or ``None``.

        The bundle is populated by :meth:`on_build` when the tool is
        ``"translate"`` and a prim is selected. QA harnesses use it to drive
        the gesture callbacks directly; tests use it to inspect the emitted
        shapes.
        """
        return self._translate_handles

    @property
    def rotate_handles(self) -> Any:
        """Return the last-built rotate gizmo handle bundle, or ``None``.

        Counterpart to :attr:`translate_handles` — populated by the C.3
        ``_build_rotate`` on every draw that emits the rotate tool's three
        rings. Same QA / test contract: drive gestures via
        ``bundle.gesture_for_axis("x")`` rather than synthesising a mouse.
        """
        return self._rotate_handles

    @property
    def scale_handles(self) -> Any:
        """Return the last-built scale gizmo handle bundle, or ``None``.

        Populated by the C.4 ``_build_scale`` on every draw that emits
        the scale tool's three axis cubes plus the uniform centre cube.
        QA / tests use it to drive the per-axis and uniform gestures
        directly; the uniform gesture lives on
        ``bundle.uniform_drag``.
        """
        return self._scale_handles

    # -- sc.Manipulator hooks ---------------------------------------------

    def on_build(self) -> None:
        """Emit gizmo geometry for the currently-active tool.

        Creates two nested :class:`sc.Transform` nodes (outer pivot,
        inner uniform scale) and stashes them on ``self`` so
        :meth:`refresh_transform` can update the matrices in place each
        frame — Kit's transform manipulator uses the same "build once,
        update attribute every frame" pattern
        (``omni.kit.manipulator.transform.manipulator.TransformManipulator.
        _update_from_model``), which is why its gizmo moves the instant
        selection changes without relying on an ``invalidate()`` call
        making it through at the right moment.

        No-op when the model has no selection — the gizmo is invisible
        until a prim is selected; :meth:`refresh_transform` will flip
        ``visible`` on the next frame once a selection lands.
        """
        # Emit no geometry when nothing is selected — keeps the gizmo
        # invisible AND the ``*_handles`` attributes ``None`` so tests
        # that inspect them for the empty-selection case keep asserting
        # what they expect. The persistent Transform pair (created below
        # only when we have a selection) is what
        # :meth:`refresh_transform` updates in place each frame so
        # selection changes surface on the very next draw without
        # racing the scene's invalidate queue.
        self._pivot_transform = None
        self._scale_transform = None
        self._last_built_has_selection: bool = self.has_selection()
        if not self._last_built_has_selection:
            return
        px, py, pz = self._pivot_fn()
        scale = self._resolve_scale()
        self._pivot_transform = sc.Transform(
            transform=_translation_matrix(px, py, pz),
        )
        self._last_pivot: Tuple[float, float, float] = (px, py, pz)
        self._last_scale: float = float(scale)
        with self._pivot_transform:
            self._scale_transform = sc.Transform(transform=_scale_matrix(scale))
            with self._scale_transform:
                self._build_tool_geometry()

    def _resolve_scale(self) -> float:
        """Resolve the effective world-scale, falling back to the constant."""
        if self._size_fn is None:
            return GIZMO_SIZE_SCALE
        try:
            dynamic = float(self._size_fn())
        except Exception:
            return GIZMO_SIZE_SCALE
        return dynamic if dynamic > 0.0 else GIZMO_SIZE_SCALE

    def refresh_transform(self) -> None:
        """Per-frame hook — update pivot & scale of the persistent Transforms.

        Called from :meth:`ViewportWidget._on_frame` every frame. When
        the selection transitions in or out, we :meth:`invalidate` so
        ``on_build`` can create or tear down the geometry. When a
        selection is steady but the pivot or camera-distance scale
        changes, we write the new matrix directly into the existing
        Transform nodes — Kit's
        ``omni.kit.manipulator.transform.TransformManipulator.
        _update_from_model`` does the same thing and for the same
        reason: an ``sc.Transform.transform = matrix`` assignment shows
        up on the very next draw, without depending on the scene's
        invalidate queue flushing in time. This is the fix for the
        user-visible "gizmo stays at old prim after selection change"
        bug — the yellow bbox updated via its own invalidate but the
        gizmo's didn't, so the arrows stayed at the previous pivot.
        """
        has_sel_now = self.has_selection()
        was_built_with_sel = getattr(self, "_last_built_has_selection", False)
        if has_sel_now != was_built_with_sel:
            # Geometry must be created or removed — only a full rebuild
            # can do that.
            self.invalidate()
            return
        pivot_transform = getattr(self, "_pivot_transform", None)
        scale_transform = getattr(self, "_scale_transform", None)
        if pivot_transform is None or scale_transform is None:
            return
        if not has_sel_now:
            return
        try:
            px, py, pz = self._pivot_fn()
        except Exception:
            return
        scale = self._resolve_scale()
        new_pivot = (float(px), float(py), float(pz))
        if new_pivot != self._last_pivot:
            try:
                pivot_transform.transform = _translation_matrix(*new_pivot)
                self._last_pivot = new_pivot
            except Exception:
                pass
        if abs(scale - self._last_scale) > 1e-6:
            try:
                scale_transform.transform = _scale_matrix(scale)
                self._last_scale = scale
            except Exception:
                pass

    def on_model_updated(self, item: Any) -> None:
        """Placeholder for future model-driven rebuilds — hooks Kit's signal."""

    # -- private helpers ---------------------------------------------------

    def _build_tool_geometry(self) -> None:
        """Dispatch to the per-tool builder."""
        if self._tool == TOOL_TRANSLATE:
            self._build_translate_placeholder()
        elif self._tool == TOOL_ROTATE:
            self._build_rotate()
        elif self._tool == TOOL_SCALE:
            self._build_scale()

    def _build_translate_placeholder(self) -> None:
        """Build the real translate gizmo (Step C.2).

        Delegates to :func:`ovwidgets.viewport.translate_gizmo.build_translate_gizmo`
        so the drag + hover gesture code lives next to the geometry it drives.
        Passes in our persistent gesture instances so drag state survives a
        per-frame invalidate (camera-distance scaling).
        """
        from ovwidgets.viewport.translate_gizmo import build_translate_gizmo
        self._translate_handles = build_translate_gizmo(
            self._prim_model,
            drag_gestures=self._translate_drags,
            hover_gestures=self._translate_hovers,
        )

    def _build_rotate(self) -> None:
        """Build the real rotate gizmo (Step C.3)."""
        from ovwidgets.viewport.rotate_gizmo import build_rotate_gizmo
        self._rotate_handles = build_rotate_gizmo(
            self._prim_model,
            drag_gestures=self._rotate_drags,
            hover_gestures=self._rotate_hovers,
        )

    def _build_scale(self) -> None:
        """Build the real scale gizmo (Step C.4)."""
        from ovwidgets.viewport.scale_gizmo import build_scale_gizmo
        self._scale_handles = build_scale_gizmo(
            self._prim_model,
            drag_gestures=self._scale_drags,
            hover_gestures=self._scale_hovers,
            uniform_drag=self._uniform_scale_drag,
            uniform_hover=self._uniform_scale_hover,
        )



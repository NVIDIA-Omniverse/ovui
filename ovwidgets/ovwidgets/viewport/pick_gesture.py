# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Pick and rect-select gestures.

``omni.ui_scene`` surfaces ``DragGesture.raw_input.mouse.x / .y`` in
OpenGL NDC space — ``[-1, +1]`` across the SceneView — so the drag
threshold lives in NDC units, not pixels. ``PICK_THRESHOLD_NDC = 0.01``
corresponds to roughly 1 % of the viewport's shorter side, or about
7 px on a 720 px-tall widget — short enough that a deliberate click
never accidentally crosses it, long enough that a hand-tremor click
registers as a pick rather than a marquee.

Step D.3 of the viewport behavior extends the gestures with
Shift / Ctrl modifier support so ``ViewportWidget`` can instantiate
one variant per selection mode (``replace`` / ``add`` / ``remove``)
and route each to its own callback. The modifier bits match
``omni.ui.kKeyMod*`` (see ``ovui/core/include/omni/ui/Types.h``) and
are re-exported here so callers don't have to reach into the camera
gesture module for them.

omni.ui_scene invokes ``set_on_*_fn`` callbacks with the owning
``AbstractShape`` as a positional argument. We accept but ignore it
(``_sender=None``) so direct test invocations keep working too.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Optional

from omni.ui_scene import scene as sc

# Modifier bit values — match ``omni.ui.kKeyMod*``.
MOD_NONE = 0
MOD_SHIFT = 1 << 0
MOD_CTRL = 1 << 1
MOD_ALT = 1 << 2


class GizmoAwarePickManager(sc.GestureManager):
    """Backwards-compatibility shim kept for existing viewport wiring.

    OvGear once needed a custom tie-breaker between the Screen pick /
    marquee gestures and the shape-level gizmo drag. The tie-breaker
    now lives inside
    :class:`~ovwidgets.viewport.transform_manipulator.PreventOthers`, which
    the gizmo gestures install directly — mirroring Kit's
    ``omni.kit.manipulator.transform.gestures.PreventOthers`` and the
    selection-manipulator priority pattern. This class stays so the
    viewport can keep its ``_pick_manager`` attribute and the
    ``set_gizmo_gestures`` signature without a second refactor.

    The :meth:`has_live_gizmo_drag` query is also what pick / marquee
    gestures consult in their ``_on_ended`` path so a completed gizmo
    drag doesn't double-fire as a selection change. That check must
    survive two race windows that depend on the order of Python
    callbacks fired by ``omni.ui_scene``'s C++ ``GestureManager``:

    1. **End-of-drag race** — the gizmo's ``_on_ended`` fires *before*
       the pick gesture's, clearing ``is_active``. Each gizmo gesture
       carries a ``_drag_ended_this_cycle`` latch set in its
       ``_on_ended`` and cleared at the start of the next click cycle
       by :meth:`reset_drag_end_tracker` (called from the pick
       gesture's ``_on_began``).

    2. **Mouse-down ordering race (Windows)** — when a click on the
       gizmo gets prevented by ``PreventOthers`` in the same frame as
       it begins, the pick gesture's prevented-fall-through
       ``_on_ended`` and the gizmo's ``_on_began`` both fire in that
       frame, in non-deterministic order across managers.
       ``GestureManager`` stores its caches in
       ``std::unordered_map``; libstdc++ (Linux) and the MSVC STL
       (Windows) bucket pointers differently, so on Linux the gizmo's
       ``_on_began`` ran first (set ``is_active = True``) and on
       Windows the pick's ``_on_ended`` ran first (saw
       ``is_active == False`` and the latch False, since no prior
       drag had latched it). :meth:`has_live_gizmo_drag` therefore
       also reads the C++ gesture ``state`` directly: ``BEGAN`` or
       ``CHANGED`` is set during the scene's ``preProcess``, before
       any Python callback fires, so it reports a live drag
       regardless of callback order.
    """

    def __init__(self) -> None:
        super().__init__()
        self._gizmo_gestures: list = []

    def set_gizmo_gestures(self, gestures: Iterable[Any]) -> None:
        self._gizmo_gestures = list(gestures)

    def has_live_gizmo_drag(self) -> bool:
        # Consult the C++ gesture state first — it is set by the scene's
        # ``preProcess`` *before* any Python callback fires, so it reports
        # "drag in progress this frame" reliably regardless of the order
        # in which the gizmo's ``_on_began`` and the pick gesture's
        # ``_on_ended`` happen to be dispatched. ``GestureManager``
        # iterates ``std::unordered_map<AbstractGesture*, ...>`` in
        # bucket order, which differs between libstdc++ and the MSVC STL —
        # on Linux the gizmo's ``_on_began`` (which sets ``is_active``)
        # ran before the pick's prevented-fall-through ``_on_ended``;
        # on Windows the pick's ``_on_ended`` ran first and saw
        # ``is_active == False``, so the marquee/pick fired with stale
        # ``_start_x`` from a prior click. The state check makes that
        # ordering irrelevant.
        for g in self._gizmo_gestures:
            try:
                state = g.state
            except (AttributeError, RuntimeError):
                state = None
            if state is not None and state in (
                sc.GestureState.BEGAN,
                sc.GestureState.CHANGED,
            ):
                return True
            if getattr(g, "is_active", False):
                return True
            # Catch the race where the gizmo's ``_on_ended`` already
            # flipped ``is_active`` to ``False`` before the pick
            # gesture's ``_on_ended`` had a chance to consult it.
            if getattr(g, "_drag_ended_this_cycle", False):
                return True
        return False

    def reset_drag_end_tracker(self) -> None:
        """Clear the ``_drag_ended_this_cycle`` latch on every gizmo gesture.

        The pick gestures call this from their own ``_on_began`` so a
        completed gizmo drag only suppresses the one pick mouse-up that
        belongs to the same click cycle, not every subsequent click.
        """
        for g in self._gizmo_gestures:
            try:
                g._drag_ended_this_cycle = False
            except AttributeError:
                pass

# Drag threshold in NDC units (see module docstring). Below the threshold
# the gesture is a point pick; at-or-above it is a rectangle marquee.
PICK_THRESHOLD_NDC = 0.01

# Backwards-compatibility alias for any external caller that imported the
# old name. The underlying coord system was always NDC; only the name was
# misleading. Retained as an alias rather than a silent rename so import
# errors surface immediately if someone depended on a numeric value that
# treated it as pixels (the old 5.0 constant never worked in real usage
# because NDC drags are always < 5).
PICK_THRESHOLD_PX = PICK_THRESHOLD_NDC


class PickGesture(sc.DragGesture):
    """Left-click point pick. Fires when the drag distance stays below threshold.

    ``modifiers`` selects which modifier-combination the gesture listens
    for — ``MOD_NONE`` for plain click, ``MOD_SHIFT`` / ``MOD_CTRL``
    for shift-click / ctrl-click add/remove-to-selection variants. The
    bit must match ``omni.ui_scene``'s gesture dispatch so only one
    variant fires per click.
    """

    def __init__(
        self,
        callback: Optional[Callable[..., Any]] = None,
        modifiers: int = MOD_NONE,
    ) -> None:
        self._callback = callback
        self._start_x = 0.0
        self._start_y = 0.0
        # Subclass the virtual methods (``on_began`` / ``on_ended``) —
        # the ``on_*_fn`` kwargs / ``set_on_*_fn`` setters paths only
        # fire ``on_began`` in recent omni.ui_scene bindings. See the
        # rationale on
        # :class:`ovwidgets.viewport.translate_gizmo.PrimTranslateChangedGesture`.
        super().__init__(mouse_button=0, modifiers=modifiers)

    def on_began(self) -> None:  # type: ignore[override]
        self._on_began()

    def on_ended(self) -> None:  # type: ignore[override]
        self._on_ended()

    def _on_began(self, _sender: Any = None) -> None:
        # Clearing the gizmo-drag latch at the start of every click
        # cycle means a previous gizmo drag only suppresses its own
        # mouse-up pick — never the next independent click.
        mgr = getattr(self, "_viewport_pick_manager", None)
        if mgr is not None:
            mgr.reset_drag_end_tracker()
        m = self.raw_input.mouse
        self._start_x = m.x
        self._start_y = m.y

    def _on_ended(self, _sender: Any = None) -> None:
        m = self.raw_input.mouse
        self._process_ended(m.x, m.y)

    def _process_ended(self, x: float, y: float) -> None:
        # Skip the selection mutation when a gizmo drag captured the
        # same mouse-down — otherwise a successful axis drag would also
        # toggle whatever prim sat under the release position. The
        # ``_viewport_pick_manager`` attribute is set by
        # :class:`ViewportWidget` on each pick gesture after build
        # (attaching it as the gesture's ``.manager`` breaks on-move
        # dispatch for the sibling gizmo drag).
        mgr = getattr(self, "_viewport_pick_manager", None)
        if mgr is not None and mgr.has_live_gizmo_drag():
            return
        dx = x - self._start_x
        dy = y - self._start_y
        if math.sqrt(dx * dx + dy * dy) < PICK_THRESHOLD_NDC and self._callback:
            self._callback(x, y)


class PickRectGesture(sc.DragGesture):
    """Left-drag marquee pick. Fires when the drag distance reaches threshold.

    ``modifiers`` works the same way as :class:`PickGesture`: the
    viewport instantiates one variant per selection mode
    (``MOD_NONE`` replace, ``MOD_SHIFT`` add, ``MOD_CTRL`` remove) so
    ``omni.ui_scene``'s modifier-aware dispatch routes the drag to
    the right callback. The callback receives the four NDC corner
    coords in ``(x0, y0, x1, y1)`` order — whatever the user's drag
    direction.
    """

    def __init__(
        self,
        callback: Optional[Callable[..., Any]] = None,
        modifiers: int = MOD_NONE,
    ) -> None:
        self._callback = callback
        self._start_x = 0.0
        self._start_y = 0.0
        self._rect_drawn = False
        # Subclass the virtual methods — see :class:`PickGesture`.
        super().__init__(mouse_button=0, modifiers=modifiers)

    def on_began(self) -> None:  # type: ignore[override]
        self._on_began()

    def on_changed(self) -> None:  # type: ignore[override]
        self._on_changed()

    def on_ended(self) -> None:  # type: ignore[override]
        self._on_ended()

    def _on_began(self, _sender: Any = None) -> None:
        # Same reset as :class:`PickGesture._on_began` — see the note
        # there. Both pick variants must clear the latch because only
        # one fires per mouse-down (the modifier-matching variant).
        mgr = getattr(self, "_viewport_pick_manager", None)
        if mgr is not None:
            mgr.reset_drag_end_tracker()
        m = self.raw_input.mouse
        self._start_x = m.x
        self._start_y = m.y
        self._rect_drawn = False

    def _on_changed(self, _sender: Any = None) -> None:
        m = self.raw_input.mouse
        dx = m.x - self._start_x
        dy = m.y - self._start_y
        if math.sqrt(dx * dx + dy * dy) >= PICK_THRESHOLD_NDC:
            self._rect_drawn = True

    def _on_ended(self, _sender: Any = None) -> None:
        m = self.raw_input.mouse
        self._process_ended(m.x, m.y)

    def _process_ended(self, x: float, y: float) -> None:
        # Skip the marquee mutation when a gizmo drag captured the
        # same mouse-down — see the note on :class:`PickGesture`.
        mgr = getattr(self, "_viewport_pick_manager", None)
        if mgr is not None and mgr.has_live_gizmo_drag():
            return
        dx = x - self._start_x
        dy = y - self._start_y
        if math.sqrt(dx * dx + dy * dy) >= PICK_THRESHOLD_NDC and self._callback:
            self._callback(self._start_x, self._start_y, x, y)

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Camera navigation gestures — Step B.2 of the Viewport Plan.

Four architecture-aligned gestures that replace the old
orbit/pan/zoom classes. See the viewport behavior for the
exact formulas and the camera navigation behavior (pan), §8/§10 (tumble), §9/§11 (look), §14 (zoom) for the rationale.

Boundary: every gesture reads from ``CameraManipulatorModel`` (for gate
flags only) and writes through to ``CameraController``. None of them
touch USD directly — the A.2 camera writer flushes ``CameraController``
state to the session-layer camera on the next ``render_frame``.

Mouse coordinate convention: ``self.raw_input.mouse`` is already in NDC
(from ``SceneView::_captureInput`` in ovui's C++ layer — x ranges
[-1, +1] across the viewport width, y ranges [-1, +1] with +y *up*,
inverted relative to screen-space pixel coords). The plan's formula
``rotate = delta_px / half_width * π`` becomes ``rotate = dx_ndc * π``
when expressed in NDC, because NDC is already normalised by the half
viewport extent. Full-viewport drag → ``dx_ndc = 2`` → ``2π``
(one full rotation), matching the plan's "full rotation per full-width
drag" wording.

Callback signatures: omni.ui_scene invokes ``set_on_*_fn`` callbacks
with the owning ``AbstractShape`` as a positional argument. Each handler
takes ``sender=None`` so callers (including tests) can invoke it
directly without synthesising a shape.
"""

import math
import time
from typing import Any, Callable, Optional, Tuple

from omni.ui_scene import scene as sc

from ovwidgets.viewport.camera_controller import CameraController
from ovwidgets.viewport.camera_inertia import AngularVelocityTracker, TumbleInertia
from ovwidgets.viewport.camera_manipulator import CameraManipulatorModel

# Keyboard modifier bit values — match ``carb::input::kKeyboardModifierFlag*``
# mirrored by ovui's ``omni::ui::kKeyMod*`` constants (core/include/omni/ui/Types.h).
MOD_NONE = 0
MOD_SHIFT = 1 << 0
MOD_CTRL = 1 << 1
MOD_ALT = 1 << 2

# Mouse button numbers in ovui: 0 = Left, 1 = Right, 2 = Middle.
MOUSE_LEFT = 0
MOUSE_RIGHT = 1
MOUSE_MIDDLE = 2

# Default perspective FOV (radians). Matches ``CameraController.get_matrices``
# (``math.radians(45.0)``). Gestures fall back to this when a model's
# ``projection`` item has not been populated yet.
DEFAULT_FOV_Y = math.radians(45.0)

# Fallback viewport size used when the gesture is constructed without a
# ``viewport_size_fn``. 1280×720 matches ``ViewportWidget``'s initial
# ``_width``/``_height`` defaults — close enough that the pan and tumble
# speeds feel correct before the first frame sets a real size.
_FALLBACK_VIEWPORT_SIZE: Tuple[int, int] = (1280, 720)

# Scroll sensitivity used by :class:`ZoomScrollGesture`. Matches the
# ``delta_log = log10(1 + |scroll| × 0.1) * sign(scroll)`` formula from
# the viewport behavior
_ZOOM_SCROLL_SCALE = 0.1

# Maximum absolute NDC coordinate accepted from ``raw_input.mouse``.
# ``sc.SceneView::_captureInput`` emits values in [-1, +1] when the cursor
# is inside the view; a legitimate drag past the edge overshoots slightly
# as the gesture continues to receive events. A sibling shape inside the
# same scene (the pick Screen, the selection-outline manipulator) can be
# laid out elsewhere on screen, and when the gesture system dispatches
# ``on_changed`` against that sibling's frame the reported mouse NDC is
# computed against its cursor — producing values like ``(-2.13, +2.24)``
# that, multiplied by ``math.pi`` in the tumble/look formula, yield
# double-digit-radian rotations per frame. Rejecting events outside
# ``±1.5`` preserves the drag-past-edge tolerance while filtering the
# wrong-shape events.
_NDC_VALID_BOUND = 1.5

ViewportSizeFn = Callable[[], Tuple[int, int]]


def _gate_is_set(model: Optional[CameraManipulatorModel], flag_name: str) -> bool:
    """Return True when the model is present and the named gate flag is 1.

    Gate flags (``disable_tumble`` / ``disable_pan`` / ``disable_zoom`` /
    ``disable_look``) live on the model as int items. We don't want each
    gesture to duplicate the ``None``-handling boilerplate.
    """
    if model is None:
        return False
    values = model.get_as_ints(flag_name)
    return bool(values and values[0])


def _mouse_in_ndc_bounds(mouse: Any) -> bool:
    """True when ``mouse.x`` and ``mouse.y`` lie within ``±_NDC_VALID_BOUND``.

    Guards the gesture callbacks against cross-shape dispatch that reports
    the cursor position relative to a sibling shape's frame — see the
    ``_NDC_VALID_BOUND`` comment above for the failure mode.
    """
    return abs(mouse.x) <= _NDC_VALID_BOUND and abs(mouse.y) <= _NDC_VALID_BOUND


class _AngularDragGesture(sc.DragGesture):
    """Common base for gestures that convert NDC drag → angular delta.

    Both :class:`TumbleGesture` and :class:`LookGesture` consume the same
    delta math. The only difference is which :class:`CameraController`
    mutator they call at the end of each ``_on_changed``.
    """

    _gate_flag: str = ""
    _mode_name: str = "angular"

    def __init__(
        self,
        camera: CameraController,
        model: Optional[CameraManipulatorModel] = None,
        viewport_size_fn: Optional[ViewportSizeFn] = None,
        inertia: Optional[TumbleInertia] = None,
        mouse_button: int = MOUSE_RIGHT,
        modifiers: int = MOD_NONE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(mouse_button=mouse_button, modifiers=modifiers)
        self._camera = camera
        self._model = model
        self._viewport_size_fn = viewport_size_fn
        self._inertia = inertia
        self._velocity_tracker = (
            AngularVelocityTracker(clock=clock) if inertia is not None else None
        )
        self._prev_x = 0.0
        self._prev_y = 0.0
        self._prev_anchored = False
        self._active = False
        self.set_on_began_fn(self._on_began)
        self.set_on_changed_fn(self._on_changed)
        self.set_on_ended_fn(self._on_ended)

    @property
    def is_active(self) -> bool:
        """True while the RMB drag is live (between ``on_began`` and ``on_ended``).

        Exposed publicly so :class:`~ovwidgets.viewport.camera_flight_keyboard.FlightModeKeyboard`
        can poll RMB-hold state without reaching into the private
        ``_active`` flag.
        """
        return self._active

    def _on_began(self, sender: Any = None) -> None:
        if _gate_is_set(self._model, self._gate_flag):
            self._active = False
            return
        self._active = True
        m = self.raw_input.mouse
        # When the began firing arrives from the wrong shape (see
        # ``_mouse_in_ndc_bounds``), defer anchoring ``_prev_x``/
        # ``_prev_y`` until the first in-bounds ``_on_changed`` — the
        # gesture stays armed so the real began-from-the-camera-screen
        # doesn't fire again and no drag is silently dropped.
        if _mouse_in_ndc_bounds(m):
            self._prev_x = m.x
            self._prev_y = m.y
            self._prev_anchored = True
        else:
            self._prev_x = 0.0
            self._prev_y = 0.0
            self._prev_anchored = False
        # A fresh drag starts from "no recorded motion" so the handoff
        # check at _on_ended only sees velocity from *this* drag, never
        # stale carry-over from a previous one. The inertia system
        # itself is not stopped here — the user might deliberately kick
        # inertia with a flick-drag-release cycle.
        if self._velocity_tracker is not None:
            self._velocity_tracker.reset()
        # A live gesture supersedes any running inertia: stop the coast
        # so the user's new input is the only thing driving the camera.
        if self._inertia is not None:
            self._inertia.stop()

    def _on_changed(self, sender: Any = None) -> None:
        if not self._active:
            return
        m = self.raw_input.mouse
        # Skip cross-shape-dispatch events. ``_prev_x``/``_prev_y`` stay
        # anchored to the last trusted position so the next in-bounds
        # event computes the correct incremental delta.
        if not _mouse_in_ndc_bounds(m):
            return
        if not self._prev_anchored:
            # First in-bounds event after a deferred began — anchor and
            # wait for the next event to emit a real delta. Writing a
            # zero-delta tumble here would still be harmless (``orbit(0, 0)``
            # is a no-op), but the handoff to inertia reads the velocity
            # tracker, and recording a zero sample now would spuriously
            # stale-out the tracker on a slow drag.
            self._prev_x = m.x
            self._prev_y = m.y
            self._prev_anchored = True
            return
        dx_ndc = m.x - self._prev_x
        dy_ndc = m.y - self._prev_y
        self._prev_x = m.x
        self._prev_y = m.y
        # Full-width drag: dx_ndc = 2 → rotate_y = 2π (full rotation).
        # Negative yaw on right-drag matches the architecture doc §8 — the
        # scene appears to rotate the opposite way the mouse moves so the
        # user "grabs" the object and drags it around.
        rotate_y = -dx_ndc * math.pi
        # Pitch is inverted from the raw NDC y delta so the vertical axis
        # follows the same "grab the object and drag it" convention as
        # yaw: drag-up (dy_ndc > 0) tilts the *scene* up, which means the
        # camera pitches *down* (negative elevation delta). Without this
        # negation horizontal and vertical drag would have opposite
        # conventions, which feels wrong to users coming from Maya / Kit.
        rotate_x = -dy_ndc * math.pi
        if self._velocity_tracker is not None:
            self._velocity_tracker.record(rotate_y, rotate_x)
        self._apply_angles(rotate_y, rotate_x)

    def _on_ended(self, sender: Any = None) -> None:
        self._active = False
        if self._inertia is not None and self._velocity_tracker is not None:
            vy, vx = self._velocity_tracker.pop_handoff()
            if vy != 0.0 or vx != 0.0:
                self._inertia.start(vy, vx)

    def _current_viewport_size(self) -> Tuple[int, int]:
        if self._viewport_size_fn is None:
            return _FALLBACK_VIEWPORT_SIZE
        size = self._viewport_size_fn()
        if not size:
            return _FALLBACK_VIEWPORT_SIZE
        return size

    def _apply_angles(self, rotate_y: float, rotate_x: float) -> None:
        raise NotImplementedError


class TumbleGesture(_AngularDragGesture):
    """Drag-to-orbit gesture around ``CameraController.target``.

    :class:`~ovwidgets.viewport.camera_manipulator.CameraManipulator` instantiates
    two configurations of this class: the default (``MOUSE_RIGHT,
    MOD_NONE``) and an Alt+LMB variant (``MOUSE_LEFT, MOD_ALT``). Both
    share the same :class:`~ovwidgets.viewport.camera_inertia.TumbleInertia`
    singleton; only one drag is live at any moment.

    Formula (the viewport behavior):

        rotate_y = delta_x_px / half_width  * π
        rotate_x = delta_y_px / half_height * π

    A full-width drag produces π radians (180°) of yaw; a full-height
    drag produces π radians of pitch. This matches Kit's "90° per
    half-drag" convention from the camera navigation behavior
    """

    _gate_flag = "disable_tumble"
    _mode_name = "tumble"

    def _apply_angles(self, rotate_y: float, rotate_x: float) -> None:
        self._camera.orbit(rotate_y, rotate_x)


class LookGesture(_AngularDragGesture):
    """Shift+RMB drag → rotate in place (eye fixed, target moves).

    Same angular math as :class:`TumbleGesture`, but writes through to
    :meth:`CameraController.look` instead of :meth:`orbit`. The camera
    position does not change; only the direction it faces does. See
    the camera navigation behavior and §11.
    """

    _gate_flag = "disable_look"
    _mode_name = "look"

    def __init__(
        self,
        camera: CameraController,
        model: Optional[CameraManipulatorModel] = None,
        viewport_size_fn: Optional[ViewportSizeFn] = None,
        mouse_button: int = MOUSE_RIGHT,
        modifiers: int = MOD_SHIFT,
    ) -> None:
        super().__init__(
            camera,
            model=model,
            viewport_size_fn=viewport_size_fn,
            mouse_button=mouse_button,
            modifiers=modifiers,
        )

    def _apply_angles(self, rotate_y: float, rotate_x: float) -> None:
        self._camera.look(rotate_y, rotate_x)


class PanGesture(sc.DragGesture):
    """MMB-drag → translate the camera target in screen-aligned world units.

    Formula (the viewport behavior / the camera navigation behavior):

        world_per_pixel = distance_to_coi * tan(fov_y / 2) * 2 / viewport_height

    The plan expresses ``world_per_pixel`` in pixel units; our mouse
    deltas arrive in NDC, so the equivalent for NDC input is
    ``world_per_ndc_y = distance_to_coi * tan(fov_y / 2)`` (one NDC unit
    = half-viewport extent, which is exactly the world span covered by
    one NDC unit at the COI depth). The horizontal component scales by
    the viewport aspect ratio — NDC ±1 maps to ±(W/H) world units when
    the fov is expressed vertically.

    Sign convention: dragging the mouse right (``dx_ndc > 0``) slides
    the scene right under the cursor, which means the camera target
    shifts *left* in world space; likewise dragging up (``dy_ndc > 0``,
    NDC-y is +1 at the top) slides the scene up, target shifts down.
    Both deltas are negated before handing them to ``CameraController.pan``.
    """

    def __init__(
        self,
        camera: CameraController,
        model: Optional[CameraManipulatorModel] = None,
        viewport_size_fn: Optional[ViewportSizeFn] = None,
        fov_y: float = DEFAULT_FOV_Y,
        mouse_button: int = MOUSE_MIDDLE,
        modifiers: int = MOD_NONE,
    ) -> None:
        super().__init__(mouse_button=mouse_button, modifiers=modifiers)
        self._camera = camera
        self._model = model
        self._viewport_size_fn = viewport_size_fn
        self._fov_y = fov_y
        self._prev_x = 0.0
        self._prev_y = 0.0
        self._prev_anchored = False
        self._active = False
        self.set_on_began_fn(self._on_began)
        self.set_on_changed_fn(self._on_changed)
        self.set_on_ended_fn(self._on_ended)

    def _on_began(self, sender: Any = None) -> None:
        if _gate_is_set(self._model, "disable_pan"):
            self._active = False
            return
        self._active = True
        m = self.raw_input.mouse
        # See :class:`_AngularDragGesture._on_began` for the cross-shape-
        # dispatch rationale — same deferred-anchor pattern here.
        if _mouse_in_ndc_bounds(m):
            self._prev_x = m.x
            self._prev_y = m.y
            self._prev_anchored = True
        else:
            self._prev_x = 0.0
            self._prev_y = 0.0
            self._prev_anchored = False

    def _on_changed(self, sender: Any = None) -> None:
        if not self._active:
            return
        m = self.raw_input.mouse
        if not _mouse_in_ndc_bounds(m):
            return
        if not self._prev_anchored:
            self._prev_x = m.x
            self._prev_y = m.y
            self._prev_anchored = True
            return
        dx_ndc = m.x - self._prev_x
        dy_ndc = m.y - self._prev_y
        self._prev_x = m.x
        self._prev_y = m.y
        width, height = self._current_viewport_size()
        aspect = (width / height) if (width > 0 and height > 0) else 1.0
        distance = max(self._camera.state.distance, 0.0)
        world_per_ndc_y = distance * math.tan(self._fov_y * 0.5)
        world_per_ndc_x = world_per_ndc_y * aspect
        dx_world = -dx_ndc * world_per_ndc_x
        dy_world = -dy_ndc * world_per_ndc_y
        self._camera.pan(dx_world, dy_world)

    def _on_ended(self, sender: Any = None) -> None:
        self._active = False

    def _current_viewport_size(self) -> Tuple[int, int]:
        if self._viewport_size_fn is None:
            return _FALLBACK_VIEWPORT_SIZE
        size = self._viewport_size_fn()
        if not size:
            return _FALLBACK_VIEWPORT_SIZE
        return size


class ZoomScrollGesture(sc.ScrollGesture):
    """Mouse wheel → dolly in/out along the camera's view direction.

    Formula (the viewport behavior):

        delta_log = log10(1 + |scroll| * 0.1) * sign(scroll)
        distance *= exp(delta_log)

    The log-scaled response means rapid flicks of the wheel feel the
    same as slow scrolls in relative terms: every notch applies a small
    multiplicative step regardless of the current zoom level. Positive
    ``scroll.y`` (wheel up) zooms *in* (decreases distance), matching
    the convention used by every DCC we care about.
    """

    def __init__(
        self,
        camera: CameraController,
        model: Optional[CameraManipulatorModel] = None,
    ) -> None:
        # Accept ``ScrollGesture``'s defaults: ``mouse_button == -1`` /
        # ``modifiers == 0xFFFFFFFF`` → fire on any button state and any
        # modifier combination. Restricting them here blocks the scroll
        # event from ever dispatching in the headless test environment,
        # where the ``isHovered`` check in SceneView's ``_captureInput``
        # returns only when a button is pressed.
        super().__init__()
        self._camera = camera
        self._model = model
        self.set_on_ended_fn(self._on_ended)

    def _on_ended(self, sender: Any = None) -> None:
        if _gate_is_set(self._model, "disable_zoom"):
            return
        scroll_y = self.raw_input.mouse_wheel.y
        if scroll_y == 0.0:
            return
        sign = 1.0 if scroll_y > 0.0 else -1.0
        delta_log = math.log10(1.0 + abs(scroll_y) * _ZOOM_SCROLL_SCALE) * sign
        current = self._camera.state.distance
        # scroll_y > 0 means wheel up → zoom in → smaller distance, so
        # the multiplicative factor is ``exp(-delta_log)``.
        new_distance = current * math.exp(-delta_log)
        self._camera.zoom(new_distance - current)

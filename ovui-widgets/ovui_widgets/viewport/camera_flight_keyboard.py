# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Flight-mode keyboard handler — Step B.3 of the Viewport Plan.

When RMB is held AND any of W/A/S/D/Space/C is pressed, the camera enters
"flight mode": per frame, a velocity vector expressed in the camera basis
is integrated into ``CameraController.state.target``. See
the camera navigation behavior§17 for the reference
architecture this handler distils.

Divergences from ``omni.kit.manipulator.camera.FlightModeKeyboard`` worth
noting:

* Kit subscribes to ``carb.input`` ``CHAR`` + ``KEY_UP`` events directly to
  sidestep OS key-repeat timing artifacts (§17 "The CHAR Event Trick").
  ovui's public keyboard API is ``omni.ui.Window.set_key_pressed_fn``
  with a ``(key, modifiers, pressed)`` signature and no separate CHAR
  channel. Because we only track the *set* of held keys (not event
  rates), key-repeat cannot affect correctness — a set add is idempotent,
  and the per-frame integrator reads the set each tick regardless of
  what the OS is sending between ticks.
* The 0.15 s simultaneous-release guard (§17) is not needed yet: B.3
  has no inertia (that's B.4). As soon as all motion keys are released
  (or RMB comes up), ``is_flying`` becomes False and the integrator
  stops writing to the camera. Step B.4 introduces the guard alongside
  the ``Velocity`` class.
* ``Q`` and ``E`` are reserved for roll (per the plan's text). The
  current ``CameraController`` exposes only (azimuth, elevation,
  distance, target) — there is no roll DOF. Q/E are still *tracked* in
  ``_active_keys`` so releasing them updates the set, but they do not
  contribute to the velocity vector. Adding roll is deferred.

Boundary: this module depends on ``CameraController`` (pure math) and
``CameraManipulatorModel`` (for the ``disable_fly`` gate). It never
touches USD; the A.2 session-layer camera writer flushes the mutated
target on the next ``render_frame``.
"""

from typing import Any, Iterable, Optional, Sequence, Set, Tuple

import numpy as np

from ovui_widgets.viewport.camera_controller import CameraController
from ovui_widgets.viewport.camera_manipulator import CameraManipulatorModel

# Match ``omni.ui.kKeyMod*`` / ``carb.input.KEYBOARD_MODIFIER_FLAG_*``
# bit values — identical across the ovui keyboard callback and the
# ``sc.SceneView`` gesture modifier mask (see
# ``ovui/core/include/omni/ui/Types.h`` lines 19-22).
MOD_SHIFT = 1 << 0
MOD_CTRL = 1 << 1
MOD_ALT = 1 << 2

# Base flight speed in world units per second, matching the viewport behavior
DEFAULT_BASE_SPEED = 1.0

# Modifier-key speed multipliers (the viewport behavior). Shift = sprint,
# Ctrl = tip-toe. Both held → Shift wins (faster motion is typically what
# the user wants when they fat-finger the combo).
SPEED_SHIFT = 2.0
SPEED_CTRL = 0.5

# ``Application._on_key_pressed`` forwards the raw GLFW-style key code.
# GLFW reports printable keys as their *uppercase* ASCII code regardless
# of shift state (see glfw3.h); the ovui C++ binding passes that value
# straight through. ``ord('W')`` is used for robustness — if a future
# keyboard layer switches to lowercase we still match.
_KEY_W = ord("W")
_KEY_A = ord("A")
_KEY_S = ord("S")
_KEY_D = ord("D")
_KEY_Q = ord("Q")
_KEY_E = ord("E")
_KEY_C = ord("C")
_KEY_SPACE = ord(" ")

# All key codes flight mode watches, including roll placeholders.
_TRACKED_KEYS: frozenset = frozenset({
    _KEY_W, _KEY_A, _KEY_S, _KEY_D,
    _KEY_Q, _KEY_E, _KEY_C, _KEY_SPACE,
})

# Subset that actually contributes translation in B.3 (no roll yet).
# ``is_flying`` checks this set — holding only Q/E does not count as
# "moving" so flight mode doesn't activate for roll-only input.
_MOTION_KEYS: frozenset = frozenset({
    _KEY_W, _KEY_A, _KEY_S, _KEY_D, _KEY_C, _KEY_SPACE,
})

# Setting key polled by ``FlightModeKeyboard`` when constructed with an
# application handle. the viewport behavior names this explicitly.
FLY_SPEED_SETTING = "viewport.navigation.fly_speed"


def _gate_is_set(model: Optional[CameraManipulatorModel], flag_name: str) -> bool:
    """Return True when the model is present and the named gate flag is 1.

    Mirrors the helper in ``camera_gesture.py`` so both modules read the
    ``disable_*`` gates the same way.
    """
    if model is None:
        return False
    values = model.get_as_ints(flag_name)
    return bool(values and values[0])


class FlightModeKeyboard:
    """RMB + WASD flight-mode state machine and per-frame integrator.

    The public surface is four methods and one property:

    * ``handle_key_event(key, modifiers, pressed)`` — called by the
      ovui ``Window.set_key_pressed_fn`` dispatch path (or by tests).
      Updates ``_active_keys`` and ``_modifiers``.
    * ``notify_rmb_press()`` / ``notify_rmb_release()`` — called by the
      owning widget when the right mouse button is pressed / released.
    * ``is_flying`` — True iff RMB is held AND at least one *motion*
      key is active AND the model's ``disable_fly`` gate is clear.
    * ``integrate(dt)`` — called once per frame. Advances the camera
      target by ``velocity × speed × dt`` along the camera's right /
      up / forward basis vectors. Safe to call unconditionally; it
      short-circuits when ``is_flying`` is False.
    """

    def __init__(
        self,
        camera: CameraController,
        model: Optional[CameraManipulatorModel] = None,
        base_speed: float = DEFAULT_BASE_SPEED,
        rmb_gestures: Optional[Sequence[Any]] = None,
    ) -> None:
        self._camera = camera
        self._model = model
        self._base_speed = float(base_speed)
        # Optional: gestures whose ``is_active`` property mirrors the RMB
        # drag lifecycle (``TumbleGesture`` and ``LookGesture``). When
        # provided, ``is_flying`` honours their state so a mouse event
        # that the gesture dispatcher routed into one of them already
        # implies "RMB held" without the widget having to wire an
        # additional callback. Tests can still drive the manual path
        # via ``notify_rmb_press`` / ``notify_rmb_release``.
        self._rmb_gestures: Tuple[Any, ...] = tuple(rmb_gestures or ())
        self._rmb_held_manual: bool = False
        self._modifiers: int = 0
        self._active_keys: Set[int] = set()

    # -- speed / configuration ---------------------------------------------

    @property
    def base_speed(self) -> float:
        return self._base_speed

    @base_speed.setter
    def base_speed(self, value: float) -> None:
        self._base_speed = float(value)

    # -- introspection (mostly for tests and QA) ---------------------------

    @property
    def modifiers(self) -> int:
        return self._modifiers

    @property
    def active_keys(self) -> Set[int]:
        # Defensive copy so callers can't mutate our internal state.
        return set(self._active_keys)

    @property
    def rmb_held(self) -> bool:
        """True if either ``notify_rmb_press`` was called or an attached
        gesture reports itself active."""
        if self._rmb_held_manual:
            return True
        return any(self._gesture_is_active(g) for g in self._rmb_gestures)

    @property
    def is_flying(self) -> bool:
        if _gate_is_set(self._model, "disable_fly"):
            return False
        if not self.rmb_held:
            return False
        return any(k in self._active_keys for k in _MOTION_KEYS)

    # -- inputs ------------------------------------------------------------

    def handle_key_event(self, key: int, modifiers: int, pressed: bool) -> None:
        """ovui keyboard callback entry. Updates active-keys and modifiers.

        Keys outside ``_TRACKED_KEYS`` are ignored so typing in a text
        widget (when we eventually get one) can't accidentally move the
        camera. ``modifiers`` is updated unconditionally because Shift /
        Ctrl are the speed modifiers — the user may toggle them between
        motion-key events.
        """
        self._modifiers = modifiers
        if key not in _TRACKED_KEYS:
            return
        if pressed:
            self._active_keys.add(key)
        else:
            self._active_keys.discard(key)

    def notify_rmb_press(self) -> None:
        self._rmb_held_manual = True

    def notify_rmb_release(self) -> None:
        """Drop the manual RMB flag and clear any held keys.

        Clearing ``_active_keys`` on RMB release enforces "no stuck
        velocity" — the plan's acceptance criterion. If the user
        releases RMB *before* releasing W, the key-up event for W
        normally arrives after the mouse-up. Without this clear, the
        next RMB press (even with no keys held) could re-enter flight
        mode using a stale key set.
        """
        self._rmb_held_manual = False
        self._active_keys.clear()

    def subscribe_to_window(self, window: Any) -> None:
        """Convenience: attach ``handle_key_event`` to an ``omni.ui.Window``.

        Most callers route keyboard events through the application's
        main handler and forward them here — that path supports
        chaining with app-level shortcuts. This method is offered for
        standalone use and as a convenience in tests.
        """
        window.set_key_pressed_fn(self.handle_key_event)

    def set_rmb_gestures(self, gestures: Iterable[Any]) -> None:
        """Replace the list of gestures polled for RMB-held state.

        Used by :class:`~ovui_widgets.viewport.viewport_widget.ViewportWidget` after
        ``register_camera_gestures`` produces the tumble/look gestures.
        Takes any iterable (tuple/list/generator); stored internally as a
        tuple so iteration in ``is_flying`` is cheap and stable.
        """
        self._rmb_gestures = tuple(gestures)

    # -- per-frame integration ---------------------------------------------

    def integrate(self, dt: float) -> None:
        """Advance the camera target by ``velocity × speed × dt``.

        The velocity vector is expressed in the camera basis (right /
        up / forward unit vectors from ``CameraController._get_basis``).
        ``speed`` = ``base_speed × modifier_multiplier`` — Shift doubles
        it, Ctrl halves it.

        Safe to call every frame; does nothing when ``is_flying`` is
        False or ``dt`` is non-positive.
        """
        if not self.is_flying or dt <= 0.0:
            return
        vx, vy, vz = self._velocity_components()
        if vx == 0.0 and vy == 0.0 and vz == 0.0:
            return
        speed = self._speed_multiplier() * self._base_speed
        right, up, forward = self._camera._get_basis()
        delta = (
            right * (vx * speed * dt)
            + up * (vy * speed * dt)
            + forward * (vz * speed * dt)
        )
        new_target = np.asarray(self._camera.state.target, dtype=np.float32) + delta
        self._camera.state.target = new_target.tolist()

    # -- helpers -----------------------------------------------------------

    def _velocity_components(self) -> Tuple[float, float, float]:
        """Return ``(vx, vy, vz)`` where components are in ``{-1, 0, +1}``.

        * ``vx`` — right-axis: ``D=+1``, ``A=-1``.
        * ``vy`` — up-axis:    ``Space=+1``, ``C=-1``.
        * ``vz`` — forward:    ``W=+1``, ``S=-1``.

        Opposing keys cancel (W+S → 0). Q and E are reserved for roll
        and do not appear here.
        """
        vx = 0.0
        vy = 0.0
        vz = 0.0
        if _KEY_D in self._active_keys:
            vx += 1.0
        if _KEY_A in self._active_keys:
            vx -= 1.0
        if _KEY_SPACE in self._active_keys:
            vy += 1.0
        if _KEY_C in self._active_keys:
            vy -= 1.0
        if _KEY_W in self._active_keys:
            vz += 1.0
        if _KEY_S in self._active_keys:
            vz -= 1.0
        return vx, vy, vz

    def _speed_multiplier(self) -> float:
        # Shift wins over Ctrl when both are held (see class docstring
        # rationale — "faster motion is typically what the user wants
        # when they fat-finger the combo").
        if self._modifiers & MOD_SHIFT:
            return SPEED_SHIFT
        if self._modifiers & MOD_CTRL:
            return SPEED_CTRL
        return 1.0

    @staticmethod
    def _gesture_is_active(gesture: Any) -> bool:
        """True when the gesture exposes a truthy ``is_active`` property."""
        return bool(getattr(gesture, "is_active", False))

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Flight-mode keyboard handler — Step B.3 of the Viewport Plan.

When RMB is held AND any of W/A/S/D/Q/E/Space/C or an arrow is pressed,
the camera enters "flight mode": per frame, a velocity vector expressed in
the camera basis (Q/E and C/Space along the world vertical) is integrated
into ``CameraController.state.target``. See
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
* The camera is heavy: its velocity eases toward the held keys' velocity
  (speed and direction with their own half-lives) and coasts to a stop
  after the keys or RMB come up, so ``is_flying`` stays True until then.

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

# Base flight speed: a multiplier of FLY_SPEED_SCALE.
DEFAULT_BASE_SPEED = 1.0
# Fly speed per second as a fraction of the distance to the target, and at
# least FLY_SCENE_FLOOR of the scene's diagonal (close to a surface the
# camera still moves).
FLY_SPEED_SCALE = 0.2
FLY_SCENE_FLOOR = 0.02
# RMB + wheel changes the base speed by this factor per notch, within
# [1 / FLY_SPEED_RANGE, FLY_SPEED_RANGE].
FLY_WHEEL_STEP = 1.1
FLY_SPEED_RANGE = 64.0
# Heavy fly: the speed eases toward the keys' speed with these half-lives
# (seconds), and a change of direction eases with FLY_TURN_HALF_LIFE.
FLY_ACCEL_HALF_LIFE = 0.2
FLY_DECEL_HALF_LIFE = 0.2
FLY_TURN_HALF_LIFE = 0.35

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
# Direction of each key as (right, world up, forward); the arrows
# (GLFW codes) alias W/A/S/D.
_KEY_DIRECTIONS = {
    ord("W"): (0.0, 0.0, 1.0), 265: (0.0, 0.0, 1.0),
    ord("S"): (0.0, 0.0, -1.0), 264: (0.0, 0.0, -1.0),
    ord("D"): (1.0, 0.0, 0.0), 262: (1.0, 0.0, 0.0),
    ord("A"): (-1.0, 0.0, 0.0), 263: (-1.0, 0.0, 0.0),
    ord("E"): (0.0, 1.0, 0.0), ord(" "): (0.0, 1.0, 0.0),
    ord("Q"): (0.0, -1.0, 0.0), ord("C"): (0.0, -1.0, 0.0),
}

# All key codes flight mode watches; each of them moves the camera.
_TRACKED_KEYS: frozenset = frozenset(_KEY_DIRECTIONS)

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

    The public surface is five methods and one property:

    * ``handle_key_event(key, modifiers, pressed)`` — called by the
      ovui ``Window.set_key_pressed_fn`` dispatch path (or by tests).
      Updates ``_active_keys`` and ``_modifiers``.
    * ``notify_rmb_press()`` / ``notify_rmb_release()`` — called by the
      owning widget when the right mouse button is pressed / released.
    * ``is_flying`` — True iff the model's ``disable_fly`` gate is clear
      AND either RMB is held with a flight key, or the camera still coasts.
    * ``integrate(dt)`` — called once per frame. Eases the velocity
      toward the held keys' velocity (camera right / forward, world
      vertical) and advances the camera target by it. Safe to call
      unconditionally; it short-circuits when ``is_flying`` is False.
    * ``step_speed(notches)`` — RMB + wheel changes the base speed.
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
        self._velocity = np.zeros(3)
        self.wheel_step = FLY_WHEEL_STEP
        # Diagonal of the scene's bounds, for the speed floor (0: none).
        self.scene_size = 0.0

    # -- speed / configuration ---------------------------------------------

    @property
    def base_speed(self) -> float:
        return self._base_speed

    @base_speed.setter
    def base_speed(self, value: float) -> None:
        self._base_speed = float(value)

    def step_speed(self, notches: float) -> None:
        """RMB + wheel: change the base speed by :attr:`wheel_step` per notch, within the speed range."""
        speed = self._base_speed * self.wheel_step ** notches
        self._base_speed = min(max(speed, 1.0 / FLY_SPEED_RANGE), FLY_SPEED_RANGE)

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
        gesture holds the fly button (its ``flies``, else ``is_active``)."""
        if self._rmb_held_manual:
            return True
        return any(self._gesture_is_active(g) for g in self._rmb_gestures)

    @property
    def is_flying(self) -> bool:
        if _gate_is_set(self._model, "disable_fly"):
            return False
        if self._velocity.any():
            return True  # coasting to a stop
        if not self.rmb_held:
            return False
        return bool(self._active_keys)

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
        """Ease the velocity toward the held keys' one, then move the target by it.

        The keys' velocity is ``speed`` along the camera's right / forward
        axes and the world vertical, with ``speed = base_speed ×
        FLY_SPEED_SCALE × reach × modifier_multiplier`` (Shift doubles
        it, Ctrl halves it), where ``reach`` is the distance to the target
        and at least ``FLY_SCENE_FLOOR × scene_size``. Its speed eases in with FLY_ACCEL_HALF_LIFE,
        a turn with FLY_TURN_HALF_LIFE, and without keys the camera coasts
        to a stop with FLY_DECEL_HALF_LIFE.

        Safe to call every frame; does nothing when ``is_flying`` is
        False or ``dt`` is non-positive.
        """
        if not self.is_flying or dt <= 0.0:
            return
        vx, vy, vz = self._velocity_components() if self.rmb_held else (0.0, 0.0, 0.0)
        reach = max(float(self._camera.state.distance), FLY_SCENE_FLOOR * self.scene_size)
        speed = self._speed_multiplier() * self._base_speed * FLY_SPEED_SCALE * reach
        right, _, forward = self._camera._get_basis()
        goal = (right * vx + np.asarray(self._camera.up_axis, dtype=np.float64) * vy + forward * vz) * speed
        error = goal - self._velocity
        goal_squared = float(np.dot(goal, goal))
        if goal_squared > 0.0:
            along = goal * (float(np.dot(error, goal)) / goal_squared)
            self._velocity += along * (1.0 - 0.5 ** (dt / FLY_ACCEL_HALF_LIFE))
            self._velocity += (error - along) * (1.0 - 0.5 ** (dt / FLY_TURN_HALF_LIFE))
        else:
            self._velocity *= 0.5 ** (dt / FLY_DECEL_HALF_LIFE)
            if np.linalg.norm(self._velocity) < 1.0e-3 * speed:
                self._velocity[:] = 0.0
        target = np.asarray(self._camera.state.target, dtype=np.float64) + self._velocity * dt
        self._camera.state.target = target.tolist()

    def tick(self, dt: float) -> None:
        """Camera process: fly for ``dt`` seconds (nothing when not flying)."""
        self.integrate(dt)

    def stop(self) -> None:
        """Stop coasting at once."""
        self._velocity[:] = 0.0

    # -- helpers -----------------------------------------------------------

    def _velocity_components(self) -> Tuple[float, float, float]:
        """Return ``(vx, vy, vz)``, each in ``[-1, +1]``, from the held keys.

        * ``vx`` — right-axis: ``D=+1``, ``A=-1``.
        * ``vy`` — world vertical: ``E``/``Space=+1``, ``Q``/``C=-1``.
        * ``vz`` — forward: ``W=+1``, ``S=-1``.

        The arrows alias W/A/S/D. Opposing keys cancel (W+S → 0). The
        vector is at most 1 long, so a diagonal is not faster.
        """
        sums = np.clip(sum((np.asarray(_KEY_DIRECTIONS[key]) for key in self._active_keys), np.zeros(3)), -1.0, 1.0)
        sums /= max(1.0, float(np.linalg.norm(sums)))
        vx, vy, vz = (float(v) for v in sums)
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
        """True when the gesture holds the fly button."""
        return bool(getattr(gesture, "flies", getattr(gesture, "is_active", False)))

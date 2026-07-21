# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tumble inertia — Step B.4 of the Viewport Plan.

Implements post-release angular velocity decay for :class:`TumbleGesture`,
per the camera navigation behavior§20.

Scope (v1): only tumble gets inertia. Pan and zoom do not — this matches
the Kit default and the explicit requirement in the viewport behavior
Flight-mode velocity damping (§17) is a separate subsystem and lives in
``camera_flight_keyboard`` if/when it's added.

Boundary: pure math plus the ``CameraController.orbit`` mutator. No USD,
no ovui dependencies — the session-layer camera writer (§A.2) flushes the
orbited target on the next ``render_frame``.

Decay model
-----------

the viewport behavior writes the decay as::

    velocity *= (1 - damping) ** (dt / time_constant)

Choosing ``(1 - damping) == 1/e`` (i.e. ``damping ≈ 0.632``) reduces the
formula to the pure exponential decay ``velocity *= exp(-dt / tc)``. With
``tc == 0.15 s`` this yields ``exp(-2) ≈ 0.135`` remaining after 300 ms
— about 86% decay, matching the plan's "~85% decay over 300ms" target.
We use the exponential form directly to avoid carrying around the
implicit damping coefficient.

The configured time constant is reread from the model on every tick, so
live changes to ``viewport.navigation.tumble_inertia`` (e.g., via a
settings dialog or CLI override) take effect without reinstancing.
"""

import math
import time
from typing import Callable, Optional, Tuple

from ovui_widgets.viewport.camera_controller import CameraController
from ovui_widgets.viewport.camera_manipulator import CameraManipulatorModel

# Default time constant in seconds. Matches the camera navigation behavior
# §18 and the viewport behavior (`tumble_inertia_time_constant = 0.15`).
DEFAULT_TIME_CONSTANT = 0.15

# Velocity magnitude (rad/sec) below which inertia is considered finished.
# The plan writes ``min_speed = 0.001``. At 60 fps that corresponds to a
# per-frame orbit of ~1e-5 rad — sub-pixel on any reasonable viewport.
DEFAULT_MIN_SPEED = 0.001

# dt clamp for ``tick()`` — guards against large frame stalls (first-frame
# shader compile, GC pauses) snapping the camera through a full rotation.
# the viewport behavior calls for clamping dt into [0.001, 0.1] seconds.
DT_CLAMP_MIN = 0.001
DT_CLAMP_MAX = 0.1

# Age of the last non-zero gesture delta beyond which we do not hand off
# inertia. Captures the "user stopped moving, then released" case — if the
# last motion was > 100 ms ago the drag effectively had zero velocity at
# release, so no coast.
DEFAULT_MAX_HANDOFF_AGE = 0.1

# Setting key polled by :class:`ViewportWidget` to override the default
# time constant. Setting value <= 0 disables inertia entirely (see
# :meth:`TumbleInertia.is_enabled`).
TUMBLE_INERTIA_SETTING = "viewport.navigation.tumble_inertia"


class TumbleInertia:
    """Post-release angular velocity coaster for a tumble gesture.

    The gesture hands off a 2D angular velocity ``(rotate_y_per_sec,
    rotate_x_per_sec)`` on ``on_ended``. Each frame, :meth:`tick` writes
    ``velocity * dt`` through to :meth:`CameraController.orbit` and then
    decays the velocity by ``exp(-dt / time_constant)``. When the
    magnitude drops below ``min_speed`` or :meth:`stop` is called, the
    inertia becomes inactive until the next :meth:`start`.

    The time constant is read from the attached
    :class:`CameraManipulatorModel` on every tick (item
    ``tumble_inertia``); if no model is provided the constructor-supplied
    default is used. A time constant of ``<= 0`` disables inertia — new
    :meth:`start` calls become no-ops and active inertia stops on the
    next tick.
    """

    def __init__(
        self,
        camera: CameraController,
        model: Optional[CameraManipulatorModel] = None,
        time_constant: float = DEFAULT_TIME_CONSTANT,
        min_speed: float = DEFAULT_MIN_SPEED,
    ) -> None:
        self._camera = camera
        self._model = model
        self._default_time_constant = float(time_constant)
        self._min_speed = float(min_speed)
        self._vy = 0.0
        self._vx = 0.0
        self._active = False

    # -- configuration ----------------------------------------------------

    @property
    def time_constant(self) -> float:
        """Current time constant in seconds.

        Reads the model's ``tumble_inertia`` item when a model is
        attached so the setting pipeline
        (``viewport.navigation.tumble_inertia`` → model →
        inertia) stays authoritative. Falls back to the constructor's
        default when no model is present.
        """
        if self._model is not None:
            vals = self._model.get_as_floats("tumble_inertia")
            if vals:
                return float(vals[0])
        return self._default_time_constant

    @property
    def min_speed(self) -> float:
        return self._min_speed

    def is_enabled(self) -> bool:
        """Inertia is disabled when ``time_constant <= 0``."""
        return self.time_constant > 0.0

    # -- introspection ----------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def velocity(self) -> Tuple[float, float]:
        """Current ``(rotate_y_per_sec, rotate_x_per_sec)`` (for tests/QA)."""
        return (self._vy, self._vx)

    # -- state transitions -----------------------------------------------

    def start(self, rotate_y_velocity: float, rotate_x_velocity: float) -> bool:
        """Hand off a velocity vector. Returns True if inertia armed.

        A no-op (returns False) when:

        * inertia is disabled (``time_constant <= 0``) by the viewport settings
        * the handed-off speed is at or below ``min_speed`` — the
          gesture either had no meaningful tail velocity or the user
          stopped moving before release.
        """
        if not self.is_enabled():
            self._active = False
            return False
        speed = math.hypot(rotate_y_velocity, rotate_x_velocity)
        if speed <= self._min_speed:
            self._active = False
            return False
        self._vy = float(rotate_y_velocity)
        self._vx = float(rotate_x_velocity)
        self._active = True
        return True

    def stop(self) -> None:
        self._vy = 0.0
        self._vx = 0.0
        self._active = False

    # -- per-frame integration -------------------------------------------

    def tick(self, dt: float) -> bool:
        """Integrate one frame of inertia. Returns :attr:`is_active`.

        Ordering: apply this frame's step first (``camera.orbit(vy*dt,
        vx*dt)``), then decay. That way the first tick after
        :meth:`start` actually moves the camera — otherwise a gesture
        that released with a tiny dt before the decay would coast less
        than it should.
        """
        if not self._active:
            return False
        if dt <= 0.0:
            return self._active
        # If the setting was flipped to disabled while we were coasting,
        # stop cleanly on the next tick instead of dividing by zero.
        tc = self.time_constant
        if tc <= 0.0:
            self.stop()
            return False
        dt_clamped = max(DT_CLAMP_MIN, min(DT_CLAMP_MAX, float(dt)))
        self._camera.orbit(self._vy * dt_clamped, self._vx * dt_clamped)
        decay = math.exp(-dt_clamped / tc)
        self._vy *= decay
        self._vx *= decay
        if math.hypot(self._vy, self._vx) < self._min_speed:
            self.stop()
        return self._active


class AngularVelocityTracker:
    """Records the most recent non-zero angular delta and its timestamp.

    Used by :class:`TumbleGesture` to measure tail velocity for inertia
    handoff. Kept as its own class so the gesture doesn't grow five more
    instance attributes and the behaviour is independently testable.

    The tracker ignores zero-delta frames: if the user holds the mouse
    still before releasing, the last *motion* is the last non-zero
    change, not the release. That matches
    the camera navigation behavior "last non-zero delta".
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        max_handoff_age: float = DEFAULT_MAX_HANDOFF_AGE,
    ) -> None:
        self._clock = clock
        self._max_handoff_age = float(max_handoff_age)
        self._last_change_time: Optional[float] = None
        self._last_velocity: Tuple[float, float] = (0.0, 0.0)

    def reset(self) -> None:
        self._last_change_time = None
        self._last_velocity = (0.0, 0.0)

    def record(self, rotate_y: float, rotate_x: float) -> None:
        """Record a frame delta. Zero deltas are stored as timestamps only
        so the "stopped before release" check in :meth:`pop_handoff`
        still sees a fresh timestamp without a non-zero velocity.
        """
        now = self._clock()
        if rotate_y == 0.0 and rotate_x == 0.0:
            # No motion this frame — zero out the recorded velocity so
            # a static hold → release produces no inertia, but keep a
            # fresh timestamp so age gating works predictably.
            self._last_velocity = (0.0, 0.0)
            self._last_change_time = now
            return
        prev = self._last_change_time
        if prev is not None:
            dt = now - prev
            if dt > 1e-6:
                self._last_velocity = (rotate_y / dt, rotate_x / dt)
        self._last_change_time = now

    def pop_handoff(self) -> Tuple[float, float]:
        """Return the velocity to hand off, then reset.

        Returns ``(0.0, 0.0)`` when the last non-zero change is stale or
        never recorded — ``TumbleInertia.start`` treats that as "do
        nothing" per its own threshold check.
        """
        vy, vx = self._last_velocity
        last_t = self._last_change_time
        self.reset()
        if last_t is None:
            return (0.0, 0.0)
        if self._clock() - last_t > self._max_handoff_age:
            return (0.0, 0.0)
        return (vy, vx)

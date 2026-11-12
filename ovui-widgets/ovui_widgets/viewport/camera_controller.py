# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Pure-math orbit camera controller. No pxr/USD dependency."""

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Tuple

import numpy as np

_ELEV_CLAMP = 1.5
_MIN_DIST = 0.01
_MAX_DIST = 1.0e6
# Display smoothing half-life (seconds) of the viewport's look and tumble
# steps: the shown camera eases behind the played-back hand by
# 0.05 / ln 2 = 72 ms on average. The zoom glides with its own half-life;
# the pan is not smoothed.
CAMERA_SMOOTHING_HALF_LIFE = 0.05
ZOOM_GLIDE_HALF_LIFE = 0.04
# Longest time step of the camera motions: a stalled frame does not throw
# the camera.
_MAX_STEP = 0.1
# A smoothed step this close to its end (radians, log distance or scene
# units) is finished at once, so the camera comes to rest in finite time.
_SETTLED = 1.0e-4


@dataclass
class CameraState:
    target: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    distance: float = 5.0
    azimuth: float = 0.0
    elevation: float = 0.4


def _look_at(eye: Any, center: Any, up: Any, dtype: Any = np.float32) -> Any:
    """Compute 4x4 view matrix (row-major, OpenGL convention), rounded once to ``dtype``."""
    eye = np.asarray(eye, dtype=np.float64)
    center = np.asarray(center, dtype=np.float64)
    up = np.asarray(up, dtype=np.float64)

    f = center - eye
    f = f / np.linalg.norm(f)
    r = np.cross(f, up)
    if np.linalg.norm(r) < 1.0e-6:
        # Exact authored top/bottom cameras are valid; orbit gestures still
        # clamp away from the poles. Choose a stable plan-view up vector.
        up = np.asarray([0, 1, 0] if abs(f[2]) > 0.5 else [0, 0, -1], dtype=np.float64)
        r = np.cross(f, up)
    r = r / np.linalg.norm(r)
    u = np.cross(r, f)

    m = np.eye(4, dtype=np.float64)
    m[0, :3] = r
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -np.dot(r, eye)
    m[1, 3] = -np.dot(u, eye)
    m[2, 3] = np.dot(f, eye)
    return m.astype(dtype, copy=False)


def _perspective(fovy: Any, aspect: Any, near: Any, far: Any, dtype: Any = np.float32) -> Any:
    """Compute 4x4 perspective projection matrix (OpenGL convention)."""
    t = math.tan(fovy / 2.0)
    m = np.zeros((4, 4), dtype=dtype)
    m[0, 0] = 1.0 / (aspect * t)
    m[1, 1] = 1.0 / t
    m[2, 2] = -(far + near) / (far - near)
    m[2, 3] = -(2.0 * far * near) / (far - near)
    m[3, 2] = -1.0
    return m


def _orthographic(
    half_width: float,
    half_height: float,
    near: float,
    far: float,
    dtype: Any = np.float32,
) -> Any:
    """Compute a centered OpenGL orthographic projection matrix."""
    m = np.eye(4, dtype=dtype)
    m[0, 0] = 1.0 / max(float(half_width), 1.0e-6)
    m[1, 1] = 1.0 / max(float(half_height), 1.0e-6)
    m[2, 2] = -2.0 / (far - near)
    m[2, 3] = -(far + near) / (far - near)
    return m


class CameraController:
    """Orbit camera: azimuth/elevation spherical coords around a target point.

    The world up axis defaults to Y (``(0, 1, 0)``). :meth:`set_pose` sets it
    from the stage metadata so Z-up scenes (e.g. kitchens authored in Maya
    with ``upAxis = "Z"``) orbit around the correct axis. All math in
    :meth:`_get_eye`, :meth:`_get_basis`, and :meth:`get_matrices` reads
    ``self.up_axis`` — changing it rotates the orbit gimbal live.

    :attr:`fov_degrees` is the vertical field of view used when building the
    projection matrix. 45° is a sensible default; loading a USD camera via
    :meth:`set_pose` overrides it with the prim's focal-length derived FOV.

    With a :attr:`clock` the camera is evaluated in time: every
    :meth:`get_matrices` first advances the camera's motions (the
    :attr:`processes`, such as fly and inertia, the input ramps and the
    smoothing) to the clock's now, so each matrix shows the camera at the
    moment it is handed over.
    """

    def __init__(self) -> None:
        self.state = CameraState()
        self.up_axis: list = [0.0, 1.0, 0.0]
        self.fov_degrees: float = 45.0
        self.projection_mode: str = "perspective"
        # Display smoothing of gesture steps queued by :meth:`smooth`.
        self.smoothing_half_life: float = 0.0
        self.zoom_glide_half_life: float = 0.0
        self.clock: Optional[Callable[[], float]] = None
        # Objects with ``tick(dt)`` and ``stop()`` that move the camera over time.
        self.processes: list = []
        self._time: Optional[float] = None
        self._ramps: list = []  # [key, delta left, start, end] in advanced time
        self._elapsed = 0.0  # time advanced so far
        self._pending: dict = {}

    def set_projection_mode(self, mode: str) -> bool:
        """Select ``perspective`` or ``orthographic`` projection."""
        normalized = str(mode or "").strip().lower()
        if normalized not in {"perspective", "orthographic"}:
            return False
        self.projection_mode = normalized
        return True

    def set_up_axis(self, up_axis_str: str) -> None:
        """Accepts USD-style ``"Y"`` or ``"Z"``; anything else is treated as Y."""
        if isinstance(up_axis_str, str) and up_axis_str.upper() == "Z":
            self.up_axis = [0.0, 0.0, 1.0]
        else:
            self.up_axis = [0.0, 1.0, 0.0]

    def set_pose(
        self,
        eye: Any,
        target: Any,
        up_axis: str = "Y",
        fov_degrees: float | None = None,
    ) -> None:
        """Aim the camera at ``target`` from ``eye`` (world-space points).

        Decomposes the offset into (distance, azimuth, elevation) relative to
        the stage ``up_axis`` ("Y" or "Z") so subsequent orbit / pan / zoom
        gestures behave naturally around the new pose.
        """
        self.stop_motion()
        self.set_up_axis(up_axis)
        if fov_degrees is not None and fov_degrees > 0.0:
            self.fov_degrees = float(fov_degrees)
        eye_np = np.asarray(eye, dtype=np.float64)
        target_np = np.asarray(target, dtype=np.float64)
        offset = eye_np - target_np
        d = float(np.linalg.norm(offset))
        if d < _MIN_DIST:
            d = _MIN_DIST
        self.state.target = [float(target_np[0]), float(target_np[1]), float(target_np[2])]
        self.state.distance = min(d, _MAX_DIST)
        if self.up_axis[2] > 0.5:  # Z-up
            vertical = float(offset[2])
            el = math.asin(max(-1.0, min(1.0, vertical / d)))
            # az=0 → eye is along -Y of target (camera looks toward +Y)
            az = math.atan2(float(offset[0]), -float(offset[1]))
        else:  # Y-up (default)
            vertical = float(offset[1])
            el = math.asin(max(-1.0, min(1.0, vertical / d)))
            # az=0 → eye is along +Z of target (camera looks toward -Z)
            az = math.atan2(float(offset[0]), float(offset[2]))
        horizontal_axes = (0, 1) if self.up_axis[2] > 0.5 else (0, 2)
        horizontal = math.hypot(*(float(offset[i]) for i in horizontal_axes))
        if horizontal <= 1.0e-6 * d:
            # At an exact pole the azimuth is undefined (atan2 of zero/noise),
            # while _look_at renders a fixed plan-view up vector. Use the
            # azimuth whose pan/orbit basis matches that rendered image.
            az = 0.0 if vertical > 0 else math.pi
        self.state.azimuth = float(az)
        self.state.elevation = float(el)

    def orbit(self, delta_x: float, delta_y: float, pivot: Any = None) -> None:
        """Turn about the target, or about the world point ``pivot`` (the camera keeps its view of it)."""
        if pivot is None:
            self.state.azimuth += delta_x
            self.state.elevation = float(
                np.clip(self.state.elevation + delta_y, -_ELEV_CLAMP, _ELEV_CLAMP)
            )
            return
        pivot = np.asarray(pivot, dtype=np.float64)
        offset = self._get_eye() - pivot
        local = [float(np.dot(axis, offset)) for axis in self._view_basis()]
        self.orbit(delta_x, delta_y)
        eye = pivot + sum(axis * value for axis, value in zip(self._view_basis(), local))
        self.state.target = (eye - (self._get_eye() - np.asarray(self.state.target, dtype=np.float64))).tolist()

    def dolly(self, delta: float, point: Any = None) -> None:
        """Scale the distance by ``exp(delta)`` about the world ``point`` (the target by default); the view direction stays."""
        distance = float(self.state.distance)
        scale = max(_MIN_DIST, min(_MAX_DIST, distance * math.exp(delta))) / distance
        point = np.asarray(self.state.target if point is None else point, dtype=np.float64)
        target = np.asarray(self.state.target, dtype=np.float64)
        self.state.target = (point + (target - point) * scale).tolist()
        self.state.distance = distance * scale

    def smooth(
        self,
        method: str,
        delta_x: float,
        delta_y: float = 0.0,
        anchor: Any = None,
        duration: float = 0.0,
        delay: float = 0.0,
    ) -> None:
        """Apply a gesture step ``method(delta_x, delta_y[, anchor])`` over the next frames.

        The step is spread evenly over the ``duration`` seconds that start
        ``delay`` seconds from now: a gesture replays each input step at the
        pace the hand made it. A step that should have started already is
        spread over the rest of its time. The camera then shows it through
        the display smoothing of its method: each :meth:`advance` applies the share
        ``1 - 2 ** (-dt / half_life)`` of what is queued, so the camera
        eases behind the hand without the jitter of single input events.
        ``anchor`` is a world point, or a function that returns it, or
        ``None`` while it is not known: the step then waits for it.
        """
        self._evaluate_now()
        key = (method, anchor if anchor is None or callable(anchor) else tuple(float(v) for v in anchor))
        start = self._elapsed + float(delay)
        self._ramps.append([key, np.array((delta_x, delta_y), dtype=np.float64), start, start + max(float(duration), 0.0)])
        if start + duration <= self._elapsed and not self._half_life(method):
            self.advance(0.0)

    def advance(self, dt: float) -> None:
        """Apply the input ramps and the smoothing of the steps queued by :meth:`smooth` for ``dt`` seconds."""
        begin = self._elapsed
        self._elapsed = end = begin + max(dt, 0.0)
        incoming: dict = {}
        for ramp in self._ramps:
            if callable(ramp[0][1]) and ramp[0][1]() is None:
                continue  # waits for its anchor
            start = max(begin, ramp[2])
            if end >= ramp[3]:
                part = ramp[1].copy()
            elif end <= start:
                continue
            else:
                part = ramp[1] * ((end - start) / (ramp[3] - start))
            ramp[1] -= part
            # A step due before this dt is queued whole; one due within it
            # came in evenly over it.
            due = self._pending if ramp[3] <= begin else incoming
            due[ramp[0]] = due.get(ramp[0], 0.0) + part
        self._ramps = [ramp for ramp in self._ramps if end < ramp[3] or ramp[1].any()]
        for key in list(self._pending) + [key for key in incoming if key not in self._pending]:
            # Exact first-order smoothing of the queued rest and of the part
            # that came in evenly during this dt.
            rest, part = self._pending.get(key, 0.0), incoming.get(key, 0.0)
            time_constant = self._half_life(key[0]) / math.log(2.0)
            if time_constant > 0.0 and dt > 0.0:
                kept = math.exp(-dt / time_constant)
                step = rest * (1.0 - kept) + part * (1.0 - time_constant / dt * (1.0 - kept))
            else:
                step = (rest + part) * (1.0 if time_constant <= 0.0 else 0.0)
            rest = self._pending[key] = rest + part - step
            if np.abs(rest).sum() < _SETTLED:
                step, rest = step + rest, 0.0 * rest  # the smoothing ends: the same rest pose every time
            anchor = key[1]() if callable(key[1]) else key[1]
            if key[0] in ("dolly", "orbit"):
                getattr(self, key[0])(*step[: 1 if key[0] == "dolly" else 2], anchor)
            else:
                getattr(self, key[0])(*step)
            if not rest.any():
                del self._pending[key]

    def _half_life(self, method: str) -> float:
        if method == "pan":
            return 0.0
        return self.zoom_glide_half_life if method == "dolly" else self.smoothing_half_life

    def _evaluate_now(self) -> None:
        """Advance the processes, ramps and smoothing to the clock's now."""
        if self.clock is None:
            return
        now = self.clock()
        if self._time is None or now <= self._time:
            self._time = now if self._time is None else self._time
            return
        dt = min(now - self._time, _MAX_STEP)
        self._time = now
        for process in self.processes:
            process.tick(dt)
        self.advance(dt)

    def stop_motion(self) -> None:
        """Drop the queued steps and stop every process (fly and inertia coasting)."""
        self._ramps.clear()
        self._pending.clear()
        self.stop_coasting()

    def stop_coasting(self) -> None:
        """Stop the processes (fly and inertia coasting); queued steps still ease out."""
        for process in self.processes:
            process.stop()

    def cursor_point(self, x: float, y: float, aspect: float, depth: Optional[float] = None) -> Any:
        """World point under the viewport NDC ``(x, y)`` at ``depth`` along the view (the target's by default)."""
        right, up, back = self._view_basis()
        depth = float(self.state.distance) if depth is None else float(depth)
        half = math.tan(math.radians(self.fov_degrees) / 2.0) * depth
        return self._get_eye() + (right * (x * aspect) + up * y) * half - back * depth

    def depth_of(self, point: Any) -> float:
        """Distance of the world ``point`` in front of the camera, along the view."""
        return float(np.dot(self._get_eye() - np.asarray(point, dtype=np.float64), self._view_basis()[2]))

    def _view_basis(self) -> Tuple[Any, Any, Any]:
        """Camera (right, up, back) world axes exactly as :meth:`get_matrices` renders them."""
        view = _look_at(self._get_eye(), self.state.target, self.up_axis, np.float64)
        return view[0, :3], view[1, :3], view[2, :3]

    def pan(self, delta_x: float, delta_y: float) -> None:
        right, up = self._get_pan_basis()
        try:
            tx, ty, tz = (float(v) for v in self.state.target)
        except Exception:
            tx, ty, tz = 0.0, 0.0, 0.0
        dx = float(delta_x)
        dy = float(delta_y)
        self.state.target = [
            tx + right[0] * dx + up[0] * dy,
            ty + right[1] * dx + up[1] * dy,
            tz + right[2] * dx + up[2] * dy,
        ]

    def zoom(self, delta: float) -> None:
        new_distance = self.state.distance + delta
        self.state.distance = max(_MIN_DIST, min(_MAX_DIST, new_distance))

    def look(self, delta_azimuth: float, delta_elevation: float) -> None:
        """Rotate view direction in place — eye stays fixed, target moves.

        The orbit model stores (target, distance, azimuth, elevation). A look
        gesture wants the opposite of orbit: keep the camera's world position
        and only change where it's pointing. We compute the current eye,
        update the angles with the same clamp as ``orbit``, then recompute
        ``target`` so the new (target, az, el, dist) still reproduces the
        original eye.
        """
        eye_before = self._get_eye()
        self.state.azimuth += delta_azimuth
        self.state.elevation = float(
            np.clip(
                self.state.elevation + delta_elevation, -_ELEV_CLAMP, _ELEV_CLAMP
            )
        )
        az = self.state.azimuth
        el = self.state.elevation
        d = self.state.distance
        h = d * math.cos(el)
        v = d * math.sin(el)
        if self.up_axis[2] > 0.5:  # Z-up
            offset = np.array(
                [h * math.sin(az), -h * math.cos(az), v],
                dtype=np.float64,
            )
        else:  # Y-up
            offset = np.array(
                [h * math.sin(az), v, h * math.cos(az)],
                dtype=np.float64,
            )
        new_target = eye_before - offset
        self.state.target = new_target.tolist()

    def get_matrices(self, width: int, height: int, dtype: Any = np.float32) -> Tuple[Any, Any]:
        """Return (view_4x4, proj_4x4) as numpy arrays, computed in float64 and rounded once to ``dtype``.

        Near/far planes scale with orbit distance so large-unit scenes
        (cube_stacks at 54K units wide, etc.) stay inside the frustum
        without losing depth precision on small ones. The ratio stays
        inside ``1:100000`` so the depth buffer keeps usable resolution.
        """
        self._evaluate_now()
        eye = self._get_eye()
        target = np.asarray(self.state.target, dtype=np.float64)
        world_up = np.asarray(self.up_axis, dtype=np.float64)
        view = _look_at(eye, target, world_up, dtype)
        aspect = width / height if height else 1.0
        dist = max(float(self.state.distance), _MIN_DIST)
        near = max(dist / 1000.0, 0.01)
        far = max(dist * 100.0, 10000.0)
        fovy = math.radians(self.fov_degrees)
        if self.projection_mode == "orthographic":
            half_height = dist * math.tan(fovy * 0.5)
            proj = _orthographic(
                half_height * aspect,
                half_height,
                near,
                far,
                dtype,
            )
        else:
            proj = _perspective(fovy, aspect, near, far, dtype)
        return view, proj

    def focus(self, target: Any, distance: float) -> None:
        self.stop_motion()
        self.state.target = list(target)
        self.state.distance = float(distance)

    def _get_eye(self) -> Any:
        az = self.state.azimuth
        el = self.state.elevation
        d = self.state.distance
        t = np.asarray(self.state.target, dtype=np.float64)
        h = d * math.cos(el)
        v = d * math.sin(el)
        if self.up_axis[2] > 0.5:  # Z-up
            x = h * math.sin(az)
            y = -h * math.cos(az)
            z = v
        else:  # Y-up
            x = h * math.sin(az)
            y = v
            z = h * math.cos(az)
        return t + np.array([x, y, z], dtype=np.float64)

    def _get_basis(self) -> Tuple[Any, Any, Any]:
        """Return (right, up, forward) unit vectors in world space."""
        eye = self._get_eye()
        target = np.asarray(self.state.target, dtype=np.float64)
        forward = target - eye
        norm_f = np.linalg.norm(forward)
        if norm_f < 1e-6:
            forward = np.array([0.0, 0.0, -1.0], dtype=np.float64)
        else:
            forward = forward / norm_f
        world_up = np.asarray(self.up_axis, dtype=np.float64)
        right = np.cross(forward, world_up)
        norm = np.linalg.norm(right)
        if norm < 1e-6:
            right = np.array([1.0, 0.0, 0.0], dtype=np.float64)
        else:
            right = right / norm
        up = np.cross(right, forward)
        up = up / np.linalg.norm(up)
        return right, up, forward

    def _get_pan_basis(
        self,
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Return camera right/up as plain tuples for hot pan-event handling."""
        az = float(self.state.azimuth)
        el = float(self.state.elevation)
        sin_az = math.sin(az)
        cos_az = math.cos(az)
        sin_el = math.sin(el)
        cos_el = math.cos(el)
        if self.up_axis[2] > 0.5:  # Z-up
            right = (cos_az, sin_az, 0.0)
            up = (-sin_az * sin_el, cos_az * sin_el, cos_el)
        else:  # Y-up
            right = (cos_az, 0.0, -sin_az)
            up = (-sin_az * sin_el, cos_el, -cos_az * sin_el)
        return right, up

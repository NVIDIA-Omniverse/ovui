# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Pure-math orbit camera controller. No pxr/USD dependency."""

import math
from dataclasses import dataclass, field
from typing import Any, Tuple

import numpy as np

_ELEV_CLAMP = 1.5
_MIN_DIST = 0.01
_MAX_DIST = 1.0e6


@dataclass
class CameraState:
    target: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    distance: float = 5.0
    azimuth: float = 0.0
    elevation: float = 0.4


def _look_at(eye: Any, center: Any, up: Any) -> Any:
    """Compute 4x4 view matrix (row-major, OpenGL convention)."""
    eye = np.asarray(eye, dtype=np.float32)
    center = np.asarray(center, dtype=np.float32)
    up = np.asarray(up, dtype=np.float32)

    f = center - eye
    f = f / np.linalg.norm(f)
    r = np.cross(f, up)
    r = r / np.linalg.norm(r)
    u = np.cross(r, f)

    m = np.eye(4, dtype=np.float32)
    m[0, :3] = r
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -np.dot(r, eye)
    m[1, 3] = -np.dot(u, eye)
    m[2, 3] = np.dot(f, eye)
    return m


def _perspective(fovy: Any, aspect: Any, near: Any, far: Any) -> Any:
    """Compute 4x4 perspective projection matrix (OpenGL convention)."""
    t = math.tan(fovy / 2.0)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = 1.0 / (aspect * t)
    m[1, 1] = 1.0 / t
    m[2, 2] = -(far + near) / (far - near)
    m[2, 3] = -(2.0 * far * near) / (far - near)
    m[3, 2] = -1.0
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
    """

    def __init__(self) -> None:
        self.state = CameraState()
        self.up_axis: list = [0.0, 1.0, 0.0]
        self.fov_degrees: float = 45.0

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
        self.set_up_axis(up_axis)
        if fov_degrees is not None and fov_degrees > 0.0:
            self.fov_degrees = float(fov_degrees)
        eye_np = np.asarray(eye, dtype=np.float32)
        target_np = np.asarray(target, dtype=np.float32)
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
        self.state.azimuth = float(az)
        self.state.elevation = float(np.clip(el, -_ELEV_CLAMP, _ELEV_CLAMP))

    def orbit(self, delta_x: float, delta_y: float) -> None:
        self.state.azimuth += delta_x
        self.state.elevation = float(
            np.clip(self.state.elevation + delta_y, -_ELEV_CLAMP, _ELEV_CLAMP)
        )

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
                dtype=np.float32,
            )
        else:  # Y-up
            offset = np.array(
                [h * math.sin(az), v, h * math.cos(az)],
                dtype=np.float32,
            )
        new_target = eye_before - offset
        self.state.target = new_target.tolist()

    def get_matrices(self, width: int, height: int) -> Tuple[Any, Any]:
        """Return (view_4x4, proj_4x4) as numpy float32 arrays.

        Near/far planes scale with orbit distance so large-unit scenes
        (cube_stacks at 54K units wide, etc.) stay inside the frustum
        without losing depth precision on small ones. The ratio stays
        inside ``1:100000`` so the depth buffer keeps usable resolution.
        """
        eye = self._get_eye()
        target = np.asarray(self.state.target, dtype=np.float32)
        world_up = np.asarray(self.up_axis, dtype=np.float32)
        view = _look_at(eye, target, world_up)
        aspect = width / height if height else 1.0
        dist = max(float(self.state.distance), _MIN_DIST)
        near = max(dist / 1000.0, 0.01)
        far = max(dist * 100.0, 10000.0)
        proj = _perspective(math.radians(self.fov_degrees), aspect, near, far)
        return view, proj

    def focus(self, target: Any, distance: float) -> None:
        self.state.target = list(target)
        self.state.distance = float(distance)

    def _get_eye(self) -> Any:
        az = self.state.azimuth
        el = self.state.elevation
        d = self.state.distance
        t = np.asarray(self.state.target, dtype=np.float32)
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
        return t + np.array([x, y, z], dtype=np.float32)

    def _get_basis(self) -> Tuple[Any, Any, Any]:
        """Return (right, up, forward) unit vectors in world space."""
        eye = self._get_eye()
        target = np.asarray(self.state.target, dtype=np.float32)
        forward = target - eye
        norm_f = np.linalg.norm(forward)
        if norm_f < 1e-6:
            forward = np.array([0.0, 0.0, -1.0], dtype=np.float32)
        else:
            forward = forward / norm_f
        world_up = np.asarray(self.up_axis, dtype=np.float32)
        right = np.cross(forward, world_up)
        norm = np.linalg.norm(right)
        if norm < 1e-6:
            right = np.array([1.0, 0.0, 0.0], dtype=np.float32)
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

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Screen-space picking of UsdLux lights from the light gizmo silhouette.

The renderer pick only reports geometry. A light has no surface, so a click on
its gizmo would otherwise select a mesh behind it or nothing at all. This
module projects the same silhouette that ``LightManipulator`` draws and tells
which light a click is on or near. Only the drawn lines are a target: a click
inside a gizmo, where no line is drawn, is not on the light.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

import numpy as np

from ovui_widgets.viewport.light_manipulator import (
    light_geometry_primitives,
    normalized_light_geometry,
)

# Click distance, in render pixels, that still counts as "on" the gizmo.
LIGHT_PICK_OUTLINE_TOLERANCE_PX = 10.0
# These lights light the scene from all around or from one direction, not
# from their position. Their gizmo marks where the light prim is, so it does
# not take a click from the geometry under it.
NON_POSITIONAL_LIGHT_TYPES = frozenset({"DistantLight", "DomeLight"})
# Gizmos whose distances to the click differ by less than this are equally
# near. Then the light nearest to the camera wins, as a mesh in front does.
LIGHT_PICK_SAME_DISTANCE_PX = 1.0
_ARC_SEGMENTS = 32
_MIN_CLIP_W = 1.0e-6


def _arc_points(radius: float, axis: int, z_offset: float) -> list[tuple[float, float, float]]:
    points = []
    for index in range(_ARC_SEGMENTS + 1):
        angle = 2.0 * math.pi * index / _ARC_SEGMENTS
        a = radius * math.cos(angle)
        b = radius * math.sin(angle)
        if axis == 0:
            points.append((z_offset, a, b))
        elif axis == 1:
            points.append((a, z_offset, b))
        else:
            points.append((a, b, z_offset))
    return points


def _local_polylines(
    light_type: str,
    geometry: tuple[float, float, float],
) -> list[list[tuple[float, float, float]]]:
    polylines = []
    for primitive in light_geometry_primitives(light_type, geometry):
        if primitive[0] == "line":
            polylines.append([primitive[1], primitive[2]])
        else:
            _, radius, axis, z_offset = primitive
            # The cylinder caps are offset along local Z, as drawn.
            polylines.append(_arc_points(radius, axis, z_offset if axis == 2 else 0.0))
    return polylines


def _to_clip(
    points: Sequence[Sequence[float]],
    world: np.ndarray,
    view_projection: np.ndarray,
) -> np.ndarray:
    homogeneous = np.ones((len(points), 4), dtype=float)
    homogeneous[:, :3] = np.asarray(points, dtype=float)
    # World matrices are row-vector (translation in the last row).
    return (homogeneous @ world) @ view_projection.T


def _clip_to_depth_range(
    a: np.ndarray,
    b: np.ndarray,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Cut a clip-space segment to the near and far planes.

    Perspective and orthographic projections both use ``-w <= z <= w``. An
    orthographic ``w`` is always 1, so ``w`` alone cannot tell that a point
    is behind the camera.
    """
    t0, t1 = 0.0, 1.0
    for da, db in (
        (a[3] + a[2], b[3] + b[2]),  # near plane
        (a[3] - a[2], b[3] - b[2]),  # far plane
        (a[3] - _MIN_CLIP_W, b[3] - _MIN_CLIP_W),  # in front of the eye
    ):
        if da < 0.0 and db < 0.0:
            return None
        if da < 0.0:
            t0 = max(t0, da / (da - db))
        elif db < 0.0:
            t1 = min(t1, da / (da - db))
    if t0 >= t1:
        return None
    return a + t0 * (b - a), a + t1 * (b - a)


def _segment_distance(
    point: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
) -> float:
    delta = end - start
    length_sq = float(delta @ delta)
    if length_sq <= 1.0e-12:
        return float(np.linalg.norm(point - start))
    t = max(0.0, min(1.0, float((point - start) @ delta) / length_sq))
    return float(np.linalg.norm(point - (start + t * delta)))


def light_pick_distance(
    light_type: str,
    geometry_attributes: Mapping[str, float],
    world_matrix: Sequence[float],
    view_matrix: Any,
    projection_matrix: Any,
    ndc: tuple[float, float],
    render_size: tuple[int, int],
) -> float | None:
    """Return the pixel distance from ``ndc`` to a light's gizmo, or ``None``.

    ``world_matrix`` is the 16 float row-major matrix with translation in the
    last row. ``view_matrix`` and ``projection_matrix`` are the 4x4 camera
    matrices used for rendering. ``ndc`` is the render-space click, ``y`` up.
    ``None`` means no part of the gizmo is on screen. Parts outside the
    camera's near and far planes are not on screen, also for orthographic
    cameras. Unusable input raises ``ValueError`` or ``TypeError``.
    The result is the distance to the nearest drawn line, reduced by
    ``LIGHT_PICK_OUTLINE_TOLERANCE_PX``, so a value <= 0 is a hit.
    """
    world = np.asarray(world_matrix, dtype=float).reshape(4, 4)
    view = np.asarray(view_matrix, dtype=float).reshape(4, 4)
    projection = np.asarray(projection_matrix, dtype=float).reshape(4, 4)
    width, height = float(render_size[0]), float(render_size[1])
    if width <= 0.0 or height <= 0.0:
        raise ValueError(f"render size {render_size!r} is not positive")
    if not np.all(np.isfinite(world)):
        raise ValueError("light world matrix is not finite")
    geometry = normalized_light_geometry(light_type, geometry_attributes)
    polylines = _local_polylines(light_type, geometry)
    if not polylines:
        return None
    view_projection = projection @ view
    scale = np.array([0.5 * width, 0.5 * height])
    click = np.asarray(ndc, dtype=float) * scale

    best: float | None = None
    for polyline in polylines:
        clip = _to_clip(polyline, world, view_projection)
        for index in range(len(polyline) - 1):
            visible = _clip_to_depth_range(clip[index], clip[index + 1])
            if visible is None:
                continue
            a, b = visible
            start = a[:2] / a[3] * scale
            end = b[:2] / b[3] * scale
            value = _segment_distance(click, start, end) - LIGHT_PICK_OUTLINE_TOLERANCE_PX
            if best is None or value < best:
                best = value
    if best is not None and not math.isfinite(best):
        return None
    return best


def pick_light_path(
    candidates: Iterable[tuple[str, str, Mapping[str, float], Sequence[float]]],
    view_matrix: Any,
    projection_matrix: Any,
    ndc: tuple[float, float],
    render_size: tuple[int, int],
    on_error: Callable[[str, Exception], None],
) -> str | None:
    """Return the path of the light whose gizmo the click is on, if any.

    ``candidates`` holds ``(path, light_type, geometry_attributes,
    world_matrix)``. When gizmos overlap, the nearest outline wins. When
    outlines are equally near (``LIGHT_PICK_SAME_DISTANCE_PX``), the light
    whose origin is nearest to the camera wins. A light that cannot be tested
    goes to ``on_error(path, exception)`` and the other lights are still
    tested.
    """
    hits: list[tuple[float, str, Sequence[float]]] = []
    for path, light_type, attributes, world_matrix in candidates:
        try:
            value = light_pick_distance(
                light_type,
                attributes,
                world_matrix,
                view_matrix,
                projection_matrix,
                ndc,
                render_size,
            )
        except (TypeError, ValueError) as exc:
            on_error(path, exc)
            continue
        if value is None or value > 0.0:
            continue
        hits.append((value, path, world_matrix))
    if not hits:
        return None
    best_value = min(value for value, _, _ in hits)
    nearest = [hit for hit in hits if hit[0] - best_value < LIGHT_PICK_SAME_DISTANCE_PX]
    view = np.asarray(view_matrix, dtype=float).reshape(4, 4)
    return min(nearest, key=lambda hit: (_camera_distance(hit[2], view), hit[0]))[1]


def _camera_distance(world_matrix: Sequence[float], view: np.ndarray) -> float:
    """Distance of the light origin in front of the camera, along its view."""
    origin = np.asarray(world_matrix, dtype=float).reshape(4, 4)[3]
    # The camera looks down -Z in view space.
    return -float((view @ origin)[2])

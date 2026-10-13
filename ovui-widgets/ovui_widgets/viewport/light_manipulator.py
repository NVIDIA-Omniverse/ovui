# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Selection-driven viewport silhouettes for concrete UsdLux lights."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

from omni.ui_scene import scene as sc

LIGHT_GIZMO_COLOR = 0xFF54CEFF
LIGHT_GIZMO_THICKNESS = 2.0
SUPPORTED_LIGHT_TYPES = frozenset(
    {
        "CylinderLight",
        "DiskLight",
        "DistantLight",
        "DomeLight",
        "RectLight",
        "SphereLight",
    }
)


def _dimension(
    attributes: Mapping[str, float],
    name: str,
    default: float,
) -> float:
    try:
        value = abs(float(attributes.get(name, default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def normalized_light_geometry(
    light_type: str,
    attributes: Mapping[str, float],
) -> tuple[float, float, float]:
    """Return authored local dimensions in the stage's world-space units.

    The public name is retained for compatibility, but the returned values are
    deliberately *not* normalized.  Normalizing the largest dimension and then
    applying the camera-distance gizmo scale made a light keep a fixed pixel
    footprint and caused one dimension edit to resize the other dimension.
    """
    meters_per_unit = _dimension(attributes, "meters_per_unit", 1.0)
    one_meter = 1.0 / max(meters_per_unit, 1e-12)
    if light_type == "RectLight":
        width = _dimension(attributes, "width", one_meter)
        height = _dimension(attributes, "height", one_meter)
        return (width, height, one_meter)
    if light_type in {"SphereLight", "DiskLight"}:
        reference_radius = 0.5 * one_meter
        radius = _dimension(attributes, "radius", reference_radius)
        return (radius, radius, one_meter)
    if light_type == "CylinderLight":
        radius = _dimension(attributes, "radius", 0.5 * one_meter)
        length = _dimension(attributes, "length", one_meter)
        return (radius, radius, length)
    return (one_meter, one_meter, one_meter)


def _translation_matrix(x: float, y: float, z: float) -> list[float]:
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        x, y, z, 1.0,
    ]


def _line(start: tuple[float, float, float], end: tuple[float, float, float]) -> Any:
    return sc.Line(
        list(start),
        list(end),
        color=LIGHT_GIZMO_COLOR,
        thickness=LIGHT_GIZMO_THICKNESS,
    )


def _arc(radius: float, axis: int) -> Any:
    return sc.Arc(
        radius,
        color=LIGHT_GIZMO_COLOR,
        thickness=LIGHT_GIZMO_THICKNESS,
        axis=axis,
        wireframe=True,
        sector=False,
    )


def _emission_rays(starts: tuple[tuple[float, float, float], ...], length: float) -> None:
    head_half_width = length * 0.16
    head_length = length * 0.24
    for x, y, z in starts:
        _line((x, y, z), (x, y, z - length))
        _line(
            (x, y, z - length),
            (x - head_half_width, y, z - length + head_length),
        )
        _line(
            (x, y, z - length),
            (x + head_half_width, y, z - length + head_length),
        )


def build_light_geometry(
    light_type: str,
    geometry: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> None:
    """Emit a world-space silhouette and local ``-Z`` emission direction."""
    geometry_x, geometry_y, geometry_z = geometry
    if light_type == "DomeLight":
        _arc(geometry_x, 0)
        _arc(geometry_x, 1)
        _arc(geometry_x, 2)
        return
    if light_type == "SphereLight":
        radius = geometry_x
        _arc(radius, 0)
        _arc(radius, 1)
        _arc(radius, 2)
        _line(
            (0.0, 0.0, -radius - 0.15 * geometry_z),
            (0.0, 0.0, -radius - 0.45 * geometry_z),
        )
        return
    if light_type == "DistantLight":
        _arc(0.42 * geometry_x, 2)
        ray_offset = 0.5 * geometry_x
        _emission_rays(
            ((-ray_offset, 0.0, 0.0), (0.0, 0.0, 0.0), (ray_offset, 0.0, 0.0)),
            1.65 * geometry_z,
        )
        return
    if light_type == "RectLight":
        half_width = 0.5 * geometry_x
        half_height = 0.5 * geometry_y
        corners = (
            (-half_width, -half_height, 0.0),
            (half_width, -half_height, 0.0),
            (half_width, half_height, 0.0),
            (-half_width, half_height, 0.0),
        )
        for index, corner in enumerate(corners):
            _line(corner, corners[(index + 1) % len(corners)])
        ray_offset = half_width * 0.64
        _emission_rays(
            ((-ray_offset, 0.0, 0.0), (0.0, 0.0, 0.0), (ray_offset, 0.0, 0.0)),
            0.75 * geometry_z,
        )
        return
    if light_type == "DiskLight":
        radius = geometry_x
        _arc(radius, 2)
        ray_offset = radius * 0.59
        _emission_rays(
            ((-ray_offset, 0.0, 0.0), (0.0, 0.0, 0.0), (ray_offset, 0.0, 0.0)),
            0.75 * geometry_z,
        )
        return
    if light_type == "CylinderLight":
        radius = geometry_x
        half_length = 0.5 * geometry_z
        with sc.Transform(transform=_translation_matrix(0.0, 0.0, -half_length)):
            _arc(radius, 2)
        with sc.Transform(transform=_translation_matrix(0.0, 0.0, half_length)):
            _arc(radius, 2)
        for x, y in ((-radius, 0.0), (radius, 0.0), (0.0, -radius), (0.0, radius)):
            _line((x, y, -half_length), (x, y, half_length))


class LightManipulator(sc.Manipulator):
    """Draw the selected concrete light in its authored local orientation."""

    def __init__(
        self,
        *,
        type_fn: Callable[[], str],
        geometry_fn: Callable[[], Mapping[str, float]],
        transform_fn: Callable[[], list[float] | None],
        **kwargs: Any,
    ) -> None:
        self._type_fn = type_fn
        self._geometry_fn = geometry_fn
        self._transform_fn = transform_fn
        self._world_transform: Any | None = None
        self._last_light_type = ""
        self._last_geometry = (1.0, 1.0, 1.0)
        self._last_world_transform: list[float] | None = None
        super().__init__(**kwargs)

    def _current_type(self) -> str:
        try:
            light_type = str(self._type_fn() or "")
        except Exception:
            return ""
        return light_type if light_type in SUPPORTED_LIGHT_TYPES else ""

    def _current_transform(self) -> list[float] | None:
        try:
            matrix = self._transform_fn()
        except Exception:
            return None
        return list(matrix) if matrix is not None and len(matrix) == 16 else None

    def _current_geometry(self, light_type: str) -> tuple[float, float, float]:
        try:
            attributes = self._geometry_fn()
        except Exception:
            attributes = {}
        return normalized_light_geometry(light_type, attributes)

    def on_build(self) -> None:
        self._world_transform = None
        light_type = self._current_type()
        if not light_type:
            self._last_light_type      = ""
            self._last_geometry        = (1.0, 1.0, 1.0)
            self._last_world_transform = None
            return
        geometry = self._current_geometry(light_type)
        world_transform = self._current_transform()
        self._last_light_type = light_type
        self._last_geometry = geometry
        self._last_world_transform = world_transform
        if not light_type or world_transform is None:
            return
        self._world_transform = sc.Transform(transform=world_transform)
        with self._world_transform:
            build_light_geometry(light_type, geometry)

    def refresh_transform(self) -> None:
        light_type = self._current_type()
        if not light_type:
            if self._last_light_type:
                self.invalidate()
            return
        geometry = self._current_geometry(light_type)
        world_transform = self._current_transform()
        if (
            light_type != self._last_light_type
            or geometry != self._last_geometry
            or (world_transform is None) != (self._last_world_transform is None)
        ):
            self.invalidate()
            return
        if not light_type or world_transform is None:
            return
        world_node = self._world_transform
        if world_node is None:
            return
        if world_transform != self._last_world_transform:
            try:
                world_node.transform = world_transform
                self._last_world_transform = world_transform
            except Exception:
                pass

    def on_model_updated(self, item: Any) -> None:
        return None


__all__ = [
    "LightManipulator",
    "SUPPORTED_LIGHT_TYPES",
    "build_light_geometry",
    "normalized_light_geometry",
]

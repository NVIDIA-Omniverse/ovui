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


Point3 = tuple[float, float, float]
# ("line", start, end) or ("arc", radius, axis, z_offset)
LightPrimitive = tuple[Any, ...]


def _line(start: Point3, end: Point3) -> LightPrimitive:
    return ("line", start, end)


def _arc(radius: float, axis: int, z_offset: float = 0.0) -> LightPrimitive:
    return ("arc", radius, axis, z_offset)


def _emission_rays(starts: tuple[Point3, ...], length: float) -> list[LightPrimitive]:
    head_half_width = length * 0.16
    head_length = length * 0.24
    primitives: list[LightPrimitive] = []
    for x, y, z in starts:
        primitives.append(_line((x, y, z), (x, y, z - length)))
        primitives.append(
            _line(
                (x, y, z - length),
                (x - head_half_width, y, z - length + head_length),
            )
        )
        primitives.append(
            _line(
                (x, y, z - length),
                (x + head_half_width, y, z - length + head_length),
            )
        )
    return primitives


def light_geometry_primitives(
    light_type: str,
    geometry: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> list[LightPrimitive]:
    """Describe the light silhouette as local-space lines and arcs.

    Drawing and viewport picking both use this description, so a click lands
    on exactly the shape the selected light draws.
    """
    geometry_x, geometry_y, geometry_z = geometry
    if light_type == "DomeLight":
        return [_arc(geometry_x, 0), _arc(geometry_x, 1), _arc(geometry_x, 2)]
    if light_type == "SphereLight":
        radius = geometry_x
        return [
            _arc(radius, 0),
            _arc(radius, 1),
            _arc(radius, 2),
            _line(
                (0.0, 0.0, -radius - 0.15 * geometry_z),
                (0.0, 0.0, -radius - 0.45 * geometry_z),
            ),
        ]
    if light_type == "DistantLight":
        ray_offset = 0.5 * geometry_x
        return [_arc(0.42 * geometry_x, 2)] + _emission_rays(
            ((-ray_offset, 0.0, 0.0), (0.0, 0.0, 0.0), (ray_offset, 0.0, 0.0)),
            1.65 * geometry_z,
        )
    if light_type == "RectLight":
        half_width = 0.5 * geometry_x
        half_height = 0.5 * geometry_y
        corners = (
            (-half_width, -half_height, 0.0),
            (half_width, -half_height, 0.0),
            (half_width, half_height, 0.0),
            (-half_width, half_height, 0.0),
        )
        primitives = [
            _line(corner, corners[(index + 1) % len(corners)])
            for index, corner in enumerate(corners)
        ]
        ray_offset = half_width * 0.64
        return primitives + _emission_rays(
            ((-ray_offset, 0.0, 0.0), (0.0, 0.0, 0.0), (ray_offset, 0.0, 0.0)),
            0.75 * geometry_z,
        )
    if light_type == "DiskLight":
        radius = geometry_x
        ray_offset = radius * 0.59
        return [_arc(radius, 2)] + _emission_rays(
            ((-ray_offset, 0.0, 0.0), (0.0, 0.0, 0.0), (ray_offset, 0.0, 0.0)),
            0.75 * geometry_z,
        )
    if light_type == "CylinderLight":
        radius = geometry_x
        half_length = 0.5 * geometry_z
        primitives = [_arc(radius, 2, -half_length), _arc(radius, 2, half_length)]
        for x, y in ((-radius, 0.0), (radius, 0.0), (0.0, -radius), (0.0, radius)):
            primitives.append(_line((x, y, -half_length), (x, y, half_length)))
        return primitives
    return []


def build_light_geometry(
    light_type: str,
    geometry: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> None:
    """Emit a world-space silhouette and local ``-Z`` emission direction."""
    for primitive in light_geometry_primitives(light_type, geometry):
        if primitive[0] == "line":
            sc.Line(
                list(primitive[1]),
                list(primitive[2]),
                color=LIGHT_GIZMO_COLOR,
                thickness=LIGHT_GIZMO_THICKNESS,
            )
            continue
        _, radius, axis, z_offset = primitive
        if z_offset:
            with sc.Transform(transform=_translation_matrix(0.0, 0.0, z_offset)):
                _emit_arc(radius, axis)
        else:
            _emit_arc(radius, axis)


def _emit_arc(radius: float, axis: int) -> Any:
    return sc.Arc(
        radius,
        color=LIGHT_GIZMO_COLOR,
        thickness=LIGHT_GIZMO_THICKNESS,
        axis=axis,
        wireframe=True,
        sector=False,
    )


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
    "light_geometry_primitives",
    "normalized_light_geometry",
]

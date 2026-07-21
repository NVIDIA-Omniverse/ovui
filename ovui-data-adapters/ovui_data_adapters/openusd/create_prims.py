# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Create-menu OpenUSD prim authoring helpers.

The mesh evaluators in this module are standalone ports of Kit's primitive
mesh evaluators. They intentionally depend only on ``pxr``;
there are no Kit, Carbonite, settings, UI, or command-registry dependencies.
When the application supplies an undo manager, menu-created prims are pushed
through the same command stack as other stage edits.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from numbers import Number
from typing import Any, Callable

from ovui_data_adapters.common import Command

MESH_MENU_ORDER = ("Cone", "Cube", "Cylinder", "Disk", "Plane", "Sphere", "Torus")
SHAPE_MENU_ORDER = ("Capsule", "Cone", "Cube", "Cylinder", "Sphere")
LIGHT_MENU_ORDER = (
    ("Cylinder Light", "CylinderLight"),
    ("Disk Light", "DiskLight"),
    ("Distant Light", "DistantLight"),
    ("Dome Light", "DomeLight"),
    ("Rect Light", "RectLight"),
    ("Sphere Light", "SphereLight"),
)

DEFAULT_HALF_SCALE_CM = 50.0
MESH_TYPES_WITH_ZERO_ABOVE_GROUND_OFFSET = frozenset({"Disk", "Plane"})
LIGHT_TYPES_WITHOUT_SHAPING_API = frozenset({"DistantLight", "DomeLight"})
DISTANT_LIGHT_Y_UP_EULER = (315.0, 0.0, 0.0)
DISTANT_LIGHT_Z_UP_EULER = (45.0, 0.0, 90.0)
DOME_LIGHT_Y_UP_EULER = (0.0, 270.0, 0.0)
DOME_LIGHT_Z_UP_EULER = (-270.0, 0.0, 270.0)
Z_UP_CAMERA_AND_LIGHT_EULER = (90.0, 0.0, 90.0)
SHAPING_CONE_ANGLE_DEGREES = 180.0


class _CreatePrimCommand(Command):
    """Undoable wrapper for Create-menu USD authoring callbacks."""

    def __init__(
        self,
        stage: Any,
        label: str,
        author_fn: Callable[[], Any | None],
    ) -> None:
        self._stage = stage
        self._label = label
        self._author_fn = author_fn
        self._path: Any | None = None
        self._prim: Any | None = None
        self._delete_command: Any | None = None

    @property
    def label(self) -> str:
        return self._label

    @property
    def prim(self) -> Any | None:
        return self._prim

    def do(self) -> None:
        if self._delete_command is not None:
            self._delete_command.undo()
            self._delete_command = None
            self._prim = self._stage.GetPrimAtPath(self._path)
            return

        prim = self._author_fn()
        self._prim = prim
        if prim:
            self._path = prim.GetPath()

    def undo(self) -> None:
        if self._path is None:
            return
        from ovui_data_adapters.openusd.commands import DeletePrimCommand

        self._delete_command = DeletePrimCommand(self._stage, self._path)
        self._delete_command.do()
        self._prim = None


class AbstractShapeEvaluator:
    """Base interface for procedural mesh evaluators."""

    def __init__(self, attributes: dict[str, Any]):
        self._attributes = attributes

    def eval(self, **kwargs: Any) -> tuple[list[Any], list[Any], list[Any], list[int], list[int]]:
        raise NotImplementedError("Eval must be implemented for this shape.")

    @staticmethod
    def get_default_half_scale() -> float:
        return DEFAULT_HALF_SCALE_CM


@dataclass(frozen=True)
class MeshTopology:
    points: tuple[Any, ...]
    normals: tuple[Any, ...]
    st: tuple[Any, ...]
    face_vertex_indices: tuple[int, ...]
    face_vertex_counts: tuple[int, ...]


def _gf() -> Any:
    from pxr import Gf

    return Gf


def _vec3f(value: Any) -> Any:
    Gf = _gf()
    if isinstance(value, Gf.Vec3f):
        return value
    if isinstance(value, (tuple, list)):
        return Gf.Vec3f(*value)
    return Gf.Vec3f(value)


def inverse_u(uv: Any) -> Any:
    Gf = _gf()
    return Gf.Vec2f(1 - uv[0], uv[1])


def inverse_v(uv: Any) -> Any:
    Gf = _gf()
    return Gf.Vec2f(uv[0], 1 - uv[1])


def transform_point(point: Any, origin: Any, half_scale: float) -> Any:
    return half_scale * point + _vec3f(origin)


def generate_circle_points(
    up_axis: str,
    num_points: int,
    delta: float,
    center_point: Any | None = None,
) -> tuple[list[Any], list[Any]]:
    Gf = _gf()
    center = Gf.Vec3f(0.0) if center_point is None else _vec3f(center_point)
    points: list[Any] = []
    point_sts: list[Any] = []

    for i in range(num_points):
        theta = i * delta * math.pi * 2
        if up_axis == "Y":
            point = Gf.Vec3f(math.cos(theta), 0.0, math.sin(theta))
            st = Gf.Vec2f(1.0 - point[0] / 2.0, (1.0 + point[2]) / 2.0)
        else:
            point = Gf.Vec3f(math.cos(theta), math.sin(theta), 0.0)
            st = Gf.Vec2f((1.0 - point[0]) / 2.0, (1.0 + point[1]) / 2.0)
        point_sts.append(st)
        points.append(point + center)

    return points, point_sts


def generate_disk(
    center_point: Any,
    u_patches: int,
    v_patches: int,
    origin: Any,
    half_scale: float,
    up_axis: str = "Y",
) -> tuple[list[Any], list[Any], list[Any], list[int], list[int]]:
    Gf = _gf()
    v_delta = 1.0 / v_patches

    num_u_verts = u_patches
    num_v_verts = v_patches + 1

    points: list[Any] = []
    normals: list[Any] = []
    sts: list[Any] = []
    face_indices: list[int] = []
    face_vertex_counts: list[int] = []

    center_point = transform_point(center_point, origin, half_scale)
    circle_points, _ = generate_circle_points(up_axis, u_patches, 1.0 / u_patches)
    for i in range(num_v_verts - 1):
        v = v_delta * i
        for j in range(num_u_verts):
            point = transform_point(circle_points[j], (0, 0, 0), half_scale * (1 - v))
            points.append(point + center_point)

    points.append(center_point)

    def calc_index(i: int, j: int) -> int:
        ii = i if i < num_u_verts else 0
        base_index = j * num_u_verts
        if j == num_v_verts - 1:
            return base_index
        return base_index + ii

    def get_uv(i: int, j: int) -> Any:
        vindex = calc_index(i, j)
        point = (points[vindex] - _vec3f(origin)) / half_scale
        if up_axis == "Y":
            return (Gf.Vec2f(-point[0], -point[2]) + Gf.Vec2f(1, 1)) / 2
        return (Gf.Vec2f(point[0], point[1]) + Gf.Vec2f(1)) / 2

    for j in range(v_patches):
        for i in range(u_patches):
            vindex00 = calc_index(i, j)
            vindex10 = calc_index(i + 1, j)
            vindex11 = calc_index(i + 1, j + 1)
            vindex01 = calc_index(i, j + 1)
            uv00 = get_uv(i, j)
            uv10 = get_uv(i + 1, j)
            uv11 = get_uv(i + 1, j + 1)
            uv01 = get_uv(i, j + 1)

            if up_axis == "Y":
                if vindex11 == vindex01:
                    sts.extend([inverse_u(uv00), inverse_u(uv01), inverse_u(uv10)])
                    face_indices.extend((vindex00, vindex01, vindex10))
                else:
                    sts.extend([inverse_u(uv00), inverse_u(uv01), inverse_u(uv11), inverse_u(uv10)])
                    face_indices.extend((vindex00, vindex01, vindex11, vindex10))
                normal = Gf.Vec3f(0.0, 1.0, 0.0)
            else:
                if vindex11 == vindex01:
                    sts.extend([uv00, uv10, uv01])
                    face_indices.extend((vindex00, vindex10, vindex01))
                else:
                    sts.extend([uv00, uv10, uv11, uv01])
                    face_indices.extend((vindex00, vindex10, vindex11, vindex01))
                normal = Gf.Vec3f(0.0, 0.0, 1.0)

            if vindex11 == vindex01:
                face_vertex_counts.append(3)
                normals.extend([normal] * 3)
            else:
                face_vertex_counts.append(4)
                normals.extend([normal] * 4)

    return points, normals, sts, face_indices, face_vertex_counts


def generate_plane(
    origin: Any,
    half_scale: Any,
    u_patches: int,
    v_patches: int,
    up_axis: str,
) -> tuple[list[Any], list[Any], list[Any], list[int], list[int]]:
    Gf = _gf()
    if isinstance(half_scale, Number):
        w, h, d = half_scale, half_scale, half_scale
    else:
        w, h, d = half_scale
    x, y, z = origin[0], origin[1], origin[2]

    num_u_verts = u_patches + 1
    num_v_verts = v_patches + 1

    points: list[Any] = []
    normals: list[Any] = []
    sts: list[Any] = []
    face_indices: list[int] = []
    face_vertex_counts: list[int] = []

    u_delta = 1.0 / u_patches
    v_delta = 1.0 / v_patches
    if up_axis == "Y":
        w_delta = 2.0 * w * u_delta
        h_delta = 2.0 * d * v_delta
        bottom_left = Gf.Vec3f(x - w, y, z - d)
        for i in range(num_v_verts):
            for j in range(num_u_verts):
                points.append(bottom_left + Gf.Vec3f(j * w_delta, 0.0, i * h_delta))
    elif up_axis == "Z":
        w_delta = 2.0 * w / u_patches
        h_delta = 2.0 * h / v_patches
        bottom_left = Gf.Vec3f(x - w, y - h, z)
        for i in range(num_v_verts):
            for j in range(num_u_verts):
                points.append(bottom_left + Gf.Vec3f(j * w_delta, i * h_delta, 0.0))
    else:
        w_delta = 2.0 * h / u_patches
        h_delta = 2.0 * d / v_patches
        bottom_left = Gf.Vec3f(x, y - h, z - d)
        for i in range(num_v_verts):
            for j in range(num_u_verts):
                points.append(bottom_left + Gf.Vec3f(0, j * w_delta, i * h_delta))

    def calc_index(i: int, j: int) -> int:
        ii = i if i < num_u_verts else 0
        jj = j if j < num_v_verts else 0
        return jj * num_u_verts + ii

    def get_uv(i: int, j: int) -> Any:
        u = i * u_delta if i < num_u_verts else 1.0
        if up_axis == "Y":
            v = 1 - j * v_delta if j < num_v_verts else 0.0
        else:
            v = j * v_delta if j < num_v_verts else 1.0
        return Gf.Vec2f(u, v)

    for j in range(v_patches):
        for i in range(u_patches):
            vindex00 = calc_index(i, j)
            vindex10 = calc_index(i + 1, j)
            vindex11 = calc_index(i + 1, j + 1)
            vindex01 = calc_index(i, j + 1)
            uv00 = get_uv(i, j)
            uv10 = get_uv(i + 1, j)
            uv11 = get_uv(i + 1, j + 1)
            uv01 = get_uv(i, j + 1)

            if up_axis == "Y":
                sts.extend([uv00, uv01, uv11, uv10])
                face_indices.extend((vindex00, vindex01, vindex11, vindex10))
                normal = Gf.Vec3f(0.0, 1.0, 0.0)
            elif up_axis == "Z":
                sts.extend([uv00, uv10, uv11, uv01])
                face_indices.extend((vindex00, vindex10, vindex11, vindex01))
                normal = Gf.Vec3f(0.0, 0.0, 1.0)
            else:
                sts.extend([uv00, uv01, uv11, uv10])
                face_indices.extend((vindex00, vindex01, vindex11, vindex10))
                normal = Gf.Vec3f(0.0, 1.0, 0.0)
            face_vertex_counts.append(4)
            normals.extend([normal] * 4)

    return points, normals, sts, face_indices, face_vertex_counts


def modify_winding_order(face_counts: list[int], values: list[Any]) -> None:
    total = 0
    for count in face_counts:
        if count >= 3:
            start = total + 1
            end = total + count
            values[start:end] = values[start:end][::-1]
        total += count


class PlaneEvaluator(AbstractShapeEvaluator):
    def eval(self, **kwargs: Any) -> tuple[list[Any], list[Any], list[Any], list[int], list[int]]:
        half_scale = _positive(kwargs.get("half_scale"), self.get_default_half_scale())
        up_axis = kwargs.get("up_axis", "Y")
        Gf = _gf()
        u_patches = max(int(kwargs.get("u_patches", 1)), 1)
        v_patches = max(int(kwargs.get("v_patches", 1)), 1)
        return generate_plane(Gf.Vec3f(0.0), [half_scale, half_scale, half_scale], u_patches, v_patches, up_axis)


class DiskEvaluator(AbstractShapeEvaluator):
    def eval(self, **kwargs: Any) -> tuple[list[Any], list[Any], list[Any], list[int], list[int]]:
        half_scale = _positive(kwargs.get("half_scale"), self.get_default_half_scale())
        up_axis = kwargs.get("up_axis", "Y")
        Gf = _gf()
        u_patches = max(int(kwargs.get("u_patches", 32)), 3)
        v_patches = max(int(kwargs.get("v_patches", 1)), 1)
        return generate_disk(Gf.Vec3f(0.0), u_patches, v_patches, Gf.Vec3f(0.0), half_scale, up_axis)


class CubeEvaluator(AbstractShapeEvaluator):
    def eval(self, **kwargs: Any) -> tuple[list[Any], list[Any], list[Any], list[int], list[int]]:
        half_scale = _positive(kwargs.get("half_scale"), self.get_default_half_scale())
        Gf = _gf()
        origin = Gf.Vec3f(0.0)
        u_patches = max(int(kwargs.get("u_patches", 1)), 1)
        v_patches = max(int(kwargs.get("v_patches", 1)), 1)
        w_patches = max(int(kwargs.get("w_patches", 1)), 1)
        x, y, z = origin

        xy = generate_plane(Gf.Vec3f(x, y, z + half_scale), half_scale, u_patches, v_patches, "Z")
        xz = generate_plane(Gf.Vec3f(x, y - half_scale, z), half_scale, u_patches, w_patches, "Y")
        yz = generate_plane(Gf.Vec3f(x - half_scale, y, z), half_scale, v_patches, w_patches, "X")

        xy_points, xy_normals, xy_sts, xy_indices, xy_counts = xy
        xz_points, xz_normals, xz_sts, xz_indices, xz_counts = xz
        yz_points, yz_normals, yz_sts, yz_indices, yz_counts = yz

        points: list[Any] = []
        normals: list[Any] = []
        sts: list[Any] = []
        face_indices: list[int] = []
        face_vertex_counts: list[int] = []

        points.extend(xy_points)
        normals.extend([Gf.Vec3f(0, 0, 1)] * len(xy_normals))
        sts.extend(xy_sts)
        face_indices.extend(xy_indices)
        face_vertex_counts.extend(xy_counts)

        total_indices = len(points)
        points.extend([point + Gf.Vec3f(0, 0, -2.0 * half_scale) for point in xy_points])
        normals.extend([Gf.Vec3f(0, 0, -1)] * len(xy_normals))
        modify_winding_order(xy_counts, xy_sts)
        sts.extend([Gf.Vec2f(1 - st[0], st[1]) for st in xy_sts])
        plane_face_indices = [index + total_indices for index in xy_indices]
        modify_winding_order(xy_counts, plane_face_indices)
        face_indices.extend(plane_face_indices)
        face_vertex_counts.extend(xy_counts)

        total_indices = len(points)
        points.extend([point + Gf.Vec3f(0, 2.0 * half_scale, 0) for point in xz_points])
        normals.extend([Gf.Vec3f(0, 1, 0)] * len(xz_normals))
        sts.extend(xz_sts)
        face_indices.extend([index + total_indices for index in xz_indices])
        face_vertex_counts.extend(xz_counts)

        total_indices = len(points)
        points.extend(xz_points)
        normals.extend([Gf.Vec3f(0, -1, 0)] * len(xz_normals))
        modify_winding_order(xz_counts, xz_sts)
        sts.extend([Gf.Vec2f(st[0], 1 - st[1]) for st in xz_sts])
        plane_face_indices = [index + total_indices for index in xz_indices]
        modify_winding_order(xz_counts, plane_face_indices)
        face_indices.extend(plane_face_indices)
        face_vertex_counts.extend(xz_counts)

        total_indices = len(points)
        points.extend(yz_points)
        normals.extend([Gf.Vec3f(-1, 0, 0)] * len(yz_normals))
        sts.extend([Gf.Vec2f(st[1], st[0]) for st in yz_sts])
        face_indices.extend([index + total_indices for index in yz_indices])
        face_vertex_counts.extend(yz_counts)

        total_indices = len(points)
        points.extend([point + Gf.Vec3f(2.0 * half_scale, 0, 0) for point in yz_points])
        normals.extend([Gf.Vec3f(1, 0, 0)] * len(yz_normals))
        modify_winding_order(yz_counts, yz_sts)
        sts.extend([Gf.Vec2f(1 - st[1], st[0]) for st in yz_sts])
        plane_face_indices = [index + total_indices for index in yz_indices]
        modify_winding_order(yz_counts, plane_face_indices)
        face_indices.extend(plane_face_indices)
        face_vertex_counts.extend(yz_counts)

        keep = [True] * len(points)
        index_remap = [-1] * len(points)
        keep_points: list[Any] = []
        for i, point in enumerate(points):
            if not keep[i]:
                continue
            keep_points.append(point)
            index_remap[i] = len(keep_points) - 1
            for j in range(i + 1, len(points)):
                if Gf.IsClose(points[j], point, 1e-6):
                    keep[j] = False
                    index_remap[j] = len(keep_points) - 1

        for i, index in enumerate(face_indices):
            face_indices[i] = index_remap[index]

        return keep_points, normals, sts, face_indices, face_vertex_counts


class ConeEvaluator(AbstractShapeEvaluator):
    radius = 1.0
    height = 2.0

    def _eval(self, up_axis: str, u: float, v: float) -> tuple[Any, Any]:
        Gf = _gf()
        theta = u * 2.0 * math.pi
        x = (1 - v) * math.cos(theta)
        h = v * self.height - 1
        if up_axis == "Y":
            z = (1 - v) * math.sin(theta)
            point = Gf.Vec3f(x, h, z)
            dpdu = Gf.Vec3f(-2.0 * math.pi * z, 0.0, 2.0 * math.pi * x)
            dpdv = Gf.Vec3f(-x / (1 - v), self.height, -z / (1 - v))
            normal = (dpdv ^ dpdu).GetNormalized()
        else:
            y = (1 - v) * math.sin(theta)
            point = Gf.Vec3f(x, y, h)
            dpdu = Gf.Vec3f(-2.0 * math.pi * y, 2.0 * math.pi * x, 0)
            dpdv = Gf.Vec3f(-x / (1 - v), -y / (1 - v), self.height)
            normal = (dpdu ^ dpdv).GetNormalized()
        return point, normal

    def eval(self, **kwargs: Any) -> tuple[list[Any], list[Any], list[Any], list[int], list[int]]:
        Gf = _gf()
        half_scale = _positive(kwargs.get("half_scale"), self.get_default_half_scale())
        up_axis = kwargs.get("up_axis", "Y")
        origin = Gf.Vec3f(0.0)
        u_patches = max(int(kwargs.get("u_patches", 64)), 3)
        v_patches = max(int(kwargs.get("v_patches", 3)), 1)
        w_patches = max(int(kwargs.get("w_patches", 1)), 1)
        accuracy = 0.00001
        u_delta = 1.0 / u_patches
        v_delta = (1.0 - accuracy) / v_patches
        num_u_verts = u_patches
        num_v_verts = v_patches + 1

        points: list[Any] = []
        point_normals: list[Any] = []
        normals: list[Any] = []
        sts: list[Any] = []
        face_indices: list[int] = []
        face_vertex_counts: list[int] = []

        for j in range(num_v_verts):
            for i in range(num_u_verts):
                point, normal = self._eval(up_axis, i * u_delta, j * v_delta)
                points.append(transform_point(point, origin, half_scale))
                point_normals.append(normal)

        def calc_index(i: int, j: int) -> int:
            ii = i if i < num_u_verts else 0
            return j * num_u_verts + ii

        def get_uv(i: int, j: int) -> Any:
            u = 1 - i * u_delta if i < num_u_verts else 0.0
            v = j * v_delta if j != num_v_verts - 1 else 1.0
            return Gf.Vec2f(u, v)

        for j in range(v_patches):
            for i in range(u_patches):
                vindex00 = calc_index(i, j)
                vindex10 = calc_index(i + 1, j)
                vindex11 = calc_index(i + 1, j + 1)
                vindex01 = calc_index(i, j + 1)
                uv00 = get_uv(i, j)
                uv10 = get_uv(i + 1, j)
                uv11 = get_uv(i + 1, j + 1)
                uv01 = get_uv(i, j + 1)
                if up_axis == "Y":
                    sts.extend([uv00, uv01, uv11, uv10])
                    face_indices.extend((vindex00, vindex01, vindex11, vindex10))
                    normals.extend([
                        point_normals[vindex00],
                        point_normals[vindex01],
                        point_normals[vindex11],
                        point_normals[vindex10],
                    ])
                else:
                    sts.extend([inverse_u(uv00), inverse_u(uv10), inverse_u(uv11), inverse_u(uv01)])
                    face_indices.extend((vindex00, vindex10, vindex11, vindex01))
                    normals.extend([
                        point_normals[vindex00],
                        point_normals[vindex10],
                        point_normals[vindex11],
                        point_normals[vindex01],
                    ])
                face_vertex_counts.append(4)

        if up_axis == "Y":
            bottom_center_point = Gf.Vec3f(0, -1, 0)
            top_center_point = Gf.Vec3f(0, 1 - accuracy, 0)
        else:
            bottom_center_point = Gf.Vec3f(0, 0, -1)
            top_center_point = Gf.Vec3f(0, 0, 1 - accuracy)

        def add_hat(
            center_point: Any,
            rim_points_start_index: int,
            cap_patches: int,
            invert_wind_order: bool = False,
        ) -> None:
            bt_points, _, bt_sts, bt_indices, bt_counts = generate_disk(
                center_point, u_patches, cap_patches, origin, half_scale, up_axis
            )
            total_points = len(points)
            points.extend(bt_points[num_u_verts:])

            if invert_wind_order:
                modify_winding_order(bt_counts, bt_sts)
                sts.extend([inverse_v(st) for st in bt_sts])
            else:
                sts.extend(bt_sts)
            face_vertex_counts.extend(bt_counts)
            normals.extend([center_point] * len(bt_indices))

            for idx, index in enumerate(bt_indices):
                if index >= num_u_verts:
                    bt_indices[idx] += total_points - num_u_verts
                else:
                    bt_indices[idx] += rim_points_start_index
            if invert_wind_order:
                modify_winding_order(bt_counts, bt_indices)
            face_indices.extend(bt_indices)

        add_hat(top_center_point, len(points) - num_u_verts, 1)
        add_hat(bottom_center_point, 0, w_patches, True)
        return points, normals, sts, face_indices, face_vertex_counts


class CylinderEvaluator(AbstractShapeEvaluator):
    def eval(self, **kwargs: Any) -> tuple[list[Any], list[Any], list[Any], list[int], list[int]]:
        Gf = _gf()
        half_scale = _positive(kwargs.get("half_scale"), self.get_default_half_scale())
        up_axis = kwargs.get("up_axis", "Y")
        origin = Gf.Vec3f(0.0)
        u_patches = max(int(kwargs.get("u_patches", 32)), 3)
        v_patches = max(int(kwargs.get("v_patches", 1)), 1)
        w_patches = max(int(kwargs.get("w_patches", 1)), 1)
        u_delta = 1.0 / u_patches
        v_delta = 1.0 / v_patches
        num_u_verts = u_patches
        num_v_verts = v_patches + 1

        points: list[Any] = []
        normals: list[Any] = []
        sts: list[Any] = []
        face_indices: list[int] = []
        face_vertex_counts: list[int] = []

        circle_points, _ = generate_circle_points(up_axis, num_u_verts, u_delta)
        for j in range(num_v_verts):
            for i in range(num_u_verts):
                v = j * v_delta
                point = Gf.Vec3f(circle_points[i])
                if up_axis == "Y":
                    point[1] = 2.0 * (v - 0.5)
                else:
                    point[2] = 2.0 * (v - 0.5)
                points.append(transform_point(point, origin, half_scale))

        def calc_index(i: int, j: int) -> int:
            ii = i if i < num_u_verts else 0
            jj = j if j < num_v_verts else 0
            return jj * num_u_verts + ii

        def get_uv(i: int, j: int) -> Any:
            u = 1 - i * u_delta if i < num_u_verts else 0.0
            v = j * v_delta if j < num_v_verts else 1.0
            return Gf.Vec2f(u, v)

        for j in range(v_patches):
            for i in range(u_patches):
                vindex00 = calc_index(i, j)
                vindex10 = calc_index(i + 1, j)
                vindex11 = calc_index(i + 1, j + 1)
                vindex01 = calc_index(i, j + 1)
                uv00 = get_uv(i, j)
                uv10 = get_uv(i + 1, j)
                uv11 = get_uv(i + 1, j + 1)
                uv01 = get_uv(i, j + 1)
                p00 = points[vindex00]
                p10 = points[vindex10]
                p11 = points[vindex11]
                p01 = points[vindex01]
                if up_axis == "Y":
                    sts.extend([uv00, uv01, uv11, uv10])
                    face_indices.extend((vindex00, vindex01, vindex11, vindex10))
                    normals.extend([
                        Gf.Vec3f(p00[0], 0, p00[2]),
                        Gf.Vec3f(p01[0], 0, p01[2]),
                        Gf.Vec3f(p11[0], 0, p11[2]),
                        Gf.Vec3f(p10[0], 0, p10[2]),
                    ])
                else:
                    sts.extend([inverse_u(uv00), inverse_u(uv10), inverse_u(uv11), inverse_u(uv01)])
                    face_indices.extend((vindex00, vindex10, vindex11, vindex01))
                    normals.extend([
                        Gf.Vec3f(p00[0], p00[1], 0),
                        Gf.Vec3f(p10[0], p10[1], 0),
                        Gf.Vec3f(p11[0], p11[1], 0),
                        Gf.Vec3f(p01[0], p01[1], 0),
                    ])
                face_vertex_counts.append(4)

        if up_axis == "Y":
            bottom_center_point = Gf.Vec3f(0, -1, 0)
            top_center_point = Gf.Vec3f(0, 1, 0)
        else:
            bottom_center_point = Gf.Vec3f(0, 0, -1)
            top_center_point = Gf.Vec3f(0, 0, 1)

        def add_hat(
            center_point: Any,
            rim_points_start_index: int,
            cap_patches: int,
            invert_wind_order: bool = False,
        ) -> None:
            bt_points, _, bt_sts, bt_indices, bt_counts = generate_disk(
                center_point, u_patches, cap_patches, origin, half_scale, up_axis
            )
            total_points = len(points)
            points.extend(bt_points[num_u_verts:])
            if invert_wind_order:
                modify_winding_order(bt_counts, bt_sts)
                sts.extend([inverse_v(st) for st in bt_sts])
            else:
                sts.extend(bt_sts)
            face_vertex_counts.extend(bt_counts)
            normals.extend([center_point] * len(bt_indices))
            for idx, index in enumerate(bt_indices):
                if index >= num_u_verts:
                    bt_indices[idx] += total_points - num_u_verts
                else:
                    bt_indices[idx] += rim_points_start_index
            if invert_wind_order:
                modify_winding_order(bt_counts, bt_indices)
            face_indices.extend(bt_indices)

        top_hat_start_index = len(points) - num_u_verts
        add_hat(bottom_center_point, 0, w_patches, True)
        add_hat(top_center_point, top_hat_start_index, w_patches)
        return points, normals, sts, face_indices, face_vertex_counts


class SphereEvaluator(AbstractShapeEvaluator):
    def _eval(self, u: float, v: float, up_axis: str) -> Any:
        Gf = _gf()
        theta = u * 2.0 * math.pi
        phi = (v - 0.5) * math.pi
        cos_phi = math.cos(phi)
        if up_axis == "Y":
            return Gf.Vec3f(cos_phi * math.cos(theta), math.sin(phi), cos_phi * math.sin(theta))
        return Gf.Vec3f(cos_phi * math.cos(theta), cos_phi * math.sin(theta), math.sin(phi))

    def eval(self, **kwargs: Any) -> tuple[list[Any], list[Any], list[Any], list[int], list[int]]:
        Gf = _gf()
        half_scale = _positive(kwargs.get("half_scale"), self.get_default_half_scale())
        up_axis = kwargs.get("up_axis", "Y")
        origin = Gf.Vec3f(0.0)
        u_patches = max(int(kwargs.get("u_patches", 32)), 3)
        v_patches = max(int(kwargs.get("v_patches", 16)), 2)
        u_delta = 1.0 / u_patches
        v_delta = 1.0 / v_patches
        num_u_verts = u_patches
        num_v_verts = v_patches + 1

        points: list[Any] = []
        normals: list[Any] = []
        sts: list[Any] = []
        face_indices: list[int] = []
        face_vertex_counts: list[int] = []

        bottom_point = Gf.Vec3f(0.0, -1.0, 0.0) if up_axis == "Y" else Gf.Vec3f(0.0, 0.0, -1.0)
        points.append(transform_point(bottom_point, origin, half_scale))
        for j in range(1, num_v_verts - 1):
            for i in range(num_u_verts):
                points.append(
                    Gf.Vec3f(
                        transform_point(
                            self._eval(i * u_delta, j * v_delta, up_axis),
                            origin,
                            half_scale,
                        )
                    )
                )
        top_point = Gf.Vec3f(0.0, 1.0, 0.0) if up_axis == "Y" else Gf.Vec3f(0.0, 0.0, 1.0)
        points.append(transform_point(top_point, origin, half_scale))

        def calc_index(i: int, j: int) -> int:
            if j == 0:
                return 0
            if j == num_v_verts - 1:
                return len(points) - 1
            ii = i if i < num_u_verts else 0
            return (j - 1) * num_u_verts + ii + 1

        def get_uv(i: int, j: int) -> Any:
            u = 1 - i * u_delta if up_axis == "Y" else i * u_delta
            return Gf.Vec2f(u, j * v_delta)

        for j in range(v_patches):
            for i in range(u_patches):
                vindex00 = calc_index(i, j)
                vindex10 = calc_index(i + 1, j)
                vindex11 = calc_index(i + 1, j + 1)
                vindex01 = calc_index(i, j + 1)
                st00 = get_uv(i, j)
                st10 = get_uv(i + 1, j)
                st11 = get_uv(i + 1, j + 1)
                st01 = get_uv(i, j + 1)
                p0 = points[vindex00]
                p1 = points[vindex10]
                p2 = points[vindex11]
                p3 = points[vindex01]
                if up_axis == "Y":
                    if vindex11 == vindex01:
                        sts.extend([st00, st01, st10])
                        face_indices.extend((vindex00, vindex01, vindex10))
                        face_vertex_counts.append(3)
                        normals.extend([p0, p3, p1])
                    elif vindex00 == vindex10:
                        sts.extend([st00, st01, st11])
                        face_indices.extend((vindex00, vindex01, vindex11))
                        face_vertex_counts.append(3)
                        normals.extend([p0, p3, p2])
                    else:
                        sts.extend([st00, st01, st11, st10])
                        face_indices.extend((vindex00, vindex01, vindex11, vindex10))
                        face_vertex_counts.append(4)
                        normals.extend([p0, p3, p2, p1])
                else:
                    if vindex11 == vindex01:
                        sts.extend([st00, st10, st01])
                        face_indices.extend((vindex00, vindex10, vindex01))
                        face_vertex_counts.append(3)
                        normals.extend([p0, p1, p3])
                    elif vindex00 == vindex10:
                        sts.extend([st00, st11, st01])
                        face_indices.extend((vindex00, vindex11, vindex01))
                        face_vertex_counts.append(3)
                        normals.extend([p0, p2, p3])
                    else:
                        sts.extend([st00, st10, st11, st01])
                        face_indices.extend((vindex00, vindex10, vindex11, vindex01))
                        face_vertex_counts.append(4)
                        normals.extend([p0, p1, p2, p3])

        return points, normals, sts, face_indices, face_vertex_counts


class TorusEvaluator(AbstractShapeEvaluator):
    hole_radius = 1.0
    tube_radius = 0.5

    def _eval(self, up_axis: str, u: float, v: float) -> tuple[Any, Any]:
        Gf = _gf()
        theta = u * 2.0 * math.pi
        phi = v * 2.0 * math.pi - 0.5 * math.pi
        rad_cos_phi = self.tube_radius * math.cos(phi)
        cos_theta = math.cos(theta)
        sin_phi = math.sin(phi)
        sin_theta = math.sin(theta)
        x = (self.hole_radius + rad_cos_phi) * cos_theta
        nx = self.hole_radius * cos_theta
        if up_axis == "Y":
            y = self.tube_radius * sin_phi
            z = (self.hole_radius + rad_cos_phi) * sin_theta
            ny = 0
            nz = self.hole_radius * sin_theta
        else:
            y = (self.hole_radius + rad_cos_phi) * sin_theta
            z = self.tube_radius * sin_phi
            ny = self.hole_radius * sin_theta
            nz = 0
        point = Gf.Vec3f(x, y, z)
        normal = Gf.Vec3f(x - nx, y - ny, z - nz).GetNormalized()
        return point, normal

    def eval(self, **kwargs: Any) -> tuple[list[Any], list[Any], list[Any], list[int], list[int]]:
        Gf = _gf()
        half_scale = _positive(kwargs.get("half_scale"), self.get_default_half_scale())
        up_axis = kwargs.get("up_axis", "Y")
        origin = Gf.Vec3f(0.0)
        u_patches = max(int(kwargs.get("u_patches", 32)), 3)
        v_patches = max(int(kwargs.get("v_patches", 32)), 3)
        u_delta = 1.0 / u_patches
        v_delta = 1.0 / v_patches
        num_u_verts = u_patches
        num_v_verts = v_patches
        points: list[Any] = []
        point_normals: list[Any] = []
        sts: list[Any] = []
        face_indices: list[int] = []
        face_vertex_counts: list[int] = []

        for j in range(num_v_verts):
            for i in range(num_u_verts):
                point, normal = self._eval(up_axis, i * u_delta, j * v_delta)
                points.append(transform_point(point, origin, half_scale))
                point_normals.append(normal)

        def calc_index(i: int, j: int) -> int:
            ii = i if i < num_u_verts else 0
            jj = j if j < num_v_verts else 0
            return jj * num_u_verts + ii

        def get_uv(i: int, j: int) -> Any:
            if up_axis == "Y":
                u = 1 - i * u_delta if i < num_u_verts else 0.0
            else:
                u = i * u_delta if i < num_u_verts else 1.0
            v = j * v_delta if j < num_v_verts else 1.0
            return Gf.Vec2f(u, v)

        normals: list[Any] = []
        for j in range(v_patches):
            for i in range(u_patches):
                vindex00 = calc_index(i, j)
                vindex10 = calc_index(i + 1, j)
                vindex11 = calc_index(i + 1, j + 1)
                vindex01 = calc_index(i, j + 1)
                face_vertex_counts.append(4)
                if up_axis == "Y":
                    sts.extend([get_uv(i, j), get_uv(i, j + 1), get_uv(i + 1, j + 1), get_uv(i + 1, j)])
                    face_indices.extend((vindex00, vindex01, vindex11, vindex10))
                    normals.extend([
                        point_normals[vindex00],
                        point_normals[vindex01],
                        point_normals[vindex11],
                        point_normals[vindex10],
                    ])
                else:
                    sts.extend([get_uv(i, j), get_uv(i + 1, j), get_uv(i + 1, j + 1), get_uv(i, j + 1)])
                    face_indices.extend((vindex00, vindex10, vindex11, vindex01))
                    normals.extend([
                        point_normals[vindex00],
                        point_normals[vindex10],
                        point_normals[vindex11],
                        point_normals[vindex01],
                    ])

        return points, normals, sts, face_indices, face_vertex_counts


MESH_EVALUATORS: dict[str, type[AbstractShapeEvaluator]] = {
    "Cone": ConeEvaluator,
    "Cube": CubeEvaluator,
    "Cylinder": CylinderEvaluator,
    "Disk": DiskEvaluator,
    "Plane": PlaneEvaluator,
    "Sphere": SphereEvaluator,
    "Torus": TorusEvaluator,
}


def evaluate_mesh_topology(stage: Any, mesh_name: str) -> MeshTopology:
    """Return Kit-compatible mesh topology for ``mesh_name`` on ``stage``."""
    from pxr import Gf, UsdGeom

    evaluator_class = MESH_EVALUATORS.get(mesh_name)
    if evaluator_class is None:
        raise ValueError(f"Unsupported mesh primitive: {mesh_name}")

    evaluator = evaluator_class({})
    points, normals, sts, face_indices, face_vertex_counts = evaluator.eval(
        up_axis=str(UsdGeom.GetStageUpAxis(stage))
    )

    units = UsdGeom.GetStageMetersPerUnit(stage)
    if Gf.IsClose(units, 0.0, 1e-6):
        units = 0.01
    scale = 0.01 / units
    return MeshTopology(
        points=tuple(point * scale for point in points),
        normals=tuple(normals),
        st=tuple(sts),
        face_vertex_indices=tuple(int(index) for index in face_indices),
        face_vertex_counts=tuple(int(count) for count in face_vertex_counts),
    )


def mesh_above_ground_translate(stage: Any, mesh_name: str) -> Any:
    """Return the Kit-compatible default translate value for a mesh create."""
    return _mesh_above_ground_translate(stage, mesh_name)


def apply_default_xform_ops(
    prim: Any,
    translate_value: Any | None = None,
    rotate_value: Any | None = None,
    scale_value: Any | None = None,
) -> None:
    """Apply Kit-compatible default xform ops to ``prim``."""
    _apply_default_xform_ops(
        prim,
        translate_value=translate_value,
        rotate_value=rotate_value,
        scale_value=scale_value,
    )


def set_extent_from_plugins(prim: Any) -> None:
    """Author extent using USD's boundable extent plugins."""
    _set_extent_from_plugins(prim)


def _push_create_command(
    app: Any,
    stage: Any,
    label: str,
    author_fn: Callable[[], Any | None],
) -> Any | None:
    """Run a Create-menu authoring callback through undo when available."""
    undo_manager = getattr(app, "undo_manager", None)
    push = getattr(undo_manager, "push", None)
    if not callable(push):
        return author_fn()

    command = _CreatePrimCommand(stage, label, author_fn)
    push(command)
    return command.prim


def create_mesh_prim(app: Any, mesh_name: str) -> Any | None:
    """Create a procedural ``UsdGeom.Mesh`` primitive."""
    from pxr import Gf, Sdf, UsdGeom, Vt

    stage = _require_stage(app)
    if stage is None:
        return None
    evaluator_class = MESH_EVALUATORS.get(mesh_name)
    if evaluator_class is None:
        _show_error(f"Unsupported mesh primitive: {mesh_name}")
        return None

    def author() -> Any:
        path = get_next_free_prim_path(stage, mesh_name)
        up_axis = str(UsdGeom.GetStageUpAxis(stage))
        mesh = UsdGeom.Mesh.Define(stage, path)
        prim = mesh.GetPrim()
        _apply_default_xform_ops(
            prim,
            translate_value=_mesh_above_ground_translate(stage, mesh_name),
        )

        evaluator = evaluator_class({})
        points, normals, sts, point_indices, face_vertex_counts = evaluator.eval(up_axis=up_axis)

        units = UsdGeom.GetStageMetersPerUnit(stage)
        if Gf.IsClose(units, 0.0, 1e-6):
            units = 0.01
        scale = 0.01 / units
        points = [point * scale for point in points]

        mesh.GetPointsAttr().Set(Vt.Vec3fArray(points))
        mesh.GetNormalsAttr().Set(Vt.Vec3fArray(normals))
        mesh.GetFaceVertexIndicesAttr().Set(point_indices)
        mesh.GetFaceVertexCountsAttr().Set(face_vertex_counts)
        mesh.SetNormalsInterpolation("faceVarying")

        st_primvar = UsdGeom.PrimvarsAPI(prim).CreatePrimvar(
            "st",
            Sdf.ValueTypeNames.TexCoord2fArray,
        )
        st_primvar.SetInterpolation("faceVarying")
        st_primvar.Set(Vt.Vec2fArray(sts))
        mesh.CreateSubdivisionSchemeAttr("none")
        _set_extent_from_plugins(prim)
        return prim

    return _push_create_command(app, stage, f"Create {mesh_name}", author)


def create_shape_prim(app: Any, shape_name: str) -> Any | None:
    """Create a native USD geometry schema primitive."""
    from pxr import UsdGeom

    stage = _require_stage(app)
    if stage is None:
        return None
    schema_define = _shape_schema_defines().get(shape_name)
    if schema_define is None:
        _show_error(f"Unsupported shape primitive: {shape_name}")
        return None

    def author() -> Any:
        path = get_next_free_prim_path(stage, shape_name)
        schema = schema_define(stage, path)
        prim = schema.GetPrim()
        _set_authored_attributes(prim, get_geometry_standard_prim_attrs(stage)[shape_name])
        if shape_name in {"Capsule", "Cone", "Cylinder"}:
            axis_attr = prim.GetAttribute(str(UsdGeom.Tokens.axis))
            if axis_attr:
                axis_attr.Set(UsdGeom.GetStageUpAxis(stage))
        _apply_default_xform_ops(prim)
        _set_extent_from_plugins(prim)
        return prim

    return _push_create_command(app, stage, f"Create {shape_name}", author)


def create_light_prim(app: Any, light_type: str) -> Any | None:
    """Create a native ``UsdLux`` light primitive with Kit-compatible defaults."""
    stage = _require_stage(app)
    if stage is None:
        return None
    schema_define = _light_schema_defines().get(light_type)
    if schema_define is None:
        _show_error(f"Unsupported light primitive: {light_type}")
        return None

    def author() -> Any:
        path = get_next_free_prim_path(stage, light_type)
        schema = schema_define(stage, path)
        prim = schema.GetPrim()
        _set_authored_attributes(prim, dict(get_light_prim_attrs(stage)[light_type]))
        _apply_default_xform_ops(prim, rotate_value=_default_euler_for_prim(prim, stage))
        _apply_light_shaping_api(prim, light_type)
        return prim

    return _push_create_command(app, stage, f"Create {light_type}", author)


def create_camera(app: Any) -> Any | None:
    """Create a USD camera with Kit-style typed defaults."""
    from pxr import Gf, UsdGeom

    stage = _require_stage(app)
    if stage is None:
        return None
    def author() -> Any:
        camera = UsdGeom.Camera.Define(stage, get_next_free_prim_path(stage, "Camera"))
        prim = camera.GetPrim()
        camera.GetFocalLengthAttr().Set(18.147562)
        camera.GetFocusDistanceAttr().Set(400.0)
        camera.GetClippingRangeAttr().Set(Gf.Vec2f(1.0, 10000000.0))
        _apply_default_xform_ops(prim, rotate_value=_default_euler_for_prim(prim, stage))
        return prim

    return _push_create_command(app, stage, "Create Camera", author)


def create_scope(app: Any) -> Any | None:
    """Create a ``UsdGeom.Scope`` prim."""
    from pxr import UsdGeom

    stage = _require_stage(app)
    if stage is None:
        return None
    def author() -> Any:
        return UsdGeom.Scope.Define(stage, get_next_free_prim_path(stage, "Scope")).GetPrim()

    return _push_create_command(app, stage, "Create Scope", author)


def create_xform(app: Any) -> Any | None:
    """Create a ``UsdGeom.Xform`` prim."""
    from pxr import UsdGeom

    stage = _require_stage(app)
    if stage is None:
        return None
    def author() -> Any:
        xform = UsdGeom.Xform.Define(stage, get_next_free_prim_path(stage, "Xform"))
        prim = xform.GetPrim()
        _apply_default_xform_ops(prim)
        return prim

    return _push_create_command(app, stage, "Create Xform", author)


def create_usd_preview_surface_material(app: Any) -> Any | None:
    """Create a UsdShade material containing a UsdPreviewSurface shader."""
    from pxr import Gf, Sdf, UsdGeom, UsdShade

    stage = _require_stage(app)
    if stage is None:
        return None

    looks_path = _looks_scope_path(stage)
    if not stage.GetPrimAtPath(looks_path):
        UsdGeom.Scope.Define(stage, looks_path)

    material_path = get_next_free_path(stage, looks_path.AppendChild("PreviewSurface"))
    material = UsdShade.Material.Define(stage, material_path)
    shader = UsdShade.Shader.Define(stage, material_path.AppendChild("Shader"))
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.18, 0.18, 0.18))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.5)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    surface_output = shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput().ConnectToSource(surface_output)
    displacement_output = shader.CreateOutput("displacement", Sdf.ValueTypeNames.Token)
    material.CreateDisplacementOutput().ConnectToSource(displacement_output)
    return material.GetPrim()


def create_mesh_cone(app: Any) -> Any | None:
    return create_mesh_prim(app, "Cone")


def create_mesh_cube(app: Any) -> Any | None:
    return create_mesh_prim(app, "Cube")


def create_mesh_cylinder(app: Any) -> Any | None:
    return create_mesh_prim(app, "Cylinder")


def create_mesh_disk(app: Any) -> Any | None:
    return create_mesh_prim(app, "Disk")


def create_mesh_plane(app: Any) -> Any | None:
    return create_mesh_prim(app, "Plane")


def create_mesh_sphere(app: Any) -> Any | None:
    return create_mesh_prim(app, "Sphere")


def create_mesh_torus(app: Any) -> Any | None:
    return create_mesh_prim(app, "Torus")


def create_shape_capsule(app: Any) -> Any | None:
    return create_shape_prim(app, "Capsule")


def create_shape_cone(app: Any) -> Any | None:
    return create_shape_prim(app, "Cone")


def create_shape_cube(app: Any) -> Any | None:
    return create_shape_prim(app, "Cube")


def create_shape_cylinder(app: Any) -> Any | None:
    return create_shape_prim(app, "Cylinder")


def create_shape_sphere(app: Any) -> Any | None:
    return create_shape_prim(app, "Sphere")


def create_cylinder_light(app: Any) -> Any | None:
    return create_light_prim(app, "CylinderLight")


def create_disk_light(app: Any) -> Any | None:
    return create_light_prim(app, "DiskLight")


def create_distant_light(app: Any) -> Any | None:
    return create_light_prim(app, "DistantLight")


def create_dome_light(app: Any) -> Any | None:
    return create_light_prim(app, "DomeLight")


def create_rect_light(app: Any) -> Any | None:
    return create_light_prim(app, "RectLight")


def create_sphere_light(app: Any) -> Any | None:
    return create_light_prim(app, "SphereLight")


def get_geometry_standard_prim_attrs(stage: Any) -> dict[str, dict[Any, Any]]:
    """Return Kit-compatible native geometry defaults for the given stage."""
    from pxr import UsdGeom

    geom_base = 0.5 / _stage_meters_per_unit(stage)
    geom_base_double = geom_base * 2
    geom_base_half = geom_base / 2
    return {
        "Capsule": {
            UsdGeom.Tokens.radius: geom_base_half,
            UsdGeom.Tokens.height: geom_base,
        },
        "Cone": {
            UsdGeom.Tokens.radius: geom_base,
            UsdGeom.Tokens.height: geom_base_double,
            UsdGeom.Tokens.extent: [(-geom_base, -geom_base, -geom_base), (geom_base, geom_base, geom_base)],
        },
        "Cube": {
            UsdGeom.Tokens.size: geom_base_double,
            UsdGeom.Tokens.extent: [(-geom_base, -geom_base, -geom_base), (geom_base, geom_base, geom_base)],
        },
        "Cylinder": {
            UsdGeom.Tokens.radius: geom_base,
            UsdGeom.Tokens.height: geom_base_double,
            UsdGeom.Tokens.extent: [(-geom_base, -geom_base, -geom_base), (geom_base, geom_base, geom_base)],
        },
        "Plane": {
            UsdGeom.Tokens.width: geom_base_double,
            UsdGeom.Tokens.length: geom_base_double,
            UsdGeom.Tokens.axis: UsdGeom.Tokens.y,
            UsdGeom.Tokens.extent: [(-geom_base, 0, -geom_base), (geom_base, 0, geom_base)],
        },
        "Sphere": {
            UsdGeom.Tokens.radius: geom_base,
            UsdGeom.Tokens.extent: [(-geom_base, -geom_base, -geom_base), (geom_base, geom_base, geom_base)],
        },
    }


def apply_geometry_standard_prim_attrs(stage: Any, prim: Any, shape_name: str) -> None:
    """Apply Kit-compatible native geometry defaults to ``prim``."""
    from pxr import UsdGeom

    attrs = get_geometry_standard_prim_attrs(stage).get(shape_name)
    if attrs is None:
        raise ValueError(f"Unsupported shape primitive: {shape_name}")
    _set_authored_attributes(prim, attrs)
    if shape_name in {"Capsule", "Cone", "Cylinder"}:
        axis_attr = prim.GetAttribute(str(UsdGeom.Tokens.axis))
        if axis_attr:
            axis_attr.Set(UsdGeom.GetStageUpAxis(stage))
    _apply_default_xform_ops(prim)
    _set_extent_from_plugins(prim)


def get_light_prim_attrs(stage: Any) -> dict[str, dict[Any, Any]]:
    """Return Kit-compatible light defaults for the given stage."""
    from pxr import UsdLux

    geom_base = 0.5 / _stage_meters_per_unit(stage)
    geom_base_double = geom_base * 2
    if hasattr(UsdLux.Tokens, "inputsIntensity"):
        return {
            "CylinderLight": {
                UsdLux.Tokens.inputsLength: geom_base_double,
                UsdLux.Tokens.inputsRadius: 5,
                UsdLux.Tokens.inputsIntensity: 30000,
            },
            "DiskLight": {
                UsdLux.Tokens.inputsRadius: geom_base,
                UsdLux.Tokens.inputsIntensity: 60000,
            },
            "DistantLight": {
                UsdLux.Tokens.inputsAngle: 1.0,
                UsdLux.Tokens.inputsIntensity: 3000,
            },
            "DomeLight": {
                UsdLux.Tokens.inputsIntensity: 1000,
                UsdLux.Tokens.inputsTextureFormat: UsdLux.Tokens.latlong,
            },
            "RectLight": {
                UsdLux.Tokens.inputsWidth: geom_base_double,
                UsdLux.Tokens.inputsHeight: geom_base_double,
                UsdLux.Tokens.inputsIntensity: 15000,
            },
            "SphereLight": {
                UsdLux.Tokens.inputsRadius: geom_base,
                UsdLux.Tokens.inputsIntensity: 30000,
            },
        }

    return {
        "CylinderLight": {
            UsdLux.Tokens.length: geom_base_double,
            UsdLux.Tokens.radius: 5,
            UsdLux.Tokens.intensity: 30000,
        },
        "DiskLight": {
            UsdLux.Tokens.radius: geom_base,
            UsdLux.Tokens.intensity: 60000,
        },
        "DistantLight": {
            UsdLux.Tokens.angle: 1.0,
            UsdLux.Tokens.intensity: 3000,
        },
        "DomeLight": {
            UsdLux.Tokens.intensity: 1000,
            UsdLux.Tokens.textureFormat: UsdLux.Tokens.latlong,
        },
        "RectLight": {
            UsdLux.Tokens.width: geom_base_double,
            UsdLux.Tokens.height: geom_base_double,
            UsdLux.Tokens.intensity: 15000,
        },
        "SphereLight": {
            UsdLux.Tokens.radius: geom_base,
            UsdLux.Tokens.intensity: 30000,
        },
    }


def apply_light_standard_prim_attrs(
    stage: Any,
    prim: Any,
    light_type: str,
) -> None:
    """Apply the same Kit-compatible defaults used by the 0.1 Create menu."""
    attrs = get_light_prim_attrs(stage).get(light_type)
    if attrs is None:
        raise ValueError(f"Unsupported light primitive: {light_type}")
    _set_authored_attributes(prim, dict(attrs))
    _apply_default_xform_ops(
        prim,
        rotate_value=_default_euler_for_prim(prim, stage),
    )
    _apply_light_shaping_api(prim, light_type)


def apply_camera_standard_prim_attrs(stage: Any, prim: Any) -> None:
    """Apply the same typed camera defaults used by the 0.1 Create menu."""
    from pxr import Gf, UsdGeom

    camera = UsdGeom.Camera(prim)
    if not camera:
        raise ValueError(f"Prim is not a UsdGeom.Camera: {prim.GetPath()}")
    camera.GetFocalLengthAttr().Set(18.147562)
    camera.GetFocusDistanceAttr().Set(400.0)
    camera.GetClippingRangeAttr().Set(Gf.Vec2f(1.0, 10000000.0))
    _apply_default_xform_ops(
        prim,
        rotate_value=_default_euler_for_prim(prim, stage),
    )


def get_next_free_prim_path(stage: Any, child_name: str) -> Any:
    """Return the next free path for ``child_name`` under default prim or root."""
    return get_next_free_path(stage, _default_parent_path(stage).AppendChild(child_name))


def get_next_free_path(stage: Any, base_path: Any) -> Any:
    """Simple ``omni.usd.get_stage_next_free_path`` equivalent."""
    from pxr import Sdf

    path = base_path if isinstance(base_path, Sdf.Path) else Sdf.Path(str(base_path))
    if not path.IsAbsolutePath():
        path = _default_parent_path(stage).AppendChild(path.name)
    if not stage.GetPrimAtPath(path):
        return path

    parent = path.GetParentPath()
    base_name = path.name
    index = 1
    while True:
        candidate = parent.AppendChild(f"{base_name}_{index:02d}")
        if not stage.GetPrimAtPath(candidate):
            return candidate
        index += 1


def _positive(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _get_stage(app: Any) -> Any | None:
    stage = getattr(app, "_stage", None)
    if stage is not None:
        return stage
    adapter = getattr(app, "_stage_adapter", None)
    if adapter is not None:
        return getattr(adapter, "stage", None)
    return None


def _require_stage(app: Any) -> Any | None:
    stage = _get_stage(app)
    if stage is None:
        _show_error("No stage open")
    return stage


def _show_error(message: str) -> None:
    print(f"[OpenUSD adapter] {message}", file=sys.stderr)


def _default_parent_path(stage: Any) -> Any:
    from pxr import Sdf

    default_prim = stage.GetDefaultPrim()
    if default_prim and default_prim.IsValid():
        return default_prim.GetPath()
    return Sdf.Path.absoluteRootPath


def _looks_scope_path(stage: Any) -> Any:
    return _default_parent_path(stage).AppendChild("Looks")


def _stage_meters_per_unit(stage: Any) -> float:
    from pxr import Gf, UsdGeom

    units = UsdGeom.GetStageMetersPerUnit(stage) if stage else 0.01
    if Gf.IsClose(units, 0.0, 1e-6):
        return 0.01
    return units


def _mesh_above_ground_translate(stage: Any, mesh_name: str) -> Any:
    from pxr import Gf, UsdGeom

    if mesh_name in MESH_TYPES_WITH_ZERO_ABOVE_GROUND_OFFSET:
        return Gf.Vec3f(0.0, 0.0, 0.0)

    evaluator_class = MESH_EVALUATORS.get(mesh_name)
    half_scale = evaluator_class.get_default_half_scale() if evaluator_class else DEFAULT_HALF_SCALE_CM
    offset = half_scale / 2.0 if mesh_name == "Torus" else half_scale
    offset *= 0.01 / _stage_meters_per_unit(stage)

    if str(UsdGeom.GetStageUpAxis(stage)) == "Y":
        return Gf.Vec3f(0.0, offset, 0.0)
    return Gf.Vec3f(0.0, 0.0, offset)


def _default_euler_for_prim(prim: Any, stage: Any) -> Any:
    from pxr import Gf, UsdGeom, UsdLux

    up_axis = str(UsdGeom.GetStageUpAxis(stage))
    if prim.IsA(UsdLux.DistantLight):
        if up_axis == "Y":
            return Gf.Vec3f(*DISTANT_LIGHT_Y_UP_EULER)
        return Gf.Vec3f(*DISTANT_LIGHT_Z_UP_EULER)

    if prim.IsA(UsdLux.DomeLight):
        if up_axis == "Y":
            return Gf.Vec3f(*DOME_LIGHT_Y_UP_EULER)
        return Gf.Vec3f(*DOME_LIGHT_Z_UP_EULER)

    if (
        prim.IsA(UsdLux.SphereLight)
        or prim.IsA(UsdLux.CylinderLight)
        or prim.IsA(UsdLux.DiskLight)
        or prim.IsA(UsdLux.RectLight)
        or prim.IsA(UsdGeom.Camera)
    ):
        if up_axis == "Z":
            return Gf.Vec3f(*Z_UP_CAMERA_AND_LIGHT_EULER)

    return Gf.Vec3f(0.0, 0.0, 0.0)


def _apply_light_shaping_api(prim: Any, light_type: str) -> None:
    from pxr import UsdLux

    if light_type in LIGHT_TYPES_WITHOUT_SHAPING_API or not hasattr(UsdLux, "ShapingAPI"):
        return

    light_api = UsdLux.ShapingAPI.Apply(prim)
    shaping_defaults = (
        ("CreateShapingConeAngleAttr", (SHAPING_CONE_ANGLE_DEGREES,)),
        ("CreateShapingConeSoftnessAttr", ()),
        ("CreateShapingFocusAttr", ()),
        ("CreateShapingFocusTintAttr", ()),
        ("CreateShapingIesFileAttr", ()),
    )
    for method_name, args in shaping_defaults:
        method = getattr(light_api, method_name, None)
        if method is not None:
            method(*args)


def _apply_default_xform_ops(
    prim: Any,
    translate_value: Any | None = None,
    rotate_value: Any | None = None,
    scale_value: Any | None = None,
) -> None:
    from pxr import UsdGeom

    if not prim or not prim.IsA(UsdGeom.Xformable):
        return
    xformable = UsdGeom.Xformable(prim)
    translate = xformable.AddTranslateOp(UsdGeom.XformOp.PrecisionFloat)
    rotate = xformable.AddRotateXYZOp(UsdGeom.XformOp.PrecisionFloat)
    scale = xformable.AddScaleOp(UsdGeom.XformOp.PrecisionFloat)
    translate.Set(_vec3f((0.0, 0.0, 0.0) if translate_value is None else translate_value))
    rotate.Set(_vec3f((0.0, 0.0, 0.0) if rotate_value is None else rotate_value))
    scale.Set(_vec3f((1.0, 1.0, 1.0) if scale_value is None else scale_value))


def _set_extent_from_plugins(prim: Any) -> None:
    from pxr import Usd, UsdGeom

    if not prim or not prim.IsA(UsdGeom.Boundable):
        return
    attr = prim.GetAttribute(str(UsdGeom.Tokens.extent))
    if not attr or attr.HasAuthoredValueOpinion():
        return
    bounds = UsdGeom.Boundable.ComputeExtentFromPlugins(UsdGeom.Boundable(prim), Usd.TimeCode.Default())
    if bounds is not None:
        attr.Set(bounds)


def _set_authored_attributes(prim: Any, attrs: dict[Any, Any]) -> None:
    from pxr import Sdf

    with Sdf.ChangeBlock():
        for attr_name, value in attrs.items():
            name = str(attr_name)
            attr = prim.GetAttribute(name)
            if not attr:
                attr = prim.CreateAttribute(name, _infer_sdf_type(value), False)
            attr.Set(value)


def _infer_sdf_type(value: Any) -> Any:
    from pxr import Gf, Sdf

    if isinstance(value, bool):
        return Sdf.ValueTypeNames.Bool
    if isinstance(value, int):
        return Sdf.ValueTypeNames.Int
    if isinstance(value, float):
        return Sdf.ValueTypeNames.Float
    if isinstance(value, Gf.Vec2f):
        return Sdf.ValueTypeNames.Float2
    if isinstance(value, Gf.Vec3f):
        return Sdf.ValueTypeNames.Float3
    if isinstance(value, str) or value.__class__.__name__ == "Token":
        return Sdf.ValueTypeNames.Token
    return Sdf.ValueTypeNames.String


def _shape_schema_defines() -> dict[str, Callable[[Any, Any], Any]]:
    from pxr import UsdGeom

    return {
        "Capsule": UsdGeom.Capsule.Define,
        "Cone": UsdGeom.Cone.Define,
        "Cube": UsdGeom.Cube.Define,
        "Cylinder": UsdGeom.Cylinder.Define,
        "Sphere": UsdGeom.Sphere.Define,
    }


def _light_schema_defines() -> dict[str, Callable[[Any, Any], Any]]:
    from pxr import UsdLux

    return {
        "CylinderLight": UsdLux.CylinderLight.Define,
        "DiskLight": UsdLux.DiskLight.Define,
        "DistantLight": UsdLux.DistantLight.Define,
        "DomeLight": UsdLux.DomeLight.Define,
        "RectLight": UsdLux.RectLight.Define,
        "SphereLight": UsdLux.SphereLight.Define,
    }

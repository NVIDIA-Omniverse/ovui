# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovstage StageAdapter bounds and computed bound-camera behavior."""

from __future__ import annotations

import math
import pathlib
from typing import Any, Iterator

import pytest

from ovui_data_adapters.common import AABB
from ovui_data_adapters.ovstage._scene import OvstageScene
from ovui_data_adapters.ovstage._stage_write import write_matrix_attribute
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    create_provider_session,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes
from ovui_data_adapters.ovstage.stage_adapter import OvstageStageAdapter


pytestmark = [
    pytest.mark.requires_ovstage,
]

_SIZE_CUBE = "/World/VisibilityCases/HiddenParent/InheritedHiddenChild"
_RADIUS_SPHERE = "/World/VisibilityCases/VisibleParent/InheritedVisibleChild"
_MESH_EXTENT = "/World/Hierarchy/GroupB/TriangleMesh"
_NESTED_CUBE = "/World/TransformCases/NestedParent/NestedChild/RuntimeBoundCube"
_PRECEDENCE_CUBE = "/World/BoundsPrecedenceCube"
_PRECEDENCE_SPHERE = "/World/BoundsPrecedenceSphere"
_ROTATED_PARENT = "/World/TransformCases/MatrixOnly"
_ROTATED_CUBE = f"{_ROTATED_PARENT}/RotatedRuntimeBoundCube"
_UNAVAILABLE_XFORM = "/World/AttributeCases/MirroredValues"
_GROUP_A = "/World/Hierarchy/GroupA"
_ROTATED_SCALED_MATRIX = (
    0.0, 2.0, 0.0, 0.0,
    -1.0, 0.0, 0.0, 0.0,
    0.0, 0.0, 0.5, 0.0,
    3.0, -2.0, 5.0, 1.0,
)


@pytest.fixture()
def ovstage_runtime():
    return load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )


@pytest.fixture()
def ovstage_scene(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_runtime: Any,
) -> Iterator[OvstageScene]:
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(ovstage_static_scene_path))
    try:
        yield scene
    finally:
        session.shutdown_scene()


@pytest.fixture()
def stage_adapter(ovstage_scene: OvstageScene) -> OvstageStageAdapter:
    return OvstageStageAdapter(ovstage_scene)


def test_cube_world_aabb_prefers_size_when_extent_disagrees(
    stage_adapter: OvstageStageAdapter,
    ovstage_scene: OvstageScene,
) -> None:
    _create_runtime_cube(
        ovstage_scene,
        _PRECEDENCE_CUBE,
        size=2.0,
        extent=((-10.0, -10.0, -10.0), (10.0, 10.0, 10.0)),
    )

    _assert_aabb(
        stage_adapter.compute_prim_world_aabb_with_extent_fallback(_PRECEDENCE_CUBE),
        ((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)),
    )


def test_cube_world_aabb_uses_mirrored_size_when_extent_is_absent(
    stage_adapter: OvstageStageAdapter,
) -> None:
    _assert_aabb(
        stage_adapter.compute_prim_world_aabb_with_extent_fallback(_SIZE_CUBE),
        ((-0.375, -0.375, -0.375), (0.375, 0.375, 0.375)),
    )


def test_sphere_world_aabb_prefers_radius_when_extent_disagrees(
    stage_adapter: OvstageStageAdapter,
    ovstage_scene: OvstageScene,
) -> None:
    _create_runtime_sphere(
        ovstage_scene,
        _PRECEDENCE_SPHERE,
        radius=0.25,
        extent=((-8.0, -8.0, -8.0), (8.0, 8.0, 8.0)),
    )

    _assert_aabb(
        stage_adapter.compute_prim_world_aabb_with_extent_fallback(_PRECEDENCE_SPHERE),
        ((-0.25, -0.25, -0.25), (0.25, 0.25, 0.25)),
    )


def test_sphere_world_aabb_uses_mirrored_radius_when_extent_is_absent(
    stage_adapter: OvstageStageAdapter,
) -> None:
    _assert_aabb(
        stage_adapter.compute_prim_world_aabb_with_extent_fallback(_RADIUS_SPHERE),
        ((-0.4, -0.4, -0.4), (0.4, 0.4, 0.4)),
    )


def test_mesh_world_aabb_uses_mirrored_extent(
    stage_adapter: OvstageStageAdapter,
) -> None:
    _assert_aabb(
        stage_adapter.compute_prim_world_aabb_with_extent_fallback(_MESH_EXTENT),
        ((-0.5, 0.0, 0.0), (0.5, 1.0, 0.0)),
    )


def test_transformed_hierarchy_applies_world_matrix_to_local_bounds(
    stage_adapter: OvstageStageAdapter,
    ovstage_scene: OvstageScene,
) -> None:
    _create_runtime_cube(ovstage_scene, _NESTED_CUBE, size=2.0)

    _assert_aabb(
        stage_adapter.compute_prim_world_aabb_with_extent_fallback(_NESTED_CUBE),
        ((-1.0, 9.0, 1.0), (1.0, 11.0, 3.0)),
    )


def test_rotated_scaled_world_matrix_transforms_all_aabb_corners(
    stage_adapter: OvstageStageAdapter,
    ovstage_scene: OvstageScene,
) -> None:
    _create_rotated_scaled_cube(ovstage_scene)

    # Row-vector transform of cube corners:
    # x' = 3 - y, y' = 2x - 2, z' = 0.5z + 5 for x/y/z in [-1, 1].
    _assert_aabb(
        stage_adapter.compute_prim_world_aabb_with_extent_fallback(_ROTATED_CUBE),
        ((2.0, -4.0, 4.5), (4.0, 0.0, 5.5)),
    )


def test_selection_world_aabb_unions_available_prim_bounds(
    stage_adapter: OvstageStageAdapter,
) -> None:
    _assert_aabb(
        stage_adapter.compute_world_aabb([_SIZE_CUBE, _MESH_EXTENT]),
        ((-0.5, -0.375, -0.375), (0.5, 1.0, 0.375)),
    )


def test_group_selection_world_aabb_unions_descendant_geometry(
    stage_adapter: OvstageStageAdapter,
) -> None:
    assert stage_adapter.compute_prim_world_aabb_with_extent_fallback(_GROUP_A) is None
    _assert_aabb(
        stage_adapter.compute_world_aabb([_GROUP_A]),
        ((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5)),
    )


def test_empty_selection_and_unavailable_prims_report_no_bounds(
    stage_adapter: OvstageStageAdapter,
) -> None:
    size_cube_bounds = stage_adapter.compute_prim_world_aabb_with_extent_fallback(_SIZE_CUBE)

    assert stage_adapter.compute_world_aabb([]) is None
    assert stage_adapter.compute_prim_world_aabb_with_extent_fallback(
        _UNAVAILABLE_XFORM
    ) is None
    assert stage_adapter.compute_prim_world_aabb_with_extent_fallback(
        "/World/DoesNotExist"
    ) is None
    assert stage_adapter.compute_world_aabb([_UNAVAILABLE_XFORM]) is None
    _assert_aabb(
        stage_adapter.compute_world_aabb([_SIZE_CUBE, _UNAVAILABLE_XFORM]),
        size_cube_bounds,
    )


def test_bound_camera_is_derived_from_computed_scene_aabb(
    stage_adapter: OvstageStageAdapter,
) -> None:
    scene_bounds = stage_adapter.compute_world_aabb(["/"])
    _assert_aabb(
        scene_bounds,
        ((-0.5, -0.5, -0.5), (0.5, 1.0, 0.5)),
    )

    pose = stage_adapter.read_bound_camera()

    assert pose is not None
    assert pose.target == pytest.approx(_center(scene_bounds))
    assert pose.up_axis == "Y"
    assert pose.fov_degrees == pytest.approx(45.0)
    assert pose.prim_path == "ovstage:computed-bound-camera"
    assert _distance(pose.eye, pose.target) >= _radius(scene_bounds) / math.sin(
        math.radians(pose.fov_degrees) * 0.5
    )


def _create_runtime_cube(
    scene: OvstageScene,
    path: str,
    size: float,
    extent: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None,
) -> None:
    attrs = [f"    double size = {float(size)}"]
    if extent is not None:
        attrs.append(f"    float3[] extent = {_format_extent(extent)}")
    _add_runtime_primitive(scene, path, "Cube", attrs)


def _create_runtime_sphere(
    scene: OvstageScene,
    path: str,
    radius: float,
    extent: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None,
) -> None:
    attrs = [f"    double radius = {float(radius)}"]
    if extent is not None:
        attrs.append(f"    float3[] extent = {_format_extent(extent)}")
    _add_runtime_primitive(scene, path, "Sphere", attrs)


def _create_rotated_scaled_cube(scene: OvstageScene) -> None:
    write_matrix_attribute(
        scene._stage,
        [_ROTATED_PARENT],
        "omni:xform",
        _ROTATED_SCALED_MATRIX,
    )
    _add_runtime_primitive(scene, _ROTATED_CUBE, "Cube", ["    double size = 2"])


def _format_extent(
    extent: tuple[tuple[float, float, float], tuple[float, float, float]],
) -> str:
    mins, maxs = extent
    return (
        f"[({mins[0]}, {mins[1]}, {mins[2]}), "
        f"({maxs[0]}, {maxs[1]}, {maxs[2]})]"
    )


def _add_runtime_primitive(
    scene: OvstageScene,
    path: str,
    type_name: str,
    attributes: list[str],
) -> None:
    from ovstage import population

    leaf = str(path).rstrip("/").rsplit("/", 1)[-1]
    lines = [
        "#usda 1.0",
        "(",
        f'    defaultPrim = "{leaf}"',
        ")",
        "",
        f'def {type_name} "{leaf}"',
        "{",
        *attributes,
        "    matrix4d xformOp:transform = "
        + "( (1,0,0,0), (0,1,0,0), (0,0,1,0), (0,0,0,1) )",
        '    uniform token[] xformOpOrder = ["xformOp:transform"]',
        "}",
    ]
    population.add_usd_reference_from_string(
        scene._stage,
        "\n".join(lines) + "\n",
        str(path),
    )
    ordinal = scene._stage.begin_frame()
    try:
        population.apply_usd_changes(scene._stage, ordinal)
    finally:
        scene._stage.end_frame(ordinal)


def _assert_aabb(actual: AABB, expected: AABB) -> None:
    assert actual is not None
    assert expected is not None
    assert actual[0] == pytest.approx(expected[0])
    assert actual[1] == pytest.approx(expected[1])


def _center(bounds: AABB) -> tuple[float, float, float]:
    assert bounds is not None
    mins, maxs = bounds
    return tuple((mins[axis] + maxs[axis]) * 0.5 for axis in range(3))


def _radius(bounds: AABB) -> float:
    assert bounds is not None
    mins, maxs = bounds
    size = tuple(maxs[axis] - mins[axis] for axis in range(3))
    return math.sqrt(sum(component * component for component in size)) * 0.5


def _distance(
    lhs: tuple[float, float, float],
    rhs: tuple[float, float, float],
) -> float:
    delta = tuple(lhs[axis] - rhs[axis] for axis in range(3))
    return math.sqrt(sum(component * component for component in delta))

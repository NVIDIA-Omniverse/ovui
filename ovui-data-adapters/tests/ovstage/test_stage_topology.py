# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovstage StageAdapter topology and path-cache behavior."""

from __future__ import annotations

import pathlib
from typing import Any, Iterator

import pytest

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


@pytest.fixture()
def ovstage_runtime():
    return load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )


@pytest.fixture()
def stage_adapter(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_runtime: Any,
) -> Iterator[OvstageStageAdapter]:
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(ovstage_static_scene_path))
    try:
        yield OvstageStageAdapter(scene)
    finally:
        session.shutdown_scene()


def _child_paths(adapter: OvstageStageAdapter, item: Any) -> list[str]:
    return [adapter.get_item_path(child) for child in adapter.get_children(item)]


def _count_descendants(adapter: OvstageStageAdapter, item: Any) -> int:
    return 1 + sum(
        _count_descendants(adapter, child)
        for child in adapter.get_children(item)
    )


def test_get_root_returns_stable_synthesized_root(
    stage_adapter: OvstageStageAdapter,
) -> None:
    root_a = stage_adapter.get_root()
    root_b = stage_adapter.get_root()

    assert root_a is root_b
    assert stage_adapter.get_item_path(root_a) == "/"
    assert _child_paths(stage_adapter, root_a) == ["/World"]


def test_get_children_returns_fixture_hierarchy_from_native_ovstage(
    stage_adapter: OvstageStageAdapter,
) -> None:
    root = stage_adapter.get_root()
    world = stage_adapter.get_item_at_path("/World")
    hierarchy = stage_adapter.get_item_at_path("/World/Hierarchy")
    group_a = stage_adapter.get_item_at_path("/World/Hierarchy/GroupA")
    group_b = stage_adapter.get_item_at_path("/World/Hierarchy/GroupB")

    assert world is not None
    assert hierarchy is not None
    assert group_a is not None
    assert group_b is not None
    assert _child_paths(stage_adapter, root) == ["/World"]
    assert _child_paths(stage_adapter, world) == [
        "/World/AttributeCases",
        "/World/Cameras",
        "/World/Hierarchy",
        "/World/TransformCases",
        "/World/VisibilityCases",
    ]
    assert set(_child_paths(stage_adapter, hierarchy)) == {
        "/World/Hierarchy/Looks",
        "/World/Hierarchy/GroupA",
        "/World/Hierarchy/GroupB",
    }
    assert set(_child_paths(stage_adapter, group_a)) == {
        "/World/Hierarchy/GroupA/BoxA",
        "/World/Hierarchy/GroupA/BallA",
    }
    assert _child_paths(stage_adapter, group_b) == [
        "/World/Hierarchy/GroupB/TriangleMesh",
    ]
    assert _count_descendants(stage_adapter, root) == 25


def test_can_have_children_reflects_current_topology(
    stage_adapter: OvstageStageAdapter,
) -> None:
    root = stage_adapter.get_root()
    group_a = stage_adapter.get_item_at_path("/World/Hierarchy/GroupA")
    leaf = stage_adapter.get_item_at_path("/World/Hierarchy/GroupA/BoxA")
    empty_scope = stage_adapter.get_item_at_path("/World/Hierarchy/Looks")

    assert group_a is not None
    assert leaf is not None
    assert empty_scope is not None
    assert stage_adapter.can_have_children(root) is True
    assert stage_adapter.can_have_children(group_a) is True
    assert stage_adapter.can_have_children(leaf) is False
    assert stage_adapter.can_have_children(empty_scope) is False


def test_get_item_path_round_trips_through_path_cache(
    stage_adapter: OvstageStageAdapter,
) -> None:
    paths = [
        "/",
        "/World",
        "/World/Hierarchy/GroupA/BallA",
        "/World/TransformCases/NestedParent/NestedChild",
        "/World/Cameras/MainCamera",
    ]

    for path in paths:
        item = stage_adapter.get_item_at_path(path)
        assert item is not None
        assert stage_adapter.get_item_path(item) == path
        assert stage_adapter.get_item_at_path(path) is item

    assert stage_adapter.get_item_at_path("/World/Missing") is None


def test_cache_invalidates_after_native_topology_mutation(
    stage_adapter: OvstageStageAdapter,
) -> None:
    stage = stage_adapter.stage
    group_path = "/World/Hierarchy/GroupA"
    probe_path = f"{group_path}/Step7CacheProbe"
    group_before = stage_adapter.get_item_at_path(group_path)
    topology_before = stage.get_topology_version()

    assert group_before is not None
    assert stage_adapter.get_item_at_path(probe_path) is None

    ordinal = stage.begin_frame()
    stage.create_prims(ordinal, [probe_path], "Xform")
    stage.end_frame(ordinal)

    group_after_create = stage_adapter.get_item_at_path(group_path)
    probe_item = stage_adapter.get_item_at_path(probe_path)

    assert stage.get_topology_version() > topology_before
    assert group_after_create is not None
    # Unchanged items keep their identity so a topology edit elsewhere does
    # not invalidate selection handles.
    assert group_after_create is group_before
    assert probe_item is not None
    assert probe_path in _child_paths(stage_adapter, group_after_create)

    topology_after_create = stage.get_topology_version()
    ordinal = stage.begin_frame()
    stage.delete_prims(ordinal, [probe_path])
    stage.end_frame(ordinal)

    group_after_delete = stage_adapter.get_item_at_path(group_path)

    assert stage.get_topology_version() > topology_after_create
    assert group_after_delete is not None
    assert group_after_delete is group_after_create
    assert stage_adapter.get_item_at_path(probe_path) is None
    assert probe_path not in _child_paths(stage_adapter, group_after_delete)


def test_children_enumerate_in_native_order_not_authored_usd_order(
    stage_adapter: OvstageStageAdapter,
) -> None:
    """Authored USD child order is not preserved by the native-only adapter.

    The fixture authors ``BoxA`` before ``BallA`` under ``GroupA``. The exact
    OVStage 0.1 topology surface enumerates children in its own native
    (lexicographic) order, and the adapter reports that order truthfully
    instead of restoring the authored order through an OpenUSD bridge.
    """
    group = stage_adapter.get_item_at_path("/World/Hierarchy/GroupA")
    assert group is not None
    assert _child_paths(stage_adapter, group) == [
        "/World/Hierarchy/GroupA/BallA",
        "/World/Hierarchy/GroupA/BoxA",
    ]


def test_badge_and_item_flags_are_truthfully_inert_without_composition_data(
    stage_adapter: OvstageStageAdapter,
) -> None:
    """Composition badges and default-prim identity flags stay inert.

    Exact OVStage exposes no composition-arc or default-prim metadata, so the
    native-only adapter reports no badges and no identity flags rather than
    guessing them from an OpenUSD bridge.
    """
    from ovui_data_adapters.common import BadgeFlags, ItemFlags

    for path in ("/World", "/World/Hierarchy/GroupA", "/World/Hierarchy/GroupA/BoxA"):
        item = stage_adapter.get_item_at_path(path)
        assert item is not None
        assert stage_adapter.get_badge_flags(item) is BadgeFlags.NONE
        assert stage_adapter.get_item_flags(item) is ItemFlags.NONE

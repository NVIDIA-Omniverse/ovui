# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovstage SelectionAdapter path conversion."""

from __future__ import annotations

from dataclasses import dataclass
import pathlib
from typing import Any, Iterator

import pytest

from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    create_provider_session,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes
from ovui_data_adapters.ovstage.selection_adapter import OvstageSelectionAdapter
from ovui_data_adapters.ovstage.stage_adapter import OvstageStageAdapter


pytestmark = [
    pytest.mark.requires_ovstage,
]


@dataclass(frozen=True)
class _SelectionRecord:
    path: str
    source: str = "test"


@dataclass(frozen=True)
class _SelectionSnapshot:
    items: tuple[_SelectionRecord, ...]

    def paths(self) -> list[str]:
        return [item.path for item in self.items]


@pytest.fixture()
def ovstage_runtime():
    return load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )


@pytest.fixture()
def adapters(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_runtime: Any,
) -> Iterator[tuple[Any, OvstageStageAdapter, OvstageSelectionAdapter]]:
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(ovstage_static_scene_path))
    stage_adapter = OvstageStageAdapter(scene)
    selection_adapter = OvstageSelectionAdapter(scene, stage_adapter)
    try:
        yield scene, stage_adapter, selection_adapter
    finally:
        session.shutdown_scene()


def test_single_selection_record_resolves_through_path_cache(
    adapters: tuple[Any, OvstageStageAdapter, OvstageSelectionAdapter],
) -> None:
    _scene, stage_adapter, selection_adapter = adapters
    path = "/World/Hierarchy/GroupA/BoxA"

    items = selection_adapter.to_adapter_items(_SelectionRecord(path))

    assert items == [stage_adapter.get_item_at_path(path)]
    assert selection_adapter.to_selection_items(items) == [path]


def test_multi_selection_snapshot_preserves_order(
    adapters: tuple[Any, OvstageStageAdapter, OvstageSelectionAdapter],
) -> None:
    _scene, stage_adapter, selection_adapter = adapters
    paths = [
        "/World/Hierarchy/GroupA/BoxA",
        "/World/Hierarchy/GroupA/BallA",
        "/World/Cameras/MainCamera",
    ]
    snapshot = _SelectionSnapshot(tuple(_SelectionRecord(path) for path in paths))

    items = selection_adapter.to_adapter_items(snapshot)

    assert [stage_adapter.get_item_path(item) for item in items] == paths
    assert selection_adapter.to_selection_items(items) == paths


def test_stale_path_is_dropped_without_creating_adapter_item(
    adapters: tuple[Any, OvstageStageAdapter, OvstageSelectionAdapter],
) -> None:
    _scene, stage_adapter, selection_adapter = adapters
    valid_path = "/World/Hierarchy/GroupB/TriangleMesh"
    missing_path = "/World/Hierarchy/GroupB/DeletedMesh"

    items = selection_adapter.to_adapter_items([
        _SelectionRecord(missing_path),
        _SelectionRecord(valid_path),
    ])

    assert items == [stage_adapter.get_item_at_path(valid_path)]
    assert selection_adapter.to_selection_items(items) == [valid_path]


def test_topology_change_drops_stale_path_and_old_adapter_item(
    adapters: tuple[Any, OvstageStageAdapter, OvstageSelectionAdapter],
) -> None:
    scene, stage_adapter, selection_adapter = adapters
    stage = scene._stage
    path = "/World/Hierarchy/GroupA/Step9SelectionProbe"

    ordinal = stage.begin_frame()
    stage.create_prims(ordinal, [path], "Xform")
    stage.end_frame(ordinal)

    created_items = selection_adapter.to_adapter_items([path])
    assert len(created_items) == 1
    created_item = created_items[0]
    assert stage_adapter.get_item_path(created_item) == path

    ordinal = stage.begin_frame()
    stage.delete_prims(ordinal, [path])
    stage.end_frame(ordinal)

    assert selection_adapter.to_adapter_items([_SelectionRecord(path)]) == []
    assert selection_adapter.to_selection_items([created_item]) == []


def test_recreated_path_resolves_to_current_item_not_old_handle(
    adapters: tuple[Any, OvstageStageAdapter, OvstageSelectionAdapter],
) -> None:
    scene, stage_adapter, selection_adapter = adapters
    stage = scene._stage
    path = "/World/Hierarchy/GroupA/Step9RecreateProbe"

    ordinal = stage.begin_frame()
    stage.create_prims(ordinal, [path], "Xform")
    stage.end_frame(ordinal)
    old_item = selection_adapter.to_adapter_items([path])[0]

    ordinal = stage.begin_frame()
    stage.delete_prims(ordinal, [path])
    stage.end_frame(ordinal)
    ordinal = stage.begin_frame()
    stage.create_prims(ordinal, [path], "Xform")
    stage.end_frame(ordinal)

    current_items = selection_adapter.to_adapter_items([_SelectionRecord(path)])

    assert len(current_items) == 1
    assert current_items[0] is stage_adapter.get_item_at_path(path)
    assert current_items[0] is not old_item
    assert selection_adapter.to_selection_items([old_item]) == []
    assert selection_adapter.to_selection_items(current_items) == [path]

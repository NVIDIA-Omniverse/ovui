# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovstage StageAdapter display, type, icon, and filter behavior."""

from __future__ import annotations

import pathlib
from collections import Counter
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


def _basename(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] or "/"


def _real_type_names(adapter: OvstageStageAdapter) -> dict[str, str]:
    stage = adapter.stage
    result = stage.query_prims(stage.current_ordinal)
    records: dict[str, str] = {}
    for group in result.get("groups", ()):
        type_name = str(group.get("prim_type", ""))
        handle = int(group.get("prim_list_handle") or 0)
        if not handle:
            continue
        for path in stage.get_prim_paths(handle):
            records[str(path)] = type_name
    assert records
    assert len(records) == result["total_prim_count"]
    return records


def test_display_names_are_path_basenames(
    stage_adapter: OvstageStageAdapter,
) -> None:
    root = stage_adapter.get_root()
    type_names = _real_type_names(stage_adapter)

    assert stage_adapter.get_display_name(root) == "/"
    for path in sorted(type_names):
        item = stage_adapter.get_item_at_path(path)

        assert item is not None
        assert stage_adapter.get_display_name(item) == _basename(path)


def test_type_names_match_real_ovstage_prim_queries(
    stage_adapter: OvstageStageAdapter,
) -> None:
    type_names = _real_type_names(stage_adapter)

    for path, expected_type in type_names.items():
        item = stage_adapter.get_item_at_path(path)

        assert item is not None
        assert stage_adapter.get_type_name(item) == expected_type


def test_type_category_and_icon_map_actual_present_types(
    stage_adapter: OvstageStageAdapter,
) -> None:
    type_names = _real_type_names(stage_adapter)
    expected_by_type = {
        "Camera": ("Camera", "Camera"),
        "Cube": ("Mesh", "Mesh"),
        "Mesh": ("Mesh", "Mesh"),
        "Scope": ("Scope", "Scope"),
        "Sphere": ("Mesh", "Mesh"),
        "Xform": ("Xform", "Xform"),
    }
    present_types = set(type_names.values())

    assert present_types <= set(expected_by_type)
    for path, type_name in type_names.items():
        item = stage_adapter.get_item_at_path(path)
        expected_category, expected_icon = expected_by_type[type_name]

        assert item is not None
        assert stage_adapter.get_type_category(item) == expected_category
        assert stage_adapter.get_icon_name(item) == expected_icon


def test_filter_items_uses_cached_records_for_type_text(
    stage_adapter: OvstageStageAdapter,
) -> None:
    type_names = _real_type_names(stage_adapter)
    counts = Counter(type_names.values())
    target_type = next(
        type_name
        for type_name, count in counts.most_common()
        if type_name and count < len(type_names)
    )
    all_items = [
        item
        for path in sorted(type_names)
        if (item := stage_adapter.get_item_at_path(path)) is not None
    ]

    filtered = stage_adapter.filter_items(
        all_items,
        lambda item: target_type.lower()
        in " ".join(
            (
                stage_adapter.get_display_name(item),
                stage_adapter.get_type_name(item),
                stage_adapter.get_type_category(item),
                stage_adapter.get_icon_name(item),
            )
        ).lower(),
    )
    filtered_paths = {
        stage_adapter.get_item_path(item)
        for item in filtered
    }
    expected_paths = {
        path
        for path, type_name in type_names.items()
        if type_name == target_type
    }

    assert filtered
    assert filtered_paths == expected_paths

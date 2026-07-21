# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION is strictly
# prohibited.

"""OVStage-native hierarchy, path, display, and selection contracts."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterator

import pytest

from ovui_data_adapters.common import BadgeFlags, ItemFlags
from ovui_data_adapters.ovstage._scene import _native_path_exists
from ovui_data_adapters.ovstage._constants import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
)
from ovui_data_adapters.ovstage.provider import (
    create_provider_session,
    create_selection_adapter,
    create_stage_adapter,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes


_SCENE_A = '''#usda 1.0

def Xform "World"
{
    def Xform "BoxPretender" {}
    def Scope "Cameras"
    {
        def Xform "NotACamera" {}
        def Camera "RealCamera" {}
    }
    def Xform "Group_Unicode"
    {
        def Xform "Café_Δ" {}
        def Cube "PlainShape"
        {
            double size = 2
        }
        def Sphere "RoundShape"
        {
            double radius = 1
        }
        def Mesh "MeshShape"
        {
            int[] faceVertexCounts = [3]
            int[] faceVertexIndices = [0, 1, 2]
            point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        }
        def "Untyped" {}
    }
}

def Xform "_OvuiRuntime"
{
}
def Scope "ZedRoot"
{
    def Xform "Child"
    {
    }
}
'''

_SCENE_B = '''#usda 1.0

def Xform "World"
{
    def Scope "OnlyInReplacement"
    {
        def Sphere "SecondShape"
        {
            double radius = 3
        }
    }
}
'''


def _write_scene(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture()
def scene_paths(tmp_path: Path) -> tuple[Path, Path]:
    return (
        _write_scene(tmp_path, "hierarchy-a.usda", _SCENE_A),
        _write_scene(tmp_path, "hierarchy-b.usda", _SCENE_B),
    )


@pytest.fixture(scope="module")
def ovstage_runtime() -> Any:
    package_parent = Path(__file__).resolve().parents[2]
    previous_paths = list(sys.path)
    loaded = sys.modules.get("ovstage")
    if loaded is not None and not callable(getattr(loaded, "Stage", None)):
        sys.modules.pop("ovstage", None)
    sys.path[:] = [
        entry
        for entry in sys.path
        if not entry or Path(entry).resolve() != package_parent
    ]
    try:
        return load_required_runtimes(
            module_name=PROVIDER_NAME,
            entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
        )
    finally:
        sys.path[:] = previous_paths


@pytest.fixture()
def opened_a(
    scene_paths: tuple[Path, Path],
    ovstage_runtime: Any,
) -> Iterator[tuple[Any, Any, Any, Any]]:
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(scene_paths[0]))
    stage_adapter = create_stage_adapter(scene)
    selection_adapter = create_selection_adapter(scene, stage_adapter)
    try:
        yield session, scene, stage_adapter, selection_adapter
    finally:
        session.shutdown_scene()


def _child_paths(adapter: Any, item: Any) -> list[str]:
    return [adapter.get_item_path(child) for child in adapter.get_children(item)]


def _walk(adapter: Any) -> list[Any]:
    result: list[Any] = []

    def visit(item: Any) -> None:
        result.append(item)
        for child in adapter.get_children(item):
            visit(child)

    visit(adapter.get_root())
    return result


def test_static_hierarchy_paths_types_display_and_flags_are_native(
    opened_a: tuple[Any, Any, Any, Any],
) -> None:
    _session, scene, adapter, _selection = opened_a
    root = adapter.get_root()

    assert _child_paths(adapter, root) == ["/World", "/ZedRoot", "/_OvuiRuntime"]
    assert _child_paths(adapter, adapter.get_item_at_path("/World")) == [
        "/World/BoxPretender",
        "/World/Cameras",
        "/World/Group_Unicode",
    ]
    assert _child_paths(adapter, adapter.get_item_at_path("/World/Group_Unicode")) == [
        "/World/Group_Unicode/Café_Δ",
        "/World/Group_Unicode/MeshShape",
        "/World/Group_Unicode/PlainShape",
        "/World/Group_Unicode/RoundShape",
        "/World/Group_Unicode/Untyped",
    ]

    expected_types = {
        "/World": "Xform",
        "/World/BoxPretender": "Xform",
        "/World/Cameras": "Scope",
        "/World/Cameras/NotACamera": "Xform",
        "/World/Cameras/RealCamera": "Camera",
        "/World/Group_Unicode": "Xform",
        "/World/Group_Unicode/Café_Δ": "Xform",
        "/World/Group_Unicode/MeshShape": "Mesh",
        "/World/Group_Unicode/PlainShape": "Cube",
        "/World/Group_Unicode/RoundShape": "Sphere",
        "/World/Group_Unicode/Untyped": "",
        "/ZedRoot": "Scope",
        "/ZedRoot/Child": "Xform",
        "/_OvuiRuntime": "Xform",
    }
    items = _walk(adapter)
    assert len(items) == len(expected_types) + 1
    assert len({adapter.get_item_path(item) for item in items}) == len(items)

    for item in items:
        path = adapter.get_item_path(item)
        assert adapter.get_item_at_path(path) is item
        assert adapter.get_badge_flags(item) is BadgeFlags.NONE
        assert adapter.get_item_flags(item) is ItemFlags.NONE
        if path == "/":
            assert adapter.get_display_name(item) == "/"
            assert adapter.get_type_name(item) == ""
            continue
        assert adapter.get_display_name(item) == path.rsplit("/", 1)[-1]
        assert adapter.get_type_name(item) == expected_types[path]

    unicode_item = adapter.get_item_at_path("/World/Group_Unicode/Café_Δ")
    assert adapter.get_display_name(unicode_item) == "Café_Δ"
    untyped = adapter.get_item_at_path("/World/Group_Unicode/Untyped")
    assert adapter.get_type_category(untyped) == "Other"
    assert adapter.get_icon_name(untyped) == "Prim"
    assert _native_path_exists(scene._stage, "/_OvuiRuntime") is True


@pytest.mark.parametrize(
    "path",
    [
        "",
        " ",
        " /World ",
        "World",
        "/World/",
        "//World",
        "/World/./Group_Unicode",
        "/World/../ZedRoot",
        "/Missing",
    ],
)
def test_noncanonical_or_missing_paths_do_not_resolve(
    opened_a: tuple[Any, Any, Any, Any],
    path: str,
) -> None:
    _session, _scene, adapter, _selection = opened_a
    assert adapter.get_item_at_path(path) is None


def test_filter_uses_current_native_display_and_type_records(
    opened_a: tuple[Any, Any, Any, Any],
) -> None:
    _session, _scene, adapter, _selection = opened_a
    items = _walk(adapter)
    scopes = adapter.filter_items(
        items,
        lambda item: adapter.get_type_name(item) == "Scope",
    )
    assert [adapter.get_item_path(item) for item in scopes] == [
        "/World/Cameras",
        "/ZedRoot",
    ]


def test_foreign_and_closed_items_never_cross_scene_ownership(
    scene_paths: tuple[Path, Path],
    ovstage_runtime: Any,
) -> None:
    session_a = create_provider_session(runtime=ovstage_runtime)
    session_b = create_provider_session(runtime=ovstage_runtime)
    scene_a = session_a.open_stage(str(scene_paths[0]))
    scene_b = session_b.open_stage(str(scene_paths[1]))
    adapter_a = create_stage_adapter(scene_a)
    adapter_b = create_stage_adapter(scene_b)
    selection_a = create_selection_adapter(scene_a, adapter_a)
    selection_b = create_selection_adapter(scene_b, adapter_b)
    old_world = adapter_a.get_item_at_path("/World")
    old_shape = adapter_a.get_item_at_path("/World/Group_Unicode/PlainShape")
    current_world = adapter_b.get_item_at_path("/World")
    try:
        assert old_world is not current_world
        assert old_world != current_world
        assert adapter_b.get_children(old_world) == []
        with pytest.raises(NotImplementedError):
            adapter_b.get_item_path(old_world)
        assert adapter_b.get_display_name(old_shape) == ""
        assert adapter_b.get_type_name(old_shape) == ""
        assert adapter_b.get_type_category(old_shape) == "Other"
        assert adapter_b.get_icon_name(old_shape) == "Prim"
        assert selection_b.to_selection_items([old_world, old_shape]) == []

        session_a.shutdown_scene()
        with pytest.raises(NotImplementedError):
            adapter_a.get_item_path(old_shape)
        assert adapter_a.get_children(old_world) == []
        assert adapter_a.get_display_name(old_shape) == ""
        assert adapter_a.get_type_name(old_shape) == ""
        assert selection_a.to_adapter_items(["/World"]) == []
        assert selection_a.to_selection_items([old_shape]) == []
    finally:
        session_a.shutdown_scene()
        session_b.shutdown_scene()


def test_session_replacement_isolates_old_items_and_selection(
    scene_paths: tuple[Path, Path],
    ovstage_runtime: Any,
) -> None:
    session = create_provider_session(runtime=ovstage_runtime)
    scene_a = session.open_stage(str(scene_paths[0]))
    adapter_a = create_stage_adapter(scene_a)
    selection_a = create_selection_adapter(scene_a, adapter_a)
    old_world = adapter_a.get_item_at_path("/World")
    old_shape = adapter_a.get_item_at_path("/World/Group_Unicode/PlainShape")

    scene_b = session.open_stage(str(scene_paths[1]))
    adapter_b = create_stage_adapter(scene_b)
    selection_b = create_selection_adapter(scene_b, adapter_b)
    try:
        assert scene_a.is_open is False
        assert adapter_a.get_item_at_path("/World") is None
        assert adapter_a.get_children(old_world) == []
        assert selection_a.to_selection_items([old_world, old_shape]) == []
        assert selection_a.to_adapter_items(["/World"]) == []

        new_world = adapter_b.get_item_at_path("/World")
        assert new_world is not old_world
        assert _child_paths(adapter_b, new_world) == ["/World/OnlyInReplacement"]
        assert selection_b.to_selection_items([old_world, new_world]) == ["/World"]
    finally:
        session.shutdown_scene()


def test_selection_translation_preserves_order_duplicates_and_defensive_lists(
    opened_a: tuple[Any, Any, Any, Any],
) -> None:
    _session, _scene, adapter, selection = opened_a
    paths = [
        "/World/Group_Unicode/PlainShape",
        "/Missing",
        "/World/Cameras/RealCamera",
        "/World/Group_Unicode/PlainShape",
        " /World ",
    ]

    items = selection.to_adapter_items(paths)
    assert [adapter.get_item_path(item) for item in items] == [
        "/World/Group_Unicode/PlainShape",
        "/World/Cameras/RealCamera",
        "/World/Group_Unicode/PlainShape",
    ]
    first = selection.to_selection_items(items)
    second = selection.to_selection_items(items)
    assert first == second == [
        "/World/Group_Unicode/PlainShape",
        "/World/Cameras/RealCamera",
        "/World/Group_Unicode/PlainShape",
    ]
    assert first is not second
    first.clear()
    assert selection.to_selection_items(items) == second


class _OperationProxy:
    def __init__(self, operation: Any, events: list[str], label: str) -> None:
        self._operation = operation
        self._events = events
        self._label = label

    def wait(self, *args: Any, **kwargs: Any) -> Any:
        self._events.append(f"{self._label}.wait")
        return self._operation.wait(*args, **kwargs)


class _HandleProxy:
    def __init__(self, handle: Any, events: list[str], label: str) -> None:
        self._handle = handle
        self._events = events
        self._label = label

    @property
    def handle(self) -> int:
        return int(self._handle.handle)

    def wait(self, *args: Any, **kwargs: Any) -> Any:
        self._events.append(f"{self._label}.wait")
        return self._handle.wait(*args, **kwargs)

    def result(self, *args: Any, **kwargs: Any) -> Any:
        self._events.append(f"{self._label}.result")
        return self._handle.result(*args, **kwargs)

    def release(self) -> _OperationProxy:
        self._events.append(f"{self._label}.release")
        return _OperationProxy(
            self._handle.release(),
            self._events,
            f"{self._label}.release_op",
        )


class _GroupProxy:
    def __init__(self, group: Any, events: list[str], number: int) -> None:
        self._group = group
        self._events = events
        self._number = number
        self.released = False

    def __getattr__(self, name: str) -> Any:
        if self.released:
            raise AssertionError("native read group was used after release")
        return getattr(self._group, name)

    @property
    def raw(self) -> Any:
        return self._group.raw

    def array(self, index: int) -> Any:
        if self.released:
            raise AssertionError("native read group array was used after release")
        self._events.append(f"group.{self._number}.copy")
        return self._group.array(index)


def test_native_query_read_results_are_waited_copied_and_released(
    opened_a: tuple[Any, Any, Any, Any],
) -> None:
    _session, scene, adapter, _selection = opened_a
    stage = scene._stage
    events: list[str] = []
    query_count = 0
    read_count = 0
    group_count = 0
    original_query = stage.query
    original_read = stage.read_attributes
    original_fetch = stage.fetch_read_next
    original_release_group = stage.release_group

    def query(*args: Any, **kwargs: Any) -> _HandleProxy:
        nonlocal query_count
        query_count += 1
        events.append(f"query.{query_count}.return")
        return _HandleProxy(original_query(*args, **kwargs), events, f"query.{query_count}")

    def read(query_handle: Any, *args: Any, **kwargs: Any) -> _HandleProxy:
        nonlocal read_count
        read_count += 1
        events.append(f"read.{read_count}.return")
        return _HandleProxy(
            original_read(query_handle, *args, **kwargs),
            events,
            f"read.{read_count}",
        )

    def fetch(read_handle: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal group_count
        group = original_fetch(read_handle, *args, **kwargs)
        if group is None:
            return None
        group_count += 1
        events.append(f"group.{group_count}.return")
        return _GroupProxy(group, events, group_count)

    def release_group(group: _GroupProxy) -> None:
        original_release_group(group)
        group.released = True
        events.append(f"group.{group._number}.release")

    stage.query = query
    stage.read_attributes = read
    stage.fetch_read_next = fetch
    stage.release_group = release_group
    stage._ovui_kit_stage_bridge_cache = None
    adapter._topology_version = None

    items = _walk(adapter)
    assert adapter.get_type_name(adapter.get_item_at_path("/World/BoxPretender")) == "Xform"
    assert len(items) == 15
    assert query_count > 0
    assert read_count > 0
    assert group_count > 0
    for number in range(1, query_count + 1):
        assert events.index(f"query.{number}.wait") < events.index(f"query.{number}.release")
        assert events.index(f"query.{number}.release") < events.index(
            f"query.{number}.release_op.wait"
        )
    for number in range(1, read_count + 1):
        assert events.index(f"read.{number}.wait") < events.index(f"read.{number}.release")
        assert events.index(f"read.{number}.release") < events.index(
            f"read.{number}.release_op.wait"
        )
    for number in range(1, group_count + 1):
        assert events.index(f"group.{number}.copy") < events.index(f"group.{number}.release")


_BLOCKED_SUBPROCESS = r'''
import importlib.abc
import sys

roots = ("pxr", "ovui_data_adapters.openusd")
attempts = []

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == root or fullname.startswith(root + ".") for root in roots):
            attempts.append(fullname)
            raise ModuleNotFoundError(fullname)
        return None

sys.meta_path.insert(0, Blocker())
from ovui_data_adapters.ovstage.provider import (
    create_provider_session,
    create_selection_adapter,
    create_stage_adapter,
)

session = create_provider_session()
scene = session.open_stage(sys.argv[1])
stage_adapter = create_stage_adapter(scene)
selection = create_selection_adapter(scene, stage_adapter)
item = stage_adapter.get_item_at_path("/World/Group_Unicode/PlainShape")
assert stage_adapter.get_type_name(item) == "Cube"
assert selection.to_selection_items([item]) == ["/World/Group_Unicode/PlainShape"]
session.shutdown_scene()
assert selection.to_adapter_items(["/World"]) == []
assert selection.to_selection_items([item]) == []
assert attempts == []
assert not [
    name for name in sys.modules
    if any(name == root or name.startswith(root + ".") for root in roots)
]
'''


def test_exact_runtime_hierarchy_and_selection_do_not_attempt_forbidden_imports(
    scene_paths: tuple[Path, Path],
) -> None:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", _BLOCKED_SUBPROCESS, str(scene_paths[0])],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

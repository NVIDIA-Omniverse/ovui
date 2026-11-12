# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ovstage api_v2 source-compatibility shims."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from ovui_data_adapters.common import VisibilityState
from ovui_data_adapters.ovstage import _scene as scene_module
from ovui_data_adapters.ovstage import stage_adapter as stage_module
from ovui_data_adapters.ovstage._native import read_token_attribute
from ovui_data_adapters.ovstage._native import resolve_query_names
from ovui_data_adapters.ovstage.change_stream import (
    _TopologyUnreadable,
    _native_topology_paths,
)
from ovui_data_adapters.ovstage.stage_adapter import OvstageStageAdapter
from ovui_data_adapters.ovstage._scene import (
    OvstageScene,
    _KitStageBridgeCache,
    _KitTopologySnapshot,
    _install_frame_lifecycle_compat,
    _kit_child_paths,
    _load_population_module,
    _populate_from_file,
    _reconcile_native_write_floor,
    _record_deleted_paths,
)


class _FloorOperation:
    def __init__(self, value: int) -> None:
        self._value = int(value)

    def wait(self) -> None:
        return None

    def fetch(self) -> int:
        return self._value

    def release(self) -> "_FloorOperation":
        return _FloorOperation(self._value)


class _FloorStage:
    def __init__(self, *, current_ordinal: int, native_write_floor: int) -> None:
        self.current_ordinal = int(current_ordinal)
        self._native_write_floor = int(native_write_floor)

    def get_attribute_write_floor(self) -> _FloorOperation:
        return _FloorOperation(self._native_write_floor)


def test_scene_current_ordinal_adopts_newer_native_write_floor() -> None:
    stage = _FloorStage(current_ordinal=7, native_write_floor=11)
    scene = OvstageScene(
        stage=stage,
        source_path="fixture.usda",
        initial_ordinal=7,
        root_paths=("/World",),
    )

    assert scene.current_ordinal == 11
    assert stage.current_ordinal == 11


def test_scene_current_ordinal_never_moves_back_from_stale_native_floor() -> None:
    stage = _FloorStage(current_ordinal=11, native_write_floor=7)
    scene = OvstageScene(
        stage=stage,
        source_path="fixture.usda",
        initial_ordinal=11,
        root_paths=("/World",),
    )

    assert scene.current_ordinal == 11
    assert stage.current_ordinal == 11


class _HashTrackedPath(str):
    hash_calls = 0

    def __hash__(self) -> int:
        type(self).hash_calls += 1
        return super().__hash__()


class _FloorCountStage:
    def __init__(self, *, current_ordinal: int, native_write_floor: int) -> None:
        self.current_ordinal = int(current_ordinal)
        self._native_write_floor = int(native_write_floor)
        self.floor_operations = 0

    def get_attribute_write_floor(self) -> _FloorOperation:
        self.floor_operations += 1
        return _FloorOperation(self._native_write_floor)


def _cached_hierarchy(monkeypatch, *, native_compat=True):
    stage = _FloorCountStage(current_ordinal=1, native_write_floor=1)
    if native_compat:
        stage._ovui_get_topology_version_source = "native current_ordinal"
    stage.get_topology_version = Mock(
        side_effect=lambda: _reconcile_native_write_floor(stage),
    )
    stage.records = {"/World": ("Xform", ()), "/World/Box": ("Mesh", ())}
    stage.get_child_paths = Mock(side_effect=lambda parent: tuple(
        path for path in stage.records
        if path.rsplit("/", 1)[0] == str(parent).rstrip("/")
    ))
    scene = OvstageScene(
        stage=stage, source_path="fixture.usda", initial_ordinal=1,
        root_paths=("/World",),
    )
    adapter = OvstageStageAdapter(scene)
    copy_types = Mock(side_effect=lambda _stage: dict(stage.records))
    monkeypatch.setattr(adapter, "_copy_type_records", copy_types)
    return stage, scene, adapter, copy_types


def test_real_topology_version_still_invalidates_hierarchy(monkeypatch):
    stage, _scene, adapter, copy_types = _cached_hierarchy(monkeypatch, native_compat=False)
    assert adapter.get_item_at_path("/World/New") is None
    stage.records["/World/New"] = ("Mesh", ())
    stage._native_write_floor = 2

    assert adapter.get_item_at_path("/World/New") is not None
    assert copy_types.call_count == 2
    assert stage.floor_operations == 2


@pytest.mark.parametrize("visibility,world,expected", [
    ("invisible", True, "invisible"),
    ("inherited", False, "inherited"),
    (None, False, "invisible"),
    (None, 0, "invisible"),
    (None, True, "inherited"),
    (None, None, "inherited"),
    ("invalid", False, "inherited"),
    (17, True, "invisible"),
])
def test_native_visibility_reads_only_exact_path_columns(
    monkeypatch, visibility, world, expected,
):
    stage = SimpleNamespace(
        _ovui_read_attribute_source="native Kit read_attributes",
        # An edit moved the stage past its whole-scene cache.
        current_ordinal=2,
        _ovui_kit_stage_bridge_cache=SimpleNamespace(ordinal=1),
    )
    whole_scene_read = Mock(side_effect=AssertionError("whole-scene read"))
    monkeypatch.setattr(scene_module, "_build_kit_stage_cache", whole_scene_read)
    scene_module._install_kit_stage_bridge_compat(stage)
    records = {}
    if visibility is not None:
        records["visibility"] = SimpleNamespace(value=visibility)
    if world is not None:
        records["_worldVisibility"] = SimpleNamespace(value=world)
    read = Mock(return_value=records)
    monkeypatch.setattr(stage_module, "read_path_attribute_records", read)
    monkeypatch.setattr(stage_module, "resolve_token_id", lambda _stage, token: "invisible")

    assert stage_module._read_raw_visibility(stage, "/World/Box") == expected
    read.assert_called_once_with(stage, "/World/Box", ("visibility", "_worldVisibility"))
    whole_scene_read.assert_not_called()


@pytest.mark.parametrize("value,expected", [
    ("proxy", "proxy"), ("render", "render"), ("default", "default"),
    (None, "geometry"), ("", "geometry"), (21, "proxy"), (0, "geometry"),
])
def test_native_purpose_reads_only_exact_path_column(monkeypatch, value, expected):
    stage = SimpleNamespace(
        _ovui_read_attribute_source="native Kit read_attributes",
        # An edit moved the stage past its whole-scene cache.
        current_ordinal=2,
        _ovui_kit_stage_bridge_cache=SimpleNamespace(ordinal=1),
    )
    records = {"purpose": SimpleNamespace(value=value)} if value is not None else {}
    read = Mock(return_value=records)
    broad_read = Mock(side_effect=AssertionError("compatibility token read"))
    monkeypatch.setattr(stage_module, "read_path_attribute_records", read)
    monkeypatch.setattr(stage_module, "read_token_attribute", broad_read)
    monkeypatch.setattr(stage_module, "resolve_token_id", lambda _stage, token: "proxy" if token else "")

    assert stage_module._read_raw_purpose(stage, "/World/Box") == expected
    read.assert_called_once_with(stage, "/World/Box", ("purpose",))
    broad_read.assert_not_called()


def test_native_spatial_read_failure_does_not_fall_back_to_whole_scene(monkeypatch):
    stage = SimpleNamespace(
        _ovui_read_attribute_source="native Kit read_attributes",
        # An edit moved the stage past its whole-scene cache.
        current_ordinal=2,
        _ovui_kit_stage_bridge_cache=SimpleNamespace(ordinal=1),
    )
    read = Mock(side_effect=RuntimeError("native read failed"))
    monkeypatch.setattr(stage_module, "read_path_attribute_records", read)
    broad_read = Mock(side_effect=AssertionError("whole-scene read"))
    stage.read_attribute = broad_read
    monkeypatch.setattr(stage_module, "read_token_attribute", broad_read)

    assert stage_module._read_raw_visibility(stage, "/World/Box") == "inherited"
    assert stage_module._read_raw_purpose(stage, "/World/Box") == "geometry"
    broad_read.assert_not_called()


@pytest.mark.parametrize("cache", [None, SimpleNamespace(ordinal=2)])
def test_native_spatial_reads_use_whole_scene_cache_on_open(monkeypatch, cache):
    # On open, camera framing builds the whole-scene cache for this ordinal.
    # One exact-path read per prim would only add time to the open.
    stage = SimpleNamespace(
        _ovui_read_attribute_source="native Kit read_attributes",
        current_ordinal=2,
        _ovui_kit_stage_bridge_cache=cache,
        read_attribute=Mock(return_value=b"invisible"),
    )
    exact_read = Mock(side_effect=AssertionError("exact-path read"))
    monkeypatch.setattr(stage_module, "read_path_attribute_records", exact_read)
    monkeypatch.setattr(stage_module, "read_token_attribute", Mock(return_value="proxy"))

    assert stage_module._read_raw_visibility(stage, "/World/Box") == "invisible"
    assert stage_module._read_raw_purpose(stage, "/World/Box") == "proxy"
    exact_read.assert_not_called()


# A Kit population can publish only the effective '_worldVisibility'. It is
# invisible also for a prim that a hidden ancestor hides, so it must not read
# as the prim's own hide (the Stage eye would show the closed eye).
_OWN_HIDDEN = {"visibility": b"invisible", "_worldVisibility": b"\x00"}
_OWN_INHERITED = {"visibility": b"inherited", "_worldVisibility": b"\x00"}
_WORLD_HIDDEN = {"_worldVisibility": b"\x00"}
_WORLD_VISIBLE = {"_worldVisibility": b"\x01"}
_EYE_OF_BOX_UNDER_PARENT = [
    # The stage gives the own value: the own hide comes first.
    (_OWN_HIDDEN, _OWN_HIDDEN, VisibilityState.INVISIBLE),
    (_OWN_HIDDEN, _OWN_INHERITED, VisibilityState.INHERITED_INVISIBLE),
    # Only the effective value: the ancestors decide.
    (_WORLD_HIDDEN, _WORLD_HIDDEN, VisibilityState.INHERITED_INVISIBLE),
    (_WORLD_VISIBLE, _WORLD_HIDDEN, VisibilityState.INVISIBLE),
    (_WORLD_VISIBLE, _WORLD_VISIBLE, VisibilityState.VISIBLE),
]


class _KitPopulationStage:
    """A Kit-integrated stage with /World/Parent/Box and the columns of its population."""

    def __init__(self, columns: dict[str, dict[str, bytes]], *, cache_ordinal: int) -> None:
        self.current_ordinal = 2
        self._ovui_kit_stage_bridge_cache = _KitStageBridgeCache(
            ordinal=cache_ordinal,
            path_order=tuple(columns),
            attrs={
                (path, name): value
                for path, values in columns.items()
                for name, value in values.items()
            },
            types={},
        )
        scene_module._install_kit_stage_bridge_compat(self)

    def query_prims(self, _ordinal: int) -> dict[str, object]:
        # The eye does not need the prim types.
        return {"groups": ()}

    def get_topology_version(self) -> int:
        return 1

    def get_child_paths(self, parent: str) -> tuple[str, ...]:
        return {
            "": ("/World",),
            "/World": ("/World/Parent",),
            "/World/Parent": ("/World/Parent/Box",),
        }.get(parent, ())

    def get_parent_path(self, path: str) -> str:
        return path.rsplit("/", 1)[0]


def _eye_state_of_box(stage: _KitPopulationStage) -> VisibilityState:
    scene = OvstageScene(
        stage=stage, source_path="fixture.usda", initial_ordinal=2,
        root_paths=("/World",),
    )
    adapter = OvstageStageAdapter(scene)
    return adapter.compute_visibility(adapter.get_item_at_path("/World/Parent/Box"))


@pytest.mark.parametrize("parent,box,expected", _EYE_OF_BOX_UNDER_PARENT)
def test_eye_on_open_tells_own_hide_from_world_visibility(parent, box, expected):
    stage = _KitPopulationStage(
        {"/World/Parent": parent, "/World/Parent/Box": box}, cache_ordinal=2,
    )

    assert _eye_state_of_box(stage) is expected


@pytest.mark.parametrize("parent,box,expected", _EYE_OF_BOX_UNDER_PARENT)
def test_eye_after_edit_tells_own_hide_from_world_visibility(
    monkeypatch, parent, box, expected,
):
    columns = {"/World/Parent": parent, "/World/Parent/Box": box}
    # An edit moved the stage past its whole-scene cache.
    stage = _KitPopulationStage(columns, cache_ordinal=1)
    monkeypatch.setattr(
        stage_module,
        "read_path_attribute_records",
        lambda _stage, path, _names: {
            name: SimpleNamespace(value=value.decode() if name == "visibility" else value[0])
            for name, value in columns.get(path, {}).items()
        },
    )

    assert _eye_state_of_box(stage) is expected


def test_legacy_spatial_token_reads_remain_unchanged(monkeypatch):
    stage = SimpleNamespace(current_ordinal=7, read_attribute=Mock(return_value=b"invisible"))
    narrow_read = Mock(side_effect=AssertionError("unexpected native path reader"))
    monkeypatch.setattr(stage_module, "read_path_attribute_records", narrow_read)
    purpose_read = Mock(return_value="proxy")
    monkeypatch.setattr(stage_module, "read_token_attribute", purpose_read)

    assert stage_module._read_raw_visibility(stage, "/World/Box") == "invisible"
    stage.read_attribute.assert_called_once_with(7, ["/World/Box"], "visibility")
    assert stage_module._read_raw_purpose(stage, "/World/Box") == "proxy"
    purpose_read.assert_called_once_with(stage, "/World/Box", "purpose")
    narrow_read.assert_not_called()


@pytest.mark.parametrize("cache_kind", ["topology", "bridge"])
def test_authoritative_cache_reuses_path_membership_across_parent_lookups(
    cache_kind: str,
) -> None:
    path_order = tuple(
        _HashTrackedPath(f"/World/Parent{index}/Leaf")
        for index in range(100)
    )
    if cache_kind == "topology":
        cache = _KitTopologySnapshot(7, path_order)
        cache_attribute = "_ovui_kit_topology_snapshot"
    else:
        cache = _KitStageBridgeCache(
            ordinal=7,
            path_order=path_order,
            attrs={},
            types={},
        )
        cache_attribute = "_ovui_kit_stage_bridge_cache"
    stage = SimpleNamespace(current_ordinal=7)
    setattr(stage, cache_attribute, cache)
    _HashTrackedPath.hash_calls = 0

    assert _kit_child_paths(stage, "/World/Parent1") == (
        "/World/Parent1/Leaf",
    )
    assert _kit_child_paths(stage, "/World/Parent2") == (
        "/World/Parent2/Leaf",
    )
    assert _kit_child_paths(stage, "/World/Parent3") == (
        "/World/Parent3/Leaf",
    )

    assert _HashTrackedPath.hash_calls == 0


def test_committed_floor_is_reconciled_once_before_multi_parent_traversal() -> None:
    stage = _FloorCountStage(current_ordinal=6, native_write_floor=7)
    stage._ovui_kit_topology_snapshot = _KitTopologySnapshot(
        7,
        (
            "/World/Parent1/Leaf",
            "/World/Parent2/Leaf",
            "/World/Parent3/Leaf",
        ),
    )

    assert _reconcile_native_write_floor(stage) == 7
    assert _kit_child_paths(stage, "/World/Parent1") == (
        "/World/Parent1/Leaf",
    )
    assert _kit_child_paths(stage, "/World/Parent2") == (
        "/World/Parent2/Leaf",
    )
    assert _kit_child_paths(stage, "/World/Parent3") == (
        "/World/Parent3/Leaf",
    )

    assert stage.floor_operations == 1


class _UnreadableStage:
    """A stage whose whole-stage reads answer nothing while its roots do.

    That is what a build with no ``usd-path`` rows looks like, and what any
    stage looks like while the connection is down.
    """

    current_ordinal = 9

    def __init__(self) -> None:
        self.whole_stage_reads = 0

    def query(self, filter=None, attrs=None):
        assert filter is None
        self.whole_stage_reads += 1
        return SimpleNamespace(wait=lambda: None)

    def read_attributes(self, _query, _attrs, _ordinal_range):
        return SimpleNamespace(wait=lambda: None)

    def fetch_read_next(self, _read):
        return None

    def release_read(self, _read) -> None:
        return None

    def release_query(self, _query) -> None:
        return None

    def get_attribute_write_floor(self) -> _FloorOperation:
        return _FloorOperation(self.current_ordinal)


def test_unreadable_topology_is_read_once_per_ordinal_but_reread_by_the_poll(
    monkeypatch,
) -> None:
    """A read that did not answer is not repeated per parent, by any surface.

    Every expanded parent asking the stage again turns one tree traversal into
    one failed read per row -- whole-stage and per-parent alike -- which is what
    makes an outage stall the application and grow its memory.  The poll owns
    the retry, so a source that comes back is still noticed at the same ordinal.
    """

    class _PathDictionary:
        def __init__(self, _stage) -> None:
            pass

        def __enter__(self) -> "_PathDictionary":
            return self

        def __exit__(self, *_exc) -> None:
            return None

        def intern_token(self, _name: str) -> int:
            return 1

    fake_ovstage = ModuleType("ovstage")
    fake_ovstage.PathDictionary = _PathDictionary
    fake_ovstage.OrdinalRange = SimpleNamespace(latest=lambda ordinal: ordinal)
    monkeypatch.setitem(sys.modules, "ovstage", fake_ovstage)
    monkeypatch.setattr(
        scene_module,
        "_kit_stage_cache",
        lambda stage, ordinal: _KitStageBridgeCache(
            ordinal=ordinal, path_order=(), attrs={}, types={}
        ),
    )
    monkeypatch.setattr(
        scene_module,
        "_hierarchy_kit_child_paths",
        lambda _stage, parent, _ordinal: ("/World",) if parent == "/" else None,
    )
    per_parent_reads = []
    monkeypatch.setattr(
        scene_module,
        "_filtered_kit_child_paths",
        lambda _stage, parent, _ordinal: per_parent_reads.append(parent),
    )

    stage = _UnreadableStage()
    stage._ovui_kit_topology_snapshot = _KitTopologySnapshot(
        8,
        ("/World", "/World/Parent1", "/World/Parent2", "/World/Parent3"),
    )

    # Walk root-down, the way the adapter rebuilds its topology cache.
    assert _kit_child_paths(stage, "/World") == (
        "/World/Parent1",
        "/World/Parent2",
        "/World/Parent3",
    )
    for parent in ("/World/Parent1", "/World/Parent2", "/World/Parent3"):
        assert _kit_child_paths(stage, parent) == ()
    assert stage.whole_stage_reads == 1
    # "/World" is the lookup made before anything was known; "/" is the single
    # reading the whole-stage probe takes to find out whether this surface is
    # answering at all.  Neither the remaining rows nor any repeat asks again.
    assert per_parent_reads == ["/World", "/"]

    with pytest.raises(_TopologyUnreadable):
        _native_topology_paths(stage)
    assert stage.whole_stage_reads == 2


def test_answering_parent_surface_is_used_when_the_whole_stage_read_is_not(
    monkeypatch,
) -> None:
    """A per-parent surface that still answers is not silenced by a failed
    whole-stage read.

    The two are different surfaces, and one can fail while the other works.
    While that is true the tree must follow the surface that answers, so a prim
    another writer removed leaves the tree straight away instead of lingering
    until the whole-stage surface comes back.
    """

    class _PathDictionary:
        def __init__(self, _stage) -> None:
            pass

        def __enter__(self) -> "_PathDictionary":
            return self

        def __exit__(self, *_exc) -> None:
            return None

        def intern_token(self, _name: str) -> int:
            return 1

    fake_ovstage = ModuleType("ovstage")
    fake_ovstage.PathDictionary = _PathDictionary
    fake_ovstage.OrdinalRange = SimpleNamespace(latest=lambda ordinal: ordinal)
    monkeypatch.setitem(sys.modules, "ovstage", fake_ovstage)
    monkeypatch.setattr(
        scene_module,
        "_kit_stage_cache",
        lambda stage, ordinal: _KitStageBridgeCache(
            ordinal=ordinal, path_order=(), attrs={}, types={}
        ),
    )
    monkeypatch.setattr(
        scene_module,
        "_hierarchy_kit_child_paths",
        lambda _stage, parent, _ordinal: ("/World",) if parent == "/" else None,
    )
    # The parent surface is up, and /World/Parent2 has been removed by another
    # writer since the last readable whole-stage topology was published.
    # /World/Parent1 has genuinely become empty, which is a real answer and
    # not a sign that the surface stopped working.
    live = {
        "/": ("/World",),
        "/World": ("/World/Parent1", "/World/Parent3"),
        "/World/Parent1": (),
        "/World/Parent3": ("/World/Parent3/Leaf",),
    }
    asked = []

    def _filtered(_stage, parent, _ordinal):
        asked.append(parent)
        return live.get(parent, ())

    monkeypatch.setattr(scene_module, "_filtered_kit_child_paths", _filtered)

    stage = _UnreadableStage()
    stage._ovui_kit_topology_snapshot = _KitTopologySnapshot(
        8,
        ("/World", "/World/Parent1", "/World/Parent2", "/World/Parent3"),
    )

    # The poll has already run and found the whole-stage read unanswered, which
    # is the state the parent lookups below have to survive.
    with pytest.raises(_TopologyUnreadable):
        _native_topology_paths(stage)

    assert _kit_child_paths(stage, "/World") == (
        "/World/Parent1",
        "/World/Parent3",
    )
    assert _kit_child_paths(stage, "/World/Parent1") == ()
    # One parent legitimately having no children is that parent's answer, not
    # evidence about the surface: the next parent is still read from it.
    assert _kit_child_paths(stage, "/World/Parent3") == ("/World/Parent3/Leaf",)
    # Every lookup reached the surface that answers; none was served from the
    # superseded whole-stage topology, which still lists /World/Parent2.
    assert asked == ["/", "/World", "/World/Parent1", "/World/Parent3"]


class _PrefixTrackedPath(str):
    startswith_calls = 0

    def startswith(self, prefix, *args):
        type(self).startswith_calls += 1
        return super().startswith(prefix, *args)


def test_deleted_metadata_pruning_scales_with_path_depth_not_removed_delta() -> None:
    removed = tuple(f"/World/Removed{index}/Leaf" for index in range(2_000))
    subtree_root = "/World/DeletedSubtree"
    surviving = _PrefixTrackedPath("/World/SurvivingSibling/Leaf")
    deleted_descendant = _PrefixTrackedPath(f"{subtree_root}/Branch/Leaf")
    authored_types = {
        **{
            _PrefixTrackedPath(path): "Xform"
            for path in removed
        },
        deleted_descendant: "Mesh",
        surviving: "Scope",
    }
    births = {path: 7 for path in authored_types}
    stage = SimpleNamespace(
        _ovui_authored_prim_types=authored_types,
        _ovui_path_birth_ordinals=births,
    )
    _PrefixTrackedPath.startswith_calls = 0

    _record_deleted_paths(stage, (*removed, subtree_root))

    assert stage._ovui_authored_prim_types == {surviving: "Scope"}
    assert stage._ovui_path_birth_ordinals == {surviving: 7}
    assert _PrefixTrackedPath.startswith_calls < len(removed) * 20


def test_open_scene_from_file_is_public_package_export() -> None:
    import ovui_data_adapters.ovstage as ovstage_package
    from ovui_data_adapters.ovstage import open_scene_from_file
    from ovui_data_adapters.ovstage._scene import open_scene_from_file as implementation

    assert open_scene_from_file is implementation
    assert "open_scene_from_file" in ovstage_package.__all__


def test_renderer_adapter_is_public_package_export() -> None:
    import ovui_data_adapters.ovstage as ovstage_package
    from ovui_data_adapters.ovstage import OvstageRendererAdapter
    from ovui_data_adapters.ovstage.renderer_adapter import (
        OvstageRendererAdapter as implementation,
    )

    assert OvstageRendererAdapter is implementation
    assert "OvstageRendererAdapter" in ovstage_package.__all__


class _FakePathDictionary:
    def __init__(self, names: dict[int, str]) -> None:
        self._names = dict(names)

    def token_to_string(self, _dict_pointer, token: int) -> tuple[int, str]:
        return (0, self._names.get(int(token), ""))


class _ApiV2Stage:
    current_ordinal = 7

    def __init__(self) -> None:
        self.queries: list[dict[str, list[str]]] = []
        self.released: list[int] = []

    def update_write_floor(self, ordinal: int) -> None:
        self.current_ordinal = int(ordinal)

    def query_prims(self, ordinal: int, **_kwargs) -> dict[str, object]:
        return {"native": True, "ordinal": int(ordinal)}

    def query(self, *, parent_in: list[str]) -> tuple[int, dict[str, int]]:
        self.queries.append({"parent_in": list(parent_in)})
        return (101, {"all_handle": 202})

    def get_prim_paths(self, handle: int) -> tuple[str, ...]:
        assert handle == 202
        return ("/World/A", "/World/B")

    def release_query(self, query_handle: int) -> None:
        self.released.append(int(query_handle))


def test_api_v2_compat_does_not_override_native_query_prims() -> None:
    stage = _ApiV2Stage()

    _install_frame_lifecycle_compat(stage)

    assert "query_prims" not in stage.__dict__
    assert stage.query_prims(3) == {"native": True, "ordinal": 3}


def test_api_v2_get_child_paths_uses_native_parent_query() -> None:
    stage = _ApiV2Stage()

    _install_frame_lifecycle_compat(stage)

    assert stage.get_child_paths("/World") == ("/World/A", "/World/B")
    assert stage.queries == [{"parent_in": ["/World"]}]
    assert stage.released == [101]
    assert stage._ovui_get_child_paths_source == "native query(parent_in)"


def test_kit_get_child_paths_filters_native_parent_metadata(monkeypatch) -> None:
    """Hierarchy lookup must not build the broad property bridge cache."""

    class _Operation:
        def wait(self) -> None:
            return None

    class _Query(_Operation):
        released = False

        def release(self) -> _Operation:
            self.released = True
            return _Operation()

    class _Read(_Operation):
        def __init__(self) -> None:
            self.groups = [SimpleNamespace(prim_list=501)]
            self.released = False

        def release(self) -> _Operation:
            self.released = True
            return _Operation()

    class _PathDictionary:
        def __init__(self, _stage) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

        def intern_token(self, value: str) -> int:
            assert value == "usd-path"
            return 71

        def create_path_list_from_strings(self, paths) -> int:
            assert list(paths) == ["/"]
            return 601

        def destroy_path_list(self, handle: int) -> None:
            assert handle == 601

        def get_path_strings(self, handle: int) -> list[str]:
            assert handle == 501
            return ["/World", "/Environment"]

    class _Predicate:
        def __init__(self, attribute, op, values) -> None:
            self.attribute = attribute
            self.op = op
            self.values = tuple(values)

    class _Filter:
        def __init__(self, predicates) -> None:
            self.predicates = tuple(predicates)

    class _FilterOp:
        IN = 1

    class _HierarchyRelation:
        CHILDREN = 1

    class _OrdinalRange:
        @classmethod
        def latest(cls, ordinal: int):
            return ("latest", int(ordinal))

    class _KitStage:
        current_ordinal = 7

        def __init__(self) -> None:
            self.filters = []
            self.reads = []
            self.query_handle = None
            self.read_handle = None
            self.hierarchy_calls = []

        def get_hierarchy(self, path_list, ordinal, relation):
            self.hierarchy_calls.append((path_list, ordinal, relation))
            item = SimpleNamespace(ok=False, paths=())
            return SimpleNamespace(items=[item])

        def query(self, filter=None, attrs=None):
            if filter is None:
                raise AssertionError("child lookup must not build the broad stage cache")
            predicate = filter.predicates[0]
            self.filters.append(
                (predicate.attribute, predicate.op, predicate.values, tuple(attrs))
            )
            self.query_handle = _Query()
            return self.query_handle

        def fetch_query_result(self, _query):
            raise AssertionError("the filtered query is consumed through read groups")

        def read_attributes(self, _query, attrs, ordinal_range):
            self.reads.append((tuple(attrs), ordinal_range))
            self.read_handle = _Read()
            return self.read_handle

        def fetch_read_next(self, read: _Read):
            return read.groups.pop(0) if read.groups else None

        def release_group(self, _group) -> None:
            return None

    fake_ovstage = ModuleType("ovstage")
    fake_ovstage.Filter = _Filter
    fake_ovstage.FilterOp = _FilterOp
    fake_ovstage.HierarchyRelation = _HierarchyRelation
    fake_ovstage.OrdinalRange = _OrdinalRange
    fake_ovstage.PathDictionary = _PathDictionary
    fake_ovstage.Predicate = _Predicate
    monkeypatch.setitem(sys.modules, "ovstage", fake_ovstage)

    stage = _KitStage()
    _install_frame_lifecycle_compat(stage)

    assert stage.get_child_paths("") == ("/Environment", "/World")
    assert stage.hierarchy_calls == [(601, 7, _HierarchyRelation.CHILDREN)]
    assert stage.filters == [("usd-parent", _FilterOp.IN, ("/",), (71,))]
    assert stage.reads == [((71,), ("latest", 7))]
    assert stage.query_handle.released is True
    assert stage.read_handle.released is True


def test_kit_get_child_paths_prefers_native_hierarchy(monkeypatch) -> None:
    class _PathDictionary:
        destroyed = []

        def __init__(self, _stage) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

        def create_path_list_from_strings(self, paths) -> int:
            assert list(paths) == ["/"]
            return 601

        def destroy_path_list(self, handle: int) -> None:
            self.destroyed.append(handle)

    class _HierarchyRelation:
        CHILDREN = 1

    class _KitStage:
        current_ordinal = 9

        def __init__(self) -> None:
            self.hierarchy_calls = []
            self._ovui_authored_prim_types = {
                "/Created": "Xform",
                "/World/Nested": "Xform",
            }

        def query(self, *_args, **_kwargs):
            raise AssertionError("native hierarchy must avoid a filter query")

        def fetch_query_result(self, _query):
            raise AssertionError

        def read_attributes(self, *_args, **_kwargs):
            raise AssertionError

        def get_hierarchy(self, path_list, ordinal, relation):
            self.hierarchy_calls.append((path_list, ordinal, relation))
            item = SimpleNamespace(
                ok=True,
                paths=("/World", "/Environment", "/__Fabric_StageInfo"),
            )
            return SimpleNamespace(items=[item])

    fake_ovstage = ModuleType("ovstage")
    fake_ovstage.HierarchyRelation = _HierarchyRelation
    fake_ovstage.PathDictionary = _PathDictionary
    monkeypatch.setitem(sys.modules, "ovstage", fake_ovstage)

    stage = _KitStage()
    _install_frame_lifecycle_compat(stage)

    assert stage.get_child_paths("") == ("/Created", "/Environment", "/World")
    assert stage.hierarchy_calls == [(601, 9, _HierarchyRelation.CHILDREN)]
    assert _PathDictionary.destroyed == [601]
    assert stage._ovui_get_child_paths_source.startswith("native hierarchy")


def test_native_token_helpers_resolve_query_names_and_token_attributes() -> None:
    class _Stage:
        current_ordinal = 1

        def _path_dict(self):
            return (_FakePathDictionary({5: "Cube", 9: "test:count"}), object())

        def read_attribute(self, _ordinal, _paths, _attr_name):
            return (5).to_bytes(8, "little")

    stage = _Stage()

    assert resolve_query_names(stage, ["<token 9>", "size"]) == ("test:count", "size")
    assert read_token_attribute(stage, "/World/Cube", "usd-prim-type") == "Cube"


def test_integrated_kit_population_module_is_supported() -> None:
    module = ModuleType("ovstage")
    population = ModuleType("ovstage.population")
    calls: list[tuple[object, str, int]] = []

    def open_usd(stage, path, ordinal):
        calls.append((stage, path, ordinal))

    population.open_usd = open_usd
    module.population = population
    stage = object()

    loaded = _load_population_module(module)
    _populate_from_file(loaded, stage, "scene.usda", 12)

    assert loaded is population
    assert calls == [(stage, "scene.usda", 12)]


def test_explicit_population_domains_use_sync_open_usd() -> None:
    population = ModuleType("ovstage.population")
    calls: list[tuple[object, str, int, int]] = []
    stage = object()

    def open_usd(value, path, ordinal, *, domains):
        calls.append((value, path, ordinal, domains))

    population.open_usd = open_usd

    _populate_from_file(
        population,
        stage,
        "scene.usda",
        12,
        population_domains=3,
    )

    assert calls == [(stage, "scene.usda", 12, 3)]


def test_explicit_population_domains_prefer_async_open_usd() -> None:
    population = ModuleType("ovstage.population")
    calls: list[tuple[object, str, int, int]] = []
    waits: list[str] = []
    stage = object()

    class _Operation:
        def wait(self) -> None:
            waits.append("wait")

    def open_usd_async(value, path, ordinal, *, domains):
        calls.append((value, path, ordinal, domains))
        return _Operation()

    def populate_from_file_async(*_args, **_kwargs):
        raise AssertionError("explicit domains require an open_usd entry point")

    population.open_usd_async = open_usd_async
    population.populate_from_file_async = populate_from_file_async

    _populate_from_file(
        population,
        stage,
        "scene.usda",
        12,
        population_domains=5,
    )

    assert calls == [(stage, "scene.usda", 12, 5)]
    assert waits == ["wait"]


def test_scene_exposes_live_native_stage() -> None:
    native = object()
    scene = OvstageScene(
        stage=native,
        source_path="scene.usda",
        initial_ordinal=1,
        root_paths=("/World",),
    )

    assert scene.native_stage is native

    scene._stage = None
    with pytest.raises(RuntimeError, match="scene is closed"):
        _ = scene.native_stage


def test_kit_stage_bridge_query_prims_and_read_attribute(monkeypatch) -> None:
    class _FakeOrdinalRange:
        @classmethod
        def latest(cls, ordinal: int):
            return ("latest", int(ordinal))

    class _FakeKitPathDictionary:
        names = {
            10: "omni:fabric:localMatrix",
            11: "omni:fabric:worldMatrix",
            12: "size",
            13: "points",
            14: "faceVertexCounts",
            15: "faceVertexIndices",
            16: "focalLength",
            17: "material:binding",
            18: "usd-prim-type",
            30: "Xform",
            31: "Cube",
            32: "Mesh",
            33: "Camera",
        }
        tokens = {value: key for key, value in names.items()}
        path_lists = {
            100: (
                "/World",
                "/World/Cube",
                "/World/Mesh",
                "/Cameras/Main",
                "/__Fabric_StageInfo",
            ),
        }

        def __init__(self, _stage) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

        def intern_token(self, value: str) -> int:
            token = self.tokens.get(value)
            if token is None:
                token = max(self.names) + 1
                self.tokens[value] = token
                self.names[token] = value
            return token

        def token_to_string(self, token: int) -> str:
            return self.names[int(token)]

        def path_to_string(self, path: int) -> str:
            return {200: "/World/Looks/Material"}[int(path)]

        def get_path_strings(self, handle: int) -> list[str]:
            return list(self.path_lists[int(handle)])

    class _FakeQuery:
        def __init__(self, attrs):
            # Model OVStage 0.1's broad-discovery omission: the relationship
            # is readable when explicitly requested even though it is absent
            # from query(None, None). The bridge must therefore carry the
            # standard material binding in its mandatory request set.
            discovered = [
                token
                for token, name in _FakeKitPathDictionary.names.items()
                if token != _FakeKitPathDictionary.tokens["material:binding"]
                and name not in ("Xform", "Cube", "Mesh", "Camera")
            ]
            self.attrs = list(discovered if attrs is None else attrs)

        def result(self):
            return type(
                "QueryResult",
                (),
                {
                    "attributes": list(self.attrs),
                    "total_prim_count": 5,
                    "all_handle": 100,
                },
            )()

        def release(self) -> None:
            return None

    class _FakeGroup:
        prim_list = 100
        has_prim_index_map = False
        has_data_index_map = False
        tensor_count = 1
        ordinal = 1
        is_delete = False

        def __init__(
            self,
            attr: int,
            offset: int,
            count: int,
            values,
            *,
            is_array: bool = False,
            semantic: int = 0,
        ) -> None:
            self.attribute = attr
            self.prim_offset = offset
            self.prim_count = count
            self.data_count = count
            self._values = values
            self.raw = SimpleNamespace(
                is_array=bool(is_array),
                semantic=int(semantic),
            )

        def prim_index(self, local: int) -> int:
            return self.prim_offset + int(local)

        def data_row_index(self, local: int) -> int:
            return int(local)

        def array(self, _index: int):
            return self._values

        def tensor(self, _index: int):
            code = {"i": 0, "u": 1, "f": 2}[self._values.dtype.kind]
            return SimpleNamespace(
                dtype=SimpleNamespace(
                    code=code,
                    bits=int(self._values.dtype.itemsize) * 8,
                    lanes=1,
                )
            )

    class _FakeRead:
        def __init__(self, *, binding_only: bool) -> None:
            if binding_only:
                self.groups = [
                    _FakeGroup(
                        17,
                        1,
                        1,
                        np.array([200], dtype=np.uint64),
                        is_array=True,
                        semantic=4,
                    )
                ]
                return
            matrices = (
                np.eye(4, dtype=np.float64)
                .reshape(1, 16)
                .repeat(5, axis=0)
                .reshape(-1)
            )
            self.groups = [
                _FakeGroup(10, 0, 5, matrices),
                _FakeGroup(11, 0, 5, matrices),
                _FakeGroup(12, 1, 1, np.array([2.5], dtype=np.float64)),
                _FakeGroup(
                    13,
                    2,
                    1,
                    np.array([0, 0, 0, 1, 0, 0, 0, 1, 0], dtype=np.float32),
                ),
                _FakeGroup(14, 2, 1, np.array([3], dtype=np.int32)),
                _FakeGroup(15, 2, 1, np.array([0, 1, 2], dtype=np.int32)),
                _FakeGroup(16, 3, 1, np.array([35.0], dtype=np.float32)),
                # Authoritative native prim types, one token row per prim in
                # prim-list order; the internal Fabric bookkeeping prim has no
                # public type token (0 reads back as the truthful empty type).
                _FakeGroup(
                    18,
                    0,
                    5,
                    np.array(
                        [
                            _FakeKitPathDictionary.tokens["Xform"],
                            _FakeKitPathDictionary.tokens["Cube"],
                            _FakeKitPathDictionary.tokens["Mesh"],
                            _FakeKitPathDictionary.tokens["Camera"],
                            0,
                        ],
                        dtype=np.uint64,
                    ),
                ),
            ]

    class _KitLikeStage:
        current_ordinal = 1

        def __init__(self) -> None:
            self.requested_attrs: list[list[int]] = []

        def query(self, _filter=None, attrs=None):
            return _FakeQuery(attrs)

        def fetch_query_result(self, _query):
            raise AssertionError("query.result() is used by the Kit wrapper")

        def read_attributes(self, _query, attrs, _ordinal_range):
            requested = list(attrs)
            self.requested_attrs.append(requested)
            binding = _FakeKitPathDictionary.tokens["material:binding"]
            return _FakeRead(binding_only=requested == [binding])

        def fetch_read_next(self, read: _FakeRead):
            if not read.groups:
                return None
            return read.groups.pop(0)

        def release_group(self, _group) -> None:
            return None

        def release_read(self, _read) -> None:
            return None

        def release_query(self, _query) -> None:
            return None

    fake_ovstage = ModuleType("ovstage")
    fake_ovstage.PathDictionary = _FakeKitPathDictionary
    fake_ovstage.OrdinalRange = _FakeOrdinalRange
    monkeypatch.setitem(sys.modules, "ovstage", fake_ovstage)

    stage = _KitLikeStage()

    _install_frame_lifecycle_compat(stage)

    result = stage.query_prims(1)
    by_type = {
        group["prim_type"]: stage.get_prim_paths(group["prim_list_handle"])
        for group in result["groups"]
    }

    # /World carries the authoritative native type; /Cameras is a synthesized
    # hierarchy ancestor with no native metadata, so its type is truthfully
    # empty rather than guessed.
    assert by_type["Xform"] == ("/World",)
    assert by_type[""] == ("/Cameras",)
    assert by_type["Cube"] == ("/World/Cube",)
    assert by_type["Mesh"] == ("/World/Mesh",)
    assert by_type["Camera"] == ("/Cameras/Main",)
    assert stage.get_child_paths("") == ("/Cameras", "/World")
    assert stage.get_child_paths("/Cameras") == ("/Cameras/Main",)
    assert stage.get_child_paths("/World") == ("/World/Cube", "/World/Mesh")
    assert stage.read_attribute(1, ["/World/Cube"], "usd-prim-type") == b"Cube"
    assert (
        stage.read_attribute(1, ["/World/Cube"], "size")
        == np.array([2.5], dtype=np.float64).tobytes()
    )
    material_binding = _FakeKitPathDictionary.tokens["material:binding"]
    assert any(
        material_binding in request and len(request) > 1
        for request in stage.requested_attrs
    )
    assert [material_binding] in stage.requested_attrs
    assert stage.read_path_targets(
        1,
        "/World/Cube",
        "material:binding",
    ) == ("/World/Looks/Material",)
    assert stage._ovui_query_prims_source == "native Kit query/read_attributes"

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Runtime-free tests for the Kit stage bridge property-enumeration surface.

These cover the helpers that let the Property Inspector list and decode
attributes of a selected Kit ovstage prim (fixing the prior "No properties"
state): attribute-name exposure, column dtype derivation, and the cache's
per-path attribute listing / column-dtype lookup.
"""
from __future__ import annotations

import struct
import sys
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import Mock

import numpy as np
import pytest

from ovui_data_adapters.ovstage import _scene
from ovui_data_adapters.ovstage import property_adapter as property_module


def test_kit_material_path_request_contract_for_ovstage_01(monkeypatch) -> None:
    """Require readable binding data without claiming unreadable connections.

    A direct Kit OVStage 0.1 probe of a populated UsdShade material returns a
    semantic-4 group for ``material:binding``. The same public query/read flow
    returns no group for any of the four material terminal spellings below:
    Fabric owns those values under ``NameSuffix::connection`` and OVStage 0.1
    filters that suffix from discovery/type negotiation.
    """

    monkeypatch.setattr(_scene, "_discover_kit_attr_names", lambda _stage: ())

    requested = set(_scene._requested_kit_attr_names(object()))
    unreadable_connection_forms = {
        "outputs:surface",
        "outputs:surface.connect",
        "outputs:displacement",
        "outputs:displacement.connect",
    }

    assert "material:binding" in requested
    assert requested.isdisjoint(unreadable_connection_forms)


def test_exposed_attr_name_maps_and_hides() -> None:
    # Fabric matrix columns surface under their common names.
    assert _scene._kit_exposed_attr_name("omni:fabric:localMatrix") == "localMatrix"
    assert _scene._kit_exposed_attr_name("omni:fabric:worldMatrix") == "worldMatrix"
    # Ordinary attributes pass through.
    assert _scene._kit_exposed_attr_name("size") == "size"
    assert _scene._kit_exposed_attr_name("extent") == "extent"
    # Bridge-internal / underscore-prefixed attributes are hidden.
    assert _scene._kit_exposed_attr_name("_worldVisibility") is None
    assert _scene._kit_exposed_attr_name("_worldExtent") is None


def test_row_dtype_float32_cast_attrs() -> None:
    # extent is down-cast to float32 in _array_row_bytes; dtype must match.
    arr = np.zeros((1, 6), dtype=np.float64)  # 6 values per prim
    assert _scene._kit_row_dtype(arr, 1, "extent") == (2, 32, 6)


def test_row_dtype_native_kinds() -> None:
    # size: one float64 per prim -> (FLOAT=2, 64, lanes=1).
    assert _scene._kit_row_dtype(np.zeros((1, 1), dtype=np.float64), 1, "size") == (2, 64, 1)
    # localMatrix: 16 float64 per prim -> matrix lanes=16.
    assert _scene._kit_row_dtype(
        np.zeros((1, 16), dtype=np.float64), 1, "omni:fabric:localMatrix"
    ) == (2, 64, 16)
    # an integer column maps to DLPack int code 0.
    assert _scene._kit_row_dtype(np.zeros((1, 1), dtype=np.int32), 1, "count") == (0, 32, 1)


def test_row_dtype_rejects_zero_width() -> None:
    assert _scene._kit_row_dtype(np.zeros((0,), dtype=np.float64), 1, "x") is None


def _cache_with(dtypes):
    return _scene._KitStageBridgeCache(
        ordinal=1,
        path_order=tuple({p for (p, _n) in dtypes}),
        attrs={},
        types={},
        dtypes=dtypes,
    )


def test_cache_attribute_names_and_column_dtype() -> None:
    cube = "/World/Hierarchy/GroupA/BoxA"
    dtypes = {
        (cube, "size"): (2, 64, 1),
        (cube, "extent"): (2, 32, 6),
        (cube, "localMatrix"): (2, 64, 16),
        ("/World/Other", "radius"): (2, 64, 1),
    }
    cache = _cache_with(dtypes)
    # Per-path attribute names are sorted and scoped to the path.
    assert cache.attribute_names_for_path(cube) == ("extent", "localMatrix", "size")
    assert cache.attribute_names_for_path("/World/Other") == ("radius",)
    # Column dtype lookup resolves through the registered handle's paths.
    handle = cache.register_paths((cube,))
    assert cache.column_dtype(handle, "size") == (2, 64, 1)
    assert cache.column_dtype(handle, "localMatrix") == (2, 64, 16)
    assert cache.column_dtype(handle, "missing") is None


class _SinglePassDict(dict[tuple[str, str], Any]):
    def __init__(self, values: dict[tuple[str, str], Any]) -> None:
        super().__init__(values)
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        if self.iterations > 1:
            raise AssertionError("mapping keys were rescanned per prim")
        return super().__iter__()


def test_cache_indexes_attribute_names_once() -> None:
    cube = "/World/Cube"
    sphere = "/World/Sphere"
    dtypes = _SinglePassDict(
        {
            (cube, "extent"): (2, 32, 6),
            (cube, "size"): (2, 64, 1),
            (sphere, "radius"): (2, 64, 1),
        }
    )
    cache = _scene._KitStageBridgeCache(
        ordinal=1,
        path_order=(cube, sphere),
        attrs={},
        types={cube: "Cube", sphere: "Sphere"},
        dtypes=dtypes,
    )

    assert cache.attribute_names_for_path(cube) == ("extent", "size")
    assert cache.attribute_names_for_path(sphere) == ("radius",)
    assert dtypes.iterations == 1


class _PathDictionary:
    def path_to_string(self, identifier: int) -> str:
        return {
            11: "/World/Looks/Material",
            12: "/World/Looks/Material/Shader",
        }[identifier]

    def token_to_string(self, identifier: int) -> str:
        return {21: "outputs:surface"}[identifier]


def test_cache_decodes_relationship_and_connection_semantics() -> None:
    cube = "/World/Cube"
    material = "/World/Looks/Material"
    cache = _scene._KitStageBridgeCache(
        ordinal=3,
        path_order=(cube, material),
        attrs={
            (cube, "material:binding"): struct.pack("<Q", 11),
            (material, "outputs:surface"): struct.pack("<QQ", 12, 21),
        },
        types={cube: "Cube", material: "Material"},
        semantics={
            (cube, "material:binding"): 4,
            (material, "outputs:surface"): 12,
        },
    )
    paths = _PathDictionary()

    assert cache.read_path_targets(cube, "material:binding", paths) == (
        "/World/Looks/Material",
    )
    assert cache.read_path_targets(material, "outputs:surface", paths) == (
        "/World/Looks/Material/Shader.outputs:surface",
    )
    assert cache.read_path_targets(cube, "size", paths) is None


def test_cache_rejects_misaligned_path_semantic_payload() -> None:
    cache = _scene._KitStageBridgeCache(
        ordinal=1,
        path_order=("/World/Cube",),
        attrs={("/World/Cube", "material:binding"): b"bad"},
        types={},
        semantics={("/World/Cube", "material:binding"): 4},
    )

    try:
        cache.read_path_targets(
            "/World/Cube",
            "material:binding",
            _PathDictionary(),
        )
    except ValueError as exc:
        assert "invalid byte count" in str(exc)
    else:  # pragma: no cover - defensive failure branch
        raise AssertionError("misaligned relationship bytes must be rejected")


@pytest.mark.parametrize("profiling", [False, True])
def test_property_diagnostics_preserve_reads_and_cache_hits(monkeypatch, profiling):
    names = []

    def profile_call(name, function, *args):
        names.append(name)
        return function(*args)

    stage = SimpleNamespace(
        current_ordinal=1,
        get_topology_version=lambda: 7,
        query_prims=Mock(return_value={"groups": [
            {"prim_list_handle": 1, "attributes": ["size"]},
        ]}),
        get_prim_paths=Mock(return_value=["/World/Box"]),
    )
    scene = SimpleNamespace(
        _stage=stage, is_open=True,
        profile_ovui_call=profile_call if profiling else None,
    )
    adapter = property_module._NativeOvstagePropertyAdapter(scene, ["/World/Box"])
    monkeypatch.setattr(property_module, "_read_attribute_info", lambda *args: ((2, 32, 1), 0, False))
    monkeypatch.setattr(property_module, "_read_attribute_bytes", lambda *args: struct.pack("<f", 3.0))

    assert adapter.get_attribute_names() == ["size"]
    assert adapter.get_attribute_names() == ["size"]
    assert adapter.get_value("size") == 3.0
    stage.query_prims.assert_called_once_with(1)
    stage.get_prim_paths.assert_called_once_with(1)
    if profiling:
        assert names.count("OvstagePropertyAdapter.copy_path_descriptors") == 1
        assert names.count("OvstagePropertyAdapter.query_prims") == 1
        assert "OvstagePropertyAdapter.read_attribute_info" in names
        assert "OvstagePropertyAdapter.read_attribute_bytes" in names
        assert "OvstagePropertyAdapter.read_value_bytes" in names
        assert "OvstagePropertyAdapter.decode_value" in names
    else:
        assert names == []


@pytest.fixture
def selected_property_stage(monkeypatch):
    """Exercise the real bridge copier with only exact-path native operations."""
    tokens: dict[str, int] = {}
    path_lists: dict[int, tuple[str, ...]] = {}
    operations = []
    released_groups = []

    class Paths:
        def __init__(self, stage):
            self.stage = stage

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            pass

        def intern_token(self, name):
            return tokens.setdefault(name, len(tokens) + 1)

        def token_to_string(self, token):
            return next(name for name, value in tokens.items() if value == token)

        def create_path_list_from_strings(self, paths):
            handle = max(path_lists, default=0) + 1
            path_lists[handle] = tuple(paths)
            return handle

        def destroy_path_list(self, handle):
            del path_lists[handle]

        def get_path_strings(self, handle):
            return path_lists[handle]

        def path_to_string(self, identifier):
            return {200: "/World/Looks/Material", 201: "/World/Looks/Shader"}[identifier]

    class Operation:
        def __init__(self, **data):
            self.__dict__.update(data)
            self.released = False
            operations.append(self)

        def wait(self):
            pass

        def release(self):
            self.released = True

        def result(self):
            names = dict.fromkeys(
                name for path in self.paths for name in stage.values.get(path, {})
                # Preserve Kit 0.1's discovery omission; binding still needs
                # the existing dedicated narrow read pass.
                if name != "material:binding"
            )
            return SimpleNamespace(attributes=[Paths(stage).intern_token(name) for name in names])

    class Stage:
        current_ordinal = 1

        def __init__(self):
            self.values = {"/World/Box": {"size": (np.array([3.0]), 0, False)}}
            self.queries = []
            self.reads = []
            self.query = Mock(side_effect=AssertionError("whole-scene query"))
            self.fail_read = False

        def get_topology_version(self):
            return self.current_ordinal

        def query_from_path_list(self, handle):
            self.queries.append(path_lists[handle])
            return Operation(paths=path_lists[handle], path_list=handle)

        def read_attributes(self, query, attrs, ordinal):
            if self.fail_read:
                raise RuntimeError("read failed")
            self.reads.append((query.paths, tuple(attrs), ordinal))
            groups = []
            for index, path in enumerate(query.paths):
                for name, (array, semantic, is_array) in self.values.get(path, {}).items():
                    token = Paths(self).intern_token(name)
                    if token not in attrs or (name == "material:binding" and len(attrs) != 1):
                        continue
                    groups.append(SimpleNamespace(
                        attribute=token, prim_list=query.path_list,
                        prim_count=1, data_count=1, tensor_count=1,
                        prim_index=lambda _local, index=index: index,
                        data_row_index=lambda _local: 0,
                        array=lambda _tensor, array=array: array,
                        tensor=lambda _tensor, array=array: SimpleNamespace(dtype=SimpleNamespace(
                            code={"i": 0, "u": 1, "f": 2}[array.dtype.kind],
                            bits=array.dtype.itemsize * 8, lanes=1,
                        )),
                        raw=SimpleNamespace(semantic=semantic, is_array=is_array),
                    ))
            return Operation(groups=groups)

        def fetch_read_next(self, read):
            return read.groups.pop(0) if read.groups else None

        def release_group(self, group):
            released_groups.append(group)

    stage = Stage()
    ovstage = ModuleType("ovstage")
    ovstage.PathDictionary = Paths
    ovstage.OrdinalRange = SimpleNamespace(latest=lambda ordinal: ordinal)
    monkeypatch.setitem(sys.modules, "ovstage", ovstage)
    _scene._install_kit_stage_bridge_compat(stage)
    scene = SimpleNamespace(_stage=stage, is_open=True)
    adapter = property_module._NativeOvstagePropertyAdapter(scene, ["/World/Box"])
    return stage, adapter, Paths(stage), path_lists, operations, released_groups


def test_selected_properties_never_populate_whole_stage_cache(selected_property_stage):
    stage, adapter, _paths, path_lists, operations, groups = selected_property_stage
    stage.values["/World/Unselected"] = {"unrelated": (np.arange(1000.0), 0, True)}
    sentinel = object()
    stage._ovui_kit_stage_bridge_cache = sentinel

    assert adapter.is_valid()
    assert adapter.get_attribute_names() == ["size"]
    assert adapter.get_value("size") == 3.0
    assert adapter.get_attribute_metadata("size").type_name == "double"
    assert set(stage.queries) == {("/World/Box",)}
    assert set(adapter._path_descriptors) == {"/World/Box"}
    stage.query.assert_not_called()
    assert stage._ovui_kit_stage_bridge_cache is sentinel
    assert path_lists == {}
    assert all(operation.released for operation in operations)
    assert len(groups) == 1

    query_count = len(stage.queries)
    assert adapter.get_value("size") == 3.0
    assert len(stage.queries) == query_count
    stage.values["/World/Box"]["size"] = (np.array([4.0]), 0, False)
    stage.current_ordinal = 2
    assert adapter.get_value("size") == 4.0
    assert len(stage.queries) > query_count
    stage.query.assert_not_called()


@pytest.mark.parametrize("mismatch", ["missing", "dtype", "semantic", "array", "value"])
def test_selected_properties_preserve_multiselection(selected_property_stage, mismatch):
    stage, adapter, _paths, _lists, _ops, _groups = selected_property_stage
    second = {
        "missing": {},
        "dtype": {"size": (np.array([3], dtype=np.int32), 0, False)},
        "semantic": {"size": (np.array([3.0]), 5, False)},
        "array": {"size": (np.array([3.0]), 0, True)},
        "value": {"size": (np.array([7.0]), 0, False)},
    }[mismatch]
    stage.values["/World/Other"] = second
    adapter._paths = ["/World/Box", "/World/Other"]

    if mismatch == "value":
        assert adapter.get_attribute_names() == ["size"]
        assert adapter.is_ambiguous("size")
        assert adapter.get_value("size") is None
    else:
        assert adapter.get_attribute_names() == []
    assert set(stage.queries) == {("/World/Box",), ("/World/Other",)}
    stage.query.assert_not_called()


def test_selected_properties_preserve_relationship_asset_token_and_matrix(selected_property_stage):
    stage, adapter, paths, _lists, _ops, _groups = selected_property_stage
    asset = b"relative.png\0C:/textures/resolved.png\0"
    stage.values["/World/Box"].update({
        "visibility": (np.array([paths.intern_token("inherited")], dtype=np.uint64), 2, False),
        "material:binding": (np.array([200], dtype=np.uint64), 4, True),
        "connection": (np.array([201, paths.intern_token("outputs:surface")], dtype=np.uint64), 12, True),
        "texture": (np.frombuffer(asset, dtype=np.uint8), 1, True),
        "omni:fabric:localMatrix": (np.eye(4).reshape(-1), 10, False),
        "samples": (np.arange(65, dtype=np.float32), 0, True),
    })

    assert adapter.get_value("visibility") == "inherited"
    assert adapter.get_value("material:binding") == ("/World/Looks/Material",)
    assert adapter.get_value("connection") == ("/World/Looks/Shader.outputs:surface",)
    assert adapter.get_value("texture") == "relative.png"
    assert adapter.get_resolved_asset_path("texture") == "C:/textures/resolved.png"
    assert adapter.get_value("localMatrix") == tuple(np.eye(4).reshape(-1))
    assert adapter.get_attribute_metadata("localMatrix").is_locked
    assert adapter.get_attribute_metadata("samples").is_big_array
    assert adapter.get_value("samples") == tuple(float(value) for value in range(65))
    stage.query.assert_not_called()


@pytest.mark.parametrize("paths", [[], ["invalid"], ["/World/Missing"]])
def test_selected_properties_empty_invalid_or_missing_paths(selected_property_stage, paths):
    stage, adapter, _dictionary, lists, operations, _groups = selected_property_stage
    adapter._paths = paths
    assert not adapter.is_valid()
    assert adapter.get_attribute_names() == []
    stage.query.assert_not_called()
    assert lists == {}
    assert all(operation.released for operation in operations)
    if not paths or paths == ["invalid"]:
        assert stage.queries == []


def test_selected_property_failed_read_releases_handles_and_retries(selected_property_stage):
    stage, adapter, _dictionary, lists, operations, _groups = selected_property_stage
    stage.fail_read = True
    with pytest.raises(RuntimeError, match="read failed"):
        adapter.get_attribute_names()
    assert lists == {}
    assert all(operation.released for operation in operations)
    assert adapter._selection_cache is None
    stage.fail_read = False
    assert adapter.get_value("size") == 3.0
    stage.query.assert_not_called()


def test_selected_property_failed_query_creation_releases_path_list(selected_property_stage):
    stage, adapter, _dictionary, lists, _operations, _groups = selected_property_stage
    stage.query_from_path_list = Mock(side_effect=RuntimeError("query failed"))
    with pytest.raises(RuntimeError, match="query failed"):
        adapter.get_attribute_names()
    assert lists == {}
    assert adapter._selection_cache is None
    stage.query.assert_not_called()


def test_selected_property_malformed_relationship_has_no_broad_fallback(selected_property_stage):
    stage, adapter, _dictionary, _lists, _operations, _groups = selected_property_stage
    stage.values["/World/Box"]["material:binding"] = (
        np.array([1, 2, 3], dtype=np.uint8), 4, True,
    )
    adapter.get_attribute_names()
    assert property_module._read_path_targets(
        stage, "/World/Box", "material:binding", adapter._selection_cache,
    ) is None
    stage.query.assert_not_called()

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovstage api_v2 source-compatibility shims."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import numpy as np

from ovui_data_adapters.ovstage._native import read_token_attribute
from ovui_data_adapters.ovstage._native import resolve_query_names
from ovui_data_adapters.ovstage._scene import (
    _install_frame_lifecycle_compat,
    _load_population_module,
    _populate_from_file,
)


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

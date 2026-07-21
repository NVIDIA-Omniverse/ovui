# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION is strictly
# prohibited.

"""OVStage-native property inspection, semantics, and lifetime contracts."""

from __future__ import annotations

import os
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, Iterator

import numpy as np
import pytest

from ovui_data_adapters.ovstage._constants import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
)
from ovui_data_adapters.ovstage._scene import _merge_kit_read_groups
from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter
from ovui_data_adapters.ovstage.provider import (
    create_property_adapter,
    create_provider_session,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes


_SCENE = '''#usda 1.0

def Xform "World"
{
    def Material "Material" {}
    def Mesh "BoundMesh" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        int[] faceVertexCounts = [3]
        int[] faceVertexIndices = [0, 1, 2]
        int[] holeIndices = []
        point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        rel material:binding = </World/Material>
    }
    def Camera "Camera"
    {
        double2 clippingRange = (0.1, 1000)
        float focalLength = 35
    }
    def Xform "Translated"
    {
        double3 xformOp:translate = (1, 2, 3)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }
    def Xform "Custom"
    {
        custom string test:label = "Café Δ"
    }
}
'''


def _write_scene(tmp_path: Path, name: str = "property-contract.usda") -> Path:
    path = tmp_path / name
    path.write_text(_SCENE, encoding="utf-8")
    return path


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
def exact_scene(
    tmp_path: Path,
    ovstage_runtime: Any,
) -> Iterator[tuple[Any, Any]]:
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(_write_scene(tmp_path)))
    try:
        yield session, scene
    finally:
        session.shutdown_scene()


class _FakeStage:
    current_ordinal = 7

    def __init__(self) -> None:
        self._paths = {
            1: ("/A",),
            2: ("/B",),
        }
        self._attrs: dict[str, tuple[str, ...]] = {
            "/A": (
                "misleadingAssetName",
                "plainToken",
                "falseValue",
                "halfValue",
                "float2Value",
                "pointValue",
                "colorValue",
                "quatValue",
                "matrixValue",
                "stringValue",
                "assetValue",
                "emptyArray",
                "oneElementArray",
                "pointArray",
                "tokenArray",
                "targetRelationship",
                "targetConnection",
                "unknownValue",
                "malformedValue",
                "malformedSemantic",
                "typeMismatch",
                "onlyA",
            ),
            "/B": (
                "misleadingAssetName",
                "plainToken",
                "falseValue",
                "halfValue",
                "float2Value",
                "pointValue",
                "colorValue",
                "quatValue",
                "matrixValue",
                "stringValue",
                "assetValue",
                "emptyArray",
                "oneElementArray",
                "pointArray",
                "tokenArray",
                "targetRelationship",
                "targetConnection",
                "unknownValue",
                "malformedSemantic",
                "typeMismatch",
            ),
        }
        common = {
            "misleadingAssetName": ((2, 32, 1), 0, False, struct.pack("<f", 2.5)),
            "plainToken": ((1, 64, 1), 2, False, struct.pack("<Q", 10)),
            "falseValue": ((6, 8, 1), 0, False, b"\x00"),
            "halfValue": ((2, 16, 1), 0, False, struct.pack("<e", 1.5)),
            "pointValue": ((2, 32, 3), 5, False, struct.pack("<3f", 1, 2, 3)),
            "colorValue": ((2, 64, 4), 8, False, struct.pack("<4d", .1, .2, .3, .4)),
            "quatValue": ((2, 32, 4), 9, False, struct.pack("<4f", 1, 2, 3, 4)),
            "matrixValue": ((2, 64, 16), 10, False, struct.pack("<16d", *range(16))),
            "stringValue": ((1, 8, 1), 13, True, "Café Δ".encode()),
            "assetValue": ((1, 8, 1), 1, True, b"textures/albedo.png"),
            "emptyArray": ((0, 32, 1), 0, True, b""),
            "oneElementArray": ((0, 32, 1), 0, True, struct.pack("<i", 7)),
            "pointArray": ((2, 32, 3), 5, True, struct.pack("<6f", 1, 2, 3, 4, 5, 6)),
            "tokenArray": ((1, 64, 1), 2, True, struct.pack("<2Q", 10, 11)),
            "targetRelationship": ((1, 64, 1), 4, True, struct.pack("<Q", 101)),
            "targetConnection": ((1, 64, 2), 12, True, struct.pack("<2Q", 102, 12)),
            "unknownValue": ((7, 8, 1), 0, False, b"\x03"),
            "malformedSemantic": ((2, 32, 1), 99, False, struct.pack("<f", 1.0)),
        }
        self._records: dict[tuple[str, str], tuple[tuple[int, int, int], int, bool, bytes]] = {}
        for path in ("/A", "/B"):
            for name, record in common.items():
                self._records[(path, name)] = record
        self._records[("/A", "float2Value")] = (
            (2, 32, 2), 0, False, struct.pack("<2f", 1.0, 2.0)
        )
        self._records[("/B", "float2Value")] = (
            (2, 32, 2), 0, False, struct.pack("<2f", 1.0, 9.0)
        )
        self._records[("/B", "pointValue")] = (
            (2, 32, 3), 5, False, struct.pack("<3f", 1.0, 9.0, 3.0)
        )
        self._records[("/A", "malformedValue")] = ((2, 32, 1), 0, False, b"")
        self._records[("/A", "onlyA")] = ((0, 32, 1), 0, False, struct.pack("<i", 3))
        self._records[("/A", "typeMismatch")] = (
            (2, 32, 1), 0, False, struct.pack("<f", 1.0)
        )
        self._records[("/B", "typeMismatch")] = (
            (0, 32, 1), 0, False, struct.pack("<i", 1)
        )

    def get_topology_version(self) -> int:
        return 1

    def query_prims(self, _ordinal: int) -> dict[str, object]:
        return {
            "groups": [
                {"prim_list_handle": 1, "attributes": self._attrs["/A"]},
                {"prim_list_handle": 2, "attributes": self._attrs["/B"]},
            ]
        }

    def get_prim_paths(self, handle: int) -> tuple[str, ...]:
        return self._paths[int(handle)]

    def read_attribute_info(
        self, _ordinal: int, path: str, name: str
    ) -> dict[str, object] | None:
        record = self._records.get((str(path), str(name)))
        if record is None:
            return None
        dtype, semantic, is_array, _payload = record
        return {"dtype": dtype, "semantic": semantic, "is_array": is_array}

    def read_attribute(self, _ordinal: int, paths: list[str], name: str) -> bytes:
        return self._records[(str(paths[0]), str(name))][3]

    def read_path_targets(
        self, _ordinal: int, _path: str, name: str
    ) -> tuple[str, ...] | None:
        if name == "targetRelationship":
            return ("/Target",)
        if name == "targetConnection":
            return ("/Target.outputs:value",)
        return None

    def resolve_token(self, token: int) -> str:
        return {10: "first", 11: "second"}.get(int(token), "")


class _FakeScene:
    def __init__(self, stage: Any) -> None:
        self._stage = stage
        self.is_open = True


def test_semantic_and_array_metadata_drive_public_property_surface() -> None:
    adapter = OvstagePropertyAdapter(_FakeScene(_FakeStage()), ["/A"])

    assert adapter.get_attribute_names() == [
        name for name in _FakeStage()._attrs["/A"] if name != "malformedValue"
    ]
    assert adapter.get_attribute_metadata("misleadingAssetName").type_name == "float"
    assert adapter.get_value("misleadingAssetName") == pytest.approx(2.5)
    assert adapter.get_attribute_metadata("plainToken").type_name == "token"
    assert adapter.get_value("plainToken") == "first"
    assert adapter.get_attribute_metadata("falseValue").value_type is bool
    assert adapter.get_attribute_metadata("falseValue").is_locked is True
    assert adapter.get_value("falseValue") is False
    assert adapter.get_attribute_metadata("halfValue").type_name == "half"
    assert adapter.get_attribute_metadata("halfValue").is_locked is True
    assert adapter.get_value("halfValue") == pytest.approx(1.5)

    expected = {
        "float2Value": ("float2", "float2", (1.0, 2.0)),
        "pointValue": ("point3f", "float3", (1.0, 2.0, 3.0)),
        "colorValue": ("color4d", "color4f", (.1, .2, .3, .4)),
        "quatValue": ("quatf", tuple, (1.0, 2.0, 3.0, 4.0)),
        "matrixValue": ("matrix4d", tuple, tuple(float(i) for i in range(16))),
    }
    for name, (type_name, value_type, value) in expected.items():
        metadata = adapter.get_attribute_metadata(name)
        assert metadata.type_name == type_name
        assert metadata.value_type == value_type
        np.testing.assert_allclose(adapter.get_value(name), value)


def test_text_arrays_targets_unknown_and_metadata_are_defensive() -> None:
    adapter = OvstagePropertyAdapter(_FakeScene(_FakeStage()), ["/A"])

    assert adapter.get_value("stringValue") == "Café Δ"
    assert adapter.get_attribute_metadata("stringValue").type_name == "string"
    assert adapter.get_value("assetValue") == "textures/albedo.png"
    assert adapter.get_attribute_metadata("assetValue").value_type == "asset"
    assert adapter.get_resolved_asset_path("assetValue") is None
    assert adapter.get_value("emptyArray") == ()
    assert adapter.get_value("oneElementArray") == (7,)
    assert adapter.get_value("pointArray") == (
        (1.0, 2.0, 3.0),
        (4.0, 5.0, 6.0),
    )
    assert adapter.get_value("tokenArray") == ("first", "second")
    for name in ("emptyArray", "oneElementArray", "pointArray", "tokenArray"):
        metadata = adapter.get_attribute_metadata(name)
        assert metadata.type_name == "array"
        assert metadata.value_type == "array"
        assert metadata.is_locked is True

    assert adapter.get_value("targetRelationship") == ("/Target",)
    assert adapter.get_value("targetConnection") == ("/Target.outputs:value",)
    for name in ("targetRelationship", "targetConnection"):
        metadata = adapter.get_attribute_metadata(name)
        assert metadata.type_name == "relationship"
        assert metadata.value_type == "relationship"
        assert metadata.is_locked is True

    unknown = adapter.get_attribute_metadata("unknownValue")
    assert unknown.type_name == "unknown"
    assert unknown.is_locked is True
    assert adapter.get_value("unknownValue") == (3,)
    malformed = adapter.get_attribute_metadata("malformedSemantic")
    assert malformed.type_name == "unknown"
    assert malformed.is_locked is True
    assert adapter.get_value("malformedSemantic") == tuple(struct.pack("<f", 1.0))
    assert "malformedValue" not in adapter.get_attribute_names()
    assert all(
        adapter.get_attribute_metadata(name).is_authored is False
        and adapter.get_attribute_metadata(name).is_time_sampled is False
        for name in adapter.get_attribute_names()
    )


def test_multiselect_is_intersection_ordered_and_reports_component_ambiguity() -> None:
    adapter = OvstagePropertyAdapter(_FakeScene(_FakeStage()), ["/A", "/B"])

    assert "onlyA" not in adapter.get_attribute_names()
    assert "typeMismatch" not in adapter.get_attribute_names()
    assert adapter.is_ambiguous("float2Value") is True
    assert adapter.get_value("float2Value") is None
    assert adapter.get_per_component_ambiguity("float2Value") == [False, True]
    assert adapter.is_ambiguous("pointValue") is True
    assert adapter.get_per_component_ambiguity("pointValue") == [False, True, False]
    assert adapter.is_ambiguous("oneElementArray") is False
    assert adapter.get_per_component_ambiguity("oneElementArray") is None
    names = adapter.get_attribute_names()
    assert names == [
        name
        for name in _FakeStage()._attrs["/A"]
        if name in _FakeStage()._attrs["/B"] and name != "typeMismatch"
    ]
    names.append("caller-mutation")
    assert "caller-mutation" not in adapter.get_attribute_names()


@pytest.mark.parametrize("path", ["", " ", "A", " /A", "/A ", "/A/", "//A", "/A/./B"])
def test_noncanonical_property_paths_are_invalid(path: str) -> None:
    adapter = OvstagePropertyAdapter(_FakeScene(_FakeStage()), [path])
    assert adapter.is_valid() is False
    assert adapter.get_attribute_names() == []


def test_closed_property_adapter_clears_cached_state() -> None:
    scene = _FakeScene(_FakeStage())
    adapter = OvstagePropertyAdapter(scene, ["/A"])
    assert adapter.is_valid() is True
    assert adapter.get_attribute_names()
    scene.is_open = False
    assert adapter.is_valid() is False
    assert adapter.get_attribute_names() == []
    with pytest.raises(NotImplementedError):
        adapter.get_value("float2Value")


def test_exact_wheel_properties_use_native_semantics_and_truth(
    exact_scene: tuple[Any, Any],
) -> None:
    _session, scene = exact_scene
    mesh = create_property_adapter(scene, ["/World/BoundMesh"])
    camera = create_property_adapter(scene, ["/World/Camera"])
    translated = create_property_adapter(scene, ["/World/Translated"])
    custom = create_property_adapter(scene, ["/World/Custom"])

    assert mesh.get_value("material:binding") == ("/World/Material",)
    relationship = mesh.get_attribute_metadata("material:binding")
    assert relationship.type_name == "relationship"
    assert relationship.value_type == "relationship"
    assert relationship.is_locked is False
    assert mesh.get_value("faceVertexCounts") == (3,)
    assert mesh.get_value("faceVertexIndices") == (0, 1, 2)
    assert mesh.get_value("holeIndices") == ()
    for name in ("faceVertexCounts", "faceVertexIndices", "holeIndices", "points"):
        metadata = mesh.get_attribute_metadata(name)
        assert metadata.type_name == "array"
        assert metadata.value_type == "array"
        assert metadata.is_locked is False
    np.testing.assert_allclose(
        mesh.get_value("points"),
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    )
    assert {
        "usd-prim-type",
        "omni:fabric:resetXformStack",
        "omni:rtx:skip",
    }.isdisjoint(mesh.get_attribute_names())
    assert {"refinementLevel", "singleSided", "timeVaryingAttributes"}.issubset(
        mesh.get_attribute_names()
    )
    assert mesh.get_value("singleSided") is False
    assert mesh.get_attribute_metadata("singleSided").is_locked is False

    clipping = camera.get_attribute_metadata("clippingRange")
    assert clipping.type_name == "float2"
    assert clipping.value_type == "float2"
    assert camera.get_value("clippingRange") == pytest.approx((1.0, 1_000_000.0))
    assert clipping.is_authored is False
    assert clipping.is_time_sampled is False
    assert "xformOp:translate" not in translated.get_attribute_names()
    assert "test:label" not in custom.get_attribute_names()


def test_exact_wheel_values_are_python_owned_after_native_group_release(
    exact_scene: tuple[Any, Any],
) -> None:
    _session, scene = exact_scene
    mesh = create_property_adapter(scene, ["/World/BoundMesh"])
    points = mesh.get_value("points")
    names = mesh.get_attribute_names()

    scene._stage._ovui_kit_stage_bridge_cache = None
    assert create_property_adapter(scene, ["/World/BoundMesh"]).get_value("points") == points
    assert points == ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    names.append("caller-mutation")
    assert "caller-mutation" not in mesh.get_attribute_names()


class _Waitable:
    def __init__(self, events: list[str], name: str, *, fail: bool = False) -> None:
        self.events = events
        self.name = name
        self.fail = fail

    def wait(self) -> None:
        self.events.append(f"{self.name}.wait")
        if self.fail:
            raise RuntimeError(f"{self.name} failed")


class _Handle(_Waitable):
    handle = 1

    def release(self) -> _Waitable:
        self.events.append(f"{self.name}.release")
        return _Waitable(self.events, f"{self.name}.release_op")


class _Group:
    attribute = 10
    prim_list = 20
    prim_count = 1
    data_count = 1
    tensor_count = 1
    raw = SimpleNamespace(is_array=True, semantic=5)

    def __init__(self, values: np.ndarray, events: list[str]) -> None:
        self.values = values
        self.events = events

    def prim_index(self, _local: int) -> int:
        return 0

    def data_row_index(self, _local: int) -> int:
        return 0

    def array(self, _index: int) -> np.ndarray:
        self.events.append("group.borrow")
        return self.values

    def tensor(self, _index: int) -> Any:
        return SimpleNamespace(dtype=SimpleNamespace(code=2, bits=32, lanes=3))


def test_read_group_values_and_metadata_are_copied_before_release() -> None:
    events: list[str] = []
    values = np.array([1, 2, 3, 4, 5, 6], dtype=np.float32)
    group = _Group(values, events)
    query = _Handle(events, "query")
    read = _Handle(events, "read")

    class _Stage:
        def query(self, _filter: Any, _attrs: Any) -> _Handle:
            events.append("query.return")
            return query

        def read_attributes(self, _query: Any, _attrs: Any, _range: Any) -> _Handle:
            events.append("read.return")
            return read

        def fetch_read_next(self, _read: Any) -> Any:
            if "group.return" in events:
                return None
            events.append("group.return")
            return group

        def release_group(self, _group: Any) -> None:
            events.append("group.release")
            values[:] = 99

    class _Paths:
        def token_to_string(self, _token: int) -> str:
            return "points"

        def get_path_strings(self, _handle: int) -> tuple[str, ...]:
            return ("/Mesh",)

    attrs: dict[tuple[str, str], bytes] = {}
    dtypes: dict[tuple[str, str], tuple[int, int, int]] = {}
    semantics: dict[tuple[str, str], int] = {}
    arrays: dict[tuple[str, str], bool] = {}
    path_order: list[str] = []
    _merge_kit_read_groups(
        _Stage(),
        _Paths(),
        attr_tokens=[10],
        ordinal_range=object(),
        attrs=attrs,
        dtypes=dtypes,
        semantics=semantics,
        arrays=arrays,
        path_order=path_order,
        seen_paths=set(),
    )

    assert attrs[("/Mesh", "points")] == struct.pack("<6f", 1, 2, 3, 4, 5, 6)
    assert dtypes[("/Mesh", "points")] == (2, 32, 3)
    assert semantics[("/Mesh", "points")] == 5
    assert arrays[("/Mesh", "points")] is True
    assert events.index("query.wait") < events.index("read.wait")
    assert events.index("group.borrow") < events.index("group.release")
    assert events.index("group.release") < events.index("read.release")
    assert events.index("read.release_op.wait") < events.index("query.release")
    assert events.index("query.release") < events.index("query.release_op.wait")


def test_query_failure_still_releases_query_handle() -> None:
    events: list[str] = []
    query = _Handle(events, "query", fail=True)

    class _Stage:
        def query(self, _filter: Any, _attrs: Any) -> _Handle:
            return query

    with pytest.raises(RuntimeError, match="query failed"):
        _merge_kit_read_groups(
            _Stage(),
            object(),
            attr_tokens=[10],
            ordinal_range=object(),
            attrs={},
            dtypes={},
            semantics={},
            arrays={},
            path_order=[],
            seen_paths=set(),
        )
    assert events == ["query.wait", "query.release", "query.release_op.wait"]


def test_read_failure_releases_read_and_query_handles() -> None:
    events: list[str] = []
    query = _Handle(events, "query")
    read = _Handle(events, "read", fail=True)

    class _Stage:
        def query(self, _filter: Any, _attrs: Any) -> _Handle:
            return query

        def read_attributes(self, _query: Any, _attrs: Any, _range: Any) -> _Handle:
            return read

    with pytest.raises(RuntimeError, match="read failed"):
        _merge_kit_read_groups(
            _Stage(),
            object(),
            attr_tokens=[10],
            ordinal_range=object(),
            attrs={},
            dtypes={},
            semantics={},
            arrays={},
            path_order=[],
            seen_paths=set(),
        )
    assert events == [
        "query.wait",
        "read.wait",
        "read.release",
        "read.release_op.wait",
        "query.release",
        "query.release_op.wait",
    ]


def test_group_decode_failure_still_releases_group_and_handles() -> None:
    events: list[str] = []
    query = _Handle(events, "query")
    read = _Handle(events, "read")
    group = _Group(np.array([1], dtype=np.float32), events)

    class _Stage:
        def query(self, _filter: Any, _attrs: Any) -> _Handle:
            return query

        def read_attributes(self, _query: Any, _attrs: Any, _range: Any) -> _Handle:
            return read

        def fetch_read_next(self, _read: Any) -> Any:
            return group

        def release_group(self, _group: Any) -> None:
            events.append("group.release")

    class _Paths:
        def token_to_string(self, _token: int) -> str:
            raise RuntimeError("token decode failed")

    with pytest.raises(RuntimeError, match="token decode failed"):
        _merge_kit_read_groups(
            _Stage(),
            _Paths(),
            attr_tokens=[10],
            ordinal_range=object(),
            attrs={},
            dtypes={},
            semantics={},
            arrays={},
            path_order=[],
            seen_paths=set(),
        )
    assert "group.release" in events
    assert events.index("group.release") < events.index("read.release")
    assert events.index("read.release_op.wait") < events.index("query.release")


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
from ovui_data_adapters.ovstage.provider import create_property_adapter, create_provider_session

session = create_provider_session()
scene = session.open_stage(sys.argv[1])
mesh = create_property_adapter(scene, ["/World/BoundMesh"])
assert mesh.get_value("material:binding") == ("/World/Material",)
assert mesh.get_value("faceVertexCounts") == (3,)
assert mesh.get_value("holeIndices") == ()
assert mesh.get_attribute_metadata("faceVertexIndices").value_type == "array"
session.shutdown_scene()
assert mesh.is_valid() is False
assert mesh.get_attribute_names() == []
assert attempts == []
assert not [
    name for name in sys.modules
    if any(name == root or name.startswith(root + ".") for root in roots)
]
'''


def test_exact_runtime_property_path_attempts_no_forbidden_imports(tmp_path: Path) -> None:
    scene_path = _write_scene(tmp_path, "blocked-property.usda")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", _BLOCKED_SUBPROCESS, str(scene_path)],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

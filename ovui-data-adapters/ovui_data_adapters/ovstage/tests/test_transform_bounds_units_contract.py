# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION is strictly
# prohibited.

"""OVStage-native transform, visibility, bounds, and units contracts."""

from __future__ import annotations

import math
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from ovui_data_adapters.common import VisibilityState
from ovui_data_adapters.ovstage._constants import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
)
from ovui_data_adapters.ovstage.provider import (
    create_provider_session,
    create_stage_adapter,
    create_transform_adapter,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes


_SCENE = '''#usda 1.0
(
    metersPerUnit = 0.5
    upAxis = "Z"
)

def Xform "World"
{
    def Xform "Parent"
    {
        double3 xformOp:translate = (3, -4, 5)
        double xformOp:rotateZ = 37
        float3 xformOp:scale = (2, 3, -1)
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateZ", "xformOp:scale"]

        def Cube "Child"
        {
            double size = 2
            double3 xformOp:translate = (1, 2, 3)
            double3 xformOp:rotateXYZ = (15, -25, 40)
            float3 xformOp:scale = (-1, 0.5, 2)
            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]
        }
    }

    def Xform "ResetParent"
    {
        double3 xformOp:translate = (100, 200, 300)
        uniform token[] xformOpOrder = ["xformOp:translate"]

        def Cube "ResetChild"
        {
            double size = 4
            double3 xformOp:translate = (7, 8, 9)
            uniform token[] xformOpOrder = ["!resetXformStack!", "xformOp:translate"]
        }
    }

    def Xform "Singular"
    {
        float3 xformOp:scale = (1, 0, -2)
        uniform token[] xformOpOrder = ["xformOp:scale"]
    }

    def Cube "Visible"
    {
        double size = 2
        double3 xformOp:translate = (10, 0, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }

    def Xform "HiddenParent"
    {
        uniform token visibility = "invisible"
        double3 xformOp:translate = (100, 0, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]

        def Sphere "InheritedChild"
        {
            double radius = 20
        }
    }

    def Sphere "HiddenChild"
    {
        double radius = 25
        uniform token visibility = "invisible"
        double3 xformOp:translate = (300, 0, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }

    def Sphere "ProxyChild"
    {
        double radius = 30
        uniform token purpose = "proxy"
        double3 xformOp:translate = (200, 0, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }
}
'''


def _write_scene(tmp_path: Path) -> Path:
    path = tmp_path / "transform-bounds-units.usda"
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
def opened_scene(
    tmp_path: Path,
    ovstage_runtime: Any,
) -> Iterator[tuple[Any, Any, Any, Any]]:
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(_write_scene(tmp_path)))
    stage_adapter = create_stage_adapter(scene)
    transform_adapter = create_transform_adapter(scene)
    try:
        yield session, scene, stage_adapter, transform_adapter
    finally:
        session.shutdown_scene()


def _matmul(lhs: list[list[float]], rhs: list[list[float]]) -> list[list[float]]:
    return [
        [
            sum(float(lhs[row][inner]) * float(rhs[inner][column]) for inner in range(4))
            for column in range(4)
        ]
        for row in range(4)
    ]


def _assert_matrix_close(
    actual: list[list[float]],
    expected: list[list[float]],
) -> None:
    assert len(actual) == len(expected) == 4
    for actual_row, expected_row in zip(actual, expected):
        assert actual_row == pytest.approx(expected_row, abs=1.0e-6)


def _assert_bounds_close(actual: Any, expected: Any) -> None:
    assert actual is not None
    assert actual[0] == pytest.approx(expected[0], abs=1.0e-6)
    assert actual[1] == pytest.approx(expected[1], abs=1.0e-6)


def test_exact_native_matrices_use_row_vector_composition_and_preserve_reset_and_singular(
    opened_scene: tuple[Any, Any, Any, Any],
) -> None:
    _session, _scene, _stage_adapter, transform = opened_scene

    parent_world = transform.get_world_transform("/World/Parent")
    child_local = transform.get_local_transform("/World/Parent/Child")
    child_world = transform.get_world_transform("/World/Parent/Child")
    _assert_matrix_close(child_world, _matmul(child_local, parent_world))
    assert child_world[3][:3] == pytest.approx(
        [0.9863810712849301, 1.995443036765154, 2.0],
        abs=1.0e-6,
    )

    reset_local = transform.get_local_transform("/World/ResetParent/ResetChild")
    reset_world = transform.get_world_transform("/World/ResetParent/ResetChild")
    _assert_matrix_close(reset_world, reset_local)
    assert reset_world[3][:3] == pytest.approx([7.0, 8.0, 9.0])

    singular = transform.get_world_transform("/World/Singular")
    assert singular[1][1] == 0.0
    assert singular[2][2] == -2.0

    first = transform.get_world_transform("/World/Parent")
    first[3][0] = 12345.0
    assert transform.get_world_transform("/World/Parent")[3][0] == pytest.approx(3.0)


def test_visibility_is_effective_and_bounds_match_default_purpose_subtree_semantics(
    opened_scene: tuple[Any, Any, Any, Any],
) -> None:
    _session, _scene, stage, _transform = opened_scene

    hidden_parent = stage.get_item_at_path("/World/HiddenParent")
    inherited_child = stage.get_item_at_path("/World/HiddenParent/InheritedChild")
    hidden_child = stage.get_item_at_path("/World/HiddenChild")
    visible = stage.get_item_at_path("/World/Visible")
    assert stage.compute_visibility(hidden_parent) is VisibilityState.INVISIBLE
    assert stage.compute_visibility(inherited_child) is VisibilityState.INHERITED_INVISIBLE
    assert stage.compute_visibility(hidden_child) is VisibilityState.INVISIBLE
    assert stage.compute_visibility(visible) is VisibilityState.VISIBLE

    # The common subtree contract mirrors a default-purpose BBoxCache: a
    # selected hidden root still has a bound, while hidden descendants and
    # non-default-purpose descendants are excluded from a selected ancestor.
    _assert_bounds_close(
        stage.compute_world_aabb(["/World/HiddenParent"]),
        ((80.0, -20.0, -20.0), (120.0, 20.0, 20.0)),
    )
    _assert_bounds_close(
        stage.compute_world_aabb(["/World"]),
        ((-1.433941121354883, -3.1737886028227518, -1.0),
         (11.0, 10.0, 11.0)),
    )
    assert stage.compute_world_aabb(["/World/ProxyChild"]) is None


def test_public_population_stage_info_drives_up_axis_and_bound_camera(
    opened_scene: tuple[Any, Any, Any, Any],
) -> None:
    _session, _scene, stage, _transform = opened_scene
    assert stage.read_stage_up_axis() == "Z"
    pose = stage.read_bound_camera()
    assert pose is not None
    assert pose.up_axis == "Z"


def test_spatial_tokens_are_copied_once_per_native_ordinal(
    opened_scene: tuple[Any, Any, Any, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ovui_data_adapters.ovstage import stage_adapter as stage_adapter_module

    _session, scene, stage, _transform = opened_scene
    calls: list[tuple[str, str]] = []
    native_read = stage_adapter_module.read_token_attribute

    def counted_read(native_stage: Any, path: str, name: str) -> Any:
        calls.append((path, name))
        return native_read(native_stage, path, name)

    monkeypatch.setattr(stage_adapter_module, "read_token_attribute", counted_read)
    first_bounds = stage.compute_world_aabb(["/World"])
    first_call_count = len(calls)
    assert first_bounds is not None
    assert first_call_count > 0
    # The api-v2 compatibility cache owns snapshot handles. Its size is the
    # only available leak counter; pair this private ownership assertion with
    # the repeated public bound and visibility reads below.
    native_cache = scene._stage._ovui_kit_stage_bridge_cache
    handle_count = len(native_cache._handles)

    for _index in range(20):
        assert stage.compute_world_aabb(["/World"]) == first_bounds
        item = stage.get_item_at_path("/World/HiddenParent/InheritedChild")
        assert stage.compute_visibility(item) is VisibilityState.INHERITED_INVISIBLE
    assert len(calls) == first_call_count
    assert len(native_cache._handles) == handle_count


class _FakeScene:
    def __init__(self, stage: Any) -> None:
        self._stage = stage
        self.is_open = True

    @property
    def hierarchy(self) -> Any:
        raise ImportError("no hierarchy in the public api-v2 runtime")


class _MatrixStage:
    current_ordinal = 7

    def __init__(self) -> None:
        translated = [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            4.0, 5.0, 6.0, 1.0,
        ]
        self.values = {
            ("/Valid", "localMatrix"): struct.pack("<16d", *translated),
            ("/Valid", "worldMatrix"): struct.pack("<16d", *translated),
            ("/WrongSemantic", "localMatrix"): struct.pack("<16d", *translated),
            ("/WrongSemantic", "worldMatrix"): struct.pack("<16d", *translated),
            ("/NonFinite", "localMatrix"): struct.pack(
                "<16d", *([1.0] * 15 + [math.nan])
            ),
            ("/NonFinite", "worldMatrix"): struct.pack(
                "<16d", *([1.0] * 15 + [math.nan])
            ),
        }

    def get_parent_path(self, path: str) -> str:
        if path not in {"/Valid", "/WrongSemantic", "/NonFinite"}:
            raise KeyError(path)
        return ""

    def read_attribute(self, _ordinal: int, paths: list[str], name: str) -> bytes:
        return self.values[(paths[0], name)]

    def read_attribute_info(self, _ordinal: int, path: str, _name: str) -> dict[str, Any]:
        semantic = 0 if path == "/WrongSemantic" else 10
        return {"dtype": (2, 64, 16), "semantic": semantic, "is_array": False}


def test_transform_reads_reject_noncanonical_paths_and_malformed_native_layouts() -> None:
    transform = create_transform_adapter(_FakeScene(_MatrixStage()))
    identity = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    assert transform.get_local_transform("/Valid")[3][:3] == [4.0, 5.0, 6.0]
    for invalid in (" /Valid", "/Valid ", "Valid", "/Valid/", "/A//B", "/A/../B"):
        assert transform.get_local_transform(invalid) == identity
    assert transform.get_local_transform("/WrongSemantic") == identity
    assert transform.get_local_transform("/NonFinite") == identity


class _LifecycleHandle:
    def __init__(
        self,
        events: list[str],
        label: str,
        *,
        fail_wait: bool = False,
    ) -> None:
        self._events = events
        self._label = label
        self._fail_wait = fail_wait

    def __enter__(self) -> "_LifecycleHandle":
        self._events.append(f"{self._label}.enter")
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._events.append(f"{self._label}.release")
        self._events.append(f"{self._label}.release.wait")

    def wait(self) -> None:
        self._events.append(f"{self._label}.wait")
        if self._fail_wait:
            raise RuntimeError(f"{self._label} failed")


class _LifecycleQuery(_LifecycleHandle):
    pass


class _LifecycleRead(_LifecycleHandle):
    def __init__(self, events: list[str], group: Any, *, fail_wait: bool = False) -> None:
        super().__init__(events, "read", fail_wait=fail_wait)
        self._group = group

    def groups(self) -> Iterator[Any]:
        self._events.append("read.groups")
        yield self._group


class _LifecycleDictionary:
    def __init__(self, stage: Any) -> None:
        self._stage = stage

    def __enter__(self) -> "_LifecycleDictionary":
        self._stage.events.append("dictionary.enter")
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._stage.events.append("dictionary.exit")

    def intern_token(self, value: str) -> int:
        self._stage.events.append(f"dictionary.intern:{value}")
        return 41

    def get_path_strings(self, _handle: int) -> list[str]:
        self._stage.events.append("dictionary.paths.copy")
        return ["/__ovstage_population_stage_info__"]

    def token_to_string(self, token: int) -> str:
        self._stage.events.append(f"dictionary.token.copy:{token}")
        return "Z"


class _LifecycleOrdinalRange:
    @staticmethod
    def latest(ordinal: int) -> tuple[str, int]:
        return ("latest", int(ordinal))


class _LifecycleStage:
    current_ordinal = 3

    def __init__(self) -> None:
        self.events: list[str] = []
        self.fail_read_wait = False
        dtype = SimpleNamespace(code=1, bits=64, lanes=1)
        tensor = SimpleNamespace(dtype=dtype)
        self.group = SimpleNamespace(
            attribute=41,
            prim_list=17,
            prim_count=1,
            data_count=1,
            tensor_count=1,
            is_array=False,
            raw=SimpleNamespace(semantic=0),
            tensor=lambda _index: tensor,
            array=lambda _index: SimpleNamespace(
                reshape=lambda *_shape: SimpleNamespace(tolist=lambda: [99])
            ),
            prim_index=lambda _index: 0,
            data_row_index=lambda _index: 0,
        )

    def query(self, _filter: Any, attrs: list[int]) -> _LifecycleQuery:
        assert attrs == [41]
        self.events.append("stage.query")
        return _LifecycleQuery(self.events, "query")

    def read_attributes(
        self,
        _query: Any,
        attrs: list[int],
        ordinal_range: Any,
    ) -> _LifecycleRead:
        assert attrs == [41]
        assert ordinal_range == ("latest", 3)
        self.events.append("stage.read")
        return _LifecycleRead(
            self.events,
            self.group,
            fail_wait=self.fail_read_wait,
        )

    def release_group(self, group: Any) -> None:
        assert group is self.group
        self.events.append("group.release")


def test_up_axis_native_query_wait_copy_release_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from ovui_data_adapters.ovstage import _native

    stage = _LifecycleStage()
    runtime = SimpleNamespace(
        PathDictionary=_LifecycleDictionary,
        OrdinalRange=_LifecycleOrdinalRange,
    )
    monkeypatch.setattr(_native, "import_module", lambda name: runtime)
    adapter = create_stage_adapter(_FakeScene(stage))

    assert adapter.read_stage_up_axis() == "Z"
    assert adapter.read_stage_up_axis() == "Z"
    assert stage.events == [
        "dictionary.enter",
        "dictionary.intern:upAxis",
        "stage.query",
        "query.enter",
        "query.wait",
        "stage.read",
        "read.enter",
        "read.wait",
        "read.groups",
        "dictionary.paths.copy",
        "dictionary.token.copy:99",
        "group.release",
        "read.release",
        "read.release.wait",
        "query.release",
        "query.release.wait",
        "dictionary.exit",
    ]


def test_up_axis_malformed_group_is_released_before_truthful_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ovui_data_adapters.ovstage import _native

    stage = _LifecycleStage()
    wrong_dtype = SimpleNamespace(code=2, bits=64, lanes=1)
    stage.group.tensor = lambda _index: SimpleNamespace(dtype=wrong_dtype)
    runtime = SimpleNamespace(
        PathDictionary=_LifecycleDictionary,
        OrdinalRange=_LifecycleOrdinalRange,
    )
    monkeypatch.setattr(_native, "import_module", lambda name: runtime)

    assert create_stage_adapter(_FakeScene(stage)).read_stage_up_axis() == "Y"
    assert "group.release" in stage.events
    assert stage.events[-5:] == [
        "read.release",
        "read.release.wait",
        "query.release",
        "query.release.wait",
        "dictionary.exit",
    ]


def test_up_axis_read_failure_releases_reserved_handles_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ovui_data_adapters.ovstage import _native

    stage = _LifecycleStage()
    stage.fail_read_wait = True
    runtime = SimpleNamespace(
        PathDictionary=_LifecycleDictionary,
        OrdinalRange=_LifecycleOrdinalRange,
    )
    monkeypatch.setattr(_native, "import_module", lambda name: runtime)

    assert create_stage_adapter(_FakeScene(stage)).read_stage_up_axis() == "Y"
    assert "read.groups" not in stage.events
    assert stage.events[-5:] == [
        "read.release",
        "read.release.wait",
        "query.release",
        "query.release.wait",
        "dictionary.exit",
    ]

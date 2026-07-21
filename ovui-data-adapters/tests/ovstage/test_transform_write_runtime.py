# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Runtime-agnostic routing tests for ``OvstageTransformAdapter`` local writes.

These exercise the selection between the legacy ``ovhierarchy`` write path and
the Kit-integrated ``Stage.write_attribute`` copy-in path without requiring
either native runtime, by driving fake stage/scene objects.
"""
from __future__ import annotations

import struct
from typing import Any, List

from ovui_data_adapters.ovstage import transform_adapter as ta
from ovui_data_adapters.ovstage.transform_adapter import OvstageTransformAdapter

_CUBE = "/World/Hierarchy/GroupA/BoxA"
_IDENTITY_FLAT = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]
_TRANSLATE = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [2.0, 3.0, 4.0, 1.0],
]


class _BaseFakeStage:
    """Minimal stage with the surface the transform adapter reads."""

    def __init__(self) -> None:
        self.current_ordinal = 1

    def get_parent_path(self, path: str) -> str:
        value = str(path).rstrip("/")
        if value in ("", "/"):
            raise KeyError(path)
        return value.rsplit("/", 1)[0] or ""

    def read_attribute(self, ordinal: int, paths: List[str], attr_name: str) -> bytes:
        if attr_name in ("localMatrix", "worldMatrix"):
            return struct.pack("<16d", *_IDENTITY_FLAT)
        return b""


class _KitFakeStage(_BaseFakeStage):
    """Exposes the Kit copy-in write surface (write_attribute + path-list query)."""

    def __init__(self) -> None:
        super().__init__()
        self.frames: list[int] = []

    def begin_frame(self) -> int:
        return int(self.current_ordinal) + 1

    def end_frame(self, ordinal: int) -> None:
        self.frames.append(int(ordinal))
        self.current_ordinal = int(ordinal)

    def query_from_path_list(self, path_list: Any) -> Any:  # pragma: no cover - unused (write is patched)
        raise AssertionError("write should be routed through kit_write_local_matrix")

    def write_attribute(self, *a: Any, **k: Any) -> Any:  # pragma: no cover - unused
        raise AssertionError("write should be routed through kit_write_local_matrix")


class _LegacyFakeStage(_BaseFakeStage):
    """No Kit write surface; writes go through ovhierarchy + begin/end frame."""

    def __init__(self) -> None:
        super().__init__()
        self.begun: list[int] = []
        self.ended: list[int] = []

    def begin_frame(self) -> int:
        ordinal = int(self.current_ordinal) + 1
        self.begun.append(ordinal)
        return ordinal

    def end_frame(self, ordinal: int) -> None:
        self.ended.append(int(ordinal))
        self.current_ordinal = int(ordinal)


class _FakeHierarchy:
    def __init__(self) -> None:
        self.local_writes: list[tuple[int, str, list[float]]] = []
        self.world_updates: list[int] = []

    def set_local_xform(self, ordinal: int, path: str, flat: list[float]) -> None:
        self.local_writes.append((int(ordinal), str(path), list(flat)))

    def update_world_xforms(self, ordinal: int) -> None:
        self.world_updates.append(int(ordinal))


class _FakeScene:
    def __init__(self, stage: Any, hierarchy: Any | None) -> None:
        self._stage = stage
        self.is_open = True
        self._hierarchy = hierarchy
        self.physics_controls = None

    @property
    def hierarchy(self) -> Any:
        if self._hierarchy is None:
            raise RuntimeError("ovhierarchy transform runtime is unavailable")
        return self._hierarchy


def test_kit_stage_routes_local_write_through_copy_in(monkeypatch) -> None:
    stage = _KitFakeStage()
    adapter = OvstageTransformAdapter(_FakeScene(stage, hierarchy=None))

    calls: list[tuple[Any, str, list[float]]] = []

    def _fake_kit_write(stage_arg: Any, path: str, flat: list[float]) -> None:
        calls.append((stage_arg, path, list(flat)))

    monkeypatch.setattr(ta, "kit_write_local_matrix", _fake_kit_write)

    assert adapter.can_transform(_CUBE) is True
    adapter.set_local_transform(_CUBE, _TRANSLATE)

    assert len(calls) == 1
    stage_arg, path, flat = calls[0]
    assert stage_arg is stage
    assert path == _CUBE
    # Row-major flatten: translation lands in flat indices 12/13/14.
    assert flat[12:15] == [2.0, 3.0, 4.0]


def test_legacy_hierarchy_path_is_preserved() -> None:
    stage = _LegacyFakeStage()
    hierarchy = _FakeHierarchy()
    adapter = OvstageTransformAdapter(_FakeScene(stage, hierarchy=hierarchy))

    assert adapter.can_transform(_CUBE) is True
    adapter.set_local_transform(_CUBE, _TRANSLATE)

    assert len(hierarchy.local_writes) == 1
    ordinal, path, flat = hierarchy.local_writes[0]
    assert path == _CUBE
    assert flat[12:15] == [2.0, 3.0, 4.0]
    assert hierarchy.world_updates == [ordinal]
    assert stage.begun == [ordinal] and stage.ended == [ordinal]


def test_no_write_runtime_blocks_edit_policy() -> None:
    stage = _BaseFakeStage()  # no begin/end_frame, no write surface, no hierarchy
    adapter = OvstageTransformAdapter(_FakeScene(stage, hierarchy=None))

    assert adapter.can_transform(_CUBE) is False


# ── kit_write_local_matrix native-handle cleanup ──────────────────────────────


class _FakeQuery:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def release(self) -> None:
        self._events.append("query.release")


class _FakePathDictionary:
    def __init__(self, stage: Any, events: list[str]) -> None:
        self._events = events
        self.created: list[int] = []
        self.destroyed: list[int] = []
        self._next = 100

    def __enter__(self) -> "_FakePathDictionary":
        return self

    def __exit__(self, *exc: Any) -> None:
        self._events.append("pathdict.exit")

    def create_path_list_from_strings(self, paths: list[str]) -> int:
        handle = self._next
        self._next += 1
        self.created.append(handle)
        self._events.append(f"create_path_list:{handle}")
        return handle

    def destroy_path_list(self, path_list: int) -> None:
        self.destroyed.append(int(path_list))
        self._events.append(f"destroy_path_list:{path_list}")


class _KitWriteFakeStage:
    def __init__(self, events: list[str], *, fail_write: bool = False) -> None:
        self._events = events
        self._fail_write = fail_write
        self.current_ordinal = 1
        self.ended: list[int] = []
        self.is_array_flags: list[bool] = []

    def begin_frame(self) -> int:
        return int(self.current_ordinal) + 1

    def end_frame(self, ordinal: int) -> None:
        self.ended.append(int(ordinal))
        self.current_ordinal = int(ordinal)
        self._events.append(f"end_frame:{ordinal}")

    def query_from_path_list(self, path_list: int) -> _FakeQuery:
        self._events.append(f"query_from_path_list:{path_list}")
        return _FakeQuery(self._events)

    def write_attribute(
        self,
        query: Any,
        attr: str,
        ordinal: int,
        tensors: Any,
        *,
        is_array: bool,
        semantic: int = 0,
    ) -> Any:
        self.is_array_flags.append(bool(is_array))
        self._events.append(f"write_attribute:{attr}:{ordinal}")
        if self._fail_write:
            raise RuntimeError("simulated write failure")

        class _Op:
            def wait(_self) -> None:
                return None

        return _Op()


def _install_fake_ovstage(monkeypatch, pd_holder: list) -> list[str]:
    """Patch ``_scene.import_module('ovstage')`` to return a fake module so the
    native cleanup contract can be exercised without the Kit runtime. Returns
    the shared event log."""
    from importlib import import_module as _real_import_module

    from ovui_data_adapters.ovstage import _scene, _stage_write

    events: list[str] = []

    def _make_pd(stage: Any) -> _FakePathDictionary:
        pd = _FakePathDictionary(stage, events)
        pd_holder.append(pd)
        return pd

    class _DT:
        def __init__(self, *, code: Any, bits: int, lanes: int) -> None:
            self.code, self.bits, self.lanes = code, bits, lanes

    fake_module = type(
        "_FakeOvstage",
        (),
        {
            "PathDictionary": staticmethod(_make_pd),
            "make_dltensor": staticmethod(lambda flat, **k: ("tensor", k)),
            "numpy_to_dldatatype": staticmethod(
                lambda dtype, *, lanes=1: (str(dtype), int(lanes))
            ),
            "AttributeSemantic": type("_Semantic", (), {"MATRIX": 7}),
            "DLDataType": _DT,
            "DLDataTypeCode": type("_C", (), {"kDLFloat": 2}),
        },
    )

    monkeypatch.setattr(
        _scene,
        "import_module",
        lambda name: fake_module if name == "ovstage" else _real_import_module(name),
    )
    monkeypatch.setattr(
        _stage_write,
        "import_module",
        lambda name: fake_module if name == "ovstage" else _real_import_module(name),
    )
    return events


_FLAT16 = [float(i) for i in range(16)]


def test_kit_write_local_matrix_destroys_path_list(monkeypatch) -> None:
    from ovui_data_adapters.ovstage._scene import kit_write_local_matrix
    from ovui_data_adapters.ovstage._stage_write import recorded_stage_writes

    holder: list = []
    events = _install_fake_ovstage(monkeypatch, holder)
    stage = _KitWriteFakeStage(events)

    kit_write_local_matrix(stage, _CUBE, _FLAT16)

    pd = holder[0]
    assert stage.is_array_flags == [False]
    assert pd.created and pd.destroyed == pd.created
    # Path list is destroyed after the query is released and before end_frame.
    assert events.index("query.release") < events.index(f"destroy_path_list:{pd.created[0]}")
    assert events.index(f"destroy_path_list:{pd.created[0]}") < events.index("end_frame:2")
    assert recorded_stage_writes(
        stage,
        since_ordinal=1,
        current_ordinal=2,
    ) == {"omni:xform": {_CUBE}}


def test_kit_write_local_matrix_destroys_path_list_on_write_failure(monkeypatch) -> None:
    from ovui_data_adapters.ovstage._scene import kit_write_local_matrix

    holder: list = []
    _install_fake_ovstage(monkeypatch, holder)
    stage = _KitWriteFakeStage([], fail_write=True)

    try:
        kit_write_local_matrix(stage, _CUBE, _FLAT16)
    except RuntimeError:
        pass

    pd = holder[0]
    # Even when the write raises, the path list is still destroyed and the frame
    # is closed.
    assert pd.destroyed == pd.created
    assert stage.ended == [2]

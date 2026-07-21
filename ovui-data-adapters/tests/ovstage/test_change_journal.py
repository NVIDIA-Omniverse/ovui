# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this software, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Runtime-free regressions for native OVStage write-journal delivery."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
from ovui_data_adapters.common import ChangeEventType
from ovui_data_adapters.ovstage import _stage_write, change_stream
from ovui_data_adapters.ovstage._stage_write import (
    StageWriteBatch,
    recorded_stage_writes,
)
from ovui_data_adapters.ovstage.change_stream import OvstageChangeStream


class _Query:
    def __init__(self, attributes: tuple[int, ...] = ()) -> None:
        self._attributes = attributes

    def result(self) -> Any:
        return SimpleNamespace(attributes=self._attributes)

    def release(self) -> None:
        return None


class _ReadGroup:
    def __init__(self, attribute: int, paths: tuple[str, ...]) -> None:
        self.attribute = int(attribute)
        self.prim_list = paths
        self.prim_count = len(paths)

    @staticmethod
    def prim_index(local_index: int) -> int:
        return int(local_index)


class _Read:
    def __init__(self, groups: tuple[_ReadGroup, ...]) -> None:
        self._groups = list(groups)

    def fetch_next(self) -> _ReadGroup | None:
        return self._groups.pop(0) if self._groups else None

    def release(self) -> None:
        return None


class _PathDictionary:
    def __init__(self, stage: "_NativeStage") -> None:
        self._stage = stage

    def create_path_list_from_strings(self, paths: Any) -> tuple[str, ...]:
        return tuple(str(path) for path in paths)

    def destroy_path_list(self, path_list: Any) -> None:
        return None

    def intern_token(self, value: str) -> int:
        return self._stage.intern_token(value)

    def token_to_string(self, value: int) -> str:
        return self._stage.token_to_string(value)

    @staticmethod
    def get_path_strings(prim_list: Any) -> tuple[str, ...]:
        return tuple(str(path) for path in prim_list)

    def destroy(self) -> None:
        return None


class _NativeStage:
    def __init__(self) -> None:
        self.current_ordinal = 0
        self._tokens: dict[str, int] = {}
        self._token_names: dict[int, str] = {}
        self._read_paths = (
            "/World/Cube",
            "/_OvuiRuntime/Render/Viewport",
        )

    def intern_token(self, value: str) -> int:
        name = str(value)
        token = self._tokens.get(name)
        if token is None:
            token = len(self._tokens) + 1
            self._tokens[name] = token
            self._token_names[token] = name
        return token

    def token_to_string(self, value: int) -> str:
        return self._token_names[int(value)]

    def begin_frame(self) -> int:
        return self.current_ordinal + 1

    def end_frame(self, ordinal: int) -> None:
        self.current_ordinal = int(ordinal)

    def query_from_path_list(self, path_list: Any) -> _Query:
        return _Query()

    def write_attribute(self, *args: Any, **kwargs: Any) -> None:
        return None

    def query_prims(self, ordinal: int) -> dict[str, tuple[Any, ...]]:
        return {"groups": ()}

    def query(self, *, filter: Any = None) -> _Query:
        return _Query((self.intern_token("focalLength"),))

    def read_attributes(self, query: Any, attributes: Any, ordinal_range: Any) -> _Read:
        return _Read(
            (
                _ReadGroup(
                    self.intern_token("focalLength"),
                    self._read_paths,
                ),
            )
        )

    def fetch_read_next(self, read: Any) -> None:
        return None

    def get_attribute_write_floor(self, attribute: Any) -> int:
        return 0

    def release_group(self, group: Any) -> None:
        return None


class _Scene:
    initial_ordinal = 0

    def __init__(
        self,
        stage: _NativeStage,
        presentation_root_paths: tuple[str, ...] = ("/_OvuiRuntime",),
    ) -> None:
        self._stage = stage
        self.presentation_root_paths = presentation_root_paths

    @property
    def current_ordinal(self) -> int:
        return self._stage.current_ordinal


def _fake_ovstage_module(stage: _NativeStage) -> Any:
    return SimpleNamespace(
        PathDictionary=lambda _stage: _PathDictionary(stage),
        OrdinalRange=SimpleNamespace(
            between=lambda first, last: (int(first), int(last))
        ),
        make_dltensor=lambda array, **kwargs: (array, kwargs),
        numpy_to_dldatatype=lambda dtype, *, lanes=1: (str(dtype), int(lanes)),
    )


def test_user_change_filter_preserves_source_collision_and_hides_dynamic_root() -> None:
    scene = SimpleNamespace(
        presentation_root_paths=("/_OvuiRuntime_2",),
    )

    assert change_stream._is_user_change_path(
        "/_OvuiRuntime/UserData",
        scene=scene,
    )
    assert not change_stream._is_user_change_path(
        "/_OvuiRuntime_2/Render/Viewport",
        scene=scene,
    )


def test_private_journal_rows_never_reach_events_and_public_rows_are_deduped(
    monkeypatch,
) -> None:
    stage = _NativeStage()
    module = _fake_ovstage_module(stage)
    monkeypatch.setattr(_stage_write, "import_module", lambda _name: module)
    monkeypatch.setattr(change_stream, "import_module", lambda _name: module)
    stream = OvstageChangeStream(_Scene(stage))

    with StageWriteBatch(
        stage,
        ["/_OvuiRuntime/Render/Viewport", "/World/Cube"],
    ) as batch:
        batch.write_fixed(
            "focalLength",
            np.asarray([18.0, 24.0], dtype=np.float32),
        )

    # The journal records native writes verbatim. Its evidence is filtered at
    # the ChangeEvent boundary, where it is merged with native dirty reads.
    assert recorded_stage_writes(
        stage,
        since_ordinal=0,
        current_ordinal=1,
    ) == {
        "focalLength": {
            "/_OvuiRuntime/Render/Viewport",
            "/World/Cube",
        }
    }

    events = stream.poll()

    assert len(events) == 1
    assert events[0].event_type is ChangeEventType.INFO_CHANGE
    assert events[0].source == "ovstage:attribute"
    # /World/Cube occurs in both the journal and native read group, but emits
    # once. The provider-private row occurs in both and never emits.
    assert events[0].changed_paths == ("/World/Cube",)
    assert getattr(stage, "_ovui_native_write_journal") == {}
    assert stream.poll() == ()

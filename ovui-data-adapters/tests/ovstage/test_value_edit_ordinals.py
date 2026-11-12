# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A value edit of OVUI is not a structure change, and it names the prims it changed (#501)."""

from __future__ import annotations

from ovui_data_adapters.ovstage import _scene
from ovui_data_adapters.ovstage._scene import (
    _kit_stage_cache,
    _topology_version,
    note_camera_ordinal,
    note_value_edit_ordinal,
    value_edit_paths,
)


class _Stage:
    """The write floor is ``current_ordinal`` when the stage has no floor query."""

    def __init__(self, ordinal: int = 5) -> None:
        self.current_ordinal = ordinal

    def get_topology_version(self) -> int:
        return _topology_version(self)

    def write(self) -> int:
        self.current_ordinal += 1
        return self.current_ordinal


def test_a_value_edit_keeps_the_topology_version():
    """Defect: each hide or gizmo edit read the type of every prim again."""
    stage = _Stage()
    assert stage.get_topology_version() == 5
    note_value_edit_ordinal(stage, stage.write(), "visibility", ["/World/A"])
    note_value_edit_ordinal(stage, stage.write(), "omni:xform", ["/World/B"])
    assert stage.get_topology_version() == 5
    stage.write()
    assert stage.get_topology_version() == 8


def test_a_write_of_a_structure_column_moves_the_topology_version():
    stage = _Stage()
    assert stage.get_topology_version() == 5
    note_value_edit_ordinal(stage, stage.write(), "usd-schemas", ["/World/A"])
    assert stage.get_topology_version() == 6
    assert value_edit_paths(stage, 5, 6, ("visibility",)) is None


def test_value_edit_paths_names_only_the_recorded_writes():
    stage = _Stage()
    tokens = ("visibility", "purpose")
    assert stage.get_topology_version() == 5
    note_value_edit_ordinal(stage, stage.write(), "visibility", ["/World/A"])
    note_value_edit_ordinal(stage, stage.write(), "omni:xform", ["/World/B"])
    note_camera_ordinal(stage, stage.write(), ("/Camera",))
    assert value_edit_paths(stage, 5, 5, tokens) == frozenset()
    assert value_edit_paths(stage, 5, 8, tokens) == {"/World/A", "/Camera"}
    assert value_edit_paths(stage, 6, 8, tokens) == {"/Camera"}
    # A camera write that does not name its camera cannot name what it changed.
    note_camera_ordinal(stage, stage.write())
    assert value_edit_paths(stage, 8, 9, tokens) is None
    # Another writer's ordinal.
    stage.write()
    assert value_edit_paths(stage, 9, 10, tokens) is None
    assert value_edit_paths(stage, 7, 5, tokens) is None
    # A column that the write log does not keep.
    assert value_edit_paths(stage, 10, 10, ("omni:xform",)) is None


def test_the_whole_scene_values_are_read_again_after_a_value_edit(monkeypatch):
    stage = _Stage()
    builds: list[int] = []

    def build(_stage, ordinal, prim_paths=None):
        builds.append(int(ordinal))
        return _scene._KitStageBridgeCache(
            ordinal=ordinal, path_order=("/World",), attrs={}, types={}
        )

    monkeypatch.setattr(_scene, "_build_kit_stage_cache", build)
    assert stage.get_topology_version() == 5
    _kit_stage_cache(stage, 5)
    # A camera write keeps the cache, as before.
    note_camera_ordinal(stage, stage.write(), ("/Camera",))
    _kit_stage_cache(stage, 6)
    # The cache holds values: a value edit makes it stale.
    note_value_edit_ordinal(stage, stage.write(), "visibility", ["/World"])
    _kit_stage_cache(stage, 7)
    assert builds == [5, 7]

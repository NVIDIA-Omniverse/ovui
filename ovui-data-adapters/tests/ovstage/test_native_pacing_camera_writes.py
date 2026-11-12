# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A camera write is not a structure change for the stage tree's cache key."""

from __future__ import annotations

from ovui_data_adapters.ovstage._scene import (
    _same_structure,
    _topology_version,
    begin_native_camera_writes,
    end_native_camera_writes,
    note_camera_ordinal,
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


def test_an_ordinary_write_moves_the_version():
    stage = _Stage()
    assert stage.get_topology_version() == 5
    stage.write()
    assert stage.get_topology_version() == 6


def test_a_python_camera_write_keeps_the_version():
    stage = _Stage()
    assert stage.get_topology_version() == 5
    note_camera_ordinal(stage, stage.write())
    note_camera_ordinal(stage, stage.write())
    assert stage.get_topology_version() == 5
    stage.write()
    assert stage.get_topology_version() == 8


def test_the_camera_writes_of_a_native_session_keep_the_version():
    stage = _Stage()
    assert stage.get_topology_version() == 5
    begin_native_camera_writes(stage, 5)
    stage.write()
    stage.write()
    # Read while the session writes, and after it stopped.
    assert stage.get_topology_version() == 5
    stage.write()
    end_native_camera_writes(stage)
    assert stage.get_topology_version() == 5
    # Python writes after the session stopped are structure changes again.
    stage.write()
    assert stage.get_topology_version() == 9


def test_a_write_before_the_session_started_still_moves_the_version():
    stage = _Stage()
    assert stage.get_topology_version() == 5
    stage.write()
    begin_native_camera_writes(stage, 6)
    stage.write()
    end_native_camera_writes(stage)
    assert stage.get_topology_version() == 6


def test_a_structure_reading_holds_across_camera_writes_only():
    stage = _Stage()
    assert stage.get_topology_version() == 5
    note_camera_ordinal(stage, 6)
    stage.write()
    begin_native_camera_writes(stage, 6)
    stage.write()
    assert _same_structure(stage, 5, 7)
    end_native_camera_writes(stage)
    stage.write()
    assert _same_structure(stage, 7, 7)
    assert not _same_structure(stage, 5, 8)
    assert not _same_structure(stage, 8, 5)


class _Stream:
    def __init__(self, last_ordinal: int) -> None:
        self.last_ordinal = last_ordinal


class _Scene:
    def __init__(self, stream: _Stream | None) -> None:
        self._change_stream = stream


def _adapter(stage: _Stage, stream: _Stream | None):
    from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter

    adapter = object.__new__(OvstageRendererAdapter)
    adapter._attached_stage = stage
    adapter._scene = _Scene(stream)
    adapter._successful_frame_count = 1
    adapter._native_pacing_after_ordinal = 0
    return adapter


def test_a_new_scene_starts_native_pacing_the_frame_after_its_changes_are_delivered():
    stage = _Stage(5)
    stream = _Stream(3)
    adapter = _adapter(stage, stream)
    # The stage browser has not seen the attach's ordinals: render synchronously.
    assert not adapter._scene_open_changes_delivered()
    assert not adapter._scene_open_changes_delivered()
    stream.last_ordinal = 5
    # Delivered in this frame: a listener may still run in it.
    assert not adapter._scene_open_changes_delivered()
    assert adapter._scene_open_changes_delivered()
    assert adapter._scene_open_changes_delivered()


def test_without_a_polling_change_stream_native_pacing_starts_after_a_bounded_wait():
    from ovui_data_adapters.ovstage import renderer_adapter

    adapter = _adapter(_Stage(5), None)
    assert not adapter._scene_open_changes_delivered()
    adapter._successful_frame_count = renderer_adapter._SCENE_OPEN_SYNCHRONOUS_FRAMES
    assert adapter._scene_open_changes_delivered()


class _PacingStatus:
    def __init__(self) -> None:
        self.presented = 0

    def _get_native_frame_pacing_status(self):
        return {"presented_renderer_frames": self.presented}


def test_the_first_session_of_a_scene_restarts_its_frame_timing_once():
    from ovui_data_adapters.ovstage import renderer_adapter

    adapter = _adapter(_Stage(5), _Stream(5))
    paused = []
    adapter._stop_native_frame_pacing_locked = lambda reason, **kw: paused.append((reason, kw))
    adapter._native_pacing_after_ordinal = -1
    assert adapter._scene_open_changes_delivered()
    native = _PacingStatus()
    native.presented = renderer_adapter._SCENE_OPEN_SETTLE_FRAMES - 1
    adapter._settle_scene_open_frame_timing(native)
    assert paused == []
    native.presented = renderer_adapter._SCENE_OPEN_SETTLE_FRAMES
    adapter._settle_scene_open_frame_timing(native)
    adapter._settle_scene_open_frame_timing(native)
    assert paused == [("scene open frame timing", {"capture_selected_camera": False, "pause_render": True})]


class _FloorQuery:
    def __init__(self, value: int) -> None:
        self._value = value

    def wait(self) -> None:
        return None

    def fetch(self) -> int:
        return self._value

    def release(self) -> None:
        return None


def test_rows_read_together_share_one_write_floor_read():
    import time

    stage = _Stage(5)
    reads = []
    stage.native_floor = 5

    def get_attribute_write_floor():
        reads.append(stage.native_floor)
        return _FloorQuery(stage.native_floor)

    stage.get_attribute_write_floor = get_attribute_write_floor
    for _row in range(50):
        assert stage.get_topology_version() == 5
    assert len(reads) == 1
    # Python's own write shows at once: it raises current_ordinal.
    stage.write()
    assert stage.get_topology_version() == 6
    # Another writer's ordinal shows with the next read of the floor.
    stage.native_floor = 9
    time.sleep(0.01)
    assert stage.get_topology_version() == 9
    assert len(reads) == 2


def test_the_adapter_camera_write_keeps_the_topology_version(monkeypatch):
    """Defect: each camera move rebuilt the whole stage tree on the next selection."""
    from types import SimpleNamespace

    import numpy as np

    from ovui_data_adapters.ovstage import renderer_adapter

    stage = _Stage(5)
    assert stage.get_topology_version() == 5

    class _Batch:
        def __init__(self, target, paths):
            self.ordinal = None

        def __enter__(self):
            self.ordinal = stage.write()
            return self

        def __exit__(self, *_exc):
            return None

        def write_fixed(self, *_args, **_kwargs):
            return None

        def write_tokens(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(renderer_adapter, "StageWriteBatch", _Batch)
    monkeypatch.setattr(
        renderer_adapter,
        "import_module",
        lambda name: SimpleNamespace(AttributeSemantic=SimpleNamespace(MATRIX=0)),
    )
    adapter = _adapter(stage, _Stream(5))
    view = np.eye(4)
    projection = np.diag([1.0, 1.0, -1.0, 1.0])
    for step in range(3):
        view[3, 0] = float(step)
        adapter._push_runtime_camera_state_native_pacing("/Camera", view, projection, "_state")
    assert stage.current_ordinal == 8
    assert stage.get_topology_version() == 5
    # The camera writes changed only the camera: other cached values stay valid.
    assert value_edit_paths(stage, 5, 8, ("visibility",)) == {"/Camera"}


def test_the_selection_outline_is_written_during_a_pause(monkeypatch):
    """Defect: writing the outline stopped the session, so one frame rendered on the UI thread."""
    from ovui_data_adapters.ovstage import renderer_adapter
    from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter

    events = []

    class _Renderer:
        def set_selection_outline_group_strings(self, paths, group_id):
            events.append(("write", list(paths), group_id))

    adapter = object.__new__(OvstageRendererAdapter)
    adapter._renderer = _Renderer()
    adapter._attached_stage = object()
    adapter._native_render_is_paused = lambda: False
    adapter._profile_ovui_call = lambda name, function, *args, **kwargs: function(*args, **kwargs)
    adapter._stop_native_frame_pacing = lambda reason, **kwargs: events.append(("stop", reason, kwargs))
    monkeypatch.setattr(renderer_adapter, "_native_path_exists", lambda stage, path: True)

    applied = adapter._write_selection_outline_group(["/World/Cube"], 1)

    assert applied == {"/World/Cube"}
    assert events == [
        ("stop", "selection outline membership", {"pause_render": True}),
        ("write", ["/World/Cube"], 1),
    ]

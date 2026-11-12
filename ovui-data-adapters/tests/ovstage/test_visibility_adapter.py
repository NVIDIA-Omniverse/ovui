# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ovstage StageAdapter inherited and raw runtime visibility behavior."""

from __future__ import annotations

import pathlib
from typing import Any, Iterator

import pytest

from ovui_data_adapters.common import ChangeEvent, ChangeEventType, VisibilityState
from ovui_data_adapters.ovstage._native import read_token_attribute
from ovui_data_adapters.ovstage._scene import OvstageScene
from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    create_provider_session,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes
from ovui_data_adapters.ovstage.stage_adapter import OvstageStageAdapter


pytestmark = [
    pytest.mark.requires_ovstage,
]

_HIDDEN_PARENT = "/World/VisibilityCases/HiddenParent"
_INHERITED_HIDDEN_CHILD = f"{_HIDDEN_PARENT}/InheritedHiddenChild"
_VISIBLE_PARENT = "/World/VisibilityCases/VisibleParent"
_EXPLICIT_HIDDEN_CHILD = f"{_VISIBLE_PARENT}/ExplicitHiddenChild"
_INHERITED_VISIBLE_CHILD = f"{_VISIBLE_PARENT}/InheritedVisibleChild"


@pytest.fixture()
def ovstage_runtime():
    return load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )


@pytest.fixture()
def ovstage_scene(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_runtime: Any,
) -> Iterator[OvstageScene]:
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(ovstage_static_scene_path))
    try:
        yield scene
    finally:
        session.shutdown_scene()


@pytest.fixture()
def stage_adapter(ovstage_scene: OvstageScene) -> OvstageStageAdapter:
    return OvstageStageAdapter(ovstage_scene)


def test_parent_hidden_child_visible_reports_inherited_hidden(
    stage_adapter: OvstageStageAdapter,
    ovstage_scene: OvstageScene,
) -> None:
    parent = _require_item(stage_adapter, _HIDDEN_PARENT)
    child = _require_item(stage_adapter, _INHERITED_HIDDEN_CHILD)

    assert _raw_visibility(ovstage_scene._stage, _HIDDEN_PARENT) == "invisible"
    # Kit population publishes effective world visibility. It cannot recover
    # whether a hidden child authored ``inherited`` or ``invisible``.
    assert stage_adapter.compute_visibility(parent) is VisibilityState.INVISIBLE
    assert stage_adapter.compute_visibility(child) is VisibilityState.INHERITED_INVISIBLE
    assert stage_adapter.can_edit_visibility(parent) is True
    assert stage_adapter.can_edit_visibility(child) is True


def test_parent_visible_child_hidden_reports_explicit_hidden(
    stage_adapter: OvstageStageAdapter,
    ovstage_scene: OvstageScene,
) -> None:
    parent = _require_item(stage_adapter, _VISIBLE_PARENT)
    hidden_child = _require_item(stage_adapter, _EXPLICIT_HIDDEN_CHILD)
    visible_child = _require_item(stage_adapter, _INHERITED_VISIBLE_CHILD)

    assert _raw_visibility(ovstage_scene._stage, _VISIBLE_PARENT) == "inherited"
    assert _raw_visibility(ovstage_scene._stage, _EXPLICIT_HIDDEN_CHILD) == "invisible"
    assert _raw_visibility(ovstage_scene._stage, _INHERITED_VISIBLE_CHILD) == "inherited"
    assert stage_adapter.compute_visibility(parent) is VisibilityState.VISIBLE
    assert stage_adapter.compute_visibility(hidden_child) is VisibilityState.INVISIBLE
    assert stage_adapter.compute_visibility(visible_child) is VisibilityState.VISIBLE


def test_runtime_visibility_toggle_writes_raw_and_recomputes_inherited_children(
    stage_adapter: OvstageStageAdapter,
    ovstage_scene: OvstageScene,
) -> None:
    parent = _require_item(stage_adapter, _VISIBLE_PARENT)
    inherited_child = _require_item(stage_adapter, _INHERITED_VISIBLE_CHILD)
    events: list[ChangeEvent] = []
    subscription = stage_adapter.subscribe_changes(events.append)

    stage_adapter.set_visibility(parent, False)

    assert _raw_visibility(ovstage_scene._stage, _VISIBLE_PARENT) == "invisible"
    assert stage_adapter.compute_visibility(parent) is VisibilityState.INVISIBLE
    assert stage_adapter.compute_visibility(inherited_child) is VisibilityState.INHERITED_INVISIBLE
    assert len(events) == 1
    assert events[-1].event_type is ChangeEventType.INFO_CHANGE
    assert events[-1].source == "ovstage:visibility"
    assert events[-1].changed_paths == (_VISIBLE_PARENT,)
    assert ovstage_scene.change_stream.poll() == ()

    stage_adapter.set_visibility(parent, True)

    assert _raw_visibility(ovstage_scene._stage, _VISIBLE_PARENT) == "inherited"
    assert stage_adapter.compute_visibility(parent) is VisibilityState.VISIBLE
    assert stage_adapter.compute_visibility(inherited_child) is VisibilityState.VISIBLE
    assert len(events) == 2
    assert events[-1].source == "ovstage:visibility"
    assert events[-1].changed_paths == (_VISIBLE_PARENT,)
    subscription.cancel()


def test_a_hide_reads_again_only_the_edited_prim_and_descendants_without_own_value(
    stage_adapter: OvstageStageAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defect #501: each hide or unhide read the type and the visibility of every prim again.

    A hide does not change the own visibility value of a descendant, so the
    descendant keeps it and its eye shows the same state without a new read.
    """
    from ovui_data_adapters.ovstage import stage_adapter as stage_adapter_module

    parent = _require_item(stage_adapter, _VISIBLE_PARENT)
    inherited_child = _require_item(stage_adapter, _INHERITED_VISIBLE_CHILD)
    hidden_child = _require_item(stage_adapter, _EXPLICIT_HIDDEN_CHILD)
    other = _require_item(stage_adapter, _HIDDEN_PARENT)
    assert stage_adapter.compute_visibility(parent) is VisibilityState.VISIBLE
    assert stage_adapter.compute_visibility(inherited_child) is VisibilityState.VISIBLE
    assert stage_adapter.compute_visibility(hidden_child) is VisibilityState.INVISIBLE
    assert stage_adapter.compute_visibility(other) is VisibilityState.INVISIBLE

    type_reads: list[int] = []
    visibility_reads: list[str] = []
    read_types = stage_adapter_module._kit_type_records
    read_visibility = stage_adapter_module._read_visibility_value

    def counted_types(stage: Any, ordinal: int) -> Any:
        type_reads.append(ordinal)
        return read_types(stage, ordinal)

    def counted_visibility(stage: Any, path: str) -> Any:
        visibility_reads.append(path)
        return read_visibility(stage, path)

    monkeypatch.setattr(stage_adapter_module, "_kit_type_records", counted_types)
    monkeypatch.setattr(stage_adapter_module, "_read_visibility_value", counted_visibility)

    for visible, child_state in (
        (False, VisibilityState.INHERITED_INVISIBLE),
        (True, VisibilityState.VISIBLE),
    ):
        visibility_reads.clear()
        stage_adapter.set_visibility(parent, visible)

        assert stage_adapter.get_item_at_path(_VISIBLE_PARENT) is parent
        assert stage_adapter.compute_visibility(parent) is (
            VisibilityState.VISIBLE if visible else VisibilityState.INVISIBLE
        )
        assert stage_adapter.compute_visibility(inherited_child) is child_state
        assert stage_adapter.compute_visibility(hidden_child) is VisibilityState.INVISIBLE
        assert stage_adapter.compute_visibility(other) is VisibilityState.INVISIBLE
        assert _VISIBLE_PARENT in visibility_reads
        assert _INHERITED_VISIBLE_CHILD not in visibility_reads
        assert _EXPLICIT_HIDDEN_CHILD not in visibility_reads
        assert _HIDDEN_PARENT not in visibility_reads
    assert type_reads == []


def test_writes_of_another_writer_read_again_only_the_prims_that_they_hid(
    stage_adapter: OvstageStageAdapter,
    ovstage_scene: OvstageScene,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defect #501: each result write of a solver made the next hide read every prim again."""
    from ovui_data_adapters.ovstage import stage_adapter as stage_adapter_module

    parent = _require_item(stage_adapter, _VISIBLE_PARENT)
    inherited_child = _require_item(stage_adapter, _INHERITED_VISIBLE_CHILD)
    other = _require_item(stage_adapter, _HIDDEN_PARENT)
    assert stage_adapter.compute_visibility(parent) is VisibilityState.VISIBLE
    assert stage_adapter.compute_visibility(inherited_child) is VisibilityState.VISIBLE
    assert stage_adapter.compute_visibility(other) is VisibilityState.INVISIBLE

    type_reads: list[int] = []
    visibility_reads: list[str] = []
    read_types = stage_adapter_module._kit_type_records
    read_visibility = stage_adapter_module._read_visibility_value
    monkeypatch.setattr(
        stage_adapter_module,
        "_kit_type_records",
        lambda stage, ordinal: type_reads.append(ordinal) or read_types(stage, ordinal),
    )
    monkeypatch.setattr(
        stage_adapter_module,
        "_read_visibility_value",
        lambda stage, path: visibility_reads.append(path) or read_visibility(stage, path),
    )
    stage = ovstage_scene._stage
    # Another writer, through the native Stage only: results, then a hide. The
    # application polls the change stream at 30 Hz, faster than such a writer.
    for step in range(3):
        _native_write(stage, (_VISIBLE_PARENT, _HIDDEN_PARENT), "cae:solverStep", [step, step])
        ovstage_scene.change_stream.poll()
    _native_write(stage, (_VISIBLE_PARENT,), "visibility", ["invisible"])
    ovstage_scene.change_stream.poll()

    assert stage_adapter.compute_visibility(parent) is VisibilityState.INVISIBLE
    assert stage_adapter.compute_visibility(inherited_child) is VisibilityState.INHERITED_INVISIBLE
    assert stage_adapter.compute_visibility(other) is VisibilityState.INVISIBLE
    assert _VISIBLE_PARENT in visibility_reads
    assert _INHERITED_VISIBLE_CHILD not in visibility_reads
    assert _HIDDEN_PARENT not in visibility_reads
    assert type_reads == []

    # A burst of frames that the stage no longer keeps when the poll comes is
    # read again in full: the values stay right.
    for step in range(6):
        _native_write(stage, (_HIDDEN_PARENT,), "cae:solverStep", [step])
    _native_write(stage, (_VISIBLE_PARENT,), "visibility", ["inherited"])
    ovstage_scene.change_stream.poll()
    assert stage_adapter.compute_visibility(parent) is VisibilityState.VISIBLE
    assert stage_adapter.compute_visibility(inherited_child) is VisibilityState.VISIBLE
    assert stage_adapter.compute_visibility(other) is VisibilityState.INVISIBLE
    type_reads.clear()

    # A structure change of that writer still makes the adapter read the types
    # again, also a create and a delete that keep the prim count.
    created = f"{_VISIBLE_PARENT}/CreatedByOtherWriter"
    ordinal = stage.begin_frame()
    stage.create_prims(ordinal, [created], "Xform")
    stage.end_frame(ordinal)
    ordinal = stage.begin_frame()
    stage.delete_prims(ordinal, [_INHERITED_VISIBLE_CHILD])
    stage.end_frame(ordinal)
    ovstage_scene.change_stream.poll()

    assert stage_adapter.get_item_at_path(_INHERITED_VISIBLE_CHILD) is None
    assert stage_adapter.get_item_at_path(created) is not None
    assert type_reads


def test_outside_visibility_write_during_native_camera_session_refreshes_cached_values(
    stage_adapter: OvstageStageAdapter,
    ovstage_scene: OvstageScene,
) -> None:
    """A camera interval does not give its publisher exclusive native Stage access."""
    from ovui_data_adapters.ovstage._scene import (
        begin_native_camera_writes,
        end_native_camera_writes,
    )

    parent = _require_item(stage_adapter, _VISIBLE_PARENT)
    child = _require_item(stage_adapter, _INHERITED_VISIBLE_CHILD)
    properties = OvstagePropertyAdapter(ovstage_scene, [_VISIBLE_PARENT])
    assert stage_adapter.compute_visibility(parent) is VisibilityState.VISIBLE
    assert stage_adapter.compute_visibility(child) is VisibilityState.VISIBLE
    assert properties.get_value("visibility") == "inherited"
    events: list[ChangeEvent] = []
    subscription = stage_adapter.subscribe_changes(events.append)
    stage = ovstage_scene.native_stage
    begin_native_camera_writes(stage, ovstage_scene.current_ordinal)
    try:
        for token, parent_state, child_state in (
            ("invisible", VisibilityState.INVISIBLE, VisibilityState.INHERITED_INVISIBLE),
            ("inherited", VisibilityState.VISIBLE, VisibilityState.VISIBLE),
            ("invisible", VisibilityState.INVISIBLE, VisibilityState.INHERITED_INVISIBLE),
        ):
            events.clear()
            _native_write(stage, (_VISIBLE_PARENT,), "visibility", [token])
            ovstage_scene.change_stream.poll()

            assert events
            assert all(event.event_type is not ChangeEventType.RESYNC for event in events)
            assert stage_adapter.compute_visibility(parent) is parent_state
            assert stage_adapter.compute_visibility(child) is child_state
            assert properties.get_value("visibility") == token
    finally:
        end_native_camera_writes(stage)
        subscription.cancel()


def test_non_imageable_paths_cannot_edit_visibility(
    stage_adapter: OvstageStageAdapter,
    ovstage_scene: OvstageScene,
) -> None:
    path = "/World/VisibilityCases/NonImageableMaterial"
    stage = ovstage_scene._stage
    ordinal = stage.begin_frame()
    stage.create_prims(ordinal, [path], "Material")
    stage.end_frame(ordinal)

    item = _require_item(stage_adapter, path)

    assert stage_adapter.compute_visibility(item) is VisibilityState.VISIBLE
    assert stage_adapter.can_edit_visibility(item) is False
    with pytest.raises(NotImplementedError):
        stage_adapter.set_visibility(item, False)
    assert _raw_visibility(stage, path) == "inherited"


def test_stale_path_visibility_is_safe_and_not_editable(
    stage_adapter: OvstageStageAdapter,
    ovstage_scene: OvstageScene,
) -> None:
    stale_item = _require_item(stage_adapter, _INHERITED_VISIBLE_CHILD)
    stage = ovstage_scene._stage
    ordinal = stage.begin_frame()
    stage.delete_prims(ordinal, [_INHERITED_VISIBLE_CHILD])
    stage.end_frame(ordinal)

    assert stage_adapter.get_item_at_path(_INHERITED_VISIBLE_CHILD) is None
    assert stage_adapter.compute_visibility(stale_item) is VisibilityState.VISIBLE
    assert stage_adapter.can_edit_visibility(stale_item) is False
    with pytest.raises(NotImplementedError):
        stage_adapter.set_visibility(stale_item, False)


def test_property_visibility_authors_usd_and_synchronizes_ovstage(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = OvstagePropertyAdapter(ovstage_scene, [_HIDDEN_PARENT])
    stage = ovstage_scene._stage
    before = _raw_visibility(stage, _HIDDEN_PARENT)

    assert "visibility" in adapter.get_attribute_names()
    adapter.set_value("visibility", "inherited")

    assert before == "invisible"
    assert adapter.get_value("visibility") == "inherited"
    assert _raw_visibility(stage, _HIDDEN_PARENT) == "inherited"


def _require_item(adapter: OvstageStageAdapter, path: str) -> Any:
    item = adapter.get_item_at_path(path)
    assert item is not None, f"missing fixture prim: {path}"
    return item


def _raw_visibility(stage: Any, path: str) -> str:
    return read_token_attribute(stage, path, "visibility") or "inherited"


def _native_write(stage: Any, paths: tuple[str, ...], name: str, values: list[Any]) -> None:
    """Commit one frame through the public native Stage API, as a writer that is not OVUI."""
    import numpy as np
    import ovstage

    with ovstage.PathDictionary(stage) as dictionary:
        if all(isinstance(value, str) for value in values):
            array = np.asarray([dictionary.intern_token(value) for value in values], dtype=np.uint64)
            semantic = int(ovstage.AttributeSemantic.TOKEN_ID)
        else:
            array = np.asarray(values, dtype=np.int32)
            semantic = 0
        tensor = ovstage.make_dltensor(
            array, dtype=ovstage.numpy_to_dldatatype(array.dtype), shape=[len(paths)]
        )
        path_list = dictionary.create_path_list_from_strings(list(paths))
        query = stage.query_from_path_list(path_list)
        ordinal = stage.begin_frame()
        try:
            write = ovstage.WriteDesc(name, tensor, is_array=False, semantic=semantic)
            stage.write_attributes(query, (write,), ordinal, prim_mode=ovstage.PrimMode.UPSERT).wait()
        finally:
            query.release().wait()
            dictionary.destroy_path_list(path_list)
        stage.end_frame(ordinal)

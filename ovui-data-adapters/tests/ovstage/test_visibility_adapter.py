# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

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

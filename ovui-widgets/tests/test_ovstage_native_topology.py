# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from importlib import import_module
import pathlib
import time
from typing import Any

import pytest

from ovui_data_adapters.ovstage._stage_write import wait_operation
from ovui_data_adapters.ovstage._structural import (
    create_native_prims,
    delete_native_paths,
)
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    create_provider_session,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes
from ovui_data_adapters.ovstage.stage_adapter import OvstageStageAdapter
from ovui_widgets.stage.widget.hierarchy_model import HierarchyModel


pytestmark = [pytest.mark.requires_ovstage]

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_STATIC_SCENE_PATH = (
    _REPO_ROOT
    / "ovui-data-adapters"
    / "tests"
    / "data"
    / "ovstage_static_scene.usda"
)


@pytest.fixture()
def ovstage_runtime():
    return load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )


def _commit_raw_create(scene: Any, path: str) -> None:
    stage = scene.native_stage
    ordinal = int(scene.current_ordinal) + 1
    create_native_prims(stage, ((path, "Xform"),), ordinal=ordinal)
    wait_operation(stage.advance_write_floor(ordinal))


def _commit_raw_delete(scene: Any, *paths: str) -> None:
    stage = scene.native_stage
    ordinal = int(scene.current_ordinal) + 1
    delete_native_paths(stage, paths, ordinal=ordinal)
    wait_operation(stage.advance_write_floor(ordinal))


def _child_paths(adapter: Any, model: Any, path: str) -> list[str]:
    """Children of ``path`` as the rendered tree sees them."""

    item = model.resolve_path(path)
    if item is None:
        return []
    return [adapter.get_item_path(c.adapter_item) for c in model.get_item_children(item)]


def _model_subtree_paths(adapter: Any, model: Any, item: Any) -> list[str]:
    """Every path under ``item``; OVStage deletion does not cascade."""

    paths: list[str] = []
    for child in model.get_item_children(item):
        paths.append(adapter.get_item_path(child.adapter_item))
        paths.extend(_model_subtree_paths(adapter, model, child))
    return paths


def test_stage_tree_construction_queries_only_topology_metadata(
    ovstage_runtime: Any,
) -> None:
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(_STATIC_SCENE_PATH))
    stage = scene.native_stage
    model = None
    original_query = stage.query
    original_query_prims = stage.query_prims
    requested_attributes: list[tuple[str, ...]] = []
    broad_query_calls = 0

    def query(filter_value: Any, attributes: Any):
        assert attributes is not None, "Stage Tree construction used attribute discovery"
        ovstage = import_module("ovstage")
        with ovstage.PathDictionary(stage) as paths:
            names = tuple(paths.token_to_string(int(token)) for token in attributes)
        assert set(names) <= {"usd-path", "usd-prim-type", "usd-schemas"}
        requested_attributes.append(names)
        return original_query(filter_value, attributes)

    def query_prims(*_args: Any, **_kwargs: Any):
        nonlocal broad_query_calls
        broad_query_calls += 1
        raise AssertionError("Stage Tree construction used broad query_prims()")

    stage.query = query
    stage.query_prims = query_prims
    try:
        adapter = OvstageStageAdapter(scene)
        model = HierarchyModel(adapter)
        cube = adapter.get_item_at_path("/World/Hierarchy/GroupA/BoxA")

        assert cube is not None
        assert adapter.get_type_name(cube) == "Cube"
        assert requested_attributes
        assert {
            name
            for query_attributes in requested_attributes
            for name in query_attributes
        } == {"usd-path", "usd-prim-type", "usd-schemas"}
        assert broad_query_calls == 0
    finally:
        stage.query = original_query
        stage.query_prims = original_query_prims
        if model is not None:
            model.detach_document()
        session.shutdown_scene()


def test_materialized_stage_tree_recovers_after_a_topology_outage(
    ovstage_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tree already on screen must pick the prim up when reads recover.

    The publication delivers the path once while the whole-stage reads are
    unavailable, so the model materializes without it.  Recovery reconciles
    the adapter, but a model that keeps the children and the adapter item it
    cached during the outage renders a stage that is missing a prim until
    something unrelated rebuilds it.
    """

    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(_STATIC_SCENE_PATH))
    model = None
    try:
        adapter = OvstageStageAdapter(scene)
        model = HierarchyModel(adapter)
        scene.change_stream.poll()
        parent = "/World/Hierarchy"
        before = _child_paths(adapter, model, parent)
        assert before

        path = f"{parent}/OutageRecoveredProbe"
        _commit_raw_create(scene, path)

        scene_module = import_module("ovui_data_adapters.ovstage._scene")
        monkeypatch.setattr(
            scene_module, "_merge_kit_read_groups", lambda *_a, **_k: None
        )
        monkeypatch.setattr(
            scene_module, "_hierarchy_kit_child_paths", lambda *_a, **_k: None
        )
        monkeypatch.setattr(scene.native_stage, "fetch_read_next", lambda *_a, **_k: None)
        scene.native_stage._ovui_kit_stage_bridge_cache = None
        scene.change_stream.publish_resync_change([path], source="test:structural")
        assert path not in _child_paths(adapter, model, parent)

        monkeypatch.undo()
        assert scene.change_stream.poll()

        assert path in _child_paths(adapter, model, parent)
        assert model.resolve_path(path) is not None
    finally:
        if model is not None:
            model.detach_document()
        session.shutdown_scene()


def test_cached_stage_tree_tracks_raw_native_topology_commits(
    ovstage_runtime: Any,
) -> None:
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(_STATIC_SCENE_PATH))
    model = None
    try:
        adapter = OvstageStageAdapter(scene)
        model = HierarchyModel(adapter)
        world = model.resolve_path("/World")
        assert world is not None
        assert model.get_item_children(world)

        path = "/World/RawNativeTopologyProbe"
        _commit_raw_create(scene, path)
        assert scene.change_stream.poll()
        assert model.resolve_path(path) is not None

        _commit_raw_delete(scene, path)
        assert scene.change_stream.poll()
        assert model.resolve_path(path) is None

        # Deleting the last prim empties the stage.  A whole-stage read that
        # finds nothing is only indistinguishable from an unreadable runtime
        # if emptiness alone is the test, and then the tree never clears.
        remaining = _model_subtree_paths(adapter, model, model.resolve_path("/"))
        assert remaining
        _commit_raw_delete(scene, *remaining)
        assert scene.change_stream.poll()
        assert model.get_item_children(model.resolve_path("/")) == []
        assert scene.change_stream.poll() == ()
    finally:
        if model is not None:
            model.detach_document()
        session.shutdown_scene()


def test_scheduled_native_poll_tracks_raw_native_topology_commits(
    ovstage_runtime: Any,
) -> None:
    """The application's non-blocking poll must deliver native inserts and deletes."""

    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(_STATIC_SCENE_PATH))
    model = None
    stream = scene.change_stream
    if stream._native_dirty_collector is None:
        session.shutdown_scene()
        pytest.skip("native OVStage dirty collector is not available")

    def scheduled_poll(timeout: float = 10.0) -> tuple[Any, ...]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            events = stream._poll_impl(
                source=None,
                deliver_suppressed=False,
                allow_native_async=True,
            )
            if events:
                return events
            time.sleep(0.01)
        return ()

    try:
        adapter = OvstageStageAdapter(scene)
        model = HierarchyModel(adapter)
        assert model.resolve_path("/World") is not None
        scheduled_poll(timeout=1.0)

        path = "/World/ScheduledNativeTopologyProbe"
        _commit_raw_create(scene, path)
        assert scheduled_poll()
        assert model.resolve_path(path) is not None

        _commit_raw_delete(scene, path)
        assert scheduled_poll()
        assert model.resolve_path(path) is None
    finally:
        if model is not None:
            model.detach_document()
        session.shutdown_scene()

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION is strictly
# prohibited.

"""OVStage-native structural authoring contracts."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Iterator

import pytest

from ovui_data_adapters.common import ChangeEventType, CreateRequest, ReparentPosition
from ovui_data_adapters.ovstage._constants import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
)
from ovui_data_adapters.ovstage.provider import (
    create_provider_session,
    create_property_adapter,
    create_selection_adapter,
    create_stage_adapter,
    create_transform_adapter,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes
from ovui_data_adapters.services.undo import UndoManager


_SCENE = '''#usda 1.0

def Xform "World"
{
    def Xform "GroupA"
    {
        double3 xformOp:translate = (2, 3, 4)
        uniform token[] xformOpOrder = ["xformOp:translate"]

        def Cube "Box"
        {
            double size = 2
            rel material:binding = </World/Looks/SharedMaterial>

            def Sphere "Nested"
            {
                double radius = 0.75
            }
        }
        def Mesh "DataMesh"
        {
            int[] faceVertexCounts = [3]
            int[] faceVertexIndices = [0, 1, 2]
            point3f[] points = [(0, 0, 0), (2, 0, 0), (0, 2, 0)]
        }
        def Camera "InspectionCamera"
        {
            float focalLength = 31
        }
    }
    def Xform "GroupB"
    {
        double3 xformOp:translate = (-7, 5, 1)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }
    def Scope "Looks"
    {
        def Material "SharedMaterial"
        {
        }
    }
}
'''


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
def opened(
    tmp_path: Path,
    ovstage_runtime: Any,
) -> Iterator[tuple[Any, Any, Any, UndoManager]]:
    scene_path = tmp_path / "structural.usda"
    scene_path.write_text(_SCENE, encoding="utf-8")
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(scene_path))
    undo = UndoManager()
    adapter = create_stage_adapter(scene, undo)
    try:
        yield session, scene, adapter, undo
    finally:
        session.shutdown_scene()


def test_create_action_uses_native_type_and_is_one_undoable_resync(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, _scene, adapter, undo = opened
    events = []
    subscription = adapter.subscribe_changes(events.append)
    try:
        catalog = adapter.list_create_actions(selection_paths=("/World",))
        action = catalog.action("create.geometry.shape.cube")
        assert action is not None and action.is_available
        assert action.target_prim_type == "Cube"

        result = adapter.create_prim(
            CreateRequest(
                "create.geometry.shape.cube",
                requested_parent_path="/World/GroupB",
                requested_name="CreatedCube",
            )
        )
        assert result.accepted is True
        assert result.created_paths == ("/World/GroupB/CreatedCube",)
        created = adapter.get_item_at_path(result.primary_path)
        assert created is not None
        assert adapter.get_type_name(created) == "Cube"
        assert undo.can_undo() is True
        assert len(events) == 1
        assert events[0].event_type is ChangeEventType.RESYNC

        assert undo.undo() is True
        assert adapter.get_item_at_path(result.primary_path) is None
        assert len(events) == 2
        assert undo.redo() is True
        recreated = adapter.get_item_at_path(result.primary_path)
        assert recreated is not None
        assert adapter.get_type_name(recreated) == "Cube"
        assert len(events) == 3
    finally:
        subscription.cancel()


def test_rename_reparent_and_delete_are_native_and_undoable(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    session, _scene, adapter, undo = opened
    original = adapter.get_item_at_path("/World/GroupA/Box")
    group_b = adapter.get_item_at_path("/World/GroupB")
    assert original is not None and group_b is not None
    assert adapter.can_rename(original) is True

    actual_name = adapter.rename(original, "Renamed")
    assert actual_name == "Renamed"
    renamed = adapter.get_item_at_path("/World/GroupA/Renamed")
    assert renamed is not None
    assert adapter.get_type_name(renamed) == "Cube"

    assert adapter.can_reparent([renamed], group_b) is True
    adapter.reparent([renamed], group_b, ReparentPosition.CHILD)
    moved = adapter.get_item_at_path("/World/GroupB/Renamed")
    assert moved is not None
    assert adapter.get_type_name(moved) == "Cube"

    command = session.make_delete_prim_command(adapter.stage, "/World/GroupB/Renamed")
    undo.push(command)
    assert adapter.get_item_at_path("/World/GroupB/Renamed") is None

    assert undo.undo() is True
    restored = adapter.get_item_at_path("/World/GroupB/Renamed")
    assert restored is not None
    assert adapter.get_type_name(restored) == "Cube"
    assert undo.undo() is True
    assert adapter.get_item_at_path("/World/GroupA/Renamed") is not None
    assert undo.undo() is True
    assert adapter.get_item_at_path("/World/GroupA/Box") is not None


def test_structural_validation_failure_has_no_scene_or_history_effect(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, adapter, undo = opened
    before = (scene.current_ordinal, scene.topology_revision)
    result = adapter.create_prim(
        CreateRequest(
            "create.geometry.shape.cube",
            requested_parent_path="relative",
            requested_name="Bad",
        )
    )
    assert result.accepted is False
    assert (scene.current_ordinal, scene.topology_revision) == before
    assert undo.can_undo() is False


def test_every_available_action_creates_its_exact_native_type(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, _scene, adapter, undo = opened
    catalog = adapter.list_create_actions()
    disabled = {
        action.action_id: action.disabled_reason
        for action in catalog.actions
        if not action.is_available
    }
    assert set(disabled) == {"create.material.usd-preview-surface.bind"}
    assert "Select at least one" in disabled["create.material.usd-preview-surface.bind"]

    expected_types: dict[str, str] = {}
    created_by_action: dict[str, str] = {}
    for index, action in enumerate(catalog.available_actions):
        options = {"prim_type": "Cube"} if action.action_id == "create.prim" else {}
        expected_type = "Cube" if action.action_id == "create.prim" else action.target_prim_type
        result = adapter.create_prim(
            CreateRequest(
                action.action_id,
                requested_parent_path="/World/GroupB",
                requested_name=f"Action_{index}",
                options=options,
            )
        )
        assert result.accepted is True, (action.action_id, result.message)
        expected_types[result.primary_path] = expected_type
        created_by_action[action.action_id] = result.primary_path
        item = adapter.get_item_at_path(result.primary_path)
        assert item is not None
        assert adapter.get_type_name(item) == expected_type

    assert len(expected_types) == 27
    assert undo.can_undo() is True
    for path, expected_type in expected_types.items():
        item = adapter.get_item_at_path(path)
        assert item is not None
        assert adapter.get_type_name(item) == expected_type
    assert created_by_action["create.camera"] in {
        choice.path for choice in adapter.list_cameras()
    }
    assert created_by_action["create.render_product"] in {
        choice.path for choice in adapter.list_render_products()
    }


def test_create_default_scaffolds_unique_names_and_redo_clearing(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, _scene, adapter, undo = opened
    first = adapter.create_prim(CreateRequest("create.render_product"))
    assert first.accepted is True
    assert first.created_paths == (
        "/Render",
        "/Render/Products",
        "/Render/Products/RenderProduct",
    )
    assert adapter.get_item_at_path(first.primary_path) is not None
    assert [choice.path for choice in adapter.list_render_products()] == [
        "/Render/Products/RenderProduct"
    ]

    second = adapter.create_prim(CreateRequest("create.render_product"))
    assert second.accepted is True
    assert second.primary_path == "/Render/Products/RenderProduct_01"
    assert undo.undo() is True
    assert [choice.path for choice in adapter.list_render_products()] == [
        "/Render/Products/RenderProduct"
    ]
    replacement = adapter.create_prim(
        CreateRequest(
            "create.geometry.shape.sphere",
            requested_parent_path="/World/GroupB",
            requested_name="RedoBreaker",
        )
    )
    assert replacement.accepted is True
    assert undo.can_redo() is False


@pytest.mark.parametrize(
    ("parent", "name", "action", "options"),
    (
        ("relative", "Bad", "create.geometry.shape.cube", {}),
        ("/World/", "Bad", "create.geometry.shape.cube", {}),
        ("/World//GroupB", "Bad", "create.geometry.shape.cube", {}),
        ("/World/Missing", "Bad", "create.geometry.shape.cube", {}),
        ("/World/GroupB", "   ", "create.geometry.shape.cube", {}),
        ("/World/GroupB", "Bad", "create.prim", {"prim_type": ""}),
        ("/World/GroupB", "Bad", "create.prim", {"prim_type": "InventedType"}),
    ),
)
def test_create_validation_is_atomic_and_silent(
    opened: tuple[Any, Any, Any, UndoManager],
    parent: str,
    name: str,
    action: str,
    options: dict[str, str],
) -> None:
    _session, scene, adapter, undo = opened
    events = []
    subscription = adapter.subscribe_changes(events.append)
    before = (scene.current_ordinal, scene.topology_revision)
    try:
        result = adapter.create_prim(
            CreateRequest(
                action,
                requested_parent_path=parent,
                requested_name=name,
                options=options,
            )
        )
    finally:
        subscription.cancel()
    assert result.accepted is False
    assert (scene.current_ordinal, scene.topology_revision) == before
    assert undo.can_undo() is False
    assert events == []


def test_delete_subtree_undo_restores_types_arrays_relationships_and_catalogs(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    session, scene, adapter, undo = opened
    mesh_path = "/World/GroupA/DataMesh"
    box_path = "/World/GroupA/Box"
    mesh = create_property_adapter(scene, [mesh_path])
    box = create_property_adapter(scene, [box_path])
    before_points = mesh.get_value("points")
    before_counts = mesh.get_value("faceVertexCounts")
    before_binding = box.get_value("material:binding")
    before_cameras = tuple(choice.path for choice in adapter.list_cameras())

    undo.push(session.make_delete_prim_command(adapter.stage, "/World/GroupA"))
    assert adapter.get_item_at_path("/World/GroupA") is None
    assert "/World/GroupA/InspectionCamera" not in {
        choice.path for choice in adapter.list_cameras()
    }

    assert undo.undo() is True
    restored_mesh = create_property_adapter(scene, [mesh_path])
    restored_box = create_property_adapter(scene, [box_path])
    assert restored_mesh.get_value("points") == before_points
    assert restored_mesh.get_value("faceVertexCounts") == before_counts
    assert restored_box.get_value("material:binding") == before_binding
    assert tuple(choice.path for choice in adapter.list_cameras()) == before_cameras
    assert adapter.get_type_name(adapter.get_item_at_path(box_path)) == "Cube"
    assert adapter.get_type_name(
        adapter.get_item_at_path(f"{box_path}/Nested")
    ) == "Sphere"
    assert undo.redo() is True
    assert adapter.get_item_at_path("/World/GroupA") is None


def test_namespace_edits_preserve_native_data_and_local_spatial_semantics(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, adapter, undo = opened
    transform = create_transform_adapter(scene)
    old_path = "/World/GroupA/Box"
    old_local = tuple(transform.get_local_transform(old_path))
    old_world = tuple(transform.get_world_transform(old_path))
    old_binding = create_property_adapter(scene, [old_path]).get_value(
        "material:binding"
    )
    box = adapter.get_item_at_path(old_path)
    group_b = adapter.get_item_at_path("/World/GroupB")

    assert adapter.rename(box, "Café_Box") == "Café_Box"
    renamed_path = "/World/GroupA/Café_Box"
    renamed = adapter.get_item_at_path(renamed_path)
    assert renamed is not None
    assert create_property_adapter(scene, [renamed_path]).get_value(
        "material:binding"
    ) == old_binding
    adapter.reparent([renamed], group_b, ReparentPosition.CHILD)
    moved_path = "/World/GroupB/Café_Box"
    assert tuple(transform.get_local_transform(moved_path)) == old_local
    # Exact public clone preserves both populated matrix columns. Correcting
    # either one would require an out-of-scope persistent transform write.
    assert tuple(transform.get_world_transform(moved_path)) == old_world
    assert create_property_adapter(scene, [moved_path]).get_value(
        "material:binding"
    ) == old_binding
    assert adapter.get_item_at_path(f"{moved_path}/Nested") is not None

    assert undo.undo() is True
    assert adapter.get_item_at_path(renamed_path) is not None
    assert undo.undo() is True
    assert adapter.get_item_at_path(old_path) is not None


def test_namespace_validation_rejects_cycles_collisions_duplicates_and_stale_items(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, adapter, undo = opened
    box = adapter.get_item_at_path("/World/GroupA/Box")
    nested = adapter.get_item_at_path("/World/GroupA/Box/Nested")
    group_a = adapter.get_item_at_path("/World/GroupA")
    group_b = adapter.get_item_at_path("/World/GroupB")
    before = (scene.current_ordinal, scene.topology_revision)

    assert adapter.can_reparent([group_a], nested) is False
    assert adapter.can_reparent([box, box], group_b) is False
    with pytest.raises(ValueError, match="themselves"):
        adapter.reparent([group_a], nested, ReparentPosition.CHILD)
    with pytest.raises(ValueError, match="Duplicate"):
        adapter.reparent([box, box], group_b, ReparentPosition.CHILD)

    adapter.rename(box, "Collision")
    collision = adapter.get_item_at_path("/World/GroupA/Collision")
    assert collision is not None
    with pytest.raises(ValueError, match="already exists"):
        adapter.rename(collision, "DataMesh")
    stale = box
    assert adapter.can_rename(stale) is False
    assert (scene.current_ordinal, scene.topology_revision) == (
        before[0] + 1,
        before[1] + 1,
    )
    assert undo.can_undo() is True


@pytest.mark.parametrize("position", (ReparentPosition.BEFORE, ReparentPosition.AFTER))
def test_unrepresentable_sibling_order_moves_fail_without_mutation(
    opened: tuple[Any, Any, Any, UndoManager],
    position: ReparentPosition,
) -> None:
    _session, scene, adapter, undo = opened
    box = adapter.get_item_at_path("/World/GroupA/Box")
    group_b = adapter.get_item_at_path("/World/GroupB")
    before = (scene.current_ordinal, scene.topology_revision)
    with pytest.raises(NotImplementedError):
        adapter.reparent([box], group_b, position)
    assert (scene.current_ordinal, scene.topology_revision) == before
    assert adapter.get_item_at_path("/World/GroupA/Box") is not None
    assert adapter.get_item_at_path("/World/Box") is None
    assert undo.can_undo() is False


def test_selection_translation_filters_deleted_and_moved_paths_without_aliasing(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    session, scene, adapter, undo = opened
    selection = create_selection_adapter(scene, adapter)
    box_path = "/World/GroupA/Box"
    old_item = selection.to_adapter_items([box_path])[0]
    undo.push(session.make_delete_prim_command(adapter.stage, box_path))
    assert selection.to_adapter_items([box_path]) == []
    assert selection.to_selection_items([old_item]) == []
    assert undo.undo() is True
    current = selection.to_adapter_items([box_path])
    assert len(current) == 1
    assert current[0] is not old_item


@pytest.mark.parametrize(
    "path",
    (
        "/",
        "relative",
        "/World/",
        "/World//GroupA",
        "/World/Missing",
        "/__ovstage_population_stage_info__",
        "/TempChangeTracking",
        "/omni_rtx_loadingStatePrim",
    ),
)
def test_delete_validation_is_atomic_silent_and_stage_local(
    opened: tuple[Any, Any, Any, UndoManager],
    path: str,
) -> None:
    session, scene, adapter, undo = opened
    events = []
    subscription = adapter.subscribe_changes(events.append)
    before = (scene.current_ordinal, scene.topology_revision)
    try:
        with pytest.raises((ValueError, NotImplementedError)):
            session.make_delete_prim_command(adapter.stage, path)
        with pytest.raises(NotImplementedError):
            session.make_delete_prim_command(object(), "/World/GroupA")
    finally:
        subscription.cancel()
    assert (scene.current_ordinal, scene.topology_revision) == before
    assert undo.can_undo() is False
    assert events == []


def test_duplicate_and_colliding_native_batches_fail_before_a_frame(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, adapter, undo = opened
    before = (scene.current_ordinal, scene.topology_revision)
    with pytest.raises(ValueError, match="duplicate"):
        scene.prepare_native_topology(
            (),
            (
                ("/World/GroupB/Duplicate", "Cube"),
                ("/World/GroupB/Duplicate", "Sphere"),
            ),
        )
    with pytest.raises(RuntimeError, match="already contains"):
        scene.prepare_native_topology(
            (),
            (("/World/GroupA", "Xform"),),
        )
    assert (scene.current_ordinal, scene.topology_revision) == before
    assert adapter.get_item_at_path("/World/GroupB/Duplicate") is None
    assert undo.can_undo() is False


def test_structural_events_are_single_observer_safe_and_reentrant_safe(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, _scene, adapter, undo = opened
    events = []
    reentrant_results = []
    subscriptions = (
        adapter.subscribe_changes(lambda _event: (_ for _ in ()).throw(RuntimeError("observer"))),
        adapter.subscribe_changes(events.append),
        adapter.subscribe_changes(
            lambda _event: reentrant_results.append(
                adapter.create_prim(
                    CreateRequest(
                        "create.scope",
                        requested_parent_path="/World/GroupB",
                        requested_name="Reentrant",
                    )
                )
            )
        ),
    )
    try:
        result = adapter.create_prim(
            CreateRequest(
                "create.geometry.shape.cube",
                requested_parent_path="/World/GroupB",
                requested_name="EventCube",
            )
        )
        assert result.accepted is True
        assert len(events) == 1
        assert events[0].event_type is ChangeEventType.RESYNC
        assert reentrant_results[-1].accepted is False
        assert adapter.get_item_at_path("/World/GroupB/Reentrant") is None
        assert undo.undo() is True
        assert len(events) == 2
        assert undo.redo() is True
        assert len(events) == 3
    finally:
        for subscription in subscriptions:
            subscription.cancel()


def test_failed_multi_type_native_batch_rolls_back_without_committed_ordinal(
    opened: tuple[Any, Any, Any, UndoManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session, scene, adapter, undo = opened
    stage = scene._stage
    original_create = stage.create_prims
    calls = 0

    def fail_second_type(ordinal: int, paths: tuple[str, ...], type_name: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected second type failure")
        original_create(ordinal, paths, type_name)

    monkeypatch.setattr(stage, "create_prims", fail_second_type)
    before = (scene.current_ordinal, scene.topology_revision)
    with pytest.raises(RuntimeError, match="failed to prepare"):
        scene.prepare_native_topology(
            ("/World/GroupA/Box",),
            (
                ("/World/GroupB/RollbackCube", "Cube"),
                ("/World/GroupB/RollbackSphere", "Sphere"),
            ),
        )
    assert (scene.current_ordinal, scene.topology_revision) == before
    assert adapter.get_item_at_path("/World/GroupA/Box") is not None
    assert adapter.get_item_at_path("/World/GroupB/RollbackCube") is None
    assert adapter.get_item_at_path("/World/GroupB/RollbackSphere") is None
    assert undo.can_undo() is False

    monkeypatch.setattr(stage, "create_prims", original_create)
    result = adapter.create_prim(
        CreateRequest(
            "create.geometry.shape.cube",
            requested_parent_path="/World/GroupB",
            requested_name="AfterRollback",
        )
    )
    assert result.accepted is True
    assert adapter.get_item_at_path("/World/GroupA/Box") is not None
    assert adapter.get_item_at_path("/World/GroupB/RollbackCube") is None


def test_history_from_replaced_scene_cannot_mutate_new_scene(
    tmp_path: Path,
    ovstage_runtime: Any,
) -> None:
    first_path = tmp_path / "first.usda"
    second_path = tmp_path / "second.usda"
    first_path.write_text(_SCENE, encoding="utf-8")
    second_path.write_text(
        '#usda 1.0\n\ndef Xform "Replacement"\n{\n}\n',
        encoding="utf-8",
    )
    session = create_provider_session(runtime=ovstage_runtime)
    undo = UndoManager()
    first = session.open_stage(str(first_path))
    adapter = create_stage_adapter(first, undo)
    result = adapter.create_prim(
        CreateRequest(
            "create.scope",
            requested_parent_path="/World/GroupB",
            requested_name="OldHistory",
        )
    )
    assert result.accepted is True
    replacement = session.open_stage(str(second_path))
    replacement_adapter = create_stage_adapter(replacement)
    try:
        with pytest.raises(RuntimeError, match="closed or replaced"):
            undo.undo()
        assert undo.can_undo() is True
        assert replacement_adapter.get_item_at_path("/Replacement") is not None
        assert replacement_adapter.get_item_at_path(result.primary_path) is None
    finally:
        session.shutdown_scene()


def test_closed_scene_rejects_new_structural_edits(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    session, scene, adapter, undo = opened
    item = adapter.get_item_at_path("/World/GroupA/Box")
    assert item is not None
    session.shutdown_scene()

    result = adapter.create_prim(
        CreateRequest(
            "create.scope",
            requested_parent_path="/World",
            requested_name="AfterClose",
        )
    )
    assert result.accepted is False
    assert adapter.can_rename(item) is False
    with pytest.raises(NotImplementedError):
        session.make_delete_prim_command(scene._stage, "/World/GroupA/Box")
    assert undo.can_undo() is False

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for MockStageAdapter — in-memory StageAdapter development harness."""

import pytest
from ovui_data_adapters.common import (
    BadgeFlags,
    ChangeEventType,
    ItemFlags,
    ReparentPosition,
    VisibilityState,
)

from ovui_widgets.common.settings import Subscription
from ovui_widgets.common.testing.mock_stage import MockStageAdapter

# ── Default tree ──────────────────────────────────────────────────────────────

class TestDefaultTree:
    def test_root_name(self):
        adapter = MockStageAdapter()
        assert adapter.get_display_name(adapter.get_root()) == "World"

    def test_root_path(self):
        adapter = MockStageAdapter()
        assert adapter.get_item_path(adapter.get_root()) == "/World"

    def test_root_type(self):
        adapter = MockStageAdapter()
        assert adapter.get_type_name(adapter.get_root()) == "Xform"

    def test_root_has_three_children(self):
        adapter = MockStageAdapter()
        assert len(adapter.get_children(adapter.get_root())) == 3

    def test_child_names(self):
        adapter = MockStageAdapter()
        names = [adapter.get_display_name(c) for c in adapter.get_children(adapter.get_root())]
        assert names == ["Geometry", "Lights", "Camera"]

    def test_geometry_has_three_children(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        assert len(adapter.get_children(geometry)) == 3

    def test_geometry_children_names(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        names = [adapter.get_display_name(c) for c in adapter.get_children(geometry)]
        assert names == ["Ground", "Sphere", "Cube"]

    def test_lights_has_one_child(self):
        adapter = MockStageAdapter()
        lights = adapter.get_children(adapter.get_root())[1]
        assert len(adapter.get_children(lights)) == 1
        assert adapter.get_display_name(adapter.get_children(lights)[0]) == "DomeLight"

    def test_all_paths_correct(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        geometry, lights, camera = adapter.get_children(root)
        ground, sphere, cube = adapter.get_children(geometry)
        dome = adapter.get_children(lights)[0]

        assert adapter.get_item_path(geometry) == "/World/Geometry"
        assert adapter.get_item_path(lights) == "/World/Lights"
        assert adapter.get_item_path(camera) == "/World/Camera"
        assert adapter.get_item_path(ground) == "/World/Geometry/Ground"
        assert adapter.get_item_path(sphere) == "/World/Geometry/Sphere"
        assert adapter.get_item_path(cube) == "/World/Geometry/Cube"
        assert adapter.get_item_path(dome) == "/World/Lights/DomeLight"

    def test_type_names(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        geometry, lights, camera = adapter.get_children(root)
        ground = adapter.get_children(geometry)[0]
        dome = adapter.get_children(lights)[0]

        assert adapter.get_type_name(geometry) == "Xform"
        assert adapter.get_type_name(ground) == "Mesh"
        assert adapter.get_type_name(dome) == "Light"
        assert adapter.get_type_name(camera) == "Camera"

    def test_can_have_children(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        ground = adapter.get_children(adapter.get_children(root)[0])[0]
        assert adapter.can_have_children(root) is True
        assert adapter.can_have_children(ground) is True

    def test_get_item_at_path_root(self):
        adapter = MockStageAdapter()
        assert adapter.get_item_at_path("/World") is adapter.get_root()

    def test_get_item_at_path_deep(self):
        adapter = MockStageAdapter()
        item = adapter.get_item_at_path("/World/Geometry/Sphere")
        assert item is not None
        assert adapter.get_display_name(item) == "Sphere"

    def test_get_item_at_path_missing(self):
        adapter = MockStageAdapter()
        assert adapter.get_item_at_path("/World/DoesNotExist") is None

    def test_get_children_returns_copy(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        children_a = adapter.get_children(root)
        children_b = adapter.get_children(root)
        assert children_a is not children_b


# ── Icons and flags ───────────────────────────────────────────────────────────

class TestIconsAndFlags:
    def test_mesh_icon(self):
        adapter = MockStageAdapter()
        ground = adapter.get_children(adapter.get_children(adapter.get_root())[0])[0]
        assert adapter.get_icon_name(ground) == "Mesh"

    def test_light_icon(self):
        adapter = MockStageAdapter()
        dome = adapter.get_children(adapter.get_children(adapter.get_root())[1])[0]
        assert adapter.get_icon_name(dome) == "Light"

    def test_camera_icon(self):
        adapter = MockStageAdapter()
        camera = adapter.get_children(adapter.get_root())[2]
        assert adapter.get_icon_name(camera) == "Camera"

    def test_xform_icon(self):
        adapter = MockStageAdapter()
        assert adapter.get_icon_name(adapter.get_root()) == "Xform"

    def test_generic_icon_for_unknown_type(self):
        adapter = MockStageAdapter()
        item = adapter.add_child("/World", "Weird", "CustomType")
        assert adapter.get_icon_name(item) == "Prim"

    def test_mesh_category(self):
        adapter = MockStageAdapter()
        ground = adapter.get_children(adapter.get_children(adapter.get_root())[0])[0]
        assert adapter.get_type_category(ground) == "Mesh"

    def test_light_category(self):
        adapter = MockStageAdapter()
        dome = adapter.get_children(adapter.get_children(adapter.get_root())[1])[0]
        assert adapter.get_type_category(dome) == "Light"

    def test_camera_category(self):
        adapter = MockStageAdapter()
        camera = adapter.get_children(adapter.get_root())[2]
        assert adapter.get_type_category(camera) == "Camera"

    def test_xform_category(self):
        adapter = MockStageAdapter()
        assert adapter.get_type_category(adapter.get_root()) == "Xform"

    def test_unknown_type_returns_other_category(self):
        adapter = MockStageAdapter()
        item = adapter.add_child("/World", "Weird", "CustomType")
        assert adapter.get_type_category(item) == "Other"

    def test_get_item_flags_returns_none(self):
        adapter = MockStageAdapter()
        assert adapter.get_item_flags(adapter.get_root()) == ItemFlags.NONE

    def test_get_badge_flags_returns_none(self):
        adapter = MockStageAdapter()
        assert adapter.get_badge_flags(adapter.get_root()) == BadgeFlags.NONE

    def test_get_badge_flags_returns_badgeflags_instance(self):
        adapter = MockStageAdapter()
        assert isinstance(adapter.get_badge_flags(adapter.get_root()), BadgeFlags)

    def test_can_edit_visibility(self):
        adapter = MockStageAdapter()
        assert adapter.can_edit_visibility(adapter.get_root()) is True


# ── Visibility ────────────────────────────────────────────────────────────────

class TestVisibility:
    def test_all_start_visible(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        assert adapter.compute_visibility(root) == VisibilityState.VISIBLE
        for child in adapter.get_children(root):
            assert adapter.compute_visibility(child) == VisibilityState.VISIBLE

    def test_set_invisible(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        adapter.set_visibility(geometry, False)
        assert adapter.compute_visibility(geometry) == VisibilityState.INVISIBLE

    def test_child_of_invisible_parent(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        ground = adapter.get_children(geometry)[0]
        adapter.set_visibility(geometry, False)
        assert adapter.compute_visibility(ground) == VisibilityState.INHERITED_INVISIBLE

    def test_set_back_to_visible(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        adapter.set_visibility(geometry, False)
        adapter.set_visibility(geometry, True)
        assert adapter.compute_visibility(geometry) == VisibilityState.VISIBLE

    def test_child_visible_when_parent_restored(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        ground = adapter.get_children(geometry)[0]
        adapter.set_visibility(geometry, False)
        adapter.set_visibility(geometry, True)
        assert adapter.compute_visibility(ground) == VisibilityState.VISIBLE

    def test_root_invisible_makes_children_inherited(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        geometry = adapter.get_children(root)[0]
        adapter.set_visibility(root, False)
        assert adapter.compute_visibility(root) == VisibilityState.INVISIBLE
        assert adapter.compute_visibility(geometry) == VisibilityState.INHERITED_INVISIBLE

    def test_item_invisible_parent_invisible_is_invisible_not_inherited(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        ground = adapter.get_children(geometry)[0]
        adapter.set_visibility(geometry, False)
        adapter.set_visibility(ground, False)
        # ground is explicitly invisible (its own flag), not just inherited
        assert adapter.compute_visibility(ground) == VisibilityState.INVISIBLE


# ── Rename ────────────────────────────────────────────────────────────────────

class TestRename:
    def test_can_rename_non_root(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        assert adapter.can_rename(geometry) is True

    def test_cannot_rename_root(self):
        adapter = MockStageAdapter()
        assert adapter.can_rename(adapter.get_root()) is False

    def test_rename_updates_name(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        adapter.rename(geometry, "NewGeometry")
        assert adapter.get_display_name(geometry) == "NewGeometry"

    def test_rename_updates_path(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        adapter.rename(geometry, "NewGeometry")
        assert adapter.get_item_path(geometry) == "/World/NewGeometry"

    def test_rename_updates_children_paths(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        ground = adapter.get_children(geometry)[0]
        adapter.rename(geometry, "NewGeometry")
        assert adapter.get_item_path(ground) == "/World/NewGeometry/Ground"

    def test_rename_returns_name(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        result = adapter.rename(geometry, "NewGeometry")
        assert result == "NewGeometry"

    def test_rename_notifies_subscriber(self):
        adapter = MockStageAdapter()
        events = []
        sub = adapter.subscribe_changes(lambda e: events.append(e))  # noqa: F841
        geometry = adapter.get_children(adapter.get_root())[0]
        adapter.rename(geometry, "NewGeometry")
        assert len(events) == 1
        assert events[0].event_type == ChangeEventType.RESYNC

    def test_normalize_name_strips_spaces(self):
        adapter = MockStageAdapter()
        assert adapter.normalize_name("hello world") == "hello_world"

    def test_normalize_name_strips_dots_dashes(self):
        adapter = MockStageAdapter()
        assert adapter.normalize_name("a.b-c") == "a_b_c"

    def test_normalize_name_preserves_valid_chars(self):
        adapter = MockStageAdapter()
        assert adapter.normalize_name("valid_name_123") == "valid_name_123"

    def test_rename_deep_nesting_path_propagation(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        geometry = adapter.get_children(root)[0]
        ground = adapter.get_children(geometry)[0]
        adapter.rename(geometry, "Geo")
        assert adapter.get_item_path(ground) == "/World/Geo/Ground"

    def test_rename_then_rename_child(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        ground = adapter.get_children(geometry)[0]
        adapter.rename(geometry, "Geo")
        adapter.rename(ground, "Floor")
        assert adapter.get_item_path(ground) == "/World/Geo/Floor"

    def test_get_item_at_path_after_rename(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        adapter.rename(geometry, "Geo")
        assert adapter.get_item_at_path("/World/Geometry") is None
        assert adapter.get_item_at_path("/World/Geo") is not None


# ── Reparent ──────────────────────────────────────────────────────────────────

class TestReparent:
    def test_reparent_moves_item_parent(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        geometry = adapter.get_children(root)[0]
        cube = adapter.get_children(geometry)[2]
        adapter.reparent([cube], root, ReparentPosition.CHILD)
        assert cube.parent is root

    def test_reparent_adds_to_new_parent_children(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        geometry = adapter.get_children(root)[0]
        cube = adapter.get_children(geometry)[2]
        adapter.reparent([cube], root, ReparentPosition.CHILD)
        assert cube in root.children

    def test_reparent_removes_from_old_parent(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        geometry = adapter.get_children(root)[0]
        cube = adapter.get_children(geometry)[2]
        adapter.reparent([cube], root, ReparentPosition.CHILD)
        assert cube not in geometry.children

    def test_reparent_updates_path(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        geometry = adapter.get_children(root)[0]
        cube = adapter.get_children(geometry)[2]
        adapter.reparent([cube], root, ReparentPosition.CHILD)
        assert adapter.get_item_path(cube) == "/World/Cube"

    def test_reparent_notifies_subscriber(self):
        adapter = MockStageAdapter()
        events = []
        sub = adapter.subscribe_changes(lambda e: events.append(e))  # noqa: F841
        root = adapter.get_root()
        geometry = adapter.get_children(root)[0]
        cube = adapter.get_children(geometry)[2]
        adapter.reparent([cube], root, ReparentPosition.CHILD)
        assert len(events) == 1
        assert events[0].event_type == ChangeEventType.RESYNC

    def test_can_reparent_valid(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        geometry = adapter.get_children(root)[0]
        cube = adapter.get_children(geometry)[2]
        assert adapter.can_reparent([cube], root) is True

    def test_cannot_reparent_into_self(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        assert adapter.can_reparent([geometry], geometry) is False

    def test_cannot_reparent_into_descendant(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        geometry = adapter.get_children(root)[0]
        ground = adapter.get_children(geometry)[0]
        assert adapter.can_reparent([geometry], ground) is False

    def test_reparent_multiple_items(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        geometry = adapter.get_children(root)[0]
        sphere = adapter.get_children(geometry)[1]
        cube = adapter.get_children(geometry)[2]
        adapter.reparent([sphere, cube], root, ReparentPosition.CHILD)
        assert sphere.parent is root
        assert cube.parent is root

    def test_reparent_updates_path_for_all_items(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        geometry = adapter.get_children(root)[0]
        sphere = adapter.get_children(geometry)[1]
        cube = adapter.get_children(geometry)[2]
        adapter.reparent([sphere, cube], root, ReparentPosition.CHILD)
        assert adapter.get_item_path(sphere) == "/World/Sphere"
        assert adapter.get_item_path(cube) == "/World/Cube"


# ── Subscriber notifications ──────────────────────────────────────────────────

class TestSubscriberNotifications:
    def test_subscribe_returns_subscription(self):
        adapter = MockStageAdapter()
        sub = adapter.subscribe_changes(lambda e: None)
        assert isinstance(sub, Subscription)

    def test_subscriber_called_on_visibility_change(self):
        adapter = MockStageAdapter()
        events = []
        sub = adapter.subscribe_changes(lambda e: events.append(e))  # noqa: F841
        adapter.set_visibility(adapter.get_children(adapter.get_root())[0], False)
        assert len(events) == 1

    def test_subscriber_called_on_rename(self):
        adapter = MockStageAdapter()
        events = []
        sub = adapter.subscribe_changes(lambda e: events.append(e))  # noqa: F841
        adapter.rename(adapter.get_children(adapter.get_root())[0], "NewName")
        assert len(events) == 1

    def test_subscriber_called_on_reparent(self):
        adapter = MockStageAdapter()
        events = []
        sub = adapter.subscribe_changes(lambda e: events.append(e))  # noqa: F841
        root = adapter.get_root()
        geometry = adapter.get_children(root)[0]
        cube = adapter.get_children(geometry)[2]
        adapter.reparent([cube], root, ReparentPosition.CHILD)
        assert len(events) == 1

    def test_subscriber_not_called_when_suppressed(self):
        adapter = MockStageAdapter()
        events = []
        sub = adapter.subscribe_changes(lambda e: events.append(e))  # noqa: F841
        geometry = adapter.get_children(adapter.get_root())[0]
        with adapter.suppress_change_notifications():
            adapter.set_visibility(geometry, False)
        assert len(events) == 0

    def test_events_resume_after_suppress(self):
        adapter = MockStageAdapter()
        events = []
        sub = adapter.subscribe_changes(lambda e: events.append(e))  # noqa: F841
        geometry = adapter.get_children(adapter.get_root())[0]
        with adapter.suppress_change_notifications():
            adapter.set_visibility(geometry, False)
        adapter.set_visibility(geometry, True)
        assert len(events) == 1

    def test_subscription_cancel_stops_notifications(self):
        adapter = MockStageAdapter()
        events = []
        sub = adapter.subscribe_changes(lambda e: events.append(e))
        geometry = adapter.get_children(adapter.get_root())[0]
        adapter.set_visibility(geometry, False)
        assert len(events) == 1
        sub.cancel()
        adapter.set_visibility(geometry, True)
        assert len(events) == 1

    def test_cancel_is_idempotent(self):
        adapter = MockStageAdapter()
        sub = adapter.subscribe_changes(lambda e: None)
        sub.cancel()
        sub.cancel()  # should not raise

    def test_multiple_subscribers_all_called(self):
        adapter = MockStageAdapter()
        events_a, events_b = [], []
        sub_a = adapter.subscribe_changes(lambda e: events_a.append(e))  # noqa: F841
        sub_b = adapter.subscribe_changes(lambda e: events_b.append(e))  # noqa: F841
        adapter.set_visibility(adapter.get_children(adapter.get_root())[0], False)
        assert len(events_a) == 1
        assert len(events_b) == 1

    def test_cancel_one_subscriber_leaves_other(self):
        adapter = MockStageAdapter()
        events_a, events_b = [], []
        sub_a = adapter.subscribe_changes(lambda e: events_a.append(e))
        sub_b = adapter.subscribe_changes(lambda e: events_b.append(e))  # noqa: F841
        sub_a.cancel()
        adapter.set_visibility(adapter.get_children(adapter.get_root())[0], False)
        assert len(events_a) == 0
        assert len(events_b) == 1


# ── Test helpers ──────────────────────────────────────────────────────────────

class TestTestHelpers:
    def test_add_child_creates_item(self):
        adapter = MockStageAdapter()
        item = adapter.add_child("/World", "NewPrim", "Mesh")
        assert adapter.get_display_name(item) == "NewPrim"
        assert adapter.get_type_name(item) == "Mesh"
        assert adapter.get_item_path(item) == "/World/NewPrim"

    def test_add_child_appends_to_parent(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        initial = len(adapter.get_children(root))
        adapter.add_child("/World", "Extra", "Xform")
        assert len(adapter.get_children(root)) == initial + 1

    def test_add_child_notifies_resync(self):
        adapter = MockStageAdapter()
        events = []
        sub = adapter.subscribe_changes(lambda e: events.append(e))  # noqa: F841
        adapter.add_child("/World", "Extra", "Xform")
        assert len(events) == 1
        assert events[0].event_type == ChangeEventType.RESYNC

    def test_add_child_missing_parent_raises(self):
        adapter = MockStageAdapter()
        with pytest.raises(ValueError, match="No item at path"):
            adapter.add_child("/World/Missing", "Child", "Mesh")

    def test_add_child_sets_parent_ref(self):
        adapter = MockStageAdapter()
        item = adapter.add_child("/World", "NewPrim", "Mesh")
        assert item.parent is adapter.get_root()

    def test_remove_deletes_item(self):
        adapter = MockStageAdapter()
        adapter.remove("/World/Geometry")
        assert adapter.get_item_at_path("/World/Geometry") is None

    def test_remove_removes_from_parent_children(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        geometry = adapter.get_children(root)[0]
        adapter.remove("/World/Geometry")
        assert geometry not in adapter.get_children(root)

    def test_remove_notifies_resync(self):
        adapter = MockStageAdapter()
        events = []
        sub = adapter.subscribe_changes(lambda e: events.append(e))  # noqa: F841
        adapter.remove("/World/Geometry")
        assert len(events) == 1
        assert events[0].event_type == ChangeEventType.RESYNC

    def test_remove_missing_path_no_crash(self):
        adapter = MockStageAdapter()
        adapter.remove("/World/NonExistent")

    def test_fire_change_sends_event(self):
        adapter = MockStageAdapter()
        events = []
        sub = adapter.subscribe_changes(lambda e: events.append(e))  # noqa: F841
        adapter.fire_change(["/World/Geometry"])
        assert len(events) == 1
        assert events[0].changed_paths == ("/World/Geometry",)
        assert events[0].event_type == ChangeEventType.INFO_CHANGE

    def test_fire_change_multiple_paths(self):
        adapter = MockStageAdapter()
        events = []
        sub = adapter.subscribe_changes(lambda e: events.append(e))  # noqa: F841
        adapter.fire_change(["/World/A", "/World/B"])
        assert events[0].changed_paths == ("/World/A", "/World/B")


# ── Large tree ────────────────────────────────────────────────────────────────

class TestLargeTree:
    def test_large_tree_prim_count(self):
        adapter = MockStageAdapter(prim_count=1000)
        assert len(adapter.get_children(adapter.get_root())) == 1000

    def test_large_tree_iteration_no_crash(self):
        adapter = MockStageAdapter(prim_count=1000)
        for child in adapter.get_children(adapter.get_root()):
            _ = adapter.get_item_path(child)
            _ = adapter.get_display_name(child)
            _ = adapter.compute_visibility(child)

    def test_large_tree_paths_unique(self):
        adapter = MockStageAdapter(prim_count=100)
        paths = [adapter.get_item_path(c) for c in adapter.get_children(adapter.get_root())]
        assert len(paths) == len(set(paths))

    def test_large_tree_root_name(self):
        adapter = MockStageAdapter(prim_count=10)
        assert adapter.get_display_name(adapter.get_root()) == "World"


# ── Filter ────────────────────────────────────────────────────────────────────

class TestFilterItems:
    def test_filter_keeps_matching(self):
        adapter = MockStageAdapter()
        geometry = adapter.get_children(adapter.get_root())[0]
        result = adapter.filter_items(
            adapter.get_children(geometry),
            lambda i: adapter.get_type_name(i) == "Mesh",
        )
        assert len(result) == 3

    def test_filter_removes_non_matching(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        result = adapter.filter_items(
            adapter.get_children(root),
            lambda i: adapter.get_type_name(i) == "Camera",
        )
        assert len(result) == 1
        assert adapter.get_display_name(result[0]) == "Camera"

    def test_filter_empty_list(self):
        adapter = MockStageAdapter()
        assert adapter.filter_items([], lambda i: True) == []

    def test_filter_none_match(self):
        adapter = MockStageAdapter()
        result = adapter.filter_items(
            adapter.get_children(adapter.get_root()),
            lambda i: False,
        )
        assert result == []


# ── Undo stubs ────────────────────────────────────────────────────────────────

class TestUndoStubs:
    def test_begin_end_no_crash(self):
        adapter = MockStageAdapter()
        adapter.begin_undo_group("test")
        adapter.end_undo_group()

    def test_nested_groups_no_crash(self):
        adapter = MockStageAdapter()
        adapter.begin_undo_group("outer")
        adapter.begin_undo_group("inner")
        adapter.end_undo_group()
        adapter.end_undo_group()


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_suppress_nested_restores_correctly(self):
        """Outer suppress context must still suppress after inner exits."""
        adapter = MockStageAdapter()
        events = []
        sub = adapter.subscribe_changes(lambda e: events.append(e))  # noqa: F841
        geometry = adapter.get_children(adapter.get_root())[0]

        with adapter.suppress_change_notifications():
            with adapter.suppress_change_notifications():
                adapter.set_visibility(geometry, False)
            adapter.set_visibility(geometry, True)  # still suppressed

        adapter.set_visibility(geometry, False)  # now fires
        assert len(events) == 1

    def test_rename_item_with_deep_children(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        adapter.add_child("/World/Geometry/Ground", "Detail", "Mesh")
        geometry = adapter.get_children(root)[0]
        adapter.rename(geometry, "Geo")
        detail = adapter.get_item_at_path("/World/Geo/Ground/Detail")
        assert detail is not None

    def test_is_concrete(self):
        """MockStageAdapter must be fully concrete — no remaining abstract methods."""
        adapter = MockStageAdapter()
        assert not hasattr(adapter, "__abstractmethods__") or not adapter.__abstractmethods__

    def test_fire_change_suppressed(self):
        adapter = MockStageAdapter()
        events = []
        sub = adapter.subscribe_changes(lambda e: events.append(e))  # noqa: F841
        with adapter.suppress_change_notifications():
            adapter.fire_change(["/World"])
        assert len(events) == 0

    def test_reparent_path_update_preserves_grandchildren(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        geometry = adapter.get_children(root)[0]
        lights = adapter.get_children(root)[1]
        # Move entire Geometry subtree under Lights
        adapter.reparent([geometry], lights, ReparentPosition.CHILD)
        ground = adapter.get_item_at_path("/World/Lights/Geometry/Ground")
        assert ground is not None

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for HierarchyItem and HierarchyModel.

Runs headlessly — no visible window needed.
"""

from __future__ import annotations

import pytest
from ovui_data_adapters.common import BadgeFlags, ItemFlags

from ovui_widgets.common.testing.mock_stage import MockStageAdapter
from ovui_widgets.stage.hierarchy_model import HierarchyItem, HierarchyModel


@pytest.fixture
def adapter():
    return MockStageAdapter()


@pytest.fixture
def model(adapter):
    return HierarchyModel(adapter)


class TestRootAccess:
    def test_get_item_children_none_returns_list(self, model):
        roots = model.get_item_children(None)
        assert isinstance(roots, list)

    def test_get_item_children_none_returns_one_item(self, model):
        roots = model.get_item_children(None)
        assert len(roots) == 1

    def test_root_is_hierarchy_item(self, model):
        roots = model.get_item_children(None)
        assert isinstance(roots[0], HierarchyItem)

    def test_root_name_model_returns_world(self, model):
        roots = model.get_item_children(None)
        name_model = model.get_item_value_model(roots[0], 0)
        assert name_model.get_value_as_string() == "World"

    def test_root_adapter_item_is_world(self, model):
        roots = model.get_item_children(None)
        assert roots[0].adapter_item.name == "World"

    def test_root_parent_is_none(self, model):
        roots = model.get_item_children(None)
        assert roots[0].parent is None


class TestChildren:
    def test_root_children_count(self, model):
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        assert len(children) == 3

    def test_root_children_are_hierarchy_items(self, model):
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        assert all(isinstance(c, HierarchyItem) for c in children)

    def test_root_children_names(self, model):
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        names = [model.get_item_value_model(c, 0).get_value_as_string() for c in children]
        assert names == ["Geometry", "Lights", "Camera"]

    def test_geometry_grandchildren_count(self, model):
        root = model.get_item_children(None)[0]
        geometry = model.get_item_children(root)[0]
        grandchildren = model.get_item_children(geometry)
        assert len(grandchildren) == 3

    def test_geometry_grandchildren_names(self, model):
        root = model.get_item_children(None)[0]
        geometry = model.get_item_children(root)[0]
        grandchildren = model.get_item_children(geometry)
        names = [model.get_item_value_model(gc, 0).get_value_as_string() for gc in grandchildren]
        assert names == ["Ground", "Sphere", "Cube"]

    def test_lights_child_count(self, model):
        root = model.get_item_children(None)[0]
        lights = model.get_item_children(root)[1]
        lights_children = model.get_item_children(lights)
        assert len(lights_children) == 1

    def test_lights_child_name(self, model):
        root = model.get_item_children(None)[0]
        lights = model.get_item_children(root)[1]
        dome = model.get_item_children(lights)[0]
        assert model.get_item_value_model(dome, 0).get_value_as_string() == "DomeLight"

    def test_camera_has_no_children(self, model):
        root = model.get_item_children(None)[0]
        camera = model.get_item_children(root)[2]
        assert model.get_item_children(camera) == []

    def test_non_hierarchy_item_returns_empty_list(self, model):
        assert model.get_item_children("not an item") == []

    def test_non_hierarchy_item_object_returns_empty(self, model):
        assert model.get_item_children(object()) == []


class TestLazyLoading:
    def test_root_children_initially_none(self, model):
        root = model.get_item_children(None)[0]
        assert root._children is None

    def test_children_populated_after_access(self, model):
        root = model.get_item_children(None)[0]
        model.get_item_children(root)
        assert root._children is not None

    def test_second_access_returns_cached_children(self, model):
        root = model.get_item_children(None)[0]
        first = model.get_item_children(root)
        second = model.get_item_children(root)
        assert first is second

    def test_grandchildren_initially_none(self, model):
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        for child in children:
            assert child._children is None

    def test_name_model_initially_none(self, model):
        root = model.get_item_children(None)[0]
        assert root._name_model is None

    def test_name_model_populated_after_access(self, model):
        root = model.get_item_children(None)[0]
        model.get_item_value_model(root, 0)
        assert root._name_model is not None

    def test_name_model_cached_on_second_call(self, model):
        root = model.get_item_children(None)[0]
        m1 = model.get_item_value_model(root, 0)
        m2 = model.get_item_value_model(root, 0)
        assert m1 is m2


class TestValueModels:
    def test_value_model_count_is_three_for_item(self, model):
        root = model.get_item_children(None)[0]
        assert model.get_item_value_model_count(root) == 3

    def test_value_model_count_is_three_for_none(self, model):
        assert model.get_item_value_model_count(None) == 3

    def test_column_zero_returns_model(self, model):
        root = model.get_item_children(None)[0]
        vm = model.get_item_value_model(root, 0)
        assert vm is not None

    def test_column_zero_world_name(self, model):
        root = model.get_item_children(None)[0]
        vm = model.get_item_value_model(root, 0)
        assert vm.get_value_as_string() == "World"

    def test_column_one_returns_type_model(self, model):
        root = model.get_item_children(None)[0]
        assert model.get_item_value_model(root, 1) is not None

    def test_column_two_returns_visibility_model(self, model):
        root = model.get_item_children(None)[0]
        assert model.get_item_value_model(root, 2) is not None

    def test_non_hierarchy_item_returns_none(self, model):
        assert model.get_item_value_model(None, 0) is None

    def test_name_model_is_cached(self, model):
        root = model.get_item_children(None)[0]
        vm1 = model.get_item_value_model(root, 0)
        vm2 = model.get_item_value_model(root, 0)
        assert vm1 is vm2

    def test_each_child_has_correct_name(self, model):
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        expected = ["Geometry", "Lights", "Camera"]
        for child, exp_name in zip(children, expected):
            assert model.get_item_value_model(child, 0).get_value_as_string() == exp_name


class TestChangeNotifications:
    def test_fire_change_calls_item_changed(self, model, adapter):
        notified = []
        sub = model.subscribe_item_changed_fn(lambda m, i: notified.append(i))  # noqa: F841
        adapter.fire_change(["/World"])
        assert len(notified) > 0

    def test_fire_change_passes_none_item(self, model, adapter):
        notified = []
        sub = model.subscribe_item_changed_fn(lambda m, i: notified.append(i))  # noqa: F841
        adapter.fire_change(["/World"])
        assert None in notified

    def test_add_child_triggers_notification(self, model, adapter):
        notified = []
        sub = model.subscribe_item_changed_fn(lambda m, i: notified.append(i))  # noqa: F841
        adapter.add_child("/World", "NewPrim", "Mesh")
        assert len(notified) > 0

    def test_remove_triggers_notification(self, model, adapter):
        notified = []
        sub = model.subscribe_item_changed_fn(lambda m, i: notified.append(i))  # noqa: F841
        adapter.remove("/World/Camera")
        assert len(notified) > 0

    def test_after_change_children_reload(self, model, adapter):
        root = model.get_item_children(None)[0]
        # Load children first
        model.get_item_children(root)
        assert len(root._children) == 3
        # Add a child and invalidate
        adapter.add_child("/World", "Extra", "Mesh")
        model.invalidate_item(root)
        # Reload
        children = model.get_item_children(root)
        assert len(children) == 4


class TestPathCache:
    def test_path_cache_empty_initially(self, model):
        assert model._path_cache == {}

    def test_path_cache_populated_after_root_children(self, model):
        root = model.get_item_children(None)[0]
        model.get_item_children(root)
        assert len(model._path_cache) == 3

    def test_path_cache_has_expected_paths(self, model):
        root = model.get_item_children(None)[0]
        model.get_item_children(root)
        assert "/World/Geometry" in model._path_cache
        assert "/World/Lights" in model._path_cache
        assert "/World/Camera" in model._path_cache

    def test_path_cache_item_identity(self, model):
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        geometry_item = children[0]
        assert model._path_cache["/World/Geometry"] is geometry_item

    def test_path_cache_grows_with_grandchildren(self, model):
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        model.get_item_children(children[0])  # load Geometry children
        assert "/World/Geometry/Ground" in model._path_cache
        assert "/World/Geometry/Sphere" in model._path_cache
        assert "/World/Geometry/Cube" in model._path_cache


class TestInvalidateItem:
    def test_invalidate_clears_children(self, model):
        root = model.get_item_children(None)[0]
        model.get_item_children(root)
        assert root._children is not None
        model.invalidate_item(root)
        assert root._children is None

    def test_invalidate_children_reload_on_next_access(self, model):
        root = model.get_item_children(None)[0]
        model.get_item_children(root)
        model.invalidate_item(root)
        children = model.get_item_children(root)
        assert len(children) == 3

    def test_invalidate_emits_notification(self, model):
        root = model.get_item_children(None)[0]
        model.get_item_children(root)
        notified = []
        sub = model.subscribe_item_changed_fn(lambda m, i: notified.append(i))  # noqa: F841
        model.invalidate_item(root)
        assert len(notified) > 0


class TestParentLinks:
    def test_children_parent_is_root(self, model):
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        for child in children:
            assert child.parent is root

    def test_grandchildren_parent_is_geometry(self, model):
        root = model.get_item_children(None)[0]
        geometry = model.get_item_children(root)[0]
        grandchildren = model.get_item_children(geometry)
        for gc in grandchildren:
            assert gc.parent is geometry

    def test_parent_chain_root_to_grandchild(self, model):
        root = model.get_item_children(None)[0]
        geometry = model.get_item_children(root)[0]
        ground = model.get_item_children(geometry)[0]
        assert ground.parent is geometry
        assert ground.parent.parent is root
        assert root.parent is None


class TestSetAdapter:
    def test_set_adapter_swaps_root(self):
        adapter1 = MockStageAdapter()
        adapter2 = MockStageAdapter()
        adapter2.add_child("/World", "UniqueChild", "Mesh")
        model = HierarchyModel(adapter1)
        model.set_adapter(adapter2)
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        names = [model.get_item_value_model(c, 0).get_value_as_string() for c in children]
        assert "UniqueChild" in names

    def test_set_adapter_clears_path_cache(self):
        adapter1 = MockStageAdapter()
        adapter2 = MockStageAdapter()
        model = HierarchyModel(adapter1)
        root = model.get_item_children(None)[0]
        model.get_item_children(root)
        assert len(model._path_cache) > 0
        model.set_adapter(adapter2)
        assert model._path_cache == {}

    def test_set_adapter_root_from_new_adapter(self):
        adapter1 = MockStageAdapter()
        adapter2 = MockStageAdapter()
        model = HierarchyModel(adapter1)
        model.set_adapter(adapter2)
        root = model.get_item_children(None)[0]
        assert root.adapter_item is adapter2.get_root()

    def test_set_adapter_old_subscription_cancelled(self):
        adapter1 = MockStageAdapter()
        adapter2 = MockStageAdapter()
        model = HierarchyModel(adapter1)
        notified = []
        sub = model.subscribe_item_changed_fn(lambda m, i: notified.append(i))  # noqa: F841
        model.set_adapter(adapter2)
        notified.clear()
        adapter1.fire_change(["/World"])
        assert len(notified) == 0

    def test_set_adapter_new_subscription_active(self):
        adapter1 = MockStageAdapter()
        adapter2 = MockStageAdapter()
        model = HierarchyModel(adapter1)
        model.set_adapter(adapter2)
        notified = []
        sub = model.subscribe_item_changed_fn(lambda m, i: notified.append(i))  # noqa: F841
        adapter2.fire_change(["/World"])
        assert len(notified) > 0

    def test_set_adapter_clears_selected_items(self):
        adapter1 = MockStageAdapter()
        adapter2 = MockStageAdapter()
        model = HierarchyModel(adapter1)
        root = model.get_item_children(None)[0]
        model._selected_items = [root]
        model.set_adapter(adapter2)
        assert model._selected_items == []


class TestCanItemHaveChildren:
    def test_root_can_have_children(self, model):
        root = model.get_item_children(None)[0]
        assert model.can_item_have_children(root) is True

    def test_geometry_can_have_children(self, model):
        root = model.get_item_children(None)[0]
        geometry = model.get_item_children(root)[0]
        assert model.can_item_have_children(geometry) is True

    def test_camera_cannot_have_children(self, model):
        root = model.get_item_children(None)[0]
        camera = model.get_item_children(root)[2]
        assert model.can_item_have_children(camera) is False

    def test_non_hierarchy_item_none_returns_false(self, model):
        assert model.can_item_have_children(None) is False

    def test_non_hierarchy_item_string_returns_false(self, model):
        assert model.can_item_have_children("string") is False

    def test_non_hierarchy_item_object_returns_false(self, model):
        assert model.can_item_have_children(object()) is False


class TestColumnTypeValues:
    def test_root_type_is_xform(self, model):
        root = model.get_item_children(None)[0]
        vm = model.get_item_value_model(root, 1)
        assert vm.get_value_as_string() == "Xform"

    def test_geometry_type_is_xform(self, model):
        root = model.get_item_children(None)[0]
        geometry = model.get_item_children(root)[0]
        vm = model.get_item_value_model(geometry, 1)
        assert vm.get_value_as_string() == "Xform"

    def test_ground_type_is_mesh(self, model):
        root = model.get_item_children(None)[0]
        geometry = model.get_item_children(root)[0]
        ground = model.get_item_children(geometry)[0]
        vm = model.get_item_value_model(ground, 1)
        assert vm.get_value_as_string() == "Mesh"

    def test_dome_light_type_is_light(self, model):
        root = model.get_item_children(None)[0]
        lights = model.get_item_children(root)[1]
        dome = model.get_item_children(lights)[0]
        vm = model.get_item_value_model(dome, 1)
        assert vm.get_value_as_string() == "Light"

    def test_camera_type_is_camera(self, model):
        root = model.get_item_children(None)[0]
        camera = model.get_item_children(root)[2]
        vm = model.get_item_value_model(camera, 1)
        assert vm.get_value_as_string() == "Camera"

    def test_type_model_is_cached(self, model):
        root = model.get_item_children(None)[0]
        vm1 = model.get_item_value_model(root, 1)
        vm2 = model.get_item_value_model(root, 1)
        assert vm1 is vm2


class TestColumnVisibilityValues:
    # Column 2 now returns VisibilityValueModel: the checkbox
    # is True when the item is *invisible* (eye closed).
    def test_visible_item_reads_false(self, model):
        root = model.get_item_children(None)[0]
        vm = model.get_item_value_model(root, 2)
        assert vm.get_value_as_bool() is False

    def test_invisible_item_reads_true(self):
        adapter = MockStageAdapter()
        adapter._root.visible = False
        model = HierarchyModel(adapter)
        root = model.get_item_children(None)[0]
        vm = model.get_item_value_model(root, 2)
        assert vm.get_value_as_bool() is True

    def test_inherited_invisible_reads_true(self):
        adapter = MockStageAdapter()
        adapter._root.visible = False
        model = HierarchyModel(adapter)
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        # Children inherit invisible state from root → checkbox checked (hidden).
        vm = model.get_item_value_model(children[0], 2)
        assert vm.get_value_as_bool() is True

    def test_visibility_model_is_cached(self, model):
        root = model.get_item_children(None)[0]
        vm1 = model.get_item_value_model(root, 2)
        vm2 = model.get_item_value_model(root, 2)
        assert vm1 is vm2

    def test_column_beyond_range_returns_none(self, model):
        root = model.get_item_children(None)[0]
        assert model.get_item_value_model(root, 3) is None


class TestGetSelectedPaths:
    def test_empty_initially(self, model):
        assert model.get_selected_paths() == []

    def test_returns_path_of_selected_item(self, model):
        root = model.get_item_children(None)[0]
        model._selected_items = [root]
        paths = model.get_selected_paths()
        assert "/World" in paths

    def test_returns_multiple_paths(self, model):
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        model._selected_items = list(children[:2])
        paths = model.get_selected_paths()
        assert len(paths) == 2
        assert "/World/Geometry" in paths
        assert "/World/Lights" in paths

    def test_returns_list_type(self, model):
        assert isinstance(model.get_selected_paths(), list)


class TestExpandedPaths:
    def test_empty_initially(self, model):
        assert model._expanded_paths == set()

    def test_set_expanded_true_adds_path(self, model):
        model._set_path_expanded("/World", True)
        assert "/World" in model._expanded_paths

    def test_set_expanded_false_removes_path(self, model):
        model._set_path_expanded("/World", True)
        model._set_path_expanded("/World", False)
        assert "/World" not in model._expanded_paths

    def test_set_expanded_false_nonexistent_is_safe(self, model):
        model._set_path_expanded("/nonexistent", False)
        assert "/nonexistent" not in model._expanded_paths

    def test_multiple_paths_tracked(self, model):
        model._set_path_expanded("/World", True)
        model._set_path_expanded("/World/Geometry", True)
        assert "/World" in model._expanded_paths
        assert "/World/Geometry" in model._expanded_paths

    def test_collapse_removes_only_that_path(self, model):
        model._set_path_expanded("/World", True)
        model._set_path_expanded("/World/Geometry", True)
        model._set_path_expanded("/World/Geometry", False)
        assert "/World" in model._expanded_paths
        assert "/World/Geometry" not in model._expanded_paths


class TestSetFilterInternal:
    def test_set_filter_clears_path_cache(self, model, adapter):
        root = model.get_item_children(None)[0]
        model.get_item_children(root)
        assert len(model._path_cache) > 0
        model.set_filter("Sphere")
        assert model._path_cache == {}

    def test_set_filter_resets_root_children(self, model, adapter):
        root = model.get_item_children(None)[0]
        model.get_item_children(root)
        assert root._children is not None
        model.set_filter("Sphere")
        assert root._children is None

    def test_clear_filter_clears_path_cache(self, model, adapter):
        root = model.get_item_children(None)[0]
        model.get_item_children(root)
        model.set_filter("")
        assert model._path_cache == {}

    def test_set_filter_notifies_model(self, model, adapter):
        notified = []
        sub = model.subscribe_item_changed_fn(lambda m, i: notified.append(i))  # noqa: F841
        model.set_filter("Sphere")
        assert len(notified) > 0

    def test_clear_filter_notifies_model(self, model, adapter):
        model.set_filter("Sphere")
        notified = []
        sub = model.subscribe_item_changed_fn(lambda m, i: notified.append(i))  # noqa: F841
        model.set_filter("")
        assert len(notified) > 0


class TestEmptyHierarchy:
    def test_root_with_no_children_returns_empty_list(self):
        adapter = MockStageAdapter()
        adapter._root.children = []
        model = HierarchyModel(adapter)
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        assert children == []

    def test_empty_root_path_cache_stays_empty(self):
        adapter = MockStageAdapter()
        adapter._root.children = []
        model = HierarchyModel(adapter)
        root = model.get_item_children(None)[0]
        model.get_item_children(root)
        assert model._path_cache == {}

    def test_empty_root_can_have_children_false(self):
        adapter = MockStageAdapter()
        adapter._root.children = []
        model = HierarchyModel(adapter)
        root = model.get_item_children(None)[0]
        assert model.can_item_have_children(root) is False

    def test_single_child_only(self):
        adapter = MockStageAdapter()
        adapter._root.children = []
        adapter.add_child("/World", "OnlyChild", "Mesh")
        model = HierarchyModel(adapter)
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        assert len(children) == 1
        assert model.get_item_value_model(children[0], 0).get_value_as_string() == "OnlyChild"


class TestHierarchyItemFlagCacheInit:
    def test_new_item_is_dirty(self, adapter):
        item = HierarchyItem(adapter.get_root())
        assert item._flags_dirty is True

    def test_new_item_item_flags_is_none(self, adapter):
        item = HierarchyItem(adapter.get_root())
        assert item._item_flags == ItemFlags.NONE

    def test_new_item_badge_flags_is_none(self, adapter):
        item = HierarchyItem(adapter.get_root())
        assert item._badge_flags == BadgeFlags.NONE

    def test_new_item_filtered_is_false(self, adapter):
        item = HierarchyItem(adapter.get_root())
        assert item.filtered is False

    def test_new_item_child_filtered_is_false(self, adapter):
        item = HierarchyItem(adapter.get_root())
        assert item.child_filtered is False


class TestHierarchyItemMarkDirty:
    def test_mark_dirty_sets_flag(self, adapter):
        item = HierarchyItem(adapter.get_root())
        item._flags_dirty = False
        item.mark_dirty()
        assert item._flags_dirty is True

    def test_mark_dirty_is_idempotent(self, adapter):
        item = HierarchyItem(adapter.get_root())
        item.mark_dirty()
        item.mark_dirty()
        assert item._flags_dirty is True

    def test_mark_dirty_does_not_read_adapter(self, adapter):
        # mark_dirty must be cheap — never talk to the adapter.
        item = HierarchyItem(adapter.get_root())
        call_count = {"n": 0}
        orig = adapter.get_item_flags

        def counting(x):
            call_count["n"] += 1
            return orig(x)

        adapter.get_item_flags = counting  # type: ignore[assignment]
        item.mark_dirty()
        assert call_count["n"] == 0


class TestHierarchyItemRefreshFlags:
    def test_first_access_reads_adapter(self, adapter):
        item = HierarchyItem(adapter.get_root())
        item._refresh_flags(adapter)
        assert item._flags_dirty is False

    def test_second_access_skips_adapter_when_clean(self, adapter):
        item = HierarchyItem(adapter.get_root())
        item._refresh_flags(adapter)
        call_count = {"n": 0}
        orig = adapter.get_item_flags

        def counting(x):
            call_count["n"] += 1
            return orig(x)

        adapter.get_item_flags = counting  # type: ignore[assignment]
        item._refresh_flags(adapter)
        assert call_count["n"] == 0

    def test_refresh_after_mark_dirty_rereads_adapter(self, adapter):
        adapter.set_default("/World/Camera")
        camera = adapter.get_item_at_path("/World/Camera")
        item = HierarchyItem(camera)
        item._refresh_flags(adapter)
        assert item.is_default(adapter) is True


class TestHierarchyItemFlagAccessors:
    def test_item_flags_returns_adapter_value(self, adapter):
        adapter.set_item_flags("/World/Camera", ItemFlags.IS_INACTIVE)
        camera = adapter.get_item_at_path("/World/Camera")
        item = HierarchyItem(camera)
        assert item.item_flags(adapter) == ItemFlags.IS_INACTIVE

    def test_badge_flags_returns_adapter_value(self, adapter):
        adapter.set_badge_flags(
            "/World/Camera", BadgeFlags.REFERENCE | BadgeFlags.PAYLOAD,
        )
        camera = adapter.get_item_at_path("/World/Camera")
        item = HierarchyItem(camera)
        assert item.badge_flags(adapter) == BadgeFlags.REFERENCE | BadgeFlags.PAYLOAD

    def test_is_default_true(self, adapter):
        adapter.set_default("/World/Camera")
        camera = adapter.get_item_at_path("/World/Camera")
        item = HierarchyItem(camera)
        assert item.is_default(adapter) is True

    def test_is_default_false_by_default(self, adapter):
        item = HierarchyItem(adapter.get_root())
        assert item.is_default(adapter) is False

    def test_is_inactive_true(self, adapter):
        adapter.set_item_flags("/World/Camera", ItemFlags.IS_INACTIVE)
        camera = adapter.get_item_at_path("/World/Camera")
        item = HierarchyItem(camera)
        assert item.is_inactive(adapter) is True

    def test_is_instance_proxy_true(self, adapter):
        adapter.set_item_flags("/World/Camera", ItemFlags.IS_INSTANCE_PROXY)
        camera = adapter.get_item_at_path("/World/Camera")
        item = HierarchyItem(camera)
        assert item.is_instance_proxy(adapter) is True

    def test_is_class_item_true(self, adapter):
        adapter.set_item_flags("/World/Camera", ItemFlags.IS_CLASS)
        camera = adapter.get_item_at_path("/World/Camera")
        item = HierarchyItem(camera)
        assert item.is_class_item(adapter) is True

    def test_is_abstract_true(self, adapter):
        adapter.set_item_flags("/World/Camera", ItemFlags.IS_ABSTRACT)
        camera = adapter.get_item_at_path("/World/Camera")
        item = HierarchyItem(camera)
        assert item.is_abstract(adapter) is True

    def test_accessor_respects_multiple_flags(self, adapter):
        combined = ItemFlags.IS_DEFAULT_PRIM | ItemFlags.IS_INACTIVE
        adapter.set_item_flags("/World/Camera", combined)
        camera = adapter.get_item_at_path("/World/Camera")
        item = HierarchyItem(camera)
        assert item.is_default(adapter) is True
        assert item.is_inactive(adapter) is True
        assert item.is_abstract(adapter) is False

    def test_accessor_caches_first_result(self, adapter):
        adapter.set_default("/World/Camera")
        camera = adapter.get_item_at_path("/World/Camera")
        item = HierarchyItem(camera)
        assert item.is_default(adapter) is True
        # Swap the override: without mark_dirty, the cached value should persist.
        del adapter._item_flags_overrides["/World/Camera"]
        assert item.is_default(adapter) is True


class TestHierarchyModelMarkDirtyOnChange:
    def test_adapter_change_marks_root_dirty(self, model, adapter):
        root = model.get_item_children(None)[0]
        root._refresh_flags(adapter)
        assert root._flags_dirty is False
        adapter.set_default("/World")
        assert root._flags_dirty is True

    def test_adapter_change_marks_cached_children_dirty(self, model, adapter):
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        for child in children:
            child._refresh_flags(adapter)
        adapter.fire_change(["/World"])
        for child in children:
            assert child._flags_dirty is True

    def test_adapter_change_does_not_eagerly_hit_adapter(self, model, adapter):
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        for child in children:
            child._refresh_flags(adapter)
        call_count = {"n": 0}
        orig = adapter.get_item_flags

        def counting(x):
            call_count["n"] += 1
            return orig(x)

        adapter.get_item_flags = counting  # type: ignore[assignment]
        adapter.fire_change(["/World"])
        # Reset only sets the dirty bit; it must not re-read the adapter.
        assert call_count["n"] == 0

    def test_next_accessor_rereads_after_change(self, model, adapter):
        root = model.get_item_children(None)[0]
        assert root.is_default(adapter) is False
        adapter.set_default("/World")
        assert root.is_default(adapter) is True

    def test_invalidate_item_marks_item_dirty(self, model, adapter):
        root = model.get_item_children(None)[0]
        root._refresh_flags(adapter)
        assert root._flags_dirty is False
        model.invalidate_item(root)
        assert root._flags_dirty is True


class TestMockStageAdapterSetDefault:
    def test_set_default_stores_flag(self):
        adapter = MockStageAdapter()
        adapter.set_default("/World/Camera")
        camera = adapter.get_item_at_path("/World/Camera")
        assert bool(adapter.get_item_flags(camera) & ItemFlags.IS_DEFAULT_PRIM)

    def test_set_default_on_missing_path_raises(self):
        adapter = MockStageAdapter()
        with pytest.raises(ValueError):
            adapter.set_default("/Nope")

    def test_set_default_clears_previous(self):
        adapter = MockStageAdapter()
        adapter.set_default("/World/Camera")
        adapter.set_default("/World/Geometry")
        camera = adapter.get_item_at_path("/World/Camera")
        geometry = adapter.get_item_at_path("/World/Geometry")
        assert not (adapter.get_item_flags(camera) & ItemFlags.IS_DEFAULT_PRIM)
        assert bool(adapter.get_item_flags(geometry) & ItemFlags.IS_DEFAULT_PRIM)

    def test_set_default_preserves_other_flags(self):
        adapter = MockStageAdapter()
        adapter.set_item_flags("/World/Camera", ItemFlags.IS_INACTIVE)
        adapter.set_default("/World/Camera")
        camera = adapter.get_item_at_path("/World/Camera")
        flags = adapter.get_item_flags(camera)
        assert bool(flags & ItemFlags.IS_DEFAULT_PRIM)
        assert bool(flags & ItemFlags.IS_INACTIVE)

    def test_set_default_fires_change_event(self):
        adapter = MockStageAdapter()
        events = []
        sub = adapter.subscribe_changes(lambda e: events.append(e))  # noqa: F841
        adapter.set_default("/World/Camera")
        assert len(events) == 1
        assert "/World/Camera" in events[0].changed_paths

    def test_set_item_flags_none_clears_override(self):
        adapter = MockStageAdapter()
        adapter.set_item_flags("/World/Camera", ItemFlags.IS_INACTIVE)
        adapter.set_item_flags("/World/Camera", ItemFlags.NONE)
        assert "/World/Camera" not in adapter._item_flags_overrides

    def test_set_badge_flags_round_trip(self):
        adapter = MockStageAdapter()
        adapter.set_badge_flags("/World/Camera", BadgeFlags.REFERENCE)
        camera = adapter.get_item_at_path("/World/Camera")
        assert adapter.get_badge_flags(camera) == BadgeFlags.REFERENCE

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for expand/collapse persistence across adapter change events.

Feature: HierarchyModel._expanded_paths tracks which paths are expanded so
that after a tree rebuild (adapter change event) the state can be restored.
"""

import pytest

from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.stage.hierarchy_model import HierarchyModel


@pytest.fixture
def adapter():
    return MockStageAdapter()


@pytest.fixture
def model(adapter):
    return HierarchyModel(adapter)


class TestExpandedPathsSet:
    def test_expanded_paths_empty_initially(self, model):
        assert model._expanded_paths == set()

    def test_set_path_expanded_adds_to_set(self, model, adapter):
        root_path = adapter.get_item_path(adapter.get_root())
        model._set_path_expanded(root_path, True)
        assert root_path in model._expanded_paths

    def test_set_path_collapsed_removes_from_set(self, model, adapter):
        root_path = adapter.get_item_path(adapter.get_root())
        model._set_path_expanded(root_path, True)
        model._set_path_expanded(root_path, False)
        assert root_path not in model._expanded_paths

    def test_collapse_nonexistent_path_is_noop(self, model):
        model._set_path_expanded("/World/Nonexistent", False)
        assert "/World/Nonexistent" not in model._expanded_paths

    def test_multiple_paths_tracked_independently(self, model, adapter):
        root_path = adapter.get_item_path(adapter.get_root())
        child_path = "/World/Geometry"
        model._set_path_expanded(root_path, True)
        model._set_path_expanded(child_path, True)
        assert root_path in model._expanded_paths
        assert child_path in model._expanded_paths

    def test_collapse_one_leaves_other_intact(self, model, adapter):
        root_path = adapter.get_item_path(adapter.get_root())
        child_path = "/World/Geometry"
        model._set_path_expanded(root_path, True)
        model._set_path_expanded(child_path, True)
        model._set_path_expanded(root_path, False)
        assert root_path not in model._expanded_paths
        assert child_path in model._expanded_paths


class TestPersistenceAcrossAdapterChange:
    def test_expanded_path_survives_adapter_change(self, model, adapter):
        root_path = adapter.get_item_path(adapter.get_root())
        model._set_path_expanded(root_path, True)
        adapter.fire_change([root_path])
        assert root_path in model._expanded_paths

    def test_multiple_paths_survive_adapter_change(self, model, adapter):
        root_path = adapter.get_item_path(adapter.get_root())
        geo_path = "/World/Geometry"
        model._set_path_expanded(root_path, True)
        model._set_path_expanded(geo_path, True)
        adapter.fire_change([root_path])
        assert root_path in model._expanded_paths
        assert geo_path in model._expanded_paths

    def test_collapsed_path_absent_after_adapter_change(self, model, adapter):
        root_path = adapter.get_item_path(adapter.get_root())
        model._set_path_expanded(root_path, True)
        model._set_path_expanded(root_path, False)
        adapter.fire_change([root_path])
        assert root_path not in model._expanded_paths

    def test_adapter_change_clears_children_for_rebuild(self, model, adapter):
        """Adapter change triggers a full rebuild (children cleared)."""
        root = model.get_item_children(None)[0]
        model.get_item_children(root)  # Load children
        assert root._children is not None
        adapter.fire_change(["/World"])
        assert root._children is None

    def test_adapter_change_preserves_valid_path_cache(self, model, adapter):
        """Adapter change keeps still-valid cache entries so the TreeView's
        object-identity-keyed expansion set survives the rebuild."""
        root = model.get_item_children(None)[0]
        children = list(model.get_item_children(root))
        assert len(model._path_cache) > 0
        sample_path = adapter.get_item_path(children[0].adapter_item)
        pre_item = model._path_cache[sample_path]
        adapter.fire_change(["/World"])
        assert sample_path in model._path_cache
        assert model._path_cache[sample_path] is pre_item

    def test_adapter_change_prunes_deleted_paths(self, model, adapter):
        """Paths the adapter no longer knows about get pruned from the cache."""
        root = model.get_item_children(None)[0]
        list(model.get_item_children(root))  # populate with /World/Geometry etc.
        # Insert a fake stale entry that the adapter does not resolve.
        from ovwidgets.stage.widget.hierarchy_model import HierarchyItem
        fake = HierarchyItem(adapter_item=None, parent=None)
        model._path_cache["/World/DeletedGhost"] = fake
        adapter.fire_change(["/World"])
        assert "/World/DeletedGhost" not in model._path_cache


class TestNewItemsStartCollapsed:
    def test_new_child_path_not_in_expanded(self, model, adapter):
        adapter.add_child("/World", "NewMesh", "Mesh")
        assert "/World/NewMesh" not in model._expanded_paths

    def test_existing_children_not_auto_expanded(self, model, adapter):
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        for child in children:
            path = adapter.get_item_path(child.adapter_item)
            assert path not in model._expanded_paths

    def test_set_expanded_then_add_child_doesnt_expand_new(self, model, adapter):
        root_path = adapter.get_item_path(adapter.get_root())
        model._set_path_expanded(root_path, True)
        adapter.add_child("/World", "NewMesh2", "Mesh")
        assert "/World/NewMesh2" not in model._expanded_paths


class TestResolvePath:
    """``HierarchyModel.resolve_path`` walks from root, lazy-loading along
    the way so callers can address never-rendered paths."""

    def test_resolve_root_returns_root(self, model, adapter):
        root_path = adapter.get_item_path(adapter.get_root())
        assert model.resolve_path(root_path) is model._root

    def test_resolve_loads_child_into_cache(self, model, adapter):
        # Fresh model: nothing in the cache yet.
        assert "/World/Geometry" not in model._path_cache
        item = model.resolve_path("/World/Geometry")
        assert item is not None
        assert model._path_cache["/World/Geometry"] is item

    def test_resolve_deep_path_walks_ancestors(self, model, adapter):
        # Cube lives two levels under World — both ancestor items must end
        # up in the cache after the walk.
        item = model.resolve_path("/World/Geometry/Cube")
        assert item is not None
        assert "/World/Geometry" in model._path_cache
        assert "/World/Geometry/Cube" in model._path_cache

    def test_resolve_unknown_path_returns_none(self, model, adapter):
        assert model.resolve_path("/World/DoesNotExist") is None

    def test_resolve_reuses_cached_item(self, model, adapter):
        first = model.resolve_path("/World/Geometry")
        second = model.resolve_path("/World/Geometry")
        assert first is second


class TestExpansionSurvivesMutation:
    """After an adapter change, items reachable from paths the user had
    expanded are still expanded in the TreeView — in practice that means
    the HierarchyItem at those paths retains its object identity so the
    TreeView's own expansion set stays valid."""

    def test_item_identity_preserved_across_change(self, model, adapter):
        root = model.get_item_children(None)[0]
        children_before = list(model.get_item_children(root))
        ids_before = {
            adapter.get_item_path(c.adapter_item): id(c) for c in children_before
        }
        adapter.fire_change(["/World"])
        children_after = list(model.get_item_children(root))
        ids_after = {
            adapter.get_item_path(c.adapter_item): id(c) for c in children_after
        }
        # Every path that existed before + after the change keeps the
        # same HierarchyItem object.
        for p, id_before in ids_before.items():
            if p in ids_after:
                assert ids_after[p] == id_before, f"{p} re-created"

    def test_new_child_gets_fresh_item(self, model, adapter):
        root = model.get_item_children(None)[0]
        list(model.get_item_children(root))  # populate cache
        adapter.add_child("/World", "AfterChange", "Xform")
        children = list(model.get_item_children(root))
        paths = [adapter.get_item_path(c.adapter_item) for c in children]
        assert "/World/AfterChange" in paths

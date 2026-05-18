# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for lazy prim loading in HierarchyModel — OvGear Step 65.

Covers: threshold constant, small-tree full load, large-tree truncation,
_get_children_count, load_more_children batching, _pending_expand_paths
lifecycle, filter bypass, and performance.
"""

import time

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_model(prim_count: int):
    from ovwidgets.common.testing.mock_stage import MockStageAdapter
    from ovwidgets.stage.hierarchy_model import HierarchyModel
    adapter = MockStageAdapter(prim_count=prim_count)
    return HierarchyModel(adapter), adapter


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_threshold_exists(self):
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        assert hasattr(HierarchyModel, "PRIM_EXPAND_THRESHOLD")

    def test_threshold_value(self):
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        assert HierarchyModel.PRIM_EXPAND_THRESHOLD == 10_000

    def test_batch_size_exists(self):
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        assert hasattr(HierarchyModel, "PRIM_LAZY_BATCH_SIZE")

    def test_batch_size_value(self):
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        assert HierarchyModel.PRIM_LAZY_BATCH_SIZE == 100

    def test_batch_size_positive(self):
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        assert HierarchyModel.PRIM_LAZY_BATCH_SIZE > 0

    def test_threshold_greater_than_batch(self):
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        assert HierarchyModel.PRIM_EXPAND_THRESHOLD > HierarchyModel.PRIM_LAZY_BATCH_SIZE


# ---------------------------------------------------------------------------
# Small tree — all children returned immediately
# ---------------------------------------------------------------------------

class TestSmallTree:
    def test_small_tree_returns_all_children(self):
        model, _ = _make_model(50)
        root_item = model.get_item_children(None)[0]
        children = model.get_item_children(root_item)
        assert len(children) == 50

    def test_small_tree_no_pending(self):
        model, adapter = _make_model(50)
        root_item = model.get_item_children(None)[0]
        model.get_item_children(root_item)
        root_path = adapter.get_item_path(adapter.get_root())
        assert root_path not in model._pending_expand_paths

    def test_pending_empty_after_small_tree(self):
        model, _ = _make_model(100)
        root_item = model.get_item_children(None)[0]
        model.get_item_children(root_item)
        assert len(model._pending_expand_paths) == 0

    def test_just_below_threshold_returns_all(self):
        model, _ = _make_model(9_999)
        root_item = model.get_item_children(None)[0]
        children = model.get_item_children(root_item)
        assert len(children) == 9_999
        assert len(model._pending_expand_paths) == 0

    def test_exactly_at_threshold_returns_all(self):
        model, _ = _make_model(10_000)
        root_item = model.get_item_children(None)[0]
        children = model.get_item_children(root_item)
        assert len(children) == 10_000
        assert len(model._pending_expand_paths) == 0


# ---------------------------------------------------------------------------
# Large tree — truncation to first batch
# ---------------------------------------------------------------------------

class TestLargeTree:
    def test_large_tree_returns_batch_size(self):
        model, _ = _make_model(15_000)
        root_item = model.get_item_children(None)[0]
        children = model.get_item_children(root_item)
        assert len(children) == 100

    def test_large_tree_adds_to_pending(self):
        model, adapter = _make_model(15_000)
        root_item = model.get_item_children(None)[0]
        model.get_item_children(root_item)
        root_path = adapter.get_item_path(adapter.get_root())
        assert root_path in model._pending_expand_paths

    def test_one_above_threshold_triggers_lazy(self):
        model, _ = _make_model(10_001)
        root_item = model.get_item_children(None)[0]
        children = model.get_item_children(root_item)
        assert len(children) == 100
        assert len(model._pending_expand_paths) == 1

    def test_large_tree_children_are_hierarchy_items(self):
        from ovwidgets.stage.hierarchy_model import HierarchyItem
        model, _ = _make_model(15_000)
        root_item = model.get_item_children(None)[0]
        children = model.get_item_children(root_item)
        assert all(isinstance(c, HierarchyItem) for c in children)

    def test_large_tree_children_cached_on_second_call(self):
        model, _ = _make_model(15_000)
        root_item = model.get_item_children(None)[0]
        c1 = model.get_item_children(root_item)
        c2 = model.get_item_children(root_item)
        assert c1 is c2

    def test_children_have_correct_parents(self):
        model, _ = _make_model(15_000)
        root_item = model.get_item_children(None)[0]
        children = model.get_item_children(root_item)
        assert all(c.parent is root_item for c in children)


# ---------------------------------------------------------------------------
# _get_children_count
# ---------------------------------------------------------------------------

class TestGetChildrenCount:
    def test_count_matches_total(self):
        model, _ = _make_model(200)
        root_item = model.get_item_children(None)[0]
        assert model._get_children_count(root_item) == 200

    def test_count_without_loading_children(self):
        model, _ = _make_model(15_000)
        root_item = model.get_item_children(None)[0]
        assert root_item._children is None
        count = model._get_children_count(root_item)
        assert count == 15_000
        assert root_item._children is None  # count must NOT materialise items

    def test_count_small_tree(self):
        model, _ = _make_model(7)
        root_item = model.get_item_children(None)[0]
        assert model._get_children_count(root_item) == 7

    def test_count_large_tree(self):
        model, _ = _make_model(10_001)
        root_item = model.get_item_children(None)[0]
        assert model._get_children_count(root_item) == 10_001

    def test_count_callable(self):
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        assert callable(HierarchyModel._get_children_count)


# ---------------------------------------------------------------------------
# load_more_children
# ---------------------------------------------------------------------------

class TestLoadMoreChildren:
    def test_load_more_extends_children(self):
        model, _ = _make_model(15_000)
        root_item = model.get_item_children(None)[0]
        model.get_item_children(root_item)  # loads first 100
        added = model.load_more_children(root_item)
        assert added == 100
        assert len(root_item._children) == 200

    def test_load_more_returns_zero_not_pending(self):
        model, _ = _make_model(50)
        root_item = model.get_item_children(None)[0]
        model.get_item_children(root_item)
        assert model.load_more_children(root_item) == 0

    def test_load_more_sequential_batches(self):
        model, _ = _make_model(15_000)
        root_item = model.get_item_children(None)[0]
        model.get_item_children(root_item)  # 100
        model.load_more_children(root_item)  # 200
        model.load_more_children(root_item)  # 300
        assert len(root_item._children) == 300

    def test_load_more_removes_from_pending_when_exhausted(self):
        model, adapter = _make_model(10_050)
        root_item = model.get_item_children(None)[0]
        model.get_item_children(root_item)  # loads first 100

        root_path = adapter.get_item_path(adapter.get_root())
        # Load batches until exhausted
        while root_path in model._pending_expand_paths:
            model.load_more_children(root_item)

        assert root_path not in model._pending_expand_paths
        assert len(root_item._children) == 10_050

    def test_load_more_all_unique_paths(self):
        model, adapter = _make_model(15_000)
        root_item = model.get_item_children(None)[0]
        model.get_item_children(root_item)
        model.load_more_children(root_item)
        paths = {adapter.get_item_path(c.adapter_item) for c in root_item._children}
        assert len(paths) == len(root_item._children)

    def test_load_more_items_are_hierarchy_items(self):
        from ovwidgets.stage.hierarchy_model import HierarchyItem
        model, _ = _make_model(15_000)
        root_item = model.get_item_children(None)[0]
        model.get_item_children(root_item)
        model.load_more_children(root_item)
        assert all(isinstance(c, HierarchyItem) for c in root_item._children)

    def test_load_more_without_prior_load_returns_zero(self):
        model, _ = _make_model(15_000)
        root_item = model.get_item_children(None)[0]
        # root_item._children is None; not in pending yet
        result = model.load_more_children(root_item)
        assert result == 0

    def test_load_more_callable(self):
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        assert callable(HierarchyModel.load_more_children)


# ---------------------------------------------------------------------------
# _pending_expand_paths lifecycle
# ---------------------------------------------------------------------------

class TestPendingExpandPaths:
    def test_initially_empty(self):
        model, _ = _make_model(15_000)
        assert len(model._pending_expand_paths) == 0

    def test_cleared_on_set_adapter(self):
        model, _ = _make_model(15_000)
        root_item = model.get_item_children(None)[0]
        model.get_item_children(root_item)
        assert len(model._pending_expand_paths) == 1

        from ovwidgets.common.testing.mock_stage import MockStageAdapter
        model.set_adapter(MockStageAdapter(prim_count=50))
        assert len(model._pending_expand_paths) == 0

    def test_cleared_on_adapter_change_event(self):
        model, adapter = _make_model(15_000)
        root_item = model.get_item_children(None)[0]
        model.get_item_children(root_item)
        assert len(model._pending_expand_paths) == 1

        adapter.fire_change(["/World"])
        assert len(model._pending_expand_paths) == 0

    def test_is_set_type(self):
        model, _ = _make_model(15_000)
        assert isinstance(model._pending_expand_paths, set)

    def test_contains_correct_path(self):
        model, adapter = _make_model(15_000)
        root_item = model.get_item_children(None)[0]
        model.get_item_children(root_item)
        expected_path = adapter.get_item_path(adapter.get_root())
        assert expected_path in model._pending_expand_paths


# ---------------------------------------------------------------------------
# Filter bypass — lazy loading disabled when filter active
# ---------------------------------------------------------------------------

class TestFilterBypass:
    def test_filter_active_loads_all_matching(self):
        """When a filter is active, lazy loading is bypassed."""
        model, _ = _make_model(15_000)
        model.set_filter("Prim_1")  # matches Prim_1, Prim_10, Prim_100, etc.
        root_item = model.get_item_children(None)[0]
        children = model.get_item_children(root_item)
        # Filter is active — all matching children loaded, no lazy truncation
        assert len(children) > 100

    def test_filter_off_reverts_to_lazy(self):
        """Clearing filter on a large tree re-enables lazy loading."""
        model, _ = _make_model(15_000)
        model.set_filter("Prim_1")  # activate filter
        root_item = model.get_item_children(None)[0]
        model.get_item_children(root_item)

        model.set_filter("")  # clear filter
        root_item2 = model.get_item_children(None)[0]
        children = model.get_item_children(root_item2)
        assert len(children) == 100


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

class TestPerformance:
    def test_large_tree_initial_load_fast(self):
        """First batch of 100 from a 15k tree must load in < 100ms."""
        from ovwidgets.common.testing.mock_stage import MockStageAdapter
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        adapter = MockStageAdapter(prim_count=15_000)
        model = HierarchyModel(adapter)

        start = time.perf_counter()
        root_item = model.get_item_children(None)[0]
        children = model.get_item_children(root_item)
        elapsed = time.perf_counter() - start

        assert len(children) == 100
        assert elapsed < 0.1, f"Lazy load too slow: {elapsed * 1000:.1f}ms"

    def test_small_tree_loads_fast(self):
        """100-prim tree loads all children in < 100ms."""
        from ovwidgets.common.testing.mock_stage import MockStageAdapter
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        adapter = MockStageAdapter(prim_count=100)
        model = HierarchyModel(adapter)

        start = time.perf_counter()
        root_item = model.get_item_children(None)[0]
        children = model.get_item_children(root_item)
        elapsed = time.perf_counter() - start

        assert len(children) == 100
        assert elapsed < 0.1, f"Small tree too slow: {elapsed * 1000:.1f}ms"

    def test_get_children_count_fast(self):
        """_get_children_count on 15k tree must complete in < 50ms."""
        from ovwidgets.common.testing.mock_stage import MockStageAdapter
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        adapter = MockStageAdapter(prim_count=15_000)
        model = HierarchyModel(adapter)
        root_item = model.get_item_children(None)[0]

        start = time.perf_counter()
        count = model._get_children_count(root_item)
        elapsed = time.perf_counter() - start

        assert count == 15_000
        assert elapsed < 0.05, f"Count too slow: {elapsed * 1000:.1f}ms"

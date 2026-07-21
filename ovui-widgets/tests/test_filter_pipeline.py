# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Comprehensive unit tests for FilterPipeline and make_name_filter.

Tests the public API of FilterPipeline and the make_name_filter
factory function used for the Stage Browser filter bar.
"""

from __future__ import annotations

import pytest

from ovui_widgets.common.testing.mock_stage import MockStageAdapter
from ovui_widgets.stage.filter_pipeline import FilterPipeline, make_name_filter


@pytest.fixture
def adapter():
    return MockStageAdapter()


# ---------------------------------------------------------------------------
# FilterPipeline construction and is_active property
# ---------------------------------------------------------------------------

class TestFilterPipelineInit:
    def test_new_pipeline_not_active(self):
        fp = FilterPipeline()
        assert fp.is_active is False

    def test_new_pipeline_predicates_list_empty(self):
        fp = FilterPipeline()
        assert fp._predicates == []

    def test_new_pipeline_passes_root(self, adapter):
        fp = FilterPipeline()
        root = adapter.get_root()
        assert fp.passes(adapter, root) is True

    def test_new_pipeline_passes_all_children(self, adapter):
        fp = FilterPipeline()
        for child in adapter.get_children(adapter.get_root()):
            assert fp.passes(adapter, child) is True


class TestIsActive:
    def test_becomes_active_after_add(self):
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: True)
        assert fp.is_active is True

    def test_remains_active_with_multiple_predicates(self):
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: True)
        fp.add_predicate(lambda a, i: False)
        assert fp.is_active is True

    def test_not_active_after_clear(self):
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: True)
        fp.clear()
        assert fp.is_active is False

    def test_double_clear_safe(self):
        fp = FilterPipeline()
        fp.clear()
        fp.clear()
        assert fp.is_active is False

    def test_add_then_clear_then_add(self):
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: False)
        fp.clear()
        fp.add_predicate(lambda a, i: True)
        assert fp.is_active is True


# ---------------------------------------------------------------------------
# FilterPipeline.passes() with custom predicates
# ---------------------------------------------------------------------------

class TestPasses:
    def test_no_predicates_always_passes(self, adapter):
        fp = FilterPipeline()
        root = adapter.get_root()
        assert fp.passes(adapter, root) is True

    def test_true_predicate_passes(self, adapter):
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: True)
        assert fp.passes(adapter, adapter.get_root()) is True

    def test_false_predicate_fails(self, adapter):
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: False)
        assert fp.passes(adapter, adapter.get_root()) is False

    def test_and_logic_all_true(self, adapter):
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: True)
        fp.add_predicate(lambda a, i: True)
        fp.add_predicate(lambda a, i: True)
        assert fp.passes(adapter, adapter.get_root()) is True

    def test_and_logic_one_false_fails(self, adapter):
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: True)
        fp.add_predicate(lambda a, i: False)
        fp.add_predicate(lambda a, i: True)
        assert fp.passes(adapter, adapter.get_root()) is False

    def test_and_logic_all_false(self, adapter):
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: False)
        fp.add_predicate(lambda a, i: False)
        assert fp.passes(adapter, adapter.get_root()) is False

    def test_predicate_receives_adapter(self, adapter):
        received_adapters = []
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: (received_adapters.append(a), True)[1])
        fp.passes(adapter, adapter.get_root())
        assert received_adapters[0] is adapter

    def test_predicate_receives_item(self, adapter):
        root = adapter.get_root()
        received_items = []
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: (received_items.append(i), True)[1])
        fp.passes(adapter, root)
        assert received_items[0] is root

    def test_clear_then_passes_all(self, adapter):
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: False)
        fp.clear()
        assert fp.passes(adapter, adapter.get_root()) is True

    def test_short_circuits_on_first_false(self, adapter):
        call_log = []
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: (call_log.append("first"), False)[1])
        fp.add_predicate(lambda a, i: (call_log.append("second"), True)[1])
        fp.passes(adapter, adapter.get_root())
        assert "first" in call_log
        assert "second" not in call_log


class TestAddPredicate:
    def test_predicates_accumulate(self):
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: True)
        fp.add_predicate(lambda a, i: True)
        fp.add_predicate(lambda a, i: True)
        assert len(fp._predicates) == 3

    def test_clear_empties_predicates(self):
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: True)
        fp.add_predicate(lambda a, i: True)
        fp.clear()
        assert fp._predicates == []

    def test_predicates_executed_in_order(self, adapter):
        order = []
        fp = FilterPipeline()
        fp.add_predicate(lambda a, i: (order.append(1), True)[1])
        fp.add_predicate(lambda a, i: (order.append(2), True)[1])
        fp.add_predicate(lambda a, i: (order.append(3), True)[1])
        fp.passes(adapter, adapter.get_root())
        assert order == [1, 2, 3]


# ---------------------------------------------------------------------------
# make_name_filter factory
# ---------------------------------------------------------------------------

class TestMakeNameFilter:
    def test_exact_name_matches(self, adapter):
        pred = make_name_filter("World")
        root = adapter.get_root()
        assert pred(adapter, root) is True

    def test_exact_name_no_match(self, adapter):
        pred = make_name_filter("Sphere")
        root = adapter.get_root()
        assert pred(adapter, root) is False

    def test_case_insensitive_lower(self, adapter):
        pred = make_name_filter("world")
        root = adapter.get_root()
        assert pred(adapter, root) is True

    def test_case_insensitive_upper(self, adapter):
        item = adapter.get_item_at_path("/World/Geometry/Sphere")
        pred = make_name_filter("SPHERE")
        assert pred(adapter, item) is True

    def test_case_insensitive_mixed(self, adapter):
        item = adapter.get_item_at_path("/World/Geometry/Sphere")
        pred = make_name_filter("sPheRe")
        assert pred(adapter, item) is True

    def test_empty_string_matches_all(self, adapter):
        pred = make_name_filter("")
        root = adapter.get_root()
        for child in adapter.get_children(root):
            assert pred(adapter, child) is True

    def test_partial_substring_matches(self, adapter):
        pred = make_name_filter("orl")
        root = adapter.get_root()
        assert pred(adapter, root) is True

    def test_partial_substring_no_match(self, adapter):
        pred = make_name_filter("xyz_unique_no_match")
        root = adapter.get_root()
        assert pred(adapter, root) is False

    def test_filter_uses_display_name(self, adapter):
        item = adapter.get_item_at_path("/World/Lights/DomeLight")
        pred = make_name_filter("DomeLight")
        assert pred(adapter, item) is True

    def test_filter_uses_display_name_partial(self, adapter):
        item = adapter.get_item_at_path("/World/Lights/DomeLight")
        pred = make_name_filter("dome")
        assert pred(adapter, item) is True

    def test_filter_against_mesh_child(self, adapter):
        item = adapter.get_item_at_path("/World/Geometry/Ground")
        pred = make_name_filter("Ground")
        assert pred(adapter, item) is True

    def test_filter_against_mesh_child_no_match(self, adapter):
        item = adapter.get_item_at_path("/World/Geometry/Ground")
        pred = make_name_filter("Sphere")
        assert pred(adapter, item) is False

    def test_filter_dot_character_literal(self, adapter):
        """Dot is a regex metachar — make_name_filter uses simple substring, not regex."""
        root = adapter.get_root()
        pred = make_name_filter(".")
        # "World" does not contain "." — should not match
        assert pred(adapter, root) is False

    def test_filter_returns_callable(self):
        pred = make_name_filter("test")
        assert callable(pred)

    def test_filter_lowercase_stored_at_creation(self, adapter):
        """Filter text is lowercased once at creation, not per-call."""
        root = adapter.get_root()
        pred = make_name_filter("WORLD")
        assert pred(adapter, root) is True
        assert pred(adapter, root) is True  # consistent on repeated calls


# ---------------------------------------------------------------------------
# FilterPipeline with make_name_filter
# ---------------------------------------------------------------------------

class TestFilterPipelineWithNameFilter:
    def test_single_name_filter_matches(self, adapter):
        fp = FilterPipeline()
        fp.add_predicate(make_name_filter("Sphere"))
        sphere = adapter.get_item_at_path("/World/Geometry/Sphere")
        assert fp.passes(adapter, sphere) is True

    def test_single_name_filter_excludes(self, adapter):
        fp = FilterPipeline()
        fp.add_predicate(make_name_filter("Sphere"))
        cube = adapter.get_item_at_path("/World/Geometry/Cube")
        assert fp.passes(adapter, cube) is False

    def test_double_name_filter_both_match(self, adapter):
        fp = FilterPipeline()
        fp.add_predicate(make_name_filter("Dome"))
        fp.add_predicate(make_name_filter("Light"))
        item = adapter.get_item_at_path("/World/Lights/DomeLight")
        assert fp.passes(adapter, item) is True

    def test_double_name_filter_one_misses(self, adapter):
        fp = FilterPipeline()
        fp.add_predicate(make_name_filter("Dome"))
        fp.add_predicate(make_name_filter("Camera"))
        item = adapter.get_item_at_path("/World/Lights/DomeLight")
        assert fp.passes(adapter, item) is False

    def test_clear_restores_pass_all(self, adapter):
        fp = FilterPipeline()
        fp.add_predicate(make_name_filter("no_match_xyz"))
        root = adapter.get_root()
        assert fp.passes(adapter, root) is False
        fp.clear()
        assert fp.passes(adapter, root) is True

    def test_pipeline_is_active_with_name_filter(self):
        fp = FilterPipeline()
        fp.add_predicate(make_name_filter("test"))
        assert fp.is_active is True

    def test_pipeline_not_active_after_clear_name_filter(self):
        fp = FilterPipeline()
        fp.add_predicate(make_name_filter("test"))
        fp.clear()
        assert fp.is_active is False

    def test_all_geometry_children_covered(self, adapter):
        """Verify filter against every child in geometry group."""
        fp = FilterPipeline()
        fp.add_predicate(make_name_filter("sphere"))
        geometry = adapter.get_item_at_path("/World/Geometry")
        for child in adapter.get_children(geometry):
            name = adapter.get_display_name(child)
            expected = "sphere" in name.lower()
            assert fp.passes(adapter, child) is expected

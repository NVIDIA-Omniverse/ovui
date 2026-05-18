# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 19: FilterPipeline and Stage Browser filter bar."""

import pytest

from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.stage.filter_pipeline import FilterPipeline, make_name_filter
from ovwidgets.stage.hierarchy_model import HierarchyModel
from ovwidgets.stage.stage_widget import StageWidget


@pytest.fixture(autouse=True)
def reset_bus():
    SelectionBus._instance = None
    yield
    SelectionBus._instance = None


# ---------------------------------------------------------------------------
# FilterPipeline unit tests
# ---------------------------------------------------------------------------

class TestFilterPipelineNoPredicate:
    def test_no_predicates_is_not_active(self):
        fp = FilterPipeline()
        assert fp.is_active is False

    def test_no_predicates_passes_everything(self):
        adapter = MockStageAdapter()
        root = adapter.get_root()
        fp = FilterPipeline()
        assert fp.passes(adapter, root) is True

    def test_no_predicates_passes_any_item(self):
        adapter = MockStageAdapter()
        children = adapter.get_children(adapter.get_root())
        fp = FilterPipeline()
        for child in children:
            assert fp.passes(adapter, child) is True


class TestNameFilter:
    def test_matches_exact_name(self):
        adapter = MockStageAdapter()
        predicate = make_name_filter("World")
        root = adapter.get_root()
        assert predicate(adapter, root) is True

    def test_matches_case_insensitive(self):
        adapter = MockStageAdapter()
        predicate = make_name_filter("world")
        root = adapter.get_root()
        assert predicate(adapter, root) is True

    def test_matches_partial_substring(self):
        adapter = MockStageAdapter()
        predicate = make_name_filter("orl")
        root = adapter.get_root()
        assert predicate(adapter, root) is True

    def test_excludes_non_matching(self):
        adapter = MockStageAdapter()
        predicate = make_name_filter("Sphere")
        root = adapter.get_root()
        assert predicate(adapter, root) is False

    def test_empty_string_matches_everything(self):
        adapter = MockStageAdapter()
        predicate = make_name_filter("")
        root = adapter.get_root()
        assert predicate(adapter, root) is True


class TestMultiplePredicates:
    def test_both_must_pass(self):
        adapter = MockStageAdapter()
        fp = FilterPipeline()
        fp.add_predicate(make_name_filter("World"))
        fp.add_predicate(make_name_filter("sphere"))  # "World" doesn't contain "sphere"
        root = adapter.get_root()
        assert fp.passes(adapter, root) is False

    def test_both_pass(self):
        adapter = MockStageAdapter()
        fp = FilterPipeline()
        fp.add_predicate(make_name_filter("W"))
        fp.add_predicate(make_name_filter("orl"))
        root = adapter.get_root()
        assert fp.passes(adapter, root) is True

    def test_clear_removes_all_predicates(self):
        adapter = MockStageAdapter()
        fp = FilterPipeline()
        fp.add_predicate(make_name_filter("no_match_xyz"))
        fp.clear()
        assert fp.is_active is False
        root = adapter.get_root()
        assert fp.passes(adapter, root) is True


# ---------------------------------------------------------------------------
# HierarchyModel.set_filter() tests
# ---------------------------------------------------------------------------

class TestHierarchyModelSetFilter:
    def test_model_has_filter_pipeline(self):
        model = HierarchyModel(MockStageAdapter())
        assert hasattr(model, "_filter_pipeline")
        assert isinstance(model._filter_pipeline, FilterPipeline)

    def test_filter_not_active_initially(self):
        model = HierarchyModel(MockStageAdapter())
        assert model._filter_pipeline.is_active is False

    def test_set_filter_activates_pipeline(self):
        model = HierarchyModel(MockStageAdapter())
        model.set_filter("Sphere")
        assert model._filter_pipeline.is_active is True

    def test_set_filter_empty_clears_pipeline(self):
        model = HierarchyModel(MockStageAdapter())
        model.set_filter("Sphere")
        model.set_filter("")
        assert model._filter_pipeline.is_active is False

    def test_set_filter_hides_non_matching_children(self):
        """After filtering for 'Sphere', World's direct children include Geometry (ancestor) but not Camera."""
        adapter = MockStageAdapter()
        model = HierarchyModel(adapter)
        model.set_filter("Sphere")
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        child_names = [adapter.get_display_name(c.adapter_item) for c in children]
        # Geometry is an ancestor of Sphere → stays visible
        assert "Geometry" in child_names
        # Camera and Lights don't have matching descendants
        assert "Camera" not in child_names

    def test_set_filter_clears_filter_shows_all(self):
        """Clearing the filter restores all children."""
        adapter = MockStageAdapter()
        model = HierarchyModel(adapter)
        model.set_filter("Sphere")
        model.set_filter("")
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        child_names = [adapter.get_display_name(c.adapter_item) for c in children]
        assert "Geometry" in child_names
        assert "Lights" in child_names
        assert "Camera" in child_names


# ---------------------------------------------------------------------------
# Ancestor visibility tests
# ---------------------------------------------------------------------------

class TestAncestorVisibility:
    def test_ancestor_of_match_is_visible(self):
        """World/Geometry should appear when filtering for 'Sphere' (Sphere is under Geometry)."""
        adapter = MockStageAdapter()
        model = HierarchyModel(adapter)
        model.set_filter("Sphere")
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        child_names = [adapter.get_display_name(c.adapter_item) for c in children]
        assert "Geometry" in child_names

    def test_grandchild_match_makes_intermediate_visible(self):
        """After filtering for 'Sphere', expanding Geometry should show only Sphere, not Ground or Cube."""
        adapter = MockStageAdapter()
        model = HierarchyModel(adapter)
        model.set_filter("Sphere")
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        # Find Geometry
        geometry = next(
            c for c in children if adapter.get_display_name(c.adapter_item) == "Geometry"
        )
        geo_children = model.get_item_children(geometry)
        geo_child_names = [adapter.get_display_name(c.adapter_item) for c in geo_children]
        assert "Sphere" in geo_child_names
        assert "Ground" not in geo_child_names
        assert "Cube" not in geo_child_names

    def test_non_matching_leaf_excluded(self):
        """Camera has no children and doesn't match 'Sphere' → excluded."""
        adapter = MockStageAdapter()
        model = HierarchyModel(adapter)
        model.set_filter("Sphere")
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        child_names = [adapter.get_display_name(c.adapter_item) for c in children]
        assert "Camera" not in child_names


# ---------------------------------------------------------------------------
# Widget filter bar integration
# ---------------------------------------------------------------------------

class TestStageWidgetFilterBar:
    def test_widget_has_filter_field_attr(self):
        w = StageWidget()
        assert hasattr(w, "_filter_field")
        w.destroy()

    def test_filter_field_populated_after_build(self):
        # Step 7: StageWidget is now a pure widget — build() runs from
        # __init__, so the StringField is live immediately.
        w = StageWidget()
        assert w._filter_field is not None
        w.destroy()

    def test_filter_styles_in_stage_styles(self):
        from ovwidgets.stage.style import STAGE_STYLES
        assert "Stage.FilterBar" in STAGE_STYLES
        assert "Stage.FilterField" in STAGE_STYLES

    def test_filter_bar_has_background_color(self):
        from ovwidgets.stage.style import STAGE_STYLES
        assert "background_color" in STAGE_STYLES["Stage.FilterBar"]

    def test_filter_field_has_background_color(self):
        from ovwidgets.stage.style import STAGE_STYLES
        assert "background_color" in STAGE_STYLES["Stage.FilterField"]


# ---------------------------------------------------------------------------
# Design Step 3 — icon-inside-field pill + STYLE-PROPOSAL token compliance
# ---------------------------------------------------------------------------

class TestStageFilterPillStep3:
    """The Design Step 3 filter bar wraps the magnifier icon + input +
    clear button in a single bordered ``Rectangle`` so the icon visibly
    sits inside the field. These tests pin the token bindings, the
    transparent-inner-input contract, and the focus-state mirroring
    (the pseudo-state can't fire on a Rectangle, so ``begin_edit_fn`` /
    ``end_edit_fn`` swap the outer Rectangle's ``name`` to ``"focused"``).
    """

    def test_filter_field_uses_background_field_token(self):
        from ovwidgets.stage.style import STAGE_STYLES
        assert STAGE_STYLES["Stage.FilterField"]["background_color"] == (
            "background_field"
        )

    def test_filter_field_uses_border_default_token(self):
        from ovwidgets.stage.style import STAGE_STYLES
        assert STAGE_STYLES["Stage.FilterField"]["border_color"] == "border_default"

    def test_filter_field_uses_radius_small_token(self):
        from ovwidgets.stage.style import STAGE_STYLES
        assert STAGE_STYLES["Stage.FilterField"]["border_radius"] == "radius_small"

    def test_filter_field_has_1px_border(self):
        from ovwidgets.stage.style import STAGE_STYLES
        assert STAGE_STYLES["Stage.FilterField"]["border_width"] == 0

    def test_filter_field_focused_uses_border_focused(self):
        """Named variant — toggled via ``name = "focused"`` on the Rectangle."""
        from ovwidgets.stage.style import STAGE_STYLES
        assert "Stage.FilterField::focused" in STAGE_STYLES
        assert STAGE_STYLES["Stage.FilterField::focused"]["border_color"] == (
            "border_focused"
        )

    def test_filter_field_border_uses_border_default_token(self):
        from ovwidgets.stage.style import STAGE_STYLES
        assert STAGE_STYLES["Stage.FilterFieldBorder"]["background_color"] == (
            "border_default"
        )

    def test_filter_field_border_focused_uses_border_focused(self):
        from ovwidgets.stage.style import STAGE_STYLES
        assert STAGE_STYLES["Stage.FilterFieldBorder::focused"]["background_color"] == (
            "border_focused"
        )

    def test_filter_field_input_is_transparent(self):
        """The inner StringField renders on top of the bordered Rectangle;
        its own background must be transparent so only the pill reads."""
        from ovwidgets.stage.style import STAGE_STYLES
        assert "Stage.FilterFieldInput" in STAGE_STYLES
        assert STAGE_STYLES["Stage.FilterFieldInput"]["background_color"] == (
            "transparent"
        )
        assert STAGE_STYLES["Stage.FilterFieldInput"]["border_width"] == 0

    def test_filter_field_input_has_text_primary(self):
        from ovwidgets.stage.style import STAGE_STYLES
        assert STAGE_STYLES["Stage.FilterFieldInput"]["color"] == "text_primary"

    def test_filter_placeholder_style_registered(self):
        from ovwidgets.stage.style import STAGE_STYLES
        assert STAGE_STYLES["Stage.FilterPlaceholder"]["color"] == "text_disabled"
        assert "font_size" in STAGE_STYLES["Stage.FilterPlaceholder"]

    def test_widget_has_filter_rect(self):
        w = StageWidget()
        assert w._filter_rect is not None
        assert w._filter_border_rect is not None
        assert w._filter_placeholder is not None
        w.destroy()

    def test_begin_edit_toggles_focused_name(self):
        w = StageWidget()
        assert w._filter_rect is not None
        assert w._filter_border_rect is not None
        assert w._filter_rect.name in ("", None)
        assert w._filter_border_rect.name in ("", None)
        w._on_filter_begin_edit(w._filter_field.model)
        assert w._filter_rect.name == "focused"
        assert w._filter_border_rect.name == "focused"
        w._on_filter_end_edit(w._filter_field.model)
        assert w._filter_rect.name == ""
        assert w._filter_border_rect.name == ""
        w.destroy()

    def test_chrome_state_hides_placeholder_when_text_exists(self):
        w = StageWidget()
        w._set_filter_chrome_state(False)
        assert w._filter_placeholder.visible is True
        w._set_filter_chrome_state(True)
        assert w._filter_placeholder.visible is False
        w.destroy()


# ---------------------------------------------------------------------------
# Empty-state overlay (shown when the tree has no visible children)
# ---------------------------------------------------------------------------

class TestStageWidgetEmptyState:
    def test_widget_has_empty_state_attrs(self):
        w = StageWidget()
        assert hasattr(w, "_empty_state_container")
        assert hasattr(w, "_empty_state_label")
        w.destroy()

    def test_empty_state_hidden_with_children(self):
        w = StageWidget()
        # Default MockStageAdapter has a populated /World tree.
        assert w._empty_state_container is not None
        assert w._empty_state_container.visible is False
        w.destroy()

    def test_empty_state_shown_when_filter_matches_nothing(self):
        w = StageWidget()
        w.filter_by_text("___impossible_prim_name___")
        assert w._empty_state_container.visible is True
        assert "___impossible_prim_name___" in w._empty_state_label.text
        w.destroy()

    def test_empty_state_hidden_when_filter_cleared(self):
        w = StageWidget()
        w.filter_by_text("___impossible_prim_name___")
        assert w._empty_state_container.visible is True
        w.filter_by_text("")
        assert w._empty_state_container.visible is False
        w.destroy()

    def test_empty_state_style_registered(self):
        from ovwidgets.stage.style import STAGE_STYLES
        assert "Stage.EmptyState" in STAGE_STYLES
        assert STAGE_STYLES["Stage.EmptyState"]["color"] == "text_disabled"

    def test_empty_state_update_tolerates_missing_attrs(self):
        # Mirrors test_step26_open_file's __new__ bypass: _update_empty_state
        # must not raise when the overlay attributes were never installed.
        w = StageWidget.__new__(StageWidget)
        w._filter_field = None
        w._update_empty_state()  # must not raise

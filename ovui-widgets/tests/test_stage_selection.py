# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Stage Browser selection (Step 17).

Tests selection tracking, SelectionBus integration, reentrancy guard,
and selection styles.
"""

import pytest
from ovui_data_adapters.common import ChangeEvent, ChangeEventType

from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_stage import MockStageAdapter
from ovui_widgets.stage.hierarchy_model import HierarchyItem, HierarchyModel
from ovui_widgets.stage.stage_widget import StageWidget
from ovui_widgets.stage.widget.stage_delegate import _ROW_HEIGHT


@pytest.fixture(autouse=True)
def reset_bus():
    SelectionBus._instance = None
    yield
    SelectionBus._instance = None


class _FakeScrollFrame:
    def __init__(self, viewport_height: float, max_scroll: float) -> None:
        self.computed_height = viewport_height
        self.scroll_y_max = max_scroll
        self.scroll_y = 0.0


class _FakeTreeView:
    def __init__(self, widget: StageWidget) -> None:
        self._widget = widget
        self.selection_writes = []
        self.selection = []
        self.expanded = []

    def set_expanded(self, item, expanded, recursive):
        path = self._widget._adapter.get_item_path(item.adapter_item)
        self.expanded.append((path, expanded, recursive))

    def is_expanded(self, item):
        path = self._widget._adapter.get_item_path(item.adapter_item)
        return path in self._widget._model._expanded_paths

    @property
    def selection(self):
        return self._selection

    @selection.setter
    def selection(self, value):
        self._selection = list(value)
        self.selection_writes.append(list(value))


def _install_focus_fakes(
    widget: StageWidget,
    viewport_height: float,
    max_scroll: float,
) -> tuple[_FakeTreeView, _FakeScrollFrame]:
    tree = _FakeTreeView(widget)
    scroll = _FakeScrollFrame(viewport_height, max_scroll)
    widget._tree_view = tree
    widget._model._tree_view_ref = tree
    widget._scrolling_frame = scroll
    return tree, scroll


def _expected_centered_scroll(row_index: int, viewport_height: float) -> float:
    return float(row_index * _ROW_HEIGHT) - ((viewport_height - _ROW_HEIGHT) * 0.5)


class TestSelectionTracking:
    def test_model_has_selected_items(self):
        model = HierarchyModel(MockStageAdapter())
        assert hasattr(model, "_selected_items")
        assert model._selected_items == []

    def test_model_has_selection_guard(self):
        model = HierarchyModel(MockStageAdapter())
        assert hasattr(model, "_selection_guard")
        assert model._selection_guard is False

    def test_get_selected_paths_empty_initially(self):
        model = HierarchyModel(MockStageAdapter())
        assert model.get_selected_paths() == []

    def test_get_selected_paths_returns_list(self):
        model = HierarchyModel(MockStageAdapter())
        assert isinstance(model.get_selected_paths(), list)

    def test_transform_info_change_does_not_rebuild_stage_tree(self):
        model = HierarchyModel(MockStageAdapter())
        model.get_item_children(model._root)
        original_children = model._root._children
        changed_items = []
        sub = model.subscribe_item_changed_fn(
            lambda _model, item: changed_items.append(item)
        )
        try:
            model._on_adapter_event(
                ChangeEvent(
                    changed_paths=("/World/Geometry/Cube",),
                    resynced_paths=(),
                    event_type=ChangeEventType.INFO_CHANGE,
                    source="ovstage:transform",
                )
            )
        finally:
            sub.unsubscribe()

        assert changed_items == []
        assert model._root._children is original_children

    def test_widget_has_bus_sub_attr(self):
        w = StageWidget()
        assert hasattr(w, "_bus_sub")
        assert w._bus_sub is not None
        w.destroy()

    def test_widget_has_tree_view_attr(self):
        w = StageWidget()
        assert hasattr(w, "_tree_view")
        w.destroy()


class TestStageFooter:
    def test_footer_labels_created(self):
        w = StageWidget(adapter=MockStageAdapter())
        assert w._footer_prim_label is not None
        assert w._footer_hidden_label is not None
        w.destroy()

    def test_footer_shows_live_prim_count(self):
        w = StageWidget(adapter=MockStageAdapter())
        assert w._footer_prim_label.text == "8 prims"
        w.destroy()

    def test_footer_shows_live_hidden_count(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        sphere = adapter.get_item_at_path("/World/Geometry/Sphere")

        adapter.set_visibility(sphere, False)

        assert w._footer_hidden_label.text == "USD · 1 hidden"
        w.destroy()

    def test_footer_hidden_count_decrements_when_visibility_restored(self):
        adapter = MockStageAdapter()
        sphere = adapter.get_item_at_path("/World/Geometry/Sphere")
        adapter.set_visibility(sphere, False)
        w = StageWidget(adapter=adapter)

        adapter.set_visibility(sphere, True)

        assert w._footer_hidden_label.text == "USD · 0 hidden"
        w.destroy()

    def test_footer_prim_count_updates_after_resync(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)

        adapter.add_child("/World", "Extra", "Mesh")

        assert w._footer_prim_label.text == "9 prims"
        w.destroy()


class TestTreeSelectionCallback:
    def test_chevron_collapse_keeps_descendant_selected_and_cancels_focus_retry(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        tree, _ = _install_focus_fakes(w, viewport_height=120.0, max_scroll=200.0)
        root = w._model.get_item_children(None)[0]
        child = w._model.get_item_children(root)[0]
        child_path = adapter.get_item_path(child.adapter_item)
        root_path = adapter.get_item_path(root.adapter_item)
        w._model._selected_items = [child]
        w._model._expanded_paths.add(root_path)
        w._pending_focus_path = child_path
        w._focus_preserve_expanded_paths.add(root_path)

        w._on_branch_toggle(root, False)

        assert w._model._selected_items == [child]
        assert root_path not in w._model._expanded_paths
        assert tree.expanded[-1] == (root_path, False, False)
        assert w._pending_focus_path is None
        assert w._focus_preserve_expanded_paths == set()
        w.destroy()

    def test_on_tree_selection_changed_updates_selected_items(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        root = w._model.get_item_children(None)[0]
        w._on_tree_selection_changed([root])
        assert root in w._model._selected_items
        w.destroy()

    def test_selected_items_cleared_on_empty_selection(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        root = w._model.get_item_children(None)[0]
        w._on_tree_selection_changed([root])
        w._on_tree_selection_changed([])
        assert w._model._selected_items == []
        w.destroy()

    def test_selected_items_have_correct_paths(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        root = w._model.get_item_children(None)[0]
        w._on_tree_selection_changed([root])
        paths = w._model.get_selected_paths()
        assert len(paths) == 1
        assert paths[0] == "/World"
        w.destroy()

    def test_selection_publishes_to_bus(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        received = []
        sub = SelectionBus.instance().subscribe(lambda e: received.append(e))  # noqa: F841
        root = w._model.get_item_children(None)[0]
        w._on_tree_selection_changed([root])
        assert len(received) >= 1
        stage_events = [e for e in received if e.source == "stage"]
        assert len(stage_events) == 1
        assert "/World" in stage_events[0].snapshot.paths()
        w.destroy()

    def test_multiselect_updates_all_items(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        root = w._model.get_item_children(None)[0]
        children = w._model.get_item_children(root)
        w._on_tree_selection_changed([root] + children[:2])
        assert len(w._model._selected_items) == 3
        w.destroy()

    def test_multiselect_paths_include_all(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        root = w._model.get_item_children(None)[0]
        children = w._model.get_item_children(root)
        w._on_tree_selection_changed([root] + children)
        paths = w._model.get_selected_paths()
        assert "/World" in paths
        assert "/World/Geometry" in paths
        assert "/World/Lights" in paths
        assert "/World/Camera" in paths
        w.destroy()

    def test_non_hierarchy_items_filtered_out(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        root = w._model.get_item_children(None)[0]
        w._on_tree_selection_changed([root, "not_an_item", None])
        assert all(isinstance(i, HierarchyItem) for i in w._model._selected_items)
        w.destroy()

    def test_selection_change_refreshes_old_and_new_rows(self, monkeypatch):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        root = w._model.get_item_children(None)[0]
        child = w._model.get_item_children(root)[0]
        w._model._selected_items = [root]
        refreshed = []
        monkeypatch.setattr(w._model, "_item_changed", lambda item: refreshed.append(item))

        w._on_tree_selection_changed([child])

        assert refreshed == [root, child]
        w.destroy()


class TestBusToTree:
    def test_bus_event_from_stage_source_is_skipped(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        initial_items = list(w._model._selected_items)
        SelectionBus.instance().publish(["/World"], source="stage")
        assert w._model._selected_items == initial_items
        w.destroy()

    def test_bus_event_from_external_updates_selected_items(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        root = w._model.get_item_children(None)[0]
        w._model.get_item_children(root)  # populate path_cache with children
        SelectionBus.instance().publish(["/World/Geometry"], source="viewport")
        assert len(w._model._selected_items) == 1
        assert w._model._selected_items[0] is w._model._path_cache["/World/Geometry"]
        w.destroy()

    def test_bus_event_path_not_in_cache_ignored(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        SelectionBus.instance().publish(["/World/NonExistent"], source="viewport")
        assert w._model._selected_items == []
        w.destroy()

    def test_bus_event_partial_path_match(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        root = w._model.get_item_children(None)[0]
        w._model.get_item_children(root)
        # One path in cache, one not
        SelectionBus.instance().publish(["/World/Geometry", "/World/Ghost"], source="viewport")
        assert len(w._model._selected_items) == 1
        w.destroy()

    def test_bus_clear_deselects_all(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        root = w._model.get_item_children(None)[0]
        w._on_tree_selection_changed([root])
        assert len(w._model._selected_items) == 1
        SelectionBus.instance().publish([], source="viewport")
        assert w._model._selected_items == []
        w.destroy()

    def test_viewport_selection_expands_parents_and_centers_selected_row(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        _tree, scroll = _install_focus_fakes(w, viewport_height=54, max_scroll=200)

        SelectionBus.instance().publish(["/World/Geometry/Cube"], source="viewport")

        assert w.get_selection() == ["/World/Geometry/Cube"]
        assert "/World" in w._model._expanded_paths
        assert "/World/Geometry" in w._model._expanded_paths
        assert scroll.scroll_y == _expected_centered_scroll(row_index=4, viewport_height=54)
        w.destroy()

    def test_viewport_reselect_focuses_again_when_parents_already_expanded(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        _tree, scroll = _install_focus_fakes(w, viewport_height=54, max_scroll=200)
        SelectionBus.instance().publish(["/World/Geometry/Cube"], source="viewport")
        scroll.scroll_y = 0.0

        SelectionBus.instance().publish(["/World/Geometry/Cube"], source="viewport")

        assert w.get_selection() == ["/World/Geometry/Cube"]
        assert scroll.scroll_y == _expected_centered_scroll(row_index=4, viewport_height=54)
        w.destroy()

    def test_viewport_selection_focuses_under_already_expanded_parent(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        _tree, scroll = _install_focus_fakes(w, viewport_height=54, max_scroll=200)
        w.expand("/World")
        w.expand("/World/Geometry")
        scroll.scroll_y = 120.0

        SelectionBus.instance().publish(["/World/Geometry/Sphere"], source="viewport")

        assert w.get_selection() == ["/World/Geometry/Sphere"]
        assert scroll.scroll_y == _expected_centered_scroll(row_index=3, viewport_height=54)
        w.destroy()

    def test_viewport_multi_selection_focuses_last_selected_row(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        _tree, scroll = _install_focus_fakes(w, viewport_height=54, max_scroll=200)

        SelectionBus.instance().publish(
            ["/World/Geometry/Sphere", "/World/Geometry/Cube"],
            source="viewport",
        )

        assert w.get_selection() == ["/World/Geometry/Sphere", "/World/Geometry/Cube"]
        assert scroll.scroll_y == _expected_centered_scroll(row_index=4, viewport_height=54)
        w.destroy()

    def test_viewport_focus_clamps_when_centering_is_not_possible(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        _tree, scroll = _install_focus_fakes(w, viewport_height=54, max_scroll=30)

        SelectionBus.instance().publish(["/World/Geometry/Cube"], source="viewport")

        assert scroll.scroll_y == 30.0
        w.destroy()

    def test_viewport_focus_keeps_first_row_visible_at_top(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        _tree, scroll = _install_focus_fakes(w, viewport_height=54, max_scroll=200)

        SelectionBus.instance().publish(["/World"], source="viewport")

        assert w.get_selection() == ["/World"]
        assert scroll.scroll_y == 0.0
        w.destroy()


class TestReentrancyGuard:
    def test_guard_prevents_publish_from_tree_callback(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        w._model._selection_guard = True
        publish_count = [0]
        original = SelectionBus.instance().publish

        def counting_publish(*args, **kwargs):
            publish_count[0] += 1
            original(*args, **kwargs)

        SelectionBus.instance().publish = counting_publish
        w._on_tree_selection_changed([])
        assert publish_count[0] == 0
        w._model._selection_guard = False
        w.destroy()

    def test_guard_prevents_bus_handler_from_running(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        w._model._selection_guard = True
        root = w._model.get_item_children(None)[0]
        w._model.get_item_children(root)
        # Directly call the bus handler with guard set
        from ovui_widgets.common.selection import (
            SelectionChangedEvent,
            SelectionItem,
            SelectionSnapshot,
        )
        snapshot = SelectionSnapshot(items=(SelectionItem(path="/World/Geometry", source="viewport"),))
        event = SelectionChangedEvent(snapshot=snapshot, source="viewport")
        w._on_bus_selection_changed(event)
        # Guard was set, so selected_items should not have changed
        assert w._model._selected_items == []
        w._model._selection_guard = False
        w.destroy()

    def test_guard_cleared_after_tree_callback(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        root = w._model.get_item_children(None)[0]
        w._on_tree_selection_changed([root])
        assert w._model._selection_guard is False
        w.destroy()

    def test_guard_cleared_after_bus_handler(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        root = w._model.get_item_children(None)[0]
        w._model.get_item_children(root)
        SelectionBus.instance().publish(["/World/Geometry"], source="viewport")
        assert w._model._selection_guard is False
        w.destroy()


class TestSelectionStyles:
    def test_stage_styles_has_treeview_selected(self):
        from ovui_widgets.stage.style import STAGE_STYLES
        assert "TreeView:selected" in STAGE_STYLES

    def test_stage_styles_has_treeview_item_selected(self):
        from ovui_widgets.stage.style import STAGE_STYLES
        assert "TreeView.Item:selected" in STAGE_STYLES

    def test_treeview_selected_has_background_color(self):
        from ovui_widgets.stage.style import STAGE_STYLES
        style = STAGE_STYLES["TreeView:selected"]
        assert "background_color" in style

    def test_treeview_item_selected_has_color(self):
        from ovui_widgets.stage.style import STAGE_STYLES
        style = STAGE_STYLES["TreeView.Item:selected"]
        assert "color" in style

    def test_treeview_selected_uses_selection_palette(self):
        from omni.ui import color as cl

        from ovui_widgets.stage.style import STAGE_STYLES
        style = STAGE_STYLES["TreeView:selected"]
        assert str(style["background_color"]) == str(cl.treeview_selection)

    def test_treeview_item_selected_keeps_primary_text_palette(self):
        from omni.ui import color as cl

        from ovui_widgets.stage.style import STAGE_STYLES
        style = STAGE_STYLES["TreeView.Item:selected"]
        assert str(style["color"]) == str(cl.text_primary)

    def test_treeview_selection_color_is_exact_reference_gray(self):
        import omni.ui as ui
        from omni.ui import color as cl

        import ovui_widgets.app
        import ovui_widgets.common.style.palette  # noqa: F401

        ui.set_shade("default")
        assert ui.ColorStore.find("treeview_selection") == cl("#232429")

    def test_accent_primary_color_is_exact_reference_blue(self):
        import omni.ui as ui
        from omni.ui import color as cl

        import ovui_widgets.common.style.palette  # noqa: F401

        ui.set_shade("default")
        assert ui.ColorStore.find("accent_primary") == cl("#008AF9")

    def test_stage_styles_define_treeview_selected(self):
        # Step 7: STAGE_STYLES is merged into ui.style.default at startup
        # (see ovui_widgets.app.style.apply_global_styles). The widget no longer
        # exposes its own per-window style dict.
        from ovui_widgets.stage.style import STAGE_STYLES
        assert "TreeView:selected" in STAGE_STYLES


class TestDestroyCleanup:
    def test_destroy_cancels_bus_subscription(self):
        w = StageWidget()
        bus_sub = w._bus_sub
        w.destroy()
        assert w._bus_sub is None

    def test_after_destroy_bus_events_not_received(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        root = w._model.get_item_children(None)[0]
        w._model.get_item_children(root)
        w.destroy()
        SelectionBus.instance().publish(["/World/Geometry"], source="viewport")
        # After destroy, no crash — subscription was cancelled

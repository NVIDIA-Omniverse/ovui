# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 7 — StageWidget as a pure embeddable widget.

These tests verify that StageWidget is not a window: it builds its UI
into whatever ovui layout context is active at construction time, and it
exposes the StageWidget public surface (set_adapter, get_selection,
filter_by_text, scroll_to, expand/collapse, destroy).
"""

import omni.ui as ui
import pytest

from ovwidgets.common.managed_window import ManagedWindow
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.stage.widget.stage_widget import StageWidget


@pytest.fixture(autouse=True)
def reset_bus():
    SelectionBus._instance = None
    yield
    SelectionBus._instance = None


class TestPureWidget:
    def test_not_a_managed_window(self):
        assert not issubclass(StageWidget, ManagedWindow)

    def test_embeds_inside_ui_window_frame(self):
        """StageWidget builds its UI into the surrounding context."""
        win = ui.Window("_test_embed_stage", width=400, height=600)
        try:
            with win.frame:
                widget = StageWidget(adapter=MockStageAdapter())
            assert widget._tree_view is not None
            assert widget._filter_field is not None
            # Tree populated from the MockStageAdapter.
            roots = widget._model.get_item_children(None)
            assert len(roots) == 1
        finally:
            widget.destroy()
            win.destroy()

    def test_embeds_inside_plain_vstack(self):
        with ui.VStack():
            widget = StageWidget(adapter=MockStageAdapter())
        assert widget._tree_view is not None
        widget.destroy()


class TestHeadlessOperation:
    def test_selection_bus_none_defaults_to_singleton(self):
        # StageWidget uses SelectionBus.instance() when selection_bus=None. The
        # plan Step 7 example picks SelectionBus.instance() as the sensible
        # default so two widgets in the same process stay in sync.
        bus = SelectionBus.instance()
        widget = StageWidget(adapter=MockStageAdapter())
        assert widget._selection_bus is bus
        assert widget._bus_sub is not None
        widget.destroy()
        assert widget._bus_sub is None

    def test_no_bus_tree_callback_does_not_crash(self):
        widget = StageWidget(adapter=MockStageAdapter())
        widget._selection_bus = None  # simulate late detach
        widget._bus_sub = None
        widget._on_tree_selection_changed([])  # must not raise


class TestPublicApi:
    def _make(self) -> StageWidget:
        return StageWidget(adapter=MockStageAdapter())

    def test_get_selection_empty_initially(self):
        w = self._make()
        assert w.get_selection() == []
        w.destroy()

    def test_set_selection_roundtrip(self):
        w = self._make()
        # Populate path cache so the widget can find /World.
        w._model.get_item_children(None)
        w.set_selection(["/World"])
        assert w.get_selection() == ["/World"]
        w.destroy()

    def test_filter_by_text_activates_pipeline(self):
        w = self._make()
        w.filter_by_text("Sphere")
        assert w._model._filter_pipeline.is_active is True
        w.filter_by_text("")
        assert w._model._filter_pipeline.is_active is False
        w.destroy()

    def test_visible_columns_default_and_override(self):
        w = self._make()
        assert w.get_visible_columns() == ["Name", "Type", "Visibility"]
        w.set_visible_columns(["Name", "Visibility"])
        assert w.get_visible_columns() == ["Name", "Visibility"]
        w.destroy()

    def test_get_adapter_returns_injected(self):
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        assert w.get_adapter() is adapter
        w.destroy()

    def test_expand_collapse_round_trip(self):
        w = self._make()
        w._model.get_item_children(None)  # populate cache so /World resolves
        w.expand("/World", recursive=False)
        assert "/World" in w._model._expanded_paths
        w.collapse("/World", recursive=False)
        assert "/World" not in w._model._expanded_paths
        w.destroy()

    def test_expand_unknown_path_is_noop(self):
        w = self._make()
        w.expand("/DoesNotExist")  # must not raise
        w.destroy()

    def test_scroll_to_expands_ancestors(self):
        w = self._make()
        w._model.get_item_children(None)
        root_children = w._model.get_item_children(w._model._root)
        for c in root_children:
            w._model.get_item_children(c)  # populate /World/Geometry etc.
        w.scroll_to("/World/Geometry/Sphere")
        assert "/World" in w._model._expanded_paths
        assert "/World/Geometry" in w._model._expanded_paths
        # Sphere itself should not be forcibly expanded (it's a leaf target).
        assert "/World/Geometry/Sphere" not in w._model._expanded_paths
        w.destroy()

    def test_scroll_to_root_is_noop(self):
        w = self._make()
        w.scroll_to("/")  # must not raise
        w.destroy()


class TestDestroyIdempotent:
    def test_destroy_clears_bus_sub(self):
        w = StageWidget(adapter=MockStageAdapter())
        w.destroy()
        assert w._bus_sub is None

    def test_destroy_twice_does_not_crash(self):
        w = StageWidget(adapter=MockStageAdapter())
        w.destroy()
        w.destroy()  # must not raise

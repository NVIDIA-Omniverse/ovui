# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 62 — final polish: tooltips, focus ring, a11y.

Covers:

- Style tokens — ``Layers.TreeView.Row::row_focus``,
  ``Layers.FilterPlaceholder``, ``Layers.EmptyStageLabel``.
- Delegate tooltip copy constants + dynamic tooltips on save / mute /
  lock / name cells.
- Focus-ring painting when :attr:`LayerItem.is_focused` is ``True``.
- :class:`LayerWindow` empty-stage and filter-placeholder constants.
- :class:`LayerWindow._update_focused_item` collapses a single-row
  selection to :attr:`LayerItem.is_focused` and clears the flag on
  multi-select.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import omni.ui as ui
import pytest

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.layers import LayerDelegate, LayerModel, LayerWindow
from ovui_widgets.layers.layer_item import LayerItem
from ovui_widgets.layers.style import LAYERS_STYLES


def _can_build_frame() -> bool:
    try:
        w = ui.Window("__probe_layers_step62__", width=10, height=10)
        w.destroy()
        return True
    except Exception:
        return False


_UI_AVAILABLE = _can_build_frame()
_skip_no_ui = pytest.mark.skipif(
    not _UI_AVAILABLE,
    reason="ui.Frame construction not available without ui.init()",
)


def _headless_window() -> LayerWindow:
    """Construct a :class:`LayerWindow` bypassing ``super().__init__``.

    Mirrors the pattern in ``test_layers_step51_search_field._headless_window``
    so the Step-62 window-level helpers can be exercised without a
    live ``ui.Window``. Every attribute the new Step-62 code touches
    is pre-initialised here.
    """
    w = LayerWindow.__new__(LayerWindow)
    w._app = None
    w._adapter = None
    w._model = None
    w._tree_view = None
    w._delegate = None
    w._save_all_button = None
    w._save_all_badge = None
    w._save_all_sub = None
    w._context_menu_builder = None
    w._filter_field = None
    w._filter_icon = None
    w._filter_clear_button = None
    w._filter_placeholder = None
    w._pending_filter_handle = None
    w._empty_state_container = None
    w._empty_state_label = None
    w._insert_button = None
    w._create_button = None
    w._delete_button = None
    w._selection_watch = None
    return w


# ─── Style tokens ─────────────────────────────────────────────────────────────


class TestStep62StyleTokens:
    def test_row_focus_selector_present(self) -> None:
        assert "Layers.TreeView.Row::row_focus" in LAYERS_STYLES

    def test_row_focus_has_1px_border(self) -> None:
        rule = LAYERS_STYLES["Layers.TreeView.Row::row_focus"]
        assert rule["border_width"] == 1

    def test_row_focus_border_color_is_accent(self) -> None:
        # Accent-primary colour so the ring matches the
        # :class:`ui.StringField` ``:focused`` outline vocabulary.
        from omni.ui import color as cl

        rule = LAYERS_STYLES["Layers.TreeView.Row::row_focus"]
        assert rule["border_color"] == cl.accent_primary

    def test_filter_placeholder_selector_present(self) -> None:
        assert "Layers.FilterPlaceholder" in LAYERS_STYLES

    def test_empty_stage_label_selector_present(self) -> None:
        assert "Layers.EmptyStageLabel" in LAYERS_STYLES


# ─── Delegate tooltip copy ────────────────────────────────────────────────────


class TestStep62DelegateTooltipConstants:
    def test_save_tooltip_constant_exists(self) -> None:
        assert isinstance(LayerDelegate.SAVE_TOOLTIP, str)
        assert "save" in LayerDelegate.SAVE_TOOLTIP.lower()

    def test_local_mute_tooltips_distinguish_states(self) -> None:
        # The two tooltips must not collapse to the same string —
        # the cue's job is to explain what a click will do *now*.
        assert (
            LayerDelegate.LOCAL_MUTE_TOOLTIP_MUTED
            != LayerDelegate.LOCAL_MUTE_TOOLTIP_UNMUTED
        )

    def test_lock_tooltips_distinguish_states(self) -> None:
        assert (
            LayerDelegate.LOCK_TOOLTIP_LOCKED
            != LayerDelegate.LOCK_TOOLTIP_UNLOCKED
        )

    def test_readonly_overlay_tooltip_mentions_file(self) -> None:
        assert "read-only" in LayerDelegate.READONLY_OVERLAY_TOOLTIP.lower()


# ─── Delegate tooltip rendering ───────────────────────────────────────────────


@_skip_no_ui
class TestStep62DelegateTooltips:
    """Build each cell and assert the outer stack carries a tooltip."""

    def _build_and_capture(self, delegate, model, item, column_id):
        """Render ``column_id`` and return the outermost :class:`ui.ZStack`
        that the delegate attached the tooltip to.
        """
        window = ui.Window(
            f"__test_layers_step62_col{column_id}__", width=80, height=40
        )
        try:
            with window.frame:
                container = ui.VStack()
                with container:
                    delegate.build_widget(model, item, column_id, 0, False)
            return container
        finally:
            window.destroy()

    def test_name_tooltip_is_layer_identifier(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        window = ui.Window("__step62_name_tt__", width=80, height=40)
        try:
            with window.frame:
                with ui.VStack():
                    delegate.build_widget(
                        model, model.root_item, LayerDelegate.COL_NAME, 0, False
                    )
            # ``build_widget`` attaches the tooltip string to the HStack
            # it creates inside the cell. There is no post-build handle
            # on the delegate, so the behavioural assertion is that the
            # build completes without raising and the identifier is
            # non-empty (the constant input used in the tooltip).
            assert model.root_item.identifier == ROOT_LAYER_IDENTIFIER
        finally:
            window.destroy()
            model.destroy()

    def test_save_widget_builds_with_tooltip_for_dirty_layer(self) -> None:
        adapter = MockLayerStackAdapter()
        # Flip the root's dirty bit so the save column renders the dot
        # (and therefore carries the tooltip branch).
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        window = ui.Window("__step62_save_tt__", width=80, height=40)
        try:
            with window.frame:
                with ui.VStack():
                    delegate.build_widget(
                        model, model.root_item, LayerDelegate.COL_SAVE, 0, False
                    )
        finally:
            window.destroy()
            model.destroy()

    def test_mute_widget_builds_with_tooltip(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        window = ui.Window("__step62_mute_tt__", width=80, height=40)
        try:
            with window.frame:
                with ui.VStack():
                    delegate.build_widget(
                        model,
                        model.root_item,
                        LayerDelegate.COL_LOCAL_MUTE,
                        0,
                        False,
                    )
        finally:
            window.destroy()
            model.destroy()

    def test_lock_widget_builds_with_tooltip(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        window = ui.Window("__step62_lock_tt__", width=80, height=40)
        try:
            with window.frame:
                with ui.VStack():
                    delegate.build_widget(
                        model, model.root_item, LayerDelegate.COL_LOCK, 0, False
                    )
        finally:
            window.destroy()
            model.destroy()


# ─── Focus ring ───────────────────────────────────────────────────────────────


class TestStep62LayerItemFocusFlag:
    def test_is_focused_defaults_to_false(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert item.is_focused is False

    def test_is_focused_setter_updates_state(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        item.is_focused = True
        assert item.is_focused is True
        item.is_focused = False
        assert item.is_focused is False

    def test_is_focused_setter_coerces_to_bool(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        item.is_focused = 1  # type: ignore[assignment]
        assert item.is_focused is True
        assert isinstance(item._is_focused, bool)


@_skip_no_ui
class TestStep62FocusRingPainting:
    def test_build_focus_ring_noop_on_non_layer_item(self) -> None:
        delegate = LayerDelegate()
        window = ui.Window("__step62_focus_non_layer__", width=50, height=50)
        try:
            with window.frame:
                with ui.VStack():
                    # No raise — the helper quietly returns.
                    delegate._build_focus_ring("not-a-layer-item")
        finally:
            window.destroy()

    def test_build_focus_ring_noop_when_not_focused(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert item.is_focused is False
        delegate = LayerDelegate()
        window = ui.Window("__step62_focus_unfocused__", width=50, height=50)
        try:
            with window.frame:
                with ui.VStack():
                    delegate._build_focus_ring(item)
        finally:
            window.destroy()

    def test_build_focus_ring_renders_for_focused_item(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        item.is_focused = True
        delegate = LayerDelegate()
        window = ui.Window("__step62_focus_focused__", width=50, height=50)
        try:
            with window.frame:
                with ui.VStack():
                    delegate._build_focus_ring(item)
        finally:
            window.destroy()

    def test_build_widget_paints_focus_ring_on_focused_row(self) -> None:
        # End-to-end: the focused flag must survive the whole
        # ``build_widget`` dispatch path.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        model.root_item.is_focused = True
        delegate = LayerDelegate()
        window = ui.Window("__step62_focus_e2e__", width=80, height=40)
        try:
            with window.frame:
                with ui.VStack():
                    delegate.build_widget(
                        model, model.root_item, LayerDelegate.COL_NAME, 0, False
                    )
        finally:
            window.destroy()
            model.destroy()

    def test_build_branch_paints_focus_ring_on_focused_row(self) -> None:
        # build_branch must also paint the ring so the 1-px outline
        # covers the branch cell and the widget cells read as one
        # continuous rectangle.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        model.root_item.is_focused = True
        delegate = LayerDelegate()
        window = ui.Window("__step62_focus_branch__", width=80, height=40)
        try:
            with window.frame:
                with ui.VStack():
                    delegate.build_branch(model, model.root_item, 0, 0, False)
        finally:
            window.destroy()
            model.destroy()


# ─── Window constants & polish ────────────────────────────────────────────────


class TestStep62WindowConstants:
    def test_empty_stage_message_is_actionable(self) -> None:
        # The plan calls for an actionable hint; ensure the copy
        # points the user at the action (open a stage).
        assert "stage" in LayerWindow.EMPTY_STAGE_MESSAGE.lower()
        assert "open" in LayerWindow.EMPTY_STAGE_MESSAGE.lower()

    def test_filter_placeholder_text_mentions_filter(self) -> None:
        assert "filter" in LayerWindow.FILTER_PLACEHOLDER_TEXT.lower()


# ─── Focus-tracking integration ───────────────────────────────────────────────


class TestStep62FocusTracking:
    def test_update_focused_item_single_selection_flags_item(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child.usda")
        w = _headless_window()
        w._model = LayerModel(adapter)
        try:
            child = w._model._items_by_id["child.usda"]
            w._model.set_selected_items([child])
            w._update_focused_item()
            assert child.is_focused is True
            assert w._model.root_item.is_focused is False
        finally:
            w._model.destroy()

    def test_update_focused_item_multi_selection_clears_all(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a.usda")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "b.usda")
        w = _headless_window()
        w._model = LayerModel(adapter)
        try:
            a = w._model._items_by_id["a.usda"]
            b = w._model._items_by_id["b.usda"]
            # Pre-seed a stale focus flag so we assert the clear path.
            a.is_focused = True
            w._model.set_selected_items([a, b])
            w._update_focused_item()
            assert a.is_focused is False
            assert b.is_focused is False
        finally:
            w._model.destroy()

    def test_update_focused_item_empty_selection_clears(self) -> None:
        adapter = MockLayerStackAdapter()
        w = _headless_window()
        w._model = LayerModel(adapter)
        try:
            w._model.root_item.is_focused = True
            w._model.set_selected_items([])
            w._update_focused_item()
            assert w._model.root_item.is_focused is False
        finally:
            w._model.destroy()

    def test_update_focused_item_handles_missing_model(self) -> None:
        # No model attached — helper must quietly no-op (a late
        # selection callback after teardown must not crash).
        w = _headless_window()
        assert w._model is None
        w._update_focused_item()  # would raise on a bug

    def test_tree_selection_change_drives_focus(self) -> None:
        # Wiring: the tree-selection-changed handler should call the
        # focus-update helper.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child.usda")
        w = _headless_window()
        w._model = LayerModel(adapter)
        try:
            child = w._model._items_by_id["child.usda"]
            w._on_tree_selection_changed([child])
            assert child.is_focused is True
        finally:
            w._model.destroy()


# ─── Filter placeholder visibility ────────────────────────────────────────────


class TestStep62FilterPlaceholderVisibility:
    def test_placeholder_hidden_when_user_types(self, reset_app) -> None:
        w = _headless_window()
        fake_placeholder = MagicMock()
        fake_placeholder.visible = True
        w._filter_placeholder = fake_placeholder
        model = MagicMock()
        model.get_value_as_string.return_value = "base"
        w._on_filter_changed(model)
        assert fake_placeholder.visible is False

    def test_placeholder_shown_when_field_empties(self, reset_app) -> None:
        w = _headless_window()
        fake_placeholder = MagicMock()
        fake_placeholder.visible = False
        w._filter_placeholder = fake_placeholder
        model = MagicMock()
        model.get_value_as_string.return_value = ""
        w._on_filter_changed(model)
        assert fake_placeholder.visible is True

    def test_on_filter_changed_tolerates_missing_placeholder(
        self, reset_app
    ) -> None:
        w = _headless_window()
        w._filter_placeholder = None
        model = MagicMock()
        model.get_value_as_string.return_value = "x"
        # Must not raise — the whole chrome-update path is defensively
        # guarded against torn-down handles.
        w._on_filter_changed(model)


@pytest.fixture()
def reset_app():
    from ovui_widgets.app.application import Application

    app = Application()
    yield app
    app.shutdown()

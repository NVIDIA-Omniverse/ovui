# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 51 — name-search filter bar.

Covers:

- :meth:`LayerModel.filter_by_text` state transitions (active /
  cleared / same-text short-circuit / destroyed no-op).
- Case-insensitive substring match across layer display names.
- Ancestor promotion: a parent of a matching descendant stays visible
  via :attr:`LayerItem.child_filtered`.
- :meth:`LayerModel.get_item_children` filter passthrough for
  top-level rows and sublayer children.
- :meth:`LayerModel.has_any_filter_match` gating the empty-state
  overlay.
- :class:`LayerWindow` debounce, clear-button, and chrome wiring
  through ``Application.call_later``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import omni.ui as ui
import pytest

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.testing.mock_layer_stack import (
    ROOT_LAYER_IDENTIFIER,
    SESSION_LAYER_IDENTIFIER,
)
from ovwidgets.layers import LayerModel, LayerWindow
from ovwidgets.layers.style import LAYERS_STYLES

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _build_adapter_with_nested_sublayers() -> MockLayerStackAdapter:
    """Root has two branches:

        root
        ├── background_base.usda
        │   └── background_gradient.usda
        └── props_base.usda
    """
    adapter = MockLayerStackAdapter()
    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "background_base.usda",
        display_name="background_base.usda",
    )
    adapter.add_sublayer(
        "background_base.usda",
        "background_gradient.usda",
        display_name="background_gradient.usda",
    )
    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "props_base.usda",
        display_name="props_base.usda",
    )
    return adapter


def _can_create_window() -> bool:
    try:
        w = ui.Window("__probe_layers_step51__", width=10, height=10)
        w.destroy()
        return True
    except Exception:
        return False


_WINDOW_AVAILABLE = _can_create_window()
_skip_no_window = pytest.mark.skipif(
    not _WINDOW_AVAILABLE,
    reason="ui.Window creation not available without ui.init()",
)


# ─── LayerModel.filter_by_text — state transitions ───────────────────────────


class TestFilterByText:
    def test_default_filter_text_is_empty(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert model.filter_text == ""
        finally:
            model.destroy()

    def test_setting_filter_updates_text(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model.filter_by_text("base")
            assert model.filter_text == "base"
        finally:
            model.destroy()

    def test_empty_text_clears_filter(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model.filter_by_text("base")
            assert model.filter_text == "base"
            model.filter_by_text("")
            assert model.filter_text == ""
        finally:
            model.destroy()

    def test_none_treated_as_empty(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model.filter_by_text("base")
            model.filter_by_text(None)  # type: ignore[arg-type]
            assert model.filter_text == ""
        finally:
            model.destroy()

    def test_same_text_is_noop(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model.filter_by_text("base")
            # Capture events fired by a re-apply of the same text.
            events: list = []
            sub = model.subscribe_item_changed_fn(
                lambda _m, item: events.append(item)
            )
            try:
                model.filter_by_text("base")
                assert events == []
            finally:
                sub.unsubscribe()
        finally:
            model.destroy()

    def test_destroyed_model_filter_is_noop(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        model.destroy()
        # Must not raise or mutate internal state.
        model.filter_by_text("anything")
        assert model.filter_text == ""


# ─── Match semantics + ancestor propagation ──────────────────────────────────


class TestFilterSemantics:
    def test_case_insensitive_substring_match(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model.filter_by_text("PROPS")
            props = next(
                s
                for s in model.root_item.sublayers
                if s.identifier == "props_base.usda"
            )
            assert props.filtered is True
            assert props.child_filtered is False
        finally:
            model.destroy()

    def test_partial_substring_matches(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model.filter_by_text("gradient")
            bg = next(
                s
                for s in model.root_item.sublayers
                if s.identifier == "background_base.usda"
            )
            gradient = bg.sublayers[0]
            assert gradient.filtered is True
            assert gradient.child_filtered is False
        finally:
            model.destroy()

    def test_ancestor_stays_visible_when_child_matches(self) -> None:
        # Step 51's ancestor-promotion contract: a parent of a matched
        # row keeps ``child_filtered=True`` so the expansion path to
        # the match survives the filter.
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model.filter_by_text("gradient")
            bg = next(
                s
                for s in model.root_item.sublayers
                if s.identifier == "background_base.usda"
            )
            assert bg.filtered is False
            assert bg.child_filtered is True
            # Root is the common ancestor of every matching row, so
            # it always carries ``child_filtered`` when any descendant
            # matches.
            assert model.root_item.child_filtered is True
        finally:
            model.destroy()

    def test_no_match_leaves_tree_with_no_flags(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model.filter_by_text("zzzz_no_match_zzzz")
            for s in model.root_item.sublayers:
                assert s.filtered is False
                assert s.child_filtered is False
            assert model.root_item.filtered is False
            assert model.root_item.child_filtered is False
        finally:
            model.destroy()

    def test_clearing_filter_resets_every_flag(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model.filter_by_text("gradient")
            assert model.root_item.child_filtered is True
            model.filter_by_text("")
            assert model.root_item.filtered is False
            assert model.root_item.child_filtered is False
            for s in model.root_item.sublayers:
                assert s.filtered is False
                assert s.child_filtered is False
                for ss in s.sublayers:
                    assert ss.filtered is False
                    assert ss.child_filtered is False
        finally:
            model.destroy()


# ─── get_item_children gating ────────────────────────────────────────────────


class TestGetItemChildrenFilter:
    def test_filter_hides_non_matching_top_level_row(self) -> None:
        adapter = MockLayerStackAdapter(include_session=True)
        model = LayerModel(adapter)
        try:
            # The session layer is anonymous / off-disk — filtering by
            # a name that doesn't match either identifier hides both
            # top-level rows, and hides the session specifically when
            # the root matches.
            model.filter_by_text("root")
            top = model.get_item_children(None)
            identifiers = [c.identifier for c in top]
            assert ROOT_LAYER_IDENTIFIER in identifiers
            assert SESSION_LAYER_IDENTIFIER not in identifiers
        finally:
            model.destroy()

    def test_filter_keeps_matching_sublayer_and_hides_others(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model.filter_by_text("props")
            # Root is the only visible top-level row because it is
            # the (single-root) ancestor of the matching "props_base".
            top = model.get_item_children(None)
            assert [c.identifier for c in top] == [ROOT_LAYER_IDENTIFIER]
            model._settings.show_layer_contents = False  # drop prim specs
            children = model.get_item_children(model.root_item)
            assert [c.identifier for c in children] == ["props_base.usda"]
        finally:
            model.destroy()

    def test_filter_keeps_ancestor_path_to_match(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model.filter_by_text("gradient")
            model._settings.show_layer_contents = False
            top = model.get_item_children(None)
            assert [c.identifier for c in top] == [ROOT_LAYER_IDENTIFIER]
            root_children = model.get_item_children(model.root_item)
            ids = [c.identifier for c in root_children]
            # The matching subtree survives; the unrelated
            # ``props_base`` sibling is dropped.
            assert "background_base.usda" in ids
            assert "props_base.usda" not in ids
            bg = next(
                c for c in root_children
                if c.identifier == "background_base.usda"
            )
            bg_children = model.get_item_children(bg)
            assert [c.identifier for c in bg_children] == [
                "background_gradient.usda"
            ]
        finally:
            model.destroy()

    def test_no_filter_returns_every_sublayer(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model._settings.show_layer_contents = False
            root_children = model.get_item_children(model.root_item)
            ids = [c.identifier for c in root_children]
            assert "background_base.usda" in ids
            assert "props_base.usda" in ids
        finally:
            model.destroy()


# ─── has_any_filter_match — empty-state gating ───────────────────────────────


class TestHasAnyFilterMatch:
    def test_true_when_no_filter(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            assert model.has_any_filter_match() is True
        finally:
            model.destroy()

    def test_true_when_filter_has_at_least_one_match(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model.filter_by_text("props")
            assert model.has_any_filter_match() is True
        finally:
            model.destroy()

    def test_false_when_filter_rejects_everything(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model.filter_by_text("nothing_matches_this_long_token")
            assert model.has_any_filter_match() is False
        finally:
            model.destroy()


# ─── Structural events re-apply the filter ───────────────────────────────────


class TestFilterPersistsAcrossStructuralEvents:
    def test_added_sublayer_joins_match_set(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model.filter_by_text("props")
            # Add another matching sublayer — structural event should
            # mark the new row as matched without a second manual
            # ``filter_by_text`` call.
            adapter.add_sublayer(
                ROOT_LAYER_IDENTIFIER,
                "props_extra.usda",
                display_name="props_extra.usda",
            )
            props_extra = next(
                s
                for s in model.root_item.sublayers
                if s.identifier == "props_extra.usda"
            )
            assert props_extra.filtered is True
        finally:
            model.destroy()

    def test_set_adapter_preserves_filter(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        model = LayerModel(adapter)
        try:
            model.filter_by_text("props")
            new_adapter = _build_adapter_with_nested_sublayers()
            model.set_adapter(new_adapter)
            assert model.filter_text == "props"
            props = next(
                s
                for s in model.root_item.sublayers
                if s.identifier == "props_base.usda"
            )
            assert props.filtered is True
        finally:
            model.destroy()


# ─── LayerWindow — debounce + chrome ─────────────────────────────────────────


def _headless_window() -> LayerWindow:
    """Construct a LayerWindow bypassing ``super().__init__`` so we can
    exercise filter-bar callbacks without a live ``ui.Window``.

    Mirrors the pattern from ``test_property_filter._make_headless``.
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
    w._filter_placeholder = None  # Step 62
    w._pending_filter_handle = None
    w._empty_state_container = None
    w._empty_state_label = None
    return w


def _make_model_mock(text: str) -> MagicMock:
    m = MagicMock()
    m.get_value_as_string.return_value = text
    return m


@pytest.fixture()
def reset_app():
    from ovwidgets.app.application import Application
    Application._instance = None
    app = Application()
    yield app
    app.shutdown()


class TestWindowDebounce:
    def test_on_filter_changed_schedules_call_later(self, reset_app) -> None:
        w = _headless_window()
        w._on_filter_changed(_make_model_mock("base"))
        assert w._pending_filter_handle is not None

    def test_debounce_delay_is_150ms(self, reset_app) -> None:
        import time
        w = _headless_window()
        before = time.monotonic()
        w._on_filter_changed(_make_model_mock("base"))
        delay = w._pending_filter_handle._due_time - before
        assert abs(delay - 0.15) < 0.05

    def test_rapid_change_cancels_previous_timer(self, reset_app) -> None:
        w = _headless_window()
        w._on_filter_changed(_make_model_mock("b"))
        first = w._pending_filter_handle
        w._on_filter_changed(_make_model_mock("ba"))
        assert first.is_cancelled

    def test_timer_fires_applies_filter_to_model(self, reset_app) -> None:
        app = reset_app
        w = _headless_window()
        adapter = _build_adapter_with_nested_sublayers()
        w._model = LayerModel(adapter)
        try:
            w._on_filter_changed(_make_model_mock("props"))
            # Force the timer past-due and run one frame tick.
            w._pending_filter_handle._due_time = 0
            app._on_frame_update(0.0)
            assert w._model.filter_text == "props"
            assert w._pending_filter_handle is None
        finally:
            w._model.destroy()

    def test_apply_filter_clears_pending_handle(self, reset_app) -> None:
        w = _headless_window()
        mock_handle = MagicMock()
        w._pending_filter_handle = mock_handle
        w._apply_filter("foo")
        assert w._pending_filter_handle is None

    def test_on_filter_changed_toggles_clear_button_visibility(
        self, reset_app
    ) -> None:
        w = _headless_window()
        # Use MagicMocks as the icon / clear-button stand-ins so we
        # can assert the visibility flips without a real ovui widget.
        w._filter_clear_button = MagicMock()
        w._filter_icon = MagicMock()
        w._on_filter_changed(_make_model_mock("text"))
        assert w._filter_clear_button.visible is True
        assert w._filter_icon.name == "active"
        w._on_filter_changed(_make_model_mock(""))
        assert w._filter_clear_button.visible is False
        assert w._filter_icon.name == ""

    def test_clear_filter_resets_field_model(self) -> None:
        w = _headless_window()
        field = MagicMock()
        field.model = MagicMock()
        w._filter_field = field
        w._clear_filter()
        field.model.set_value.assert_called_once_with("")

    def test_headless_no_app_applies_synchronously(self) -> None:
        from ovwidgets.app.application import Application

        # Force no-instance state.
        Application._instance = None
        w = _headless_window()
        adapter = _build_adapter_with_nested_sublayers()
        w._model = LayerModel(adapter)
        try:
            w._on_filter_changed(_make_model_mock("props"))
            # No Application singleton → filter applied immediately,
            # no debounce handle scheduled.
            assert w._pending_filter_handle is None
            assert w._model.filter_text == "props"
        finally:
            w._model.destroy()


class TestWindowEmptyState:
    def test_empty_state_hidden_when_no_filter(self, reset_app) -> None:
        w = _headless_window()
        adapter = _build_adapter_with_nested_sublayers()
        w._model = LayerModel(adapter)
        try:
            container = MagicMock()
            w._empty_state_container = container
            w._update_empty_state()
            assert container.visible is False
        finally:
            w._model.destroy()

    def test_empty_state_shown_when_filter_rejects_everything(
        self, reset_app
    ) -> None:
        w = _headless_window()
        adapter = _build_adapter_with_nested_sublayers()
        w._model = LayerModel(adapter)
        try:
            container = MagicMock()
            w._empty_state_container = container
            w._model.filter_by_text("zzz_no_match_zzz")
            w._update_empty_state()
            assert container.visible is True
        finally:
            w._model.destroy()

    def test_empty_state_hidden_when_some_match(self, reset_app) -> None:
        w = _headless_window()
        adapter = _build_adapter_with_nested_sublayers()
        w._model = LayerModel(adapter)
        try:
            container = MagicMock()
            w._empty_state_container = container
            w._model.filter_by_text("props")
            w._update_empty_state()
            assert container.visible is False
        finally:
            w._model.destroy()


# ─── Style tokens ────────────────────────────────────────────────────────────


class TestFilterStyleTokens:
    def test_filter_background_present(self) -> None:
        assert "Layers.FilterBackground" in LAYERS_STYLES

    def test_filter_field_has_focus_and_default_border(self) -> None:
        assert "Layers.FilterField" in LAYERS_STYLES
        assert "Layers.FilterField:focused" in LAYERS_STYLES
        assert "border_color" in LAYERS_STYLES["Layers.FilterField"]

    def test_filter_icon_active_variant(self) -> None:
        assert "Layers.FilterIcon" in LAYERS_STYLES
        assert "Layers.FilterIcon::active" in LAYERS_STYLES

    def test_filter_clear_button_style(self) -> None:
        assert "Layers.FilterClearButton.Image" in LAYERS_STYLES

    def test_empty_state_style(self) -> None:
        assert "Layers.EmptyState" in LAYERS_STYLES


# ─── LayerWindow — full build path ───────────────────────────────────────────


@_skip_no_window
class TestWindowBuildPath:
    def test_build_creates_filter_field(self) -> None:
        adapter = _build_adapter_with_nested_sublayers()
        w = LayerWindow(services=MagicMock(), adapter=adapter)
        try:
            with w._window.frame:
                w._build_ui()
            assert w._filter_field is not None
            assert w._filter_clear_button is not None
            assert w._filter_icon is not None
        finally:
            w.destroy()

    def test_build_restores_filter_text_from_model(self) -> None:
        # When a filter was already set on the model (e.g. via a
        # set_adapter swap that preserved the filter), the new
        # StringField must pick it up on rebuild.
        adapter = _build_adapter_with_nested_sublayers()
        w = LayerWindow(services=MagicMock(), adapter=adapter)
        try:
            with w._window.frame:
                w._build_ui()
            assert w._model is not None
            w._model.filter_by_text("props")
            with w._window.frame:
                w._build_ui()
            assert w._filter_field is not None
            assert w._filter_field.model.get_value_as_string() == "props"
        finally:
            w.destroy()

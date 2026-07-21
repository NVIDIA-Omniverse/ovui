# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 27: PropertyWindow skeleton with filter bar and scroll area."""

import pytest

# ---------------------------------------------------------------------------
# Import / structure tests — always run (no omni.ui runtime needed)
# ---------------------------------------------------------------------------


class TestPropertyWindowImport:
    def test_can_import_property_widget(self):
        from ovui_widgets.property.window import PropertyWindow
        assert PropertyWindow is not None

    def test_is_managed_window_subclass(self):
        from ovui_widgets.common.managed_window import ManagedWindow
        from ovui_widgets.property.window import PropertyWindow
        assert issubclass(PropertyWindow, ManagedWindow)

    def test_has_set_adapter_method(self):
        from ovui_widgets.property.window import PropertyWindow
        assert callable(PropertyWindow.set_adapter)

    def test_has_set_selection_method(self):
        from ovui_widgets.property.window import PropertyWindow
        assert callable(PropertyWindow.set_selection)

    def test_has_rebuild_content_method(self):
        from ovui_widgets.property.window import PropertyWindow
        assert callable(PropertyWindow._rebuild_content)

    def test_has_build_groups_method(self):
        from ovui_widgets.property.window import PropertyWindow
        assert callable(PropertyWindow._build_groups)

    def test_has_clear_filter_method(self):
        from ovui_widgets.property.window import PropertyWindow
        assert callable(PropertyWindow._clear_filter)


class TestPropertyStylesExist:
    def test_styles_importable(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert PROPERTY_STYLES is not None

    def test_legacy_filter_keys_removed(self):
        """Step 0.4 retired Property.FilterBar/FilterField/FilterClear in favour
        of the canonical ``Property.SearchField`` key."""
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "Property.FilterBar" not in PROPERTY_STYLES
        assert "Property.FilterField" not in PROPERTY_STYLES
        assert "Property.FilterClear" not in PROPERTY_STYLES

    def test_search_field_has_background_color(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "background_color" in PROPERTY_STYLES["Property.SearchField"]

    def test_search_field_has_text_color(self):
        """``Property.SearchField`` sets ``color`` for the field text."""
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "color" in PROPERTY_STYLES["Property.SearchField"]

    def test_search_field_has_border_radius(self):
        """``Property.SearchField`` sets ``border_radius``."""
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "border_radius" in PROPERTY_STYLES["Property.SearchField"]

    def test_search_field_pressed_has_focused_border(self):
        """``Property.SearchField:pressed`` sets the focused-ring border."""
        from ovui_widgets.property.style import PROPERTY_STYLES
        pressed = PROPERTY_STYLES["Property.SearchField:pressed"]
        assert "border_width" in pressed
        assert "border_color" in pressed

    def test_value_field_focused_named_variant_uses_focused_border(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        focused = PROPERTY_STYLES["Property.ValueField::focused"]
        assert focused["border_color"] == "border_focused"
        assert focused["background_color"] == "background_value_field_editing"

    def test_value_field_focused_pseudo_state_uses_focused_border(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        focused = PROPERTY_STYLES["Property.ValueField:focused"]
        assert focused["border_color"] == "border_focused"
        assert focused["background_color"] == "background_value_field_editing"


class TestPropertyFilterPillStep3:
    """Design Step 3 — the Property filter pill. Mirrors
    :class:`TestStageFilterPillStep3` in ``test_stage_filter.py`` so the
    two filter bars stay sibling-identical. The pill is the outer
    ``Rectangle`` (``Property.SearchField``); the inner borderless
    ``StringField`` styles as ``Property.SearchFieldInput``.
    """

    def test_property_search_field_uses_background_field_token(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert PROPERTY_STYLES["Property.SearchField"]["background_color"] == (
            "background_field"
        )

    def test_property_search_field_uses_border_default(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert PROPERTY_STYLES["Property.SearchField"]["border_color"] == (
            "border_default"
        )

    def test_property_search_field_uses_radius_small(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert PROPERTY_STYLES["Property.SearchField"]["border_radius"] == (
            "radius_small"
        )

    def test_property_search_field_has_1px_border(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert PROPERTY_STYLES["Property.SearchField"]["border_width"] == 0

    def test_property_search_field_focused_named_variant(self):
        """``::focused`` (not ``:focused``) — named variant toggled via
        ``Rectangle.name = "focused"``."""
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "Property.SearchField::focused" in PROPERTY_STYLES
        assert PROPERTY_STYLES["Property.SearchField::focused"]["border_color"] == (
            "border_focused"
        )

    def test_property_search_field_border_uses_border_default(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert PROPERTY_STYLES["Property.SearchFieldBorder"]["background_color"] == (
            "border_default"
        )

    def test_property_search_field_border_focused_uses_border_focused(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        focused = PROPERTY_STYLES["Property.SearchFieldBorder::focused"]
        assert focused["background_color"] == "border_focused"

    def test_property_search_field_input_is_transparent(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "Property.SearchFieldInput" in PROPERTY_STYLES
        assert PROPERTY_STYLES["Property.SearchFieldInput"]["background_color"] == (
            "transparent"
        )
        assert PROPERTY_STYLES["Property.SearchFieldInput"]["border_width"] == 0

    def test_property_search_field_input_has_text_primary(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert PROPERTY_STYLES["Property.SearchFieldInput"]["color"] == "text_primary"

    def test_property_search_field_placeholder_style_registered(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        style = PROPERTY_STYLES["Property.SearchFieldPlaceholder"]
        assert style["color"] == "text_disabled"
        assert "font_size" in style

    def test_property_inactive_hints_use_disabled_text(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert PROPERTY_STYLES["Property.EmptyLabel"]["color"] == "text_disabled"
        assert PROPERTY_STYLES["Property.FallbackAttribute"]["color"] == "text_disabled"

    def test_property_selection_header_styles_match_step12_tokens(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert PROPERTY_STYLES["Property.SelectionHeader"]["color"] == "accent_primary"
        assert PROPERTY_STYLES["Property.SelectionHeader.Title"]["color"] == (
            "text_primary"
        )
        assert PROPERTY_STYLES["Property.SelectionHeader.Path"]["color"] == (
            "text_secondary"
        )

    def test_property_and_stage_share_pill_tokens(self):
        """Sibling-identical: pill bg / border / radius values match token-for-token."""
        from ovui_widgets.property.style import PROPERTY_STYLES
        from ovui_widgets.stage.style import STAGE_STYLES
        ps = PROPERTY_STYLES["Property.SearchField"]
        ss = STAGE_STYLES["Stage.FilterField"]
        for key in ("background_color", "border_color", "border_radius", "border_width"):
            assert ps[key] == ss[key], (
                f"Step 3 token mismatch at {key!r}: "
                f"Property={ps[key]!r} vs Stage={ss[key]!r}"
            )


class TestSrd22_2Styles:
    """PROPERTY_STYLES defines five canonical Property.* style selectors."""

    def test_group_frame_exists(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "Property.GroupFrame" in PROPERTY_STYLES

    def test_group_frame_hover_and_pressed_variants(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "Property.GroupFrame:hovered" in PROPERTY_STYLES
        assert "Property.GroupFrame:pressed" in PROPERTY_STYLES

    def test_label_column_exists(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "Property.LabelColumn" in PROPERTY_STYLES
        assert "Property.AttributeLabel" in PROPERTY_STYLES

    def test_label_column_ambiguous_and_mixed_variants(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "Property.LabelColumn::ambiguous" in PROPERTY_STYLES
        assert "Property.LabelColumn::mixed" in PROPERTY_STYLES
        assert "Property.AttributeLabel::ambiguous" in PROPERTY_STYLES
        assert "Property.AttributeLabel::mixed" in PROPERTY_STYLES

    def test_value_field_exists(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "Property.ValueField" in PROPERTY_STYLES

    def test_value_field_uses_step14_tokens(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        style = PROPERTY_STYLES["Property.ValueField"]
        assert style["background_color"] == "background_value_field"
        assert style["border_color"] == "property_value_border"
        assert style["border_radius"] == "radius_small"
        assert style["border_width"] == 1

    def test_mixed_overlay_exists(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "Property.MixedOverlay" in PROPERTY_STYLES

    def test_search_field_exists(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "Property.SearchField" in PROPERTY_STYLES

    def test_search_field_pressed_variant(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "Property.SearchField:pressed" in PROPERTY_STYLES

    def test_component_separator_exists(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "Property.ComponentSeparator" in PROPERTY_STYLES

    @pytest.mark.parametrize("ch", ["X", "Y", "Z", "W"])
    def test_channel_label_base_styles_exist(self, ch):
        """property attribute builder behavior colour-coding: one style type per axis channel."""
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert f"Property.ChannelLabel.{ch}" in PROPERTY_STYLES

    @pytest.mark.parametrize("ch", ["X", "Y", "Z", "W"])
    def test_channel_label_mixed_states_exist(self, ch):
        """Ambiguous channels override the axis colour with the warning colour."""
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert f"Property.ChannelLabel.{ch}::mixed" in PROPERTY_STYLES

    @pytest.mark.parametrize(
        ("ch", "palette_name"),
        [("X", "channel_x"), ("Y", "channel_y"),
         ("Z", "channel_z"), ("W", "channel_w")],
    )
    def test_channel_label_style_references_palette(self, ch, palette_name):
        """Each Property.ChannelLabel.* style must point at the matching
        ``channel_{x,y,z,w}`` palette shade, not a raw ARGB int."""
        from ovui_widgets.property.style import PROPERTY_STYLES
        style = PROPERTY_STYLES[f"Property.ChannelLabel.{ch}"]
        assert "color" in style
        # cl.xxx returns a shade-name string, not an int
        assert isinstance(style["color"], str)
        assert style["color"] == palette_name


# ---------------------------------------------------------------------------
# Headless behaviour tests — bypass ManagedWindow.__init__ via __new__
# ---------------------------------------------------------------------------


def _make_headless():
    """Return a PropertyWindow instance with no live ui.Window.

    Step 6.2: the bypass-``__init__`` factory now also constructs a
    default :class:`AttributesWidget` bound back to ``w`` so the thin
    delegate methods on :class:`PropertyWindow` (``_build_groups`` etc.)
    resolve. The widget isn't registered in ``w._widgets`` by default
    because many tests in this module pin behaviour with an empty
    widget list.
    """
    from ovui_widgets.property.widget.attributes_widget import AttributesWidget
    from ovui_widgets.property.window import PropertyWindow
    w = PropertyWindow.__new__(PropertyWindow)
    w._adapter = None
    w._selection = []
    w._filter_text = ""
    w._pending_filter_handle = None
    w._filter_field = None
    w._filter_border_rect = None
    w._filter_rect = None
    w._filter_placeholder = None
    w._filter_icon = None
    w._filter_clear_button = None
    w._content = None
    w._window = None
    w._group_collapse_state = {}
    w._active_context_menu = None
    w._bus_sub = None
    w._stage_adapter = None
    w._stage_change_sub = None
    w._undo_manager_ref = None
    w._widgets = []
    w._default_attributes = AttributesWidget(w)
    return w


class TestPropertyWindowHeadless:
    def test_creates_with_no_window_no_crash(self):
        w = _make_headless()
        assert w is not None

    def test_filter_field_starts_none(self):
        w = _make_headless()
        assert w._filter_field is None

    def test_content_starts_none(self):
        w = _make_headless()
        assert w._content is None

    def test_adapter_starts_none(self):
        w = _make_headless()
        assert w._adapter is None

    def test_selection_starts_empty(self):
        w = _make_headless()
        assert w._selection == []

    def test_set_adapter_none_stores_none(self):
        w = _make_headless()
        w.set_adapter(None)
        assert w._adapter is None

    def test_set_adapter_stores_adapter(self):
        w = _make_headless()

        class _FakeAdapter:
            pass

        fa = _FakeAdapter()
        w.set_adapter(fa)
        assert w._adapter is fa

    def test_set_selection_stores_paths(self):
        w = _make_headless()
        w.set_selection(["/World/Sphere"])
        assert w._selection == ["/World/Sphere"]

    def test_set_selection_empty_stores_empty_list(self):
        w = _make_headless()
        w.set_selection([])
        assert w._selection == []

    def test_rebuild_content_called_on_set_adapter(self):
        w = _make_headless()
        calls = []
        w._rebuild_content = lambda: calls.append(1)
        w.set_adapter(None)
        assert calls == [1]

    def test_rebuild_content_called_on_set_selection(self):
        w = _make_headless()
        calls = []
        w._rebuild_content = lambda: calls.append(1)
        w.set_selection(["/World/Sphere"])
        assert calls == [1]

    def test_rebuild_content_no_op_when_content_is_none(self):
        w = _make_headless()
        w._rebuild_content()  # must not raise

    # QA BUG-002: empty-selection placeholder wiring.
    def test_build_empty_selection_placeholder_method_exists(self):
        from ovui_widgets.property.window import PropertyWindow
        assert callable(PropertyWindow._build_empty_selection_placeholder)

    def test_empty_selection_invokes_placeholder_helper(self):
        w = _make_headless()
        calls = []

        class _FakeContent:
            def clear(self): pass
            def __enter__(self): return self
            def __exit__(self, *_): pass

        w._content = _FakeContent()
        w._scroll_preserver = None
        w._build_empty_selection_placeholder = lambda: calls.append("empty")
        w._rebuild_content()
        assert calls == ["empty"]

    def test_non_empty_selection_skips_placeholder_helper(self):
        w = _make_headless()
        calls = []

        class _FakeContent:
            def clear(self): pass
            def __enter__(self): return self
            def __exit__(self, *_): pass

        w._content = _FakeContent()
        w._scroll_preserver = None
        w._build_empty_selection_placeholder = lambda: calls.append("empty")
        w._build_selection_header = lambda: calls.append("header")
        w._build_registered_widgets = lambda: calls.append("widgets")
        w._selection = ["/World/Foo"]

        class _Adapter:
            def get_attribute_names(self): return []
        w._adapter = _Adapter()
        w._rebuild_content()
        assert "empty" not in calls
        assert calls == ["header", "widgets"]

    def test_selection_header_info_uses_stage_adapter(self):
        w = _make_headless()
        item = object()

        class _StageAdapter:
            def get_item_at_path(self, path):
                assert path == "/World/DomeLight"
                return item

            def get_display_name(self, item_arg):
                assert item_arg is item
                return "DomeLight"

            def get_type_name(self, item_arg):
                assert item_arg is item
                return "DomeLight"

        w._stage_adapter = _StageAdapter()
        w._selection = ["/World/DomeLight"]

        info = w._get_selection_header_info()

        assert info is not None
        assert info.prim_type == "DOMELIGHT"
        assert info.name == "DomeLight"
        assert info.path == "/World/DomeLight"

    def test_selection_header_builds_type_label_with_accent_style(self, monkeypatch):
        from ovui_widgets.property import window as window_mod
        from ovui_widgets.property.window import _SelectionHeaderInfo

        class _Ctx:
            def __enter__(self): return self
            def __exit__(self, *_): return False

        w = _make_headless()
        w._get_selection_header_info = lambda: _SelectionHeaderInfo(
            prim_type="CUBE",
            name="Cube",
            path="/World/Cube",
        )
        labels = []
        w._build_selection_header_label = (
            lambda text, style, height: labels.append((text, style, height))
        )
        monkeypatch.setattr(window_mod.ui, "VStack", lambda **kwargs: _Ctx())
        monkeypatch.setattr(window_mod.ui, "Spacer", lambda **kwargs: None)
        monkeypatch.setattr(window_mod.ui, "Rectangle", lambda **kwargs: None)

        w._build_selection_header()

        assert labels[0][0] == "CUBE"
        assert labels[0][1] == "Property.SelectionHeader"

    def test_selection_header_info_hidden_without_selection(self):
        w = _make_headless()
        w._selection = []
        assert w._get_selection_header_info() is None

    def test_selection_header_info_hidden_for_multi_selection(self):
        w = _make_headless()
        w._selection = ["/World/A", "/World/B"]
        assert w._get_selection_header_info() is None

    def test_selection_header_info_hidden_without_stage_item(self):
        w = _make_headless()

        class _StageAdapter:
            def get_item_at_path(self, path):
                return None

        w._stage_adapter = _StageAdapter()
        w._selection = ["/World/Missing"]
        assert w._get_selection_header_info() is None

    def test_clear_filter_no_crash_when_field_is_none(self):
        w = _make_headless()
        w._clear_filter()  # must not raise

    def test_clear_filter_resets_field_to_empty(self):
        w = _make_headless()
        set_calls = []

        class _FakeModel:
            def set_value(self, v):
                set_calls.append(v)

        class _FakeField:
            model = _FakeModel()

        w._filter_field = _FakeField()
        w._clear_filter()
        assert set_calls == [""]

    def test_filter_chrome_state_hides_placeholder_when_text_exists(self):
        w = _make_headless()

        class _FakeChrome:
            visible = True
            name = ""

        w._filter_placeholder = _FakeChrome()
        w._filter_clear_button = _FakeChrome()
        w._filter_icon = _FakeChrome()
        w._set_filter_chrome_state(False)
        assert w._filter_placeholder.visible is True
        assert w._filter_clear_button.visible is False
        assert w._filter_icon.name == ""
        w._set_filter_chrome_state(True)
        assert w._filter_placeholder.visible is False
        assert w._filter_clear_button.visible is True
        assert w._filter_icon.name == "active"


# ---------------------------------------------------------------------------
# Widget creation tests — require ui.Window to work without ui.init()
# ---------------------------------------------------------------------------


def _can_create_window() -> bool:
    try:
        import omni.ui as ui
        w = ui.Window("__probe__", width=10, height=10)
        w.destroy()
        return True
    except Exception:
        return False


_WINDOW_AVAILABLE = _can_create_window()
_skip_no_window = pytest.mark.skipif(
    not _WINDOW_AVAILABLE, reason="ui.Window creation not available without ui.init()"
)


@_skip_no_window
class TestPropertyWindowCreation:
    def test_creates_without_adapter_no_crash(self):
        from ovui_widgets.property.window import PropertyWindow
        w = PropertyWindow()
        w.destroy()

    def test_title_is_property_inspector(self):
        from ovui_widgets.property.window import PropertyWindow
        w = PropertyWindow()
        assert w.title == "Property Inspector"
        w.destroy()

    def test_set_adapter_none_no_crash(self):
        from ovui_widgets.property.window import PropertyWindow
        w = PropertyWindow()
        w.set_adapter(None)
        w.destroy()

    def test_set_selection_empty_no_crash(self):
        from ovui_widgets.property.window import PropertyWindow
        w = PropertyWindow()
        w.set_selection([])
        w.destroy()

    def test_filter_field_attr_starts_none_headless(self):
        from ovui_widgets.property.window import PropertyWindow
        w = PropertyWindow()
        # _build_ui runs lazily in live loop; _filter_field stays None at construction
        assert w._filter_field is None
        w.destroy()

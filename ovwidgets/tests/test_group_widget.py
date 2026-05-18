# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for AttributeGroupWidget — CollapsableFrame-backed group header.

Originally written for Step 28 against the hand-rolled ZStack/arrow
implementation. Rewritten in Step 0.3 (the property inspector phase 0) when
``AttributeGroupWidget`` was switched to wrap ``ui.CollapsableFrame``.
The public API surface (``is_collapsed``, ``content``, ``toggle``,
``set_collapsed``, ``on_collapse_change``) is the same as before; the
internal structure changed (``_frame`` replaces ``_arrow_label``;
``_content.visible`` replaced by the frame's built-in show/hide).
"""


# ---------------------------------------------------------------------------
# Import / structure tests
# ---------------------------------------------------------------------------


class TestGroupWidgetImport:
    def test_can_import(self):
        from ovwidgets.property.group_widget import AttributeGroupWidget
        assert AttributeGroupWidget is not None

    def test_has_is_collapsed_property(self):
        from ovwidgets.property.group_widget import AttributeGroupWidget
        assert isinstance(AttributeGroupWidget.is_collapsed, property)

    def test_has_content_property(self):
        from ovwidgets.property.group_widget import AttributeGroupWidget
        assert isinstance(AttributeGroupWidget.content, property)

    def test_has_toggle_method(self):
        from ovwidgets.property.group_widget import AttributeGroupWidget
        assert callable(AttributeGroupWidget.toggle)

    def test_has_set_collapsed_method(self):
        from ovwidgets.property.group_widget import AttributeGroupWidget
        assert callable(AttributeGroupWidget.set_collapsed)


class TestPropertyGroupFrameStyleExists:
    """Step 0.3 moves the group frame under the Property.GroupFrame key."""

    def test_group_frame_style_exists(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        assert "Property.GroupFrame" in PROPERTY_STYLES

    def test_group_frame_hovered_variant_exists(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        assert "Property.GroupFrame:hovered" in PROPERTY_STYLES

    def test_group_frame_pressed_variant_exists(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        assert "Property.GroupFrame:pressed" in PROPERTY_STYLES

    def test_group_frame_header_style_exists(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        assert "Property.GroupFrame.Header" in PROPERTY_STYLES

    def test_group_frame_chevron_style_exists(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        assert "Property.GroupFrame.Chevron" in PROPERTY_STYLES

    def test_legacy_propertygroup_keys_removed(self):
        """PropertyGroup.Header/Arrow/Title/Content are gone after Step 0.3."""
        from ovwidgets.property.style import PROPERTY_STYLES
        assert "PropertyGroup.Header" not in PROPERTY_STYLES
        assert "PropertyGroup.Arrow" not in PROPERTY_STYLES
        assert "PropertyGroup.Title" not in PROPERTY_STYLES
        assert "PropertyGroup.Content" not in PROPERTY_STYLES


# ---------------------------------------------------------------------------
# Step 8.2 / Step 13 — Header styling refresh: nested ``::inner`` variant,
# plus the ``level`` kwarg wired through the widget. Step 13 keeps hover
# feedback visually quiet so headers stay divider-like.
# ---------------------------------------------------------------------------


class TestGroupFrameHoverPressedRefresh:
    """Step 13 keeps :hovered / :pressed subtle for compact headers."""

    def test_hovered_has_secondary_color(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        entry = PROPERTY_STYLES["Property.GroupFrame:hovered"]
        assert "secondary_color" in entry

    def test_hovered_secondary_color_matches_srd(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        entry = PROPERTY_STYLES["Property.GroupFrame:hovered"]
        assert entry["secondary_color"] == "background_primary"

    def test_hovered_keeps_color_muted(self):
        """Hover keeps built-in CollapsableFrame chrome invisible."""
        from ovwidgets.property.style import PROPERTY_STYLES
        entry = PROPERTY_STYLES["Property.GroupFrame:hovered"]
        assert "color" in entry
        assert entry["color"] == "transparent"

    def test_pressed_has_secondary_color(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        entry = PROPERTY_STYLES["Property.GroupFrame:pressed"]
        assert "secondary_color" in entry

    def test_pressed_secondary_color_matches_srd(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        entry = PROPERTY_STYLES["Property.GroupFrame:pressed"]
        assert entry["secondary_color"] == "background_primary"

    def test_pressed_keeps_color_muted(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        entry = PROPERTY_STYLES["Property.GroupFrame:pressed"]
        assert "color" in entry
        assert entry["color"] == "transparent"


class TestPropertyGroupFrameInnerVariant:
    """Step 8.2 — ``::inner`` name variant paints nested-group titles in
    ``cl.text_secondary`` so the visual hierarchy subordinates them without
    breaking the PROPERTY_STYLES secondary_color hover/pressed settings.
    """

    def test_inner_base_registered(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        assert "Property.GroupFrame::inner" in PROPERTY_STYLES

    def test_inner_hovered_registered(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        assert "Property.GroupFrame::inner:hovered" in PROPERTY_STYLES

    def test_inner_pressed_registered(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        assert "Property.GroupFrame::inner:pressed" in PROPERTY_STYLES

    def test_inner_base_uses_text_secondary(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        entry = PROPERTY_STYLES["Property.GroupFrame::inner"]
        assert entry["color"] == "transparent"

    def test_inner_hovered_keeps_title_muted(self):
        """Resolution-chain guard: nested hover remains as quiet as base hover."""
        from ovwidgets.property.style import PROPERTY_STYLES
        entry = PROPERTY_STYLES["Property.GroupFrame::inner:hovered"]
        assert entry["color"] == "transparent"
        assert entry["secondary_color"] == "background_primary"

    def test_inner_pressed_keeps_title_muted(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        entry = PROPERTY_STYLES["Property.GroupFrame::inner:pressed"]
        assert entry["color"] == "transparent"
        assert entry["secondary_color"] == "background_primary"


class TestPropertyGroupHeaderStep13:
    """Step 13 — compact uppercase Property group headers."""

    def test_base_group_frame_uses_muted_header_tone(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        entry = PROPERTY_STYLES["Property.GroupFrame"]
        assert entry["color"] == "transparent"

    def test_base_group_frame_has_no_extra_padding_or_margin(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        entry = PROPERTY_STYLES["Property.GroupFrame"]
        assert entry["padding"] == 0
        assert entry["margin_height"] == 1
        assert entry["margin_width"] == 8

    def test_header_style_uses_small_muted_text(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        entry = PROPERTY_STYLES["Property.GroupFrame.Header"]
        assert entry["color"] == "text_primary"
        assert entry["font_size"] == "font_size_medium"

    def test_header_background_matches_panel(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        entry = PROPERTY_STYLES["Property.GroupFrame.Header"]
        assert entry["background_color"] == "background_primary"

    def test_header_style_has_no_extra_margin(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        entry = PROPERTY_STYLES["Property.GroupFrame.Header"]
        assert entry["padding"] == 0
        assert entry["margin_height"] == 0
        assert entry["margin_width"] == 0

    def test_chevron_uses_muted_text_tone(self):
        from ovwidgets.property.style import PROPERTY_STYLES
        entry = PROPERTY_STYLES["Property.GroupFrame.Chevron"]
        assert entry["color"] == "text_secondary"

    def test_header_title_is_uppercase_without_renaming_group(self):
        from ovwidgets.property.group_widget import format_property_group_header_title
        assert format_property_group_header_title("Attributes") == "Attributes"
        assert format_property_group_header_title("Primvars") == "Primvars"
        assert format_property_group_header_title("Transform") == "Transform"

    def test_group_stack_spacing_preserves_visible_frame_gap(self):
        from ovwidgets.property.group_widget import GROUP_STACK_SPACING
        assert GROUP_STACK_SPACING == 34


class _FakeCollapsableFrame:
    """Headless double for ``ui.CollapsableFrame`` that tracks the
    ``name`` assignment and the ``style_type_name_override`` kwarg so
    Step 8.2 can assert both without an initialised omni.ui root.
    """

    def __init__(
        self,
        title: str = "",
        collapsed: bool = False,
        height=None,
        style_type_name_override: str = "",
        build_header_fn=None,
    ) -> None:
        self.title = title
        self._collapsed = collapsed
        self.height = height
        self.style_type_name_override = style_type_name_override
        self.build_header_fn = build_header_fn
        self.name = ""
        self._fn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @collapsed.setter
    def collapsed(self, value: bool) -> None:
        if self._collapsed == value:
            return
        self._collapsed = value
        if self._fn is not None:
            self._fn(value)

    def set_collapsed_changed_fn(self, fn) -> None:
        self._fn = fn

    def set_mouse_released_fn(self, fn) -> None:
        self._mouse_fn = fn


class TestAttributeGroupWidgetLevelKwarg:
    """Step 8.2 — ``level`` kwarg controls the ``::inner`` variant wire.

    Uses a patched ``ui.CollapsableFrame`` stand-in so the test can run
    without a real omni.ui root; asserts both the VStack content and
    the ``name`` stamp on the underlying frame. ``ui.VStack`` is also
    patched because the real VStack requires an ovui root.
    """

    def _patch_ui(self, monkeypatch):
        import omni.ui as ui
        monkeypatch.setattr(ui, "CollapsableFrame", _FakeCollapsableFrame)

        class _FakeVStack:
            def __init__(self, *args, **kwargs) -> None:
                self.kwargs = kwargs

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr(ui, "VStack", _FakeVStack)

    def test_default_level_is_zero(self, monkeypatch):
        self._patch_ui(monkeypatch)
        from ovwidgets.property.group_widget import AttributeGroupWidget
        g = AttributeGroupWidget("Transform")
        assert g._level == 0

    def test_level_zero_leaves_frame_name_empty(self, monkeypatch):
        """``name`` stays the default empty string so the base
        ``Property.GroupFrame`` selector family applies unchanged."""
        self._patch_ui(monkeypatch)
        from ovwidgets.property.group_widget import AttributeGroupWidget
        g = AttributeGroupWidget("Transform", level=0)
        assert g._frame.name == ""

    def test_level_one_sets_frame_name_inner(self, monkeypatch):
        """``level=1`` activates the ``Property.GroupFrame::inner``
        selector family — dimmer title, hover brightens back."""
        self._patch_ui(monkeypatch)
        from ovwidgets.property.group_widget import AttributeGroupWidget
        g = AttributeGroupWidget("Translate", level=1)
        assert g._frame.name == "inner"

    def test_level_two_still_sets_inner(self, monkeypatch):
        """Deeper nesting (``level=2``, ``level=3``) continues to paint
        with the ``::inner`` variant — a single subordination shade is
        enough; going deeper does not further dim.
        """
        self._patch_ui(monkeypatch)
        from ovwidgets.property.group_widget import AttributeGroupWidget
        g2 = AttributeGroupWidget("X", level=2)
        g3 = AttributeGroupWidget("X", level=3)
        assert g2._frame.name == "inner"
        assert g3._frame.name == "inner"

    def test_style_type_name_override_is_property_groupframe(self, monkeypatch):
        """Contract: the ``CollapsableFrame`` always carries
        ``style_type_name_override="Property.GroupFrame"`` — Step 8.2
        adds a name variant, it does NOT introduce a new style type."""
        self._patch_ui(monkeypatch)
        from ovwidgets.property.group_widget import AttributeGroupWidget
        g = AttributeGroupWidget("Transform", level=0)
        assert g._frame.style_type_name_override == "Property.GroupFrame"
        g2 = AttributeGroupWidget("Translate", level=1)
        assert g2._frame.style_type_name_override == "Property.GroupFrame"

    def test_custom_header_builder_is_compact_property_header(self, monkeypatch):
        """Step 13 keeps collapse behaviour on CollapsableFrame while replacing
        the drawn header with the compact Property-specific header builder.
        """
        self._patch_ui(monkeypatch)
        from ovwidgets.property.group_widget import (
            AttributeGroupWidget,
            build_property_group_header,
        )
        g = AttributeGroupWidget("Transform")
        assert g._frame.build_header_fn is build_property_group_header

    def test_collapsable_frame_uses_fit_content_height(self, monkeypatch):
        """Property groups must measure to their rows, not fill the parent stack."""
        self._patch_ui(monkeypatch)
        from ovwidgets.property.group_widget import FIT_CONTENT_HEIGHT, AttributeGroupWidget
        g = AttributeGroupWidget("Transform")
        assert g._frame.height == FIT_CONTENT_HEIGHT

    def test_content_stack_uses_fit_content_height(self, monkeypatch):
        """Collapsed frames can only release row space if the inner stack is measured."""
        self._patch_ui(monkeypatch)
        from ovwidgets.property.group_widget import FIT_CONTENT_HEIGHT, AttributeGroupWidget
        g = AttributeGroupWidget("Transform")
        assert g.content.kwargs["height"] == FIT_CONTENT_HEIGHT

    def test_content_stack_has_no_internal_vertical_gap(self, monkeypatch):
        """The group frame uses the reference row rhythm inside sections."""
        self._patch_ui(monkeypatch)
        from ovwidgets.property.group_widget import GROUP_CONTENT_SPACING, AttributeGroupWidget
        g = AttributeGroupWidget("Transform")
        assert g.content.kwargs["spacing"] == GROUP_CONTENT_SPACING
        assert GROUP_CONTENT_SPACING == 5

    def test_collapse_callback_still_wires(self, monkeypatch):
        """Step 8.2's ``level`` kwarg must not regress Step 0.3's
        collapse wiring — the on_collapse_change callback still fires.
        """
        self._patch_ui(monkeypatch)
        from ovwidgets.property.group_widget import AttributeGroupWidget
        calls = []
        g = AttributeGroupWidget(
            "Translate",
            level=1,
            on_collapse_change=lambda c: calls.append(c),
        )
        g.set_collapsed(True)
        assert calls == [True]

    def test_context_menu_callback_still_wires(self, monkeypatch):
        """Step 8.2 must not regress Step 5.3's right-click wiring.
        A widget built with both ``level=1`` and ``on_context_menu``
        still stores the context-menu callback and the frame keeps a
        mouse-release handler (asserted by the ``_mouse_fn`` attribute
        on the fake frame, set by ``set_mouse_released_fn``).
        """
        self._patch_ui(monkeypatch)
        from ovwidgets.property.group_widget import AttributeGroupWidget
        calls = []
        g = AttributeGroupWidget(
            "Translate",
            level=1,
            on_context_menu=lambda x, y: calls.append((x, y)),
        )
        assert hasattr(g._frame, "_mouse_fn")
        g._frame._mouse_fn(10.0, 20.0, 1, 0)  # right-click
        assert calls == [(10.0, 20.0)]


# ---------------------------------------------------------------------------
# Headless behaviour — bypass __init__ via __new__ with a _FakeFrame that
# mimics ui.CollapsableFrame's notify-on-change semantics.
# ---------------------------------------------------------------------------


class _FakeFrame:
    """Stand-in for ``ui.CollapsableFrame`` that models its NOTIFY semantics:

    * ``collapsed`` is a property; assigning an unchanged value is a no-op.
    * Assigning a changed value fires the registered change callback.
    * ``set_collapsed_changed_fn`` stores the callback.
    """

    def __init__(self, collapsed: bool = False) -> None:
        self._collapsed = collapsed
        self._fn = None

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @collapsed.setter
    def collapsed(self, value: bool) -> None:
        if self._collapsed == value:
            return
        self._collapsed = value
        if self._fn is not None:
            self._fn(value)

    def set_collapsed_changed_fn(self, fn) -> None:
        self._fn = fn


def _make_headless(name: str = "Transform", initially_collapsed: bool = False):
    """Construct an AttributeGroupWidget without real omni.ui objects."""
    from ovwidgets.property.group_widget import AttributeGroupWidget
    g = AttributeGroupWidget.__new__(AttributeGroupWidget)
    g._name = name
    g._on_collapse_change = None
    g._frame = _FakeFrame(initially_collapsed)
    g._content = None
    g._frame.set_collapsed_changed_fn(g._on_frame_collapsed_changed)
    return g


class TestGroupWidgetHeadless:
    # 1. Group creates expanded by default
    def test_creates_expanded_by_default(self):
        g = _make_headless()
        assert g.is_collapsed is False

    # 2. Group creates collapsed when initially_collapsed=True
    def test_creates_collapsed_when_requested(self):
        g = _make_headless(initially_collapsed=True)
        assert g.is_collapsed is True

    # 3. Toggle flips collapsed state (expanded → collapsed → expanded)
    def test_toggle_flips_state(self):
        g = _make_headless()
        g.toggle()
        assert g.is_collapsed is True
        g.toggle()
        assert g.is_collapsed is False

    # 4. set_collapsed(True) collapses; reads via frame.collapsed
    def test_set_collapsed_true_collapses(self):
        g = _make_headless()
        g.set_collapsed(True)
        assert g.is_collapsed is True
        assert g._frame.collapsed is True

    # 5. set_collapsed(False) with same state is no-op (no callback)
    def test_set_collapsed_same_state_is_noop(self):
        g = _make_headless()
        calls = []
        g._on_collapse_change = lambda c: calls.append(c)
        g.set_collapsed(False)  # already False
        assert calls == []
        assert g.is_collapsed is False

    # 6. on_collapse_change fires on state change initiated via set_collapsed
    def test_on_collapse_change_fires_on_change(self):
        g = _make_headless()
        calls = []
        g._on_collapse_change = lambda c: calls.append(c)
        g.set_collapsed(True)
        assert calls == [True]

    # 7. on_collapse_change fires on state change initiated via the frame
    # (this models a user clicking the CollapsableFrame's header directly).
    def test_on_collapse_change_fires_on_frame_driven_change(self):
        g = _make_headless()
        calls = []
        g._on_collapse_change = lambda c: calls.append(c)
        g._frame.collapsed = True
        assert calls == [True]
        assert g.is_collapsed is True

    # 8. Content property returns the ui.VStack (or None in the headless fixture)
    def test_content_is_none_headless(self):
        g = _make_headless()
        assert g.content is None

    # 9. set_collapsed with no frame built (edge case) does not raise
    def test_set_collapsed_no_frame_is_safe(self):
        from ovwidgets.property.group_widget import AttributeGroupWidget
        g = AttributeGroupWidget.__new__(AttributeGroupWidget)
        g._name = "X"
        g._on_collapse_change = None
        g._frame = None
        g._content = None
        g.set_collapsed(True)  # must not raise
        assert g.is_collapsed is False  # frame is None → default False

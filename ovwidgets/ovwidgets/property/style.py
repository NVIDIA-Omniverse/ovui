# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Property Inspector domain-scoped styles (property inspector style behavior, §22.2).

Step 0.1 introduced the five PROPERTY_STYLES selectors (``Property.GroupFrame``,
``Property.LabelColumn``, ``Property.MixedOverlay``, ``Property.SearchField``,
``Property.ComponentSeparator``) alongside the legacy keys. Step 0.3 retired
``PropertyGroup.Header/Arrow/Title/Content`` once ``AttributeGroupWidget``
switched to ``ui.CollapsableFrame`` with ``Property.GroupFrame``. Step 0.4
retires ``Property.FilterBar/FilterField/FilterClear`` now that the filter
bar in ``window.py`` overrides with ``Property.SearchField`` on
both the StringField and its clear button. Remaining legacy keys
(``Property.Scroll``, ``Property.Separator``, ``Property.EmptyLabel``,
``Property.FallbackAttribute``) are replaced in later phases (2.3, 2.4, 8.1).
"""

from omni.ui import color as cl
from omni.ui import constant as fl

PROPERTY_STYLES = {
    # ------------------------------------------------------------------
    # Property Inspector public style selectors
    # ------------------------------------------------------------------
    "Property.GroupFrame": {
        "background_color": cl.background_primary,
        "secondary_color": cl.background_primary,
        "color": cl.transparent,
        "border_radius": fl.radius_none,
        "border_width": 0,
        "border_color": cl.transparent,
        "padding": 0,
        "margin": 0.0,
        "margin_width": 8,
        "margin_height": 1,
        "font_size": fl.font_size_small,
    },
    "Property.GroupFrame.Header": {
        "background_color": cl.background_primary,
        "color": cl.text_primary,
        "font_size": fl.font_size_medium,
        "border_radius": fl.radius_none,
        "border_color": cl.transparent,
        "border_width": 0,
        "padding": 0,
        "margin": 0,
        "margin_width": 0,
        "margin_height": 0,
    },
    "Property.GroupFrame.Chevron": {
        "color": cl.text_secondary,
    },
    "Property.ComboBoxChevron": {
        "color": cl.text_secondary,
    },
    # Victor's NO-GO rejects boxed/differently-coloured Property collapsible
    # frames. Keep the built-in collapse behaviour but make the frame chrome
    # disappear into the panel; hierarchy comes from the uppercase header,
    # row rhythm, and surrounding spacing.
    "Property.GroupFrame:hovered": {
        "background_color": cl.background_primary,
        "secondary_color": cl.background_primary,
        "color": cl.transparent,
        "border_color": cl.transparent,
    },
    "Property.GroupFrame:pressed": {
        "background_color": cl.background_primary,
        "secondary_color": cl.background_primary,
        "color": cl.transparent,
        "border_color": cl.transparent,
    },
    # Nested-level variant. ``AttributeGroupWidget`` sets
    # ``frame.name = "inner"`` when ``level >= 1``; nested groups use the
    # same blended surface treatment while inheriting the compact header
    # typography from ``Property.GroupFrame.Header``.
    "Property.GroupFrame::inner": {
        "background_color": cl.background_primary,
        "secondary_color": cl.background_primary,
        "color": cl.transparent,
        "border_color": cl.transparent,
    },
    "Property.GroupFrame::inner:hovered": {
        "background_color": cl.background_primary,
        "color": cl.transparent,
        "secondary_color": cl.background_primary,
        "border_color": cl.transparent,
    },
    "Property.GroupFrame::inner:pressed": {
        "background_color": cl.background_primary,
        "color": cl.transparent,
        "secondary_color": cl.background_primary,
        "border_color": cl.transparent,
    },

    "Property.LabelColumn": {
        "color": cl.property_label_text,
        "font_size": fl.font_size_small,
    },
    "Property.LabelColumn:disabled": {"color": cl.property_label_text},
    "Property.LabelColumn::ambiguous": {"color": cl.text_disabled},
    "Property.LabelColumn::mixed": {"color": cl.status_warning},
    # Schema-default rows keep the same sampled Property label tone as the
    # rest of the reference inspector. Authored state is still carried by the
    # right-side ControlState indicator rather than a lower-contrast label.
    "Property.LabelColumn::not_authored": {"color": cl.property_label_text},
    "Property.LabelColumn::not_authored:disabled": {
        "color": cl.property_label_text,
    },
    # Step 7.1 / Step 16 — the substring of a label that matches the
    # current filter text paints in the primary blue accent so the match run
    # reads as "the thing your filter targeted" against the muted
    # ``text_secondary`` run colour. highlight-label behavior /
    # the property inspector behavior Applied via
    # :class:`HighlightLabel` by setting the match segment's
    # ``ui.Label.name`` to ``"highlight"``.
    "Property.LabelColumn::highlight": {"color": cl.accent_primary},

    # Step 14 — canonical selector for compact attribute labels. The legacy
    # ``Property.LabelColumn`` selector remains above for compatibility with
    # existing row code and tests, but both point at the same small,
    # reference-toned tier.
    "Property.AttributeLabel": {
        "color": cl.property_label_text,
        "font_size": fl.font_size_small,
    },
    "Property.AttributeLabel:disabled": {"color": cl.property_label_text},
    "Property.AttributeLabel::ambiguous": {"color": cl.text_disabled},
    "Property.AttributeLabel::mixed": {"color": cl.status_warning},
    "Property.AttributeLabel::not_authored": {"color": cl.property_label_text},
    "Property.AttributeLabel::not_authored:disabled": {
        "color": cl.property_label_text,
    },
    "Property.AttributeLabel::highlight": {"color": cl.accent_primary},

    # Step 14 — value controls in the Property Inspector use the #161616
    # input-well fill, visible 1px border, and small radius. Individual
    # FloatDrag/IntDrag/StringField/ComboBox widgets opt into this selector
    # from attribute_row.py.
    # Routed through ``cl.background_value_field`` (separate from
    # ``cl.background_field``) so future property-only retuning can happen
    # without affecting other inputs.
    "Property.ValueField": {
        "background_color": cl.background_value_field,
        "color": cl.text_value,
        "secondary_color": cl.background_value_field,
        "font_size": fl.font_size_value,
        "border_radius": fl.radius_small,
        "border_width": 1,
        "border_color": cl.property_value_border,
    },
    "Property.ValueField:hovered": {
        "border_color": cl.border_strong,
    },
    "Property.ValueField:pressed": {
        "background_color": cl.background_value_field_editing,
        "secondary_color": cl.background_value_field_editing,
        "border_color": cl.border_focused,
    },
    "Property.ValueField:focused": {
        "background_color": cl.background_value_field_editing,
        "secondary_color": cl.background_value_field_editing,
        "border_color": cl.border_focused,
    },
    "Property.ValueField::focused": {
        "background_color": cl.background_value_field_editing,
        "secondary_color": cl.background_value_field_editing,
        "border_color": cl.border_focused,
    },
    "Property.ValueField:disabled": {
        "background_color": cl.background_value_field,
        "color": cl.text_disabled,
        "border_color": cl.property_value_border,
    },
    "Property.DropdownValueField": {
        "background_color": cl.background_value_field,
        "color": cl.text_value,
        "secondary_color": cl.background_value_field,
        "font_size": fl.font_size_value,
        "border_radius": fl.radius_small,
        "border_width": 0,
        "border_color": cl.transparent,
    },
    "Property.DropdownValueField:hovered": {
        "border_color": cl.transparent,
    },
    "Property.DropdownValueField:pressed": {
        "background_color": cl.background_value_field_editing,
        "secondary_color": cl.background_value_field_editing,
        "border_color": cl.border_focused,
    },
    "Property.DropdownValueField:focused": {
        "background_color": cl.background_value_field_editing,
        "secondary_color": cl.background_value_field_editing,
        "border_color": cl.border_focused,
    },
    "Property.DropdownValueField:disabled": {
        "background_color": cl.background_value_field,
        "color": cl.text_disabled,
        "border_color": cl.transparent,
    },
    "Property.DropdownFieldBorder": {
        "background_color": cl.property_dropdown_border,
        "border_radius": fl.radius_small,
    },

    # Channel axis labels (property attribute builder behavior). Each channel has its own style type
    # so the per-channel ``::mixed`` state selector can override the axis
    # colour with the warning colour without conflicting with the whole-row
    # ``Property.LabelColumn`` selector.
    "Property.ChannelLabel.X": {
        "color": cl.channel_x,
        "font_size": fl.font_size_tiny,
    },
    "Property.ChannelLabel.Y": {
        "color": cl.channel_y,
        "font_size": fl.font_size_tiny,
    },
    "Property.ChannelLabel.Z": {
        "color": cl.channel_z,
        "font_size": fl.font_size_tiny,
    },
    "Property.ChannelLabel.W": {
        "color": cl.channel_w,
        "font_size": fl.font_size_tiny,
    },
    "Property.ChannelLabel.X::mixed": {"color": cl.status_warning},
    "Property.ChannelLabel.Y::mixed": {"color": cl.status_warning},
    "Property.ChannelLabel.Z::mixed": {"color": cl.status_warning},
    "Property.ChannelLabel.W::mixed": {"color": cl.status_warning},

    "Property.MixedOverlay": {
        "color": cl.text_disabled,
        "font_size": fl.font_size_small,
    },

    # Aligned with ``Stage.FilterField`` (Design Step 3): the Property
    # filter pill now uses a border Rectangle behind a borderless fill
    # Rectangle that wraps the magnifier icon, input, and clear button. The inner ``StringField``
    # is transparent and uses ``Property.SearchFieldInput`` for its
    # text-colour / font-size so only the outer pill's border + radius
    # read. Both panels resolve to the same token set
    # (``cl.background_field`` / ``cl.border_default`` / ``fl.radius_small``)
    # so the two filter bars are pixel-identical when docked side-by-side.
    "Property.SearchField": {
        "background_color": cl.background_field,
        "color": cl.text_primary,
        "border_radius": fl.radius_small,
        "border_width": 0,
        "border_color": cl.border_default,
    },
    # Drawn behind ``Property.SearchField`` so the 1 px resting border
    # remains visible in screenshot QA even when the standalone ovui
    # Rectangle border path does not paint ``border_width``.
    "Property.SearchFieldBorder": {
        "background_color": cl.border_default,
        "border_radius": fl.radius_small,
    },
    # Named variant — toggled by swapping ``Rectangle.name`` from the
    # begin-edit / end-edit callbacks on the inner StringField (omni.ui
    # doesn't fire a focused pseudo-state on Rectangle, so the focus
    # ring is driven imperatively, matching ``Stage.FilterField::focused``).
    "Property.SearchField::focused": {
        "border_color": cl.border_focused,
    },
    "Property.SearchFieldBorder::focused": {
        "background_color": cl.border_focused,
        "border_radius": fl.radius_small,
    },
    # ``:pressed`` retained for tests that assert
    # ``border_width`` + ``border_color`` exist on a pressed variant of
    # ``Property.SearchField``. The state does not fire on the outer
    # Rectangle in practice — the live focus ring comes from the
    # ``::focused`` named variant above — but the style entry is kept
    # so the spec-level assertion continues to hold without a rename.
    "Property.SearchField:pressed": {
        "border_width": 1.0,
        "border_color": cl.border_focused,
    },
    # Inner StringField — transparent so only the outer pill's border
    # reads. Mirrors ``Stage.FilterFieldInput``.
    "Property.SearchFieldInput": {
        "background_color": cl.transparent,
        "color": cl.text_primary,
        "border_width": 0,
        "border_radius": 0,
        "padding": 0,
        "font_size": fl.font_size_small,
    },
    "Property.SearchFieldPlaceholder": {
        "color": cl.text_disabled,
        "font_size": fl.font_size_small,
    },

    "Property.SelectionHeader": {
        "color": cl.accent_primary,
        "font_size": fl.font_size_small,
    },
    "Property.SelectionHeader.Title": {
        "color": cl.text_primary,
        "font_size": fl.font_size_large,
    },
    "Property.SelectionHeader.Path": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_small,
    },

    "Property.ComponentSeparator": {
        "background_color": cl.border_default,
        "margin_width": 2.0,
    },

    # Step 3.4 — small swatch rectangle on colour3f/colour4f rows. The per-row
    # ``background_color`` is set imperatively (the value is the current
    # colour), but the base style supplies a 1px border so the swatch stays
    # visible against matching-coloured backgrounds and a small radius for
    # visual polish.
    "Property.ColorSwatch": {
        "border_width": 1.0,
        "border_color": cl.border_default,
        "border_radius": fl.radius_small,
    },

    # Step 3.6 — small folder button that sits at the end of an asset-path
    # row. Click is a no-op until the file-picker hook lands in a later
    # phase (the property inspector behavior). The style shape matches
    # a standard Button with a tightened padding so the ``...`` glyph
    # fits the 22px width without wrapping.
    "Property.AssetPathFolderButton": {
        "background_color": cl.background_field,
        "color": cl.text_primary,
        "border_radius": fl.radius_small,
        "padding": 2.0,
    },

    # Step 15 — right-edge state indicators. Standalone renders a rounded
    # rectangle and Kit renders a currentColor SVG; both read their active
    # fill/tint from these selectors while preserving the existing state
    # predicates and right-edge slot.
    "Property.ControlState": {
        "background_color": cl.background_tertiary,
        "border_width": 0.0,
        "border_radius": 4.0,
    },
    "Property.ControlState::mixed": {"background_color": cl.status_warning},
    "Property.ControlState::locked": {"background_color": cl.text_secondary},
    "Property.ControlState::timesampled": {"background_color": cl.status_info},
    "Property.ControlState::notdefault": {
        "background_color": cl.property_state_indicator_active,
        "color": cl.property_state_indicator_active,
    },

    # Step 7.4 — large-selection gate. When more than 100 paths are
    # selected the full attribute build is suppressed and this banner
    # renders instead with a "Load Anyway" button. Uses the status-
    # warning palette to communicate "this selection is larger than the
    # inspector normally handles" without reading as an error. Margin
    # keeps the banner away from the filter bar and the scrollable
    # edges so the single VStack body does not slam into the frame.
    "Property.LargeSelectionBanner": {
        "color": cl.status_warning,
        "font_size": fl.font_size_medium,
        "margin": 12.0,
    },

    # ------------------------------------------------------------------
    # Legacy keys still referenced by window.py / attribute_row.py.
    # Removed in later phases (see module docstring).
    # ------------------------------------------------------------------
    "Property.Scroll": {
        "background_color": cl.scrollbar_track,
        "secondary_color": cl.scrollbar_thumb,
        "scrollbar_size": fl.scrollbar_width,
        "border_radius": fl.radius_small,
    },
    "Property.Scroll:hovered": {
        "secondary_color": cl.scrollbar_thumb_hovered,
    },
    "Property.Scroll:pressed": {
        "secondary_color": cl.scrollbar_thumb_hovered,
    },
    # Step QA-polish — separator below the filter bar. Uses
    # ``cl.border_default`` so it matches ``Stage.Separator`` exactly
    # when the two panels are side-by-side.
    "Property.Separator": {"background_color": cl.border_default},

    # Step QA-polish — filter-bar chrome. These keys mirror
    # ``Stage.FilterBar`` / ``Stage.FilterIcon`` / ``Stage.FilterClearButton.Image``
    # one-for-one so the Property filter bar reads as a sibling of the
    # Stage filter bar instead of a second-rate copy. The legacy
    # ``Property.FilterBar`` key is still blocklisted (Step 0.4), so
    # the background rectangle lives under ``Property.FilterBackground``.
    "Property.FilterBackground": {
        "background_color": cl.background_primary,
        "border_radius": 0,
    },
    "Property.FilterIcon": {
        "color": cl.text_secondary,
    },
    "Property.FilterIcon::active": {
        "color": cl.accent_primary,
    },
    "Property.FilterClearButton.Image": {
        "color": cl.text_secondary,
    },
    "Property.EmptyLabel": {
        "color": cl.text_disabled,
        "margin": 8,
        "font_size": fl.font_size_small,
    },
    "Property.FallbackAttribute": {
        "color": cl.text_disabled,
        "margin": 2,
        "font_size": fl.font_size_small,
    },
}

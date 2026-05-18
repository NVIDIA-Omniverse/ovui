# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Layer-window domain-scoped styles (stage browser behavior, §21; LAYERS-PLAN Step 11).

All selectors start with ``Layers.*`` so they only affect the Layers
widget. Colors resolve through the shared ``cl.*`` ColorStore so they
follow theme switches (``set_shade("light")`` / ``"default"``) after
:func:`ovwidgets.app.style.apply_global_styles` is re-called on theme change.

Selector grammar follows style naming rules (Type::Name:State) and
naming follows §4 (domain-scoped dot notation + snake_case names).
Phase-C row delegates and Phase-D column buttons override properties
here; the dict below is the complete base contract for Step 11.
"""

from omni.ui import color as cl
from omni.ui import constant as fl

LAYERS_STYLES: dict = {
    # ── Tree container ─────────────────────────────────────────────────
    # Backs the whole widget body; ``secondary_color`` is the omni.ui
    # key for TreeView branch / expander lines (same hook the Stage
    # widget uses via ``cl.treeview_branch_line``).
    "Layers.TreeView": {
        "background_color": cl.treeview_well_background,
        "color": cl.text_primary,
        # ``secondary_color`` doubles as the column-divider colour in
        # ovui's ``TreeView`` (``core/src/TreeView.cpp:675, 884``). Painted
        # transparent so the built-in 1-px column dividers never appear —
        # they were the visible "gaps" that fragmented the per-cell row
        # background into 6 disconnected chunks before Group F. Selection
        # / hover now paint as one continuous band via the TreeView's
        # native ``AddRectFilled`` mechanism.
        "secondary_color": cl.transparent,
        # ovui's TreeView resolves the *hover* tint from
        # ``background_selected_color`` (``core/src/TreeView.cpp:680``),
        # NOT ``:hovered.background_color``. Setting this property here
        # is what actually fires when the cursor passes over a row.
        "background_selected_color": cl.layers_row_hover,
        "font_size": fl.font_size_small,
    },
    # Group F (Step 23 reversal) — restore the TreeView's native
    # ``:selected`` paint so selection appears as one continuous, edge-to-
    # edge band across every column. The earlier per-cell-Rectangle
    # approach left visible inter-column gaps because the column
    # dividers (``secondary_color``) and per-widget margins prevented
    # the rectangles from butting up against each other. ovui's native
    # selection paint at ``TreeView.cpp:1561-1565`` uses raw
    # ``ImDrawList::AddRectFilled`` per column with column-stride
    # cursor advancement, which produces the contiguous strip we want.
    "Layers.TreeView:hovered": {
        # Kept for completeness — ovui actually fires hover via
        # ``background_selected_color`` above, but a future ovui build
        # may consult ``:hovered.background_color`` directly.
        "background_color": cl.layers_row_hover,
    },
    "Layers.TreeView:selected": {
        "background_color": cl.treeview_selection,
    },
    "Layers.EmptyAreaHit": {
        "background_color": cl.treeview_well_background,
        "border_radius": fl.radius_none,
    },
    "Layers.TreeScrollingFrame": {
        "background_color": cl.treeview_well_background,
        "secondary_color": cl.scrollbar_thumb,
        "scrollbar_size": fl.scrollbar_width,
        "border_radius": fl.radius_none,
        "padding": 0,
        "margin": 0,
    },
    "Layers.TreeScrollingFrame:hovered": {
        "secondary_color": cl.scrollbar_thumb_hovered,
    },
    "Layers.TreeScrollingFrame:pressed": {
        "secondary_color": cl.scrollbar_thumb_hovered,
    },

    # ── Row background (Phase C draws a per-row ui.Rectangle with this
    # type so hover / selected states can paint the whole row strip
    # rather than individual columns). Step 23 drops the base tint to
    # transparent so the Rectangle disappears at rest and only paints
    # on :hovered / :selected — Step 25's edit-target overlay is painted
    # by swapping the Rectangle's ``name`` (``row_bg`` → ``row_bg_edit_target``)
    # rather than by composing two backgrounds, so the base entry
    # cannot carry a colour that would leak through to edit-target rows.
    #
    # Group D (audit issue #5) — the selected-row background uses the
    # shared ``cl.treeview_selection`` token (the same token Stage uses
    # at ``ovwidgets.stage/style.py:124``) so the two panels' selected rows
    # paint the same colour when docked side-by-side. The previous
    # ``cl.layers_row_selected`` value (#5A5A5A medium gray) was much
    # lighter than Stage's ``#232429`` and read as a different
    # selection language; consolidation removes that drift.
    "Layers.TreeView.Row": {
        "background_color": cl.transparent,
    },
    "Layers.TreeView.Row:hovered": {
        "background_color": cl.layers_row_hover,
    },
    "Layers.TreeView.Row:selected": {
        "background_color": cl.treeview_selection,
    },
    # ``name="row_bg"`` scopes the Step 23 delegate-painted Rectangle.
    # Carrying the same selector as the base lets Step 25's edit-target
    # overlay fork off a sibling ``Layers.TreeView.Row::row_bg_edit_target``
    # without touching the hover / selected vocabulary. ``:hovered`` and
    # ``:selected`` states propagate from the TreeView item chain —
    # omni.ui re-resolves the style when a row toggles state, so no
    # delegate-side tracking is needed.
    "Layers.TreeView.Row::row_bg": {
        "background_color": cl.transparent,
    },
    "Layers.TreeView.Row::row_bg:hovered": {
        "background_color": cl.layers_row_hover,
    },
    "Layers.TreeView.Row::row_bg:selected": {
        "background_color": cl.treeview_selection,
    },
    # ``name="row_bg_edit_target"`` — Step 25's forked sibling selector
    # painted only on the current authoring-layer row. The colour carries
    # through the ``:hovered`` / ``:selected`` states so hovering or
    # selecting the authoring row still reads as *green-with-highlight*
    # rather than swapping back to the neutral hover / selected tints
    # (the edit-target signal must never be hidden by interaction).
    # Hover lightens slightly via ``layers_row_hover`` overlay, selection
    # uses ``cl.treeview_selection`` — but because those tokens are both
    # neutral grays, we keep the green fill as the base and let the
    # :hovered / :selected pseudo-states inherit from the base entry so
    # the row stays green.
    "Layers.TreeView.Row::row_bg_edit_target": {
        "background_color": cl.layers_row_edit_target,
    },
    "Layers.TreeView.Row::row_bg_edit_target:hovered": {
        "background_color": cl.layers_row_edit_target,
    },
    "Layers.TreeView.Row::row_bg_edit_target:selected": {
        "background_color": cl.layers_row_edit_target,
    },
    # ``name="row_focus"`` — Step 62 keyboard-focus ring. Painted as a
    # 1-px rectangle overlay on whichever row is currently the single
    # focused (keyboard-navigation) target. The accent-primary border
    # matches :class:`ui.StringField`'s ``:focused`` ring so the same
    # "this is the focused control" signal reads as one vocabulary
    # across the window. The fill stays transparent so the row's
    # existing hover / selection / edit-target tints remain visible
    # underneath the ring — focus is additive, never replaces row bg.
    "Layers.TreeView.Row::row_focus": {
        "background_color": cl.transparent,
        "border_color": cl.accent_primary,
        "border_width": 1,
    },

    # ── Layer name label ──────────────────────────────────────────────
    # Base uses the shared primary text; named variants override only
    # ``color`` so other properties inherit from the base entry
    # (style naming rules — named-group inheritance). The ``::normal``
    # variant (Step 18) exists so the delegate can unconditionally pass
    # ``name=<role>`` without special-casing the default state — ovui
    # falls back to the base entry when the named variant is absent but
    # declaring it makes the contract explicit.
    "Layers.NameLabel": {
        "color": cl.text_primary,
        "font_size": fl.font_size_small,
    },
    "Layers.NameLabel::normal": {
        "color": cl.text_primary,
    },
    "Layers.NameLabel::missing": {
        "color": cl.layers_label_missing,
    },
    "Layers.NameLabel::disabled": {
        "color": cl.layers_label_disabled,
    },
    "Layers.NameLabel::edit_target": {
        # Group F (audit finding #2) — collapsed the green stack: the
        # leading-icon green (``Layers.LeadingIcon::edit_target``) is
        # the persistent edit-target signal; the layer-name label
        # reads as primary text so the row matches Stage's typography
        # vocabulary. Previously the name painted in
        # ``cl.layers_icon_edit_target`` green, which combined with
        # the row background, the leading icon, the run-cursor, and
        # per-column save / lock glyphs to put 5+ green elements on
        # one row — too "shiny" per the visual diagnostic.
        "color": cl.text_primary,
    },
    "Layers.NameLabel::anonymous": {
        # Step 27 — in-memory / unsaved layers. omni.ui does not expose
        # a first-class italic toggle in its style dict (the FontStyle
        # enum only surfaces through ``ui.Glyph`` loading, not per-label
        # slant), so the italic-feel cue rides on the softer
        # ``cl.text_secondary`` tint + the ``[anon]`` suffix emitted by
        # :class:`~ovwidgets.layers.models.layer_name_model.LayerNameValueModel`.
        # The dimmer colour reads as "less committed" than the
        # primary-text default — pairs naturally with the bracketed tag
        # to convey "metadata, not a real on-disk layer yet".
        "color": cl.text_secondary,
    },

    # ── Leading layer icon on the name column (Step 25) ─────────────
    # A stack of three thin horizontal bars that reads as a "layers"
    # glyph (three sheets of paper stacked). Rendered with primitives
    # rather than an SVG for the same reasons the Step 19/20/21 icons
    # use primitives — NVIDIA Sans lacks a dedicated layers codepoint
    # and the Step-25 SVG pack (``layers_edit_target_pin.svg`` etc.)
    # is not yet shipped. The three named states encode:
    #   ``::normal``         — no edit target here; dim secondary-text
    #                          tint so the icon stays quiet on normal
    #                          rows.
    #   ``::edit_target``    — the authoring layer; full green from
    #                          ``cl.layers_icon_edit_target`` so the
    #                          icon reads as the active signal even
    #                          against the green row background.
    #   ``::has_descendant`` — some descendant of this row is the
    #                          edit target (Step 24 propagates the
    #                          flag); half-green tint from
    #                          ``cl.layers_icon_half_edit`` so the
    #                          cue is visibly weaker than the full
    #                          authoring row.
    # Step 26 swaps the primitive for a provider-backed glyph pack but
    # keeps the ``name=`` state contract so the style block stays put.
    "Layers.LeadingIcon": {
        "background_color": cl.transparent,
        "border_color": cl.transparent,
    },
    "Layers.LeadingIcon::normal": {
        "background_color": cl.text_secondary,
        "border_color": cl.text_secondary,
    },
    "Layers.LeadingIcon::edit_target": {
        "background_color": cl.layers_icon_edit_target,
        "border_color": cl.layers_icon_edit_target,
    },
    "Layers.LeadingIcon::has_descendant": {
        "background_color": cl.layers_icon_half_edit,
        "border_color": cl.layers_icon_half_edit,
    },

    # ── Missing-layer X badge (Step 27) ─────────────────────────────
    # Small red "X" drawn in the name column between the leading icon
    # and the label whenever :attr:`LayerItem.is_missing`. The tint
    # matches :data:`cl.layers_label_missing` — the same red as the
    # ``NameLabel::missing`` role — so the label + badge read as one
    # coherent "unresolved layer" cue rather than two unrelated reds.
    # ``font_size`` is explicit (medium) so the ``X`` stays legible at
    # row height even when NVIDIA Sans falls back to a narrower glyph.
    # Step 27's SVG pack swaps the :class:`ui.Label` for an
    # ``Image::layers_missing_x`` provider; the selector stays stable
    # because the name is type-scoped rather than tied to a text tag.
    "Layers.MissingBadge": {
        "color": cl.layers_label_missing,
        "font_size": fl.font_size_small,
    },

    # ── Prim-spec row labels (Step 48) ───────────────────────────────
    # Prim-spec rows (``PrimSpecItem``) render under their owning layer
    # when ``LayerSettings.show_layer_contents`` is enabled. The row
    # is a three-part horizontal strip — ``<specifier tag> <name>
    # (<type>)`` — and every part carries its own style-type override
    # so Step 49 can swap the text tag for a provider-backed SVG
    # without disturbing the name / type labels.
    #
    # ``Layers.PrimSpecTag::<kind>`` colours the specifier tag by
    # specifier. ``def`` rides the primary-text tint so regular
    # definitions read as neutral; ``over`` / ``class`` dim slightly
    # to the secondary-text tint to hint at "this row is not a fresh
    # definition" without colouring the whole row.
    "Layers.PrimSpecTag": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_small,
        "background_color": cl.transparent,
    },
    "Layers.PrimSpecTag::def": {
        "color": cl.text_primary,
    },
    "Layers.PrimSpecTag::over": {
        "color": cl.text_secondary,
    },
    "Layers.PrimSpecTag::class": {
        "color": cl.text_secondary,
    },
    "Layers.PrimSpecName": {
        "color": cl.text_primary,
        "font_size": fl.font_size_small,
    },
    "Layers.PrimSpecType": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_small,
    },

    # ── Prim-spec specifier icon (Step 49) ──────────────────────────
    # The per-specifier glyph (``prim_def`` / ``prim_over`` /
    # ``prim_class``) is rendered with :class:`ui.ImageWithProvider`;
    # the PNG raster itself carries the colour, so this rule only
    # reserves the slot and lets the row-bg Rectangle paint through at
    # the transparent margins. A named-variant block per specifier
    # stays present so Step 53+ theming passes can tint a glyph without
    # re-drawing the PNG — e.g. a light-theme ``prim_over`` recolour
    # can ride on ``::over`` without touching ``::def``.
    "Layers.PrimSpecIcon": {
        "background_color": cl.transparent,
        "border_color": cl.transparent,
    },
    "Layers.PrimSpecIcon::def": {
        "background_color": cl.transparent,
    },
    "Layers.PrimSpecIcon::over": {
        "background_color": cl.transparent,
    },
    "Layers.PrimSpecIcon::class": {
        "background_color": cl.transparent,
    },

    # Composition badge (reference / payload) overlaid on the bottom-
    # right corner of the specifier icon. ``Layers.PrimSpecBadge`` keeps
    # the slot transparent — the PNG carries its own fill + outline —
    # but the named variants exist so Step 53+ can target per-badge
    # theming (e.g. dimming the reference badge when the layer is muted)
    # without renaming the selector.
    "Layers.PrimSpecBadge": {
        "background_color": cl.transparent,
        "border_color": cl.transparent,
    },
    "Layers.PrimSpecBadge::reference": {
        "background_color": cl.transparent,
    },
    "Layers.PrimSpecBadge::payload": {
        "background_color": cl.transparent,
    },
    "Layers.PrimSpecBadge::instance": {
        "background_color": cl.transparent,
    },

    # ── Column icon buttons (stubs — Phase D fills the interaction
    # surface). Base gives transparent backgrounds so the row stripe
    # bleeds through; ``muted`` dims the glyph for disabled columns.
    "Layers.IconButton": {
        "color": cl.text_secondary,
        "background_color": cl.transparent,
    },
    "Layers.IconButton::muted": {
        "color": cl.layers_label_disabled,
    },

    # ── Name-search filter bar (Step 51) ─────────────────────────────
    # The 30-px strip above the Save-All toolbar. ``FilterBackground``
    # paints the raised chrome so the strip visibly separates from the
    # near-black TreeView body; the field,
    # icon, and clear-button entries mirror the Stage / Property filter
    # tokens one-for-one so the three filter bars render identically
    # when the panels are docked side by side.
    "Layers.FilterBackground": {
        "background_color": cl.background_primary,
        "border_radius": 0,
    },
    # ovui's single-Rectangle ``border_width`` path is unreliable across
    # standalone builds (a flat border on the StringField does not paint
    # consistently). We mirror the Stage / Property two-Rectangle pattern:
    # an outer ``Layers.FilterFieldBorder`` Rectangle paints
    # ``cl.border_default`` as a solid fill, and an inner borderless
    # ``Layers.FilterField`` Rectangle paints the ``cl.background_field`` fill
    # 1 px inside on every edge so the outer fill reads as a 1-px ring. The StringField on top
    # uses ``Layers.FilterFieldInput`` (transparent fill, primary text
    # colour) so only the two Rectangles paint the chrome and the field
    # contributes only its glyphs. Focus highlight rides on the
    # ``::focused`` named variants — :meth:`_on_filter_begin_edit` flips
    # the rectangles' ``.name`` because omni.ui's ``:focused`` pseudo-state
    # does not fire on a ``ui.Rectangle``.
    "Layers.FilterField": {
        "background_color": cl.background_field,
        "color": cl.text_primary,
        "border_radius": fl.radius_small,
        "border_width": 0,
        "border_color": cl.border_default,
    },
    "Layers.FilterFieldBorder": {
        "background_color": cl.border_default,
        "border_radius": fl.radius_small,
    },
    # ``::focused`` named variants — flipped imperatively from
    # :meth:`LayerWindow._on_filter_begin_edit` /
    # :meth:`_on_filter_end_edit`. Mirror ``Stage.FilterField::focused``
    # so the focus ring colour matches the Stage / Property panels when
    # docked side-by-side. The ``:focused`` pseudo-state entry below is
    # kept for backwards compatibility with the Step 51 spec assertions
    # (``test_layers_step51_search_field.py``) and Step 60's resolution
    # matrix; omni.ui does not surface ``:focused`` on Rectangle at paint
    # time, but the dict membership is asserted by spec tests.
    "Layers.FilterField::focused": {
        "border_color": cl.border_focused,
    },
    "Layers.FilterFieldBorder::focused": {
        "background_color": cl.border_focused,
        "border_radius": fl.radius_small,
    },
    "Layers.FilterField:focused": {
        "border_color": cl.border_focused,
    },
    # Inner ``StringField`` — transparent fill so only the wrapping
    # rectangles paint the pill chrome. Mirrors ``Stage.FilterFieldInput``
    # one-for-one so the three filter bars (Stage / Property / Layers)
    # render pixel-identical when docked together.
    "Layers.FilterFieldInput": {
        "background_color": cl.transparent,
        "color": cl.text_primary,
        "border_width": 0,
        "border_radius": 0,
        "padding": 0,
        "font_size": fl.font_size_small,
    },
    # Leading magnifier glyph. ``color`` tints the raster so the icon
    # answers the theme without shipping a separate PNG per theme; the
    # ``::active`` variant swaps to the accent tint when a search is
    # live, echoing the clear-X visibility cue.
    "Layers.FilterIcon": {
        "color": cl.text_secondary,
    },
    "Layers.FilterIcon::active": {
        "color": cl.accent_primary,
    },
    "Layers.FilterClearButton.Image": {
        "color": cl.text_secondary,
    },
    # 1-px divider between the filter bar and the Save-All toolbar
    # strip so the two same-tinted rows read as distinct zones. Uses
    # the shared ``cl.border_default`` so the rule matches the Stage /
    # Property separators when the three panels are docked together.
    "Layers.FilterSeparator": {
        "background_color": cl.border_default,
    },
    # "No matching layers" overlay painted on top of the TreeView when
    # the filter rejects every row. Uses the disabled-text tint so the
    # message reads as a quiet "nothing here" cue rather than an error.
    "Layers.EmptyState": {
        "color": cl.text_disabled,
        "font_size": fl.font_size_small,
    },
    # Step 62 — placeholder text overlay painted inside the filter
    # field when the user hasn't typed anything. Rendered as a
    # :class:`ui.Label` above the :class:`ui.StringField` because the
    # standalone ``omni.ui`` build's StringField has no native
    # placeholder prop. Tint is the disabled-text role so the hint
    # reads as "type something here" guidance rather than real content.
    "Layers.FilterPlaceholder": {
        "color": cl.text_disabled,
        "font_size": fl.font_size_small,
    },
    # Step 62 — "Open a USD stage to see layers" message rendered
    # inside the window body when no adapter is attached. Quieter than
    # the primary text role (disabled tint) so the empty window reads
    # as an intentional waiting-state rather than a broken panel.
    "Layers.EmptyStageLabel": {
        "color": cl.text_disabled,
        "font_size": fl.font_size_small,
    },

    # ── Options dropdown button (Step 53) ────────────────────────────
    # Gear-glyph button on the left of the Save-All strip. The hit
    # rectangle carries the hover / pressed feedback; the three-bar
    # glyph primitives sit on top and read as "options / sliders".
    # Transparent at rest so the Save-All strip's
    # ``background_primary`` tint bleeds through; hover + press
    # lift the button with the shared ``interactive_*`` tokens so the
    # affordance matches the Save-All button next to it.
    "Layers.OptionsButton": {
        "background_color": cl.transparent,
        "border_radius": fl.radius_small,
    },
    "Layers.OptionsButton:hovered": {
        "background_color": cl.interactive_hovered,
    },
    "Layers.OptionsButton:pressed": {
        "background_color": cl.interactive_pressed,
    },
    # The three horizontal bars making up the gear glyph. Uses the
    # secondary-text tint so the icon sits quieter than the primary
    # Save-All label on the same strip — the dropdown is a less
    # frequent interaction than Save-All, and dimming it keeps the
    # toolbar's visual hierarchy intact.
    "Layers.OptionsGlyph": {
        "background_color": cl.text_secondary,
        "border_color": cl.text_secondary,
    },

    # ── Save-All toolbar button + badge (Step 35) ────────────────────
    # The header strip above the tree carries a Save-All button.
    # ``Layers.Toolbar`` scopes the strip itself. It sits on the panel-chrome
    # tier while the TreeView below recedes to the well tier; the existing
    # separator lines make the filter / toolbar / tree stack read as distinct
    # reference-like bands.
    "Layers.Toolbar": {
        "background_color": cl.background_primary,
    },
    # The Save-All button sits on the toolbar strip. ``enabled=False``
    # dims it through the standard :disabled pseudo-state so users can
    # tell at a glance when nothing is dirty. A :hovered shade lifts
    # the button so hover affordance reads as an interactive target.
    "Layers.SaveAllButton": {
        "background_color": cl.interactive_default,
        "color": cl.text_primary,
        "border_color": cl.border_default,
        "border_width": 1,
        "border_radius": fl.radius_small,
        "font_size": fl.font_size_small,
    },
    "Layers.SaveAllButton:hovered": {
        "background_color": cl.interactive_hovered,
    },
    "Layers.SaveAllButton:pressed": {
        "background_color": cl.interactive_pressed,
    },
    "Layers.SaveAllButton:disabled": {
        "background_color": cl.interactive_disabled,
        "color": cl.layers_button_disabled_text,
    },
    "Layers.SaveAllButtonLabel": {
        "color": cl.layers_button_disabled_text,
        "font_size": fl.font_size_small,
    },
    "Layers.SaveAllButtonLabel::enabled": {
        "color": cl.text_primary,
    },
    "Layers.SaveAllButtonLabel::disabled": {
        "color": cl.layers_button_disabled_text,
    },
    # Badge dot — a small filled :class:`ui.Circle` drawn on the top-
    # right corner of the button (inside its enclosing ``ui.ZStack``)
    # when at least one layer is dirty. Amber matches the per-row
    # save-dirty dot (``Layers.SaveIcon::dirty``) so the "unsaved work"
    # colour reads as one signal across the tree strip and the
    # toolbar.
    "Layers.SaveAllBadge": {
        "background_color": cl.transparent,
        "border_color": cl.transparent,
    },
    "Layers.SaveAllBadge::dirty": {
        "background_color": cl.layers_icon_save_dirty,
        "border_color": cl.layers_icon_save_dirty,
    },

    # ── Save / dirty indicator (Step 19) ─────────────────────────────
    # Rendered as a centred filled :class:`ui.Circle` on column 2 when
    # the layer is dirty and saveable. The Circle's fill colour comes
    # from the ``background_color`` key (omni.ui maps the property
    # onto the filled-shape primitive). The ``::dirty`` named variant
    # carries the amber tint; the base entry sits ready for Step 33's
    # error state (``::error``) and the future "clean hover"
    # (``::hover``) without a second selector rename.
    "Layers.SaveIcon": {
        "background_color": cl.transparent,
        "border_color": cl.transparent,
    },
    "Layers.SaveIcon::dirty": {
        "background_color": cl.layers_icon_save_dirty,
        "border_color": cl.layers_icon_save_dirty,
    },

    # ── Local-mute eye indicator (Step 20) ───────────────────────────
    # Column 3 renders one of two primitives depending on the layer's
    # local-mute bit: a filled :class:`ui.Circle` (name ``open``) for
    # an unmuted / visible layer, and a centred horizontal
    # :class:`ui.Rectangle` (name ``muted``) for a locally muted layer.
    # Using primitives instead of a text glyph avoids the same font-
    # coverage trap Step 19's :class:`ui.Circle` sidesteps — NVIDIA
    # Sans does not ship every Geometric-Shapes codepoint, so an "●"
    # or "◯" label would render as a fallback "?" box on machines
    # without a full-coverage font installed. The SVG eye icons from
    # LAYERS-WINDOW-ARCHITECTURE §28.1 replace these primitives when
    # the Step-24 icon pack lands; the style block stays stable because
    # the ``name=`` state lookup matches ``Image::layers_mute:*``.
    "Layers.MuteIcon": {
        "background_color": cl.transparent,
        "border_color": cl.transparent,
    },
    "Layers.MuteIcon::open": {
        # Open eye — painted in the secondary-text tint so it sits
        # quieter than the amber save indicator. It's a "state is
        # normal" icon, not a call to action.
        "background_color": cl.text_secondary,
        "border_color": cl.text_secondary,
    },
    "Layers.MuteIcon::muted": {
        # Muted eye — dimmed to the disabled-label tint so the row
        # reads as off at a glance (matches the ``NameLabel::disabled``
        # colour the Step-18 name model uses for the same state).
        "background_color": cl.layers_label_disabled,
        "border_color": cl.layers_label_disabled,
    },

    # ── Lock / padlock indicator (Step 21) ───────────────────────────
    # Column 6 renders a small padlock glyph whose visibility follows
    # the layer's lock bit. Step 21 uses shape primitives so the cell
    # is font-independent (same rationale as the Step-19 save dot and
    # Step-20 mute eye — NVIDIA Sans does not carry ``U+1F512`` in
    # every deployment). The Step-24 icon pack swaps the primitives
    # for provider-backed ``ImageWithProvider`` glyphs; the style
    # block stays stable because the ``name=`` state lookup
    # (``locked`` / ``unlocked``) matches ``Image::layers_lock:*``.
    #
    # Two primitives make the padlock:
    #   - ``shackle`` (the arch over the body) — a thin rectangle the
    #     delegate draws only in the locked state.
    #   - ``body`` (the rectangular base) — painted in both states,
    #     tinted brighter when locked, dimmer when unlocked.
    "Layers.LockIcon": {
        "background_color": cl.transparent,
        "border_color": cl.transparent,
    },
    "Layers.LockIcon::locked": {
        # Locked padlock — rendered in the primary-text tint so it
        # reads as an active, deliberate state signal. Matches the
        # brightness of the save dirty dot without borrowing its
        # amber (lock is not a call to action the way dirty is).
        "background_color": cl.text_primary,
        "border_color": cl.text_primary,
    },
    "Layers.LockIcon::unlocked": {
        # Unlocked padlock — dimmed to the disabled-label tint so
        # the "default / open" state stays quiet in the column
        # strip. Pairs visually with ``MuteIcon::muted`` and
        # ``NameLabel::disabled`` for a consistent "low-salience"
        # tint across icon columns.
        "background_color": cl.layers_label_disabled,
        "border_color": cl.layers_label_disabled,
    },
    "Layers.LockIcon::readonly_overlay": {
        # Step 27 — non-interactive backdrop hint painted behind the
        # clickable padlock glyph whenever the layer's file is
        # read-only on disk. Uses the dedicated
        # ``layers_icon_readonly_backdrop`` tint (muted amber-brown,
        # sharing the amber hue family with the Step-19 save dirty
        # dot) so the "write-blocked" colour vocabulary reads as one
        # signal family. Distinct from ``::locked`` / ``::unlocked``
        # because this signal is about file permissions, not the
        # user-toggled lock bit — a read-only *and* locked row shows
        # the bright padlock on top of the backdrop, which is exactly
        # the "doubly guarded" read we want.
        "background_color": cl.layers_icon_readonly_backdrop,
        "border_color": cl.layers_icon_readonly_backdrop,
    },

    # ── Placeholder-column icons (Step 22) ──────────────────────────
    # Columns 1 (Live), 4 (Global Mute), and 5 (Latest) reserve space
    # in the seven-column layout but have no working backend in v1
    # (LAYERS-PLAN Step 22). The delegate draws a small shape
    # primitive in the disabled-label tint so the columns read as
    # "intentionally empty / coming soon" rather than visually
    # jagged. All three columns share this block so a later theme
    # tweak to the placeholder tint only touches one entry.
    #
    # The named variants match the column that paints them — Steps
    # 42 / 43 / 44 wire the real Live / Global Mute / Latest models
    # and will graduate each column off the placeholder selector
    # individually (much like Save / Mute / Lock graduated off the
    # shared Step-17 ``ui.Spacer``).
    "Layers.PlaceholderIcon": {
        "background_color": cl.transparent,
        "border_color": cl.transparent,
    },
    # ── Branch chevron ───────────────────────────────────────────────
    # ``build_branch`` draws a PNG chevron glyph (``chevron_right.png``
    # /  ``chevron_down.png`` from ``ovwidgets.app/resources/icons/``) via
    # :class:`ui.ImageWithProvider`. ``color`` tints the white PNG with
    # the secondary-text role so the chevron reads as an affordance
    # without competing with the row content. Mirrors
    # ``Stage.TreeChevron`` at ``ovwidgets.stage/style.py:138-140`` one-for-one
    # so the two trees' branch arrows render identically.
    "Layers.BranchChevron": {
        "color": cl.text_secondary,
    },
    "Layers.PlaceholderIcon::disabled": {
        # Single shared "low-salience" tint for every column-strip
        # placeholder — matches ``MuteIcon::muted`` /
        # ``LockIcon::unlocked`` / ``NameLabel::disabled`` so the
        # whole "this is off" vocabulary uses one colour.
        "background_color": cl.layers_label_disabled,
        "border_color": cl.layers_label_disabled,
    },

    # ── Drop indicator (Step 44) ─────────────────────────────────────
    # Delegate paints a per-cell :class:`ui.Rectangle` with this type
    # override whenever the :class:`~ovwidgets.layers.drop_visual_controller.
    # DropVisualController` reports a live drag-over state. Four named
    # variants cover the indicator set:
    #
    #   ``::drop_target``   — valid "drop onto" hover. 2-px border in
    #                         the drag-accent green; ``background_color``
    #                         stays transparent so the row's existing
    #                         hover / selection / edit-target fill
    #                         bleeds through and the outline reads as
    #                         an overlay rather than a flat swap.
    #   ``::drop_rejected`` — invalid hover (locked parent, cycle, …).
    #                         Red 2-px border. Also transparent fill so
    #                         the row's underlying state (e.g. green
    #                         authoring-layer fill) stays readable and
    #                         the user can still tell *which* row was
    #                         rejected.
    #   ``::drop_above`` /  — valid between-drop. Paints a bright-blue
    #     ``::drop_below``    horizontal 2-px stripe (background_color,
    #                         border keeps the same hue so anti-aliased
    #                         edges stay crisp on both themes). The
    #                         delegate sandwiches the Rectangle between
    #                         Spacers so the stripe pins to the top or
    #                         bottom of the cell without consuming
    #                         vertical space from the row's real
    #                         content.
    #
    # All four variants share the transparent base so switching among
    # them across frames doesn't require clearing explicit properties.
    "Layers.DropIndicator": {
        "background_color": cl.transparent,
        "border_color": cl.transparent,
        "border_width": 0,
    },
    "Layers.DropIndicator::drop_target": {
        "background_color": cl.transparent,
        "border_color": cl.layers_drop_target,
        "border_width": 2,
    },
    "Layers.DropIndicator::drop_rejected": {
        "background_color": cl.transparent,
        "border_color": cl.layers_drop_rejected,
        "border_width": 2,
    },
    "Layers.DropIndicator::drop_above": {
        "background_color": cl.layers_drop_between,
        "border_color": cl.layers_drop_between,
    },
    "Layers.DropIndicator::drop_below": {
        "background_color": cl.layers_drop_between,
        "border_color": cl.layers_drop_between,
    },

    # ── Bottom footer toolbar (Step 54) ──────────────────────────────
    # 28-px strip at the bottom of the Layers window carrying the
    # Insert / Create / Delete trio that mirrors the context-menu
    # operations (LAYERS-WINDOW-ARCHITECTURE §25.5). Sits on
    # ``background_primary`` to match ``Layers.Toolbar``; the existing
    # ``Layers.FooterSeparator`` 1-px rule supplies the divider against
    # the tree body without a brighter chrome band.
    "Layers.Footer": {
        "background_color": cl.background_primary,
    },
    "Layers.FooterGap": {
        "background_color": cl.background_primary,
    },
    "Layers.FooterButtonGap": {
        "background_color": cl.background_primary,
    },
    "Layers.ToolbarButtonGap": {
        "background_color": cl.background_primary,
    },
    # 1-px divider between the TreeView body and the footer strip so
    # the two zones read as distinct. Uses the shared
    # ``cl.border_default`` so it matches the ``Layers.FilterSeparator``
    # that divides the filter bar from the Save-All strip above.
    "Layers.FooterSeparator": {
        "background_color": cl.border_default,
    },
    # The three footer buttons share the Save-All button's visual
    # language (rounded rect, subtle border, interactive_* fills) so
    # the two toolbar strips present a single button-family. The
    # ``:disabled`` pseudo-state dims the fill and the glyph together
    # so the user reads "this action is not applicable right now" at
    # a glance (e.g. Delete on the root layer). Font size stays on the
    # regular compact tier so these buttons do not dominate the Layers panel.
    "Layers.FooterButton": {
        "background_color": cl.interactive_default,
        "color": cl.text_primary,
        "border_color": cl.border_default,
        "border_width": 1,
        "border_radius": fl.radius_small,
        "font_size": fl.font_size_small,
    },
    "Layers.FooterButton:hovered": {
        "background_color": cl.interactive_hovered,
    },
    "Layers.FooterButton:pressed": {
        "background_color": cl.interactive_pressed,
    },
    "Layers.FooterButton:disabled": {
        "background_color": cl.interactive_disabled,
        "color": cl.layers_button_disabled_text,
    },
    "Layers.FooterButtonLabel": {
        "color": cl.layers_button_disabled_text,
        "font_size": fl.font_size_small,
    },
    "Layers.FooterButtonLabel::enabled": {
        "color": cl.text_primary,
    },
    "Layers.FooterButtonLabel::disabled": {
        "color": cl.layers_button_disabled_text,
    },
}

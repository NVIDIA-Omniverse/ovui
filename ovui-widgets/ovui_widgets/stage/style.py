# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Stage Browser domain-scoped styles (stage browser behavior, §21).

All selectors start with ``Stage.*`` or ``TreeView*`` so they only affect
the Stage widget. Colors resolve through the shared ``cl.*`` ColorStore so
they follow theme switches (``set_shade("light")`` / ``"dark"``).
"""

from omni.ui import color as cl
from omni.ui import constant as fl

STAGE_STYLES = {
    # ── Column headers (UI-005 — design-reference rev-9 anchor) ─────────
    # Reference header sits on the panel chrome above the tree well; hierarchy
    # comes from the #222222 strip, readable muted header text, and the
    # separator rule.
    #
    # Token anchor (locked to ovuiDark rev-9 — OVUI_REFERENCE_IMPLEMENTATION_PLAN
    # Step 3.2 / UI-005):
    #   - header text colour   → ``cl.text_secondary`` (#A7A7A7 muted grey,
    #     readable against the corrected reference #222222 header strip)
    #   - eye-icon colour      → ``cl.text_secondary`` for the same visible
    #     header-column treatment as NAME / TYPE
    #   - separator-rule tone  → ``cl.border_default`` (#4B4B4B — the rev-9
    #     quiet 1-px rule under the header band, paired with the matching
    #     ``Stage.Separator`` and ``Stage.Footer.Rule`` tokens)
    "Stage.ColumnHeader.Bg": {
        "background_color": cl.background_primary,
        "border_radius": 0,
    },
    "Stage.ColumnHeader.Bg:hovered": {
        "background_color": cl.background_primary,
        "border_radius": 0,
    },
    "Stage.ColumnHeader": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_small,
    },
    "Stage.ColumnHeader:hovered": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_small,
    },
    "Stage.ColumnHeader.Icon": {
        "color": cl.text_secondary,
    },
    "Stage.ColumnHeader.Icon:hovered": {
        "color": cl.text_secondary,
    },
    "Stage.ColumnHeader.Rule": {
        "background_color": cl.border_default,
        "border_radius": 0,
    },

    # ── Type column label ────────────────────────────────────────────────
    "Stage.TypeLabel": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_tiny,
    },
    "Stage.TypeLabel:selected": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_tiny,
    },

    # ── Default-prim pill (UI-033 — design-reference rev-9 anchor) ───────
    # Reference (`OvuiSampleApp.png`) shows the Stage tree as a calm flat
    # list of neutral labels with no high-chroma DEF pill or saturated
    # prim-type icons. Step 3.4 / UI-033 retones the underlying tokens so
    # the pill and the prim-icon family read at the reference's quiet
    # baseline; the selectors below stay untouched so the wiring contract
    # (background + border both resolve to the same pill token; label
    # tones via ``cl.text_secondary``) remains stable.
    #
    # Token anchor (locked to ovuiDark rev-9 — OVUI_REFERENCE_IMPLEMENTATION_PLAN
    # Step 3.4 / UI-033, defined in ``ovui_widgets/common/style/palette.py``):
    #   - pill background        → ``cl.stage_default_prim_pill_background``
    #     (#1F1F1F — the ``cl.background_secondary`` panel-body family;
    #     down from the prior #1D2634 blue tint that read as a saturated
    #     accent against the calm reference)
    #   - prim-icon mesh tint    → ``cl.prim_type_mesh`` (#7A8FA8 — muted
    #     blue-grey; down from the prior #008AF9 selection-blue which
    #     overlapped ``cl.accent_primary``)
    #   - prim-icon light tint   → ``cl.prim_type_light`` (#B09269 — muted
    #     warm gold; down from the prior #DDAA50 amber)
    #   - prim-icon camera tint  → ``cl.prim_type_camera`` (#8A93A8 — quiet
    #     neutral cool grey; down from the prior #99A3C9 light-blue)
    # The active ``Stage.PrimIcon`` selector still paints via
    # ``cl.text_secondary`` (its existing quiet-grey wiring); the
    # ``cl.prim_type_*`` shades are toned so any future per-category
    # tinting consumer inherits a reference-aligned neutral.
    "Stage.DefaultPrimPill": {
        "background_color": cl.stage_default_prim_pill_background,
        "border_radius": fl.radius_small,
        "border_color": cl.stage_default_prim_pill_background,
        "border_width": 1,
    },
    "Stage.DefaultPrimPill:hovered": {
        "background_color": cl.stage_default_prim_pill_background,
        "border_radius": fl.radius_small,
        "border_color": cl.stage_default_prim_pill_background,
        "border_width": 1,
    },
    "Stage.DefaultPrimPill.Label": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_tiny,
        "padding": 0,
    },
    "Stage.DefaultPrimPill.Label:hovered": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_tiny,
        "padding": 0,
    },

    # ── Name column label (state-aware) ──────────────────────────────────
    "Stage.Name": {
        "color": cl.text_primary,
        "font_size": fl.font_size_small,
    },
    "Stage.Name::inactive": {
        "color": cl.text_disabled,
        "font_size": fl.font_size_small,
    },
    "Stage.Name::abstract": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_small,
    },

    # ── Row hover / selection (UI-006 — design-reference rev-9 anchor) ──
    # Aggressive zero-out of every spacing attribute the omni.ui
    # ``TreeView`` widget inherits from global ``Rectangle`` / ``Frame`` /
    # ``ScrollingFrame`` styles. Without these, the standalone ovui build
    # left an un-tunable ~22-px strip above the first data row even with
    # ``header_visible=False`` (the TreeView quietly still reserves header
    # chrome). Every attribute below is load-bearing — removing any one
    # of them restores the gap.
    #
    # Token anchor (locked to ovuiDark rev-9 — OVUI_REFERENCE_IMPLEMENTATION_PLAN
    # Step 3.3 / UI-006):
    #   - selected row fill           → ``cl.treeview_selection`` (#232429 —
    #     the rev-9 quiet selected band; matches the reference's
    #     low-contrast active-row highlight)
    #   - hover row fill              → ``cl.background_tertiary`` (#222222 —
    #     a raised hover band above the near-black tree well)
    #   - left selection-accent fill  → ``cl.treeview_selection`` so the
    #     selected-row geometry remains but the reference's neutral tree
    #     treatment is preserved instead of adding a blue rail)
    #   - resting eye-icon colour     → ``cl.text_secondary`` (#A7A7A7 — one
    #     step up from ``cl.text_disabled``; matches the reference's clearly
    #     readable right-edge eye glyph)
    #   - hidden / disabled eye tone  → ``cl.text_disabled`` (#4B4B4B — the
    #     paired quiet token for the toggled-off / non-toggleable states)
    # Visibility icon glyph size is 14 px (``_VISIBILITY_ICON_SIZE`` in
    # ``stage_delegate.py``), bumped from 12 px under UI-006 so the eye
    # reads at the reference's scale; the column-header eye preview in
    # ``StageDelegate.build_column_header`` remains at 12 px because
    # UI-005 fixed it as the column-header glyph size.
    "TreeView": {
        "background_color": cl.treeview_well_background,
        "color": cl.text_primary,
        "padding": 0,
        "margin": 0,
        "margin_width": 0,
        "margin_height": 0,
        "border_width": 0,
        "border_radius": 0,
        # UI-006 / Step 3.3 hover paint mechanism: ovui's TreeView resolves
        # the *hover* tint from ``background_selected_color`` (see
        # ``ovui/core/src/TreeView.cpp`` row-paint path documented in
        # ``ovui-widgets/ovui_widgets/layers/style.py:33-37``), NOT from
        # ``TreeView:hovered.background_color``. Setting this property is
        # what actually fires when the cursor passes over a Stage row;
        # without it the row hover treatment never paints. Token mirrors
        # the existing ``TreeView:hovered`` value (``cl.background_tertiary``),
        # one notch above the dedicated tree well, so resting / hover /
        # selected paint a consistent three-tier band sequence.
        "background_selected_color": cl.background_tertiary,
    },
    "TreeView.Header": {
        "background_color": cl.treeview_well_background,
        "color": cl.text_primary,
        "height": 0,
        "padding": 0,
        "margin": 0,
        "margin_height": 0,
        "border_width": 0,
        "font_size": 0,
    },
    "TreeView.Item": {
        "color": cl.text_primary,
        "font_size": fl.font_size_small,
        "margin_height": 0,
        "margin_width": 0,
        "margin": 0,
        "padding": 0,
    },
    "TreeView.ScrollingFrame": {
        "padding": 0,
        "margin": 0,
        "border_width": 0,
        "border_radius": 0,
    },
    "TreeView:hovered": {
        "background_color": cl.background_tertiary,
    },
    "TreeView:selected": {
        "background_color": cl.treeview_selection,
    },
    "TreeView.Item:selected": {
        "color": cl.text_primary,
        "font_size": fl.font_size_small,
    },
    "Stage.Name:selected": {
        "color": cl.text_primary,
        "font_size": fl.font_size_small,
    },
    "Stage.SelectionAccent": {
        "background_color": cl.treeview_selection,
        "border_radius": 0,
    },
    "Stage.TreeChevron": {
        "color": cl.text_secondary,
    },

    # ── Type icon ────────────────────────────────────────────────────────
    "Stage.PrimIcon": {
        "color": cl.text_secondary,
    },
    "Stage.Badge": {},

    # ── Visibility eye ───────────────────────────────────────────────────
    "Stage.VisibilityIcon": {
        "color": cl.text_secondary,
    },
    "Stage.VisibilityIcon::visible": {
        "color": cl.text_secondary,
    },
    "Stage.VisibilityIcon::hidden": {
        "color": cl.text_disabled,
    },
    "Stage.VisibilityIcon::disabled": {
        "color": cl.text_disabled,
    },

    # ── Filter bar (UI-001 — design-reference rev-9 anchor) ──────────────
    # The bar is the panel-width strip sitting flush at the top of the
    # Stage column; ``Stage.FilterFieldBorder`` paints the one-pixel ring,
    # while ``Stage.FilterField`` is the inner fill wrapping the magnifier
    # icon + text input + clear button so the icon appears *inside* the field.
    # The StringField itself (``Stage.FilterFieldInput``) is rendered
    # transparent so only the outer Rectangle's border + radius read.
    #
    # Token anchor (locked to ovuiDark rev-9 — OVUI_REFERENCE_IMPLEMENTATION_PLAN
    # Step 3.1 / UI-001):
    #   - resting border tone  → ``cl.border_default`` (#4B4B4B — visible
    #     against the #222222 panel chrome, matches the reference's readable
    #     1 px ring; reaffirmed against ``OvuiSampleApp.png``)
    #   - corner radius        → ``fl.radius_small`` (~3 px, matches the
    #     reference filter pill arc)
    #   - placeholder colour   → ``cl.text_disabled`` (#4B4B4B muted grey,
    #     reads as inactive helper text against the pill fill)
    #   - focused border tone  → ``cl.border_focused`` (#008AF9 selection
    #     blue, mirrored from interactive-focus token; toggled imperatively
    #     via ``rect.name = "focused"`` in ``_on_filter_begin_edit``)
    # The sibling ``Property.SearchField`` selectors carry the same anchor
    # (UI-002 / Property.SearchField sibling contract); the cross-panel
    # pill-token contract is pinned by
    # ``test_property_and_stage_share_pill_tokens``.
    "Stage.FilterBar": {
        "background_color": cl.background_primary,
        "border_radius": 0,
    },
    "Stage.FilterField": {
        "background_color": cl.background_field,
        "border_radius": fl.radius_small,
        "border_width": 0,
        "border_color": cl.border_default,
    },
    # ``Rectangle`` border rendering is inconsistent across the standalone
    # ovui builds, so the live widget also draws a 1 px border rectangle
    # behind the field fill. The token is still the required
    # ``cl.border_default``; this selector exists only to make the border
    # visible in screenshot QA.
    "Stage.FilterFieldBorder": {
        "background_color": cl.border_default,
        "border_radius": fl.radius_small,
    },
    "Stage.FilterField::focused": {
        "border_color": cl.border_focused,
    },
    "Stage.FilterFieldBorder::focused": {
        "background_color": cl.border_focused,
        "border_radius": fl.radius_small,
    },
    "Stage.FilterFieldInput": {
        "background_color": cl.transparent,
        "color": cl.text_primary,
        "border_width": 0,
        "border_radius": 0,
        "padding": 0,
        "font_size": fl.font_size_small,
    },
    "Stage.FilterPlaceholder": {
        "color": cl.text_disabled,
        "font_size": fl.font_size_small,
    },
    "Stage.FilterIcon": {
        "color": cl.text_secondary,
    },
    "Stage.FilterIcon::active": {
        "color": cl.accent_primary,
    },
    "Stage.FilterClearButton.Image": {
        "color": cl.text_secondary,
    },

    # ── Separator between filter and tree ────────────────────────────────
    "Stage.Separator": {
        "background_color": cl.border_default,
    },

    # ── Tree-body scrolling frame ────────────────────────────────────────
    # Step 19: thin, subtle scrollbar matching the Property Inspector.
    # The track is transparent, the thumb is muted at rest, and the
    # hovered/pressed frame state brightens the same thumb token.
    "Stage.ScrollingFrame": {
        "background_color": cl.treeview_well_background,
        "secondary_color": cl.scrollbar_thumb,
        "scrollbar_size": fl.scrollbar_width,
        "border_radius": fl.radius_small,
        "padding": 0,
        "margin": 0,
    },
    "Stage.ScrollingFrame:hovered": {
        "secondary_color": cl.scrollbar_thumb_hovered,
    },
    "Stage.ScrollingFrame:pressed": {
        "secondary_color": cl.scrollbar_thumb_hovered,
    },

    # ── Fixed status footer ──────────────────────────────────────────────
    "Stage.Footer": {
        "background_color": cl.background_primary,
        "color": cl.text_secondary,
        "font_size": fl.font_size_small,
        "border_radius": 0,
        "padding": 0,
    },
    "Stage.Footer.Rule": {
        "background_color": cl.border_default,
        "border_radius": 0,
    },

    # ── Empty-state overlay shown when the tree has no visible children ──
    "Stage.EmptyState": {
        "color": cl.text_disabled,
        "font_size": fl.font_size_small,
    },

    # ── Drop indicator ───────────────────────────────────────────────────
    "Stage.DropIndicator": {
        "background_color": cl.treeview_drop_indicator,
        "border_width": 1,
        "border_color": cl.treeview_drop_indicator,
        "border_radius": 1,
    },

    # ── Inline rename field ──────────────────────────────────────────────
    "Stage.RenameField": {
        "background_color": cl.background_field,
        "color": cl.text_primary,
        "border_color": cl.border_focused,
        "border_width": 1,
        "border_radius": fl.radius_small,
        "padding": 2,
        "font_size": fl.font_size_small,
    },
}

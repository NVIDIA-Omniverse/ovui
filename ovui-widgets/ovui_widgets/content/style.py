# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Content Browser domain-scoped style tokens.

The ``Content.*`` selector namespace covers every widget that lives
inside the Content Browser panel — the three-column row renderer
(Step 8), plus the toolbar / path bar / breadcrumbs / tree / card /
empty-state / scroll / file-bar / splitter blocks that light up in
Steps 13–50. Naming follows style naming rules§5 and theme-aware content style rules:
domain dot-notation types (``Content.<Widget>``), ``::name`` for
variants, ``:state`` for pseudo-states, and ``cl.*`` / ``fl.*``
shaded references so theme switching propagates automatically when
:func:`ovui_widgets.app.style.set_theme` re-applies the merged global style.
"""

from __future__ import annotations

import omni.ui as ui
from omni.ui import color as cl
from omni.ui import constant as fl

CONTENT_STYLES: dict = {
    # ── Row renderer (Step 8 — FileBrowserDelegate name/size/date cells) ──
    "Content.Row.Name": {
        "color": cl.text_primary,
        "font_size": fl.font_size_medium,
    },
    "Content.Row.Name::disabled": {
        "color": cl.text_disabled,
    },
    # Step 36 — Cut variant. Applied by FileBrowserDelegate._build_name_cell
    # and TreeFolderDelegate.build_widget when the row's URL is in the
    # clipboard and the clipboard is in Cut mode. Uses the same
    # ``text_disabled`` colour as the ``::disabled`` variant so the
    # faded look reads the same whether the row is disabled or cut.
    # Matches the ``Content.Card.Label::cut`` / ``Content.Card.Image::cut``
    # siblings further down so the tree rows and grid cards fade
    # identically when a cut is in flight.
    "Content.Row.Name::cut": {
        "color": cl.text_disabled,
    },
    # Step 46 — Missing variant. Applied by NavigationDelegate.build_widget
    # to :class:`RecentFileItem` rows whose backend stat failed (file
    # renamed, moved, or the backing storage is offline). Grey matches
    # the ``::disabled`` / ``::cut`` variants so stale recent entries
    # read as "not live" without visually competing with cut rows. The
    # the content browser implementation step 46 spec calls for "italicised + grey" but
    # ovui's font stack does not ship an italic face — the variant
    # degrades to grey-only, which is still visually distinct from
    # the live text_primary used on reachable recent entries.
    "Content.Row.Name::missing": {
        "color": cl.text_disabled,
    },
    # Navigation-pane collection roots (Bookmarks / My Computer / Recent).
    # These roots are permanent wayfinding labels, not selected content, so
    # they should sit on the same muted text tier as breadcrumbs and card
    # captions until hovered/selected by the nav TreeView.
    "Content.Row.Name::collection": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_small,
    },
    "Content.Row.Name::collection:hovered": {
        "color": cl.text_primary,
        "font_size": fl.font_size_small,
    },
    "Content.Row.Name::collection:selected": {
        "color": cl.text_primary,
        "font_size": fl.font_size_small,
    },
    "Content.Row.Size": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_small,
    },
    "Content.Row.Size::disabled": {
        "color": cl.text_disabled,
    },
    "Content.Row.Date": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_small,
    },
    "Content.Row.Date::disabled": {
        "color": cl.text_disabled,
    },
    # No color override: the PNG asset paints its own fill; omni.ui
    # would otherwise multiply the tint against the source and wash
    # the glyph out. Same contract as Stage.PrimIcon / Stage.Badge.
    "Content.FileIcon": {},
    # Content's branch arrows use the same chevron assets as Stage/Layers, but
    # the light-theme reference needs the glyph restrained to the normal text
    # tone instead of the asset's bright source pixels.
    "Content.BranchGlyph": {
        "color": cl.content_branch_glyph,
    },
    "Content.ColumnHeader": {
        "color": cl.text_primary,
        "font_size": fl.font_size_small,
    },
    "Content.ColumnHeader.ClickArea": {
        "background_color": cl.transparent,
        "border_width": 0,
        "padding": 0,
        "margin": 0,
    },
    "Content.ColumnHeader.ClickArea:hovered": {
        "background_color": cl.background_elevated,
    },
    "Content.SortArrow": {
        "color": cl.accent_primary,
    },

    # ── Toolbar (Step 28 — filter/search chrome above the browser) ────────
    "Content.ToolBar": {
        "background_color": cl.background_primary,
        "padding": fl.spacing_small,
    },
    "Content.ToolBar.Button": {
        "background_color": cl.transparent,
        "border_width": 0,
        "border_radius": fl.radius_small,
        "padding": fl.spacing_small,
        "margin": 0,
    },
    "Content.ToolBar.Button:hovered": {
        "background_color": cl.interactive_hovered,
    },
    "Content.ToolBar.Button:pressed": {
        "background_color": cl.interactive_pressed,
    },
    "Content.ToolBar.Button:disabled": {
        "color": cl.text_disabled,
    },
    "Content.ToolBar.Button.Image": {
        "color": cl.text_secondary,
    },
    "Content.ToolBar.Button.Image:disabled": {
        "color": cl.text_disabled,
    },
    "Content.ToolBar.Separator": {
        "background_color": cl.border_default,
    },

    # ── Path bar + breadcrumbs (Steps 17–20 — navigation row) ─────────────
    "Content.PathBar.Border": {
        "background_color": cl.border_default,
        "border_radius": fl.radius_small,
    },
    "Content.PathBar": {
        "background_color": cl.background_field,
        "border_radius": fl.radius_small,
        "border_width": 0,
    },
    "Content.PathBar.ScrollingFrame": {
        "background_color": cl.transparent,
        "secondary_color": cl.scrollbar_thumb,
        "scrollbar_size": fl.scrollbar_width,
        "border_radius": fl.radius_small,
        "border_width": 0,
        "padding": 0,
        "margin": 0,
    },
    "Content.PathBar.Field": {
        "background_color": cl.transparent,
        "color": cl.content_address_text,
        "border_width": 0,
        "font_size": fl.font_size_medium,
    },
    "Content.PathBar.Field:pressed": {
        "background_color": cl.background_field_editing,
        "border_color": cl.border_focused,
        "border_width": 1,
    },
    # Inline edit mode — a solid opaque background so the typed path
    # is clearly legible against the pane. Swapped in when the user
    # double-clicks the breadcrumb strip to edit the path; the
    # breadcrumb Frame is hidden in that state so there is no stacked
    # text. Same token vocabulary as the stage rename field.
    "Content.PathBar.EditField": {
        "background_color": cl.background_field_editing,
        "color": cl.text_primary,
        "border_color": cl.border_focused,
        "border_width": 1,
        "border_radius": fl.radius_small,
        "font_size": fl.font_size_medium,
        "padding": 2,
    },
    # Transparent overlay rectangle — catches double-clicks that
    # flip the path bar into edit mode. No fill / no border so the
    # breadcrumb layer underneath is visually unaltered; ovui's
    # button-priority hit-testing lets single clicks pass through to
    # the breadcrumb buttons.
    "Content.PathBar.Overlay": {
        "background_color": cl.transparent,
        "border_width": 0,
    },
    "Content.Breadcrumb": {
        "background_color": cl.transparent,
        "color": cl.content_address_text,
        "border_width": 0,
        "border_radius": fl.radius_small,
        "padding": 2,
        "font_size": fl.font_size_medium,
    },
    "Content.Breadcrumb:hovered": {
        "background_color": cl.background_elevated,
    },
    "Content.Breadcrumb:selected": {
        "color": cl.accent_primary,
    },
    "Content.Breadcrumb.Separator": {
        "color": cl.content_address_text,
        "font_size": fl.font_size_medium,
    },

    # ── Path bar autocomplete dropdown (§15.6 / Bug B) ────────────────────
    # The popup window behind the dropdown is allowed to paint its own
    # ImGui chrome but the readable "menu look" lives on the rectangle
    # backdrop painted by :meth:`PathField._open_autocomplete_anchor`.
    # ``Content.PathBar.Autocomplete`` styles that Rectangle — it sits
    # under the row VStack and provides the solid opaque background
    # that distinguishes the popup from the content area behind it
    # (prior to the fix, the labels floated as "ghost text" with no
    # backing rectangle).
    "Content.PathBar.Autocomplete": {
        "background_color": cl.background_secondary,
        "border_color": cl.border_default,
        "border_width": 1,
        "border_radius": fl.radius_small,
    },
    # Each suggestion row is a :class:`ui.Button`; the ``Item`` selector
    # strips the default button chrome (transparent idle fill, no
    # border) so the row reads as a menu item rather than a raised
    # control. ``:hovered`` lights up the interactive_hovered tint from
    # the palette so mouse affordance is obvious; ``::selected`` is the
    # keyboard-highlight variant set by the Down/Up cycling path.
    "Content.PathBar.Autocomplete.Item": {
        "background_color": cl.transparent,
        "color": cl.text_primary,
        "border_width": 0,
        "border_radius": fl.radius_small,
        "padding": 2,
        "margin": 0,
        "font_size": fl.font_size_medium,
    },
    "Content.PathBar.Autocomplete.Item:hovered": {
        "background_color": cl.interactive_hovered,
    },
    "Content.PathBar.Autocomplete.Item:pressed": {
        "background_color": cl.interactive_pressed,
    },
    "Content.PathBar.Autocomplete.Item::selected": {
        "background_color": cl.accent_primary,
        "color": cl.text_on_accent,
    },
    "Content.PathBar.Autocomplete.Item::selected:hovered": {
        "background_color": cl.accent_hovered,
    },

    # ── Tree view (Step 9 — file hierarchy in the left pane) ──────────────
    "Content.TreeView": {
        "background_color": cl.treeview_well_background,
        "color": cl.text_primary,
        "secondary_color": cl.transparent,
        "background_selected_color": cl.background_tertiary,
        "font_size": fl.font_size_medium,
        "border_radius": fl.radius_none,
        "border_width": 0,
        "padding": 0,
        "margin": 0,
        "margin_width": 0,
        "margin_height": 0,
    },
    "Content.TreeView:hovered": {
        "background_color": cl.background_tertiary,
    },
    "Content.TreeView:selected": {
        "background_color": cl.treeview_selection,
    },
    "Content.TreeView.Header": {
        "background_color": cl.treeview_well_background,
        "color": cl.text_primary,
        "font_size": fl.font_size_small,
        "padding": 2,
        "margin": 0,
        "margin_width": 0,
        "margin_height": 0,
        "border_width": 0,
    },
    "Content.TreeView.Item": {
        "color": cl.text_primary,
        "font_size": fl.font_size_medium,
        "padding": 0,
        "margin": 0,
        "margin_width": 0,
        "margin_height": 0,
    },
    "Content.TreeView.Item:selected": {
        "color": cl.text_primary,
    },
    "Content.TreeView.Item::disabled": {
        "color": cl.text_disabled,
    },
    "Content.TreeView.Icon": {
        "color": cl.text_primary,
    },
    "Content.TreeView.Icon:selected": {
        "color": cl.text_on_accent,
    },
    "Content.TreeView.BranchFill": {
        "background_color": cl.transparent,
        "border_radius": fl.radius_none,
    },
    "Content.TreeView.BranchFill:hovered": {
        "background_color": cl.background_tertiary,
    },
    "Content.TreeView.BranchFill:selected": {
        "background_color": cl.treeview_selection,
    },
    "Content.TreeView.ScrollingFrame": {
        "background_color": cl.treeview_well_background,
        "secondary_color": cl.scrollbar_thumb,
        "scrollbar_size": 6,
        "padding": 0,
        "margin": 0,
        "border_width": 0,
        "border_radius": 0,
    },

    # ── Grid / card (Steps 21–25 — thumbnail view) ────────────────────────
    "Content.Card": {
        "background_color": cl.transparent,
        "border_radius": fl.radius_small,
        "border_width": 0,
        "padding": 0,
        "margin": 1,
    },
    "Content.Card:hovered": {
        "background_color": cl.background_primary,
    },
    "Content.Card:pressed": {
        "background_color": cl.interactive_pressed,
    },
    "Content.Card:selected": {
        "background_color": cl.accent_primary,
    },
    # Step 41 — drop-hover variant. Applied by :class:`DropIndicator`
    # via ``card._rect.name = "drop_hover"`` while a compatible drag is
    # hovering over the card's hit rect. Uses ``treeview_drop_indicator``
    # so the feedback reads identically to the Stage Browser's
    # ``Stage.TreeView:drop`` background and to the content-browser
    # tree-row tint painted by :meth:`DropIndicator.show_row_highlight`.
    # Kept as a ``name``-variant rather than a ``:drop`` pseudo-state
    # so the controller can apply / revert the variant deliberately
    # (ovui's ``:drop`` state fires automatically for every accept-
    # drop widget during a drag, including ones the indicator has no
    # semantic reason to paint).
    "Content.Card::drop_hover": {
        "background_color": cl.treeview_drop_indicator,
    },
    # No base color override: asset / thumbnail PNGs carry their own
    # fill (coloured asset-category icons, user-supplied thumbnails),
    # and omni.ui multiplies :attr:`color` against the source — a
    # text_primary tint renders near-white under dark and near-black
    # under light, washing every colour icon to black in the light
    # shade. Matching the ``Content.FileIcon`` / ``Stage.Badge``
    # contract (empty dict) lets the source pixels paint through in
    # both themes. The ``::cut`` variant DOES tint (to text_disabled)
    # because dimming is the intended visual for cut items.
    "Content.Card.Image": {},
    "Content.Card.Image::cut": {
        "color": cl.text_disabled,
    },
    "Content.Card.Label": {
        "color": cl.content_card_label_text,
        "font_size": fl.font_size_small,
    },
    "Content.Card.Label:selected": {
        "color": cl.text_on_accent,
    },
    "Content.Card.Label::cut": {
        "color": cl.text_disabled,
    },

    # ── Inline rename field (Step 33 — active rename target) ───────────────
    # Shared selector for the :class:`ui.StringField` that replaces the
    # name label in the tree-pane row, the detail-pane row, and the
    # grid card when a rename is in flight. Matches the ovui_widgets.stage
    # ``Stage.RenameField`` contract: pale editing background, focused
    # border, and a 1-px left pad so the text doesn't kiss the field's
    # edge. A single selector for both tree/detail/grid keeps the three
    # rename surfaces visually identical.
    "Content.RenameField": {
        "background_color": cl.background_field_editing,
        "border_color": cl.border_focused,
        "border_width": 1,
        "border_radius": fl.radius_small,
        "color": cl.text_primary,
        "font_size": fl.font_size_medium,
        "padding": 1,
    },

    # ── Empty state / loading overlay (Step 15) ───────────────────────────
    "Content.EmptyState": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_medium,
    },
    "Content.LoadingSpinner": {
        "color": cl.text_secondary,
    },

    # ── Scroll (shared between tree and grid views) ───────────────────────
    # ``scrollbar_size: 6`` matches ``Stage.ScrollingFrame`` — thin
    # scrollbar contract across every OvGear panel now that dock-tab
    # chrome is hidden (style naming rules consistency requirement).
    "Content.ScrollingFrame": {
        "background_color": cl.background_secondary,
        "secondary_color": cl.scrollbar_thumb,
        "scrollbar_size": 6,
        "padding": 0,
        "margin": 0,
        "border_radius": fl.radius_none,
    },

    # ── Splitter (Step 13 — draggable handle between tree and detail) ─────
    "Content.Splitter": {
        "background_color": cl.content_splitter_handle,
        "border_radius": fl.radius_none,
    },
    "Content.Splitter:hovered": {
        "background_color": cl.splitter_handle_hovered,
    },
    "Content.Splitter:pressed": {
        "background_color": cl.splitter_handle_hovered,
    },

    # ── Zoom bar (Step 23 — thumbnail size slider + grid/list toggle) ─────
    # The ``Content.ZoomBar`` family mirrors ``Content.ToolBar``'s hover /
    # pressed / disabled contract so the bar's toggle button reads
    # consistent with the browser-bar navigation buttons a row above it
    # (style naming rules§5 consistency).
    "Content.ZoomBar": {
        "background_color": cl.transparent,
        "padding": 0,
    },
    "Content.ZoomBar.Button": {
        "background_color": cl.transparent,
        "border_width": 0,
        "border_radius": fl.radius_small,
        "padding": 0,
        "margin": 0,
    },
    "Content.ZoomBar.Button:hovered": {
        "background_color": cl.interactive_hovered,
    },
    "Content.ZoomBar.Button:pressed": {
        "background_color": cl.interactive_pressed,
    },
    "Content.ZoomBar.Button.Image": {
        "color": cl.text_secondary,
    },
    # Compact track + drag-handle rendering, theme-aware colours.
    # ``draw_mode = HANDLE`` keeps omni.ui out of its default FILLED
    # "progress-bar" path, which paints the entire widget rectangle
    # with ``secondary_color`` (accent) on the left and ``background_color``
    # on the right — that renders as a fat "filling box" and is the look
    # PR #17 accidentally shipped. HANDLE mode instead routes
    # ``background_color`` → ImGui ``FrameBg`` (the track) and
    # ``secondary_color`` → ImGui ``SliderGrab`` (the knob), which is
    # the slim-bar-with-handle shape the zoom slider was always meant
    # to be. ``border_default`` is theme-aware
    # (``#16171A`` dark / ``#D0D0D0`` light) so the track remains
    # subtly visible against the panel in both shades without
    # dominating the row.
    "Content.ZoomBar.Slider": {
        "draw_mode": ui.SliderDrawMode.HANDLE,
        "background_color": cl.content_zoom_slider_track,
        "secondary_color": cl.content_zoom_slider_thumb,
        "color": cl.text_primary,
        "border_radius": fl.radius_small,
        "padding": 0,
        "font_size": fl.font_size_small,
    },
    "Content.ZoomBar.Label": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_small,
    },

    # ── Search field (Step 27 — in-folder substring filter) ──────────────
    # Bug 14 — visual identity with the stage filter pill. The widget
    # mirrors ``ovui_widgets.stage``'s layout: an outer ``Content.SearchField.Bar``
    # strip (no radius) wraps an inner input pill. The 1-px ring is a
    # ``Content.SearchField.Border`` Rectangle sitting behind a
    # borderless ``Content.SearchField`` fill Rectangle — ovui's
    # single-Rectangle border render is unreliable across builds, so the
    # double-rectangle trick is required to make the 1-px border read. The StringField
    # (``Content.SearchField.Input``) is rendered transparent so only
    # the outer border + radius show. The ``::focused`` variant is
    # applied imperatively by the widget on begin/end edit because
    # omni.ui's ``:focused`` state does not fire on a Rectangle.
    "Content.SearchField.Bar": {
        "background_color": cl.background_primary,
        "border_radius": 0,
    },
    "Content.SearchField": {
        "background_color": cl.background_field,
        "border_radius": fl.radius_small,
        "border_width": 0,
        "border_color": cl.border_default,
    },
    "Content.SearchField.Border": {
        "background_color": cl.border_default,
        "border_radius": fl.radius_small,
    },
    "Content.SearchField::focused": {
        "border_color": cl.border_focused,
    },
    "Content.SearchField.Border::focused": {
        "background_color": cl.border_focused,
        "border_radius": fl.radius_small,
    },
    "Content.SearchField.Input": {
        "background_color": cl.transparent,
        "color": cl.content_address_text,
        "border_width": 0,
        "border_radius": 0,
        "padding": 0,
        "font_size": fl.font_size_small,
    },
    "Content.SearchField.Placeholder": {
        "color": cl.content_address_text,
        "font_size": fl.font_size_small,
    },
    "Content.SearchField.Icon": {
        "color": cl.text_secondary,
    },
    "Content.SearchField.Icon::active": {
        "color": cl.accent_primary,
    },
    "Content.SearchField.Clear.Image": {
        "color": cl.text_secondary,
    },

    # ── Highlight label (Step 29 — search-match painting) ────────────────
    # Rendered as a :class:`ui.HStack` of alternating Labels — non-match
    # segments inherit ``::normal`` (which uses :class:`cl.text_primary`
    # like the surrounding Name column / card label), match segments
    # switch to ``::highlight`` (warm yellow :class:`cl.highlight_highlight`).
    # The bare ``Content.HighlightLabel`` entry paints the container so a
    # whole-widget selector (state theme override, padding) has a home
    # even though no shared visual layer is needed at Step 29.
    "Content.HighlightLabel": {},
    "Content.HighlightLabel::normal": {
        "color": cl.text_primary,
        "font_size": fl.font_size_medium,
    },
    "Content.HighlightLabel::highlight": {
        "color": cl.highlight_highlight,
        "font_size": fl.font_size_medium,
    },

    # ── File picker dialog/bar (Steps 47–48 — browser + filename footer) ──
    "Content.FilePickerDialog": {
        "background_color": cl.background_primary,
        "border_width": 0,
    },
    "Content.FileBar": {
        "background_color": cl.background_primary,
        "border_width": 0,
    },
    "Content.FileBar.Label": {
        "color": cl.text_primary,
        "font_size": fl.font_size_value,
    },
    "Content.FileBar.Field": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "color": cl.text_primary,
        "border_radius": fl.radius_small,
        "border_color": cl.border_default,
        "border_width": 1,
        "padding": 2,
        "font_size": fl.font_size_value,
    },
    "Content.FileBar.Field:pressed": {
        "background_color": cl.background_field_editing,
        "secondary_color": cl.background_field_editing,
        "border_color": cl.border_focused,
    },
    "Content.FileBar.Field:focused": {
        "background_color": cl.background_field_editing,
        "secondary_color": cl.background_field_editing,
        "border_color": cl.border_focused,
    },
    "Content.FileBar.ComboBoxBorder": {
        "background_color": cl.border_default,
        "border_radius": fl.radius_small,
    },
    "Content.FileBar.ComboBox": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "color": cl.text_value,
        "border_radius": fl.radius_small,
        "border_color": cl.transparent,
        "border_width": 0,
        "padding": 2,
        "margin": 0,
        "font_size": fl.font_size_value,
    },
    "Content.FileBar.ComboBox:hovered": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "border_color": cl.transparent,
    },
    "Content.FileBar.ComboBox:pressed": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "border_color": cl.transparent,
    },
    "Content.FileBar.ComboBox:focused": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "border_color": cl.transparent,
    },
    "Content.FileBar.ComboBox:disabled": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "color": cl.text_disabled,
        "border_color": cl.transparent,
    },
    "Content.FileBar.ComboBox.Label": {
        "color": cl.text_value,
        "font_size": fl.font_size_value,
    },
    "Content.FileBar.ComboBoxChevron": {
        "color": cl.text_secondary,
    },
    "Content.FileBar.DropdownPopup": {
        "background_color": cl.background_field,
        "border_color": cl.border_default,
        "border_width": 1,
        "border_radius": fl.radius_small,
    },
    "Content.FileBar.DropdownItemBackground": {
        "background_color": cl.background_field,
        "border_width": 0,
        "border_radius": fl.radius_none,
        "margin": 0,
    },
    "Content.FileBar.DropdownItemBackground:hovered": {
        "background_color": cl.menu_selection,
    },
    "Content.FileBar.DropdownItemBackground:pressed": {
        "background_color": cl.menu_selection,
    },
    "Content.FileBar.DropdownItemBackgroundSelected": {
        "background_color": cl.menu_selection,
        "border_width": 0,
        "border_radius": fl.radius_none,
        "margin": 0,
    },
    "Content.FileBar.DropdownItemBackgroundSelected:hovered": {
        "background_color": cl.menu_selection,
    },
    "Content.FileBar.DropdownItemLabel": {
        "color": cl.text_primary,
        "font_size": fl.menu_item_font_size,
        "padding": 4,
        "margin": 0,
    },
}

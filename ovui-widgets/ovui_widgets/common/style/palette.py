# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Colour palette definitions (OvGear design system, design-system style rules).

All colours are registered as named shades in omni.ui.ColorStore so they
respond to ui.set_shade() theme switching.  Dark values are the default;
light values activate under ui.set_shade("light").

Dark values follow the latest design-reference hierarchy for this pass:
  - broad application/window/menu chrome: #222222
  - tree, icon-grid, and input wells: #161616
  - #313131 stays reserved for hover and raised affordances
  - content-base #E0E0E0, content-subtle #CCCCCC, content-disabled #4B4B4B
  - interactive-active / interactive-focus #008AF9 (selection blue)
"""

import omni.ui as ui  # noqa: F401 — ensures ColorStore is initialised
from omni.ui import color as cl

# ---------------------------------------------------------------------------
# Backgrounds — follow the latest design-reference two-tier correction against
# ``OvuiSampleApp.png``: broad docked panel/menu chrome sits on #222222, while
# tree wells, icon-grid bodies, and input fields sit on #161616.
# ---------------------------------------------------------------------------
cl.shade(cl("#222222"), light=cl("#E0E0E0"), name="background_primary")
cl.shade(cl("#161616"), light=cl("#CCCCCC"), name="background_secondary")
cl.shade(cl("#222222"), light=cl("#D6D6D6"), name="background_tertiary")
cl.shade(cl("#313131"), light=cl("#E5E5E5"), name="background_elevated")

# Outermost dockspace void (UI-021). The latest design-reference correction
# makes the broad application background match the window/panel chrome at
# #222222. Wired through
# ``application.py::dock_frame.set_style({"background_color": ...})``,
# which the C++ ``DockSpace.cpp::m_dockFrame`` resolves and pushes as
# ``ImGuiCol_WindowBg`` per frame.
cl.shade(cl("#222222"), light=cl("#E0E0E0"), name="dockspace_void")

# ---------------------------------------------------------------------------
# Text — neutral grey family matching ovuiDark content tokens
# ---------------------------------------------------------------------------
cl.shade(cl("#E0E0E0"), light=cl("#111111"), name="text_primary")
cl.shade(cl("#A7A7A7"), light=cl("#333333"), name="text_secondary")
cl.shade(cl("#4B4B4B"), light=cl("#8A8A8A"), name="text_disabled")
cl.shade(cl("#FFFFFF"), light=cl("#FFFFFF"), name="text_on_accent")
cl.shade(cl("#F0F0F0"), light=cl("#111111"), name="text_value")
cl.shade(cl("#A7A7A7"), light=cl("#111111"), name="content_address_text")
cl.shade(cl("#4B4B4B"), light=cl("#333333"), name="button_disabled_text")

# ---------------------------------------------------------------------------
# Borders — visible but restrained. ``border_default`` is consumed by field
# outlines and separators, so it follows the ovuiDark partition tier while
# ``border_strong`` is reserved for hover/focus-adjacent emphasis.
# ---------------------------------------------------------------------------
cl.shade(cl("#4B4B4B"), light=cl("#A8A8A8"), name="border_default")
cl.shade(cl("#636363"), light=cl("#808080"), name="border_strong")
cl.shade(cl("#008AF9"), light=cl("#0078D4"), name="border_focused")
cl.shade(cl("#4B4B4B"), light=cl("#C8C8C8"), name="property_value_border")
cl.shade(cl("#4B4B4B"), light=cl("#C8C8C8"), name="property_dropdown_border")

# ---------------------------------------------------------------------------
# Interactive states — interactive-* / background tokens. Defaults sit on
# the raised-panel surface so unselected buttons read as quiet tiles, not
# black holes.
# ---------------------------------------------------------------------------
cl.shade(cl("#222222"), light=cl("#E0E0E0"), name="interactive_default")
cl.shade(cl("#313131"), light=cl("#D4D4D4"), name="interactive_hovered")
cl.shade(cl("#0060C7"), light=cl("#C8C8C8"), name="interactive_pressed")
cl.shade(cl("#161616"), light=cl("#E8E8E8"), name="interactive_disabled")

# ---------------------------------------------------------------------------
# Accent / brand. Aligns with ovuiDark interactive-active #008AF9 — used
# for focus, active/highlight states, property authored dots, and viewport
# selection outlines.
# ---------------------------------------------------------------------------
cl.shade(cl("#008AF9"), light=cl("#008AF9"), name="accent_primary")
cl.shade(cl("#1FA0FF"), light=cl("#1FA0FF"), name="accent_hovered")
cl.shade(cl("#0060C7"), light=cl("#0060C7"), name="accent_pressed")
cl.shade(cl("#008AF9"), light=cl("#008AF9"), name="accent_secondary")

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
cl.shade(cl("#CC3333"), light=cl("#CC1111"), name="status_error")
cl.shade(cl("#E04444"), light=cl("#DD2222"), name="status_error_hovered")
cl.shade(cl("#DDAA50"), light=cl("#BB6600"), name="status_warning")
cl.shade(cl("#8AD089"), light=cl("#5A9100"), name="status_success")
cl.shade(cl("#68A8FF"), light=cl("#2266AA"), name="status_info")

# ---------------------------------------------------------------------------
# Property Inspector
# ---------------------------------------------------------------------------
cl.shade(cl("#008AF980"), light=cl("#008AF9"), name="property_state_indicator_active")
cl.shade(cl("#CCCCCC"), light=cl("#111111"), name="property_label_text")

# ---------------------------------------------------------------------------
# Content Browser
# ---------------------------------------------------------------------------
cl.shade(cl("#CCCCCC"), light=cl("#333333"), name="content_card_label_text")
cl.shade(cl("#FFFFFF"), light=cl("#333333"), name="content_branch_glyph")
cl.shade(cl("#2A2A2A"), light=cl("#D2D2D2"), name="content_zoom_slider_track")
cl.shade(cl("#4B4B4B"), light=cl("#707070"), name="content_zoom_slider_thumb")
cl.shade(cl("#2A2A2A"), light=cl("#A8A8A8"), name="content_splitter_handle")

# ---------------------------------------------------------------------------
# TreeView
# ---------------------------------------------------------------------------
cl.shade(cl("#161616"), light=cl("#CCCCCC"), name="treeview_well_background")
cl.shade(cl("#232429"), light=cl("#B8C8D8"), name="treeview_selection")
cl.shade(cl("#262626"), light=cl("#A6A6A6"), name="treeview_branch_line")
cl.shade(cl("#008AF9"), light=cl("#008AF9"), name="treeview_drop_indicator")

# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
cl.shade(cl("#222222"), light=cl("#E5E5E5"), name="menu_background")
cl.shade(cl("#313238"), light=cl("#B8C8D8"), name="menu_selection")
cl.shade(cl("#313238"), light=cl("#B8C8D8"), name="menu_bar_selection")
cl.shade(cl("#262626"), light=cl("#A8A8A8"), name="main_menu_underline")

# ---------------------------------------------------------------------------
# Scrollbar — invisible track, muted resting thumb, brighter hover thumb
# ---------------------------------------------------------------------------
cl.shade(0x0, light=0x0, name="scrollbar_track")
cl.shade(cl("#4B4B4B66"), light=cl("#70707099"), name="scrollbar_thumb")
cl.shade(cl("#75757599"), light=cl("#505050AA"), name="scrollbar_thumb_hovered")

# ---------------------------------------------------------------------------
# Dock tab strip (UI-020). The seven shades below feed
# ``apply_imgui_splitter_style`` which writes them into ``ImGuiStyle.Colors``
# at indices 34–40 (TabHovered / Tab / TabSelected /
# TabSelectedOverline / TabDimmed / TabDimmedSelected /
# TabDimmedSelectedOverline). Dark tabs follow the reference strip colors;
# light tabs use the matching light-theme surface tiers so they do not read as
# black UI chrome. The inactive tab and empty strip stay on the same tier so
# the simple inactive-tab separators remain visible without a separate band.
# ---------------------------------------------------------------------------
cl.shade(cl("#161616"), light=cl("#CCCCCC"), name="dock_tab")
cl.shade(cl("#222222"), light=cl("#D6D6D6"), name="dock_tab_hovered")
cl.shade(cl("#222222"), light=cl("#E0E0E0"), name="dock_tab_selected")
cl.shade(cl("#222222"), light=cl("#E0E0E0"), name="dock_tab_selected_overline")
cl.shade(cl("#161616"), light=cl("#CCCCCC"), name="dock_tab_dimmed")
cl.shade(cl("#222222"), light=cl("#E0E0E0"), name="dock_tab_dimmed_selected")
cl.shade(cl("#222222"), light=cl("#E0E0E0"), name="dock_tab_dimmed_selected_overline")
cl.shade(cl("#E0E0E0"), light=cl("#111111"), name="dock_tab_text")

# ---------------------------------------------------------------------------
# Splitter — quiet 1-px gutter matching the main menu underline so docked
# window separators read as structure without competing with panel content.
# ---------------------------------------------------------------------------
cl.shade(cl("#262626"), light=cl("#A8A8A8"), name="splitter_handle")
cl.shade(cl("#4B4B4B"), light=cl("#8A8A8A"), name="splitter_handle_hovered")

# ---------------------------------------------------------------------------
# Field (shared across StringField / FloatField / IntField / ComboBox /
# filter fields, so named role-first per style naming rules Option D).
# Field fills stay on the #161616 well tier in rest and edit states;
# focus is expressed by the border, not by lifting the fill.
# ---------------------------------------------------------------------------
cl.shade(cl("#161616"), light=cl("#EEEEEE"), name="background_field")
cl.shade(cl("#161616"), light=cl("#F8F8F8"), name="background_field_editing")
cl.shade(cl("#161616"), light=cl("#EEEEEE"), name="background_value_field")
cl.shade(cl("#161616"), light=cl("#F8F8F8"), name="background_value_field_editing")

# ---------------------------------------------------------------------------
# Special
# ---------------------------------------------------------------------------
cl.shade(0x0, name="transparent")
cl.shade(0x40000000, light=0x80FFFFFF, name="hud_background")

# ---------------------------------------------------------------------------
# Highlight (search-match painting — Content.HighlightLabel::highlight)
# ---------------------------------------------------------------------------
# Warm yellow called out by architecture §33.5 for the content browser's
# match-highlight pigment. Same value across dark and light themes — the
# hue is a "marker" colour whose job is to pop against any background,
# so dimming it for the light theme would defeat the point.
cl.shade(cl("#DFCB4A"), light=cl("#DFCB4A"), name="highlight_highlight")

# ---------------------------------------------------------------------------
# Prim-type icon tints (UI-033 — design-reference rev-9 anchor)
# ---------------------------------------------------------------------------
# Step 3.4 / UI-033: the reference's Stage tree reads as a calm flat list of
# neutral labels — no saturated prim-type squares, no high-chroma default-prim
# pill. The tokens below are toned to that baseline so any current or future
# consumer (``Stage.PrimIcon``, ``Stage.Badge``, ``Stage.DefaultPrimPill``)
# inherits a quiet/neutral default that does not pull the eye away from the
# panel body. Hue cues are preserved (cool blue for mesh, warm gold for light,
# cool neutral for camera) but luminance and saturation are lowered toward the
# ``cl.text_secondary`` (#A7A7A7) family so the icons read as quiet glyphs
# rather than as color tokens. The default-prim pill background drops to
# ``#1F1F1F`` — a quiet neutral fill between the tree well and panel body — which
# removes the prior blue tint and lets the [DEF] pill recede into the panel.
cl.shade(cl("#7A8FA8"), light=cl("#4D5A66"), name="prim_type_mesh")
cl.shade(cl("#B09269"), light=cl("#7A6238"), name="prim_type_light")
cl.shade(cl("#8A93A8"), light=cl("#555C6A"), name="prim_type_camera")
cl.shade(cl("#1F1F1F"), light=cl("#D0D0D0"), name="stage_default_prim_pill_background")

# ---------------------------------------------------------------------------
# Layers panel  (LAYERS-PLAN Step 11)
# Component-specific per style naming rules Option D: used by exactly one
# widget type (the Layers window tree), so the `layers_` prefix is the
# canonical scope. Kept separate from the shared `treeview_*` tokens
# because these carry Layers-specific semantics (edit-target green,
# outdated blue, missing red) that only make sense inside the Layers UI.
# ---------------------------------------------------------------------------
cl.shade(cl("#3E652F"), light=cl("#76A371"), name="layers_row_edit_target")
cl.shade(cl("#222222"), light=cl("#D6D6D6"), name="layers_row_hover")
# Group D (audit issue #5) — selected rows reuse the shared
# ``treeview_selection`` token so Stage and Layers paint identically on
# selection. The former ``layers_row_selected`` (#5A5A5A) duplicated the
# role at a different shade and has been removed.
cl.shade(cl("#FF6B6B"), light=cl("#D13C3C"), name="layers_label_missing")
cl.shade(cl("#808080"), light=cl("#A0A0A0"), name="layers_label_disabled")
cl.shade(cl("#4B4B4B"), light=cl("#8A8A8A"), name="layers_button_disabled_text")
cl.shade(cl("#57B44D"), light=cl("#3E8C37"), name="layers_icon_edit_target")
# Half-green hint for ancestor rows that contain the edit target somewhere
# below a collapsed branch (LAYERS-PLAN Step 25-26). Dimmer than the full
# ``layers_icon_edit_target`` so the ancestor reads as a quiet signal
# rather than a second authoring-layer badge.
cl.shade(cl("#3E8C37"), light=cl("#A6C6A0"), name="layers_icon_half_edit")
cl.shade(cl("#0097FF"), light=cl("#008AF9"), name="layers_icon_outdated")
# Dirty / save indicator — amber dot on column 2. Amber instead of red
# because the layer is *saveable*, not in error; red stays reserved for
# layers_label_missing and future save-failure state (Step 33).
cl.shade(cl("#E0A030"), light=cl("#8A5A00"), name="layers_icon_save_dirty")
# Read-only backdrop — muted amber-brown tint painted behind the
# clickable padlock on column 6 when the backing file is not writable
# on disk (LAYERS-PLAN Step 27). Shares the amber hue with
# ``layers_icon_save_dirty`` so the "write-blocked" colour family
# reads as one vocabulary, but lands a step darker + more desaturated
# so it reads as a passive backdrop rather than a call to action.
cl.shade(cl("#5A4530"), light=cl("#C8B08A"), name="layers_icon_readonly_backdrop")

# Drop-indicator vocabulary (LAYERS-PLAN Step 44). Three colour slots
# cover every drag-hover visual the Layers tree paints:
#   - ``layers_drop_target`` — valid "drop onto" outline. Green so the
#     colour reads as "yes, you can release here" and matches the
#     existing edit-target green so the user already reads green as
#     "authoring-relevant". Slightly brighter than
#     ``layers_icon_edit_target`` so the transient drag cue stands out
#     from the steady-state edit-target fill and doesn't merge with it
#     when the drop target happens to be the authoring layer.
#   - ``layers_drop_between`` — horizontal line for a valid between-
#     drop. Bright blue so the stripe reads as "insertion point" rather
#     than "highlight row"; blue is reserved for drag mechanics in the
#     Layers palette (the outdated/version icon is the only other blue
#     cue and it's muted by comparison).
#   - ``layers_drop_rejected`` — invalid drop outline. Red so the user
#     immediately reads "this will not land here"; a distinct red from
#     ``layers_label_missing`` so a missing *and* rejected target
#     (hovered with a locked parent on disk) doesn't collapse into one
#     colour mass.
cl.shade(cl("#76E050"), light=cl("#2E9B22"), name="layers_drop_target")
cl.shade(cl("#40A8FF"), light=cl("#1E6FD0"), name="layers_drop_between")
cl.shade(cl("#E05050"), light=cl("#C02020"), name="layers_drop_rejected")

# ---------------------------------------------------------------------------
# Channel axis colours. The reference inspector keeps X/Y/Z/W labels neutral
# instead of chromatic, while preserving distinct palette slots for tests and
# future channel-specific overrides.
# ---------------------------------------------------------------------------
cl.shade(cl("#A7A7A7"), light=cl("#333333"), name="channel_x")
cl.shade(cl("#A7A7A7"), light=cl("#333333"), name="channel_y")
cl.shade(cl("#A7A7A7"), light=cl("#333333"), name="channel_z")
cl.shade(cl("#A7A7A7"), light=cl("#333333"), name="channel_w")

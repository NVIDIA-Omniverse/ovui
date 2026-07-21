# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Global omni.ui style dictionary for all OvGear widgets (design-system style rules).

GLOBAL_STYLES is assigned to ui.style.default at startup. All color values
use cl.* string references resolved from ColorStore, and float values use
fl.* references resolved from FloatStore, so styles update automatically
when ui.set_shade() switches the active theme.
"""

import importlib.resources

import omni.ui as ui
from omni.ui import color as cl
from omni.ui import constant as fl

from ovui_widgets.common.style.urls import get_icon_path

_MENU_EXPAND_MARK_ICON = str(
    importlib.resources.files("ovui_widgets.common").joinpath("icons/chevron_right.png")
)

GLOBAL_STYLES: dict = {
    # -----------------------------------------------------------------------
    # Button — base and states
    # -----------------------------------------------------------------------
    "Button": {
        "background_color": cl.interactive_default,
        "color": cl.text_primary,
        "border_radius": fl.radius_medium,
        "border_color": cl.border_default,
        "border_width": 1,
        "padding": 4,
        "margin": 2,
        "font_size": fl.font_size_medium,
    },
    "Button:hovered": {
        "background_color": cl.interactive_hovered,
    },
    "Button:pressed": {
        "background_color": cl.interactive_pressed,
    },
    "Button:disabled": {
        "background_color": cl.interactive_disabled,
        "color": cl.button_disabled_text,
    },
    "Button:checked": {
        "background_color": cl.accent_primary,
        "color": cl.text_on_accent,
    },
    # Sub-element: label
    "Button.Label": {
        "color": cl.text_primary,
        "font_size": fl.font_size_medium,
    },
    "Button.Label:hovered": {
        "color": cl.text_primary,
    },
    "Button.Label:disabled": {
        "color": cl.button_disabled_text,
    },
    "Button.Label:checked": {
        "color": cl.text_on_accent,
    },
    # Named variant: ok
    "Button::ok": {
        "background_color": cl.accent_primary,
        "border_color": cl.accent_primary,
    },
    "Button::ok:hovered": {
        "background_color": cl.accent_hovered,
    },
    "Button.Label::ok": {
        "color": cl.text_on_accent,
    },
    # Named variant: cancel
    "Button::cancel": {
        "background_color": cl.interactive_default,
        "border_color": cl.border_default,
    },
    "Button::cancel:hovered": {
        "background_color": cl.interactive_hovered,
    },
    "Button.Label::cancel": {
        "color": cl.text_primary,
    },
    # Named variant: destructive
    "Button::destructive": {
        "background_color": cl.status_error,
        "border_color": cl.status_error,
    },
    "Button::destructive:hovered": {
        "background_color": cl.status_error_hovered,
    },
    "Button.Label::destructive": {
        "color": cl.text_on_accent,
    },
    # Independent button types
    "OKButton": {
        "background_color": cl.accent_primary,
        "color": cl.text_on_accent,
        "border_radius": fl.radius_medium,
        "border_color": cl.accent_primary,
        "border_width": 1,
        "padding": 4,
        "margin": 2,
        "font_size": fl.font_size_medium,
    },
    "OKButton:hovered": {
        "background_color": cl.accent_hovered,
    },
    "OKButton:pressed": {
        "background_color": cl.accent_pressed,
    },
    "OKButton.Label": {
        "color": cl.text_on_accent,
        "font_size": fl.font_size_medium,
    },
    "CancelButton": {
        "background_color": cl.interactive_default,
        "color": cl.text_primary,
        "border_radius": fl.radius_medium,
        "border_color": cl.border_default,
        "border_width": 1,
        "padding": 4,
        "margin": 2,
        "font_size": fl.font_size_medium,
    },
    "CancelButton:hovered": {
        "background_color": cl.interactive_hovered,
    },
    "CancelButton:pressed": {
        "background_color": cl.interactive_pressed,
    },
    "CancelButton.Label": {
        "color": cl.text_primary,
        "font_size": fl.font_size_medium,
    },
    # -----------------------------------------------------------------------
    # Label
    # -----------------------------------------------------------------------
    "Label": {
        "color": cl.text_primary,
        "font_size": fl.font_size_medium,
    },
    "Label:disabled": {
        "color": cl.text_disabled,
    },
    # -----------------------------------------------------------------------
    # CheckBox
    # -----------------------------------------------------------------------
    "CheckBox": {
        "background_color": cl.background_field,
        "color": cl.border_default,
        "border_radius": fl.radius_small,
        "border_color": cl.border_default,
        "border_width": 1,
        "font_size": fl.font_size_medium,
    },
    "CheckBox:hovered": {
        "border_color": cl.border_strong,
    },
    "CheckBox:checked": {
        "color": cl.accent_primary,
        "background_color": cl.background_field,
    },
    "CheckBox:disabled": {
        "background_color": cl.interactive_disabled,
        "color": cl.text_disabled,
    },
    # -----------------------------------------------------------------------
    # Field (StringField / FloatField / IntField)
    # -----------------------------------------------------------------------
    "Field": {
        "background_color": cl.background_field,
        "color": cl.text_value,
        "border_radius": fl.radius_small,
        "border_color": cl.border_default,
        "border_width": 1,
        "font_size": fl.font_size_value,
    },
    "Field:hovered": {
        "border_color": cl.border_default,
    },
    "Field:pressed": {
        "background_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    "Field:focused": {
        "background_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    "Field:disabled": {
        "background_color": cl.background_field,
        "color": cl.text_disabled,
        "border_color": cl.border_default,
    },
    "StringField": {
        "background_color": cl.background_field,
        "color": cl.text_value,
        "border_radius": fl.radius_small,
        "border_color": cl.border_default,
        "border_width": 1,
        "font_size": fl.font_size_value,
    },
    "StringField:hovered": {
        "border_color": cl.border_default,
    },
    "StringField:pressed": {
        "background_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    "StringField:focused": {
        "background_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    "StringField:disabled": {
        "background_color": cl.background_field,
        "color": cl.text_disabled,
        "border_color": cl.border_default,
    },
    "FloatField": {
        "background_color": cl.background_field,
        "color": cl.text_value,
        "border_radius": fl.radius_small,
        "border_color": cl.border_default,
        "border_width": 1,
        "font_size": fl.font_size_value,
    },
    "FloatField:hovered": {
        "border_color": cl.border_default,
    },
    "FloatField:pressed": {
        "background_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    "FloatField:focused": {
        "background_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    "FloatField:disabled": {
        "background_color": cl.background_field,
        "color": cl.text_disabled,
        "border_color": cl.border_default,
    },
    "IntField": {
        "background_color": cl.background_field,
        "color": cl.text_value,
        "border_radius": fl.radius_small,
        "border_color": cl.border_default,
        "border_width": 1,
        "font_size": fl.font_size_value,
    },
    "IntField:hovered": {
        "border_color": cl.border_default,
    },
    "IntField:pressed": {
        "background_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    "IntField:focused": {
        "background_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    "IntField:disabled": {
        "background_color": cl.background_field,
        "color": cl.text_disabled,
        "border_color": cl.border_default,
    },
    # -----------------------------------------------------------------------
    # FloatDrag / IntDrag
    # -----------------------------------------------------------------------
    "FloatDrag": {
        "background_color": cl.background_field,
        "color": cl.text_value,
        "secondary_color": cl.background_field,
        "border_radius": fl.radius_small,
        "border_color": cl.border_default,
        "border_width": 1,
        "font_size": fl.font_size_value,
    },
    "FloatDrag:hovered": {
        "border_color": cl.border_default,
    },
    "FloatDrag:pressed": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    "FloatDrag:focused": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    "IntDrag": {
        "background_color": cl.background_field,
        "color": cl.text_value,
        "secondary_color": cl.background_field,
        "border_radius": fl.radius_small,
        "border_color": cl.border_default,
        "border_width": 1,
        "font_size": fl.font_size_value,
    },
    "IntDrag:hovered": {
        "border_color": cl.border_default,
    },
    "IntDrag:pressed": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    "IntDrag:focused": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    # -----------------------------------------------------------------------
    # ComboBox
    # -----------------------------------------------------------------------
    "ComboBox": {
        "background_color": cl.background_field,
        "color": cl.text_value,
        "secondary_color": cl.background_field,
        "border_radius": fl.radius_small,
        "border_color": cl.border_default,
        "border_width": 1,
        "font_size": fl.font_size_value,
    },
    "ComboBox:hovered": {
        "border_color": cl.border_default,
        "secondary_color": cl.background_field,
    },
    "ComboBox:pressed": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    "ComboBox:focused": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    "ComboBox:disabled": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "color": cl.text_disabled,
        "border_color": cl.border_default,
    },
    # -----------------------------------------------------------------------
    # ScrollingFrame
    # -----------------------------------------------------------------------
    "ScrollingFrame": {
        "background_color": cl.scrollbar_track,
        "secondary_color": cl.scrollbar_thumb,
        "scrollbar_size": fl.scrollbar_width,
        "border_radius": fl.radius_small,
    },
    "ScrollingFrame:hovered": {
        "secondary_color": cl.scrollbar_thumb_hovered,
    },
    "ScrollingFrame:pressed": {
        "secondary_color": cl.scrollbar_thumb_hovered,
    },
    # -----------------------------------------------------------------------
    # Splitter
    # -----------------------------------------------------------------------
    "Splitter": {
        "background_color": cl.splitter_handle,
        "color": cl.splitter_handle,
        "border_width": fl.splitter_visual_width,
        "padding": fl.splitter_hit_target,
        "margin": 0,
    },
    "Splitter:hovered": {
        "background_color": cl.splitter_handle_hovered,
        "color": cl.splitter_handle_hovered,
    },
    # -----------------------------------------------------------------------
    # CollapsableFrame
    # -----------------------------------------------------------------------
    "CollapsableFrame": {
        "background_color": cl.background_primary,
        "secondary_color": cl.background_primary,
        "color": cl.transparent,
        "border_radius": fl.radius_none,
        "border_color": cl.transparent,
        "border_width": 0,
        "padding": 0,
        "margin_height": 0,
        "font_size": fl.font_size_medium,
    },
    "CollapsableFrame:hovered": {
        "secondary_color": cl.background_primary,
        "color": cl.transparent,
        "border_color": cl.transparent,
    },
    "CollapsableFrame:pressed": {
        "secondary_color": cl.background_primary,
        "color": cl.transparent,
        "border_color": cl.transparent,
    },
    # -----------------------------------------------------------------------
    # TreeView
    # -----------------------------------------------------------------------
    "TreeView": {
        "background_color": cl.background_secondary,
        "color": cl.text_primary,
        "font_size": fl.font_size_medium,
        "border_radius": fl.radius_small,
    },
    "TreeView:selected": {
        "background_color": cl.treeview_selection,
    },
    "TreeView.Item": {
        "color": cl.text_primary,
        "font_size": fl.font_size_medium,
    },
    "TreeView.Item:selected": {
        "color": cl.text_primary,
        "font_size": fl.font_size_medium,
    },
    "TreeView.Header": {
        "background_color": cl.background_tertiary,
        "color": cl.text_secondary,
        "font_size": fl.font_size_small,
    },
    # -----------------------------------------------------------------------
    # Menu
    # -----------------------------------------------------------------------
    "Menu.Window": {
        "background_color": cl.menu_background,
        "background_selected_color": cl.menu_selection,
        "border_color": cl.border_default,
        "border_width": 1,
        "border_radius": fl.radius_small,
    },
    "MenuBar.Menu": {
        "background_color": cl.menu_background,
        "background_selected_color": cl.menu_bar_selection,
        "border_color": cl.border_default,
        "border_width": 1,
        "border_radius": fl.radius_small,
    },
    "MainFrame": {
        "background_color": cl.dockspace_void,
        "margin_width": 0,
        "margin_height": 0,
    },
    "MainMenuBar": {
        "background_color": cl.background_primary,
        "background_selected_color": cl.menu_bar_selection,
        "border_color": cl.main_menu_underline,
        "color": cl.text_secondary,
        "font_size": fl.menu_item_font_size,
        "padding": 4,
    },
    "StatusBar": {
        "background_color": cl.dockspace_void,
        "padding": 0,
        "margin_width": 0,
        "margin_height": 0,
    },
    "Window": {
        "background_color": cl.background_primary,
        "color": cl.text_primary,
        "border_color": cl.border_default,
        "border_width": 1,
        "border_radius": fl.radius_none,
    },
    "MenuBar": {
        "background_color": cl.background_primary,
        "background_selected_color": cl.menu_bar_selection,
        "color": cl.text_secondary,
        "font_size": fl.menu_item_font_size,
        "padding": 0,
    },
    "MenuBar.Item": {
        "color": cl.text_secondary,
        "font_size": fl.menu_item_font_size,
        "padding": 0,
        "margin_width": 0,
        "margin_height": 0,
    },
    "MenuBar.Item:hovered": {
        "background_color": cl.menu_bar_selection,
        "color": cl.text_primary,
    },
    "MenuBar.ProductLabel": {
        "color": cl.text_secondary,
        "font_size": fl.menu_bar_product_font_size,
        "margin_width": 0,
        "margin_height": 0,
    },
    "MenuBar.Logo": {
        "color": cl.text_secondary,
        "margin_width": 0,
        "margin_height": 0,
    },
    "MenuBar.ProductSeparator": {
        "background_color": cl.transparent,
        "border_color": cl.transparent,
        "border_width": 0,
    },
    "Application.MenuUnderline": {
        "color": cl.splitter_handle,
        "border_width": fl.menu_underline_thickness,
    },
    "Menu.Item": {
        "color": cl.text_primary,
        "font_size": fl.menu_item_font_size,
        "padding": 8,
        "margin": 0,
        "margin_height": 3,
        "background_selected_color": cl.menu_selection,
    },
    "MenuItem": {
        "background_selected_color": cl.menu_selection,
    },
    "MenuItem:hovered": {
        "background_selected_color": cl.menu_selection,
    },
    "Menu.Item:hovered": {
        "background_color": cl.menu_selection,
        "background_selected_color": cl.menu_selection,
        "color": cl.text_primary,
    },
    "Menu.Item:disabled": {
        "color": cl.text_disabled,
    },
    "Menu.Item.CheckMark": {
        "image_url": get_icon_path("menu_checkmark"),
        "color": cl.text_primary,
        "margin_width": 4,
    },
    "Menu.Item.CheckMark:disabled": {
        "image_url": get_icon_path("menu_checkmark"),
        "color": cl.text_disabled,
    },
    "Menu.Item.Hotkey": {
        "color": cl.text_secondary,
        "font_size": fl.menu_item_font_size,
        "alignment": ui.Alignment.RIGHT_CENTER,
    },
    "Menu.Item.Hotkey:disabled": {
        "color": cl.text_disabled,
        "alignment": ui.Alignment.RIGHT_CENTER,
    },
    "Menu.Item.ExpandMark": {
        "image_url": _MENU_EXPAND_MARK_ICON,
        "color": cl.text_secondary,
        "margin_width": 5,
    },
    "Menu.Item.ExpandMark:disabled": {
        "image_url": _MENU_EXPAND_MARK_ICON,
        "color": cl.text_disabled,
        "margin_width": 5,
    },
    "Menu.ControlButton": {
        "background_color": cl.interactive_default,
        "color": cl.text_primary,
        "border_radius": fl.radius_small,
        "border_color": cl.border_default,
        "border_width": 1,
        "padding": 0,
        "margin": 0,
        "font_size": fl.menu_item_font_size,
    },
    "Menu.ControlButton:hovered": {
        "background_color": cl.interactive_hovered,
    },
    "Menu.ControlButton:pressed": {
        "background_color": cl.interactive_pressed,
    },
    "Menu.ControlButton:disabled": {
        "background_color": cl.interactive_disabled,
        "color": cl.button_disabled_text,
    },
    "Menu.ControlButton:checked": {
        "background_color": cl.accent_primary,
        "color": cl.text_on_accent,
    },
    "Menu.ControlButton.Label": {
        "color": cl.text_primary,
        "font_size": fl.menu_item_font_size,
        "alignment": ui.Alignment.CENTER,
    },
    "Menu.ControlButton.Label:disabled": {
        "color": cl.button_disabled_text,
        "alignment": ui.Alignment.CENTER,
    },
    "Menu.ControlButton.Label:checked": {
        "color": cl.text_on_accent,
        "alignment": ui.Alignment.CENTER,
    },
    "Menu.ControlComboBox": {
        "background_color": cl.background_field,
        "color": cl.text_value,
        "secondary_color": cl.background_field,
        "border_radius": fl.radius_small,
        "border_color": cl.border_default,
        "border_width": 1,
        "font_size": fl.font_size_value,
        "alignment": ui.Alignment.LEFT_CENTER,
    },
    "Menu.ControlComboBox:hovered": {
        "border_color": cl.border_default,
        "secondary_color": cl.background_field,
    },
    "Menu.ControlComboBox:pressed": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    "Menu.ControlComboBox:focused": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "border_color": cl.border_focused,
    },
    "Menu.ControlComboBox:disabled": {
        "background_color": cl.background_field,
        "secondary_color": cl.background_field,
        "color": cl.text_disabled,
        "border_color": cl.border_default,
        "alignment": ui.Alignment.LEFT_CENTER,
    },
    "Menu.Separator": {
        "background_color": cl.border_default,
        "color": cl.border_default,
    },
    # -----------------------------------------------------------------------
    # Tooltip
    # -----------------------------------------------------------------------
    "Tooltip": {
        "background_color": cl.background_elevated,
        "color": cl.text_primary,
        "border_color": cl.border_default,
        "border_width": 1,
        "border_radius": fl.radius_small,
        "padding": 4,
        "font_size": fl.font_size_small,
    },
    # -----------------------------------------------------------------------
    # Separator
    # -----------------------------------------------------------------------
    "Separator": {
        "background_color": cl.border_default,
        "color": cl.border_default,
    },
    # -----------------------------------------------------------------------
    # ProgressBar
    # -----------------------------------------------------------------------
    "ProgressBar": {
        "background_color": cl.background_field,
        "color": cl.accent_primary,
        "border_radius": fl.radius_small,
        "font_size": fl.font_size_small,
    },
    # -----------------------------------------------------------------------
    # Rectangle
    # -----------------------------------------------------------------------
    "Rectangle": {
        "background_color": cl.background_secondary,
        "border_radius": fl.radius_none,
    },
    # -----------------------------------------------------------------------
    # Dialog (modal windows)
    # -----------------------------------------------------------------------
    "Dialog": {
        "background_color": cl.background_elevated,
        "color": cl.text_primary,
        "border_color": cl.border_default,
        "border_width": 1,
        "border_radius": fl.radius_medium,
        "padding": 8,
        "font_size": fl.font_size_medium,
    },
    "Dialog.SectionTitle": {
        "color": cl.accent_secondary,
        "font_size": fl.font_size_large,
        "margin_height": 2,
    },
    # -----------------------------------------------------------------------
    # OvGear domain types
    # -----------------------------------------------------------------------
    "OvGear.StatusBar": {
        "background_color": cl.dockspace_void,
        "color": cl.text_secondary,
        "border_color": cl.splitter_handle,
        "border_width": 0,
        "padding": 2,
        "font_size": fl.font_size_small,
    },
    # -----------------------------------------------------------------------
    # Viewport HUD — corner overlays using the Step 18 label/value pattern.
    # -----------------------------------------------------------------------
    "Viewport.HUD": {
        "background_color": cl.transparent,
        "color": cl.text_secondary,
        "padding": 0,
        "margin": 0,
        "font_size": fl.font_size_small,
    },
    "Viewport.HUD.Label": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_small,
    },
    "Viewport.HUD.Value": {
        "color": cl.text_value,
        "font_size": fl.font_size_small,
    },
    "Viewport.HUD.Separator": {
        "color": cl.text_disabled,
        "font_size": fl.font_size_small,
    },
    "Viewport.Toolbar": {
        "background_color": cl.transparent,
        "color": cl.text_primary,
        "border_color": cl.transparent,
        "border_width": 0,
        "border_radius": fl.radius_none,
        "padding": 0,
        "margin": 0,
    },
    "Viewport.Toolbar.Button": {
        "background_color": cl.transparent,
        "color": cl.text_secondary,
        "border_color": cl.transparent,
        "border_width": 0,
        "border_radius": fl.radius_small,
        "padding": 0,
        "margin": 0,
        "font_size": fl.font_size_small,
    },
    "Viewport.Toolbar.Button:hovered": {
        "background_color": cl.hud_background,
        "border_color": cl.transparent,
        "color": cl.text_primary,
    },
    "Viewport.Toolbar.Button:pressed": {
        "background_color": cl.hud_background,
        "border_color": cl.border_default,
    },
    "Viewport.Toolbar.Button:checked": {
        "background_color": cl.hud_background,
        "border_color": cl.accent_primary,
        "border_width": 1,
        "color": cl.text_primary,
    },
    "Viewport.Toolbar.Button::active": {
        "background_color": cl.hud_background,
        "border_color": cl.accent_primary,
        "border_width": 1,
        "color": cl.text_primary,
    },
    "Viewport.Toolbar.Icon": {
        "color": cl.text_primary,
        "padding": 0,
        "margin": 0,
    },
    "ViewportWidget.HUD.FpsLabel": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_small,
    },
    "ViewportWidget.HUD.PrimLabel": {
        "color": cl.text_secondary,
        "font_size": fl.font_size_small,
    },
    "OvGear.StatusBar::error": {
        "background_color": cl.status_error,
        "color": cl.text_on_accent,
    },
    "OvGear.StatusBar::warning": {
        "background_color": cl.status_warning,
        "color": cl.text_on_accent,
    },
    "OvGear.StatusBar::success": {
        "background_color": cl.status_success,
        "color": cl.text_on_accent,
    },
}

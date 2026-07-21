# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Layout and sizing constants (OvGear design system, design-system style rules).

Themed values (radius, spacing) are registered via fl.shade() so they respond
to ui.set_shade() switching.  Fixed values use direct assignment.
"""

import omni.ui as ui  # noqa: F401 — ensures FloatStore is initialised
from omni.ui import constant as fl

from ovui_widgets.app.layout import MENU_BAR_HEIGHT

# ---------------------------------------------------------------------------
# Border radius (px)
#
# Reference (``ovui-design-reference/OvuiSampleApp.png``) uses a
# subtly-rounded language: tight ~3 px on input fields, ~5 px on content
# tiles. Slightly larger than the original 2/4/8 ladder, matching the
# sampled rounded squares in the reference content browser.
# ---------------------------------------------------------------------------
fl.shade(0.0, name="radius_none")
fl.shade(3.0, light=1.0, name="radius_small")
fl.shade(5.0, light=2.0, name="radius_medium")
fl.shade(8.0, light=4.0, name="radius_large")

# ---------------------------------------------------------------------------
# Spacing (px)
# ---------------------------------------------------------------------------
fl.shade(0.0, name="spacing_none")
fl.shade(4.0, light=2.0, name="spacing_small")
fl.shade(8.0, light=4.0, name="spacing_medium")
fl.shade(16.0, light=8.0, name="spacing_large")

# ---------------------------------------------------------------------------
# Font sizes — fixed across themes. The design-reference correction scales the
# previous ladder up by 25% and rounds to whole pixels.
# ---------------------------------------------------------------------------
BASE_FONT_SIZE = 18.0

fl.font_size_tiny = 10.0
fl.font_size_small = 16.0
fl.font_size_medium = BASE_FONT_SIZE
fl.font_size_value = 15.0
fl.font_size_large = 25.0
fl.font_size_xlarge = 30.0

# ---------------------------------------------------------------------------
# Component-specific — fixed values
# ---------------------------------------------------------------------------
fl.scrollbar_width = 6.0
fl.splitter_visual_width = 1.0
fl.splitter_hit_target = 5.0
fl.treeview_indent = 16.0
fl.treeview_row_height = 18.0
fl.property_label_width = 160.0
fl.property_row_height = 24.0
fl.manipulator_handle_size = 80.0
fl.menu_bar_height = float(MENU_BAR_HEIGHT)
fl.menu_item_font_size = 14.0
fl.menu_bar_product_font_size = 16.0
fl.menu_underline_thickness = 0.5
# ImGui interprets 0.0 as hover-only close buttons. Keep dock tabs geometric
# at rest while exposing the expected close affordance under the cursor
# without reserving a permanently visible icon.
fl.dock_tab_close_min_width = 0.0
fl.dock_tab_close_min_width_selected = 0.0
fl.dock_tab_close_min_width_unselected = 0.0
fl.dock_tab_height = 24.0
fl.dock_tab_overline_size = 0.0
fl.dock_tab_rounding = 0.0
fl.dock_tab_border_size = 0.0
fl.dock_tab_bar_border_size = 0.0
fl.dock_tab_inactive_separator_inset = 2.0
fl.hud_font_size = 10.0
fl.hud_padding = 6.0

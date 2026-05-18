# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovwidgets.property.parts — building blocks for attribute-row composition.

Introduced in Step 4.3 of the property inspector implementation (property control-state behavior,
the property inspector behavior). This package collects the small,
self-contained widget classes and data structures that attach to an
attribute row or to the group tree but do not themselves own the label
/ value columns — starting with the right-side
:class:`ControlStateIndicator` and its :class:`ControlStateManager`
singleton, and the :class:`UiDisplayGroup` tree
that drives nested-group rendering. Step 5.3 adds
:mod:`group_context_menu` — the Copy/Paste/Reset-All driver for
right-click on a group header. Step 7.1 adds
:class:`HighlightLabel` (highlight-label behavior / the property inspector behavior) — the search-match highlighting label that replaces the plain
``ui.Label`` in every attribute row's label slot. Step 7.2 adds
:mod:`attr_context_menu` — the Copy Value / Paste Value / Reset to
Default / Copy Attribute Path driver for right-click on an individual
attribute row.
"""

from ovwidgets.property.parts.attr_context_menu import (
    DEFAULT_CLIPBOARD_ID as ATTR_CLIPBOARD_ID,
)
from ovwidgets.property.parts.attr_context_menu import (
    PATH_CLIPBOARD_ID,
    compose_attribute_path,
    copy_attribute_path,
    copy_value,
    paste_value,
    reset_value,
    show_attr_context_menu,
)
from ovwidgets.property.parts.attr_context_menu import can_paste as attr_can_paste
from ovwidgets.property.parts.attr_context_menu import can_reset as attr_can_reset
from ovwidgets.property.parts.attr_context_menu import (
    clear_clipboard as clear_attr_clipboard,
)
from ovwidgets.property.parts.attr_context_menu import (
    get_clipboard as get_attr_clipboard,
)
from ovwidgets.property.parts.control_state import (
    ControlStateHandler,
    ControlStateIndicator,
    ControlStateManager,
)
from ovwidgets.property.parts.display_group import UiDisplayGroup
from ovwidgets.property.parts.group_context_menu import (
    DEFAULT_CLIPBOARD_ID,
    can_paste,
    can_reset,
    clear_clipboard,
    copy_group,
    get_clipboard,
    iter_group_props,
    paste_group,
    reset_group,
    show_group_context_menu,
)
from ovwidgets.property.parts.highlight_label import HighlightLabel

__all__ = [
    "ControlStateHandler",
    "ControlStateIndicator",
    "ControlStateManager",
    "HighlightLabel",
    "UiDisplayGroup",
    "DEFAULT_CLIPBOARD_ID",
    "can_paste",
    "can_reset",
    "clear_clipboard",
    "copy_group",
    "get_clipboard",
    "iter_group_props",
    "paste_group",
    "reset_group",
    "show_group_context_menu",
    "ATTR_CLIPBOARD_ID",
    "PATH_CLIPBOARD_ID",
    "attr_can_paste",
    "attr_can_reset",
    "clear_attr_clipboard",
    "compose_attribute_path",
    "copy_attribute_path",
    "copy_value",
    "get_attr_clipboard",
    "paste_value",
    "reset_value",
    "show_attr_context_menu",
]

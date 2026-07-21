# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Collapsible attribute group header for the Property Inspector (property inspector implementation, §22.2).

Step 0.3 (Phase 0 — Structural alignment): this widget now wraps
``ui.CollapsableFrame`` with ``style_type_name_override="Property.GroupFrame"``
so the ``Property.GroupFrame:hovered`` and ``:pressed`` states from PROPERTY_STYLES
are exercised while omni.ui's built-in collapse state logic is used.

Step 5.3 (the property inspector implementation, group context-menu behavior): the widget now optionally
subscribes to ``set_mouse_released_fn`` on the underlying
``CollapsableFrame``. When an ``on_context_menu`` callable is passed
in, a right-click (button == 1) fires it with the event
``(x, y)``. The callback is expected to build and show a ``ui.Menu``
at that position; see :mod:`ovui_widgets.property.parts.group_context_menu` for
the Copy / Paste / Reset All driver the ``PropertyWindow`` passes in.

Step 8.2: the widget now optionally accepts
a ``level`` kwarg (0 for top-level frames, ≥ 1 for nested frames). When
``level >= 1`` the underlying ``CollapsableFrame`` is stamped with
``name = "inner"`` so omni.ui's style resolver picks up the
``Property.GroupFrame::inner`` selector family — the nested variant
paints its title in ``cl.text_secondary`` so the visual hierarchy
subordinates nested headers without touching the header strip colour.

Step 13 replaces the drawn header with a compact Property-specific builder:
mixed-case title text, smaller muted chevrons, and a tight divider-height row.

The public API (``initially_collapsed``, ``on_collapse_change``,
``is_collapsed``, ``content``, ``toggle()``, ``set_collapsed()``) stays
unchanged so existing callers in ``window.py`` do not move.
``on_context_menu`` and ``level`` are additive optional keywords.
"""

import importlib.resources
from typing import Callable, Optional

import omni.ui as ui

from ovui_widgets.common.icon_caches import provider

_ICON_DIR = str(importlib.resources.files("ovui_widgets.common").joinpath("icons"))
_CHEVRON_RIGHT = f"{_ICON_DIR}/chevron_right.png"
_CHEVRON_DOWN = f"{_ICON_DIR}/chevron_down.png"
_HEADER_HEIGHT = 18
_HEADER_LEFT_PADDING = 0
_CHEVRON_BOX_WIDTH = 12
_CHEVRON_SIZE = 12
_CHEVRON_LABEL_GAP = 2
FIT_CONTENT_HEIGHT = 0
GROUP_CONTENT_SPACING = 5
GROUP_HEADER_CONTENT_SPACING = 4
# Reference-measured spacing between top-level Property collapsible frames.
# Keep this separate from GROUP_CONTENT_SPACING so row density inside a
# section does not change when section rhythm is adjusted.
GROUP_STACK_SPACING = 34


def format_property_group_header_title(title: str) -> str:
    """Return the compact display form for Property group headers."""
    return title


def build_property_group_header(collapsed: bool, title: str) -> None:
    """Build the compact Step 13 Property group header."""
    icon_path = _CHEVRON_RIGHT if collapsed else _CHEVRON_DOWN
    with ui.HStack(
        height=_HEADER_HEIGHT,
        style_type_name_override="Property.GroupFrame.Header",
    ):
        ui.Spacer(width=_HEADER_LEFT_PADDING)
        with ui.VStack(width=_CHEVRON_BOX_WIDTH, height=_HEADER_HEIGHT):
            ui.Spacer()
            ui.ImageWithProvider(
                provider(icon_path),
                width=_CHEVRON_SIZE,
                height=_CHEVRON_SIZE,
                style_type_name_override="Property.GroupFrame.Chevron",
            )
            ui.Spacer()
        ui.Spacer(width=_CHEVRON_LABEL_GAP)
        ui.Label(
            format_property_group_header_title(title),
            style_type_name_override="Property.GroupFrame.Header",
            alignment=ui.Alignment.LEFT_CENTER,
        )
        ui.Spacer()


class AttributeGroupWidget:
    """Collapsible section header wrapping ``ui.CollapsableFrame``."""

    def __init__(
        self,
        name: str,
        initially_collapsed: bool = False,
        on_collapse_change: Optional[Callable[[bool], None]] = None,
        on_context_menu: Optional[Callable[[float, float], None]] = None,
        level: int = 0,
    ) -> None:
        self._name = name
        self._on_collapse_change = on_collapse_change
        self._on_context_menu = on_context_menu
        self._level = level
        self._frame: Optional[ui.CollapsableFrame] = None
        self._content: Optional[ui.VStack] = None
        self._build_ui(initially_collapsed)

    def _build_ui(self, initially_collapsed: bool) -> None:
        self._frame = ui.CollapsableFrame(
            title=self._name,
            collapsed=initially_collapsed,
            height=FIT_CONTENT_HEIGHT,
            style_type_name_override="Property.GroupFrame",
            build_header_fn=build_property_group_header,
        )
        # Step 8.2 — nested frames (level >= 1) activate the
        # ``Property.GroupFrame::inner`` selector family by stamping
        # ``name = "inner"`` on the frame. Top-level frames leave the
        # name empty so the base selectors apply unchanged.
        if self._level >= 1:
            self._frame.name = "inner"
        with self._frame:
            with ui.VStack(spacing=0, height=FIT_CONTENT_HEIGHT):
                ui.Spacer(height=GROUP_HEADER_CONTENT_SPACING)
                self._content = ui.VStack(
                    spacing=GROUP_CONTENT_SPACING,
                    height=FIT_CONTENT_HEIGHT,
                )
        self._frame.set_collapsed_changed_fn(self._on_frame_collapsed_changed)
        if self._on_context_menu is not None:
            self._frame.set_mouse_released_fn(self._on_mouse_released)

    def _on_frame_collapsed_changed(self, collapsed: bool) -> None:
        if self._on_collapse_change is not None:
            self._on_collapse_change(collapsed)

    def _on_mouse_released(
        self, x: float, y: float, button: int, modifier: int
    ) -> None:
        """Route right-clicks (``button == 1``) to the context-menu callback.

        omni.ui's button encoding matches the X11 / GLFW convention:
        0 = left, 1 = right, 2 = middle. Any other button is ignored.
        The click position is forwarded verbatim so the callback can
        call ``ui.Menu.show_at(x, y)`` and pop the menu where the user
        clicked — matching the Kit header-context-menu behaviour.
        """
        if button != 1:
            return
        if self._on_context_menu is None:
            return
        self._on_context_menu(x, y)

    @property
    def is_collapsed(self) -> bool:
        if self._frame is None:
            return False
        return self._frame.collapsed

    @property
    def content(self) -> Optional[ui.VStack]:
        return self._content

    def toggle(self) -> None:
        self.set_collapsed(not self.is_collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        if self._frame is None:
            return
        if self._frame.collapsed == collapsed:
            return
        self._frame.collapsed = collapsed

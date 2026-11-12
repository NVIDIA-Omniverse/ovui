# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Standard ovui widgets get a visible default look from the global style.

An app that calls ``apply_global_styles()`` and builds UI from standard
widgets with their default options must get:

- a visible title and arrow on the default header of a ``CollapsableFrame``,
  in each state of the header, and a vertical margin between sections;
- a frame (the field background and a border) on each slider and drag.

ovui draws the default header of a ``CollapsableFrame`` with the style type
of the frame class, and it gives each slider and drag the style type
``"Slider"``. The tests take these style types from real widgets, so a style
key that no default widget uses cannot make them pass.
"""

from __future__ import annotations

import omni.ui as ui
import pytest
from ovui_widgets.app.style import set_theme

_THEMES = ("dark", "light")

_SLIDER_AND_DRAG_TYPES = (
    ui.FloatSlider,
    ui.IntSlider,
    ui.UIntSlider,
    ui.FloatDrag,
    ui.IntDrag,
    ui.UIntDrag,
)


@pytest.fixture(params=_THEMES)
def theme(request):
    """Apply the global style of one theme; restore dark afterwards."""
    set_theme(request.param)
    yield request.param
    set_theme("dark")


def _alpha(color: int) -> int:
    return (color >> 24) & 0xFF


def _style_type(widget) -> str:
    return widget.style_type_name_override or type(widget).__name__


@pytest.mark.parametrize("state", ["", ":hovered", ":pressed"])
def test_default_collapsable_frame_header_is_visible(theme, state):
    frame = ui.CollapsableFrame("Section")
    style_type = _style_type(frame)
    base = ui.style.default[style_type]
    entry = {**base, **ui.style.default.get(style_type + state, {})}

    title_color = entry["color"]
    header_color = entry["secondary_color"]
    assert _alpha(title_color) == 0xFF, (
        f"{theme}: the default title and arrow of a {style_type} header "
        f"({state or 'normal'} state) are not opaque: {hex(title_color)}"
    )
    assert title_color != header_color, (
        f"{theme}: the default title of a {style_type} header has the colour "
        f"of the header background {hex(header_color)}"
    )
    assert entry["margin_height"] > 0, (
        f"{theme}: {style_type} has no vertical margin, so two sections touch"
    )


@pytest.mark.parametrize("widget_type", _SLIDER_AND_DRAG_TYPES, ids=lambda t: t.__name__)
def test_default_sliders_and_drags_have_a_frame(theme, widget_type):
    widget = widget_type()
    style_type = _style_type(widget)
    assert style_type in ui.style.default, (
        f"{theme}: the global style has no entry for {style_type!r}, the style "
        f"type of a default {widget_type.__name__}"
    )
    entry = ui.style.default[style_type]
    field = ui.style.default["Field"]
    window = ui.style.default["Window"]

    assert entry["background_color"] == field["background_color"], (
        f"{theme}: a default {widget_type.__name__} does not have the field background"
    )
    assert entry["border_width"] >= 1, (
        f"{theme}: a default {widget_type.__name__} has no border"
    )
    assert entry["border_color"] != window["background_color"], (
        f"{theme}: the border of a default {widget_type.__name__} has the window colour"
    )

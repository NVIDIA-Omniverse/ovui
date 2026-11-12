# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""F2 in a Property Inspector number field that edits starts no rename.

With ``/World/Cube`` selected, a double-click on the Size or Translate X field
puts the field in keyboard-edit mode. F2 then opened the Stage Browser rename
field, which took the focus: the typed "60" became the prim name, Enter
removed the Cube row, and Size stayed 40.

The field is put in keyboard-edit mode with an injected double-click, and F2,
the text and Enter are injected, the same input path as a user. ovui gives
the key to the handler that the application sets on the Property Inspector
window. F2 must not start a rename in the Stage Browser or in the Content
Browser, the field must keep the edit, and Enter must commit the typed value.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import omni.ui as ui
import pytest
from ovui_data_adapters.openusd import UsdPropertyAdapter, UsdStageAdapter
from pxr import Gf, Usd, UsdGeom

from ovui_widgets.common.undo import UndoManager
from ovui_widgets.property.attribute_row import FloatAttributeRow, Vec3FloatAttributeRow

_TRANSLATE = "xformOp:translate"
# ImGuiKey values, as injected by the ovui inspector.
_KEY_ENTER = 525
_KEY_F2 = 573


@pytest.fixture(scope="module")
def frames():
    """One headless ovui start for the module; ``frames()`` draws frames."""
    from omni.ui import standalone

    from tests._vulkan_device import use_headless_vulkan

    patch = pytest.MonkeyPatch()
    use_headless_vulkan(patch)
    # An earlier test can leave the backend running with its own windows.
    standalone.shutdown()
    standalone.init("_test_property_number_field_f2", 640, 120)

    def tick(count=3):
        for _ in range(count):
            standalone._tick_one_frame()

    yield tick
    standalone.shutdown()
    patch.undo()


@pytest.fixture()
def cube(tmp_path, frames):
    """A saved stage with /World/Cube, its Size and Translate rows in a window,
    and the application key handler of the Property Inspector on the window.

    The Stage Browser and the Content Browser record a rename request; no
    text input of theirs edits.
    """
    from ovui_widgets.app.application import Application

    from tests.test_keyboard_shortcuts import _make_app

    stage = Usd.Stage.CreateNew(str(tmp_path / "keys.usda"))
    prim = UsdGeom.Cube.Define(stage, "/World/Cube")
    prim.GetSizeAttr().Set(40.0)
    prim.AddTranslateOp().Set(Gf.Vec3d(-80.0, 20.0, 0.0))
    stage.Save()
    undo = UndoManager()
    stage_adapter = UsdStageAdapter(
        stage, undo_manager=undo, call_later=lambda _delay, _callback: None
    )
    adapter = UsdPropertyAdapter(
        stage, ["/World/Cube"], undo_manager=undo, stage_adapter=stage_adapter
    )
    window = ui.Window(
        "_test_property_number_field_f2", width=640, height=120,
        position_x=0, position_y=0, flags=ui.WINDOW_FLAGS_NO_TITLE_BAR,
    )
    with window.frame:
        with ui.VStack():
            size_row = FloatAttributeRow(adapter.get_attribute_metadata("size"), adapter)
            translate_row = Vec3FloatAttributeRow(
                adapter.get_attribute_metadata(_TRANSLATE), adapter
            )
    app = _make_app()
    app._stage_window = MagicMock()
    app._stage_window.is_filter_editing.return_value = False
    app._content_window = MagicMock()
    window.set_key_pressed_fn(app._on_property_key_pressed)
    frames()
    fields = {"size": size_row._widget, "translate_x": translate_row._widgets[0]}
    yield stage, app, fields
    window.destroy()
    Application._instance = None
    frames()


def _press(frames, key):
    from omni.ui import _ui

    _ui._inject_key_event(key, True)
    frames(1)
    _ui._inject_key_event(key, False)
    frames(2)


def _double_click(frames, widget):
    from omni.ui import _ui

    # Let the double-click time (0.30 s) of an earlier click pass.
    time.sleep(0.5)
    x = widget.screen_position_x + widget.computed_width / 2
    y = widget.screen_position_y + widget.computed_height / 2
    _ui._inject_mouse_move(float(x), float(y))
    frames(2)
    for _ in range(2):
        _ui._inject_mouse_button(0, True)
        frames(1)
        _ui._inject_mouse_button(0, False)
        frames(1)
    frames(2)


def _value(stage, field):
    prim = stage.GetPrimAtPath("/World/Cube")
    if field == "size":
        return prim.GetAttribute("size").Get()
    return prim.GetAttribute(_TRANSLATE).Get()[0]


@pytest.mark.parametrize("field, typed", [("size", "60"), ("translate_x", "7")])
def test_f2_in_an_editing_number_field_starts_no_rename(cube, frames, field, typed):
    from omni.ui import _ui, standalone

    stage, app, fields = cube
    _double_click(frames, fields[field])
    assert standalone.is_text_input_active(), "the field did not enter keyboard-edit mode"

    _press(frames, _KEY_F2)

    app._stage_window.begin_rename_selected.assert_not_called()
    app._content_window.begin_rename_selected.assert_not_called()
    assert standalone.is_text_input_active(), "F2 ended the edit of the field"

    _ui._inject_text_input(typed)
    frames(2)
    _press(frames, _KEY_ENTER)

    assert _value(stage, field) == float(typed)
    assert not standalone.is_text_input_active()

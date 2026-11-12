# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Ctrl+S while a Property Inspector field edits.

A number field writes each typed value to the stage as a preview, and Escape
puts the old value back. Ctrl+S in the Property Inspector must first end the
edit as a commit, as a mouse click on Layer > Save All does, and then save:
the file gets the typed value, the layer is shown as saved, and a later
Escape changes nothing. Before the fix, the save wrote the typed value while
the field still edited, and Escape then put the old value back in the stage
only: the file kept a value that the user had cancelled.

The fields are put in keyboard-edit mode with an injected double-click and
edited with injected text and keys, the same input path as a user. Ctrl+S
reaches the application through the window key callback that the USD Viewer
gives to the Property Inspector, and the save is the real Save All of the
Layers model, which writes the file.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import omni.ui as ui
import pytest
from ovui_data_adapters.common import LayerHandle
from ovui_data_adapters.openusd import UsdPropertyAdapter, UsdStageAdapter
from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter
from pxr import Gf, Sdf, Usd, UsdGeom

from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers.layer_model import LayerModel
from ovui_widgets.property.attribute_row import StringAttributeRow, Vec3FloatAttributeRow

_TRANSLATE = "xformOp:translate"
_LABEL = "userLabel"
_START = (-80.0, 20.0, 0.0)
# ImGuiKey values, as injected by the ovui inspector.
_KEY_ESCAPE = 526
_KEY_LEFT_CTRL = 527
_KEY_S = 546 + 18


@pytest.fixture(scope="module")
def frames():
    """One headless ovui start for the module; ``frames()`` draws frames."""
    from omni.ui import standalone

    from tests._vulkan_device import use_headless_vulkan

    patch = pytest.MonkeyPatch()
    use_headless_vulkan(patch)
    # An earlier test can leave the backend running with its own windows.
    standalone.shutdown()
    standalone.init("_test_property_save_during_field_edit", 640, 120)

    def tick(count=3):
        for _ in range(count):
            standalone._tick_one_frame()

    yield tick
    standalone.shutdown()
    patch.undo()


@pytest.fixture()
def cube(tmp_path, frames):
    """A saved stage with /World/Cube, its Translate and a string row in a
    window whose key callback is the Property Inspector key handler of the
    application."""
    from ovui_widgets.app.application import Application

    path = tmp_path / "keys.usda"
    stage = Usd.Stage.CreateNew(str(path))
    cube_prim = UsdGeom.Cube.Define(stage, "/World/Cube")
    cube_prim.AddTranslateOp().Set(Gf.Vec3d(*_START))
    cube_prim.GetPrim().CreateAttribute(_LABEL, Sdf.ValueTypeNames.String).Set("old")
    stage.Save()
    undo = UndoManager()
    stage_adapter = UsdStageAdapter(stage, undo_manager=undo)
    adapter = UsdPropertyAdapter(
        stage, ["/World/Cube"], undo_manager=undo, stage_adapter=stage_adapter
    )
    layers = UsdLayerStackAdapter(stage, undo)
    layers.attach_stage()

    # The parts of the application that its key handler and Save All use.
    previous = Application._instance
    app = Application.__new__(Application)
    app._undo_manager = undo
    app._viewport_window = None
    app._content_window = None
    app._stage_window = None
    app._property_window = None
    app._layer_adapter = layers
    app._layer_window = SimpleNamespace(_model=LayerModel(layers))
    app._pending_callbacks = []

    window = ui.Window(
        "_test_property_save_during_field_edit", width=640, height=120,
        position_x=0, position_y=0, flags=ui.WINDOW_FLAGS_NO_TITLE_BAR,
    )
    with window.frame:
        with ui.VStack(height=0):
            translate = Vec3FloatAttributeRow(adapter.get_attribute_metadata(_TRANSLATE), adapter)
            label = StringAttributeRow(adapter.get_attribute_metadata(_LABEL), adapter)
    window.set_key_pressed_fn(app._on_property_key_pressed)

    def run(count=3):
        # As the application loop: draw a frame, then run the callbacks that
        # were scheduled for later.
        for _ in range(count):
            frames(1)
            app._drain_scheduled_callbacks()

    run()
    yield SimpleNamespace(
        stage=stage, path=path, undo=undo, layers=layers,
        root=LayerHandle(stage.GetRootLayer().identifier),
        translate=translate, label=label, run=run,
    )
    window.destroy()
    app._layer_window._model.destroy()
    Application._instance = previous
    frames()


def _in_file(path, name):
    """The value of ``name`` of /World/Cube in the file on disk."""
    layer = Sdf.Layer.OpenAsAnonymous(str(path))
    return layer.GetAttributeAtPath(f"/World/Cube.{name}").default


def _in_stage(stage, name):
    return stage.GetPrimAtPath("/World/Cube").GetAttribute(name).Get()


def _press(run, key):
    from omni.ui import _ui

    _ui._inject_key_event(key, True)
    run(1)
    _ui._inject_key_event(key, False)
    run(2)


def _ctrl_s(run):
    from omni.ui import _ui

    _ui._inject_key_event(_KEY_LEFT_CTRL, True)
    run(1)
    _press(run, _KEY_S)
    _ui._inject_key_event(_KEY_LEFT_CTRL, False)
    run(2)


def _type_in_field(run, widget, text):
    """Double-click ``widget`` into keyboard-edit mode and type ``text``."""
    from omni.ui import _ui, standalone

    # Let the double-click time (0.30 s) of an earlier click pass.
    time.sleep(0.5)
    x = widget.screen_position_x + widget.computed_width / 2
    y = widget.screen_position_y + widget.computed_height / 2
    _ui._inject_mouse_move(float(x), float(y))
    run(2)
    for _ in range(2):
        _ui._inject_mouse_button(0, True)
        run(1)
        _ui._inject_mouse_button(0, False)
        run(1)
    run(2)
    assert standalone.is_text_input_active(), "the field did not enter keyboard-edit mode"
    _ui._inject_text_input(text)
    run(2)


def test_ctrl_s_commits_the_number_field_edit_before_the_save(cube):
    from omni.ui import standalone

    run = cube.run
    _type_in_field(run, cube.translate._widgets[0], "55")
    # The object moves while the user types, and the layer is modified.
    assert tuple(_in_stage(cube.stage, _TRANSLATE)) == (55.0, 20.0, 0.0)
    assert cube.layers.is_dirty(cube.root)
    assert tuple(_in_file(cube.path, _TRANSLATE)) == _START

    _ctrl_s(run)

    # The edit ended as a commit, and the save wrote the committed value.
    assert not standalone.is_text_input_active(), "the field still edits after Ctrl+S"
    assert tuple(_in_file(cube.path, _TRANSLATE)) == (55.0, 20.0, 0.0)
    assert not cube.layers.is_dirty(cube.root)
    assert cube.undo.can_undo()

    _press(run, _KEY_ESCAPE)

    # Escape changes nothing: the stage, the field and the file keep 55, and
    # the layer stays saved.
    assert tuple(_in_stage(cube.stage, _TRANSLATE)) == (55.0, 20.0, 0.0)
    assert cube.translate._widgets[0].model.get_value_as_float() == 55.0
    assert tuple(_in_file(cube.path, _TRANSLATE)) == (55.0, 20.0, 0.0)
    assert not cube.layers.is_dirty(cube.root)

    # The commit is one undo step: Undo puts back the old value.
    assert cube.undo.undo()
    assert tuple(_in_stage(cube.stage, _TRANSLATE)) == _START


def test_ctrl_s_saves_a_text_field_value_that_is_written_only_at_the_end_of_the_edit(cube):
    run = cube.run
    _type_in_field(run, cube.label._widget, "new")
    # A text field writes its value only when its edit ends.
    assert _in_stage(cube.stage, _LABEL) == "old"

    _ctrl_s(run)

    # The save ran after the field had written its value.
    assert _in_stage(cube.stage, _LABEL) == "new"
    assert _in_file(cube.path, _LABEL) == "new"
    assert not cube.layers.is_dirty(cube.root)

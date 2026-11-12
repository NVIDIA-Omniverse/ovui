# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Escape in a Property Inspector number field cancels the edit.

The Translate Z field is put in keyboard-edit mode with an injected
double-click and edited with injected text and keys, the same input path as
a user. The stored value has more digits than the field shows, as in the
Factory scene of the issue. Escape must put back the exact stored value,
leave the undo and redo history as it was, and show a saved layer as not
modified (Save All off) without a reload, which rebuilds the whole stage.
Enter must still commit the typed value as one undo step.
"""

from __future__ import annotations

import time

import omni.ui as ui
import pytest
from ovui_data_adapters.common import ChangeEventType, LayerHandle
from ovui_data_adapters.openusd import UsdPropertyAdapter, UsdStageAdapter
from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter
from pxr import Gf, Sdf, Tf, Usd, UsdGeom

from ovui_widgets.common.undo import UndoManager
from ovui_widgets.property.attribute_row import (
    FloatAttributeRow,
    MatrixAttributeRow,
    Vec3FloatAttributeRow,
)

_TRANSLATE = "xformOp:translate"
# The field shows 0.3500; the stored value has more digits.
_START = (-932.1000138893723, -1500.2240890559156, 0.3500151634072495)
# ImGuiKey values, as injected by the ovui inspector.
_KEY_ENTER = 525
_KEY_ESCAPE = 526


@pytest.fixture(scope="module")
def frames():
    """One headless ovui start for the module; ``frames()`` draws frames."""
    from omni.ui import standalone

    from tests._vulkan_device import use_headless_vulkan

    patch = pytest.MonkeyPatch()
    use_headless_vulkan(patch)
    # An earlier test can leave the backend running with its own windows.
    standalone.shutdown()
    standalone.init("_test_property_number_field_escape", 640, 120)

    def tick(count=3):
        for _ in range(count):
            standalone._tick_one_frame()

    yield tick
    standalone.shutdown()
    patch.undo()


@pytest.fixture()
def ramp(tmp_path, frames):
    """A saved stage with /Ramp and its Translate row in a window.

    The adapters are connected as in the application, where the stage
    adapter tells its listeners (stage tree, renderer) of a change on a later
    frame: ``flush()`` does that step, and ``events`` records what it tells.
    """
    # A binary .usd file, as Factory.usd: its reload rebuilds the whole stage.
    stage = Usd.Stage.CreateNew(str(tmp_path / "ramp.usd"))
    UsdGeom.Xform.Define(stage, "/Ramp").AddTranslateOp().Set(Gf.Vec3d(*_START))
    stage.Save()
    undo = UndoManager()
    later = []
    stage_adapter = UsdStageAdapter(
        stage, undo_manager=undo, call_later=lambda _delay, callback: later.append(callback)
    )

    def flush():
        while later:
            later.pop(0)()

    events = []
    subscription = stage_adapter.subscribe_changes(events.append)
    adapter = UsdPropertyAdapter(
        stage, ["/Ramp"], undo_manager=undo, stage_adapter=stage_adapter
    )
    window = ui.Window(
        "_test_property_number_field_escape", width=640, height=120,
        position_x=0, position_y=0, flags=ui.WINDOW_FLAGS_NO_TITLE_BAR,
    )
    with window.frame:
        row = Vec3FloatAttributeRow(adapter.get_attribute_metadata(_TRANSLATE), adapter)
    flush()
    frames()
    yield stage, undo, adapter, row, events, flush
    window.destroy()
    subscription.cancel()
    frames()


def _translate(stage):
    return tuple(stage.GetPrimAtPath("/Ramp").GetAttribute(_TRANSLATE).Get())


def _layers(stage, undo):
    """The Layers window's adapter: its modified state drives Save All and
    the modified dot of each layer."""
    layers = UsdLayerStackAdapter(stage, undo)
    layers.attach_stage()
    return layers, LayerHandle(stage.GetRootLayer().identifier)


def _press(frames, key):
    from omni.ui import _ui

    _ui._inject_key_event(key, True)
    frames(1)
    _ui._inject_key_event(key, False)
    frames(2)


def _type_in_field(frames, widget, text):
    """Double-click ``widget`` into keyboard-edit mode and type ``text``."""
    from omni.ui import _ui, standalone

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
    assert standalone.is_text_input_active(), "the field did not enter keyboard-edit mode"
    _ui._inject_text_input(text)
    frames(2)


def test_escape_keeps_the_exact_value_and_the_redo_step(ramp, frames):
    stage, undo, adapter, row, _events, flush = ramp
    # An undone edit: Redo is available, as after Edit > Undo in the issue.
    adapter.begin_edit("visibility")
    adapter.set_value("visibility", "invisible")
    adapter.end_edit("visibility")
    assert undo.undo()
    assert not undo.can_undo() and undo.can_redo()

    _type_in_field(frames, row._widgets[2], "50")
    assert _translate(stage)[2] == 50.0  # the object moves while typing
    _press(frames, _KEY_ESCAPE)

    assert _translate(stage) == _START
    # The field shows the exact old value at once, not the rounded text.
    assert row._widgets[2].model.get_value_as_float() == _START[2]
    flush()
    assert row._widgets[2].model.get_value_as_float() == _START[2]
    assert not undo.can_undo()
    assert undo.can_redo()
    assert undo.redo()
    assert stage.GetPrimAtPath("/Ramp").GetAttribute("visibility").Get() == "invisible"


def test_escape_leaves_a_saved_layer_unmodified(ramp, frames):
    stage, undo, _adapter, row, events, flush = ramp
    layers, root = _layers(stage, undo)
    resynced = []
    key = Tf.Notice.Register(
        Usd.Notice.ObjectsChanged,
        lambda notice, _sender: resynced.extend(notice.GetResyncedPaths()),
        stage,
    )
    try:
        assert not layers.is_dirty(root)

        _type_in_field(frames, row._widgets[2], "50")
        assert layers.is_dirty(root)  # the typed value is written live
        flush()
        events.clear()
        _press(frames, _KEY_ESCAPE)
        flush()

        assert _translate(stage) == _START
        assert not undo.can_undo()
        # Save All and the modified dot of the layer are off.
        assert not layers.is_dirty(root)
        # The listeners get the restored value, and the stage is not
        # rebuilt: a reload of the layer resyncs the whole stage, which
        # stopped the application for seconds in a large scene.
        assert any("/Ramp.xformOp:translate" in event.changed_paths for event in events)
        assert not [event for event in events if event.event_type == ChangeEventType.RESYNC]
        assert resynced == []
    finally:
        key.Revoke()
        layers.detach_stage()


def test_enter_commits_the_typed_value_as_one_undo_step(ramp, frames):
    stage, undo, _adapter, row, _events, _flush = ramp

    _type_in_field(frames, row._widgets[2], "50")
    _press(frames, _KEY_ENTER)

    assert _translate(stage)[2] == 50.0
    assert undo.can_undo()
    assert undo.undo()
    assert _translate(stage) == _START
    assert not undo.can_undo()


def _scalar_row(adapter):
    row = FloatAttributeRow(adapter.get_attribute_metadata("size"), adapter)
    return row, row._widget


def _matrix_row(adapter):
    row = MatrixAttributeRow(adapter.get_attribute_metadata("frame"), adapter, n_dim=2)
    return row, row._widgets[3]


@pytest.mark.parametrize(
    ("attr_name", "type_name", "start", "make_row"),
    [
        ("size", Sdf.ValueTypeNames.Double, 0.3500151634072495, _scalar_row),
        (
            "frame", Sdf.ValueTypeNames.Matrix2d,
            Gf.Matrix2d(1.0, 0.0, 0.0, 0.3500151634072495), _matrix_row,
        ),
    ],
    ids=["scalar", "matrix"],
)
def test_escape_in_scalar_and_matrix_rows_keeps_the_exact_value(
    tmp_path, frames, attr_name, type_name, start, make_row
):
    stage = Usd.Stage.CreateNew(str(tmp_path / "rows.usd"))
    prim = UsdGeom.Xform.Define(stage, "/Ramp").GetPrim()
    prim.CreateAttribute(attr_name, type_name).Set(start)
    stage.Save()
    undo = UndoManager()
    adapter = UsdPropertyAdapter(stage, ["/Ramp"], undo_manager=undo)
    layers, root = _layers(stage, undo)
    window = ui.Window(
        "_test_property_number_field_escape_rows", width=640, height=120,
        position_x=0, position_y=0, flags=ui.WINDOW_FLAGS_NO_TITLE_BAR,
    )
    try:
        with window.frame:
            _row, field = make_row(adapter)
        frames()

        _type_in_field(frames, field, "50")
        assert prim.GetAttribute(attr_name).Get() != start  # written while typing
        _press(frames, _KEY_ESCAPE)

        assert prim.GetAttribute(attr_name).Get() == start
        assert not undo.can_undo()
        assert not layers.is_dirty(root)
    finally:
        window.destroy()
        layers.detach_stage()
        frames()

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Typed values that the Property Inspector must not store.

A user typed nan or inf in Translate X, or 1e308 in Rotate XYZ Y (a 32-bit
float attribute). The value was stored, the object vanished, Save All wrote
nan to the file, and no message showed. The field must refuse such a value,
keep the old value, and show a message that names the field and the cause.

The rows are driven through their drag field models, as the user's typing
does, with the OpenUSD adapter on a real stage.
"""

import math

import omni.ui as ui
import pytest
from pxr import Gf, Sdf, Usd, UsdGeom

from ovui_data_adapters.common import LayerHandle
from ovui_data_adapters.openusd import UsdPropertyAdapter
from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter

from ovui_widgets.common.error_reporter import ErrorReporter
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.property.attribute_row import (
    FloatAttributeRow,
    MatrixAttributeRow,
    Vec3FloatAttributeRow,
    Vec4FloatAttributeRow,
)

_BOX = "/World/BoxA"
_TRANSLATE = "xformOp:translate"
_ROTATE = "xformOp:rotateXYZ"


class _StatusBar:
    """The last warning that the status bar shows."""

    def __init__(self) -> None:
        self.text = ""

    def show_warning(self, message: str, *_args, **_kwargs) -> None:
        self.text = message


@pytest.fixture()
def status(monkeypatch):
    bar = _StatusBar()
    monkeypatch.setattr(ErrorReporter, "show_warning", bar.show_warning)
    return bar


def _box_stage(tmp_path, *paths):
    """A saved stage with the cube of the issue at each path."""
    stage = Usd.Stage.CreateNew(str(tmp_path / "numlab.usda"))
    for index, path in enumerate(paths or (_BOX,)):
        cube = UsdGeom.Cube.Define(stage, path)
        cube.AddTranslateOp().Set(Gf.Vec3d(-200.0 + 500.0 * index, 50.0, 0.0))
        cube.AddRotateXYZOp().Set(Gf.Vec3f(0.0, 0.0, 0.0))
    stage.Save()
    return stage


def _row(adapter, attr_name, row_class=Vec3FloatAttributeRow, **kwargs):
    window = ui.Window(f"test_739_{attr_name}", width=400, height=120)
    with window.frame:
        row = row_class(adapter.get_attribute_metadata(attr_name), adapter, **kwargs)
    return row, window


def _type(row, index, *values):
    """Type in one field as its drag field does: begin, each value, end.

    Return the value that the field shows after the edit.
    """
    model = row._widget.model if index is None else row._widgets[index].model
    row._on_begin_edit(model)
    for value in values:
        model.set_value(value)
    row._on_end_edit(model)
    return model.get_value_as_float()


def _value(stage, path, attr_name):
    value = stage.GetPrimAtPath(path).GetAttribute(attr_name).Get()
    return tuple(value) if hasattr(value, "__len__") else value


@pytest.mark.parametrize("typed", [math.nan, math.inf, -math.inf])
def test_non_finite_translate_is_refused_with_a_message(tmp_path, status, typed):
    stage = _box_stage(tmp_path)
    undo = UndoManager()
    adapter = UsdPropertyAdapter(stage, [_BOX], undo_manager=undo)
    row, _window = _row(adapter, _TRANSLATE)

    shown = _type(row, 0, typed)

    assert _value(stage, _BOX, _TRANSLATE) == (-200.0, 50.0, 0.0)
    assert shown == -200.0
    assert not undo.can_undo()
    assert not stage.GetRootLayer().dirty  # Save All has nothing to write
    assert status.text.startswith("Translate X: ")
    assert "must be a finite number" in status.text


@pytest.mark.parametrize(
    "typed", [(1e308,), (1.0, 1000.0, 1e30, 1e308)], ids=["at_once", "key_by_key"]
)
def test_value_outside_the_float_range_is_refused_not_stored_as_inf(
    tmp_path, status, typed
):
    # Key by key, the field writes 1, 1000 and 1e30 before 1e308 is refused:
    # the value from before the edit must come back.
    stage = _box_stage(tmp_path)
    undo = UndoManager()
    layers = UsdLayerStackAdapter(stage, undo)
    layers.attach_stage()
    adapter = UsdPropertyAdapter(stage, [_BOX], undo_manager=undo)
    row, _window = _row(adapter, _ROTATE)

    shown = _type(row, 1, *typed)

    assert _value(stage, _BOX, _ROTATE) == (0.0, 0.0, 0.0)
    assert shown == 0.0
    assert not undo.can_undo()
    # Save All and the modified dot read this state.
    assert not layers.is_dirty(LayerHandle(stage.GetRootLayer().identifier))
    layers.detach_stage()
    assert status.text.startswith("Rotate XYZ Y: 1e+308 ")
    assert "32-bit float" in status.text


def test_value_typed_after_a_refusal_is_stored_with_one_undo_step(tmp_path, status):
    # The user corrects the text after the message: 1e30 is written, 1e308
    # is refused, then 45 is typed and Enter is pressed.
    stage = _box_stage(tmp_path)
    undo = UndoManager()
    adapter = UsdPropertyAdapter(stage, [_BOX], undo_manager=undo)
    row, _window = _row(adapter, _ROTATE)

    shown = _type(row, 1, 1e30, 1e308, 45.0)

    assert _value(stage, _BOX, _ROTATE) == (0.0, 45.0, 0.0)
    assert shown == 45.0
    assert undo.undo()
    assert _value(stage, _BOX, _ROTATE) == (0.0, 0.0, 0.0)
    assert not undo.can_undo()


def test_refusal_gives_each_selected_prim_its_own_start_value(tmp_path, status):
    # Translate X differs on the two cubes ("Mixed"); 5 is written to both
    # before inf is refused.
    second = "/World/BoxB"
    stage = _box_stage(tmp_path, _BOX, second)
    undo = UndoManager()
    adapter = UsdPropertyAdapter(stage, [_BOX, second], undo_manager=undo)
    row, _window = _row(adapter, _TRANSLATE)

    _type(row, 0, 5.0, math.inf)

    assert _value(stage, _BOX, _TRANSLATE) == (-200.0, 50.0, 0.0)
    assert _value(stage, second, _TRANSLATE) == (300.0, 50.0, 0.0)
    assert not undo.can_undo()
    assert status.text.startswith("Translate X: inf ")


@pytest.mark.parametrize("typed", [1e39, 0.1])
def test_double_translate_stores_the_typed_value(tmp_path, status, typed):
    # 1e39 is above the 32-bit float range: a double must not become inf.
    stage = _box_stage(tmp_path)
    undo = UndoManager()
    adapter = UsdPropertyAdapter(stage, [_BOX], undo_manager=undo)
    row, _window = _row(adapter, _TRANSLATE)

    _type(row, 0, typed)

    assert _value(stage, _BOX, _TRANSLATE) == (typed, 50.0, 0.0)
    assert status.text == ""
    undo.undo()
    assert _value(stage, _BOX, _TRANSLATE) == (-200.0, 50.0, 0.0)


def test_non_finite_matrix_cell_of_a_transform_is_refused(tmp_path, status):
    stage = Usd.Stage.CreateNew(str(tmp_path / "matrix.usda"))
    UsdGeom.Xform.Define(stage, _BOX).AddTransformOp().Set(Gf.Matrix4d(1.0))
    stage.Save()
    adapter = UsdPropertyAdapter(stage, [_BOX], undo_manager=UndoManager())
    row, _window = _row(adapter, "xformOp:transform", MatrixAttributeRow, n_dim=4)

    shown = _type(row, 12, math.nan)

    assert _value(stage, _BOX, "xformOp:transform") == tuple(Gf.Matrix4d(1.0))
    assert shown == 0.0
    assert status.text.startswith("Transform row 4, column 1: nan ")


def test_non_finite_scalar_transform_op_is_refused(tmp_path, status):
    stage = Usd.Stage.CreateNew(str(tmp_path / "rotate_x.usda"))
    UsdGeom.Xform.Define(stage, _BOX).AddRotateXOp().Set(15.0)
    stage.Save()
    adapter = UsdPropertyAdapter(stage, [_BOX], undo_manager=UndoManager())
    row, _window = _row(adapter, "xformOp:rotateX", FloatAttributeRow)

    shown = _type(row, None, math.inf)

    assert _value(stage, _BOX, "xformOp:rotateX") == 15.0
    assert shown == 15.0
    assert status.text.startswith("Rotate X: inf ")


def test_typed_inf_is_kept_for_an_attribute_that_is_not_a_transform(tmp_path, status):
    # Outside transforms, inf can be a real value (for example a joint limit).
    stage = Usd.Stage.CreateNew(str(tmp_path / "limit.usda"))
    prim = UsdGeom.Xform.Define(stage, _BOX).GetPrim()
    prim.CreateAttribute("upperLimit", Sdf.ValueTypeNames.Float, custom=True).Set(90.0)
    adapter = UsdPropertyAdapter(stage, [_BOX], undo_manager=UndoManager())
    row, _window = _row(adapter, "upperLimit", FloatAttributeRow)

    _type(row, None, math.inf)

    assert _value(stage, _BOX, "upperLimit") == math.inf
    assert status.text == ""


def _mixed_precision_stage(tmp_path):
    """Two prims with an attribute of the same name: one half4, one float4."""
    stage = Usd.Stage.CreateNew(str(tmp_path / "mixed.usda"))
    for path, type_name, value in (
        (_HALF_PROBE, Sdf.ValueTypeNames.Half4, Gf.Vec4h(1.0, 2.0, 3.0, 4.0)),
        (_FLOAT_PROBE, Sdf.ValueTypeNames.Float4, Gf.Vec4f(1.0, 0.1234567, 1e10, 4.0)),
    ):
        prim = UsdGeom.Xform.Define(stage, path).GetPrim()
        prim.CreateAttribute("pair", type_name, custom=True).Set(value)
    return stage


_HALF_PROBE = "/World/HalfProbe"
_FLOAT_PROBE = "/World/FloatProbe"
_SELECTION_ORDERS = pytest.mark.parametrize(
    "paths",
    [(_HALF_PROBE, _FLOAT_PROBE), (_FLOAT_PROBE, _HALF_PROBE)],
    ids=["half_first", "float_first"],
)


@_SELECTION_ORDERS
def test_typed_channel_keeps_the_precision_of_each_selected_attribute(
    tmp_path, status, paths
):
    # The Property Inspector shows the type of the first selected prim. A
    # typed X must not write the other channels of the float4 with half
    # precision: 0.1234567 must stay, and 1e10 must not become inf.
    stage = _mixed_precision_stage(tmp_path)
    float_start = _value(stage, _FLOAT_PROBE, "pair")
    adapter = UsdPropertyAdapter(stage, list(paths), undo_manager=UndoManager())
    row, _window = _row(adapter, "pair", Vec4FloatAttributeRow)

    _type(row, 0, 7.0)

    assert _value(stage, _FLOAT_PROBE, "pair") == (7.0,) + float_start[1:]
    assert _value(stage, _HALF_PROBE, "pair") == (7.0, 2.0, 3.0, 4.0)
    assert status.text == ""


@_SELECTION_ORDERS
def test_whole_vector_keeps_the_precision_of_each_selected_attribute(tmp_path, paths):
    # Paste writes a whole vector to each selected prim (set_value). Each
    # attribute gets the value with its own precision.
    stage = _mixed_precision_stage(tmp_path)
    undo = UndoManager()
    adapter = UsdPropertyAdapter(stage, list(paths), undo_manager=undo)
    pasted = (9.0, 0.1234567, 3.0, 4.0)

    adapter.begin_edit("pair")
    adapter.set_value("pair", pasted)
    adapter.end_edit("pair")

    assert _value(stage, _FLOAT_PROBE, "pair") == tuple(Gf.Vec4f(*pasted))
    assert _value(stage, _HALF_PROBE, "pair") == tuple(Gf.Vec4h(*pasted))
    assert undo.undo()
    assert _value(stage, _FLOAT_PROBE, "pair") == tuple(Gf.Vec4f(1.0, 0.1234567, 1e10, 4.0))

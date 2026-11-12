# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One channel typed in a vector row for several prims keeps their other channels.

Regression: with a Sphere at Translate (0, 0, 0) and a Cube at (0, 50, 0)
selected, typing X = 100 gave the Cube the Y of the Sphere. Each prim must
keep its own values in the channels that the user did not type.
"""

import omni.ui as ui
import pytest
from ovui_data_adapters.common import AttributeMetadata, LayerHandle
from pxr import Gf, Sdf, Usd, UsdGeom

from ovui_data_adapters.openusd import UsdPropertyAdapter
from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter

from ovui_widgets.app.testing import MockPropertyAdapter
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.property.attribute_row import (
    Vec2FloatAttributeRow,
    Vec3FloatAttributeRow,
    Vec3IntAttributeRow,
)

_TRANSLATE = "xformOp:translate"


def _translate(stage, path):
    return tuple(stage.GetPrimAtPath(path).GetAttribute(_TRANSLATE).Get())


def _type_in_channel(row, index, *values):
    """Edit one channel field as its drag field does: begin, values, end."""
    model = row._widgets[index].model
    row._on_begin_edit(model)
    for value in values:
        model.set_value(value)
    row._on_end_edit(model)


def _sphere_and_cube_rows(window_name, stage=None):
    if stage is None:
        stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/Sphere").AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 0.0))
    UsdGeom.Xform.Define(stage, "/Cube").AddTranslateOp().Set(Gf.Vec3d(0.0, 50.0, 0.0))
    undo = UndoManager()
    adapter = UsdPropertyAdapter(stage, ["/Sphere", "/Cube"], undo_manager=undo)
    window = ui.Window(window_name, width=400, height=60)
    with window.frame:
        row = Vec3FloatAttributeRow(adapter.get_attribute_metadata(_TRANSLATE), adapter)
    return stage, undo, adapter, row, window


def _assert_saved_layer_unchanged(stage):
    """The root layer has the content of its file, and the Layers window
    (Save All, the modified dot) shows it as not modified."""
    layer = stage.GetRootLayer()
    on_disk = Sdf.Layer.OpenAsAnonymous(layer.realPath)
    assert layer.ExportToString() == on_disk.ExportToString()
    layers = UsdLayerStackAdapter(stage, UndoManager())
    assert not layers.is_dirty(LayerHandle(layer.identifier))


class TestUsdTranslateChannel:
    def test_typing_x_keeps_the_y_of_each_prim(self):
        stage, undo, adapter, row, _window = _sphere_and_cube_rows("test_539_type_x")
        assert adapter.get_per_component_ambiguity(_TRANSLATE) == [False, True, False]

        _type_in_channel(row, 0, 100.0)

        assert _translate(stage, "/Sphere") == (100.0, 0.0, 0.0)
        assert _translate(stage, "/Cube") == (100.0, 50.0, 0.0)
        assert adapter.get_per_component_ambiguity(_TRANSLATE) == [False, True, False]

        undo.undo()
        assert _translate(stage, "/Sphere") == (0.0, 0.0, 0.0)
        assert _translate(stage, "/Cube") == (0.0, 50.0, 0.0)
        assert not undo.can_undo()

    def test_typing_x_then_escape_leaves_the_saved_layer_unchanged(self, tmp_path):
        stage = Usd.Stage.CreateNew(str(tmp_path / "sphere_and_cube.usda"))
        stage, undo, _adapter, row, _window = _sphere_and_cube_rows(
            "test_539_escape", stage
        )
        stage.Save()

        # Escape writes the start value of the field back before the edit ends.
        _type_in_channel(row, 0, 100.0, 0.0)

        assert _translate(stage, "/Sphere") == (0.0, 0.0, 0.0)
        assert _translate(stage, "/Cube") == (0.0, 50.0, 0.0)
        assert not undo.can_undo()
        # Save All would show unsaved changes for a modified layer.
        _assert_saved_layer_unchanged(stage)

    def test_escape_leaves_no_value_where_none_was_authored(self, tmp_path):
        # CamA has an authored clipping range; CamB has none and shows
        # the fallback (1, 1000000). X is 1 on both, Y differs.
        stage = Usd.Stage.CreateNew(str(tmp_path / "cameras.usda"))
        UsdGeom.Camera.Define(stage, "/CamA").GetClippingRangeAttr().Set(Gf.Vec2f(1.0, 500.0))
        UsdGeom.Camera.Define(stage, "/CamB")
        stage.Save()
        undo = UndoManager()
        adapter = UsdPropertyAdapter(stage, ["/CamA", "/CamB"], undo_manager=undo)
        window = ui.Window("test_539_escape_unauthored", width=400, height=60)
        with window.frame:
            row = Vec2FloatAttributeRow(adapter.get_attribute_metadata("clippingRange"), adapter)
        cam_b_range = stage.GetPrimAtPath("/CamB").GetAttribute("clippingRange")
        assert not cam_b_range.HasAuthoredValue()

        _type_in_channel(row, 0, 3.0, 1.0)

        assert not cam_b_range.HasAuthoredValue()
        assert tuple(stage.GetPrimAtPath("/CamA").GetAttribute("clippingRange").Get()) == (1.0, 500.0)
        assert not undo.can_undo()
        _assert_saved_layer_unchanged(stage)


@pytest.mark.parametrize(
    ("row_class", "type_name", "p1", "p2", "typed", "expected_p1", "expected_p2"),
    [
        (Vec3FloatAttributeRow, "float3", (1.0, 2.0, 3.0), (9.0, 8.0, 7.0), 5.0,
         (5.0, 2.0, 3.0), (5.0, 8.0, 7.0)),
        (Vec3IntAttributeRow, "int3", (1, 2, 3), (9, 8, 7), 5,
         (5, 2, 3), (5, 8, 7)),
    ],
)
def test_buffered_channel_edit_keeps_other_channels_of_each_path(
    row_class, type_name, p1, p2, typed, expected_p1, expected_p2
):
    meta = AttributeMetadata(
        name="v", display_name="V", type_name=type_name, value_type=tuple, group="Test",
    )
    assert meta.change_on_edit_end  # the write happens when the edit ends
    adapter = MockPropertyAdapter(paths=["/P1", "/P2"], attributes={"v": meta})
    adapter.set_path_value("/P1", "v", p1)
    adapter.set_path_value("/P2", "v", p2)
    window = ui.Window(f"test_539_buffered_{type_name}", width=400, height=60)
    with window.frame:
        row = row_class(meta, adapter)

    _type_in_channel(row, 0, typed)

    assert adapter._per_path_values["/P1"]["v"] == expected_p1
    assert adapter._per_path_values["/P2"]["v"] == expected_p2


@pytest.mark.parametrize("paths", [[], ["/P"]])
def test_channel_edit_with_no_stored_value_counts_missing_channels_as_zero(paths):
    meta = AttributeMetadata(
        name="v", display_name="V", type_name="float3", value_type=tuple, group="Test",
    )
    adapter = MockPropertyAdapter(paths=paths, attributes={"v": meta})
    window = ui.Window(f"test_539_no_value_{len(paths)}", width=400, height=60)
    with window.frame:
        row = Vec3FloatAttributeRow(meta, adapter)

    _type_in_channel(row, 0, 5.0)

    assert adapter.get_value("v") == (5.0, 0.0, 0.0)


def test_channel_edit_with_no_stored_value_and_no_channel_count_names_the_cause():
    meta = AttributeMetadata(
        name="v", display_name="V", type_name="custom", value_type=tuple, group="Test",
    )
    adapter = MockPropertyAdapter(paths=["/P"], attributes={"v": meta})

    with pytest.raises(ValueError, match=r"set_component_value: 'v' has no stored value"):
        adapter.set_component_value("v", 0, 5.0)

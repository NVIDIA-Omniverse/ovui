# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Translate, Rotate and Scale fields of a matrix transform.

An object whose transform is stored as a matrix (``xformOp:transform``) had
only a 4x4 grid in the Property Inspector. The row that the builder table
makes for it now has Translate, Rotate and Scale fields. A value is typed
into a field with injected mouse and key input, the same input path as a
user, and the matrix of the stage, the grid and the undo history must agree.
"""

from __future__ import annotations

import math
import time

import omni.ui as ui
import pytest
from ovui_data_adapters.common.matrix_transform import decompose_matrix
from ovui_data_adapters.openusd import UsdPropertyAdapter
from pxr import Gf, Usd, UsdGeom

from ovui_widgets.common.undo import UndoManager
from ovui_widgets.property.builders import WidgetBuilderTable

_TRANSFORM = "xformOp:transform"
_KEY_ENTER = 525
_WINDOW = "_test_property_matrix_transform_fields"


def _matrix(translate, rotate_y, scale):
    """The matrix of translate, rotateXYZ (0, rotate_y, 0) and scale ops."""
    stage = Usd.Stage.CreateInMemory()
    xform = UsdGeom.Xform.Define(stage, "/M")
    xform.AddTranslateOp().Set(Gf.Vec3d(*translate))
    xform.AddRotateXYZOp().Set(Gf.Vec3f(0.0, rotate_y, 0.0))
    xform.AddScaleOp().Set(Gf.Vec3f(*scale))
    return xform.GetLocalTransformation()


_START = _matrix((-2.0, 0.75, 0.0), 30.0, (1.0, 1.5, 1.0))


@pytest.fixture(scope="module")
def frames():
    """One headless ovui start for the module; ``frames()`` draws frames."""
    from omni.ui import standalone

    from tests._vulkan_device import use_headless_vulkan

    patch = pytest.MonkeyPatch()
    use_headless_vulkan(patch)
    standalone.shutdown()
    standalone.init(_WINDOW, 640, 200)

    def tick(count=3):
        for _ in range(count):
            standalone._tick_one_frame()

    yield tick
    standalone.shutdown()
    patch.undo()


def _cube_row(frames, matrix):
    """A cube with only the matrix transform ``matrix``, and its Transform
    row in a window. Yields the stage, the undo manager and the row."""
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Cube.Define(stage, "/MatrixCube").AddTransformOp().Set(matrix)
    undo = UndoManager()
    adapter = UsdPropertyAdapter(stage, ["/MatrixCube"], undo_manager=undo)
    window = ui.Window(
        _WINDOW, width=640, height=200,
        position_x=0, position_y=0, flags=ui.WINDOW_FLAGS_NO_TITLE_BAR,
    )
    with window.frame:
        row = WidgetBuilderTable.build(_TRANSFORM, adapter.get_attribute_metadata(_TRANSFORM), adapter)
    frames()
    yield stage, undo, row
    window.destroy()
    frames()


@pytest.fixture()
def matrix_cube(frames):
    """A cube with only a matrix transform, and its Transform row in a window."""
    yield from _cube_row(frames, _START)


# A flat cube (the reviewer's scene of the zero scale): scale 1, 0, 0.
_FLAT = Gf.Matrix4d(1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, -2, 0.75, 0, 1)


@pytest.fixture()
def flat_cube(frames):
    yield from _cube_row(frames, _FLAT)


@pytest.fixture()
def nan_cube(frames):
    yield from _cube_row(frames, Gf.Matrix4d(1, 0, 0, 0, 0, float("nan"), 0, 0, 0, 0, 1, 0, -2, 0.75, 0, 1))


@pytest.fixture()
def reports(monkeypatch):
    """The status-bar messages of the Property Inspector."""
    from ovui_widgets.common.error_reporter import ErrorReporter

    shown = []
    monkeypatch.setattr(ErrorReporter, "show_warning", lambda message, *args, **kwargs: shown.append(message))
    monkeypatch.setattr(ErrorReporter, "log_warning", lambda *args, **kwargs: None)
    return shown


def _stored(stage):
    return stage.GetPrimAtPath("/MatrixCube").GetAttribute(_TRANSFORM).Get()


def _shown(widgets):
    return tuple(widget.model.get_value_as_float() for widget in widgets)


def _type_and_enter(frames, widget, keys):
    """Double-click ``widget`` into keyboard-edit mode, type each of ``keys``
    on its own frame, and press Enter."""
    from omni.ui import _ui, standalone

    # Let the double-click time (0.30 s) of an earlier click pass.
    time.sleep(0.5)
    _ui._inject_mouse_move(
        float(widget.screen_position_x + widget.computed_width / 2),
        float(widget.screen_position_y + widget.computed_height / 2),
    )
    frames(2)
    for _ in range(2):
        _ui._inject_mouse_button(0, True)
        frames(1)
        _ui._inject_mouse_button(0, False)
        frames(1)
    frames(2)
    assert standalone.is_text_input_active(), "the field did not enter keyboard-edit mode"
    for key in keys:
        _ui._inject_text_input(key)
        frames(2)
    _ui._inject_key_event(_KEY_ENTER, True)
    frames(1)
    _ui._inject_key_event(_KEY_ENTER, False)
    frames(2)


def test_the_fields_show_the_parts_of_the_matrix(matrix_cube):
    _stage, _undo, row = matrix_cube
    assert _shown(row._part_widgets["translate"]) == pytest.approx((-2.0, 0.75, 0.0))
    assert _shown(row._part_widgets["rotate"]) == pytest.approx((0.0, 30.0, 0.0))
    assert _shown(row._part_widgets["scale"]) == pytest.approx((1.0, 1.5, 1.0))
    # The 4x4 grid stays below the fields.
    assert len(row._widgets) == 16


@pytest.mark.parametrize(
    "part, index, text, expected",
    [
        ("translate", 0, "-3", _matrix((-3.0, 0.75, 0.0), 30.0, (1.0, 1.5, 1.0))),
        ("rotate", 1, "60", _matrix((-2.0, 0.75, 0.0), 60.0, (1.0, 1.5, 1.0))),
        ("scale", 0, "2", _matrix((-2.0, 0.75, 0.0), 30.0, (2.0, 1.5, 1.0))),
    ],
)
def test_a_typed_value_changes_the_matrix_the_grid_and_is_one_undo_step(
    matrix_cube, frames, part, index, text, expected
):
    stage, undo, row = matrix_cube

    _type_and_enter(frames, row._part_widgets[part][index], [text])

    assert Gf.IsClose(_stored(stage), expected, 1.0e-9)
    flat = [expected[r][c] for r in range(4) for c in range(4)]
    assert _shown(row._widgets) == pytest.approx(flat, abs=1.0e-9)
    parts = decompose_matrix(flat)
    assert _shown(row._part_widgets[part]) == pytest.approx(getattr(parts, part))

    assert undo.undo()
    assert Gf.IsClose(_stored(stage), _START, 1.0e-12)
    assert not undo.can_undo()


def test_rotate_typed_key_by_key_past_90_degrees_gives_the_typed_turn(matrix_cube, frames):
    """Each typed key writes a value (9, 95, 95., 95.5). Each value must turn
    the object from its turn at the start of the edit: the matrix of Y 95 has
    the angles X 180, Y 85, Z 180, and a new Y on those angles is another turn."""
    stage, _undo, row = matrix_cube

    _type_and_enter(frames, row._part_widgets["rotate"][1], "95.5")

    expected = _matrix((-2.0, 0.75, 0.0), 95.5, (1.0, 1.5, 1.0))
    assert Gf.IsClose(_stored(stage), expected, 1.0e-9)
    flat = [expected[r][c] for r in range(4) for c in range(4)]
    assert _shown(row._widgets) == pytest.approx(flat, abs=1.0e-9)


def test_a_flat_object_shows_its_true_parts_and_takes_a_typed_scale(flat_cube, frames):
    """A matrix with scale 1, 0, 0 (regression review): the fields showed
    false zeros, and a typed Scale X did not change the matrix."""
    stage, undo, row = flat_cube
    assert _shown(row._part_widgets["translate"]) == pytest.approx((-2.0, 0.75, 0.0))
    assert _shown(row._part_widgets["rotate"]) == pytest.approx((0.0, 0.0, 0.0))
    assert _shown(row._part_widgets["scale"]) == pytest.approx((1.0, 0.0, 0.0))

    _type_and_enter(frames, row._part_widgets["scale"][0], ["2"])

    expected = Gf.Matrix4d(2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, -2, 0.75, 0, 1)
    assert Gf.IsClose(_stored(stage), expected, 1.0e-12)
    assert _shown(row._part_widgets["scale"]) == pytest.approx((2.0, 0.0, 0.0))
    assert undo.undo()
    assert _stored(stage) == _FLAT


def test_an_edit_that_a_matrix_with_nan_cannot_take_is_refused_with_the_cause(nan_cube, frames, reports):
    """Rotate and Scale of a matrix with nan are not known: they show nan,
    and a typed value is refused with a message; the matrix stays."""
    stage, undo, row = nan_cube
    before = _stored(stage)
    assert _shown(row._part_widgets["translate"]) == pytest.approx((-2.0, 0.75, 0.0))
    assert all(math.isnan(v) for v in _shown(row._part_widgets["scale"]))

    _type_and_enter(frames, row._part_widgets["scale"][0], ["2"])

    assert str(_stored(stage)) == str(before)
    assert reports == [
        "Scale X: 2 is not accepted. The matrix has a value that is not a finite number, "
        "so its Rotate and Scale are not known. The old value stays."
    ]
    assert not undo.can_undo()

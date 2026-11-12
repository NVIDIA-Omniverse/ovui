# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""An edit of one part of a matrix transform keeps the other values of each
object, also for an adapter that writes when the edit ends.

The mock adapter writes at the end of the edit (``change_on_edit_end``) and
gives no shown value for objects with different matrices ("Mixed"). The
model must still write only the edited channel of each object.
"""

from __future__ import annotations

import math

from ovui_data_adapters.common import AttributeMetadata
from ovui_data_adapters.common.matrix_transform import decompose_matrix

from ovui_widgets.app.testing import MockPropertyAdapter
from ovui_widgets.property.models import AttributeModelBase

_TRANSFORM = "xformOp:transform"


def _matrix(translate, rotate_y_degrees):
    c = math.cos(math.radians(rotate_y_degrees))
    s = math.sin(math.radians(rotate_y_degrees))
    return (
        c, 0.0, -s, 0.0,
        0.0, 1.0, 0.0, 0.0,
        s, 0.0, c, 0.0,
        *translate, 1.0,
    )


def _two_objects():
    meta = AttributeMetadata(
        name=_TRANSFORM, display_name="Transform", type_name="matrix4d",
        value_type=tuple, group="Transform",
    )
    adapter = MockPropertyAdapter(paths=["/A", "/B"], attributes={_TRANSFORM: meta})
    adapter.set_path_value("/A", _TRANSFORM, _matrix((1.0, 2.0, 3.0), 10.0))
    adapter.set_path_value("/B", _TRANSFORM, _matrix((-4.0, 0.0, 5.0), 20.0))
    return adapter, AttributeModelBase(adapter, _TRANSFORM, meta)


def _parts(adapter, path):
    return decompose_matrix(adapter._per_path_values[path][_TRANSFORM])


def test_buffered_edit_writes_only_the_edited_channel_of_each_object_at_the_end():
    adapter, model = _two_objects()
    assert model.get_value() is None  # the matrices differ: the row shows "Mixed"

    model.begin_edit()
    assert model.set_matrix_part_value("rotate", 1, 50.0, None, field="Rotate Y")
    assert model.set_matrix_part_value("rotate", 1, 60.0, None, field="Rotate Y")
    # Nothing is written before the edit ends.
    assert math.isclose(_parts(adapter, "/A").rotate[1], 10.0)
    model.end_edit()

    a, b = _parts(adapter, "/A"), _parts(adapter, "/B")
    assert math.isclose(a.rotate[1], 60.0) and math.isclose(b.rotate[1], 60.0)
    assert a.translate == (1.0, 2.0, 3.0)
    assert b.translate == (-4.0, 0.0, 5.0)


def test_a_value_that_is_not_a_number_is_refused_and_writes_nothing(monkeypatch):
    from ovui_widgets.common.error_reporter import ErrorReporter

    messages = []
    monkeypatch.setattr(ErrorReporter, "log_warning", lambda _module, text: messages.append(text))
    monkeypatch.setattr(ErrorReporter, "show_warning", lambda text: None)
    adapter, model = _two_objects()
    before = dict(adapter._per_path_values["/A"])

    model.begin_edit()
    assert not model.set_matrix_part_value("scale", 0, float("nan"), None, field="Scale X")
    model.end_edit()

    assert adapter._per_path_values["/A"] == before
    assert messages == [
        "Scale X: nan is not accepted. A transform value must be a finite number. The old value stays."
    ]


def test_a_buffered_edit_is_refused_for_all_objects_when_one_matrix_has_nan(monkeypatch):
    """The edit is written when it ends; one selected object has a matrix
    with nan, so its Scale is not known. No object changes, and the message
    names the field and the cause."""
    from ovui_widgets.common.error_reporter import ErrorReporter

    messages = []
    monkeypatch.setattr(ErrorReporter, "log_warning", lambda _module, text: messages.append(text))
    monkeypatch.setattr(ErrorReporter, "show_warning", lambda text: None)
    adapter, model = _two_objects()
    broken = list(_matrix((-4.0, 0.0, 5.0), 20.0))
    broken[5] = float("nan")
    adapter.set_path_value("/B", _TRANSFORM, tuple(broken))
    before_a = adapter._per_path_values["/A"][_TRANSFORM]

    model.begin_edit()
    assert model.set_matrix_part_value("scale", 0, 2.0, None, field="Scale X")
    model.end_edit()

    assert adapter._per_path_values["/A"][_TRANSFORM] == before_a
    # nan is not equal to itself: compare the text of the values.
    assert str(adapter._per_path_values["/B"][_TRANSFORM]) == str(tuple(broken))
    assert messages == [
        "Scale X: 2 is not accepted. The matrix has a value that is not a finite number, "
        "so its Rotate and Scale are not known. The old value stays."
    ]
    assert not model.editing

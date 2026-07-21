# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for attribute row widgets + build_attribute_row factory.

Step 1.4 of the property inspector implementation migrated every row class off direct adapter
calls onto an owned :class:`AttributeModelBase`. The tests below verify:

* Row ``__init__`` constructs an ``AttributeModelBase`` and seeds it with
  the initial adapter value.
* Widget callbacks (``_on_begin_edit`` / ``_on_value_changed`` /
  ``_on_end_edit``) route through ``model.set_value`` / ``model.begin_edit``
  / ``model.end_edit`` — so the adapter ultimately sees the same
  ``begin_edit → set_value → end_edit`` sequence it used to receive
  directly.
* External ``adapter.fire_change()`` refreshes the row's displayed widget
  value via ``model._on_backing_changed`` → ``_on_model_value_changed``.
* The ``build_attribute_row`` factory still dispatches each type name to
  the right row class (forwards through ``WidgetBuilderTable``).
"""

from typing import Any, Callable, List

import pytest

# ---------------------------------------------------------------------------
# Minimal adapter that records calls + exposes subscribe_changes/fire_change
# ---------------------------------------------------------------------------


class _TrackingSubscription:
    """RAII subscription handle for _TrackingAdapter.subscribe_changes."""

    def __init__(self, adapter: "_TrackingAdapter", callback: Callable[[], None]) -> None:
        self._adapter = adapter
        self._callback = callback

    def cancel(self) -> None:
        if self._adapter is None:
            return
        try:
            self._adapter._subscribers.remove(self._callback)
        except ValueError:
            pass
        self._adapter = None
        self._callback = None


class _TrackingAdapter:
    """Minimal PropertyAdapter double used by row tests.

    Records every ``begin_edit``/``set_value``/``end_edit`` on
    ``self.calls`` so tests can assert the exact sequence produced by the
    row → model → adapter chain. Exposes ``subscribe_changes`` and a
    ``fire_change`` helper so tests can simulate external USD edits
    landing on the model's ``_on_backing_changed``.
    """

    def __init__(self, values=None):
        self._values = dict(values) if values else {}
        self.calls: List[tuple] = []
        self._subscribers: List[Callable[[], None]] = []
        # Step 3.6: per-attribute resolved asset paths. Mirrors the mock
        # adapter's ``set_resolved_asset_path`` seed so ``_TrackingAdapter``
        # can exercise the :class:`AssetPathAttributeRow` tooltip path.
        self._resolved_asset_paths: dict = {}

    def get_value(self, attr_name: str) -> Any:
        return self._values.get(attr_name)

    def begin_edit(self, attr_name: str) -> None:
        self.calls.append(("begin_edit", attr_name))

    def set_value(self, attr_name: str, value: Any) -> None:
        self._values[attr_name] = value
        self.calls.append(("set_value", attr_name, value))

    def end_edit(self, attr_name: str) -> None:
        self.calls.append(("end_edit", attr_name))

    def is_ambiguous(self, attr_name: str) -> bool:
        return False

    def get_resolved_asset_path(self, attr_name: str):
        """Return the seeded resolved path, or ``None`` if none seeded.

        Inherits the :class:`PropertyAdapter` ABC's default behaviour —
        ``AssetPathAttributeRow`` can call this unconditionally without
        branching on adapter scheme.
        """
        return self._resolved_asset_paths.get(attr_name)

    def subscribe_changes(self, callback: Callable[[], None]) -> _TrackingSubscription:
        self._subscribers.append(callback)
        return _TrackingSubscription(self, callback)

    def fire_change(self) -> None:
        """Invoke all subscribers — simulates a USD Tf.Notice fan-out."""
        for cb in list(self._subscribers):
            cb()


# ---------------------------------------------------------------------------
# Fake widget models (headless — no omni.ui context required)
# ---------------------------------------------------------------------------


class _FakeFloatModel:
    def __init__(self, value=0.0):
        self._value = float(value)

    def get_value_as_float(self):
        return self._value

    def set_value(self, v):
        self._value = float(v)


class _FakeIntModel:
    def __init__(self, value=0):
        self._value = int(value)

    def get_value_as_int(self):
        return self._value

    def set_value(self, v):
        self._value = int(v)


class _FakeStringModel:
    def __init__(self, value=""):
        self._value = str(value)

    def get_value_as_string(self):
        return self._value

    def set_value(self, v):
        self._value = str(v)


class _FakeBoolModel:
    def __init__(self, value=False):
        self._value = bool(value)

    def get_value_as_bool(self):
        return self._value

    def set_value(self, v):
        self._value = bool(v)


# ---------------------------------------------------------------------------
# Fake widgets (expose a ``.model`` attribute like the omni.ui widgets)
# ---------------------------------------------------------------------------


class _FakeFloatWidget:
    def __init__(self, initial=0.0):
        self.model = _FakeFloatModel(initial)


class _FakeIntWidget:
    def __init__(self, initial=0):
        self.model = _FakeIntModel(initial)


class _FakeStringWidget:
    def __init__(self, initial=""):
        self.model = _FakeStringModel(initial)


class TestValueFieldFocusHelpers:
    def test_focus_helper_sets_named_variant(self):
        from ovui_widgets.property.attribute_row import _set_value_field_focused

        widget = _FakeStringWidget()
        _set_value_field_focused(widget, True)
        assert widget.name == "focused"
        assert widget.style["border_color"] == "border_focused"
        _set_value_field_focused(widget, False)
        assert widget.name == ""
        assert widget.style == {}

    def test_matching_focus_helper_only_touches_matching_model(self):
        from ovui_widgets.property.attribute_row import _set_matching_value_field_focused

        first = _FakeFloatWidget()
        second = _FakeFloatWidget()
        _set_matching_value_field_focused([first, second], second.model, True)
        assert getattr(first, "name", "") == ""
        assert second.name == "focused"


class _FakeBoolWidget:
    def __init__(self, initial=False):
        self.model = _FakeBoolModel(initial)


# ---------------------------------------------------------------------------
# Helper to build AttributeMetadata quickly
# ---------------------------------------------------------------------------


def _make_prop(name="attr", display_name=None, value_type=float, type_name="float", group="X"):
    from ovui_data_adapters.common import AttributeMetadata
    return AttributeMetadata(
        name=name,
        display_name=display_name or name,
        type_name=type_name,
        value_type=value_type,
        group=group,
    )


# ---------------------------------------------------------------------------
# Fixture: suppress _build_ui on all row classes so tests run headlessly
# ---------------------------------------------------------------------------


@pytest.fixture
def no_ui(monkeypatch):
    """Stubs out ``_build_ui`` on every row class.

    With ``_build_ui`` neutralised, a row's ``__init__`` still constructs
    the :class:`AttributeModelBase`, subscribes to the model's value
    changes, and subscribes ``model._on_backing_changed`` to the adapter —
    which is the surface Step 1.4 needs to exercise. Tests that need a
    widget install a ``_Fake*Widget`` onto ``row._widget`` / ``row._widgets``
    after construction.
    """
    from ovui_widgets.property import attribute_row as ar
    for cls in [
        ar.FloatAttributeRow,
        ar.Vec2FloatAttributeRow,
        ar.Vec3FloatAttributeRow,
        ar.Vec4FloatAttributeRow,
        ar.IntAttributeRow,
        ar.Vec2IntAttributeRow,
        ar.Vec3IntAttributeRow,
        ar.Vec4IntAttributeRow,
        ar.Color3fAttributeRow,
        ar.Color4fAttributeRow,
        ar.MatrixAttributeRow,
        ar.AssetPathAttributeRow,
        ar.RelationshipAttributeRow,
        ar.ArrayAttributeRow,
        ar.StringAttributeRow,
        ar.TokenAttributeRow,
        ar.BoolAttributeRow,
        ar._FallbackAttributeRow,
    ]:
        monkeypatch.setattr(cls, "_build_ui", lambda self: None)


# ---------------------------------------------------------------------------
# Row construction: each row now owns an AttributeModelBase
# ---------------------------------------------------------------------------


class TestRowOwnsAttributeModelBase:
    """Each row class must construct and own an :class:`AttributeModelBase`."""

    @pytest.mark.parametrize(
        ("cls_name", "type_name", "value_type"),
        [
            ("FloatAttributeRow", "float", float),
            ("IntAttributeRow", "int", int),
            ("BoolAttributeRow", "bool", bool),
            ("StringAttributeRow", "string", str),
            ("Vec3FloatAttributeRow", "float3", tuple),
        ],
    )
    def test_row_constructs_model(self, no_ui, cls_name, type_name, value_type):
        from ovui_widgets.property import attribute_row as ar
        from ovui_widgets.property.models import AttributeModelBase
        adapter = _TrackingAdapter()
        prop = _make_prop(type_name=type_name, value_type=value_type)
        row = getattr(ar, cls_name)(prop, adapter)
        assert isinstance(row._model, AttributeModelBase)

    def test_model_seeded_with_adapter_value(self, no_ui):
        from ovui_widgets.property.attribute_row import FloatAttributeRow
        adapter = _TrackingAdapter({"radius": 2.5})
        prop = _make_prop(name="radius", value_type=float, type_name="float")
        row = FloatAttributeRow(prop, adapter)
        assert row._model.get_value() == 2.5

    def test_row_subscribes_adapter_changes(self, no_ui):
        from ovui_widgets.property.attribute_row import FloatAttributeRow
        adapter = _TrackingAdapter({"radius": 1.0})
        prop = _make_prop(name="radius", value_type=float, type_name="float")
        FloatAttributeRow(prop, adapter)
        # Row's adapter subscription routes through model._on_backing_changed.
        assert len(adapter._subscribers) == 1


# ---------------------------------------------------------------------------
# FloatAttributeRow
# ---------------------------------------------------------------------------


class TestFloatAttributeRow:
    def test_shows_correct_initial_value(self, no_ui):
        from ovui_widgets.property.attribute_row import FloatAttributeRow
        adapter = _TrackingAdapter({"opacity": 0.75})
        prop = _make_prop(name="opacity", value_type=float, type_name="float")
        row = FloatAttributeRow(prop, adapter)
        assert row._model.get_value() == 0.75

    def test_edit_sequence_goes_through_model(self, no_ui):
        from ovui_widgets.property.attribute_row import FloatAttributeRow
        adapter = _TrackingAdapter({"radius": 1.0})
        prop = _make_prop(name="radius", value_type=float, type_name="float")
        row = FloatAttributeRow(prop, adapter)
        widget_model = _FakeFloatModel(2.5)
        row._on_begin_edit(widget_model)
        row._on_value_changed(widget_model)
        row._on_end_edit(widget_model)
        # change_on_edit_end=True (default) buffers the set_value until
        # end_edit flushes. Adapter sees exactly one set_value at the end.
        assert adapter.calls == [
            ("begin_edit", "radius"),
            ("set_value", "radius", 2.5),
            ("end_edit", "radius"),
        ]

    def test_edit_no_change_skips_set_value(self, no_ui):
        from ovui_widgets.property.attribute_row import FloatAttributeRow
        adapter = _TrackingAdapter({"radius": 1.0})
        prop = _make_prop(name="radius", value_type=float, type_name="float")
        row = FloatAttributeRow(prop, adapter)
        widget_model = _FakeFloatModel(1.0)  # same as initial
        row._on_begin_edit(widget_model)
        row._on_value_changed(widget_model)
        row._on_end_edit(widget_model)
        # value unchanged → no adapter.set_value write, undo group still closed
        assert adapter.calls == [
            ("begin_edit", "radius"),
            ("end_edit", "radius"),
        ]

    def test_begin_end_edit_toggles_focused_value_field_style(self, no_ui):
        from ovui_widgets.property.attribute_row import FloatAttributeRow

        adapter = _TrackingAdapter({"radius": 1.0})
        prop = _make_prop(name="radius", value_type=float, type_name="float")
        row = FloatAttributeRow(prop, adapter)
        row._widget = _FakeFloatWidget(1.0)

        row._on_begin_edit(row._widget.model)
        assert row._widget.name == "focused"
        assert row._widget.style["border_color"] == "border_focused"

        row._on_end_edit(row._widget.model)
        assert row._widget.name == ""
        assert row._widget.style == {}

    def test_external_change_updates_widget(self, no_ui):
        from ovui_widgets.property.attribute_row import FloatAttributeRow
        adapter = _TrackingAdapter({"radius": 1.0})
        prop = _make_prop(name="radius", value_type=float, type_name="float")
        row = FloatAttributeRow(prop, adapter)
        row._widget = _FakeFloatWidget(1.0)
        adapter._values["radius"] = 7.25
        adapter.fire_change()
        assert row._widget.model.get_value_as_float() == pytest.approx(7.25)
        assert row._model.get_value() == pytest.approx(7.25)

    def test_external_change_suppressed_during_edit(self, no_ui):
        from ovui_widgets.property.attribute_row import FloatAttributeRow
        adapter = _TrackingAdapter({"radius": 1.0})
        prop = _make_prop(name="radius", value_type=float, type_name="float")
        row = FloatAttributeRow(prop, adapter)
        row._widget = _FakeFloatWidget(2.0)
        row._on_begin_edit(_FakeFloatModel(2.0))
        row._on_value_changed(_FakeFloatModel(2.0))
        adapter._values["radius"] = 999.0
        adapter.fire_change()
        # Mid-edit: backing-change is dropped; the in-progress edit value wins.
        assert row._widget.model.get_value_as_float() == pytest.approx(2.0)
        assert row._model.get_value() == pytest.approx(2.0)

    def test_feedback_loop_guard_blocks_recursion(self, no_ui):
        """Reentrant widget set_value → _on_value_changed must not loop.

        Protects against an ``omni.ui`` ``SimpleFloatModel`` implementation
        that fires ``value_changed_fn`` unconditionally on ``set_value``.
        Without ``_updating``, the chain would be
        ``_on_model_value_changed → widget.set_value →
        _on_value_changed → model.set_value → _notify_value_changed →
        _on_model_value_changed`` ad infinitum.
        """
        from ovui_widgets.property.attribute_row import FloatAttributeRow
        adapter = _TrackingAdapter({"radius": 1.0})
        prop = _make_prop(name="radius", value_type=float, type_name="float")
        row = FloatAttributeRow(prop, adapter)

        class _ReentrantWidget:
            def __init__(self, row):
                self._row = row
                self.model = _FakeFloatModel(1.0)
                self._base_set = self.model.set_value

                def _set(v):
                    self._base_set(v)
                    # Simulate an omni.ui widget that fires value_changed_fn
                    # synchronously from inside set_value.
                    self._row._on_value_changed(self.model)
                self.model.set_value = _set

        row._widget = _ReentrantWidget(row)
        adapter._values["radius"] = 5.0
        adapter.fire_change()  # would recurse forever without the guard
        assert row._widget.model.get_value_as_float() == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Vec3FloatAttributeRow
# ---------------------------------------------------------------------------


class TestVec3FloatAttributeRow:
    def test_has_three_widget_slots(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3FloatAttributeRow
        prop = _make_prop(name="translate", value_type=tuple, type_name="float3")
        adapter = _TrackingAdapter({"translate": (1.0, 2.0, 3.0)})
        row = Vec3FloatAttributeRow(prop, adapter)
        assert len(row._widgets) == 3

    def test_component_change_updates_model(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3FloatAttributeRow
        adapter = _TrackingAdapter({"t": (0.0, 0.0, 0.0)})
        prop = _make_prop(name="t", value_type=tuple, type_name="float3")
        row = Vec3FloatAttributeRow(prop, adapter)
        widget_model = _FakeFloatModel(5.0)
        row._on_begin_edit(widget_model)
        row._on_component_changed(widget_model, 1)
        assert row._model.get_value() == (0.0, 5.0, 0.0)

    def test_component_change_flushed_on_end_edit(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3FloatAttributeRow
        adapter = _TrackingAdapter({"t": (0.0, 0.0, 0.0)})
        prop = _make_prop(name="t", value_type=tuple, type_name="float3")
        row = Vec3FloatAttributeRow(prop, adapter)
        widget_model = _FakeFloatModel(5.0)
        row._on_begin_edit(widget_model)
        row._on_component_changed(widget_model, 1)
        row._on_end_edit(widget_model)
        assert adapter.calls == [
            ("begin_edit", "t"),
            ("set_value", "t", (0.0, 5.0, 0.0)),
            ("end_edit", "t"),
        ]

    def test_begin_end_edit_pair_no_change(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3FloatAttributeRow
        adapter = _TrackingAdapter({"t": (1.0, 2.0, 3.0)})
        prop = _make_prop(name="t", value_type=tuple, type_name="float3")
        row = Vec3FloatAttributeRow(prop, adapter)
        widget_model = _FakeFloatModel()
        row._on_begin_edit(widget_model)
        row._on_end_edit(widget_model)
        # No component change → no adapter.set_value write
        assert adapter.calls == [("begin_edit", "t"), ("end_edit", "t")]

    def test_begin_end_edit_only_toggles_matching_component_focus(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3FloatAttributeRow

        adapter = _TrackingAdapter({"t": (1.0, 2.0, 3.0)})
        prop = _make_prop(name="t", value_type=tuple, type_name="float3")
        row = Vec3FloatAttributeRow(prop, adapter)
        row._widgets = [_FakeFloatWidget(), _FakeFloatWidget(), _FakeFloatWidget()]

        row._on_begin_edit(row._widgets[1].model)
        assert getattr(row._widgets[0], "name", "") == ""
        assert row._widgets[1].name == "focused"
        assert getattr(row._widgets[2], "name", "") == ""

        row._on_end_edit(row._widgets[1].model)
        assert row._widgets[1].name == ""
        assert row._widgets[1].style == {}

    def test_external_change_updates_all_widgets(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3FloatAttributeRow
        adapter = _TrackingAdapter({"t": (1.0, 2.0, 3.0)})
        prop = _make_prop(name="t", value_type=tuple, type_name="float3")
        row = Vec3FloatAttributeRow(prop, adapter)
        row._widgets = [_FakeFloatWidget(), _FakeFloatWidget(), _FakeFloatWidget()]
        adapter._values["t"] = (10.0, 20.0, 30.0)
        adapter.fire_change()
        expected = (10.0, 20.0, 30.0)
        for i, widget in enumerate(row._widgets):
            assert widget.model.get_value_as_float() == pytest.approx(expected[i])


# ---------------------------------------------------------------------------
# IntAttributeRow
# ---------------------------------------------------------------------------


class TestIntAttributeRow:
    def test_shows_correct_initial_value(self, no_ui):
        from ovui_widgets.property.attribute_row import IntAttributeRow
        adapter = _TrackingAdapter({"count": 42})
        prop = _make_prop(name="count", value_type=int, type_name="int")
        row = IntAttributeRow(prop, adapter)
        assert row._model.get_value() == 42

    def test_edit_sequence_goes_through_model(self, no_ui):
        from ovui_widgets.property.attribute_row import IntAttributeRow
        adapter = _TrackingAdapter({"count": 0})
        prop = _make_prop(name="count", value_type=int, type_name="int")
        row = IntAttributeRow(prop, adapter)
        widget_model = _FakeIntModel(7)
        row._on_begin_edit(widget_model)
        row._on_value_changed(widget_model)
        row._on_end_edit(widget_model)
        assert adapter.calls == [
            ("begin_edit", "count"),
            ("set_value", "count", 7),
            ("end_edit", "count"),
        ]

    def test_external_change_updates_widget(self, no_ui):
        from ovui_widgets.property.attribute_row import IntAttributeRow
        adapter = _TrackingAdapter({"count": 1})
        prop = _make_prop(name="count", value_type=int, type_name="int")
        row = IntAttributeRow(prop, adapter)
        row._widget = _FakeIntWidget(1)
        adapter._values["count"] = 99
        adapter.fire_change()
        assert row._widget.model.get_value_as_int() == 99


# ---------------------------------------------------------------------------
# StringAttributeRow
# ---------------------------------------------------------------------------


class TestStringAttributeRow:
    def test_shows_correct_initial_value(self, no_ui):
        from ovui_widgets.property.attribute_row import StringAttributeRow
        adapter = _TrackingAdapter({"label": "hello"})
        prop = _make_prop(name="label", value_type=str, type_name="string")
        row = StringAttributeRow(prop, adapter)
        assert row._model.get_value() == "hello"

    def test_end_edit_commits_value(self, no_ui):
        from ovui_widgets.property.attribute_row import StringAttributeRow
        adapter = _TrackingAdapter({"label": "original"})
        prop = _make_prop(name="label", value_type=str, type_name="string")
        row = StringAttributeRow(prop, adapter)
        row._on_begin_edit(_FakeStringModel("original"))
        row._on_end_edit(_FakeStringModel("changed"))
        assert adapter.calls == [
            ("begin_edit", "label"),
            ("set_value", "label", "changed"),
            ("end_edit", "label"),
        ]

    def test_begin_edit_records_start_value(self, no_ui):
        from ovui_widgets.property.attribute_row import StringAttributeRow
        adapter = _TrackingAdapter({"n": "before"})
        prop = _make_prop(name="n", value_type=str, type_name="string")
        row = StringAttributeRow(prop, adapter)
        row._on_begin_edit(_FakeStringModel("before"))
        assert row._start_value == "before"

    def test_external_change_updates_widget(self, no_ui):
        from ovui_widgets.property.attribute_row import StringAttributeRow
        adapter = _TrackingAdapter({"label": "a"})
        prop = _make_prop(name="label", value_type=str, type_name="string")
        row = StringAttributeRow(prop, adapter)
        row._widget = _FakeStringWidget("a")
        adapter._values["label"] = "new"
        adapter.fire_change()
        assert row._widget.model.get_value_as_string() == "new"


# ---------------------------------------------------------------------------
# BoolAttributeRow
# ---------------------------------------------------------------------------


class TestBoolAttributeRow:
    def test_shows_correct_initial_value(self, no_ui):
        from ovui_widgets.property.attribute_row import BoolAttributeRow
        adapter = _TrackingAdapter({"visible": True})
        prop = _make_prop(name="visible", value_type=bool, type_name="bool")
        row = BoolAttributeRow(prop, adapter)
        assert row._model.get_value() is True

    def test_toggle_calls_begin_set_end_via_model(self, no_ui):
        from ovui_widgets.property.attribute_row import BoolAttributeRow
        adapter = _TrackingAdapter({"visible": False})
        prop = _make_prop(name="visible", value_type=bool, type_name="bool")
        row = BoolAttributeRow(prop, adapter)
        row._on_value_changed(_FakeBoolModel(True))
        assert adapter.calls == [
            ("begin_edit", "visible"),
            ("set_value", "visible", True),
            ("end_edit", "visible"),
        ]

    def test_external_change_updates_widget(self, no_ui):
        from ovui_widgets.property.attribute_row import BoolAttributeRow
        adapter = _TrackingAdapter({"visible": False})
        prop = _make_prop(name="visible", value_type=bool, type_name="bool")
        row = BoolAttributeRow(prop, adapter)
        row._widget = _FakeBoolWidget(False)
        adapter._values["visible"] = True
        adapter.fire_change()
        assert row._widget.model.get_value_as_bool() is True


# ---------------------------------------------------------------------------
# build_attribute_row factory (deprecated forwarder to WidgetBuilderTable)
# ---------------------------------------------------------------------------


class TestAttributeRowFactory:
    def test_dispatches_float(self, no_ui):
        from ovui_widgets.property.attribute_row import FloatAttributeRow, build_attribute_row
        prop = _make_prop(value_type=float, type_name="float")
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, FloatAttributeRow)

    def test_dispatches_int(self, no_ui):
        from ovui_widgets.property.attribute_row import IntAttributeRow, build_attribute_row
        prop = _make_prop(value_type=int, type_name="int")
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, IntAttributeRow)

    def test_dispatches_str(self, no_ui):
        from ovui_widgets.property.attribute_row import StringAttributeRow, build_attribute_row
        prop = _make_prop(value_type=str, type_name="string")
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, StringAttributeRow)

    def test_dispatches_bool(self, no_ui):
        from ovui_widgets.property.attribute_row import BoolAttributeRow, build_attribute_row
        prop = _make_prop(value_type=bool, type_name="bool")
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, BoolAttributeRow)

    def test_dispatches_float3(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3FloatAttributeRow, build_attribute_row
        prop = _make_prop(value_type=tuple, type_name="float3")
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, Vec3FloatAttributeRow)

    def test_dispatches_color3f(self, no_ui):
        """Step 3.4 moved ``color3f`` from the plain vec3 builder onto the
        new ``Color3fAttributeRow`` (+ swatch preview). Updated from the
        pre-3.4 assertion against ``Vec3FloatAttributeRow``."""
        from ovui_widgets.property.attribute_row import Color3fAttributeRow, build_attribute_row
        prop = _make_prop(value_type=tuple, type_name="color3f")
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, Color3fAttributeRow)

    def test_dispatches_color4f(self, no_ui):
        """Step 3.4: ``color4f`` is newly registered (was falling through to
        the read-only fallback before)."""
        from ovui_widgets.property.attribute_row import Color4fAttributeRow, build_attribute_row
        prop = _make_prop(value_type=tuple, type_name="color4f")
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, Color4fAttributeRow)

    def test_dispatches_double3(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3FloatAttributeRow, build_attribute_row
        prop = _make_prop(value_type=tuple, type_name="double3")
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, Vec3FloatAttributeRow)

    def test_unknown_type_uses_fallback(self, no_ui):
        """Step 3.8 registered ``double``; this regression guard now uses
        ``uchar`` (still unregistered as of Step 3.8) so the fallback
        path continues to be exercised. Anchoring against an
        unregistered USD scalar (rather than a made-up ``__unknown__``
        string) keeps the test aligned with real USD type token
        coverage — if ``uchar`` ever gets a registration, the test
        correctly starts failing and whoever added it is forced to
        pick a new still-unregistered scalar."""
        from ovui_widgets.property.attribute_row import _FallbackAttributeRow, build_attribute_row
        prop = _make_prop(value_type=object, type_name="uchar")
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, _FallbackAttributeRow)

    def test_vec3_takes_priority_over_value_type(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3FloatAttributeRow, build_attribute_row
        # type_name wins over value_type for vec3 names
        prop = _make_prop(value_type=float, type_name="normal3f")
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, Vec3FloatAttributeRow)

    @pytest.mark.parametrize("type_name", ["half2", "float2", "double2"])
    def test_dispatches_vec2_type_names(self, no_ui, type_name):
        from ovui_widgets.property.attribute_row import Vec2FloatAttributeRow, build_attribute_row
        prop = _make_prop(value_type=tuple, type_name=type_name)
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, Vec2FloatAttributeRow)

    @pytest.mark.parametrize("type_name", ["half4", "float4", "double4"])
    def test_dispatches_vec4_type_names(self, no_ui, type_name):
        from ovui_widgets.property.attribute_row import Vec4FloatAttributeRow, build_attribute_row
        prop = _make_prop(value_type=tuple, type_name=type_name)
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, Vec4FloatAttributeRow)

    def test_dispatches_int2(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec2IntAttributeRow, build_attribute_row
        prop = _make_prop(value_type=tuple, type_name="int2")
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, Vec2IntAttributeRow)

    def test_dispatches_int3(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3IntAttributeRow, build_attribute_row
        prop = _make_prop(value_type=tuple, type_name="int3")
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, Vec3IntAttributeRow)

    def test_dispatches_int4(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec4IntAttributeRow, build_attribute_row
        prop = _make_prop(value_type=tuple, type_name="int4")
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, Vec4IntAttributeRow)

    @pytest.mark.parametrize(
        ("type_name", "n_dim"),
        [("matrix2d", 2), ("matrix3d", 3), ("matrix4d", 4)],
    )
    def test_dispatches_matrix_types(self, no_ui, type_name, n_dim):
        """Step 3.5: ``matrix2d/matrix3d/matrix4d`` each dispatch to a
        ``MatrixAttributeRow`` with the matching ``n_dim``."""
        from ovui_widgets.property.attribute_row import MatrixAttributeRow, build_attribute_row
        prop = _make_prop(value_type=tuple, type_name=type_name)
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, MatrixAttributeRow)
        assert row._n_dim == n_dim

    def test_dispatches_asset(self, no_ui):
        """Step 3.6: ``asset`` dispatches to ``AssetPathAttributeRow``.

        Pre-3.6 the type name fell through to ``_FallbackAttributeRow``
        (see the previous ``test_unknown_type_uses_fallback`` regression
        guard — that test is rewritten below to use an unregistered name)."""
        from ovui_widgets.property.attribute_row import AssetPathAttributeRow, build_attribute_row
        prop = _make_prop(value_type=str, type_name="asset")
        row = build_attribute_row(prop, _TrackingAdapter())
        assert isinstance(row, AssetPathAttributeRow)

    def test_dispatches_relationship(self, no_ui):
        """Step 3.7: ``relationship`` dispatches to ``RelationshipAttributeRow``.

        Pre-3.7 the type name fell through to ``_FallbackAttributeRow``."""
        from ovui_widgets.property.attribute_row import (
            RelationshipAttributeRow,
            build_attribute_row,
        )
        adapter = _TrackingAdapter({"rel": ("/World/Target",)})
        prop = _make_prop(value_type=tuple, type_name="relationship")
        row = build_attribute_row(prop, adapter)
        assert isinstance(row, RelationshipAttributeRow)


# ---------------------------------------------------------------------------
# Step 2.5 — X/Y/Z channel label colour coding (property attribute builder behavior)
# ---------------------------------------------------------------------------
# ``Vec3FloatAttributeRow`` drives each channel label's
# ``style_type_name_override`` to ``Property.ChannelLabel.{X,Y,Z}`` so the
# per-axis palette colour (blue/green/orange) resolves at render time. When a
# channel is ambiguous, the Step 2.3 ``name="mixed"`` state selector activates
# ``Property.ChannelLabel.{…}::mixed``, which overrides the axis colour with
# ``cl.status_warning``. These tests bypass the ``no_ui`` fixture because the
# style assignments happen inside ``_build_ui``.


class TestVec3ChannelColorCoding:
    """Vec3 rows wire each channel label to ``Property.ChannelLabel.{axis}``."""

    _EXPECTED = (
        ("X", "Property.ChannelLabel.X"),
        ("Y", "Property.ChannelLabel.Y"),
        ("Z", "Property.ChannelLabel.Z"),
    )

    def _build(self, window_name, values=(1.0, 2.0, 3.0)):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import Vec3FloatAttributeRow
        prop = _make_prop(name="translate", value_type=tuple, type_name="float3")
        adapter = MockPropertyAdapter(
            paths=["/P1"], attributes={"translate": prop},
        )
        adapter.set_path_value("/P1", "translate", values)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return Vec3FloatAttributeRow(prop, adapter)

    def test_labels_use_channel_label_style(self):
        row = self._build("test_channel_color_base")
        actual = [lbl.style_type_name_override for lbl in row._channel_labels]
        assert actual == [e[1] for e in self._EXPECTED]

    def test_label_texts_match_axes(self):
        """The widget text is still the axis letter; only the style type changed."""
        row = self._build("test_channel_color_text")
        assert [lbl.text for lbl in row._channel_labels] == [e[0] for e in self._EXPECTED]

    def test_clean_labels_have_no_mixed_name(self):
        """Single-path (non-ambiguous) rows keep ``name=""`` so the axis colour
        resolves instead of the ``::mixed`` warning override."""
        row = self._build("test_channel_color_clean_name")
        assert [lbl.name for lbl in row._channel_labels] == ["", "", ""]

    def test_mixed_channel_keeps_channel_label_base_type(self):
        """Step 2.3 ambiguity uses the ``name="mixed"`` state on top of the
        Step 2.5 per-axis base — mixed warning overrides the axis colour
        without dropping the base type."""
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import Vec3FloatAttributeRow
        prop = _make_prop(name="translate", value_type=tuple, type_name="float3")
        adapter = MockPropertyAdapter(
            paths=["/P1", "/P2"], attributes={"translate": prop},
        )
        adapter.set_path_value("/P1", "translate", (1.0, 2.0, 3.0))
        adapter.set_path_value("/P2", "translate", (9.0, 2.0, 3.0))  # only X differs
        w = ui.Window("test_channel_color_mixed", width=400, height=60)
        with w.frame:
            row = Vec3FloatAttributeRow(prop, adapter)
        assert row._channel_labels[0].style_type_name_override == "Property.ChannelLabel.X"
        assert row._channel_labels[0].name == "mixed"
        # Y and Z clean: same base type, empty name
        assert row._channel_labels[1].style_type_name_override == "Property.ChannelLabel.Y"
        assert row._channel_labels[1].name == ""
        assert row._channel_labels[2].style_type_name_override == "Property.ChannelLabel.Z"
        assert row._channel_labels[2].name == ""


class TestChannelLabelStyleDict:
    """The ``PROPERTY_STYLES`` dict wires each axis to its palette shade."""

    @pytest.mark.parametrize(
        ("ch", "palette_name"),
        [("X", "channel_x"), ("Y", "channel_y"),
         ("Z", "channel_z"), ("W", "channel_w")],
    )
    def test_base_style_points_at_matching_palette_shade(self, ch, palette_name):
        from ovui_widgets.property.style import PROPERTY_STYLES
        style = PROPERTY_STYLES[f"Property.ChannelLabel.{ch}"]
        assert style["color"] == palette_name

    @pytest.mark.parametrize("ch", ["X", "Y", "Z", "W"])
    def test_mixed_state_points_at_status_warning(self, ch):
        """``::mixed`` must override the axis colour with the warning colour —
        aligning with the ``Property.LabelColumn::mixed`` convention from
        Step 2.3 so the two mixed signals share the same hue."""
        from ovui_widgets.property.style import PROPERTY_STYLES
        style = PROPERTY_STYLES[f"Property.ChannelLabel.{ch}::mixed"]
        assert style["color"] == "status_warning"


# ---------------------------------------------------------------------------
# Step 3.1 — Vec2 + Vec4 rows via shared `_VecFloatRow` base class
# ---------------------------------------------------------------------------
# Phase 3's first step generalises the vec3 row into a shared
# ``_VecFloatRow(n_components)`` with thin ``Vec2FloatAttributeRow`` and
# ``Vec4FloatAttributeRow`` subclasses. These tests pin:
#
# * row width (n_components) and channel letters (X/Y | X/Y/Z | X/Y/Z/W);
# * per-component ambiguity flows through from the adapter;
# * the W channel picks up the red ``Property.ChannelLabel.W`` style when
#   clean, and ``Property.ChannelLabel.W::mixed`` (status warning) when
#   ambiguous — proving the axis colour + mixed-state selectors land for
#   the new letter that Vec3 rows never exercised.


class TestVec2FloatAttributeRow:
    """Vec2 row: label + 2× FloatDrag (X, Y)."""

    def test_has_two_widget_slots(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec2FloatAttributeRow
        prop = _make_prop(name="uv", value_type=tuple, type_name="float2")
        adapter = _TrackingAdapter({"uv": (0.25, 0.75)})
        row = Vec2FloatAttributeRow(prop, adapter)
        assert len(row._widgets) == 2
        assert row._channel_letters == ("X", "Y")

    def test_component_change_produces_two_tuple(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec2FloatAttributeRow
        adapter = _TrackingAdapter({"uv": (0.0, 0.0)})
        prop = _make_prop(name="uv", value_type=tuple, type_name="float2")
        row = Vec2FloatAttributeRow(prop, adapter)
        widget_model = _FakeFloatModel(5.0)
        row._on_begin_edit(widget_model)
        row._on_component_changed(widget_model, 1)
        row._on_end_edit(widget_model)
        assert row._model.get_value() == (0.0, 5.0)
        assert adapter.calls == [
            ("begin_edit", "uv"),
            ("set_value", "uv", (0.0, 5.0)),
            ("end_edit", "uv"),
        ]

    def test_default_base_when_current_is_none(self, no_ui):
        """Length-2 default for edits against an empty model (no current value)."""
        from ovui_widgets.property.attribute_row import Vec2FloatAttributeRow
        adapter = _TrackingAdapter({})
        prop = _make_prop(name="uv", value_type=tuple, type_name="float2")
        row = Vec2FloatAttributeRow(prop, adapter)
        row._on_begin_edit(_FakeFloatModel())
        row._on_component_changed(_FakeFloatModel(9.0), 0)
        # Base should be [0.0, 0.0], not [0.0, 0.0, 0.0] — tuple size matches n.
        assert row._model.get_value() == (9.0, 0.0)

    def test_external_change_updates_both_widgets(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec2FloatAttributeRow
        adapter = _TrackingAdapter({"uv": (0.0, 0.0)})
        prop = _make_prop(name="uv", value_type=tuple, type_name="float2")
        row = Vec2FloatAttributeRow(prop, adapter)
        row._widgets = [_FakeFloatWidget(), _FakeFloatWidget()]
        adapter._values["uv"] = (0.5, 0.25)
        adapter.fire_change()
        assert row._widgets[0].model.get_value_as_float() == pytest.approx(0.5)
        assert row._widgets[1].model.get_value_as_float() == pytest.approx(0.25)


class TestVec4FloatAttributeRow:
    """Vec4 row: label + 4× FloatDrag (X, Y, Z, W)."""

    def test_has_four_widget_slots(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec4FloatAttributeRow
        prop = _make_prop(name="q", value_type=tuple, type_name="float4")
        adapter = _TrackingAdapter({"q": (1.0, 2.0, 3.0, 4.0)})
        row = Vec4FloatAttributeRow(prop, adapter)
        assert len(row._widgets) == 4
        assert row._channel_letters == ("X", "Y", "Z", "W")

    def test_component_change_produces_four_tuple(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec4FloatAttributeRow
        adapter = _TrackingAdapter({"q": (0.0, 0.0, 0.0, 0.0)})
        prop = _make_prop(name="q", value_type=tuple, type_name="float4")
        row = Vec4FloatAttributeRow(prop, adapter)
        widget_model = _FakeFloatModel(7.0)
        row._on_begin_edit(widget_model)
        row._on_component_changed(widget_model, 3)  # W
        row._on_end_edit(widget_model)
        assert row._model.get_value() == (0.0, 0.0, 0.0, 7.0)
        assert adapter.calls == [
            ("begin_edit", "q"),
            ("set_value", "q", (0.0, 0.0, 0.0, 7.0)),
            ("end_edit", "q"),
        ]

    def test_default_base_when_current_is_none(self, no_ui):
        """Length-4 default for edits against an empty model (no current value)."""
        from ovui_widgets.property.attribute_row import Vec4FloatAttributeRow
        adapter = _TrackingAdapter({})
        prop = _make_prop(name="q", value_type=tuple, type_name="float4")
        row = Vec4FloatAttributeRow(prop, adapter)
        row._on_begin_edit(_FakeFloatModel())
        row._on_component_changed(_FakeFloatModel(9.0), 3)
        # Base should be [0, 0, 0, 0], not [0, 0, 0] — Step 3.1 regression guard.
        assert row._model.get_value() == (0.0, 0.0, 0.0, 9.0)

    def test_external_change_updates_all_four_widgets(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec4FloatAttributeRow
        adapter = _TrackingAdapter({"q": (0.0, 0.0, 0.0, 0.0)})
        prop = _make_prop(name="q", value_type=tuple, type_name="float4")
        row = Vec4FloatAttributeRow(prop, adapter)
        row._widgets = [_FakeFloatWidget() for _ in range(4)]
        adapter._values["q"] = (0.1, 0.2, 0.3, 0.4)
        adapter.fire_change()
        expected = (0.1, 0.2, 0.3, 0.4)
        for i, widget in enumerate(row._widgets):
            assert widget.model.get_value_as_float() == pytest.approx(expected[i])


class TestVecFloatRowSharedBase:
    """The ``_VecFloatRow`` base class drives all three dimensions."""

    def test_vec_classes_inherit_base(self):
        from ovui_widgets.property.attribute_row import (
            Vec2FloatAttributeRow,
            Vec3FloatAttributeRow,
            Vec4FloatAttributeRow,
            _VecFloatRow,
        )
        for cls in (Vec2FloatAttributeRow, Vec3FloatAttributeRow, Vec4FloatAttributeRow):
            assert issubclass(cls, _VecFloatRow)

    def test_base_rejects_out_of_range_n_components(self, no_ui):
        """Guardrail: only 2, 3, 4 are supported; 1 or 5 would mean the builder
        table wired a type name to the wrong row class."""
        from ovui_widgets.property.attribute_row import _VecFloatRow
        adapter = _TrackingAdapter({"x": (1.0,)})
        prop = _make_prop(name="x", value_type=tuple, type_name="float")
        with pytest.raises(ValueError, match="n_components"):
            _VecFloatRow(prop, adapter, n_components=1)
        with pytest.raises(ValueError, match="n_components"):
            _VecFloatRow(prop, adapter, n_components=5)


class TestVec2ChannelColorCoding:
    """Vec2 rows wire each channel label to the property attribute builder behavior axis colour."""

    def _build(self, window_name, values=(0.25, 0.75)):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import Vec2FloatAttributeRow
        prop = _make_prop(name="uv", value_type=tuple, type_name="float2")
        adapter = MockPropertyAdapter(paths=["/P1"], attributes={"uv": prop})
        adapter.set_path_value("/P1", "uv", values)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return Vec2FloatAttributeRow(prop, adapter)

    def test_labels_use_x_y_channel_styles(self):
        row = self._build("test_vec2_channel_color_base")
        styles = [lbl.style_type_name_override for lbl in row._channel_labels]
        assert styles == ["Property.ChannelLabel.X", "Property.ChannelLabel.Y"]

    def test_label_texts_match_axes(self):
        row = self._build("test_vec2_channel_color_text")
        assert [lbl.text for lbl in row._channel_labels] == ["X", "Y"]


class TestVec4ChannelColorCoding:
    """Vec4 rows wire each channel label including W (red)."""

    def _build(self, window_name, values=(0.1, 0.2, 0.3, 0.4)):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import Vec4FloatAttributeRow
        prop = _make_prop(name="q", value_type=tuple, type_name="float4")
        adapter = MockPropertyAdapter(paths=["/P1"], attributes={"q": prop})
        adapter.set_path_value("/P1", "q", values)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return Vec4FloatAttributeRow(prop, adapter)

    def test_labels_use_all_four_channel_styles(self):
        row = self._build("test_vec4_channel_color_base")
        styles = [lbl.style_type_name_override for lbl in row._channel_labels]
        assert styles == [
            "Property.ChannelLabel.X",
            "Property.ChannelLabel.Y",
            "Property.ChannelLabel.Z",
            "Property.ChannelLabel.W",
        ]

    def test_w_channel_uses_channel_w_style(self):
        """Regression guard: W must resolve ``Property.ChannelLabel.W`` (red,
        property attribute builder behavior). Defined in Step 2.5 but never wired by any row until 3.1.
        """
        row = self._build("test_vec4_w_channel_color")
        assert row._channel_labels[3].style_type_name_override == "Property.ChannelLabel.W"
        assert row._channel_labels[3].text == "W"

    def test_label_texts_match_axes(self):
        row = self._build("test_vec4_channel_color_text")
        assert [lbl.text for lbl in row._channel_labels] == ["X", "Y", "Z", "W"]

    def test_w_channel_red_palette_resolves(self):
        """End-to-end: the ``Property.ChannelLabel.W`` style references the
        ``channel_w`` palette shade, which resolves to the property attribute builder behavior red."""
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert PROPERTY_STYLES["Property.ChannelLabel.W"]["color"] == "channel_w"


class TestVec2PerComponentAmbiguity:
    """Vec2 rows honour the per-component ambiguity contract."""

    def _build(self, window_name, per_path_values):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import Vec2FloatAttributeRow
        prop = _make_prop(name="uv", value_type=tuple, type_name="float2")
        adapter = MockPropertyAdapter(
            paths=[p for p, _ in per_path_values],
            attributes={"uv": prop},
        )
        for path, value in per_path_values:
            adapter.set_path_value(path, "uv", value)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return Vec2FloatAttributeRow(prop, adapter)

    def test_only_y_differs_marks_y_only(self):
        row = self._build(
            "test_vec2_only_y",
            [("/P1", (0.5, 0.5)), ("/P2", (0.5, 0.9))],
        )
        names = [lbl.name for lbl in row._channel_labels]
        assert names == ["", "mixed"]
        vis = [o.visible for o in row._overlay_labels]
        assert vis == [False, True]

    def test_all_equal_no_channels_marked(self):
        row = self._build(
            "test_vec2_all_equal",
            [("/P1", (0.5, 0.5)), ("/P2", (0.5, 0.5))],
        )
        assert [lbl.name for lbl in row._channel_labels] == ["", ""]
        assert [o.visible for o in row._overlay_labels] == [False, False]


class TestVec4PerComponentAmbiguity:
    """Vec4 rows honour the per-component ambiguity contract, including W."""

    def _build(self, window_name, per_path_values):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import Vec4FloatAttributeRow
        prop = _make_prop(name="q", value_type=tuple, type_name="float4")
        adapter = MockPropertyAdapter(
            paths=[p for p, _ in per_path_values],
            attributes={"q": prop},
        )
        for path, value in per_path_values:
            adapter.set_path_value(path, "q", value)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return Vec4FloatAttributeRow(prop, adapter)

    def test_only_w_differs_marks_w_only(self):
        """W-only mixed: pins that the ambiguity list's fourth element maps to
        the fourth widget / fourth overlay — not silently dropped the way it
        would if the row copy-pasted ``[None, None, None]`` from vec3."""
        row = self._build(
            "test_vec4_only_w",
            [("/P1", (0.0, 0.0, 0.0, 0.0)), ("/P2", (0.0, 0.0, 0.0, 1.0))],
        )
        assert [lbl.name for lbl in row._channel_labels] == ["", "", "", "mixed"]
        assert [o.visible for o in row._overlay_labels] == [False, False, False, True]

    def test_all_four_differ_all_marked(self):
        row = self._build(
            "test_vec4_all_differ",
            [
                ("/P1", (0.0, 0.0, 0.0, 0.0)),
                ("/P2", (1.0, 1.0, 1.0, 1.0)),
            ],
        )
        assert [lbl.name for lbl in row._channel_labels] == ["mixed"] * 4
        assert [o.visible for o in row._overlay_labels] == [True] * 4

    def test_w_channel_mixed_keeps_channel_w_base(self):
        """Step 2.3 ``::mixed`` overrides only the colour; the per-axis base
        type stays ``Property.ChannelLabel.W`` — otherwise the warning colour
        would apply universally instead of being axis-scoped."""
        row = self._build(
            "test_vec4_w_mixed_keeps_base",
            [("/P1", (0.0, 0.0, 0.0, 0.0)), ("/P2", (0.0, 0.0, 0.0, 1.0))],
        )
        assert row._channel_labels[3].style_type_name_override == "Property.ChannelLabel.W"
        assert row._channel_labels[3].name == "mixed"


# ---------------------------------------------------------------------------
# Step 3.2 — Int vector rows (int2 / int3 / int4) via shared ``_VecIntRow``
# ---------------------------------------------------------------------------
# Parallels Step 3.1's float-vec tests: row width, component-change output
# tuple shape (integer values, integer length), default base handling,
# external-change propagation, channel colour coding, and per-component
# ambiguity. IntDrag vs FloatDrag is the only behavioural axis that differs
# from the Vec*FloatAttributeRow shape.


class TestVec2IntAttributeRow:
    """Vec2 integer row: label + 2× IntDrag (X, Y)."""

    def test_has_two_widget_slots(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec2IntAttributeRow
        prop = _make_prop(name="size", value_type=tuple, type_name="int2")
        adapter = _TrackingAdapter({"size": (4, 8)})
        row = Vec2IntAttributeRow(prop, adapter)
        assert len(row._widgets) == 2
        assert row._channel_letters == ("X", "Y")

    def test_component_change_produces_two_tuple_of_ints(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec2IntAttributeRow
        adapter = _TrackingAdapter({"size": (0, 0)})
        prop = _make_prop(name="size", value_type=tuple, type_name="int2")
        row = Vec2IntAttributeRow(prop, adapter)
        widget_model = _FakeIntModel(5)
        row._on_begin_edit(widget_model)
        row._on_component_changed(widget_model, 1)
        row._on_end_edit(widget_model)
        assert row._model.get_value() == (0, 5)
        # Every element of the produced tuple must be ``int``, not ``float``.
        for v in row._model.get_value():
            assert isinstance(v, int) and not isinstance(v, bool)
        assert adapter.calls == [
            ("begin_edit", "size"),
            ("set_value", "size", (0, 5)),
            ("end_edit", "size"),
        ]

    def test_default_base_when_current_is_none(self, no_ui):
        """Length-2 integer default for edits against an empty model."""
        from ovui_widgets.property.attribute_row import Vec2IntAttributeRow
        adapter = _TrackingAdapter({})
        prop = _make_prop(name="size", value_type=tuple, type_name="int2")
        row = Vec2IntAttributeRow(prop, adapter)
        row._on_begin_edit(_FakeIntModel())
        row._on_component_changed(_FakeIntModel(9), 0)
        # Base should be [0, 0] — ints, length 2.
        assert row._model.get_value() == (9, 0)
        for v in row._model.get_value():
            assert isinstance(v, int) and not isinstance(v, bool)

    def test_external_change_updates_both_widgets(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec2IntAttributeRow
        adapter = _TrackingAdapter({"size": (0, 0)})
        prop = _make_prop(name="size", value_type=tuple, type_name="int2")
        row = Vec2IntAttributeRow(prop, adapter)
        row._widgets = [_FakeIntWidget(), _FakeIntWidget()]
        adapter._values["size"] = (3, 7)
        adapter.fire_change()
        assert row._widgets[0].model.get_value_as_int() == 3
        assert row._widgets[1].model.get_value_as_int() == 7


class TestVec3IntAttributeRow:
    """Vec3 integer row: label + 3× IntDrag (X, Y, Z)."""

    def test_has_three_widget_slots(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3IntAttributeRow
        prop = _make_prop(name="grid", value_type=tuple, type_name="int3")
        adapter = _TrackingAdapter({"grid": (4, 8, 16)})
        row = Vec3IntAttributeRow(prop, adapter)
        assert len(row._widgets) == 3
        assert row._channel_letters == ("X", "Y", "Z")

    def test_component_change_produces_three_tuple_of_ints(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3IntAttributeRow
        adapter = _TrackingAdapter({"grid": (0, 0, 0)})
        prop = _make_prop(name="grid", value_type=tuple, type_name="int3")
        row = Vec3IntAttributeRow(prop, adapter)
        widget_model = _FakeIntModel(5)
        row._on_begin_edit(widget_model)
        row._on_component_changed(widget_model, 2)
        row._on_end_edit(widget_model)
        assert row._model.get_value() == (0, 0, 5)
        for v in row._model.get_value():
            assert isinstance(v, int) and not isinstance(v, bool)


class TestVec4IntAttributeRow:
    """Vec4 integer row: label + 4× IntDrag (X, Y, Z, W)."""

    def test_has_four_widget_slots(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec4IntAttributeRow
        prop = _make_prop(name="box", value_type=tuple, type_name="int4")
        adapter = _TrackingAdapter({"box": (1, 2, 3, 4)})
        row = Vec4IntAttributeRow(prop, adapter)
        assert len(row._widgets) == 4
        assert row._channel_letters == ("X", "Y", "Z", "W")

    def test_component_change_produces_four_tuple_of_ints(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec4IntAttributeRow
        adapter = _TrackingAdapter({"box": (0, 0, 0, 0)})
        prop = _make_prop(name="box", value_type=tuple, type_name="int4")
        row = Vec4IntAttributeRow(prop, adapter)
        widget_model = _FakeIntModel(7)
        row._on_begin_edit(widget_model)
        row._on_component_changed(widget_model, 3)  # W
        row._on_end_edit(widget_model)
        assert row._model.get_value() == (0, 0, 0, 7)
        for v in row._model.get_value():
            assert isinstance(v, int) and not isinstance(v, bool)
        assert adapter.calls == [
            ("begin_edit", "box"),
            ("set_value", "box", (0, 0, 0, 7)),
            ("end_edit", "box"),
        ]

    def test_default_base_when_current_is_none(self, no_ui):
        """Length-4 integer default for edits against an empty model."""
        from ovui_widgets.property.attribute_row import Vec4IntAttributeRow
        adapter = _TrackingAdapter({})
        prop = _make_prop(name="box", value_type=tuple, type_name="int4")
        row = Vec4IntAttributeRow(prop, adapter)
        row._on_begin_edit(_FakeIntModel())
        row._on_component_changed(_FakeIntModel(9), 3)
        assert row._model.get_value() == (0, 0, 0, 9)

    def test_external_change_updates_all_four_widgets(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec4IntAttributeRow
        adapter = _TrackingAdapter({"box": (0, 0, 0, 0)})
        prop = _make_prop(name="box", value_type=tuple, type_name="int4")
        row = Vec4IntAttributeRow(prop, adapter)
        row._widgets = [_FakeIntWidget() for _ in range(4)]
        adapter._values["box"] = (11, 22, 33, 44)
        adapter.fire_change()
        expected = (11, 22, 33, 44)
        for i, widget in enumerate(row._widgets):
            assert widget.model.get_value_as_int() == expected[i]


class TestVecIntRowSharedBase:
    """The ``_VecIntRow`` base class drives all three integer dimensions."""

    def test_int_vec_classes_inherit_base(self):
        from ovui_widgets.property.attribute_row import (
            Vec2IntAttributeRow,
            Vec3IntAttributeRow,
            Vec4IntAttributeRow,
            _VecIntRow,
        )
        for cls in (Vec2IntAttributeRow, Vec3IntAttributeRow, Vec4IntAttributeRow):
            assert issubclass(cls, _VecIntRow)

    def test_int_and_float_bases_are_siblings(self):
        """``_VecIntRow`` and ``_VecFloatRow`` share the channel-letters
        constant but are independent class hierarchies — no cross-inheritance.
        """
        from ovui_widgets.property.attribute_row import (
            Vec3FloatAttributeRow,
            Vec3IntAttributeRow,
            _VecFloatRow,
            _VecIntRow,
        )
        assert not issubclass(_VecIntRow, _VecFloatRow)
        assert not issubclass(_VecFloatRow, _VecIntRow)
        assert not issubclass(Vec3IntAttributeRow, _VecFloatRow)
        assert not issubclass(Vec3FloatAttributeRow, _VecIntRow)

    def test_base_rejects_out_of_range_n_components(self, no_ui):
        """Guardrail: only 2, 3, 4 are supported; 1 or 5 would mean the
        builder table wired a type name to the wrong row class."""
        from ovui_widgets.property.attribute_row import _VecIntRow
        adapter = _TrackingAdapter({"x": (1,)})
        prop = _make_prop(name="x", value_type=tuple, type_name="int")
        with pytest.raises(ValueError, match="n_components"):
            _VecIntRow(prop, adapter, n_components=1)
        with pytest.raises(ValueError, match="n_components"):
            _VecIntRow(prop, adapter, n_components=5)


class TestVec2IntChannelColorCoding:
    """Vec2 int rows wire each channel label to the property attribute builder behavior axis colour."""

    def _build(self, window_name, values=(3, 7)):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import Vec2IntAttributeRow
        prop = _make_prop(name="size", value_type=tuple, type_name="int2")
        adapter = MockPropertyAdapter(paths=["/P1"], attributes={"size": prop})
        adapter.set_path_value("/P1", "size", values)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return Vec2IntAttributeRow(prop, adapter)

    def test_labels_use_x_y_channel_styles(self):
        row = self._build("test_ivec2_channel_color_base")
        styles = [lbl.style_type_name_override for lbl in row._channel_labels]
        assert styles == ["Property.ChannelLabel.X", "Property.ChannelLabel.Y"]

    def test_label_texts_match_axes(self):
        row = self._build("test_ivec2_channel_color_text")
        assert [lbl.text for lbl in row._channel_labels] == ["X", "Y"]


class TestVec3IntChannelColorCoding:
    """Vec3 int rows wire each channel label to the property attribute builder behavior axis colour."""

    def _build(self, window_name, values=(1, 2, 3)):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import Vec3IntAttributeRow
        prop = _make_prop(name="grid", value_type=tuple, type_name="int3")
        adapter = MockPropertyAdapter(paths=["/P1"], attributes={"grid": prop})
        adapter.set_path_value("/P1", "grid", values)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return Vec3IntAttributeRow(prop, adapter)

    def test_labels_use_all_three_channel_styles(self):
        row = self._build("test_ivec3_channel_color_base")
        styles = [lbl.style_type_name_override for lbl in row._channel_labels]
        assert styles == [
            "Property.ChannelLabel.X",
            "Property.ChannelLabel.Y",
            "Property.ChannelLabel.Z",
        ]


class TestVec4IntChannelColorCoding:
    """Vec4 int rows wire every channel label including W (red)."""

    def _build(self, window_name, values=(1, 2, 3, 4)):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import Vec4IntAttributeRow
        prop = _make_prop(name="box", value_type=tuple, type_name="int4")
        adapter = MockPropertyAdapter(paths=["/P1"], attributes={"box": prop})
        adapter.set_path_value("/P1", "box", values)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return Vec4IntAttributeRow(prop, adapter)

    def test_labels_use_all_four_channel_styles(self):
        row = self._build("test_ivec4_channel_color_base")
        styles = [lbl.style_type_name_override for lbl in row._channel_labels]
        assert styles == [
            "Property.ChannelLabel.X",
            "Property.ChannelLabel.Y",
            "Property.ChannelLabel.Z",
            "Property.ChannelLabel.W",
        ]

    def test_label_texts_match_axes(self):
        row = self._build("test_ivec4_channel_color_text")
        assert [lbl.text for lbl in row._channel_labels] == ["X", "Y", "Z", "W"]


class TestVec2IntPerComponentAmbiguity:
    """Vec2 int rows honour the per-component ambiguity contract."""

    def _build(self, window_name, per_path_values):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import Vec2IntAttributeRow
        prop = _make_prop(name="size", value_type=tuple, type_name="int2")
        adapter = MockPropertyAdapter(
            paths=[p for p, _ in per_path_values],
            attributes={"size": prop},
        )
        for path, value in per_path_values:
            adapter.set_path_value(path, "size", value)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return Vec2IntAttributeRow(prop, adapter)

    def test_only_y_differs_marks_y_only(self):
        row = self._build(
            "test_ivec2_only_y",
            [("/P1", (4, 8)), ("/P2", (4, 16))],
        )
        names = [lbl.name for lbl in row._channel_labels]
        assert names == ["", "mixed"]
        assert [o.visible for o in row._overlay_labels] == [False, True]


class TestVec4IntPerComponentAmbiguity:
    """Vec4 int rows honour per-component ambiguity, including W."""

    def _build(self, window_name, per_path_values):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import Vec4IntAttributeRow
        prop = _make_prop(name="box", value_type=tuple, type_name="int4")
        adapter = MockPropertyAdapter(
            paths=[p for p, _ in per_path_values],
            attributes={"box": prop},
        )
        for path, value in per_path_values:
            adapter.set_path_value(path, "box", value)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return Vec4IntAttributeRow(prop, adapter)

    def test_only_w_differs_marks_w_only(self):
        """W-only mixed: pins the ambiguity list's fourth element maps to
        the fourth widget / fourth overlay on the int row path."""
        row = self._build(
            "test_ivec4_only_w",
            [("/P1", (0, 0, 0, 0)), ("/P2", (0, 0, 0, 1))],
        )
        assert [lbl.name for lbl in row._channel_labels] == ["", "", "", "mixed"]
        assert [o.visible for o in row._overlay_labels] == [False, False, False, True]

    def test_all_four_differ_all_marked(self):
        row = self._build(
            "test_ivec4_all_differ",
            [("/P1", (0, 0, 0, 0)), ("/P2", (1, 2, 3, 4))],
        )
        assert [lbl.name for lbl in row._channel_labels] == ["mixed"] * 4
        assert [o.visible for o in row._overlay_labels] == [True] * 4

    def test_w_channel_mixed_keeps_channel_w_base(self):
        """``::mixed`` overrides only the colour; per-axis base type stays
        ``Property.ChannelLabel.W`` on the int row path too."""
        row = self._build(
            "test_ivec4_w_mixed_keeps_base",
            [("/P1", (0, 0, 0, 0)), ("/P2", (0, 0, 0, 1))],
        )
        assert row._channel_labels[3].style_type_name_override == "Property.ChannelLabel.W"
        assert row._channel_labels[3].name == "mixed"


# ---------------------------------------------------------------------------
# TokenAttributeRow — Step 3.3 (ComboBox when allowed_values set)
# ---------------------------------------------------------------------------


class _FakeComboBoxRootModel:
    """Stand-in for ``ui.ComboBox``'s root ``SimpleIntModel`` (the
    ``get_item_value_model(None)`` result)."""

    def __init__(self, value: int = 0) -> None:
        self._value = int(value)

    def get_value_as_int(self) -> int:
        return self._value

    def set_value(self, v: Any) -> None:
        self._value = int(v)


class _FakeComboBoxItemModel:
    """Stand-in for ``ui.ComboBox``'s ``AbstractItemModel``.

    Wraps a root ``_FakeComboBoxRootModel``; ``get_item_value_model(None)``
    returns that root, matching the real omni.ui API shape used by
    :class:`TokenAttributeRow._on_item_changed`.
    """

    def __init__(self, index: int = 0) -> None:
        self._root = _FakeComboBoxRootModel(index)

    def get_item_value_model(self, item: Any) -> _FakeComboBoxRootModel:
        return self._root


class _FakeComboBoxWidget:
    def __init__(self, index: int = 0) -> None:
        self.model = _FakeComboBoxItemModel(index)


class TestTokenAttributeRowConstruction:
    """ComboBox path: ``allowed_values`` set → ``TokenAttributeRow`` builds
    against the allowed list, seeds index from the current adapter value.
    """

    def test_row_constructs_model(self, no_ui):
        from ovui_widgets.property.attribute_row import TokenAttributeRow
        from ovui_widgets.property.models import AttributeModelBase
        adapter = _TrackingAdapter({"vis": "inherited"})
        prop = _make_prop(
            name="vis", value_type=str, type_name="token",
        )
        prop.allowed_values = ["inherited", "invisible"]
        row = TokenAttributeRow(prop, adapter)
        assert isinstance(row._model, AttributeModelBase)

    def test_row_stores_allowed_values(self, no_ui):
        from ovui_widgets.property.attribute_row import TokenAttributeRow
        adapter = _TrackingAdapter({"vis": "inherited"})
        prop = _make_prop(name="vis", value_type=str, type_name="token")
        prop.allowed_values = ["inherited", "invisible"]
        row = TokenAttributeRow(prop, adapter)
        assert row._allowed_values == ["inherited", "invisible"]

    def test_row_subscribes_adapter_changes(self, no_ui):
        from ovui_widgets.property.attribute_row import TokenAttributeRow
        adapter = _TrackingAdapter({"vis": "inherited"})
        prop = _make_prop(name="vis", value_type=str, type_name="token")
        prop.allowed_values = ["inherited", "invisible"]
        TokenAttributeRow(prop, adapter)
        assert len(adapter._subscribers) == 1

    def test_model_seeded_with_adapter_value(self, no_ui):
        from ovui_widgets.property.attribute_row import TokenAttributeRow
        adapter = _TrackingAdapter({"vis": "invisible"})
        prop = _make_prop(name="vis", value_type=str, type_name="token")
        prop.allowed_values = ["inherited", "invisible"]
        row = TokenAttributeRow(prop, adapter)
        assert row._model.get_value() == "invisible"

    def test_combobox_chevron_overlay_uses_shared_two_line_asset(self, monkeypatch):
        from ovui_widgets.property import attribute_row as row_mod

        containers = []
        rectangles = []
        images = []

        class _FakeWidget:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs
                self.opaque_for_mouse_events = True

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def _rectangle(*args, **kwargs):
            widget = _FakeWidget(*args, **kwargs)
            rectangles.append(widget)
            return widget

        def _image(*args, **kwargs):
            widget = _FakeWidget(*args, **kwargs)
            images.append(widget)
            return widget

        def _container(**kwargs):
            widget = _FakeWidget(**kwargs)
            containers.append(widget)
            return widget

        monkeypatch.setattr(row_mod.ui, "HStack", _container)
        monkeypatch.setattr(row_mod.ui, "VStack", _container)
        monkeypatch.setattr(row_mod.ui, "ZStack", _container)
        monkeypatch.setattr(row_mod.ui, "Spacer", lambda **kwargs: None)
        monkeypatch.setattr(row_mod.ui, "Rectangle", _rectangle)
        monkeypatch.setattr(row_mod.ui, "ImageWithProvider", _image)
        monkeypatch.setattr(row_mod, "provider", lambda path: path)

        row_mod._build_combobox_chevron_overlay()

        assert len(containers) == 4
        assert all(c.opaque_for_mouse_events is False for c in containers)
        assert rectangles == []
        chevron = images[-1]
        assert chevron.args == (row_mod._CHEVRON_DOWN,)
        assert chevron.kwargs["style_type_name_override"] == "Property.ComboBoxChevron"
        assert chevron.kwargs["width"] == row_mod._COMBOBOX_CHEVRON_SIZE == 9
        assert chevron.kwargs["height"] == row_mod._COMBOBOX_CHEVRON_SIZE == 9
        assert chevron.opaque_for_mouse_events is False


class TestTokenAttributeRowCurrentIndex:
    """``_current_index`` maps the current adapter value to its position in
    the allowed list; falls back to 0 for None, ambiguous, or off-list
    values (Kit's ``TfTokenAttributeModel`` convention)."""

    def _row(self, allowed, initial):
        from ovui_widgets.property.attribute_row import TokenAttributeRow
        adapter = _TrackingAdapter({"vis": initial} if initial is not None else {})
        prop = _make_prop(name="vis", value_type=str, type_name="token")
        prop.allowed_values = list(allowed)
        return TokenAttributeRow(prop, adapter), adapter

    def test_picks_correct_index_for_first(self, no_ui):
        row, _ = self._row(["inherited", "invisible"], "inherited")
        assert row._current_index() == 0

    def test_picks_correct_index_for_second(self, no_ui):
        row, _ = self._row(["inherited", "invisible"], "invisible")
        assert row._current_index() == 1

    def test_picks_correct_index_for_middle(self, no_ui):
        row, _ = self._row(["default", "render", "proxy", "guide"], "proxy")
        assert row._current_index() == 2

    def test_falls_back_to_zero_when_value_none(self, no_ui):
        row, _ = self._row(["inherited", "invisible"], None)
        assert row._current_index() == 0

    def test_falls_back_to_zero_when_value_unknown(self, no_ui):
        row, _ = self._row(["inherited", "invisible"], "neither")
        assert row._current_index() == 0


class TestTokenAttributeRowEdit:
    """ComboBox selection change routes through begin_edit → set_value →
    end_edit in one atomic burst (no drag)."""

    def _row(self, allowed=("a", "b", "c"), initial="a"):
        from ovui_widgets.property.attribute_row import TokenAttributeRow
        adapter = _TrackingAdapter({"t": initial})
        prop = _make_prop(name="t", value_type=str, type_name="token")
        prop.allowed_values = list(allowed)
        return TokenAttributeRow(prop, adapter), adapter

    def test_selection_change_writes_new_token(self, no_ui):
        row, adapter = self._row()
        widget_model = _FakeComboBoxItemModel(1)  # selected index 1 → "b"
        row._on_item_changed(widget_model, None)
        assert adapter.calls == [
            ("begin_edit", "t"),
            ("set_value", "t", "b"),
            ("end_edit", "t"),
        ]

    def test_item_non_none_is_ignored(self, no_ui):
        """Per-item model fires (static strings) must NOT commit a write."""
        row, adapter = self._row()
        widget_model = _FakeComboBoxItemModel(2)
        row._on_item_changed(widget_model, object())  # non-None item
        assert adapter.calls == []

    def test_selecting_current_value_skips_write(self, no_ui):
        """Spurious re-fire for the already-selected index must not emit a
        no-op edit (matches FloatAttributeRow's no-op-skip semantics)."""
        row, adapter = self._row(initial="b")
        widget_model = _FakeComboBoxItemModel(1)  # same as current
        row._on_item_changed(widget_model, None)
        assert adapter.calls == []

    def test_out_of_range_index_is_ignored(self, no_ui):
        row, adapter = self._row()
        widget_model = _FakeComboBoxItemModel(99)
        row._on_item_changed(widget_model, None)
        assert adapter.calls == []


class TestTokenAttributeRowExternalChange:
    """External adapter changes push a new selected index into the
    ComboBox root model (same backing-change path every row has)."""

    def _row(self, allowed=("a", "b", "c"), initial="a"):
        from ovui_widgets.property.attribute_row import TokenAttributeRow
        adapter = _TrackingAdapter({"t": initial})
        prop = _make_prop(name="t", value_type=str, type_name="token")
        prop.allowed_values = list(allowed)
        return TokenAttributeRow(prop, adapter), adapter

    def test_external_change_updates_widget_index(self, no_ui):
        row, adapter = self._row(initial="a")
        row._widget = _FakeComboBoxWidget(index=0)
        adapter._values["t"] = "c"
        adapter.fire_change()
        assert row._widget.model.get_item_value_model(None).get_value_as_int() == 2

    def test_external_change_unknown_value_keeps_index(self, no_ui):
        row, adapter = self._row(initial="a")
        row._widget = _FakeComboBoxWidget(index=0)
        adapter._values["t"] = "something_not_in_allowed"
        adapter.fire_change()
        # Off-list value leaves the index untouched (vs clobbering to 0)
        # so the user sees the stale-but-best-effort display instead of
        # a silent jump to the first option.
        assert row._widget.model.get_item_value_model(None).get_value_as_int() == 0

    def test_external_change_suppressed_during_edit(self, no_ui):
        row, adapter = self._row(initial="a")
        row._widget = _FakeComboBoxWidget(index=0)
        row._model.begin_edit()
        adapter._values["t"] = "c"
        adapter.fire_change()
        # Mid-edit: backing change is dropped until end_edit.
        assert row._widget.model.get_item_value_model(None).get_value_as_int() == 0

    def test_feedback_loop_guard_blocks_recursion(self, no_ui):
        """Reentrant widget set_value → _on_item_changed must not loop.

        Same guard shape as FloatAttributeRow's: without ``_updating``,
        the chain would be ``_on_model_value_changed → widget.set_value
        → _on_item_changed → model.set_value → _notify_value_changed →
        _on_model_value_changed``.
        """
        from ovui_widgets.property.attribute_row import TokenAttributeRow
        adapter = _TrackingAdapter({"t": "a"})
        prop = _make_prop(name="t", value_type=str, type_name="token")
        prop.allowed_values = ["a", "b", "c"]
        row = TokenAttributeRow(prop, adapter)

        class _ReentrantComboWidget:
            def __init__(self, outer_row):
                self._row = outer_row
                self.model = _FakeComboBoxItemModel(0)
                root = self.model.get_item_value_model(None)
                base_set = root.set_value

                def _set(v):
                    base_set(v)
                    self._row._on_item_changed(self.model, None)
                root.set_value = _set

        row._widget = _ReentrantComboWidget(row)
        adapter._values["t"] = "c"
        adapter.fire_change()
        # Recursion guard kept us sane; index still lands on 2.
        assert row._widget.model.get_item_value_model(None).get_value_as_int() == 2


# ---------------------------------------------------------------------------
# Step 3.4 — Color3f / Color4f rows with swatch preview
# ---------------------------------------------------------------------------
# Step 3.4 adds ``Color3fAttributeRow`` / ``Color4fAttributeRow`` —
# subclasses of ``_VecFloatRow`` that relabel the channels R/G/B(/A) and
# append a ``ui.Rectangle`` swatch whose ``background_color`` tracks the
# current value. The tests below pin:
#
# * channel letters and widget counts for both widths;
# * the ``_pack_color_abgr`` helper's byte-order (ABGR on the wire);
# * swatch presence + initial style dict + live update on ``set_value``
#   (the explicit property-array done signal);
# * per-component ambiguity still works through the inherited base;
# * the X/Y/Z/W axis palette is reused for the R/G/B/A labels, so no
#   new channel colours are needed.


class _FakeRectangle:
    """Stand-in for ``ui.Rectangle`` — exposes ``style`` for swatch tests."""

    def __init__(self, style=None):
        self.style = dict(style) if style else {}


class TestPackColorAbgr:
    """``_pack_color_abgr`` — byte-order pinning against omni.ui's int layout.

    omni.ui packs colour ints as ``0xAABBGGRR`` (A high, R low). Empirically
    confirmed: ``cl(1.0, 0.0, 0.0)`` → ``0xFF0000FF``. These tests lock in
    that pinning so a future refactor can't silently swap to ARGB.
    """

    def test_pure_red(self):
        from ovui_widgets.property.attribute_row import _pack_color_abgr
        assert _pack_color_abgr((1.0, 0.0, 0.0), 3) == 0xFF0000FF

    def test_pure_green(self):
        from ovui_widgets.property.attribute_row import _pack_color_abgr
        assert _pack_color_abgr((0.0, 1.0, 0.0), 3) == 0xFF00FF00

    def test_pure_blue(self):
        from ovui_widgets.property.attribute_row import _pack_color_abgr
        assert _pack_color_abgr((0.0, 0.0, 1.0), 3) == 0xFFFF0000

    def test_color3_default_opaque_alpha(self):
        """color3f has no alpha channel; packer defaults it to 0xFF (opaque)."""
        from ovui_widgets.property.attribute_row import _pack_color_abgr
        packed = _pack_color_abgr((0.5, 0.5, 0.5), 3)
        assert (packed >> 24) & 0xFF == 0xFF

    def test_color4_packs_alpha(self):
        from ovui_widgets.property.attribute_row import _pack_color_abgr
        # alpha=0.5 → ~0x80 in the high byte
        packed = _pack_color_abgr((1.0, 0.0, 0.0, 0.5), 4)
        alpha_byte = (packed >> 24) & 0xFF
        assert alpha_byte == 128  # round(0.5 * 255)

    def test_none_value_packs_opaque_black(self):
        """None value on a color3 row: packer falls back to ``(0,0,0)`` + A=1."""
        from ovui_widgets.property.attribute_row import _pack_color_abgr
        assert _pack_color_abgr(None, 3) == 0xFF000000

    def test_out_of_range_clamps(self):
        """Values outside [0.0, 1.0] clamp — HDR colours (>1.0) don't wrap."""
        from ovui_widgets.property.attribute_row import _pack_color_abgr
        # 2.0 red would wrap to byte 0x01 if not clamped.
        assert _pack_color_abgr((2.0, -1.0, 0.5), 3) == 0xFF800000 + 0xFF  # R=FF, G=00, B=80, A=FF


class TestColor3fAttributeRow:
    """Color3f row: label + 3× FloatDrag (R, G, B) + swatch."""

    def test_has_three_widget_slots(self, no_ui):
        from ovui_widgets.property.attribute_row import Color3fAttributeRow
        prop = _make_prop(name="col", value_type=tuple, type_name="color3f")
        adapter = _TrackingAdapter({"col": (0.5, 0.25, 0.125)})
        row = Color3fAttributeRow(prop, adapter)
        assert len(row._widgets) == 3

    def test_channel_letters_are_rgb(self, no_ui):
        """R/G/B (not X/Y/Z) — pins the Step 3.4 relabelling."""
        from ovui_widgets.property.attribute_row import Color3fAttributeRow
        prop = _make_prop(name="col", value_type=tuple, type_name="color3f")
        adapter = _TrackingAdapter({"col": (0.5, 0.25, 0.125)})
        row = Color3fAttributeRow(prop, adapter)
        assert row._channel_letters == ("R", "G", "B")

    def test_component_change_produces_three_tuple(self, no_ui):
        from ovui_widgets.property.attribute_row import Color3fAttributeRow
        adapter = _TrackingAdapter({"col": (0.0, 0.0, 0.0)})
        prop = _make_prop(name="col", value_type=tuple, type_name="color3f")
        row = Color3fAttributeRow(prop, adapter)
        widget_model = _FakeFloatModel(0.75)
        row._on_begin_edit(widget_model)
        row._on_component_changed(widget_model, 1)  # G
        row._on_end_edit(widget_model)
        assert row._model.get_value() == (0.0, 0.75, 0.0)

    def test_external_change_updates_all_widgets(self, no_ui):
        from ovui_widgets.property.attribute_row import Color3fAttributeRow
        adapter = _TrackingAdapter({"col": (0.0, 0.0, 0.0)})
        prop = _make_prop(name="col", value_type=tuple, type_name="color3f")
        row = Color3fAttributeRow(prop, adapter)
        row._widgets = [_FakeFloatWidget(), _FakeFloatWidget(), _FakeFloatWidget()]
        adapter._values["col"] = (0.9, 0.4, 0.1)
        adapter.fire_change()
        assert row._widgets[0].model.get_value_as_float() == pytest.approx(0.9)
        assert row._widgets[1].model.get_value_as_float() == pytest.approx(0.4)
        assert row._widgets[2].model.get_value_as_float() == pytest.approx(0.1)

    def test_rejects_invalid_n_components(self, no_ui):
        """The shared ``_ColorFloatRow`` guardrail rejects widths outside
        {3, 4} — vec2 and vec5 would indicate a wiring mistake between the
        builder and the row class."""
        from ovui_widgets.property.attribute_row import _ColorFloatRow
        adapter = _TrackingAdapter({})
        prop = _make_prop(name="col", value_type=tuple, type_name="color3f")
        with pytest.raises(ValueError, match="n_components"):
            _ColorFloatRow(prop, adapter, n_components=2)
        with pytest.raises(ValueError, match="n_components"):
            _ColorFloatRow(prop, adapter, n_components=5)


class TestColor4fAttributeRow:
    """Color4f row: label + 4× FloatDrag (R, G, B, A) + swatch."""

    def test_has_four_widget_slots(self, no_ui):
        from ovui_widgets.property.attribute_row import Color4fAttributeRow
        prop = _make_prop(name="col", value_type=tuple, type_name="color4f")
        adapter = _TrackingAdapter({"col": (1.0, 0.5, 0.25, 0.75)})
        row = Color4fAttributeRow(prop, adapter)
        assert len(row._widgets) == 4

    def test_channel_letters_are_rgba(self, no_ui):
        from ovui_widgets.property.attribute_row import Color4fAttributeRow
        prop = _make_prop(name="col", value_type=tuple, type_name="color4f")
        adapter = _TrackingAdapter({"col": (1.0, 0.5, 0.25, 0.75)})
        row = Color4fAttributeRow(prop, adapter)
        assert row._channel_letters == ("R", "G", "B", "A")

    def test_alpha_channel_change_produces_four_tuple(self, no_ui):
        from ovui_widgets.property.attribute_row import Color4fAttributeRow
        adapter = _TrackingAdapter({"col": (0.0, 0.0, 0.0, 0.0)})
        prop = _make_prop(name="col", value_type=tuple, type_name="color4f")
        row = Color4fAttributeRow(prop, adapter)
        widget_model = _FakeFloatModel(0.5)
        row._on_begin_edit(widget_model)
        row._on_component_changed(widget_model, 3)  # A
        row._on_end_edit(widget_model)
        assert row._model.get_value() == (0.0, 0.0, 0.0, 0.5)

    def test_default_base_when_current_is_none(self, no_ui):
        """Length-4 default for edits against an empty model."""
        from ovui_widgets.property.attribute_row import Color4fAttributeRow
        adapter = _TrackingAdapter({})
        prop = _make_prop(name="col", value_type=tuple, type_name="color4f")
        row = Color4fAttributeRow(prop, adapter)
        row._on_begin_edit(_FakeFloatModel())
        row._on_component_changed(_FakeFloatModel(0.9), 0)
        assert row._model.get_value() == (0.9, 0.0, 0.0, 0.0)


class TestColor3fSwatch:
    """Swatch rectangle — the Step 3.4 ``done signal``."""

    def _build_live(self, values=(1.0, 0.5, 0.25)):
        """Build a Color3fAttributeRow under a real ui.Window so the swatch
        Rectangle is instantiated (the ``no_ui`` fixture stubs _build_ui)."""
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import Color3fAttributeRow
        prop = _make_prop(name="col", value_type=tuple, type_name="color3f")
        adapter = MockPropertyAdapter(paths=["/P1"], attributes={"col": prop})
        adapter.set_path_value("/P1", "col", values)
        w = ui.Window("test_color3f_swatch", width=400, height=60)
        with w.frame:
            return Color3fAttributeRow(prop, adapter), adapter

    def test_swatch_exists_after_build(self):
        row, _ = self._build_live()
        assert row._swatch is not None

    def test_swatch_has_background_color(self):
        row, _ = self._build_live()
        assert "background_color" in row._swatch.style

    def test_swatch_initial_color_matches_value(self):
        """Swatch's initial background_color packs the initial R/G/B value."""
        from ovui_widgets.property.attribute_row import _pack_color_abgr
        row, _ = self._build_live(values=(1.0, 0.0, 0.0))
        expected = _pack_color_abgr((1.0, 0.0, 0.0), 3)
        assert row._swatch.style["background_color"] == expected

    def test_swatch_updates_on_component_change(self):
        """After an edit commits, the swatch must repaint with the new colour —
        the Step 3.4 done signal: ``swatch updates on set_value``."""
        from ovui_widgets.property.attribute_row import _pack_color_abgr
        row, _ = self._build_live(values=(0.0, 0.0, 0.0))
        widget_model = _FakeFloatModel(1.0)
        row._on_begin_edit(widget_model)
        row._on_component_changed(widget_model, 0)  # set R to 1.0
        row._on_end_edit(widget_model)
        # Swatch now reflects (1.0, 0.0, 0.0).
        expected = _pack_color_abgr((1.0, 0.0, 0.0), 3)
        assert row._swatch.style["background_color"] == expected

    def test_swatch_updates_on_external_change(self, no_ui):
        """External adapter change → swatch refreshes through
        ``_on_model_value_changed``. Uses ``no_ui`` + a ``_FakeRectangle``
        so the test stays headless (the live path is covered above)."""
        from ovui_widgets.property.attribute_row import Color3fAttributeRow, _pack_color_abgr
        adapter = _TrackingAdapter({"col": (0.0, 0.0, 0.0)})
        prop = _make_prop(name="col", value_type=tuple, type_name="color3f")
        row = Color3fAttributeRow(prop, adapter)
        row._widgets = [_FakeFloatWidget(), _FakeFloatWidget(), _FakeFloatWidget()]
        row._swatch = _FakeRectangle(style={"background_color": 0xFF000000})
        adapter._values["col"] = (0.0, 1.0, 0.0)
        adapter.fire_change()
        expected = _pack_color_abgr((0.0, 1.0, 0.0), 3)
        assert row._swatch.style["background_color"] == expected


class TestColor4fSwatch:
    """Color4 swatch — same shape as Color3 but pins the alpha channel."""

    def _build_live(self, values=(1.0, 0.5, 0.25, 0.5)):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import Color4fAttributeRow
        prop = _make_prop(name="col", value_type=tuple, type_name="color4f")
        adapter = MockPropertyAdapter(paths=["/P1"], attributes={"col": prop})
        adapter.set_path_value("/P1", "col", values)
        w = ui.Window("test_color4f_swatch", width=400, height=60)
        with w.frame:
            return Color4fAttributeRow(prop, adapter), adapter

    def test_swatch_exists_after_build(self):
        row, _ = self._build_live()
        assert row._swatch is not None

    def test_swatch_initial_color_packs_alpha(self):
        """Swatch's initial packed colour carries the authored alpha byte."""
        row, _ = self._build_live(values=(1.0, 0.0, 0.0, 0.5))
        packed = row._swatch.style["background_color"]
        # Alpha is the high byte.
        alpha = (packed >> 24) & 0xFF
        assert alpha == 128  # round(0.5 * 255)

    def test_swatch_updates_when_alpha_changes(self):
        """Editing the A component repaints the swatch with a new alpha."""
        row, _ = self._build_live(values=(1.0, 0.0, 0.0, 1.0))
        widget_model = _FakeFloatModel(0.25)
        row._on_begin_edit(widget_model)
        row._on_component_changed(widget_model, 3)  # A
        row._on_end_edit(widget_model)
        packed = row._swatch.style["background_color"]
        alpha = (packed >> 24) & 0xFF
        assert alpha == 64  # round(0.25 * 255)


class TestColorChannelColorCoding:
    """Color rows keep the property attribute builder behavior X/Y/Z/W axis palette for R/G/B/A.

    R shares X's blue, G shares Y's green, B shares Z's orange, A shares
    W's red. So the per-label ``style_type_name_override`` stays on
    ``Property.ChannelLabel.{X,Y,Z,W}`` even though the displayed text
    is R/G/B/A.
    """

    def _build(self, cls_name, values, type_name, window_name):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property import attribute_row as ar
        prop = _make_prop(name="col", value_type=tuple, type_name=type_name)
        adapter = MockPropertyAdapter(paths=["/P1"], attributes={"col": prop})
        adapter.set_path_value("/P1", "col", values)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return getattr(ar, cls_name)(prop, adapter)

    def test_color3_labels_use_xyz_axis_styles(self):
        row = self._build(
            "Color3fAttributeRow", (1.0, 0.5, 0.25), "color3f",
            "test_color3_axis_styles",
        )
        styles = [lbl.style_type_name_override for lbl in row._channel_labels]
        assert styles == [
            "Property.ChannelLabel.X",
            "Property.ChannelLabel.Y",
            "Property.ChannelLabel.Z",
        ]

    def test_color3_label_texts_are_rgb(self):
        row = self._build(
            "Color3fAttributeRow", (0.0, 0.0, 0.0), "color3f",
            "test_color3_rgb_text",
        )
        assert [lbl.text for lbl in row._channel_labels] == ["R", "G", "B"]

    def test_color4_labels_use_xyzw_axis_styles(self):
        row = self._build(
            "Color4fAttributeRow", (0.0, 0.0, 0.0, 1.0), "color4f",
            "test_color4_axis_styles",
        )
        styles = [lbl.style_type_name_override for lbl in row._channel_labels]
        assert styles == [
            "Property.ChannelLabel.X",
            "Property.ChannelLabel.Y",
            "Property.ChannelLabel.Z",
            "Property.ChannelLabel.W",
        ]

    def test_color4_label_texts_are_rgba(self):
        row = self._build(
            "Color4fAttributeRow", (0.0, 0.0, 0.0, 0.0), "color4f",
            "test_color4_rgba_text",
        )
        assert [lbl.text for lbl in row._channel_labels] == ["R", "G", "B", "A"]


class TestColorPerComponentAmbiguity:
    """Color rows inherit ``_VecFloatRow``'s per-component ambiguity; swapping
    channel letters to R/G/B/A must NOT break it — both the ``::mixed``
    state on the channel label and the ``Mixed`` overlay on the field have
    to line up with the component index."""

    def _build(self, cls_name, type_name, per_path_values, window_name):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property import attribute_row as ar
        prop = _make_prop(name="col", value_type=tuple, type_name=type_name)
        adapter = MockPropertyAdapter(
            paths=[p for p, _ in per_path_values],
            attributes={"col": prop},
        )
        for path, value in per_path_values:
            adapter.set_path_value(path, "col", value)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return getattr(ar, cls_name)(prop, adapter)

    def test_color3_only_g_differs(self):
        row = self._build(
            "Color3fAttributeRow", "color3f",
            [("/P1", (0.5, 0.5, 0.5)), ("/P2", (0.5, 0.9, 0.5))],
            "test_color3_only_g",
        )
        names = [lbl.name for lbl in row._channel_labels]
        assert names == ["", "mixed", ""]
        vis = [o.visible for o in row._overlay_labels]
        assert vis == [False, True, False]

    def test_color4_only_alpha_differs(self):
        """Pins that the fourth ambiguity element lines up with the A
        component — a bug Step 3.1's `W differs` test already caught on
        float4, re-pinned here because `_ColorFloatRow` rewrites the
        letter list."""
        row = self._build(
            "Color4fAttributeRow", "color4f",
            [("/P1", (0.0, 0.0, 0.0, 0.0)), ("/P2", (0.0, 0.0, 0.0, 1.0))],
            "test_color4_only_a",
        )
        assert [lbl.name for lbl in row._channel_labels] == ["", "", "", "mixed"]
        assert [o.visible for o in row._overlay_labels] == [False, False, False, True]

    def test_color3_all_equal_no_channels_marked(self):
        row = self._build(
            "Color3fAttributeRow", "color3f",
            [("/P1", (0.5, 0.5, 0.5)), ("/P2", (0.5, 0.5, 0.5))],
            "test_color3_all_equal",
        )
        assert [lbl.name for lbl in row._channel_labels] == ["", "", ""]


class TestColorRowInheritance:
    """Shared-base sanity: the colour rows extend ``_VecFloatRow`` (so every
    future change to per-component ambiguity, soft ranges, etc. lands in
    one place) and ``_ColorFloatRow`` (the colour-specific extension that
    swaps letters and manages the swatch)."""

    def test_color3_extends_color_float_row(self):
        from ovui_widgets.property.attribute_row import (
            Color3fAttributeRow,
            _ColorFloatRow,
        )
        assert issubclass(Color3fAttributeRow, _ColorFloatRow)

    def test_color4_extends_color_float_row(self):
        from ovui_widgets.property.attribute_row import (
            Color4fAttributeRow,
            _ColorFloatRow,
        )
        assert issubclass(Color4fAttributeRow, _ColorFloatRow)

    def test_color_float_row_extends_vec_float_row(self):
        from ovui_widgets.property.attribute_row import _ColorFloatRow, _VecFloatRow
        assert issubclass(_ColorFloatRow, _VecFloatRow)


# ---------------------------------------------------------------------------
# Step 3.5 — Matrix rows (matrix2d/matrix3d/matrix4d)
# ---------------------------------------------------------------------------
# Step 3.5 adds ``MatrixAttributeRow`` — a parameterised row that renders an
# N×N grid of ``ui.FloatDrag`` cells for USD matrix attributes. Each cell
# edits one component of the matrix; values are stored as a flat tuple of
# ``n_dim * n_dim`` floats in row-major order (matching USD's
# ``Gf.Matrix2d``/``Gf.Matrix3d``/``Gf.Matrix4d`` constructor shape).
#
# Tests pin:
#
# * widget counts for all three widths (4 / 9 / 16 cells);
# * the flat-index → (row, col) mapping — set cell [1, 2] via the model
#   and verify only that cell changes (the Step 3.5 done signal);
# * external-change propagation through every cell;
# * guardrails against unsupported widths (1, 5) since the builder table
#   would only ever instantiate 2/3/4.


class TestMatrixAttributeRow:
    """Parameterised matrix row — one class, three widths."""

    def test_2x2_has_four_widget_slots(self, no_ui):
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix2d")
        adapter = _TrackingAdapter({"m": (1.0, 2.0, 3.0, 4.0)})
        row = MatrixAttributeRow(prop, adapter, n_dim=2)
        assert len(row._widgets) == 4
        assert row._n_dim == 2
        assert row._n_cells == 4

    def test_3x3_has_nine_widget_slots(self, no_ui):
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix3d")
        adapter = _TrackingAdapter({"m": tuple(float(i) for i in range(9))})
        row = MatrixAttributeRow(prop, adapter, n_dim=3)
        assert len(row._widgets) == 9
        assert row._n_dim == 3
        assert row._n_cells == 9

    def test_4x4_has_sixteen_widget_slots(self, no_ui):
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix4d")
        adapter = _TrackingAdapter({"m": tuple(float(i) for i in range(16))})
        row = MatrixAttributeRow(prop, adapter, n_dim=4)
        assert len(row._widgets) == 16
        assert row._n_dim == 4
        assert row._n_cells == 16

    def test_rejects_invalid_n_dim(self, no_ui):
        """Guardrail: only 2, 3, 4 are supported — 1 or 5 would indicate the
        builder table wired a type name to the wrong shape."""
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        adapter = _TrackingAdapter({})
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix2d")
        with pytest.raises(ValueError, match="n_dim"):
            MatrixAttributeRow(prop, adapter, n_dim=1)
        with pytest.raises(ValueError, match="n_dim"):
            MatrixAttributeRow(prop, adapter, n_dim=5)


class TestMatrixCellEdit:
    """The Step 3.5 done signal: set cell ``[1, 2]`` via the model and
    verify that exactly that cell changed and every other cell is
    untouched. Covers all three widths."""

    @staticmethod
    def _flat(n_dim: int, row: int, col: int) -> int:
        """Row-major flat index — matches ``Gf.Matrix*d[row][col]`` reads
        and the ``Gf.Matrix*d(*flat)`` constructor argument order."""
        return row * n_dim + col

    def test_3x3_set_cell_1_2_changes_only_that_cell(self, no_ui):
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        # Start with the 3×3 identity so every "unchanged" cell has a
        # distinctive non-zero value to assert against (catches a latent
        # flat-index bug that would swap two cells).
        identity3 = (
            1.0, 0.0, 0.0,
            0.0, 1.0, 0.0,
            0.0, 0.0, 1.0,
        )
        adapter = _TrackingAdapter({"m": identity3})
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix3d")
        row = MatrixAttributeRow(prop, adapter, n_dim=3)
        widget_model = _FakeFloatModel(42.5)
        flat = self._flat(3, 1, 2)  # row 1, col 2 → flat index 5
        row._on_begin_edit(widget_model)
        row._on_component_changed(widget_model, flat)
        row._on_end_edit(widget_model)
        new_value = row._model.get_value()
        # Cell [1, 2] carries the new value.
        assert new_value[flat] == pytest.approx(42.5)
        # Every other cell is untouched.
        for i in range(9):
            if i == flat:
                continue
            assert new_value[i] == pytest.approx(identity3[i]), (
                f"cell {i} changed from {identity3[i]} to {new_value[i]}"
            )
        # Adapter sees exactly one set_value (buffered by change_on_edit_end).
        assert adapter.calls == [
            ("begin_edit", "m"),
            ("set_value", "m", new_value),
            ("end_edit", "m"),
        ]

    def test_2x2_set_cell_1_0_changes_only_that_cell(self, no_ui):
        """2×2 width: cell [1, 0] maps to flat index 2 (row 1 starts at 2)."""
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        initial = (5.0, 6.0, 7.0, 8.0)
        adapter = _TrackingAdapter({"m": initial})
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix2d")
        row = MatrixAttributeRow(prop, adapter, n_dim=2)
        flat = self._flat(2, 1, 0)  # 1*2 + 0 = 2
        row._on_begin_edit(_FakeFloatModel(99.0))
        row._on_component_changed(_FakeFloatModel(99.0), flat)
        row._on_end_edit(_FakeFloatModel(99.0))
        assert row._model.get_value() == (5.0, 6.0, 99.0, 8.0)

    def test_4x4_set_cell_2_3_changes_only_that_cell(self, no_ui):
        """4×4 width: cell [2, 3] maps to flat index 11."""
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        initial = tuple(float(i) for i in range(16))
        adapter = _TrackingAdapter({"m": initial})
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix4d")
        row = MatrixAttributeRow(prop, adapter, n_dim=4)
        flat = self._flat(4, 2, 3)  # 2*4 + 3 = 11
        row._on_begin_edit(_FakeFloatModel(77.0))
        row._on_component_changed(_FakeFloatModel(77.0), flat)
        row._on_end_edit(_FakeFloatModel(77.0))
        new_value = row._model.get_value()
        assert new_value[flat] == pytest.approx(77.0)
        for i in range(16):
            if i == flat:
                continue
            assert new_value[i] == pytest.approx(initial[i])

    def test_default_base_when_current_is_none(self, no_ui):
        """Edit against an empty model: base tuple has length ``n_dim * n_dim``
        and every cell defaults to 0.0 (matches ``_VecFloatRow``'s default)."""
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        adapter = _TrackingAdapter({})
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix3d")
        row = MatrixAttributeRow(prop, adapter, n_dim=3)
        row._on_begin_edit(_FakeFloatModel())
        row._on_component_changed(_FakeFloatModel(1.5), 4)  # centre cell
        value = row._model.get_value()
        assert len(value) == 9
        assert value[4] == pytest.approx(1.5)
        for i in range(9):
            if i == 4:
                continue
            assert value[i] == pytest.approx(0.0)


class TestMatrixExternalChange:
    """External USD writes propagate through every cell's widget via the
    shared ``_on_model_value_changed`` loop."""

    def test_external_change_updates_all_nine_widgets(self, no_ui):
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        adapter = _TrackingAdapter({"m": tuple(0.0 for _ in range(9))})
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix3d")
        row = MatrixAttributeRow(prop, adapter, n_dim=3)
        row._widgets = [_FakeFloatWidget() for _ in range(9)]
        new_value = tuple(float(i + 1) for i in range(9))
        adapter._values["m"] = new_value
        adapter.fire_change()
        for i, widget in enumerate(row._widgets):
            assert widget.model.get_value_as_float() == pytest.approx(new_value[i])

    def test_external_change_updates_all_sixteen_widgets(self, no_ui):
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        adapter = _TrackingAdapter({"m": tuple(0.0 for _ in range(16))})
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix4d")
        row = MatrixAttributeRow(prop, adapter, n_dim=4)
        row._widgets = [_FakeFloatWidget() for _ in range(16)]
        new_value = tuple(float(i + 1) * 0.1 for i in range(16))
        adapter._values["m"] = new_value
        adapter.fire_change()
        for i, widget in enumerate(row._widgets):
            assert widget.model.get_value_as_float() == pytest.approx(new_value[i])

    def test_external_change_suppressed_during_edit(self, no_ui):
        """Mid-edit: the backing-change must not clobber the user's in-progress
        edit — same guard every other row class has."""
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        adapter = _TrackingAdapter({"m": tuple(0.0 for _ in range(4))})
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix2d")
        row = MatrixAttributeRow(prop, adapter, n_dim=2)
        row._widgets = [_FakeFloatWidget() for _ in range(4)]
        row._model.begin_edit()
        adapter._values["m"] = (1.0, 2.0, 3.0, 4.0)
        adapter.fire_change()
        for widget in row._widgets:
            # Still zero — external change was suppressed during the edit.
            assert widget.model.get_value_as_float() == pytest.approx(0.0)


class TestMatrixLiveBuild:
    """Build a real ``MatrixAttributeRow`` under a ``ui.Window`` so the
    FloatDrag cells are instantiated (the ``no_ui`` fixture stubs
    ``_build_ui``). Pins the visible widget count at every width and
    verifies the initial cell values reflect the adapter's stored flat
    tuple.
    """

    def _build(self, n_dim, initial, window_name):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        type_name = f"matrix{n_dim}d"
        prop = _make_prop(name="m", value_type=tuple, type_name=type_name)
        adapter = MockPropertyAdapter(paths=["/P1"], attributes={"m": prop})
        adapter.set_path_value("/P1", "m", initial)
        w = ui.Window(window_name, width=400, height=150)
        with w.frame:
            return MatrixAttributeRow(prop, adapter, n_dim=n_dim)

    def test_2x2_cells_reflect_initial_values(self):
        initial = (1.25, 2.5, 3.75, 4.0)
        row = self._build(2, initial, "test_matrix2x2_live")
        assert len(row._widgets) == 4
        for i in range(4):
            assert row._widgets[i].model.get_value_as_float() == pytest.approx(initial[i])

    def test_3x3_cells_reflect_initial_values(self):
        initial = tuple(float(i) * 0.5 for i in range(9))
        row = self._build(3, initial, "test_matrix3x3_live")
        assert len(row._widgets) == 9
        for i in range(9):
            assert row._widgets[i].model.get_value_as_float() == pytest.approx(initial[i])

    def test_4x4_cells_reflect_initial_values(self):
        initial = tuple(float(i) * 0.1 for i in range(16))
        row = self._build(4, initial, "test_matrix4x4_live")
        assert len(row._widgets) == 16
        for i in range(16):
            assert row._widgets[i].model.get_value_as_float() == pytest.approx(initial[i])


# ---------------------------------------------------------------------------
# Step 3.6 — Asset-path row (label + StringField + folder button)
# ---------------------------------------------------------------------------
# ``AssetPathAttributeRow`` wraps a :class:`ui.StringField` for the
# authored USD asset path plus a no-op folder button (the file-picker
# integration lands in a later phase). ``adapter.get_resolved_asset_path``
# surfaces as a StringField tooltip when the adapter can resolve the
# path (property metadata behavior, the property inspector behavior).
#
# The module-level ``is_relative_path`` helper is pure Python
# and testable without any UI context. Four shapes count as absolute:
# POSIX ``/``-prefixed, Windows drive-letter, ``://`` schemes, and UNC
# ``//``. Everything else — including the empty string — is relative.


class TestIsRelativePath:
    """Pure-function helper used by AssetPathAttributeRow.

    Pinned against every shape Kit's own ``is_relative_path`` covers so
    the "Make Absolute" button (scheduled for a later phase) lands on
    the right decision boundary.
    """

    @pytest.mark.parametrize(
        "path",
        [
            "foo.png",
            "./textures/noise.png",
            "../shared/model.usd",
            "textures/subdir/tex.png",
            "",  # Empty string is relative by convention.
            "noslash",
            "dir_with_colon:value",  # Colon not at [1] — still relative.
        ],
    )
    def test_relative_paths_return_true(self, path):
        from ovui_widgets.property.attribute_row import is_relative_path
        assert is_relative_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/absolute/path.png",
            "/",
            "//unc/share/asset.png",  # POSIX absolute via leading '/' catches UNC too.
            "/mnt/project/scene.usd",
        ],
    )
    def test_posix_absolute_paths_return_false(self, path):
        from ovui_widgets.property.attribute_row import is_relative_path
        assert is_relative_path(path) is False

    @pytest.mark.parametrize(
        "path",
        [
            "C:\\project\\scene.usd",
            "c:/project/scene.usd",
            "D:\\",
            "z:/lowercase_drive.usd",
        ],
    )
    def test_windows_drive_letter_paths_return_false(self, path):
        from ovui_widgets.property.attribute_row import is_relative_path
        assert is_relative_path(path) is False

    @pytest.mark.parametrize(
        "path",
        [
            "omniverse://server/asset.usd",
            "http://example.com/tex.png",
            "https://cdn.example.com/img.jpg",
            "file:///tmp/local.usd",
            "s3://bucket/key",
        ],
    )
    def test_scheme_urls_return_false(self, path):
        from ovui_widgets.property.attribute_row import is_relative_path
        assert is_relative_path(path) is False

    def test_non_string_returns_true(self):
        """Defensive: ``None`` / non-string inputs default to relative so
        callers can lean on the helper without a preflight isinstance check."""
        from ovui_widgets.property.attribute_row import is_relative_path
        assert is_relative_path(None) is True  # type: ignore[arg-type]


class TestAssetPathAttributeRow:
    """``AssetPathAttributeRow`` drives a ``ui.StringField`` + folder button.

    Every test stubs ``_build_ui`` via the ``no_ui`` fixture so row
    construction runs headlessly; a separate ``TestAssetPathLiveBuild``
    class (below) exercises the live widget instantiation.
    """

    def test_shows_correct_initial_value(self, no_ui):
        from ovui_widgets.property.attribute_row import AssetPathAttributeRow
        adapter = _TrackingAdapter({"tex": "./textures/noise.png"})
        prop = _make_prop(name="tex", value_type=str, type_name="asset")
        row = AssetPathAttributeRow(prop, adapter)
        assert row._model.get_value() == "./textures/noise.png"

    def test_row_constructs_model(self, no_ui):
        """Step 1.4 invariant: asset-path row owns an ``AttributeModelBase``."""
        from ovui_widgets.property.attribute_row import AssetPathAttributeRow
        from ovui_widgets.property.models import AttributeModelBase
        adapter = _TrackingAdapter()
        prop = _make_prop(name="tex", value_type=str, type_name="asset")
        row = AssetPathAttributeRow(prop, adapter)
        assert isinstance(row._model, AttributeModelBase)

    def test_row_subscribes_adapter_changes(self, no_ui):
        from ovui_widgets.property.attribute_row import AssetPathAttributeRow
        adapter = _TrackingAdapter({"tex": "a.png"})
        prop = _make_prop(name="tex", value_type=str, type_name="asset")
        AssetPathAttributeRow(prop, adapter)
        assert len(adapter._subscribers) == 1

    def test_end_edit_commits_value_through_model(self, no_ui):
        from ovui_widgets.property.attribute_row import AssetPathAttributeRow
        adapter = _TrackingAdapter({"tex": "old.png"})
        prop = _make_prop(name="tex", value_type=str, type_name="asset")
        row = AssetPathAttributeRow(prop, adapter)
        row._on_begin_edit(_FakeStringModel("old.png"))
        row._on_end_edit(_FakeStringModel("new.png"))
        assert adapter.calls == [
            ("begin_edit", "tex"),
            ("set_value", "tex", "new.png"),
            ("end_edit", "tex"),
        ]

    def test_begin_edit_records_start_value(self, no_ui):
        """``_start_value`` is captured so a later revert-on-escape feature
        has the pre-edit text to restore. Parallels the String row path."""
        from ovui_widgets.property.attribute_row import AssetPathAttributeRow
        adapter = _TrackingAdapter({"tex": "before.png"})
        prop = _make_prop(name="tex", value_type=str, type_name="asset")
        row = AssetPathAttributeRow(prop, adapter)
        row._on_begin_edit(_FakeStringModel("before.png"))
        assert row._start_value == "before.png"

    def test_external_change_updates_widget(self, no_ui):
        from ovui_widgets.property.attribute_row import AssetPathAttributeRow
        adapter = _TrackingAdapter({"tex": "a.png"})
        prop = _make_prop(name="tex", value_type=str, type_name="asset")
        row = AssetPathAttributeRow(prop, adapter)
        row._widget = _FakeStringWidget("a.png")
        adapter._values["tex"] = "b.png"
        adapter.fire_change()
        assert row._widget.model.get_value_as_string() == "b.png"

    def test_folder_click_is_noop(self, no_ui):
        """Step 3.6's folder button does nothing — the file_importer hook
        lands in a later phase. Pinning the no-op means a future refactor
        that accidentally wires a side-effect fails here first."""
        from ovui_widgets.property.attribute_row import AssetPathAttributeRow
        adapter = _TrackingAdapter({"tex": "a.png"})
        prop = _make_prop(name="tex", value_type=str, type_name="asset")
        row = AssetPathAttributeRow(prop, adapter)
        assert row._on_folder_clicked() is None
        assert adapter.calls == []

    def test_resolved_tooltip_falls_back_to_empty(self, no_ui):
        """When the adapter returns ``None`` from ``get_resolved_asset_path``,
        ``_resolved_tooltip`` yields ``""`` so the row never renders a
        literal "None" string in the tooltip slot."""
        from ovui_widgets.property.attribute_row import AssetPathAttributeRow
        adapter = _TrackingAdapter({"tex": "a.png"})
        prop = _make_prop(name="tex", value_type=str, type_name="asset")
        row = AssetPathAttributeRow(prop, adapter)
        assert row._resolved_tooltip() == ""

    def test_resolved_tooltip_uses_adapter_value(self, no_ui):
        from ovui_widgets.property.attribute_row import AssetPathAttributeRow
        adapter = _TrackingAdapter({"tex": "rel/a.png"})
        adapter._resolved_asset_paths["tex"] = "/abs/root/rel/a.png"
        prop = _make_prop(name="tex", value_type=str, type_name="asset")
        row = AssetPathAttributeRow(prop, adapter)
        assert row._resolved_tooltip() == "/abs/root/rel/a.png"


class TestAssetPathLiveBuild:
    """Build a real ``AssetPathAttributeRow`` under a ``ui.Window`` so the
    StringField + folder button are actually instantiated.

    The live build exercises the full ``_build_ui`` path: widget types,
    initial value seeding, tooltip wiring, and Mixed overlay state —
    everything the ``no_ui`` fixture stubs out for headless tests above.
    """

    def _build(self, window_name, *, resolved=None, ambiguous=False):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import AssetPathAttributeRow
        prop = _make_prop(name="tex", value_type=str, type_name="asset")
        paths = ["/P1", "/P2"] if ambiguous else ["/P1"]
        adapter = MockPropertyAdapter(paths=paths, attributes={"tex": prop})
        adapter.set_path_value("/P1", "tex", "./textures/noise.png")
        if ambiguous:
            adapter.set_path_value("/P2", "tex", "./textures/other.png")
        if resolved is not None:
            adapter.set_resolved_asset_path("tex", resolved)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return AssetPathAttributeRow(prop, adapter)

    def test_string_field_renders_authored_path(self):
        row = self._build("test_asset_string_field")
        assert row._widget is not None
        assert row._widget.model.get_value_as_string() == "./textures/noise.png"

    def test_folder_button_exists(self):
        """Step 3.6 done-signal bullet: folder button present even though it
        doesn't open anything yet."""
        import omni.ui as ui
        row = self._build("test_asset_folder_button")
        assert row._folder_button is not None
        assert isinstance(row._folder_button, ui.Button)
        assert row._folder_button.text == "..."

    def test_folder_button_uses_asset_path_style(self):
        """Folder button carries the ``Property.AssetPathFolderButton``
        style type so a future phase can restyle it without touching the
        row class."""
        row = self._build("test_asset_folder_button_style")
        assert (
            row._folder_button.style_type_name_override
            == "Property.AssetPathFolderButton"
        )

    def test_tooltip_set_when_resolver_returns_path(self):
        row = self._build(
            "test_asset_tooltip_set",
            resolved="/abs/root/textures/noise.png",
        )
        assert row._widget.tooltip == "/abs/root/textures/noise.png"

    def test_tooltip_empty_when_resolver_returns_none(self):
        row = self._build("test_asset_tooltip_empty")
        # ``tooltip`` is only assigned when the resolver produced a non-empty
        # string; the default omni.ui tooltip is an empty string.
        assert row._widget.tooltip == ""

    def test_mixed_overlay_visible_for_ambiguous(self):
        row = self._build("test_asset_mixed_overlay", ambiguous=True)
        assert row._overlay is not None
        assert row._overlay.visible is True

    def test_mixed_overlay_hidden_for_single(self):
        row = self._build("test_asset_mixed_overlay_clean")
        assert row._overlay is not None
        assert row._overlay.visible is False


# ---------------------------------------------------------------------------
# Step 3.7 — Relationship row (label + read-only StringField)
# ---------------------------------------------------------------------------
# ``RelationshipAttributeRow`` wraps a :class:`ui.StringField` with
# ``read_only=True`` showing the joined target paths of a USD
# ``Usd.Relationship``. Editing is out of scope for Step 3.7 — a modal
# target picker (§9.8 ``RelationshipTargetPicker``) is scheduled for a
# later phase. The module-level ``_format_relationship_targets`` helper
# is pure Python and tested in isolation below.


class TestFormatRelationshipTargets:
    """Pure function — three display shapes driven by target count."""

    def test_empty_returns_empty_string(self):
        from ovui_widgets.property.attribute_row import _format_relationship_targets
        assert _format_relationship_targets(()) == ""

    def test_none_returns_empty_string(self):
        """Defensive: ``None`` is the seed value for a model whose adapter
        returned ``None`` (e.g. an adapter that has not yet resolved the
        relationship). The formatter must yield an empty string rather
        than the literal ``"None"``."""
        from ovui_widgets.property.attribute_row import _format_relationship_targets
        assert _format_relationship_targets(None) == ""

    def test_single_target_returns_path_verbatim(self):
        from ovui_widgets.property.attribute_row import _format_relationship_targets
        assert _format_relationship_targets(("/World/Target",)) == "/World/Target"

    def test_multiple_targets_comma_joined(self):
        from ovui_widgets.property.attribute_row import _format_relationship_targets
        result = _format_relationship_targets(("/World/A", "/World/B", "/World/C"))
        assert result == "/World/A, /World/B, /World/C"

    def test_accepts_list_like_input(self):
        """Adapters may return a list instead of a tuple; the join must
        still work without raising."""
        from ovui_widgets.property.attribute_row import _format_relationship_targets
        assert _format_relationship_targets(["/A", "/B"]) == "/A, /B"

    def test_non_string_elements_stringified(self):
        """Elements are coerced via ``str()`` so an adapter surfacing a
        ``Sdf.Path`` (or any object with a ``__str__``) still formats
        correctly — matches the stringification the USD adapter already
        performs in ``get_value``, but robust against adapters that skip it."""
        from ovui_widgets.property.attribute_row import _format_relationship_targets

        class _PathLike:
            def __init__(self, s):
                self._s = s

            def __str__(self):
                return self._s

        result = _format_relationship_targets((_PathLike("/X"), _PathLike("/Y")))
        assert result == "/X, /Y"


class TestRelationshipAttributeRow:
    """``RelationshipAttributeRow`` drives a read-only ``ui.StringField``.

    Every test stubs ``_build_ui`` via the ``no_ui`` fixture so row
    construction runs headlessly; a separate ``TestRelationshipLiveBuild``
    class (below) exercises the live widget instantiation.
    """

    def test_shows_correct_initial_value(self, no_ui):
        """Model seeded with the tuple returned by the adapter."""
        from ovui_widgets.property.attribute_row import RelationshipAttributeRow
        adapter = _TrackingAdapter({"material:binding": ("/Looks/M1",)})
        prop = _make_prop(name="material:binding", value_type=tuple, type_name="relationship")
        row = RelationshipAttributeRow(prop, adapter)
        assert row._model.get_value() == ("/Looks/M1",)

    def test_row_constructs_model(self, no_ui):
        """Step 1.4 invariant: relationship row owns an ``AttributeModelBase``."""
        from ovui_widgets.property.attribute_row import RelationshipAttributeRow
        from ovui_widgets.property.models import AttributeModelBase
        adapter = _TrackingAdapter()
        prop = _make_prop(name="rel", value_type=tuple, type_name="relationship")
        row = RelationshipAttributeRow(prop, adapter)
        assert isinstance(row._model, AttributeModelBase)

    def test_row_subscribes_adapter_changes(self, no_ui):
        from ovui_widgets.property.attribute_row import RelationshipAttributeRow
        adapter = _TrackingAdapter({"rel": ()})
        prop = _make_prop(name="rel", value_type=tuple, type_name="relationship")
        RelationshipAttributeRow(prop, adapter)
        assert len(adapter._subscribers) == 1

    def test_no_edit_callbacks_wired(self, no_ui):
        """Row is read-only: it must not carry ``_on_begin_edit`` /
        ``_on_end_edit`` / ``_on_value_changed`` callbacks that would
        call ``model.set_value`` if invoked. Pins the read-only design
        against accidental regressions that bolt on edit wiring before
        the Phase-6 target picker ships."""
        from ovui_widgets.property.attribute_row import RelationshipAttributeRow
        adapter = _TrackingAdapter({"rel": ("/T",)})
        prop = _make_prop(name="rel", value_type=tuple, type_name="relationship")
        row = RelationshipAttributeRow(prop, adapter)
        assert not hasattr(row, "_on_begin_edit")
        assert not hasattr(row, "_on_end_edit")
        assert not hasattr(row, "_on_value_changed")

    def test_external_change_updates_widget(self, no_ui):
        """External USD edit (``adapter.fire_change``) lands through the
        model's ``_on_backing_changed`` → ``_on_model_value_changed``
        pipeline and refreshes the StringField display."""
        from ovui_widgets.property.attribute_row import RelationshipAttributeRow
        adapter = _TrackingAdapter({"rel": ("/A",)})
        prop = _make_prop(name="rel", value_type=tuple, type_name="relationship")
        row = RelationshipAttributeRow(prop, adapter)
        row._widget = _FakeStringWidget("/A")
        adapter._values["rel"] = ("/A", "/B")
        adapter.fire_change()
        assert row._widget.model.get_value_as_string() == "/A, /B"

    def test_external_change_to_empty_updates_widget(self, no_ui):
        """Clearing the targets clears the StringField (no stale text)."""
        from ovui_widgets.property.attribute_row import RelationshipAttributeRow
        adapter = _TrackingAdapter({"rel": ("/A",)})
        prop = _make_prop(name="rel", value_type=tuple, type_name="relationship")
        row = RelationshipAttributeRow(prop, adapter)
        row._widget = _FakeStringWidget("/A")
        adapter._values["rel"] = ()
        adapter.fire_change()
        assert row._widget.model.get_value_as_string() == ""

    def test_no_adapter_set_value_during_construction(self, no_ui):
        """Constructing the row reads the initial value but never writes
        it back. Regression guard against a mistaken ``set_value`` call
        in ``__init__`` that would dirty the stage on open."""
        from ovui_widgets.property.attribute_row import RelationshipAttributeRow
        adapter = _TrackingAdapter({"rel": ("/T",)})
        prop = _make_prop(name="rel", value_type=tuple, type_name="relationship")
        RelationshipAttributeRow(prop, adapter)
        assert adapter.calls == []


class TestRelationshipLiveBuild:
    """Build a real ``RelationshipAttributeRow`` under a ``ui.Window`` so
    the read-only ``StringField`` is actually instantiated.
    """

    def _build(self, window_name, *, targets_a=("/World/Target",), targets_b=None):
        """Build a row with one or two prims selected.

        Single-selection (``targets_b is None``): the row reads
        ``targets_a`` from ``/P1``.
        Multi-selection (``targets_b is not None``): the row reads from
        ``/P1`` and ``/P2``; when the tuples differ the mock adapter
        flags the attribute ``is_ambiguous`` → the Mixed overlay shows.
        """
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import RelationshipAttributeRow
        prop = _make_prop(name="rel", value_type=tuple, type_name="relationship")
        paths = ["/P1"] if targets_b is None else ["/P1", "/P2"]
        adapter = MockPropertyAdapter(paths=paths, attributes={"rel": prop})
        adapter.set_path_value("/P1", "rel", targets_a)
        if targets_b is not None:
            adapter.set_path_value("/P2", "rel", targets_b)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return RelationshipAttributeRow(prop, adapter)

    def test_string_field_is_readonly(self):
        """Step 3.7 done-signal core bullet: the row's input widget is a
        read-only StringField — the user can copy but not type."""
        import omni.ui as ui
        row = self._build("test_rel_readonly")
        assert row._widget is not None
        assert isinstance(row._widget, ui.StringField)
        assert row._widget.read_only is True

    def test_single_target_displays_path_verbatim(self):
        row = self._build(
            "test_rel_single_target",
            targets_a=("/World/SingleTarget",),
        )
        assert row._widget.model.get_value_as_string() == "/World/SingleTarget"

    def test_multiple_targets_display_joined(self):
        row = self._build(
            "test_rel_multi_target",
            targets_a=("/World/A", "/World/B", "/World/C"),
        )
        assert (
            row._widget.model.get_value_as_string()
            == "/World/A, /World/B, /World/C"
        )

    def test_empty_targets_displays_empty(self):
        """Zero-target relationship renders an empty StringField (no
        placeholder text, no "None" glyph)."""
        row = self._build("test_rel_empty", targets_a=())
        assert row._widget.model.get_value_as_string() == ""

    def test_mixed_overlay_visible_for_ambiguous(self):
        """Multi-selection with divergent target lists → Mixed overlay
        visible (signals "the selection disagrees")."""
        row = self._build(
            "test_rel_mixed_overlay",
            targets_a=("/World/A",),
            targets_b=("/World/B",),
        )
        assert row._overlay is not None
        assert row._overlay.visible is True

    def test_mixed_overlay_hidden_for_single(self):
        row = self._build("test_rel_mixed_overlay_clean")
        assert row._overlay is not None
        assert row._overlay.visible is False


# ---------------------------------------------------------------------------
# Step 3.8 — ArrayAttributeRow + _format_array_value
# ---------------------------------------------------------------------------


def _make_array_prop(name="arr", *, is_big_array=False):
    """Array-attr metadata shortcut — sets ``type_name="array"`` sentinel."""
    from ovui_data_adapters.common import AttributeMetadata
    return AttributeMetadata(
        name=name,
        display_name=name,
        type_name="array",
        value_type="array",
        group="X",
        is_big_array=is_big_array,
    )


class TestFormatArrayValue:
    """``_format_array_value`` is the single source of truth for what
    ``ArrayAttributeRow`` puts in the StringField. Pin each decision
    boundary independently.
    """

    def test_none_returns_empty_string(self):
        from ovui_widgets.property.attribute_row import _format_array_value
        assert _format_array_value(None, False) == ""
        # ``is_big_array=True`` on a None value must still collapse to
        # the empty string — otherwise the row would flash "[N items]"
        # with N unresolved during a rebuild transient.
        assert _format_array_value(None, True) == ""

    def test_small_array_renders_full_tuple(self):
        from ovui_widgets.property.attribute_row import _format_array_value
        assert _format_array_value((1.0, 2.0, 3.0), False) == "(1.0, 2.0, 3.0)"

    def test_small_array_from_list_converts_to_tuple(self):
        """Step 3.8 adapters may surface arrays as tuples or lists. The
        formatter normalises to the tuple repr so the displayed string
        never depends on the container shape."""
        from ovui_widgets.property.attribute_row import _format_array_value
        assert _format_array_value([1, 2, 3], False) == "(1, 2, 3)"

    def test_empty_tuple_renders_as_empty_tuple_repr(self):
        """An authored-but-empty array is distinct from ``None`` —
        ``"()"`` signals "authored zero-length array", ``""`` signals
        "unauthored / not present"."""
        from ovui_widgets.property.attribute_row import _format_array_value
        assert _format_array_value((), False) == "()"

    def test_big_array_renders_n_items(self):
        from ovui_widgets.property.attribute_row import _format_array_value
        assert _format_array_value(tuple(range(20)), True) == "[20 items]"

    def test_big_array_honours_is_big_array_flag(self):
        """``is_big_array`` is authoritative — even a 2-element array
        renders as ``"[2 items]"`` if the adapter flagged it big. This
        pins the contract that the row never re-checks the length
        threshold (the adapter owns the decision)."""
        from ovui_widgets.property.attribute_row import _format_array_value
        assert _format_array_value((1.0, 2.0), True) == "[2 items]"

    def test_big_array_on_unsized_value_falls_back_to_str(self):
        """Defensive: if an adapter surfaces something truthy but
        unsized (e.g. a non-container ``object()`` through a future
        adapter), the big-array branch mustn't crash the row build —
        it falls back to ``str()``."""
        from ovui_widgets.property.attribute_row import _format_array_value

        class _Unsized:
            def __str__(self):
                return "opaque"

        result = _format_array_value(_Unsized(), True)
        assert result == "opaque"


class TestArrayAttributeRow:
    """Headless tests for ``ArrayAttributeRow`` — model ownership,
    subscriptions, read-only contract, external-change refresh.
    """

    def test_shows_correct_initial_value_small(self, no_ui):
        from ovui_widgets.property.attribute_row import ArrayAttributeRow
        adapter = _TrackingAdapter({"arr": (1.0, 2.0, 3.0)})
        prop = _make_array_prop(name="arr", is_big_array=False)
        row = ArrayAttributeRow(prop, adapter)
        assert row._model.get_value() == (1.0, 2.0, 3.0)

    def test_shows_correct_initial_value_big(self, no_ui):
        from ovui_widgets.property.attribute_row import ArrayAttributeRow
        values = tuple(range(20))
        adapter = _TrackingAdapter({"arr": values})
        prop = _make_array_prop(name="arr", is_big_array=True)
        row = ArrayAttributeRow(prop, adapter)
        assert row._model.get_value() == values

    def test_row_constructs_model(self, no_ui):
        """Step 1.4 invariant: array row owns an ``AttributeModelBase``."""
        from ovui_widgets.property.attribute_row import ArrayAttributeRow
        from ovui_widgets.property.models import AttributeModelBase
        adapter = _TrackingAdapter()
        prop = _make_array_prop()
        row = ArrayAttributeRow(prop, adapter)
        assert isinstance(row._model, AttributeModelBase)

    def test_row_subscribes_adapter_changes(self, no_ui):
        from ovui_widgets.property.attribute_row import ArrayAttributeRow
        adapter = _TrackingAdapter({"arr": ()})
        prop = _make_array_prop()
        ArrayAttributeRow(prop, adapter)
        assert len(adapter._subscribers) == 1

    def test_no_edit_callbacks_wired(self, no_ui):
        """Row is read-only: no ``_on_begin_edit`` / ``_on_end_edit`` /
        ``_on_value_changed`` callbacks. Regression guard against
        accidental edit wiring before the Phase-6 array editor ships.
        """
        from ovui_widgets.property.attribute_row import ArrayAttributeRow
        adapter = _TrackingAdapter({"arr": (1, 2, 3)})
        prop = _make_array_prop()
        row = ArrayAttributeRow(prop, adapter)
        assert not hasattr(row, "_on_begin_edit")
        assert not hasattr(row, "_on_end_edit")
        assert not hasattr(row, "_on_value_changed")

    def test_external_change_updates_widget_small(self, no_ui):
        """External USD edit (``adapter.fire_change``) lands through the
        model's ``_on_backing_changed`` → ``_on_model_value_changed``
        pipeline and refreshes the StringField display with the new
        tuple repr."""
        from ovui_widgets.property.attribute_row import ArrayAttributeRow
        adapter = _TrackingAdapter({"arr": (1.0,)})
        prop = _make_array_prop(is_big_array=False)
        row = ArrayAttributeRow(prop, adapter)
        row._widget = _FakeStringWidget("(1.0,)")
        adapter._values["arr"] = (1.0, 2.0, 3.0)
        adapter.fire_change()
        assert row._widget.model.get_value_as_string() == "(1.0, 2.0, 3.0)"

    def test_external_change_updates_widget_big(self, no_ui):
        """External edit to a big-flagged array refreshes as ``"[N items]"``
        — the flag is frozen on the metadata at build time, so a 20→25
        length change still renders the "[N items]" template with the
        new count."""
        from ovui_widgets.property.attribute_row import ArrayAttributeRow
        adapter = _TrackingAdapter({"arr": tuple(range(20))})
        prop = _make_array_prop(is_big_array=True)
        row = ArrayAttributeRow(prop, adapter)
        row._widget = _FakeStringWidget("[20 items]")
        adapter._values["arr"] = tuple(range(25))
        adapter.fire_change()
        assert row._widget.model.get_value_as_string() == "[25 items]"

    def test_no_adapter_set_value_during_construction(self, no_ui):
        """Constructing the row reads the initial value but never writes
        it back. Regression guard against a mistaken ``set_value`` call
        in ``__init__`` that would dirty the stage on open."""
        from ovui_widgets.property.attribute_row import ArrayAttributeRow
        adapter = _TrackingAdapter({"arr": (1, 2, 3)})
        prop = _make_array_prop()
        ArrayAttributeRow(prop, adapter)
        assert adapter.calls == []


class TestArrayLiveBuild:
    """Build a real ``ArrayAttributeRow`` under a ``ui.Window`` so the
    read-only ``StringField`` is actually instantiated.
    """

    def _build(self, window_name, *, value, is_big):
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import ArrayAttributeRow
        prop = _make_array_prop(name="arr", is_big_array=is_big)
        adapter = MockPropertyAdapter(paths=["/P"], attributes={"arr": prop})
        adapter.set_path_value("/P", "arr", value)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return ArrayAttributeRow(prop, adapter)

    def test_small_array_shows_full_tuple(self):
        """Step 3.8 done-signal bullet: small array renders as the full
        tuple repr (not elided)."""
        row = self._build(
            "test_arr_small", value=(1.0, 2.0, 3.0), is_big=False,
        )
        assert row._widget.model.get_value_as_string() == "(1.0, 2.0, 3.0)"

    def test_big_array_shows_n_items(self):
        """Step 3.8 done-signal bullet: big array renders as
        ``"[N items]"`` without expanding the element list."""
        values = tuple(range(20))
        row = self._build("test_arr_big", value=values, is_big=True)
        assert row._widget.model.get_value_as_string() == "[20 items]"

    def test_string_field_is_readonly(self):
        """The row's input widget is a read-only StringField — the user
        can copy the display string but not type a new one."""
        import omni.ui as ui
        row = self._build("test_arr_readonly", value=(1,), is_big=False)
        assert row._widget is not None
        assert isinstance(row._widget, ui.StringField)
        assert row._widget.read_only is True

    def test_empty_array_shows_empty_tuple(self):
        """Zero-length authored array renders as ``"()"`` — distinct
        from the ``""`` (unauthored) fallback path."""
        row = self._build("test_arr_empty", value=(), is_big=False)
        assert row._widget.model.get_value_as_string() == "()"

    def test_mixed_overlay_hidden_for_single(self):
        row = self._build(
            "test_arr_mixed_hidden", value=(1, 2, 3), is_big=False,
        )
        assert row._overlay is not None
        assert row._overlay.visible is False


class TestArrayAttributeRowRegistration:
    """Registration-level sanity: dispatch for ``type_name="array"``
    routes to ``ArrayAttributeRow`` via the factory forwarder.
    """

    def test_factory_dispatches_array_to_array_row(self, no_ui):
        from ovui_widgets.property.attribute_row import (
            ArrayAttributeRow,
            build_attribute_row,
        )
        prop = _make_array_prop()
        row = build_attribute_row(prop, _TrackingAdapter({"arr": ()}))
        assert isinstance(row, ArrayAttributeRow)


# ---------------------------------------------------------------------------
# Step 4.1 — Soft-range wiring into FloatDrag / IntDrag widgets
# ---------------------------------------------------------------------------
# the property inspector 4.1 (property attribute builder behavior). When ``metadata.soft_range_min``
# / ``soft_range_max`` are set, every FloatDrag/IntDrag the row builds
# must surface them as the widget's ``min`` / ``max`` so the drag handle
# respects the documented soft bounds. When neither bound is set, the
# widget stays at its omni.ui default (unbounded ``±DBL_MAX`` for
# FloatDrag, ``±INT64_MAX`` for IntDrag).


class TestDragKwargsFromMetadata:
    """Pure-function tests for the ``_drag_kwargs_from_metadata`` helper.

    The helper strips ``None`` entries before emitting the widget kwargs —
    passing ``min=None`` to ``ui.FloatDrag`` would fail the pybind11 float
    coercion. Tests pin the helper's shape so every downstream row can
    rely on ``**expansion`` cleanly.
    """

    def test_none_ranges_produce_empty_kwargs(self):
        from ovui_widgets.property.attribute_row import _drag_kwargs_from_metadata
        prop = _make_prop()
        assert _drag_kwargs_from_metadata(prop) == {}

    def test_only_min_set(self):
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.property.attribute_row import _drag_kwargs_from_metadata
        prop = AttributeMetadata(
            name="x", display_name="X", type_name="float",
            value_type=float, group="G", soft_range_min=0.5,
        )
        assert _drag_kwargs_from_metadata(prop) == {"min": 0.5}

    def test_only_max_set(self):
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.property.attribute_row import _drag_kwargs_from_metadata
        prop = AttributeMetadata(
            name="x", display_name="X", type_name="float",
            value_type=float, group="G", soft_range_max=10.0,
        )
        assert _drag_kwargs_from_metadata(prop) == {"max": 10.0}

    def test_both_bounds_set(self):
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.property.attribute_row import _drag_kwargs_from_metadata
        prop = AttributeMetadata(
            name="x", display_name="X", type_name="float",
            value_type=float, group="G",
            soft_range_min=0.0, soft_range_max=1.0,
        )
        assert _drag_kwargs_from_metadata(prop) == {"min": 0.0, "max": 1.0}

    def test_hard_range_not_in_widget_kwargs(self):
        """Hard range drives the model clamp, not the widget bounds —
        the widget only cares about the soft range (drag behaviour)."""
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.property.attribute_row import _drag_kwargs_from_metadata
        prop = AttributeMetadata(
            name="x", display_name="X", type_name="float",
            value_type=float, group="G",
            hard_range_min=0.0, hard_range_max=1.0,
        )
        # No soft range set → helper returns empty; hard bounds are
        # intentionally NOT surfaced as widget kwargs.
        assert _drag_kwargs_from_metadata(prop) == {}


class TestFloatRowSoftRangeLiveBuild:
    """Live-build tests for ``FloatAttributeRow`` soft-range wiring.

    Builds the row under a ``ui.Window`` so the real ``ui.FloatDrag`` is
    instantiated, then asserts on ``widget.min`` / ``widget.max`` which
    omni.ui surfaces as instance attributes.
    """

    def _build(self, *, soft_min=None, soft_max=None, window_name):
        import omni.ui as ui
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import FloatAttributeRow
        prop = AttributeMetadata(
            name="radius", display_name="Radius",
            type_name="float", value_type=float, group="G",
            soft_range_min=soft_min, soft_range_max=soft_max,
        )
        adapter = MockPropertyAdapter(paths=["/P"], attributes={"radius": prop})
        adapter.set_path_value("/P", "radius", 0.5)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return FloatAttributeRow(prop, adapter)

    def test_soft_range_bounds_reach_widget(self):
        """Step 4.1 done-signal bullet: soft range [0, 1] → widget.min=0,
        widget.max=1."""
        row = self._build(
            soft_min=0.0, soft_max=1.0, window_name="test_float_soft_range",
        )
        assert row._widget.min == pytest.approx(0.0)
        assert row._widget.max == pytest.approx(1.0)

    def test_no_range_leaves_widget_unbounded(self):
        """With no soft range set, the widget keeps omni.ui's default
        ``±DBL_MAX`` bounds — preserves pre-4.1 behaviour."""
        row = self._build(window_name="test_float_unbounded")
        # Default FloatDrag spans a gigantic range — not exactly
        # float('inf') but several orders of magnitude larger than any
        # documented attribute.
        assert row._widget.min < -1e100
        assert row._widget.max > 1e100

    def test_only_min_set_leaves_max_unbounded(self):
        row = self._build(
            soft_min=0.0, soft_max=None, window_name="test_float_min_only",
        )
        assert row._widget.min == pytest.approx(0.0)
        assert row._widget.max > 1e100


class TestIntRowSoftRangeLiveBuild:
    """Live-build tests for ``IntAttributeRow`` soft-range wiring."""

    def _build(self, *, soft_min=None, soft_max=None, window_name):
        import omni.ui as ui
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import IntAttributeRow
        prop = AttributeMetadata(
            name="count", display_name="Count",
            type_name="int", value_type=int, group="G",
            soft_range_min=soft_min, soft_range_max=soft_max,
        )
        adapter = MockPropertyAdapter(paths=["/P"], attributes={"count": prop})
        adapter.set_path_value("/P", "count", 5)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return IntAttributeRow(prop, adapter)

    def test_soft_range_bounds_reach_widget(self):
        row = self._build(
            soft_min=0, soft_max=10, window_name="test_int_soft_range",
        )
        assert row._widget.min == 0
        assert row._widget.max == 10

    def test_no_range_leaves_widget_unbounded(self):
        row = self._build(window_name="test_int_unbounded")
        # Default IntDrag spans ±INT64_MAX.
        assert row._widget.min < -(1 << 60)
        assert row._widget.max > (1 << 60)


class TestVecFloatRowSoftRangeLiveBuild:
    """Soft range reaches every channel FloatDrag in a float vector row."""

    def _build(self, *, n, soft_min, soft_max, window_name):
        import omni.ui as ui
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import (
            Vec2FloatAttributeRow,
            Vec3FloatAttributeRow,
            Vec4FloatAttributeRow,
        )
        cls = {2: Vec2FloatAttributeRow, 3: Vec3FloatAttributeRow,
               4: Vec4FloatAttributeRow}[n]
        prop = AttributeMetadata(
            name="v", display_name="V",
            type_name=f"float{n}", value_type=tuple, group="G",
            soft_range_min=soft_min, soft_range_max=soft_max,
        )
        adapter = MockPropertyAdapter(paths=["/P"], attributes={"v": prop})
        adapter.set_path_value("/P", "v", tuple(0.0 for _ in range(n)))
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return cls(prop, adapter)

    @pytest.mark.parametrize("n", [2, 3, 4])
    def test_every_channel_widget_respects_soft_range(self, n):
        row = self._build(
            n=n, soft_min=-1.0, soft_max=1.0,
            window_name=f"test_vec{n}_soft_range",
        )
        for w in row._widgets:
            assert w.min == pytest.approx(-1.0)
            assert w.max == pytest.approx(1.0)


class TestVecIntRowSoftRangeLiveBuild:
    """Soft range reaches every channel IntDrag in an int vector row."""

    def _build(self, *, n, soft_min, soft_max, window_name):
        import omni.ui as ui
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import (
            Vec2IntAttributeRow,
            Vec3IntAttributeRow,
            Vec4IntAttributeRow,
        )
        cls = {2: Vec2IntAttributeRow, 3: Vec3IntAttributeRow,
               4: Vec4IntAttributeRow}[n]
        prop = AttributeMetadata(
            name="iv", display_name="IV",
            type_name=f"int{n}", value_type=tuple, group="G",
            soft_range_min=soft_min, soft_range_max=soft_max,
        )
        adapter = MockPropertyAdapter(paths=["/P"], attributes={"iv": prop})
        adapter.set_path_value("/P", "iv", tuple(0 for _ in range(n)))
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return cls(prop, adapter)

    @pytest.mark.parametrize("n", [2, 3, 4])
    def test_every_channel_widget_respects_soft_range(self, n):
        row = self._build(
            n=n, soft_min=0, soft_max=100,
            window_name=f"test_ivec{n}_soft_range",
        )
        for w in row._widgets:
            assert w.min == 0
            assert w.max == 100


class TestColorRowSoftRangeLiveBuild:
    """Soft range reaches every R/G/B(/A) channel in a colour row."""

    def _build(self, *, n, soft_min, soft_max, window_name):
        import omni.ui as ui
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import (
            Color3fAttributeRow,
            Color4fAttributeRow,
        )
        cls = {3: Color3fAttributeRow, 4: Color4fAttributeRow}[n]
        prop = AttributeMetadata(
            name="c", display_name="C",
            type_name=f"color{n}f", value_type=tuple, group="G",
            soft_range_min=soft_min, soft_range_max=soft_max,
        )
        adapter = MockPropertyAdapter(paths=["/P"], attributes={"c": prop})
        adapter.set_path_value("/P", "c", tuple(0.5 for _ in range(n)))
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return cls(prop, adapter)

    @pytest.mark.parametrize("n", [3, 4])
    def test_every_channel_widget_respects_soft_range(self, n):
        row = self._build(
            n=n, soft_min=0.0, soft_max=1.0,
            window_name=f"test_color{n}_soft_range",
        )
        for w in row._widgets:
            assert w.min == pytest.approx(0.0)
            assert w.max == pytest.approx(1.0)


class TestMatrixRowSoftRangeLiveBuild:
    """Soft range reaches every cell FloatDrag in a matrix row."""

    def _build(self, *, n_dim, soft_min, soft_max, window_name):
        import omni.ui as ui
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        prop = AttributeMetadata(
            name="m", display_name="M",
            type_name=f"matrix{n_dim}d", value_type=tuple, group="G",
            soft_range_min=soft_min, soft_range_max=soft_max,
        )
        adapter = MockPropertyAdapter(paths=["/P"], attributes={"m": prop})
        adapter.set_path_value("/P", "m", tuple(
            0.0 for _ in range(n_dim * n_dim)
        ))
        w = ui.Window(window_name, width=400, height=150)
        with w.frame:
            return MatrixAttributeRow(prop, adapter, n_dim=n_dim)

    def test_3x3_cells_respect_soft_range(self):
        row = self._build(
            n_dim=3, soft_min=-2.0, soft_max=2.0,
            window_name="test_matrix_soft_range",
        )
        for w in row._widgets:
            assert w.min == pytest.approx(-2.0)
            assert w.max == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Step 4.2 — readonly / not-authored state wiring
# ---------------------------------------------------------------------------


class TestLabelKwargsFromMetadata:
    """Step 4.2 — ``_label_kwargs_from_metadata`` packages the
    ``style_type_name_override`` / ``name`` kwargs each row's attribute
    label picks up. The style override is always ``Property.LabelColumn``
    so the ``::not_authored`` state selector can attach; ``name`` toggles
    between ``""`` (authored) and ``"not_authored"`` (schema default)."""

    def test_authored_empty_name(self):
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.property.attribute_row import _label_kwargs_from_metadata
        prop = AttributeMetadata(
            name="x", display_name="X", type_name="float",
            value_type=float, group="G",
        )
        assert _label_kwargs_from_metadata(prop) == {
            "style_type_name_override": "Property.LabelColumn",
            "name": "",
        }

    def test_not_authored_sets_state_name(self):
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.property.attribute_row import _label_kwargs_from_metadata
        prop = AttributeMetadata(
            name="x", display_name="X", type_name="float",
            value_type=float, group="G", is_authored=False,
        )
        assert _label_kwargs_from_metadata(prop) == {
            "style_type_name_override": "Property.LabelColumn",
            "name": "not_authored",
        }

    def test_label_style_override_constant(self):
        """The style override is ``Property.LabelColumn`` verbatim — pins
        the selector the row labels attach to so a rename in
        ``ovui_widgets.property/style.py`` trips this test rather than silently
        drifting."""
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.property.attribute_row import _label_kwargs_from_metadata
        prop = AttributeMetadata(
            name="x", display_name="X", type_name="float",
            value_type=float, group="G",
        )
        assert (
            _label_kwargs_from_metadata(prop)["style_type_name_override"]
            == "Property.LabelColumn"
        )


class TestReadonlyWidgetState:
    """Step 4.2 — every editable row sets ``widget.enabled = not
    model.is_readonly`` at build time so time-sampled and locked
    attributes render greyed-out and non-interactive.

    Display-only rows (``RelationshipAttributeRow``, ``ArrayAttributeRow``)
    skip this wiring because their StringField is already
    ``read_only=True`` — ``enabled`` is left at its default ``True`` so
    the user can still copy the rendered text; the adapter layer never
    sees a write either way.
    """

    def _build_row(self, cls_name, *, is_time_sampled=False, is_locked=False,
                   type_name="float", value_type=float, window_name,
                   extra_kwargs=None):
        import omni.ui as ui
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property import attribute_row as ar
        cls = getattr(ar, cls_name)
        prop = AttributeMetadata(
            name="a", display_name="A", type_name=type_name,
            value_type=value_type, group="G",
            is_time_sampled=is_time_sampled, is_locked=is_locked,
            **(extra_kwargs or {}),
        )
        adapter = MockPropertyAdapter(paths=["/P"], attributes={"a": prop})
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return cls(prop, adapter)

    def test_float_row_time_sampled_widget_disabled(self):
        row = self._build_row(
            "FloatAttributeRow", is_time_sampled=True,
            window_name="test_float_ts_disabled",
        )
        assert row._widget.enabled is False

    def test_float_row_locked_widget_disabled(self):
        row = self._build_row(
            "FloatAttributeRow", is_locked=True,
            window_name="test_float_locked_disabled",
        )
        assert row._widget.enabled is False

    def test_float_row_default_widget_enabled(self):
        row = self._build_row(
            "FloatAttributeRow",
            window_name="test_float_default_enabled",
        )
        assert row._widget.enabled is True

    def test_int_row_locked_widget_disabled(self):
        row = self._build_row(
            "IntAttributeRow", type_name="int", value_type=int,
            is_locked=True, window_name="test_int_locked_disabled",
        )
        assert row._widget.enabled is False

    def test_string_row_time_sampled_widget_disabled(self):
        row = self._build_row(
            "StringAttributeRow", type_name="string", value_type=str,
            is_time_sampled=True,
            window_name="test_str_ts_disabled",
        )
        assert row._widget.enabled is False

    def test_bool_row_locked_widget_disabled(self):
        row = self._build_row(
            "BoolAttributeRow", type_name="bool", value_type=bool,
            is_locked=True, window_name="test_bool_locked_disabled",
        )
        assert row._widget.enabled is False

    @pytest.mark.parametrize(
        ("cls_name", "type_name", "n"),
        [
            ("Vec2FloatAttributeRow", "float2", 2),
            ("Vec3FloatAttributeRow", "float3", 3),
            ("Vec4FloatAttributeRow", "float4", 4),
        ],
    )
    def test_vec_float_row_every_channel_disabled_when_readonly(
        self, cls_name, type_name, n,
    ):
        row = self._build_row(
            cls_name, type_name=type_name, value_type=tuple,
            is_time_sampled=True, window_name=f"test_{cls_name}_ts",
        )
        for widget in row._widgets:
            assert widget is not None
            assert widget.enabled is False

    @pytest.mark.parametrize(
        ("cls_name", "type_name", "n"),
        [
            ("Vec2IntAttributeRow", "int2", 2),
            ("Vec3IntAttributeRow", "int3", 3),
            ("Vec4IntAttributeRow", "int4", 4),
        ],
    )
    def test_vec_int_row_every_channel_disabled_when_readonly(
        self, cls_name, type_name, n,
    ):
        row = self._build_row(
            cls_name, type_name=type_name, value_type=tuple,
            is_locked=True, window_name=f"test_{cls_name}_locked",
        )
        for widget in row._widgets:
            assert widget is not None
            assert widget.enabled is False

    @pytest.mark.parametrize(
        ("cls_name", "type_name"),
        [
            ("Color3fAttributeRow", "color3f"),
            ("Color4fAttributeRow", "color4f"),
        ],
    )
    def test_color_row_every_channel_disabled_when_readonly(
        self, cls_name, type_name,
    ):
        row = self._build_row(
            cls_name, type_name=type_name, value_type=tuple,
            is_time_sampled=True, window_name=f"test_{cls_name}_ts",
        )
        for widget in row._widgets:
            assert widget is not None
            assert widget.enabled is False

    def test_matrix_row_every_cell_disabled_when_readonly(self):
        import omni.ui as ui
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        prop = AttributeMetadata(
            name="m", display_name="M", type_name="matrix3d",
            value_type=tuple, group="G", is_locked=True,
        )
        adapter = MockPropertyAdapter(paths=["/P"], attributes={"m": prop})
        adapter.set_path_value("/P", "m", tuple(0.0 for _ in range(9)))
        w = ui.Window("test_matrix_locked", width=400, height=150)
        with w.frame:
            row = MatrixAttributeRow(prop, adapter, n_dim=3)
        for widget in row._widgets:
            assert widget is not None
            assert widget.enabled is False

    def test_token_row_locked_widget_disabled(self):
        row = self._build_row(
            "TokenAttributeRow", type_name="token", value_type=str,
            is_locked=True, window_name="test_token_locked_disabled",
            extra_kwargs={"allowed_values": ["inherited", "invisible"]},
        )
        assert row._widget.enabled is False

    def test_asset_path_row_locked_widget_disabled(self):
        row = self._build_row(
            "AssetPathAttributeRow", type_name="asset", value_type=str,
            is_locked=True, window_name="test_asset_locked_disabled",
        )
        assert row._widget.enabled is False
        # The folder button is also disabled — no point opening a file
        # picker whose result can't be written.
        assert row._folder_button.enabled is False

    def test_asset_path_row_default_folder_button_enabled(self):
        row = self._build_row(
            "AssetPathAttributeRow", type_name="asset", value_type=str,
            window_name="test_asset_default_enabled",
        )
        assert row._widget.enabled is True
        assert row._folder_button.enabled is True


class TestNotAuthoredLabelStyle:
    """Step 4.2 — every row's attribute label carries
    ``style_type_name_override="Property.LabelColumn"`` and toggles its
    ``name`` between ``""`` (authored) and ``"not_authored"`` (schema
    default). The style selector
    ``Property.LabelColumn::not_authored`` in :mod:`ovui_widgets.property.style`
    dims the text so an unauthored attribute reads differently at a
    glance (property metadata behavior, the property inspector behavior).
    """

    def _build_row(self, cls_name, *, is_authored=True, type_name="float",
                   value_type=float, window_name, extra_kwargs=None):
        import omni.ui as ui
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property import attribute_row as ar
        cls = getattr(ar, cls_name)
        prop = AttributeMetadata(
            name="a", display_name="Label Text", type_name=type_name,
            value_type=value_type, group="G", is_authored=is_authored,
            **(extra_kwargs or {}),
        )
        adapter = MockPropertyAdapter(paths=["/P"], attributes={"a": prop})
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return cls(prop, adapter)

    def test_not_authored_label_name(self):
        row = self._build_row(
            "FloatAttributeRow", is_authored=False,
            window_name="test_float_not_authored",
        )
        assert row._label is not None
        assert row._label.name == "not_authored"
        assert row._label.style_type_name_override == "Property.LabelColumn"

    def test_authored_label_name_empty(self):
        row = self._build_row(
            "FloatAttributeRow",
            window_name="test_float_authored_default",
        )
        assert row._label is not None
        assert row._label.name == ""
        assert row._label.style_type_name_override == "Property.LabelColumn"

    @pytest.mark.parametrize(
        ("cls_name", "type_name", "value_type", "extra"),
        [
            ("FloatAttributeRow", "float", float, None),
            ("IntAttributeRow", "int", int, None),
            ("StringAttributeRow", "string", str, None),
            ("BoolAttributeRow", "bool", bool, None),
            ("Vec3FloatAttributeRow", "float3", tuple, None),
            ("Vec3IntAttributeRow", "int3", tuple, None),
            ("Color3fAttributeRow", "color3f", tuple, None),
            ("AssetPathAttributeRow", "asset", str, None),
            ("RelationshipAttributeRow", "relationship", tuple, None),
            ("ArrayAttributeRow", "array", tuple, None),
            (
                "TokenAttributeRow",
                "token",
                str,
                {"allowed_values": ["a", "b"]},
            ),
        ],
    )
    def test_every_row_label_carries_style_and_name(
        self, cls_name, type_name, value_type, extra,
    ):
        """Regression guard: every row type must route its display-name
        label through ``_label_kwargs_from_metadata`` so the muted state
        selector works uniformly. A new row class that forgets the
        helper will trip here rather than silently drifting to the
        default label colour."""
        row = self._build_row(
            cls_name, is_authored=False, type_name=type_name,
            value_type=value_type,
            window_name=f"test_{cls_name}_notauth_styling",
            extra_kwargs=extra,
        )
        assert row._label is not None, (
            f"{cls_name} must expose the attribute label as ._label"
        )
        assert row._label.name == "not_authored"
        assert row._label.style_type_name_override == "Property.LabelColumn"

    def test_matrix_row_not_authored_label(self):
        import omni.ui as ui
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        prop = AttributeMetadata(
            name="m", display_name="M", type_name="matrix3d",
            value_type=tuple, group="G", is_authored=False,
        )
        adapter = MockPropertyAdapter(paths=["/P"], attributes={"m": prop})
        adapter.set_path_value("/P", "m", tuple(0.0 for _ in range(9)))
        w = ui.Window("test_matrix_notauth", width=400, height=150)
        with w.frame:
            row = MatrixAttributeRow(prop, adapter, n_dim=3)
        assert row._label is not None
        assert row._label.name == "not_authored"
        assert row._label.style_type_name_override == "Property.LabelColumn"


class TestNotAuthoredStyleSelector:
    """Step 4.2 — ``Property.LabelColumn::not_authored`` selector is
    registered in :data:`ovui_widgets.property.style.PROPERTY_STYLES` so the
    state toggle on ``Label.name`` actually paints a different colour.
    """

    def test_selector_registered(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "Property.LabelColumn::not_authored" in PROPERTY_STYLES

    def test_selector_sets_color(self):
        """The selector must change ``color`` — anything else (font-size,
        padding, etc.) would break the visual contract."""
        from ovui_widgets.property.style import PROPERTY_STYLES
        style = PROPERTY_STYLES["Property.LabelColumn::not_authored"]
        assert "color" in style


# ---------------------------------------------------------------------------
# Step 8.1 — Property.ComponentSeparator between vec / colour / matrix cells
# ---------------------------------------------------------------------------
# the property inspector implementation §8.1 calls for a thin 1-px vertical line between adjacent
# channel drag widgets so X|Y|Z reads as three distinct fields rather than a
# single blob of digits. Tests pin:
#
# * The canonical count per row type — ``n - 1`` separators for an ``n``-
#   component vector/colour row; ``(n_dim - 1) * n_dim`` for a matrix row
#   (the inline cells per matrix row, summed across every matrix row).
# * Each rectangle's ``style_type_name_override`` is
#   ``"Property.ComponentSeparator"`` so the PROPERTY_STYLES entry actually
#   attaches (otherwise the rectangles would render with the default
#   black-fill fallback).
# * The ``Property.ComponentSeparator`` style is itself registered in
#   :data:`ovui_widgets.property.style.PROPERTY_STYLES` — the end-to-end wiring,
#   not just the widget-side plumbing.


class TestComponentSeparatorStyleRegistered:
    """The ``Property.ComponentSeparator`` type is registered in
    :data:`ovui_widgets.property.style.PROPERTY_STYLES`."""

    def test_style_type_registered(self):
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "Property.ComponentSeparator" in PROPERTY_STYLES

    def test_style_has_background_color(self):
        """The separator is a solid fill; without a ``background_color`` key
        the rectangle would be invisible against any backdrop."""
        from ovui_widgets.property.style import PROPERTY_STYLES
        style = PROPERTY_STYLES["Property.ComponentSeparator"]
        assert "background_color" in style

    def test_background_color_points_at_border_default(self):
        """PROPERTY_STYLES locks the fill to the shared ``border_default`` palette
        shade — same border colour the search field and swatch borders use
        so every "thin line" in the inspector reads with the same weight.
        """
        from ovui_widgets.property.style import PROPERTY_STYLES
        style = PROPERTY_STYLES["Property.ComponentSeparator"]
        assert style["background_color"] == "border_default"


class TestVecFloatRowSeparators:
    """Vec float rows insert ``n - 1`` separators between channel drags."""

    def _build(self, cls_name, window_name, value):
        import omni.ui as ui

        import ovui_widgets.property.attribute_row as ar
        from ovui_widgets.app.testing import MockPropertyAdapter
        prop = _make_prop(
            name="v", value_type=tuple,
            type_name=f"float{len(value)}",
        )
        adapter = MockPropertyAdapter(paths=["/P1"], attributes={"v": prop})
        adapter.set_path_value("/P1", "v", value)
        cls = getattr(ar, cls_name)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return cls(prop, adapter)

    def test_vec2_has_one_separator(self):
        row = self._build(
            "Vec2FloatAttributeRow", "test_vec2_float_sep", (0.1, 0.2),
        )
        assert len(row._separators) == 1

    def test_vec3_has_two_separators(self):
        row = self._build(
            "Vec3FloatAttributeRow", "test_vec3_float_sep", (0.1, 0.2, 0.3),
        )
        assert len(row._separators) == 2

    def test_vec4_has_three_separators(self):
        row = self._build(
            "Vec4FloatAttributeRow", "test_vec4_float_sep",
            (0.1, 0.2, 0.3, 0.4),
        )
        assert len(row._separators) == 3

    def test_separators_use_component_separator_style(self):
        """Every entry in ``_separators`` carries the ``Property.ComponentSeparator`` style type
        so the rectangle actually renders with the registered fill."""
        row = self._build(
            "Vec3FloatAttributeRow", "test_vec3_float_sep_style",
            (0.1, 0.2, 0.3),
        )
        for sep in row._separators:
            assert sep.style_type_name_override == "Property.ComponentSeparator"


class TestVecIntRowSeparators:
    """Vec int rows insert ``n - 1`` separators between integer channel
    drags — parity with the float row family.
    """

    def _build(self, cls_name, window_name, value):
        import omni.ui as ui

        import ovui_widgets.property.attribute_row as ar
        from ovui_widgets.app.testing import MockPropertyAdapter
        prop = _make_prop(
            name="v", value_type=tuple,
            type_name=f"int{len(value)}",
        )
        adapter = MockPropertyAdapter(paths=["/P1"], attributes={"v": prop})
        adapter.set_path_value("/P1", "v", value)
        cls = getattr(ar, cls_name)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return cls(prop, adapter)

    def test_ivec2_has_one_separator(self):
        row = self._build(
            "Vec2IntAttributeRow", "test_ivec2_sep", (1, 2),
        )
        assert len(row._separators) == 1

    def test_ivec3_has_two_separators(self):
        row = self._build(
            "Vec3IntAttributeRow", "test_ivec3_sep", (1, 2, 3),
        )
        assert len(row._separators) == 2

    def test_ivec4_has_three_separators(self):
        row = self._build(
            "Vec4IntAttributeRow", "test_ivec4_sep", (1, 2, 3, 4),
        )
        assert len(row._separators) == 3

    def test_separators_use_component_separator_style(self):
        row = self._build(
            "Vec4IntAttributeRow", "test_ivec4_sep_style", (1, 2, 3, 4),
        )
        for sep in row._separators:
            assert sep.style_type_name_override == "Property.ComponentSeparator"


class TestColorRowSeparators:
    """Colour rows insert ``n - 1`` separators between R/G/B(/A) drags — the
    terminal swatch is NOT preceded by a separator because it is a distinct
    element (preview tile), not another channel.
    """

    def _build(self, cls_name, window_name, value):
        import omni.ui as ui

        import ovui_widgets.property.attribute_row as ar
        from ovui_widgets.app.testing import MockPropertyAdapter
        prop = _make_prop(
            name="c", value_type=tuple,
            type_name="color3f" if len(value) == 3 else "color4f",
        )
        adapter = MockPropertyAdapter(paths=["/P1"], attributes={"c": prop})
        adapter.set_path_value("/P1", "c", value)
        cls = getattr(ar, cls_name)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return cls(prop, adapter)

    def test_color3_has_two_separators(self):
        """Three channels → two separators (R|G, G|B). No separator in
        front of the swatch tile."""
        row = self._build(
            "Color3fAttributeRow", "test_color3_sep", (0.1, 0.2, 0.3),
        )
        assert len(row._separators) == 2

    def test_color4_has_three_separators(self):
        """Four channels → three separators (R|G, G|B, B|A). No separator
        in front of the swatch tile."""
        row = self._build(
            "Color4fAttributeRow", "test_color4_sep",
            (0.1, 0.2, 0.3, 0.4),
        )
        assert len(row._separators) == 3

    def test_color3_separators_use_component_separator_style(self):
        row = self._build(
            "Color3fAttributeRow", "test_color3_sep_style",
            (0.1, 0.2, 0.3),
        )
        for sep in row._separators:
            assert sep.style_type_name_override == "Property.ComponentSeparator"

    def test_color4_separators_use_component_separator_style(self):
        row = self._build(
            "Color4fAttributeRow", "test_color4_sep_style",
            (0.1, 0.2, 0.3, 0.4),
        )
        for sep in row._separators:
            assert sep.style_type_name_override == "Property.ComponentSeparator"


class TestMatrixRowSeparators:
    """Matrix rows insert ``n_dim - 1`` separators per matrix row, across
    ``n_dim`` rows — totalling ``(n_dim - 1) * n_dim`` separators.

    Separators only sit between inline cells on the same row; no
    horizontal separator between matrix rows (the outer ``ui.VStack``
    handles that visually).
    """

    def _build(self, n_dim, window_name):
        import omni.ui as ui
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        prop = AttributeMetadata(
            name="m", display_name="M",
            type_name=f"matrix{n_dim}d", value_type=tuple, group="G",
        )
        adapter = MockPropertyAdapter(paths=["/P1"], attributes={"m": prop})
        adapter.set_path_value("/P1", "m", tuple(0.0 for _ in range(n_dim * n_dim)))
        w = ui.Window(window_name, width=400, height=150)
        with w.frame:
            return MatrixAttributeRow(prop, adapter, n_dim=n_dim)

    def test_matrix2_has_two_separators(self):
        """2×2 matrix → (2-1) separators × 2 rows = 2."""
        row = self._build(2, "test_matrix2_sep")
        assert len(row._separators) == 2

    def test_matrix3_has_six_separators(self):
        """3×3 matrix → (3-1) separators × 3 rows = 6."""
        row = self._build(3, "test_matrix3_sep")
        assert len(row._separators) == 6

    def test_matrix4_has_twelve_separators(self):
        """4×4 matrix → (4-1) separators × 4 rows = 12."""
        row = self._build(4, "test_matrix4_sep")
        assert len(row._separators) == 12

    def test_matrix_separators_use_component_separator_style(self):
        row = self._build(3, "test_matrix3_sep_style")
        for sep in row._separators:
            assert sep.style_type_name_override == "Property.ComponentSeparator"


class TestVecRowSeparatorRebuildResets:
    """``_build_ui`` resets ``_separators`` before appending so a forced
    rebuild (rare — the builder table rebuilds the row rather than calling
    ``_build_ui`` a second time, but the guard matters for the headless
    :class:`_ColorFloatRow` path where the subclass's post-init swap of
    ``_channel_letters`` happens AFTER ``_build_ui`` runs once).
    """

    def test_second_build_does_not_compound_separator_count(self):
        """A second ``_build_ui`` call on a Vec3 row still produces two
        separators — not four — so a forced rebuild keeps the invariant.
        """
        import omni.ui as ui

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import Vec3FloatAttributeRow
        prop = _make_prop(
            name="v", value_type=tuple, type_name="float3",
        )
        adapter = MockPropertyAdapter(paths=["/P1"], attributes={"v": prop})
        adapter.set_path_value("/P1", "v", (0.1, 0.2, 0.3))
        w = ui.Window("test_vec3_sep_rebuild", width=400, height=60)
        with w.frame:
            row = Vec3FloatAttributeRow(prop, adapter)
            row._build_ui()  # rebuild once more
        assert len(row._separators) == 2

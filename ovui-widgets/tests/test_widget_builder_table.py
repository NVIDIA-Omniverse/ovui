# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for WidgetBuilderTable — Step 1.2.

Covers the four done-signal bullets from the property inspector 1.2:

* ``register`` returns a removable subscription
* ``build()`` dispatches to the registered builder
* unknown type falls back to the read-only fallback row
* duplicate ``register`` raises

Plus edge anchors: built-in registrations (10 type_names), public
export, idempotent cancel, cancel-after-overwrite safety, and smoke
tests for each of the five built-in builder wrapper functions.
"""

from typing import Any, List

import pytest
from ovui_data_adapters.common import AttributeMetadata

from ovui_widgets.property.builders import WidgetBuilderTable
from ovui_widgets.property.builders.builder_table import _BuilderSubscription

# ---------------------------------------------------------------------------
# Minimal adapter that records calls (same shape as test_attribute_rows.py)
# ---------------------------------------------------------------------------


class _TrackingSub:
    def __init__(self, subscribers, callback):
        self._subscribers = subscribers
        self._callback = callback

    def cancel(self):
        if self._subscribers is None:
            return
        try:
            self._subscribers.remove(self._callback)
        except ValueError:
            pass
        self._subscribers = None
        self._callback = None


class _TrackingAdapter:
    def __init__(self, values=None):
        self._values = dict(values) if values else {}
        self.calls: List[tuple] = []
        self._subscribers: List[Any] = []

    def get_value(self, attr_name):
        return self._values.get(attr_name)

    def begin_edit(self, attr_name):
        self.calls.append(("begin_edit", attr_name))

    def set_value(self, attr_name, value):
        self._values[attr_name] = value
        self.calls.append(("set_value", attr_name, value))

    def end_edit(self, attr_name):
        self.calls.append(("end_edit", attr_name))

    def is_ambiguous(self, attr_name):
        return False

    def get_resolved_asset_path(self, attr_name):
        """Matches the :class:`PropertyAdapter` ABC default. Step 3.6's
        asset builder calls this during row construction; without it the
        stub adapter would miss the attribute access."""
        return None

    def subscribe_changes(self, callback):
        self._subscribers.append(callback)
        return _TrackingSub(self._subscribers, callback)


def _make_prop(name="attr", display_name=None, value_type=float, type_name="float", group="X"):
    return AttributeMetadata(
        name=name,
        display_name=display_name or name,
        type_name=type_name,
        value_type=value_type,
        group=group,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def builder_table():
    """Snapshot/restore _TABLE so tests cannot bleed state into one another.

    Safer than relying on subscription.cancel() because it tolerates tests
    that register without cancelling, or cancel twice.
    """
    snapshot = dict(WidgetBuilderTable._TABLE)
    yield WidgetBuilderTable
    WidgetBuilderTable._TABLE.clear()
    WidgetBuilderTable._TABLE.update(snapshot)


@pytest.fixture
def no_ui(monkeypatch):
    """Suppress ``_build_ui`` on all row classes so builder-wrapper tests
    can instantiate rows outside of an omni.ui layout context.
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
# Public export and built-in registrations
# ---------------------------------------------------------------------------


class TestPublicExport:
    def test_import_from_package(self):
        from ovui_widgets.property.builders import WidgetBuilderTable as A
        from ovui_widgets.property.builders.builder_table import WidgetBuilderTable as B
        assert A is B

    def test_all_contains_widget_builder_table(self):
        import ovui_widgets.property.builders as m
        assert "WidgetBuilderTable" in m.__all__


class TestBuiltInRegistrations:
    """Anchor the Step 1.2 registration list against accidental drift."""

    def test_four_scalar_type_names_registered(self):
        for type_name in ("float", "int", "bool", "string"):
            assert type_name in WidgetBuilderTable._TABLE, (
                f"scalar type_name {type_name!r} should be registered"
            )

    def test_five_vec3_type_names_registered(self):
        """Step 3.4 moved ``color3f`` out of vec3 into the new colour builder,
        so the plain vec3 list is five names (was six in Steps 1.2–3.3)."""
        for type_name in ("float3", "double3", "normal3f", "point3f", "vector3f"):
            assert type_name in WidgetBuilderTable._TABLE, (
                f"vec3 type_name {type_name!r} should be registered"
            )

    def test_token_registered_to_token_builder_step_3_3(self):
        """Step 3.3 replaces the Step-1.3 ``token → build_string``
        shortcut with a proper ``build_token`` dispatcher (ComboBox when
        ``allowed_values`` is set, StringField fallback otherwise)."""
        from ovui_widgets.property.builders.token import build_token
        assert WidgetBuilderTable._TABLE.get("token") is build_token

    def test_all_five_vec3_share_the_same_builder(self):
        """Step 3.4 moved ``color3f`` to ``build_color3``; the remaining five
        vec3 type names still share ``build_vec3`` (so any future tweak to
        the plain vec3 row lands consistently on all of them)."""
        from ovui_widgets.property.builders.vec import build_vec3
        for type_name in ("float3", "double3", "normal3f", "point3f", "vector3f"):
            assert WidgetBuilderTable._TABLE[type_name] is build_vec3


# ---------------------------------------------------------------------------
# Done signal #1: register returns a removable subscription
# ---------------------------------------------------------------------------


class TestRegister:
    def test_register_returns_subscription_with_cancel(self, builder_table):
        sub = builder_table.register("__test_type_A__", lambda *a, **k: None)
        assert isinstance(sub, _BuilderSubscription)
        assert hasattr(sub, "cancel")
        assert callable(sub.cancel)

    def test_register_adds_entry_to_table(self, builder_table):
        def spy(*a, **k):
            return None
        builder_table.register("__test_type_B__", spy)
        assert builder_table._TABLE["__test_type_B__"] is spy

    def test_cancel_removes_entry(self, builder_table):
        sub = builder_table.register("__test_type_C__", lambda *a, **k: None)
        assert "__test_type_C__" in builder_table._TABLE
        sub.cancel()
        assert "__test_type_C__" not in builder_table._TABLE

    def test_cancel_is_idempotent(self, builder_table):
        sub = builder_table.register("__test_type_D__", lambda *a, **k: None)
        sub.cancel()
        # Second cancel must not raise and must not remove anything it did
        # not register.
        sub.cancel()
        assert "__test_type_D__" not in builder_table._TABLE

    def test_cancel_after_overwrite_does_not_evict_new_builder(self, builder_table):
        """Safety: if the slot has been re-registered by someone else, the
        original subscription's cancel must not remove the new builder.
        """
        def original(*a, **k):
            return "original"
        def replacement(*a, **k):
            return "replacement"

        sub_original = builder_table.register("__test_type_E__", original)
        sub_original.cancel()  # frees the slot
        sub_replacement = builder_table.register("__test_type_E__", replacement)
        # Now re-cancelling the original subscription (idempotent path) must
        # not evict the replacement.
        sub_original.cancel()
        assert builder_table._TABLE.get("__test_type_E__") is replacement
        # Clean up.
        sub_replacement.cancel()


# ---------------------------------------------------------------------------
# Done signal #2: build() dispatches to registered builder
# ---------------------------------------------------------------------------


class TestBuildDispatch:
    def test_build_dispatches_to_registered_builder(self, builder_table):
        calls: List[tuple] = []

        def spy(attr_name, metadata, adapter, **kwargs):
            calls.append((attr_name, metadata.type_name, adapter, kwargs))
            return "spy_result"

        sub = builder_table.register("__test_spy__", spy)
        try:
            adapter = _TrackingAdapter()
            prop = _make_prop(name="foo", type_name="__test_spy__")
            result = builder_table.build("foo", prop, adapter)
            assert result == "spy_result"
            assert calls == [("foo", "__test_spy__", adapter, {})]
        finally:
            sub.cancel()

    def test_build_forwards_kwargs_to_builder(self, builder_table):
        captured: List[dict] = []

        def spy(attr_name, metadata, adapter, **kwargs):
            captured.append(kwargs)
            return None

        sub = builder_table.register("__test_kwargs__", spy)
        try:
            adapter = _TrackingAdapter()
            prop = _make_prop(name="x", type_name="__test_kwargs__")
            builder_table.build("x", prop, adapter, app=object(), extra="payload")
            assert len(captured) == 1
            assert "app" in captured[0]
            assert captured[0]["extra"] == "payload"
        finally:
            sub.cancel()


# ---------------------------------------------------------------------------
# Done signal #3: unknown type falls back to read-only fallback row
# ---------------------------------------------------------------------------


class TestFallback:
    def test_unknown_type_routes_to_fallback(self, builder_table, no_ui):
        from ovui_widgets.property.attribute_row import _FallbackAttributeRow
        adapter = _TrackingAdapter()
        prop = _make_prop(name="mystery", type_name="__totally_unknown__")
        result = builder_table.build("mystery", prop, adapter)
        assert isinstance(result, _FallbackAttributeRow)

    def test_fallback_classmethod_creates_fallback_row(self, builder_table, no_ui):
        from ovui_widgets.property.attribute_row import _FallbackAttributeRow
        adapter = _TrackingAdapter()
        prop = _make_prop(name="x", type_name="anything")
        result = builder_table._fallback("x", prop, adapter)
        assert isinstance(result, _FallbackAttributeRow)


# ---------------------------------------------------------------------------
# Done signal #4: duplicate register raises
# ---------------------------------------------------------------------------


class TestDuplicateRegister:
    def test_duplicate_register_raises_value_error(self, builder_table):
        sub = builder_table.register("__dup_type__", lambda *a, **k: None)
        try:
            with pytest.raises(ValueError, match="already registered"):
                builder_table.register("__dup_type__", lambda *a, **k: None)
        finally:
            sub.cancel()

    def test_duplicate_register_against_builtin_raises(self, builder_table):
        """Registering against a built-in type_name (already present) must
        raise — this is the contract that forces callers to explicitly
        cancel before replacing a built-in.
        """
        with pytest.raises(ValueError, match="already registered"):
            builder_table.register("float", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# Smoke tests: each built-in builder wrapper produces the expected row
# ---------------------------------------------------------------------------


class TestScalarBuilders:
    def test_build_float_creates_float_row(self, no_ui):
        from ovui_widgets.property.attribute_row import FloatAttributeRow
        from ovui_widgets.property.builders.scalar import build_float
        adapter = _TrackingAdapter({"opacity": 0.5})
        prop = _make_prop(name="opacity", value_type=float, type_name="float")
        row = build_float("opacity", prop, adapter)
        assert isinstance(row, FloatAttributeRow)

    def test_build_int_creates_int_row(self, no_ui):
        from ovui_widgets.property.attribute_row import IntAttributeRow
        from ovui_widgets.property.builders.scalar import build_int
        adapter = _TrackingAdapter({"count": 7})
        prop = _make_prop(name="count", value_type=int, type_name="int")
        row = build_int("count", prop, adapter)
        assert isinstance(row, IntAttributeRow)

    def test_build_bool_creates_bool_row(self, no_ui):
        from ovui_widgets.property.attribute_row import BoolAttributeRow
        from ovui_widgets.property.builders.scalar import build_bool
        adapter = _TrackingAdapter({"visible": True})
        prop = _make_prop(name="visible", value_type=bool, type_name="bool")
        row = build_bool("visible", prop, adapter)
        assert isinstance(row, BoolAttributeRow)

    def test_build_string_creates_string_row(self, no_ui):
        from ovui_widgets.property.attribute_row import StringAttributeRow
        from ovui_widgets.property.builders.scalar import build_string
        adapter = _TrackingAdapter({"label": "hi"})
        prop = _make_prop(name="label", value_type=str, type_name="string")
        row = build_string("label", prop, adapter)
        assert isinstance(row, StringAttributeRow)


class TestVec3Builder:
    def test_build_vec3_creates_vec3_row(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3FloatAttributeRow
        from ovui_widgets.property.builders.vec import build_vec3
        adapter = _TrackingAdapter({"translate": (1.0, 2.0, 3.0)})
        prop = _make_prop(name="translate", value_type=tuple, type_name="float3")
        row = build_vec3("translate", prop, adapter)
        assert isinstance(row, Vec3FloatAttributeRow)

    def test_build_dispatch_for_normal3f(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3FloatAttributeRow
        adapter = _TrackingAdapter({"n": (0.0, 1.0, 0.0)})
        prop = _make_prop(name="n", value_type=tuple, type_name="normal3f")
        row = WidgetBuilderTable.build("n", prop, adapter)
        assert isinstance(row, Vec3FloatAttributeRow)


class TestIntVecBuilderRegistrations:
    """Step 3.2: ``int2/int3/int4`` register against the three ivec builders."""

    def test_int2_registered(self):
        from ovui_widgets.property.builders.ivec import build_ivec2
        assert WidgetBuilderTable._TABLE.get("int2") is build_ivec2

    def test_int3_registered(self):
        from ovui_widgets.property.builders.ivec import build_ivec3
        assert WidgetBuilderTable._TABLE.get("int3") is build_ivec3

    def test_int4_registered(self):
        from ovui_widgets.property.builders.ivec import build_ivec4
        assert WidgetBuilderTable._TABLE.get("int4") is build_ivec4

    def test_build_ivec2_creates_vec2_int_row(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec2IntAttributeRow
        from ovui_widgets.property.builders.ivec import build_ivec2
        adapter = _TrackingAdapter({"size": (4, 8)})
        prop = _make_prop(name="size", value_type=tuple, type_name="int2")
        row = build_ivec2("size", prop, adapter)
        assert isinstance(row, Vec2IntAttributeRow)

    def test_build_ivec3_creates_vec3_int_row(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3IntAttributeRow
        from ovui_widgets.property.builders.ivec import build_ivec3
        adapter = _TrackingAdapter({"grid": (1, 2, 3)})
        prop = _make_prop(name="grid", value_type=tuple, type_name="int3")
        row = build_ivec3("grid", prop, adapter)
        assert isinstance(row, Vec3IntAttributeRow)

    def test_build_ivec4_creates_vec4_int_row(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec4IntAttributeRow
        from ovui_widgets.property.builders.ivec import build_ivec4
        adapter = _TrackingAdapter({"box": (1, 2, 3, 4)})
        prop = _make_prop(name="box", value_type=tuple, type_name="int4")
        row = build_ivec4("box", prop, adapter)
        assert isinstance(row, Vec4IntAttributeRow)

    def test_build_dispatch_for_int2(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec2IntAttributeRow
        adapter = _TrackingAdapter({"size": (4, 8)})
        prop = _make_prop(name="size", value_type=tuple, type_name="int2")
        row = WidgetBuilderTable.build("size", prop, adapter)
        assert isinstance(row, Vec2IntAttributeRow)

    def test_build_dispatch_for_int3(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec3IntAttributeRow
        adapter = _TrackingAdapter({"grid": (1, 2, 3)})
        prop = _make_prop(name="grid", value_type=tuple, type_name="int3")
        row = WidgetBuilderTable.build("grid", prop, adapter)
        assert isinstance(row, Vec3IntAttributeRow)

    def test_build_dispatch_for_int4(self, no_ui):
        from ovui_widgets.property.attribute_row import Vec4IntAttributeRow
        adapter = _TrackingAdapter({"box": (1, 2, 3, 4)})
        prop = _make_prop(name="box", value_type=tuple, type_name="int4")
        row = WidgetBuilderTable.build("box", prop, adapter)
        assert isinstance(row, Vec4IntAttributeRow)


class TestTokenBuilderRegistration:
    """Step 3.3: ``token`` registers against ``build_token`` — a
    dispatcher that picks ``TokenAttributeRow`` (ComboBox) when
    ``allowed_values`` is set or ``StringAttributeRow`` (StringField)
    otherwise."""

    def test_token_registered_to_build_token(self):
        from ovui_widgets.property.builders.token import build_token
        assert WidgetBuilderTable._TABLE.get("token") is build_token

    def test_build_token_with_allowed_values_creates_token_row(self, no_ui):
        from ovui_widgets.property.attribute_row import TokenAttributeRow
        from ovui_widgets.property.builders.token import build_token
        adapter = _TrackingAdapter({"vis": "inherited"})
        prop = _make_prop(name="vis", value_type=str, type_name="token")
        prop.allowed_values = ["inherited", "invisible"]
        row = build_token("vis", prop, adapter)
        assert isinstance(row, TokenAttributeRow)

    def test_build_token_without_allowed_values_falls_back_to_string_row(self, no_ui):
        from ovui_widgets.property.attribute_row import StringAttributeRow
        from ovui_widgets.property.builders.token import build_token
        adapter = _TrackingAdapter({"p": "render"})
        prop = _make_prop(name="p", value_type=str, type_name="token")
        # No allowed_values — fallback expected.
        row = build_token("p", prop, adapter)
        assert isinstance(row, StringAttributeRow)

    def test_build_token_with_empty_allowed_list_falls_back(self, no_ui):
        """Empty list is treated the same as ``None`` — Kit's convention:
        an ``allowedTokens = []`` authored metadata is meaningless and
        should leave the UI as a free-form StringField."""
        from ovui_widgets.property.attribute_row import StringAttributeRow
        from ovui_widgets.property.builders.token import build_token
        adapter = _TrackingAdapter({"x": ""})
        prop = _make_prop(name="x", value_type=str, type_name="token")
        prop.allowed_values = []
        row = build_token("x", prop, adapter)
        assert isinstance(row, StringAttributeRow)

    def test_build_dispatch_for_token_with_allowed_values(self, no_ui):
        """End-to-end: ``WidgetBuilderTable.build("...", token-prop)`` picks
        up the token builder and produces a TokenAttributeRow when
        allowed_values is set."""
        from ovui_widgets.property.attribute_row import TokenAttributeRow
        adapter = _TrackingAdapter({"vis": "inherited"})
        prop = _make_prop(name="vis", value_type=str, type_name="token")
        prop.allowed_values = ["inherited", "invisible"]
        row = WidgetBuilderTable.build("vis", prop, adapter)
        assert isinstance(row, TokenAttributeRow)

    def test_build_dispatch_for_token_without_allowed_values(self, no_ui):
        from ovui_widgets.property.attribute_row import StringAttributeRow
        adapter = _TrackingAdapter({"name": "Hello"})
        prop = _make_prop(name="name", value_type=str, type_name="token")
        # Plain tokens (no allowedTokens) → StringField.
        row = WidgetBuilderTable.build("name", prop, adapter)
        assert isinstance(row, StringAttributeRow)

    def test_combobox_preselects_current_index(self, no_ui):
        """Picks the correct initial index from the current adapter value."""
        from ovui_widgets.property.builders.token import build_token
        adapter = _TrackingAdapter({"vis": "invisible"})
        prop = _make_prop(name="vis", value_type=str, type_name="token")
        prop.allowed_values = ["inherited", "invisible"]
        row = build_token("vis", prop, adapter)
        assert row._current_index() == 1

    def test_combobox_selection_writes_correct_value(self, no_ui):
        """Simulating a user pick via the row's ``_on_item_changed`` hook
        lands the selected token in ``adapter.set_value`` calls."""
        from ovui_widgets.property.builders.token import build_token
        from tests.test_attribute_rows import _FakeComboBoxItemModel
        adapter = _TrackingAdapter({"vis": "inherited"})
        prop = _make_prop(name="vis", value_type=str, type_name="token")
        prop.allowed_values = ["inherited", "invisible"]
        row = build_token("vis", prop, adapter)
        row._on_item_changed(_FakeComboBoxItemModel(1), None)
        assert adapter.calls == [
            ("begin_edit", "vis"),
            ("set_value", "vis", "invisible"),
            ("end_edit", "vis"),
        ]


class TestColorBuilderRegistrations:
    """Step 3.4: ``color3f/color3d/color4f/color4d`` register against the
    two colour builders (with a swatch preview rectangle alongside the
    R/G/B/A FloatDrags — see ``TestColor3fSwatch`` in
    ``test_attribute_rows.py``)."""

    def test_color3f_registered_to_build_color3(self):
        from ovui_widgets.property.builders.color import build_color3
        assert WidgetBuilderTable._TABLE.get("color3f") is build_color3

    def test_color3d_registered_to_build_color3(self):
        from ovui_widgets.property.builders.color import build_color3
        assert WidgetBuilderTable._TABLE.get("color3d") is build_color3

    def test_color4f_registered_to_build_color4(self):
        from ovui_widgets.property.builders.color import build_color4
        assert WidgetBuilderTable._TABLE.get("color4f") is build_color4

    def test_color4d_registered_to_build_color4(self):
        from ovui_widgets.property.builders.color import build_color4
        assert WidgetBuilderTable._TABLE.get("color4d") is build_color4

    def test_build_color3_creates_color3_row(self, no_ui):
        from ovui_widgets.property.attribute_row import Color3fAttributeRow
        from ovui_widgets.property.builders.color import build_color3
        adapter = _TrackingAdapter({"col": (0.5, 0.25, 0.125)})
        prop = _make_prop(name="col", value_type=tuple, type_name="color3f")
        row = build_color3("col", prop, adapter)
        assert isinstance(row, Color3fAttributeRow)

    def test_build_color4_creates_color4_row(self, no_ui):
        from ovui_widgets.property.attribute_row import Color4fAttributeRow
        from ovui_widgets.property.builders.color import build_color4
        adapter = _TrackingAdapter({"col": (0.5, 0.25, 0.125, 0.75)})
        prop = _make_prop(name="col", value_type=tuple, type_name="color4f")
        row = build_color4("col", prop, adapter)
        assert isinstance(row, Color4fAttributeRow)

    def test_build_dispatch_for_color3f(self, no_ui):
        """End-to-end: ``WidgetBuilderTable.build(... color3f)`` picks up the
        colour builder (not the plain vec3 row)."""
        from ovui_widgets.property.attribute_row import Color3fAttributeRow
        adapter = _TrackingAdapter({"col": (1.0, 0.5, 0.25)})
        prop = _make_prop(name="col", value_type=tuple, type_name="color3f")
        row = WidgetBuilderTable.build("col", prop, adapter)
        assert isinstance(row, Color3fAttributeRow)

    def test_build_dispatch_for_color3d(self, no_ui):
        from ovui_widgets.property.attribute_row import Color3fAttributeRow
        adapter = _TrackingAdapter({"col": (1.0, 0.5, 0.25)})
        prop = _make_prop(name="col", value_type=tuple, type_name="color3d")
        row = WidgetBuilderTable.build("col", prop, adapter)
        assert isinstance(row, Color3fAttributeRow)

    def test_build_dispatch_for_color4f(self, no_ui):
        from ovui_widgets.property.attribute_row import Color4fAttributeRow
        adapter = _TrackingAdapter({"col": (1.0, 0.5, 0.25, 0.5)})
        prop = _make_prop(name="col", value_type=tuple, type_name="color4f")
        row = WidgetBuilderTable.build("col", prop, adapter)
        assert isinstance(row, Color4fAttributeRow)

    def test_build_dispatch_for_color4d(self, no_ui):
        from ovui_widgets.property.attribute_row import Color4fAttributeRow
        adapter = _TrackingAdapter({"col": (0.0, 0.0, 0.0, 1.0)})
        prop = _make_prop(name="col", value_type=tuple, type_name="color4d")
        row = WidgetBuilderTable.build("col", prop, adapter)
        assert isinstance(row, Color4fAttributeRow)

    def test_color3f_not_registered_to_build_vec3(self):
        """Step 3.4 moves ``color3f`` out of the plain vec3 builder so the
        swatch appears. Regression guard — a future refactor that puts it
        back would break the swatch rendering."""
        from ovui_widgets.property.builders.vec import build_vec3
        assert WidgetBuilderTable._TABLE.get("color3f") is not build_vec3


class TestMatrixBuilderRegistrations:
    """Step 3.5: ``matrix2d/matrix3d/matrix4d`` register against three
    builder wrappers, each of which instantiates ``MatrixAttributeRow``
    with the correct ``n_dim``. USD only ships double-precision matrix
    types (no ``matrix2f/matrix3f/matrix4f``), so these three entries
    cover the complete matrix type surface — no half-precision fallback
    needed."""

    def test_matrix2d_registered_to_build_matrix2d(self):
        from ovui_widgets.property.builders.matrix import build_matrix2d
        assert WidgetBuilderTable._TABLE.get("matrix2d") is build_matrix2d

    def test_matrix3d_registered_to_build_matrix3d(self):
        from ovui_widgets.property.builders.matrix import build_matrix3d
        assert WidgetBuilderTable._TABLE.get("matrix3d") is build_matrix3d

    def test_matrix4d_registered_to_build_matrix4d(self):
        from ovui_widgets.property.builders.matrix import build_matrix4d
        assert WidgetBuilderTable._TABLE.get("matrix4d") is build_matrix4d

    def test_build_matrix2d_creates_matrix_row_n_dim_2(self, no_ui):
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        from ovui_widgets.property.builders.matrix import build_matrix2d
        adapter = _TrackingAdapter({"m": (1.0, 0.0, 0.0, 1.0)})
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix2d")
        row = build_matrix2d("m", prop, adapter)
        assert isinstance(row, MatrixAttributeRow)
        assert row._n_dim == 2
        assert row._n_cells == 4

    def test_build_matrix3d_creates_matrix_row_n_dim_3(self, no_ui):
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        from ovui_widgets.property.builders.matrix import build_matrix3d
        adapter = _TrackingAdapter({"m": tuple(0.0 for _ in range(9))})
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix3d")
        row = build_matrix3d("m", prop, adapter)
        assert isinstance(row, MatrixAttributeRow)
        assert row._n_dim == 3
        assert row._n_cells == 9

    def test_build_matrix4d_creates_matrix_row_n_dim_4(self, no_ui):
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        from ovui_widgets.property.builders.matrix import build_matrix4d
        adapter = _TrackingAdapter({"m": tuple(0.0 for _ in range(16))})
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix4d")
        row = build_matrix4d("m", prop, adapter)
        assert isinstance(row, MatrixAttributeRow)
        assert row._n_dim == 4
        assert row._n_cells == 16

    def test_build_dispatch_for_matrix2d(self, no_ui):
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        adapter = _TrackingAdapter({"m": (1.0, 0.0, 0.0, 1.0)})
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix2d")
        row = WidgetBuilderTable.build("m", prop, adapter)
        assert isinstance(row, MatrixAttributeRow)
        assert row._n_dim == 2

    def test_build_dispatch_for_matrix3d(self, no_ui):
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        adapter = _TrackingAdapter({"m": tuple(0.0 for _ in range(9))})
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix3d")
        row = WidgetBuilderTable.build("m", prop, adapter)
        assert isinstance(row, MatrixAttributeRow)
        assert row._n_dim == 3

    def test_build_dispatch_for_matrix4d(self, no_ui):
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        adapter = _TrackingAdapter({"m": tuple(0.0 for _ in range(16))})
        prop = _make_prop(name="m", value_type=tuple, type_name="matrix4d")
        row = WidgetBuilderTable.build("m", prop, adapter)
        assert isinstance(row, MatrixAttributeRow)
        assert row._n_dim == 4

    def test_three_matrix_type_names_registered(self):
        """All three USD matrix type names claim a slot in the table."""
        for type_name in ("matrix2d", "matrix3d", "matrix4d"):
            assert type_name in WidgetBuilderTable._TABLE, (
                f"matrix type_name {type_name!r} should be registered"
            )

    def test_different_widths_map_to_different_builders(self):
        """The three matrix type names dispatch to distinct builder
        functions — no cross-wiring that would build a 3×3 grid for a
        ``matrix4d`` attribute."""
        from ovui_widgets.property.builders.matrix import (
            build_matrix2d,
            build_matrix3d,
            build_matrix4d,
        )
        t = WidgetBuilderTable._TABLE
        assert t["matrix2d"] is build_matrix2d
        assert t["matrix3d"] is build_matrix3d
        assert t["matrix4d"] is build_matrix4d
        # Three distinct callables.
        assert len({t["matrix2d"], t["matrix3d"], t["matrix4d"]}) == 3


class TestAssetBuilderRegistration:
    """Step 3.6: ``asset`` registers against ``build_asset`` which returns
    an :class:`AssetPathAttributeRow` (label + StringField + folder button).

    The folder button is a no-op until the file-picker hook lands in a
    later phase (the property inspector behavior); USD ships only one
    asset-path scalar type, so this is a single-entry registration.
    """

    def test_asset_type_name_registered(self):
        assert "asset" in WidgetBuilderTable._TABLE

    def test_asset_registered_to_build_asset(self):
        from ovui_widgets.property.builders.asset import build_asset
        assert WidgetBuilderTable._TABLE.get("asset") is build_asset

    def test_build_asset_creates_asset_path_row(self, no_ui):
        from ovui_widgets.property.attribute_row import AssetPathAttributeRow
        from ovui_widgets.property.builders.asset import build_asset
        adapter = _TrackingAdapter({"tex": "./textures/noise.png"})
        prop = _make_prop(name="tex", value_type=str, type_name="asset")
        row = build_asset("tex", prop, adapter)
        assert isinstance(row, AssetPathAttributeRow)

    def test_build_dispatch_for_asset(self, no_ui):
        """End-to-end: ``WidgetBuilderTable.build(... asset)`` picks up the
        asset builder (not the read-only fallback). Pre-3.6 the ``asset``
        type_name fell through to ``_FallbackAttributeRow``; this
        regression guard catches a future mistaken drop of the
        registration."""
        from ovui_widgets.property.attribute_row import AssetPathAttributeRow
        adapter = _TrackingAdapter({"tex": "./textures/noise.png"})
        prop = _make_prop(name="tex", value_type=str, type_name="asset")
        row = WidgetBuilderTable.build("tex", prop, adapter)
        assert isinstance(row, AssetPathAttributeRow)

    def test_asset_not_registered_to_fallback(self):
        """Anchor the registration against accidental drift back to the
        fallback path. ``asset`` must point at ``build_asset``, not the
        builder-table's ``_fallback`` classmethod."""
        assert WidgetBuilderTable._TABLE.get("asset") is not WidgetBuilderTable._fallback


class TestRelationshipBuilderRegistration:
    """Step 3.7: ``relationship`` registers against ``build_relationship``
    which returns a :class:`RelationshipAttributeRow` (label + read-only
    StringField showing the joined target paths).

    Relationships have no USD ``GetTypeName()`` equivalent; the USD
    adapter synthesises ``"relationship"`` as the single type_name
    sentinel, so this is a single-entry registration (mirrors the
    ``asset`` pattern — one sentinel, one builder).
    """

    def test_relationship_type_name_registered(self):
        assert "relationship" in WidgetBuilderTable._TABLE

    def test_relationship_registered_to_build_relationship(self):
        from ovui_widgets.property.builders.relationship import build_relationship
        assert WidgetBuilderTable._TABLE.get("relationship") is build_relationship

    def test_build_relationship_creates_relationship_row(self, no_ui):
        from ovui_widgets.property.attribute_row import RelationshipAttributeRow
        from ovui_widgets.property.builders.relationship import build_relationship
        adapter = _TrackingAdapter({"rel": ("/World/Target",)})
        prop = _make_prop(name="rel", value_type=tuple, type_name="relationship")
        row = build_relationship("rel", prop, adapter)
        assert isinstance(row, RelationshipAttributeRow)

    def test_build_dispatch_for_relationship(self, no_ui):
        """End-to-end: ``WidgetBuilderTable.build(... relationship)`` picks
        up the relationship builder (not the read-only fallback). Pre-3.7
        the ``relationship`` type_name fell through to ``_FallbackAttributeRow``;
        this regression guard catches a future mistaken drop of the
        registration."""
        from ovui_widgets.property.attribute_row import RelationshipAttributeRow
        adapter = _TrackingAdapter({"rel": ("/World/Target",)})
        prop = _make_prop(name="rel", value_type=tuple, type_name="relationship")
        row = WidgetBuilderTable.build("rel", prop, adapter)
        assert isinstance(row, RelationshipAttributeRow)

    def test_relationship_not_registered_to_fallback(self):
        """Anchor the registration against accidental drift back to the
        fallback path. ``relationship`` must point at
        ``build_relationship``, not the builder-table's ``_fallback``
        classmethod."""
        assert (
            WidgetBuilderTable._TABLE.get("relationship")
            is not WidgetBuilderTable._fallback
        )


class TestArrayBuilderRegistration:
    """Step 3.8: ``array`` registers against ``build_array`` which returns
    an :class:`ArrayAttributeRow` (label + read-only StringField showing
    the full tuple for small arrays or ``"[N items]"`` for big ones).

    The USD adapter synthesises ``"array"`` as the single type_name
    sentinel for every USD array type (``float[]``, ``token[]``,
    ``float3[]``, …); this is a single-entry registration (mirrors the
    ``asset`` / ``relationship`` sentinel pattern).
    """

    def test_array_type_name_registered(self):
        assert "array" in WidgetBuilderTable._TABLE

    def test_array_registered_to_build_array(self):
        from ovui_widgets.property.builders.array import build_array
        assert WidgetBuilderTable._TABLE.get("array") is build_array

    def test_build_array_creates_array_row_small(self, no_ui):
        from ovui_widgets.property.attribute_row import ArrayAttributeRow
        from ovui_widgets.property.builders.array import build_array
        adapter = _TrackingAdapter({"arr": (1.0, 2.0, 3.0)})
        prop = _make_prop(name="arr", value_type="array", type_name="array")
        prop.is_big_array = False
        row = build_array("arr", prop, adapter)
        assert isinstance(row, ArrayAttributeRow)

    def test_build_array_creates_array_row_big(self, no_ui):
        from ovui_widgets.property.attribute_row import ArrayAttributeRow
        from ovui_widgets.property.builders.array import build_array
        adapter = _TrackingAdapter({"arr": tuple(range(20))})
        prop = _make_prop(name="arr", value_type="array", type_name="array")
        prop.is_big_array = True
        row = build_array("arr", prop, adapter)
        assert isinstance(row, ArrayAttributeRow)

    def test_build_dispatch_for_array(self, no_ui):
        """End-to-end: ``WidgetBuilderTable.build(... array)`` picks up
        the array builder (not the read-only fallback). Pre-3.8 the
        ``array`` type_name fell through to ``_FallbackAttributeRow``
        (arrays were silently dropped at the adapter boundary); this
        regression guard catches a future mistaken drop of the
        registration."""
        from ovui_widgets.property.attribute_row import ArrayAttributeRow
        adapter = _TrackingAdapter({"arr": (1.0,)})
        prop = _make_prop(name="arr", value_type="array", type_name="array")
        prop.is_big_array = False
        row = WidgetBuilderTable.build("arr", prop, adapter)
        assert isinstance(row, ArrayAttributeRow)

    def test_array_not_registered_to_fallback(self):
        """Anchor the registration against accidental drift back to the
        fallback path. ``array`` must point at ``build_array``, not the
        builder-table's ``_fallback`` classmethod."""
        assert (
            WidgetBuilderTable._TABLE.get("array")
            is not WidgetBuilderTable._fallback
        )


class TestDoubleBuilderRegistration:
    """Step 3.8: ``double`` registers against ``build_float`` (USD
    ``double`` attributes surface as Python floats via
    ``_TYPE_MAP["double"] == "float"``, so reusing the float builder is
    the correct mapping). Pre-3.8 this slot was empty and the Property
    Inspector rendered ``(unsupported double)`` for every ``double``
    attribute (e.g. Sphere's ``radius``).
    """

    def test_double_type_name_registered(self):
        assert "double" in WidgetBuilderTable._TABLE

    def test_double_registered_to_build_float(self):
        from ovui_widgets.property.builders.scalar import build_float
        assert WidgetBuilderTable._TABLE.get("double") is build_float

    def test_build_dispatch_for_double(self, no_ui):
        """End-to-end: ``WidgetBuilderTable.build(... double)`` picks up
        the float builder. Pre-3.8 fell through to
        ``_FallbackAttributeRow`` — this regression guard catches a
        future mistaken drop of the registration."""
        from ovui_widgets.property.attribute_row import FloatAttributeRow
        adapter = _TrackingAdapter({"radius": 1.0})
        prop = _make_prop(
            name="radius", value_type=float, type_name="double",
        )
        row = WidgetBuilderTable.build("radius", prop, adapter)
        assert isinstance(row, FloatAttributeRow)

    def test_double_not_registered_to_fallback(self):
        assert (
            WidgetBuilderTable._TABLE.get("double")
            is not WidgetBuilderTable._fallback
        )

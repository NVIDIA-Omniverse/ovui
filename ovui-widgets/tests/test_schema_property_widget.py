# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 6.4 — :class:`SchemaPropertyWidget`.

Covers the task's Step 6.4 done-signal checklist:

* :class:`SchemaPropertyWidget` is a :class:`SimplePropertyWidget`
  subclass and is importable from the widget subpackage
* Constructor accepts ``(title, schema_name, include_inherited)``
  with ``include_inherited`` defaulting to ``True``
* :meth:`on_new_payload` returns ``True`` when
  ``adapter.get_scheme() == schema_name`` and ``False`` otherwise
* :meth:`on_new_payload` returns ``False`` when no adapter is bound
* :meth:`build_items_content` walks the adapter's attribute list
  through :meth:`_filter_props_to_build` then
  :meth:`_customize_props_layout` and emits one row per survivor via
  the builder table
* Default :meth:`_filter_props_to_build` returns every attribute
* Default :meth:`_customize_props_layout` returns the attr list
  as-is (identity)
* Subclasses may override either hook to restrict / reorder the attrs
* :class:`MockPropertyAdapter`'s ``scheme`` constructor argument and
  :meth:`set_scheme` setter both drive :meth:`get_scheme`
"""

from __future__ import annotations

from typing import List

import pytest
from ovui_data_adapters.common import AttributeMetadata

from ovui_widgets.common.testing.mock_property import MockPropertyAdapter

# ---------------------------------------------------------------------------
# Fixtures — attributes + a recording WidgetBuilderTable double
# ---------------------------------------------------------------------------


def _make_attr(
    name: str,
    *,
    type_name: str = "float",
    display_name: str = "",
    group: str = "",
) -> AttributeMetadata:
    return AttributeMetadata(
        name=name,
        display_name=display_name or name,
        type_name=type_name,
        value_type=float,
        group=group,
    )


@pytest.fixture()
def builder_spy(monkeypatch):
    """Replace :meth:`WidgetBuilderTable.build` with a recorder.

    :class:`SchemaPropertyWidget.build_items_content` funnels every
    surviving attribute through the builder table. Recording each call
    lets tests assert exact order + count without actually constructing
    ovui widgets — which would require a frame scope.
    """
    from ovui_widgets.property.builders import WidgetBuilderTable

    calls: List[tuple] = []

    def _spy(attr_name, metadata, adapter, **kwargs):
        calls.append((attr_name, metadata, adapter, kwargs))
        return None

    monkeypatch.setattr(WidgetBuilderTable, "build", classmethod(
        lambda cls, attr_name, metadata, adapter, **kwargs:
        _spy(attr_name, metadata, adapter, **kwargs)
    ))
    return calls


# ---------------------------------------------------------------------------
# Module / import shape
# ---------------------------------------------------------------------------


class TestSchemaPropertyWidgetImportShape:
    def test_importable_from_subpackage(self):
        from ovui_widgets.property.widget import SchemaPropertyWidget
        assert SchemaPropertyWidget is not None

    def test_importable_from_direct_module(self):
        from ovui_widgets.property.widget.schema_property_widget import SchemaPropertyWidget
        assert SchemaPropertyWidget is not None

    def test_re_export_identity(self):
        from ovui_widgets.property.widget import SchemaPropertyWidget as A
        from ovui_widgets.property.widget.schema_property_widget import (
            SchemaPropertyWidget as B,
        )
        assert A is B

    def test_in_widget_subpackage_all(self):
        import ovui_widgets.property.widget as w_mod
        assert "SchemaPropertyWidget" in w_mod.__all__

    def test_is_simple_property_widget_subclass(self):
        from ovui_widgets.property.widget import (
            SchemaPropertyWidget,
            SimplePropertyWidget,
        )
        assert issubclass(SchemaPropertyWidget, SimplePropertyWidget)

    def test_is_property_widget_subclass(self):
        from ovui_widgets.property.widget import PropertyWidget, SchemaPropertyWidget
        assert issubclass(SchemaPropertyWidget, PropertyWidget)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_stores_title(self):
        from ovui_widgets.property.widget import SchemaPropertyWidget
        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        assert w._title == "Shape"

    def test_stores_schema_name(self):
        from ovui_widgets.property.widget import SchemaPropertyWidget
        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        assert w._schema_name == "shape"

    def test_include_inherited_defaults_to_true(self):
        from ovui_widgets.property.widget import SchemaPropertyWidget
        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        assert w._include_inherited is True

    def test_include_inherited_override(self):
        from ovui_widgets.property.widget import SchemaPropertyWidget
        w = SchemaPropertyWidget(
            title="Shape", schema_name="shape", include_inherited=False
        )
        assert w._include_inherited is False

    def test_initial_adapter_is_none(self):
        from ovui_widgets.property.widget import SchemaPropertyWidget
        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        assert w._adapter is None
        assert w.get_adapter() is None

    def test_inherited_initial_state(self):
        """SimplePropertyWidget scaffolding state carries through."""
        from ovui_widgets.property.widget import SchemaPropertyWidget
        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        assert w._frame is None
        assert w._content is None
        assert w._filter_model is None
        assert w._pending_rebuild_handle is None


# ---------------------------------------------------------------------------
# Adapter binding
# ---------------------------------------------------------------------------


class TestAdapterBinding:
    def test_set_adapter_stores_reference(self):
        from ovui_widgets.property.widget import SchemaPropertyWidget
        a = MockPropertyAdapter(paths=["/A"])
        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        w.set_adapter(a)
        assert w.get_adapter() is a

    def test_set_adapter_none_unbinds(self):
        from ovui_widgets.property.widget import SchemaPropertyWidget
        a = MockPropertyAdapter(paths=["/A"])
        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        w.set_adapter(a)
        w.set_adapter(None)
        assert w.get_adapter() is None


# ---------------------------------------------------------------------------
# on_new_payload — schema gate
# ---------------------------------------------------------------------------


class TestOnNewPayloadSchemaGate:
    def test_returns_true_when_scheme_matches(self):
        """Required done signal: adapter scheme matches → True."""
        from ovui_widgets.property.payload import PropertyPayload
        from ovui_widgets.property.widget import SchemaPropertyWidget

        a = MockPropertyAdapter(paths=["/A"], scheme="shape")
        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        w.set_adapter(a)
        assert w.on_new_payload(PropertyPayload(paths=["/A"])) is True

    def test_returns_false_when_scheme_differs(self):
        """Required done signal: adapter scheme ≠ schema_name → False."""
        from ovui_widgets.property.payload import PropertyPayload
        from ovui_widgets.property.widget import SchemaPropertyWidget

        a = MockPropertyAdapter(paths=["/A"], scheme="light")
        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        w.set_adapter(a)
        assert w.on_new_payload(PropertyPayload(paths=["/A"])) is False

    def test_returns_false_when_no_adapter_bound(self):
        from ovui_widgets.property.payload import PropertyPayload
        from ovui_widgets.property.widget import SchemaPropertyWidget

        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        assert w.on_new_payload(PropertyPayload(paths=["/A"])) is False

    def test_set_scheme_flips_gate(self):
        """Mutating the adapter's scheme flips the gate live.

        Validates the :meth:`MockPropertyAdapter.set_scheme` helper —
        Step 6.4 test hook that lets a single adapter drive both
        branches without re-construction.
        """
        from ovui_widgets.property.payload import PropertyPayload
        from ovui_widgets.property.widget import SchemaPropertyWidget

        a = MockPropertyAdapter(paths=["/A"], scheme="shape")
        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        w.set_adapter(a)
        payload = PropertyPayload(paths=["/A"])
        assert w.on_new_payload(payload) is True
        a.set_scheme("light")
        assert w.on_new_payload(payload) is False

    def test_gate_accepts_empty_payload_when_scheme_matches(self):
        """The gate reads the adapter's scheme, not the payload's paths.

        Empty selections still surface the widget if the adapter somehow
        reports the matching scheme (pathological but documented).
        """
        from ovui_widgets.property.payload import PropertyPayload
        from ovui_widgets.property.widget import SchemaPropertyWidget

        a = MockPropertyAdapter(paths=[], scheme="shape")
        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        w.set_adapter(a)
        assert w.on_new_payload(PropertyPayload(paths=[])) is True


# ---------------------------------------------------------------------------
# build_items_content — pipeline
# ---------------------------------------------------------------------------


class TestBuildItemsContentPipeline:
    def test_calls_filter_then_customize(self, builder_spy):
        """Required done signal: build_items_content invokes the two hooks.

        Records the order and input to each hook so tests can assert
        filter → customise is the only permitted pipeline.
        """
        from ovui_widgets.property.widget import SchemaPropertyWidget

        call_log: List[tuple] = []

        class _Sub(SchemaPropertyWidget):
            def _filter_props_to_build(self, attrs):
                call_log.append(("filter", [a.name for a in attrs]))
                return attrs

            def _customize_props_layout(self, attrs):
                call_log.append(("customize", [a.name for a in attrs]))
                return attrs

        a_attr = _make_attr("alpha")
        b_attr = _make_attr("beta")
        a = MockPropertyAdapter(
            paths=["/A"],
            attributes={"alpha": a_attr, "beta": b_attr},
            scheme="shape",
        )
        w = _Sub(title="Shape", schema_name="shape")
        w.set_adapter(a)
        w.build_items_content()

        assert [name for name, _ in call_log] == ["filter", "customize"]
        assert call_log[0][1] == ["alpha", "beta"]
        assert call_log[1][1] == ["alpha", "beta"]

    def test_customize_receives_filtered_output(self, builder_spy):
        """Required done signal: customize sees only what filter returned.

        Subclass drops ``beta`` in ``_filter_props_to_build``; the
        customise hook receives ``[alpha]`` not ``[alpha, beta]``.
        """
        from ovui_widgets.property.widget import SchemaPropertyWidget

        seen_by_customize: List[List[str]] = []

        class _Sub(SchemaPropertyWidget):
            def _filter_props_to_build(self, attrs):
                return [a for a in attrs if a.name == "alpha"]

            def _customize_props_layout(self, attrs):
                seen_by_customize.append([a.name for a in attrs])
                return attrs

        a = MockPropertyAdapter(
            paths=["/A"],
            attributes={
                "alpha": _make_attr("alpha"),
                "beta": _make_attr("beta"),
            },
            scheme="shape",
        )
        w = _Sub(title="Shape", schema_name="shape")
        w.set_adapter(a)
        w.build_items_content()
        assert seen_by_customize == [["alpha"]]

    def test_builder_table_invoked_for_every_survivor(self, builder_spy):
        """Required done signal: one row per survivor after both hooks.

        Default hooks (identity) → every declared attribute becomes one
        :meth:`WidgetBuilderTable.build` call, in declared order.
        """
        from ovui_widgets.property.widget import SchemaPropertyWidget

        a = MockPropertyAdapter(
            paths=["/A"],
            attributes={
                "alpha": _make_attr("alpha"),
                "beta": _make_attr("beta"),
                "gamma": _make_attr("gamma"),
            },
            scheme="shape",
        )
        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        w.set_adapter(a)
        w.build_items_content()

        assert [call[0] for call in builder_spy] == ["alpha", "beta", "gamma"]

    def test_builder_receives_adapter(self, builder_spy):
        from ovui_widgets.property.widget import SchemaPropertyWidget

        a = MockPropertyAdapter(
            paths=["/A"],
            attributes={"alpha": _make_attr("alpha")},
            scheme="shape",
        )
        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        w.set_adapter(a)
        w.build_items_content()
        assert builder_spy[0][2] is a

    def test_no_adapter_bound_is_noop(self, builder_spy):
        """No adapter → no crash, no builder call."""
        from ovui_widgets.property.widget import SchemaPropertyWidget

        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        w.build_items_content()
        assert builder_spy == []

    def test_empty_attribute_list_is_noop(self, builder_spy):
        """Adapter with zero attributes → no rows."""
        from ovui_widgets.property.widget import SchemaPropertyWidget

        a = MockPropertyAdapter(paths=["/A"], scheme="shape")
        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        w.set_adapter(a)
        w.build_items_content()
        assert builder_spy == []


# ---------------------------------------------------------------------------
# Default override-hook behaviour
# ---------------------------------------------------------------------------


class TestDefaultHooks:
    def test_default_filter_returns_all(self):
        from ovui_widgets.property.widget import SchemaPropertyWidget

        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        attrs = [_make_attr("a"), _make_attr("b")]
        out = w._filter_props_to_build(attrs)
        assert [a.name for a in out] == ["a", "b"]

    def test_default_filter_returns_new_list(self):
        """Identity default still returns a new list so callers can
        mutate freely without aliasing back into input."""
        from ovui_widgets.property.widget import SchemaPropertyWidget

        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        attrs = [_make_attr("a")]
        out = w._filter_props_to_build(attrs)
        assert out == attrs
        assert out is not attrs

    def test_default_customize_returns_as_is(self):
        from ovui_widgets.property.widget import SchemaPropertyWidget

        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        attrs = [_make_attr("a"), _make_attr("b"), _make_attr("c")]
        out = w._customize_props_layout(attrs)
        assert [a.name for a in out] == ["a", "b", "c"]

    def test_default_customize_returns_new_list(self):
        from ovui_widgets.property.widget import SchemaPropertyWidget

        w = SchemaPropertyWidget(title="Shape", schema_name="shape")
        attrs = [_make_attr("a")]
        out = w._customize_props_layout(attrs)
        assert out == attrs
        assert out is not attrs


# ---------------------------------------------------------------------------
# Subclass customisation — custom filter / custom layout
# ---------------------------------------------------------------------------


class TestSubclassCustomisation:
    def test_custom_filter_restricts_builds(self, builder_spy):
        """Required done signal: subclass overrides _filter_props_to_build
        → only surviving attrs reach the builder table."""
        from ovui_widgets.property.widget import SchemaPropertyWidget

        class _OnlyVisible(SchemaPropertyWidget):
            def _filter_props_to_build(self, attrs):
                return [a for a in attrs if a.name.startswith("vis_")]

        a = MockPropertyAdapter(
            paths=["/A"],
            attributes={
                "vis_a": _make_attr("vis_a"),
                "hidden_b": _make_attr("hidden_b"),
                "vis_c": _make_attr("vis_c"),
            },
            scheme="shape",
        )
        w = _OnlyVisible(title="Shape", schema_name="shape")
        w.set_adapter(a)
        w.build_items_content()

        assert [call[0] for call in builder_spy] == ["vis_a", "vis_c"]

    def test_custom_layout_reorders_attrs(self, builder_spy):
        """Subclass can reorder in :meth:`_customize_props_layout`."""
        from ovui_widgets.property.widget import SchemaPropertyWidget

        class _Reversed(SchemaPropertyWidget):
            def _customize_props_layout(self, attrs):
                return list(reversed(attrs))

        a = MockPropertyAdapter(
            paths=["/A"],
            attributes={
                "first": _make_attr("first"),
                "second": _make_attr("second"),
                "third": _make_attr("third"),
            },
            scheme="shape",
        )
        w = _Reversed(title="Shape", schema_name="shape")
        w.set_adapter(a)
        w.build_items_content()

        assert [call[0] for call in builder_spy] == ["third", "second", "first"]

    def test_custom_layout_can_drop_attrs(self, builder_spy):
        """Subclass can drop attrs in :meth:`_customize_props_layout`
        (not just reorder) — no-surprise for the builder table."""
        from ovui_widgets.property.widget import SchemaPropertyWidget

        class _KeepOne(SchemaPropertyWidget):
            def _customize_props_layout(self, attrs):
                return attrs[:1]

        a = MockPropertyAdapter(
            paths=["/A"],
            attributes={
                "keep": _make_attr("keep"),
                "drop_one": _make_attr("drop_one"),
                "drop_two": _make_attr("drop_two"),
            },
            scheme="shape",
        )
        w = _KeepOne(title="Shape", schema_name="shape")
        w.set_adapter(a)
        w.build_items_content()

        assert [call[0] for call in builder_spy] == ["keep"]

    def test_custom_filter_and_layout_compose(self, builder_spy):
        """Filter drops two, layout reverses the remaining two."""
        from ovui_widgets.property.widget import SchemaPropertyWidget

        class _FilterAndReverse(SchemaPropertyWidget):
            def _filter_props_to_build(self, attrs):
                return [a for a in attrs if a.name != "drop"]

            def _customize_props_layout(self, attrs):
                return list(reversed(attrs))

        a = MockPropertyAdapter(
            paths=["/A"],
            attributes={
                "one": _make_attr("one"),
                "drop": _make_attr("drop"),
                "two": _make_attr("two"),
            },
            scheme="shape",
        )
        w = _FilterAndReverse(title="Shape", schema_name="shape")
        w.set_adapter(a)
        w.build_items_content()

        assert [call[0] for call in builder_spy] == ["two", "one"]


# ---------------------------------------------------------------------------
# Mock adapter — scheme configurability
# ---------------------------------------------------------------------------


class TestMockAdapterSchemeConfigurable:
    def test_default_scheme_is_mock(self):
        a = MockPropertyAdapter(paths=["/A"])
        assert a.get_scheme() == "mock"

    def test_ctor_scheme_override(self):
        a = MockPropertyAdapter(paths=["/A"], scheme="shape")
        assert a.get_scheme() == "shape"

    def test_set_scheme_mutates(self):
        a = MockPropertyAdapter(paths=["/A"])
        a.set_scheme("light")
        assert a.get_scheme() == "light"

    def test_set_scheme_can_restore_default(self):
        a = MockPropertyAdapter(paths=["/A"], scheme="custom")
        a.set_scheme("mock")
        assert a.get_scheme() == "mock"

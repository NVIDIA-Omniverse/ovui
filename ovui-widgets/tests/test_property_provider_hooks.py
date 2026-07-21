# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for generic property provider hooks."""

from __future__ import annotations

from typing import Any

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter
from ovui_widgets.property.builders import WidgetBuilderTable
from ovui_widgets.property.payload import PropertyPayload
from ovui_widgets.property.provider_hooks import (
    PropertyProviderContribution,
    PropertyProviderDescriptor,
    PropertyProviderRegistry,
    ProviderPropertyWidget,
)


class _Sub:
    def cancel(self):
        pass


class _Adapter(PropertyAdapter):
    def __init__(self, attrs, *, can_clear=True):
        self._attrs = {attr.name: attr for attr in attrs}
        self._can_clear = can_clear
        self.cleared = []

    def get_paths(self):
        return ["/Selection"]

    def is_valid(self):
        return True

    def get_attribute_names(self):
        return list(self._attrs)

    def get_attribute_metadata(self, attr_name):
        return self._attrs[attr_name]

    def get_value(self, attr_name):
        return None

    def is_ambiguous(self, attr_name):
        return False

    def get_per_component_ambiguity(self, attr_name):
        return None

    def begin_edit(self, attr_name):
        pass

    def set_value(self, attr_name, value):
        pass

    def end_edit(self, attr_name):
        pass

    def subscribe_changes(self, callback):
        return _Sub()

    def get_scheme(self):
        return "test"

    def clear_value(self, attr_name):
        if not self._can_clear:
            return PropertyAdapter.clear_value(self, attr_name)
        self.cleared.append(attr_name)


def _attr(
    name,
    *,
    group="Main",
    type_name="host-test",
    authored=True,
    locked=False,
    big=False,
    sampled=False,
):
    return AttributeMetadata(
        name=name,
        display_name=name.title(),
        type_name=type_name,
        value_type=float,
        group=group,
        is_authored=authored,
        is_locked=locked,
        is_big_array=big,
        is_time_sampled=sampled,
    )


def _contribution(provider_id, adapter, **descriptor_kwargs):
    descriptor = PropertyProviderDescriptor(
        provider_id=provider_id,
        label=provider_id.title(),
        **descriptor_kwargs,
    )
    return PropertyProviderContribution(
        descriptor=descriptor,
        adapter_factory=lambda payload, context: adapter,
    )


def test_provider_registry_orders_gates_lifecycle_and_unloads():
    events = []
    host = object()
    registry = PropertyProviderRegistry(host, capabilities=("base",))
    first = _contribution(
        "first",
        _Adapter([_attr("a")]),
        order=20,
        capabilities=("base",),
        metadata={"origin": "unit"},
    )
    second = _contribution(
        "second",
        _Adapter([_attr("b")]),
        order=10,
        dev_only=True,
    )
    lifecycle = PropertyProviderContribution(
        descriptor=PropertyProviderDescriptor(
            provider_id="life",
            label="Lifecycle",
            order=30,
        ),
        adapter_factory=lambda payload, context: _Adapter([_attr("c")]),
        on_add=lambda received_host: events.append(("add", received_host)),
        on_remove=lambda received_host: events.append(("remove", received_host)),
    )

    handle = registry.add(first)
    registry.add(second)
    second_handle = registry.add(lifecycle)
    duplicate = registry.add(lifecycle)

    assert handle.id == "first"
    assert duplicate.id == second_handle.id == "life"
    assert events == [("add", host)]
    assert [item.provider_id for item in registry.iter_descriptors()] == [
        "first",
        "life",
    ]
    assert first.descriptor.metadata["origin"] == "unit"

    registry.dev_mode = True
    assert [item.provider_id for item in registry.iter_descriptors()] == [
        "second",
        "first",
        "life",
    ]

    assert second_handle.remove() is True
    assert events == [("add", host), ("remove", host)]
    assert second_handle.remove() is False


def test_provider_registry_isolates_visibility_and_adapter_failures():
    registry = PropertyProviderRegistry(object())
    visible_error = PropertyProviderContribution(
        descriptor=PropertyProviderDescriptor(
            provider_id="visible-error",
            label="Visible Error",
            visible_fn=lambda host: (_ for _ in ()).throw(RuntimeError("visible")),
        ),
        adapter_factory=lambda payload, context: _Adapter([_attr("hidden")]),
    )
    adapter_error = PropertyProviderContribution(
        descriptor=PropertyProviderDescriptor(
            provider_id="adapter-error",
            label="Adapter Error",
        ),
        adapter_factory=lambda payload, context: (_ for _ in ()).throw(RuntimeError("adapter")),
    )
    good_adapter = _Adapter([_attr("ok")])
    good = _contribution("good", good_adapter)

    registry.add(visible_error)
    registry.add(adapter_error)
    registry.add(good)

    bindings = registry.adapters_for(PropertyPayload(paths=["/Selection"]))

    assert [binding.descriptor.provider_id for binding in bindings] == ["good"]
    assert bindings[0].adapter is good_adapter
    assert set(registry.failures) == {"visible-error", "adapter-error"}


def test_provider_property_widget_composes_rows_and_editor_factory():
    adapter = _Adapter([
        _attr("z_attr", group="B"),
        _attr("a_attr", group="A"),
    ])
    registry = PropertyProviderRegistry(object())
    registry.add(_contribution("provider", adapter))
    widget = ProviderPropertyWidget(registry)
    payload = PropertyPayload(paths=["/Selection"])

    rows = widget.compose_rows(payload)

    assert [(row.group, row.attr_name) for row in rows] == [
        ("A", "a_attr"),
        ("B", "z_attr"),
    ]
    assert all(row.resettable for row in rows)

    built: list[tuple[str, str, Any]] = []

    def builder(attr_name, metadata, received_adapter, **kwargs):
        built.append((attr_name, metadata.display_name, received_adapter))

    handle = WidgetBuilderTable.register("host-test", builder)
    try:
        assert widget.on_new_payload(payload)
        widget.build_items()
    finally:
        handle.cancel()

    assert built == [
        ("a_attr", "A_Attr", adapter),
        ("z_attr", "Z_Attr", adapter),
    ]
    assert widget.failures == {}


def test_provider_rows_report_reset_and_status_capabilities():
    adapter = _Adapter([
        _attr("authored", authored=True),
        _attr("inherited", authored=False),
        _attr("locked", locked=True),
        _attr("large", big=True),
        _attr("animated", sampled=True),
    ])
    registry = PropertyProviderRegistry(object())
    registry.add(_contribution("provider", adapter))
    rows = {
        row.attr_name: row
        for row in ProviderPropertyWidget(registry).compose_rows(
            PropertyPayload(paths=["/Selection"])
        )
    }

    assert rows["authored"].resettable
    assert rows["authored"].status_text == "Authored"
    assert not rows["inherited"].resettable
    assert rows["locked"].disabled
    assert rows["locked"].status_text == "Locked"
    assert rows["large"].disabled
    assert rows["large"].status_text == "Large value"
    assert rows["animated"].status_text == "Time sampled"


def test_provider_property_widget_isolates_row_build_failures():
    adapter = _Adapter([_attr("ok"), _attr("bad")])
    registry = PropertyProviderRegistry(object())
    registry.add(_contribution("provider", adapter))
    widget = ProviderPropertyWidget(registry)
    payload = PropertyPayload(paths=["/Selection"])
    built = []

    def builder(attr_name, metadata, received_adapter, **kwargs):
        if attr_name == "bad":
            raise RuntimeError("bad row")
        built.append(attr_name)

    handle = WidgetBuilderTable.register("host-test", builder)
    try:
        assert widget.on_new_payload(payload)
        widget.build_items()
    finally:
        handle.cancel()

    assert built == ["ok"]
    assert "provider:bad" in widget.failures

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""``SchemaPropertyWidget`` — schema-gated auto-discovery property widget.

property widget stack behavior / the property inspector step 6.4. Subclass of
:class:`~ovui_widgets.property.widget.SimplePropertyWidget` that auto-discovers
the attributes of a named schema on the current selection, emits one
row per attribute through the standard builder table, and exposes two
override hooks for subclasses to shape the output:

* :meth:`_filter_props_to_build` — drop attributes that should not be
  shown for this schema (default: keep everything).
* :meth:`_customize_props_layout` — reorder / annotate / inject extras
  after filtering (default: identity).

The two hooks parallel Kit's ``MultiSchemaPropertiesWidget`` contract
(the property inspector behavior). Domain widgets for lights,
cameras, materials, etc. land as :class:`SchemaPropertyWidget`
subclasses once Step 6.5's :class:`PropertySchemeRegistry` ships.

Schema gating
-------------

:meth:`on_new_payload` returns ``True`` iff the widget's bound
:class:`~ovui_widgets.common.adapters.PropertyAdapter` reports
``get_scheme() == schema_name``. The adapter reference is set via
:meth:`set_adapter` by whichever orchestrator owns the widget —
typically :class:`~ovui_widgets.property.window.PropertyWindow` at rebuild
time; in Step 6.4 tests wire it directly. No adapter → gate returns
``False``.

The widget deliberately does **not** peek at the payload's
``get_scheme()`` (which :class:`~ovui_widgets.property.payload.PropertyPayload`
exposes) — the authoritative scheme source is the adapter, because the
adapter knows the backing store (USD, mock, vendor-specific) while the
payload only carries the path list and a coarse label. Step 7.4 may
widen the payload, at which point both paths can be valid; for now
only the adapter path is supported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovui_widgets.property.widget.simple_property_widget import SimplePropertyWidget

if TYPE_CHECKING:
    from ovui_widgets.property.payload import PropertyPayload


class SchemaPropertyWidget(SimplePropertyWidget):
    """Schema-gated :class:`SimplePropertyWidget` with customisation hooks.

    Subclasses typically:

        * super-call ``__init__(title, schema_name, include_inherited)``,
        * override :meth:`_filter_props_to_build` to drop attributes not
          in the schema,
        * override :meth:`_customize_props_layout` to reorder / group /
          inject extra metadata,
        * let the base :meth:`build_items_content` emit the rows through
          :class:`~ovui_widgets.property.builders.WidgetBuilderTable`.

    The ``include_inherited`` flag is stored on the instance for
    subclasses that distinguish schema-owned attrs from inherited ones
    (USD domain widgets typically key
    ``schema.GetSchemaAttributeNames(include_inherited)`` off it). The
    default ``_filter_props_to_build`` does not branch on the flag — it
    returns every attr — so it's purely informational at this layer.
    """

    def __init__(
        self,
        title: str,
        schema_name: str,
        include_inherited: bool = True,
    ) -> None:
        """Store the header title, schema gate, and inheritance flag.

        ``title`` is the :class:`ui.CollapsableFrame` header (passed
        through to :class:`SimplePropertyWidget`). ``schema_name`` is
        the adapter-scheme string the widget gates on —
        :meth:`on_new_payload` returns ``True`` only when the bound
        adapter reports this exact string. ``include_inherited``
        defaults to ``True`` matching the common case where domain
        widgets show both the schema's own attributes and everything
        inherited from its base schemas; subclasses that want a strict
        subset pass ``False``.
        """
        super().__init__(title=title, collapsed=False)
        self._schema_name = schema_name
        self._include_inherited = include_inherited
        self._adapter: Optional[PropertyAdapter] = None

    # ------------------------------------------------------------------
    # Adapter wiring — Step 6.5's PropertySchemeRegistry will own this
    # ------------------------------------------------------------------

    def set_adapter(self, adapter: Optional[PropertyAdapter]) -> None:
        """Bind or unbind the adapter the widget reads attrs from.

        Passing ``None`` unbinds — :meth:`on_new_payload` then returns
        ``False`` and :meth:`build_items_content` emits nothing. The
        window / registry swaps the adapter on selection change; the
        widget itself never owns the adapter.
        """
        self._adapter = adapter

    def get_adapter(self) -> Optional[PropertyAdapter]:
        """Return the currently bound adapter, or ``None`` if unbound."""
        return self._adapter

    # ------------------------------------------------------------------
    # PropertyWidget contract
    # ------------------------------------------------------------------

    def on_new_payload(self, payload: "PropertyPayload") -> bool:
        """Gate on ``adapter.get_scheme() == schema_name``.

        Returns ``False`` when no adapter is bound (the orchestrator
        forgot to call :meth:`set_adapter`, or the selection has no
        property-capable target). Returns ``False`` when the adapter
        reports a different scheme than the one this widget was
        registered for — the window then hides this widget in favour of
        whichever one matches.
        """
        if self._adapter is None:
            return False
        return self._adapter.get_scheme() == self._schema_name

    def build_items_content(self) -> None:
        """Emit rows for every attr that survives the two hooks.

        Pipeline: adapter's :meth:`get_attribute_names` →
        :meth:`_filter_props_to_build` → :meth:`_customize_props_layout`
        → one :meth:`add_item_with_model` per survivor. Each row goes
        through :class:`~ovui_widgets.property.builders.WidgetBuilderTable` the
        way :class:`AttributesWidget` does, so the per-type-name editor
        registry is honoured uniformly.

        No-op when no adapter is bound — :meth:`on_new_payload` should
        have returned ``False`` and the window should not have called
        this in the first place, but the guard makes the failure mode
        quiet if the sequence is ever violated.
        """
        if self._adapter is None:
            return
        attrs = self._collect_attrs()
        filtered = self._filter_props_to_build(attrs)
        laid_out = self._customize_props_layout(filtered)
        for attr in laid_out:
            self.add_item_with_model(attr, self._build_attribute_row)

    # ------------------------------------------------------------------
    # Override hooks — subclasses shape the attr list
    # ------------------------------------------------------------------

    def _filter_props_to_build(
        self, attrs: List[AttributeMetadata]
    ) -> List[AttributeMetadata]:
        """Drop attrs that should not be shown. Default: identity.

        Subclasses override to restrict to a specific schema's
        attributes (e.g. ``UsdLux.LightAPI.GetSchemaAttributeNames``).
        Called before :meth:`_customize_props_layout` so the layout
        hook only sees attrs that will actually render.
        """
        return list(attrs)

    def _customize_props_layout(
        self, attrs: List[AttributeMetadata]
    ) -> List[AttributeMetadata]:
        """Reorder / annotate / inject custom entries. Default: identity.

        Subclasses override to enforce a display order, inject
        separators, or add synthetic entries for custom attributes.
        Called after :meth:`_filter_props_to_build` so the input is
        already filtered down to the attrs the subclass wants.
        """
        return list(attrs)

    # ------------------------------------------------------------------
    # Helpers — private
    # ------------------------------------------------------------------

    def _collect_attrs(self) -> List[AttributeMetadata]:
        """Read every :class:`AttributeMetadata` the bound adapter exposes.

        Returns an empty list when no adapter is bound — the caller
        already checks, but the defensive branch lets this helper be
        safe to call from subclass overrides that skip the check.
        """
        adapter = self._adapter
        if adapter is None:
            return []
        out: List[AttributeMetadata] = []
        for name in adapter.get_attribute_names():
            out.append(adapter.get_attribute_metadata(name))
        return out

    def _build_attribute_row(self, attr: AttributeMetadata) -> None:
        """Dispatch one attribute row through :class:`WidgetBuilderTable`.

        Mirrors :meth:`AttributesWidget._build_attribute_row` — the
        builder table owns per-type widget registration (property attribute builder behavior);
        this widget just hands it the adapter + metadata.
        """
        adapter = self._adapter
        if adapter is None:
            return
        from ovui_widgets.property.builders import WidgetBuilderTable
        WidgetBuilderTable.build(attr.name, attr, adapter)

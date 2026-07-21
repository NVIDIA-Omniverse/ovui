# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""WidgetBuilderTable — type-dispatch for attribute row widgets.

property attribute builder behavior. Class-level registry keyed by ``AttributeMetadata.type_name``.
Replaces the ``if/elif`` chain in ``attribute_row.py::build_attribute_row``
— though the swap itself lands in Step 1.3. Built-in entries wrap the
existing row classes and are registered at import time by
``ovui_widgets.property.builders.scalar`` and ``ovui_widgets.property.builders.vec3``.

Introduced in Step 1.2 of the property inspector implementation. No callsite consumes the
table yet; ``build_attribute_row()`` is untouched.
"""

from typing import Any, Callable, Dict, Optional

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter


class _BuilderSubscription:
    """Handle returned by :meth:`WidgetBuilderTable.register`.

    ``cancel()`` removes the registration only if the table slot still
    points at the originally-registered builder. If another registration
    has since overwritten the slot (after an explicit cancel + re-register
    elsewhere), this cancel is a no-op — it never evicts someone else's
    builder. Idempotent: a second ``cancel()`` is a no-op.

    Follows the ``_ValueChangeSubscription`` pattern from Step 1.1 and
    ``_UsdPropertySubscription`` from ``ovui_widgets.stage/usd_property_adapter.py``
    — no ``__del__`` auto-cancel, so anonymous-subscription lifetime
    never surprises callers.
    """

    def __init__(self, type_name: str, builder: Callable[..., Any]) -> None:
        self._type_name: Optional[str] = type_name
        self._builder: Optional[Callable[..., Any]] = builder

    def cancel(self) -> None:
        if self._type_name is None or self._builder is None:
            return
        current = WidgetBuilderTable._TABLE.get(self._type_name)
        if current is self._builder:
            del WidgetBuilderTable._TABLE[self._type_name]
        self._type_name = None
        self._builder = None


class WidgetBuilderTable:
    """Static dispatch table: ``type_name`` → builder callable.

    Built-in entries are populated at package-import time (see
    ``ovui_widgets.property.builders.__init__``). Third-party code may add
    entries via :meth:`register`.
    """

    _TABLE: Dict[str, Callable[..., Any]] = {}

    @classmethod
    def build(
        cls,
        attr_name: str,
        metadata: AttributeMetadata,
        adapter: PropertyAdapter,
        **kwargs: Any,
    ) -> Any:
        """Dispatch to the registered builder for ``metadata.type_name``.

        Falls back to :meth:`_fallback` (read-only label) for unknown
        types. Returns whatever the builder returns — typically a row
        instance, but the registry does not enforce a return type.
        """
        builder = cls._TABLE.get(metadata.type_name, cls._fallback)
        return builder(attr_name, metadata, adapter, **kwargs)

    @classmethod
    def register(
        cls,
        type_name: str,
        builder: Callable[..., Any],
    ) -> _BuilderSubscription:
        """Register ``builder`` as the handler for ``type_name``.

        Raises ``ValueError`` if ``type_name`` is already registered —
        callers that need to replace an existing entry must cancel the
        prior subscription first. Returns a subscription whose
        :meth:`cancel` un-registers.
        """
        if type_name in cls._TABLE:
            raise ValueError(
                f"WidgetBuilderTable: builder already registered for "
                f"type_name={type_name!r}"
            )
        cls._TABLE[type_name] = builder
        return _BuilderSubscription(type_name, builder)

    @classmethod
    def _fallback(
        cls,
        attr_name: str,
        metadata: AttributeMetadata,
        adapter: PropertyAdapter,
        **kwargs: Any,
    ) -> Any:
        """Read-only label shown for unknown types.

        Wraps the existing ``_FallbackAttributeRow`` so the visual
        outcome matches the legacy dispatch in
        ``attribute_row.build_attribute_row``. The import is local to
        keep ``builder_table.py`` free of an ``omni.ui`` transitive
        dependency at module-import time — third-party callers that need
        only the class-level registry never pay for UI imports.
        """
        from ovui_widgets.property.attribute_row import _FallbackAttributeRow
        return _FallbackAttributeRow(metadata, adapter)

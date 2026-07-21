# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Generic provider hooks for adapter-backed property surfaces."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovui_widgets.property.group_widget import FIT_CONTENT_HEIGHT, GROUP_STACK_SPACING
from ovui_widgets.property.parts import UiDisplayGroup
from ovui_widgets.property.widget import PropertyWidget

if TYPE_CHECKING:
    from ovui_widgets.property.payload import PropertyPayload


ProviderPredicate = Callable[[Any], bool]
ProviderCallback = Callable[[Any], None]
ProviderAdapterFactory = Callable[[Any, Any], PropertyAdapter | None]
ProviderContextFactory = Callable[[Any, "PropertyPayload"], Any]


@dataclass(frozen=True)
class PropertyProviderDescriptor:
    """Stable descriptor for a generic property provider."""

    provider_id: str
    label: str
    order: float = 1000.0
    api_version: str = "1"
    capabilities: Iterable[str] = field(default_factory=tuple)
    dev_only: bool = False
    enabled: bool = True
    visible_fn: ProviderPredicate | None = None
    enabled_fn: ProviderPredicate | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("PropertyProviderDescriptor.provider_id is required")
        if not self.label:
            raise ValueError("PropertyProviderDescriptor.label is required")
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class PropertyProviderContribution:
    """Provider registration carrying a descriptor and adapter factory."""

    descriptor: PropertyProviderDescriptor
    adapter_factory: ProviderAdapterFactory
    on_add: ProviderCallback | None = None
    on_remove: ProviderCallback | None = None

    def __post_init__(self) -> None:
        if not callable(self.adapter_factory):
            raise ValueError("PropertyProviderContribution.adapter_factory must be callable")


@dataclass(frozen=True)
class PropertyProviderBinding:
    """Adapter instance produced for one provider."""

    descriptor: PropertyProviderDescriptor
    adapter: PropertyAdapter


@dataclass(frozen=True)
class PropertyProviderRow:
    """One adapter-backed property row selected for host composition."""

    provider_id: str
    attr_name: str
    metadata: AttributeMetadata
    adapter: PropertyAdapter
    group: str

    @property
    def resettable(self) -> bool:
        clear_value = getattr(type(self.adapter), "clear_value", None)
        return bool(
            self.metadata.is_authored
            and clear_value is not None
            and clear_value is not PropertyAdapter.clear_value
        )

    @property
    def disabled(self) -> bool:
        return bool(self.metadata.is_locked or self.metadata.is_big_array)

    @property
    def status_text(self) -> str:
        if self.metadata.is_locked:
            return "Locked"
        if self.metadata.is_big_array:
            return "Large value"
        if self.metadata.is_time_sampled:
            return "Time sampled"
        if self.metadata.is_authored:
            return "Authored"
        return ""


class PropertyProviderHandle:
    """Removable handle returned from ``PropertyProviderRegistry.add``."""

    def __init__(self, registry: "PropertyProviderRegistry", provider_id: str) -> None:
        self._registry = registry
        self._provider_id = provider_id

    @property
    def id(self) -> str:
        return self._provider_id

    def remove(self) -> bool:
        return self._registry.remove(self._provider_id)


class PropertyProviderRegistry:
    """Registry for generic adapter-backed property providers."""

    def __init__(
        self,
        host: Any = None,
        *,
        capabilities: Iterable[str] = (),
        dev_mode: bool = False,
    ) -> None:
        self._host = host
        self._capabilities: set[str] = set(capabilities)
        self._dev_mode = bool(dev_mode)
        self._entries: dict[str, PropertyProviderContribution] = {}
        self._failures: dict[str, BaseException] = {}

    @property
    def failures(self) -> dict[str, BaseException]:
        return dict(self._failures)

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self._capabilities)

    @property
    def dev_mode(self) -> bool:
        return self._dev_mode

    @dev_mode.setter
    def dev_mode(self, value: bool) -> None:
        self._dev_mode = bool(value)

    def set_capability(self, capability: str, enabled: bool = True) -> None:
        if enabled:
            self._capabilities.add(capability)
        else:
            self._capabilities.discard(capability)

    def add(self, contribution: PropertyProviderContribution) -> PropertyProviderHandle:
        provider_id = contribution.descriptor.provider_id
        if provider_id in self._entries:
            return PropertyProviderHandle(self, provider_id)
        self._entries[provider_id] = contribution
        self._invoke_lifecycle(contribution, "add")
        return PropertyProviderHandle(self, provider_id)

    def remove(self, provider_id: str) -> bool:
        contribution = self._entries.pop(provider_id, None)
        if contribution is None:
            return False
        self._invoke_lifecycle(contribution, "remove")
        return True

    def clear(self) -> None:
        for provider_id in reversed(tuple(self._entries)):
            self.remove(provider_id)

    def iter_contributions(self) -> tuple[PropertyProviderContribution, ...]:
        return tuple(
            contribution
            for contribution in self._ordered_entries()
            if self._is_available(contribution) and self._enabled(contribution)
        )

    def iter_descriptors(self) -> tuple[PropertyProviderDescriptor, ...]:
        return tuple(contribution.descriptor for contribution in self.iter_contributions())

    def adapters_for(
        self,
        payload: Any,
        context: Any = None,
    ) -> tuple[PropertyProviderBinding, ...]:
        bindings: list[PropertyProviderBinding] = []
        for contribution in self.iter_contributions():
            provider_id = contribution.descriptor.provider_id
            try:
                adapter = contribution.adapter_factory(payload, context)
            except Exception as exc:
                self._failures[provider_id] = exc
                self._log("adapter", provider_id, exc)
                continue
            if adapter is None:
                continue
            bindings.append(PropertyProviderBinding(contribution.descriptor, adapter))
        return tuple(bindings)

    def _ordered_entries(self) -> tuple[PropertyProviderContribution, ...]:
        return tuple(
            sorted(
                self._entries.values(),
                key=lambda item: (float(item.descriptor.order), item.descriptor.provider_id),
            )
        )

    def _is_available(self, contribution: PropertyProviderContribution) -> bool:
        descriptor = contribution.descriptor
        if descriptor.dev_only and not self._dev_mode:
            return False
        if any(capability not in self._capabilities for capability in descriptor.capabilities):
            return False
        if descriptor.visible_fn is None:
            return True
        try:
            return bool(descriptor.visible_fn(self._host))
        except Exception as exc:
            self._failures[descriptor.provider_id] = exc
            self._log("visible", descriptor.provider_id, exc)
            return False

    def _enabled(self, contribution: PropertyProviderContribution) -> bool:
        descriptor = contribution.descriptor
        if not descriptor.enabled:
            return False
        if descriptor.enabled_fn is None:
            return True
        try:
            return bool(descriptor.enabled_fn(self._host))
        except Exception as exc:
            self._failures[descriptor.provider_id] = exc
            self._log("enabled", descriptor.provider_id, exc)
            return False

    def _invoke_lifecycle(
        self,
        contribution: PropertyProviderContribution,
        action: str,
    ) -> None:
        fn = contribution.on_add if action == "add" else contribution.on_remove
        if fn is None:
            return
        try:
            fn(self._host)
        except Exception as exc:
            provider_id = contribution.descriptor.provider_id
            self._failures[provider_id] = exc
            self._log(action, provider_id, exc)

    @staticmethod
    def _log(action: str, provider_id: str, exc: BaseException) -> None:
        print(
            f"[ovui_widgets.property.provider_hooks] {action} failed for {provider_id}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


class ProviderPropertyWidget(PropertyWidget):
    """Compose registered provider adapters through existing property rows."""

    def __init__(
        self,
        registry: PropertyProviderRegistry,
        *,
        context_factory: ProviderContextFactory | None = None,
    ) -> None:
        self._registry = registry
        self._context_factory = context_factory
        self._window: Any = None
        self._payload: PropertyPayload | None = None
        self._failures: dict[str, BaseException] = {}

    @property
    def failures(self) -> dict[str, BaseException]:
        return dict(self._failures)

    def set_window(self, window: Any) -> None:
        self._window = window

    def on_new_payload(self, payload: "PropertyPayload") -> bool:
        self._payload = payload
        return bool(self._registry.iter_contributions())

    def build_items(self) -> None:
        if self._payload is None:
            return
        if self._window is not None:
            self._window._inspector_provider_rows = {}
        self._build_grouped_rows(
            self.compose_rows(self._payload, self._context())
        )

    def compose_rows(
        self,
        payload: "PropertyPayload",
        context: Any = None,
    ) -> tuple[PropertyProviderRow, ...]:
        rows: list[PropertyProviderRow] = []
        for binding in self._registry.adapters_for(payload, context):
            provider_id = binding.descriptor.provider_id
            adapter = binding.adapter
            try:
                attr_names = tuple(adapter.get_attribute_names())
            except Exception as exc:
                self._failures[provider_id] = exc
                PropertyProviderRegistry._log("attributes", provider_id, exc)
                continue
            for attr_name in attr_names:
                try:
                    metadata = adapter.get_attribute_metadata(attr_name)
                except Exception as exc:
                    self._failures[f"{provider_id}:{attr_name}"] = exc
                    PropertyProviderRegistry._log("metadata", provider_id, exc)
                    continue
                rows.append(PropertyProviderRow(
                    provider_id=provider_id,
                    attr_name=attr_name,
                    metadata=metadata,
                    adapter=adapter,
                    group=str(metadata.group or ""),
                ))
        return tuple(sorted(rows, key=lambda row: (row.group, row.attr_name)))

    def _build_grouped_rows(self, rows: tuple[PropertyProviderRow, ...]) -> None:
        import omni.ui as ui

        filtered_rows = self._filter_rows(rows)
        if not filtered_rows:
            ui.Label(
                "No properties",
                style_type_name_override="Property.EmptyLabel",
                alignment=ui.Alignment.CENTER,
            )
            return

        root = UiDisplayGroup(name="")
        row_by_metadata: dict[int, PropertyProviderRow] = {}
        for row in filtered_rows:
            row_by_metadata[id(row.metadata)] = row
            path_parts = row.metadata.group.split(".") if row.metadata.group else []
            root.add_prop(row.metadata, path_parts)

        with ui.VStack(spacing=GROUP_STACK_SPACING, height=FIT_CONTENT_HEIGHT):
            self._build_group_children(
                root,
                row_by_metadata,
                path="",
                level=0,
            )

    def _filter_rows(
        self,
        rows: tuple[PropertyProviderRow, ...],
    ) -> tuple[PropertyProviderRow, ...]:
        match = self._filter_text().strip().lower()
        if not match:
            return rows
        return tuple(
            row for row in rows
            if (
                match in row.metadata.display_name.lower()
                or match in row.attr_name.lower()
                or match in row.group.lower()
            )
        )

    def _build_group_children(
        self,
        group: UiDisplayGroup,
        row_by_metadata: dict[int, PropertyProviderRow],
        *,
        path: str,
        level: int,
    ) -> None:
        from ovui_widgets.property.group_widget import AttributeGroupWidget

        collapse_state = self._collapse_state()
        for child in group.get_children():
            if isinstance(child, UiDisplayGroup):
                child_path = f"{path}.{child.name}" if path else child.name
                initial_collapsed = collapse_state.get(child_path, False)
                grp = AttributeGroupWidget(
                    child.name,
                    initially_collapsed=initial_collapsed,
                    on_collapse_change=lambda c, p=child_path: collapse_state.__setitem__(p, c),  # type: ignore[misc]
                    level=level,
                )
                with grp.content:  # type: ignore[union-attr]
                    self._build_group_children(
                        child,
                        row_by_metadata,
                        path=child_path,
                        level=level + 1,
                    )
            else:
                row = row_by_metadata.get(id(child))
                if row is not None:
                    self._build_row(row)

    def _build_row(self, row: PropertyProviderRow) -> None:
        from ovui_widgets.property.builders import WidgetBuilderTable

        try:
            built_row = WidgetBuilderTable.build(
                row.attr_name,
                row.metadata,
                row.adapter,
                match=self._filter_text(),
            )
            if self._window is not None:
                self._window._inspector_provider_rows[row.attr_name] = {
                    "row": built_row,
                    "adapter": row.adapter,
                    "provider_id": row.provider_id,
                }
        except Exception as exc:
            self._failures[f"{row.provider_id}:{row.attr_name}"] = exc
            PropertyProviderRegistry._log("row", row.provider_id, exc)

    def _filter_text(self) -> str:
        if self._window is None:
            return ""
        return str(getattr(self._window, "_filter_text", "") or "")

    def _collapse_state(self) -> dict[str, bool]:
        if self._window is None:
            return {}
        state = getattr(self._window, "_group_collapse_state", None)
        if isinstance(state, dict):
            return state
        return {}

    def destroy(self) -> None:
        self._window = None
        self._payload = None
        self._failures.clear()

    def _context(self) -> Any:
        if self._context_factory is None or self._payload is None:
            return None
        try:
            return self._context_factory(self._window, self._payload)
        except Exception as exc:
            self._failures["context"] = exc
            PropertyProviderRegistry._log("context", "provider-widget", exc)
            return None


__all__ = [
    "PropertyProviderBinding",
    "PropertyProviderContribution",
    "PropertyProviderDescriptor",
    "PropertyProviderHandle",
    "PropertyProviderRegistry",
    "PropertyProviderRow",
    "ProviderPropertyWidget",
]

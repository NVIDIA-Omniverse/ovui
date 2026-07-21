# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Entry-point registry for data-adapter providers."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
import traceback
from typing import Any, Callable, Iterable


ADAPTER_ENTRY_POINT_GROUP = "ovui_data_adapters.adapters"
AdapterFactory = Callable[..., Any]


class AdapterRegistryError(Exception):
    """Base exception raised by the common adapter registry."""


class DuplicateAdapterProviderError(AdapterRegistryError):
    """Raised when two providers use the same registry name."""


class AdapterProviderNotFoundError(AdapterRegistryError):
    """Raised when an explicitly requested provider is unavailable."""


class AdapterProviderSelectionError(AdapterRegistryError):
    """Raised when no adapter provider can be selected."""


@dataclass(frozen=True)
class AdapterFactories:
    """Factory callables exposed by one registered provider."""

    stage: AdapterFactory | None = None
    properties: AdapterFactory | None = None
    transforms: AdapterFactory | None = None
    renderer: AdapterFactory | None = None
    selection: AdapterFactory | None = None
    layers: AdapterFactory | None = None
    session: AdapterFactory | None = None


@dataclass(frozen=True)
class AdapterProvider:
    """Provider metadata and factories registered through common."""

    name: str
    priority: int
    requirements: tuple[str, ...]
    factories: AdapterFactories


@dataclass(frozen=True)
class AdapterModuleLoadFailure:
    """Structured diagnostic for one failed adapter entry point."""

    name: str
    value: str
    exception_type: str
    message: str
    traceback_summary: tuple[str, ...]
    module_name: str = ""
    entry_point_value: str = ""
    requirement_name: str | None = None
    exception_text: str = ""

    @classmethod
    def from_exception(
        cls,
        name: str,
        value: str,
        exc: BaseException,
    ) -> "AdapterModuleLoadFailure":
        module_name = str(getattr(exc, "module_name", name))
        entry_point_value = str(getattr(exc, "entry_point_value", value))
        requirement_name = getattr(exc, "requirement_name", None)
        exception_text = str(getattr(exc, "exception_text", str(exc)))
        return cls(
            name=name,
            value=value,
            exception_type=type(exc).__name__,
            message=str(exc),
            traceback_summary=tuple(
                line.rstrip()
                for line in traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
            module_name=module_name,
            entry_point_value=entry_point_value,
            requirement_name=requirement_name,
            exception_text=exception_text,
        )


class AdapterRegistry:
    """Collect and select data-adapter providers discovered by common."""

    def __init__(self) -> None:
        self._providers: dict[str, AdapterProvider] = {}
        self._load_failures: list[AdapterModuleLoadFailure] = []
        self._active_provider_name: str | None = None

    @property
    def load_failures(self) -> tuple[AdapterModuleLoadFailure, ...]:
        return tuple(self._load_failures)

    @property
    def module_load_failures(self) -> tuple[AdapterModuleLoadFailure, ...]:
        return self.load_failures

    @property
    def active_provider(self) -> AdapterProvider | None:
        if self._active_provider_name is None:
            return None
        return self._providers.get(self._active_provider_name)

    def available_adapters(self) -> tuple[AdapterProvider, ...]:
        return tuple(
            self._providers[name]
            for name in sorted(self._providers)
        )

    def register_adapter(
        self,
        *,
        name: str,
        priority: int = 0,
        requirements: Iterable[str] = (),
        factories: AdapterFactories,
    ) -> AdapterProvider:
        provider_name = self._normalize_provider_name(name)
        if provider_name in self._providers:
            raise DuplicateAdapterProviderError(
                f"adapter provider already registered: {provider_name}"
            )
        if not isinstance(priority, int):
            raise TypeError("priority must be an int")
        if not isinstance(factories, AdapterFactories):
            raise TypeError("factories must be an AdapterFactories instance")

        provider = AdapterProvider(
            name=provider_name,
            priority=priority,
            requirements=tuple(requirements),
            factories=factories,
        )
        self._providers[provider_name] = provider
        return provider

    def require_adapter(self, name: str) -> AdapterProvider:
        provider_name = self._normalize_provider_name(name)
        try:
            return self._providers[provider_name]
        except KeyError as exc:
            for failure in self._load_failures:
                if self._normalize_provider_name(failure.name) == provider_name:
                    raise AdapterProviderNotFoundError(failure.message) from exc
            available = ", ".join(sorted(self._providers)) or "none"
            raise AdapterProviderNotFoundError(
                f"adapter provider not found: {provider_name}; available: {available}"
            ) from exc

    def report_module_load_failure(
        self,
        name: str,
        value: str,
        exc: BaseException,
    ) -> AdapterModuleLoadFailure:
        failure = AdapterModuleLoadFailure.from_exception(name, value, exc)
        self._load_failures.append(failure)
        return failure

    def select_adapter(self, requested_name: str | None = None) -> AdapterProvider:
        if requested_name:
            provider = self.require_adapter(requested_name)
        else:
            providers = self.available_adapters()
            if not providers:
                raise AdapterProviderSelectionError(
                    "no adapter providers are registered"
                )
            if len(providers) == 1:
                provider = providers[0]
            else:
                provider = sorted(
                    providers,
                    key=lambda item: (-item.priority, item.name),
                )[0]
        self._active_provider_name = provider.name
        return provider

    def get_adapter_factories(
        self,
        requested_name: str | None = None,
    ) -> AdapterFactories:
        return self.select_adapter(requested_name).factories

    @staticmethod
    def _normalize_provider_name(name: str) -> str:
        provider_name = str(name).strip()
        if not provider_name:
            raise ValueError("adapter provider name must not be empty")
        return provider_name


def discover_adapter_modules(
    registry: AdapterRegistry | None = None,
    requested_name: str | None = None,
) -> AdapterRegistry:
    target_registry = registry if registry is not None else AdapterRegistry()
    requested = str(requested_name or "").strip()
    for entry_point in entry_points(group=ADAPTER_ENTRY_POINT_GROUP):
        if requested and str(entry_point.name).strip() != requested:
            continue
        try:
            register = entry_point.load()
            register(target_registry)
        except Exception as exc:
            target_registry.report_module_load_failure(
                entry_point.name,
                entry_point.value,
                exc,
            )
    return target_registry


def select_adapter(
    registry: AdapterRegistry,
    requested_name: str | None = None,
) -> AdapterProvider:
    return registry.select_adapter(requested_name)


def get_adapter_factories(
    registry: AdapterRegistry | None = None,
    requested_name: str | None = None,
) -> AdapterFactories:
    target_registry = (
        discover_adapter_modules(requested_name=requested_name)
        if registry is None
        else registry
    )
    return target_registry.get_adapter_factories(requested_name)

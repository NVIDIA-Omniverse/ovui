# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Runtime preflight for the ovstage data-adapter provider."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import os
from types import ModuleType

from ovui_data_adapters.common.ovrtx_import import import_ovrtx
from ovui_data_adapters.ovstage.runtime_import import import_ovstage_runtime_module


OVSTAGE_INSTALL_MESSAGE = "Please install ovstage."


@dataclass(frozen=True)
class RuntimeRequirement:
    """One runtime module that must import and expose expected API."""

    name: str
    module_name: str
    expected_attributes: tuple[str, ...] = ()
    expected_callables: tuple[str, ...] = ()


@dataclass(frozen=True)
class LoadedRuntime:
    """One runtime module loaded by preflight."""

    requirement: RuntimeRequirement
    module: ModuleType


@dataclass(frozen=True)
class LoadedRuntimes:
    """All runtime modules required by the ovstage provider."""

    modules: tuple[LoadedRuntime, ...]

    def module(self, requirement_name: str) -> ModuleType:
        for loaded in self.modules:
            if loaded.requirement.name == requirement_name:
                return loaded.module
        raise KeyError(requirement_name)

    @property
    def requirement_names(self) -> tuple[str, ...]:
        return tuple(loaded.requirement.name for loaded in self.modules)


class OvstageRuntimePreflightError(RuntimeError):
    """Structured startup error for a failed ovstage runtime requirement."""

    def __init__(
        self,
        *,
        module_name: str,
        entry_point_value: str,
        requirement_name: str,
        exception: BaseException,
    ) -> None:
        self.module_name = module_name
        self.entry_point_value = entry_point_value
        self.requirement_name = requirement_name
        self.exception_text = f"{type(exception).__name__}: {exception}"
        if requirement_name == "ovstage" and isinstance(exception, ImportError):
            message = OVSTAGE_INSTALL_MESSAGE
        else:
            message = (
                f"{module_name} runtime requirement {requirement_name!r} failed: "
                f"{self.exception_text}"
            )
        super().__init__(message)


class MissingRuntimeApiError(RuntimeError):
    """A selected native runtime does not expose one required API."""

    def __init__(self, api_name: str) -> None:
        self.api_name = str(api_name)
        super().__init__(
            f"required runtime API is missing or not callable: {self.api_name}"
        )


OVRTX_BORROW_RENDERER_CALLABLES = (
    "attach_ovstage",
    "detach_ovstage",
    "step",
)

OVRTX_RUNTIME_REQUIREMENT = RuntimeRequirement(
    "ovrtx",
    "ovrtx",
    expected_callables=(
        "RendererConfig",
        "Renderer",
        *(f"Renderer.{name}" for name in OVRTX_BORROW_RENDERER_CALLABLES),
    ),
)

REQUIRED_RUNTIME_REQUIREMENTS = (
    RuntimeRequirement("ovstage", "ovstage", expected_callables=("Stage",)),
)

LEGACY_RUNTIME_REQUIREMENTS = (
    RuntimeRequirement("ovhierarchy", "ovhierarchy", ("Hierarchy",)),
)

OPTIONAL_RUNTIME_REQUIREMENTS = (
    RuntimeRequirement("ovphysx", "ovphysx", ("PhysXConfig",)),
)


def _import_requirement_module(requirement: RuntimeRequirement) -> ModuleType:
    if requirement.module_name == "ovrtx":
        result = import_ovrtx()
        if result.module is None:
            raise result.error or ImportError("ovrtx not available")
        return result.module
    return import_ovstage_runtime_module(
        requirement.module_name,
        import_module_fn=import_module,
    )


def _require_api(
    owner: object,
    attribute_path: str,
    *,
    api_prefix: str,
    callable_only: bool,
) -> object:
    value = owner
    for attribute_name in attribute_path.split("."):
        value = getattr(value, attribute_name, None)
        if value is None:
            raise MissingRuntimeApiError(f"{api_prefix}.{attribute_path}")
    if callable_only and not callable(value):
        raise MissingRuntimeApiError(f"{api_prefix}.{attribute_path}")
    return value


def validate_runtime_requirement(
    requirement: RuntimeRequirement,
    module: ModuleType,
) -> None:
    """Require the exact public API used from one imported runtime module."""

    for attribute_path in requirement.expected_attributes:
        _require_api(
            module,
            attribute_path,
            api_prefix=requirement.module_name,
            callable_only=False,
        )
    for attribute_path in requirement.expected_callables:
        _require_api(
            module,
            attribute_path,
            api_prefix=requirement.module_name,
            callable_only=True,
        )


def validate_ovrtx_borrow_renderer(renderer: object) -> None:
    """Require BORROW methods on the constructed renderer instance."""

    for method_name in OVRTX_BORROW_RENDERER_CALLABLES:
        _require_api(
            renderer,
            method_name,
            api_prefix="ovrtx.Renderer",
            callable_only=True,
        )


def load_required_runtimes(
    *,
    module_name: str,
    entry_point_value: str,
    requirements: tuple[RuntimeRequirement, ...] = REQUIRED_RUNTIME_REQUIREMENTS,
) -> LoadedRuntimes:
    """Import every runtime required before ovstage factories are exposed."""
    os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")
    loaded_modules: list[LoadedRuntime] = []
    for requirement in requirements:
        try:
            module = _import_requirement_module(requirement)
            validate_runtime_requirement(requirement, module)
        except Exception as exc:
            raise OvstageRuntimePreflightError(
                module_name=module_name,
                entry_point_value=entry_point_value,
                requirement_name=requirement.name,
                exception=exc,
            ) from exc
        loaded_modules.append(LoadedRuntime(requirement, module))
    return LoadedRuntimes(tuple(loaded_modules))

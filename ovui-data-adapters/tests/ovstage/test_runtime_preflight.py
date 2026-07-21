# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Runtime preflight diagnostics for the ovstage provider."""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest

from ovui_data_adapters.common import (
    AdapterProviderNotFoundError,
    AdapterRegistry,
    select_adapter,
)
from ovui_data_adapters.common.ovrtx_import import OvRtxImportResult
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    PROVIDER_REQUIREMENTS,
)
from ovui_data_adapters.ovstage.register import register
from ovui_data_adapters.ovstage.runtime_preflight import (
    LEGACY_RUNTIME_REQUIREMENTS,
    MissingRuntimeApiError,
    OVRTX_RUNTIME_REQUIREMENT,
    OVSTAGE_INSTALL_MESSAGE,
    REQUIRED_RUNTIME_REQUIREMENTS,
    OvstageRuntimePreflightError,
    load_required_runtimes,
)
import ovui_data_adapters.ovstage.runtime_preflight as preflight_module


REQUIRED_RUNTIME_NAMES = tuple(
    requirement.name for requirement in REQUIRED_RUNTIME_REQUIREMENTS
)


def _patch_missing_runtime(
    monkeypatch: pytest.MonkeyPatch,
    missing_requirement_name: str,
) -> None:
    _patch_runtime_modules(monkeypatch, missing_requirement_name=missing_requirement_name)


def _patch_runtime_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    missing_requirement_name: str | None = None,
) -> None:
    monkeypatch.delenv("OVSTAGE_ROOT", raising=False)
    monkeypatch.delenv("OVSTAGE_BUILD_DIR", raising=False)
    monkeypatch.delenv("OVSTAGE_LIBRARY_PATH", raising=False)
    monkeypatch.delenv("OVPOPULATION_LIBRARY_PATH", raising=False)
    monkeypatch.delenv("OVHIERARCHY_LIBRARY_PATH", raising=False)
    requirements_by_module = {
        requirement.module_name: requirement
        for requirement in (*REQUIRED_RUNTIME_REQUIREMENTS, *LEGACY_RUNTIME_REQUIREMENTS)
    }

    def fake_import_module(name: str, package: str | None = None) -> ModuleType:
        requirement = requirements_by_module.get(name)
        if requirement is None:
            return importlib.import_module(name, package)
        if requirement.name == "ovrtx":
            raise AssertionError("ovrtx must use the shared resolver")
        if requirement.name == missing_requirement_name:
            raise ModuleNotFoundError(
                f"mocked missing runtime: {missing_requirement_name}",
                name=name,
            )
        module = ModuleType(requirement.module_name)
        for attribute_name in requirement.expected_attributes:
            setattr(module, attribute_name, object())
        for callable_name in requirement.expected_callables:
            setattr(module, callable_name, lambda: None)
        return module

    def fake_import_ovrtx() -> OvRtxImportResult:
        raise AssertionError("ovrtx must not be required for ovstage preflight")

    monkeypatch.setattr(preflight_module, "import_module", fake_import_module)
    monkeypatch.setattr(preflight_module, "import_ovrtx", fake_import_ovrtx)


@pytest.mark.parametrize("missing_requirement_name", REQUIRED_RUNTIME_NAMES)
def test_missing_runtime_preflight_records_structured_load_failure(
    monkeypatch: pytest.MonkeyPatch,
    missing_requirement_name: str,
) -> None:
    _patch_missing_runtime(monkeypatch, missing_requirement_name)
    registry = AdapterRegistry()

    register(registry)

    assert registry.available_adapters() == ()
    assert len(registry.load_failures) == 1
    failure = registry.load_failures[0]
    assert failure.name == PROVIDER_NAME
    assert failure.module_name == PROVIDER_NAME
    assert failure.value == PROVIDER_ENTRY_POINT_VALUE
    assert failure.entry_point_value == PROVIDER_ENTRY_POINT_VALUE
    assert failure.requirement_name == missing_requirement_name
    assert failure.exception_type == "OvstageRuntimePreflightError"
    assert "ModuleNotFoundError" in failure.exception_text
    assert f"mocked missing runtime: {missing_requirement_name}" in failure.exception_text
    if missing_requirement_name == "ovstage":
        assert failure.message == OVSTAGE_INSTALL_MESSAGE
    else:
        assert missing_requirement_name in failure.message

    with pytest.raises(AdapterProviderNotFoundError) as exc_info:
        select_adapter(registry, requested_name=PROVIDER_NAME)
    if missing_requirement_name == "ovstage":
        assert str(exc_info.value) == OVSTAGE_INSTALL_MESSAGE


def test_happy_path_preflight_loads_all_runtimes_and_exposes_factories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime_modules(monkeypatch)
    registry = AdapterRegistry()

    register(registry)

    assert registry.load_failures == ()
    provider = select_adapter(registry, requested_name=PROVIDER_NAME)
    assert provider.requirements == PROVIDER_REQUIREMENTS
    assert provider.requirements == (
        "ovstage",
        "ovrtx",
    )
    assert callable(provider.factories.stage)
    assert callable(provider.factories.properties)
    assert callable(provider.factories.transforms)
    assert callable(provider.factories.renderer)
    assert callable(provider.factories.selection)
    assert callable(provider.factories.layers)
    assert callable(provider.factories.session)

    session = provider.factories.session()
    session.prepare_runtime_imports()


def test_preflight_result_names_loaded_runtime_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime_modules(monkeypatch)
    runtime = load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )

    assert runtime.requirement_names == REQUIRED_RUNTIME_NAMES
    for requirement_name in REQUIRED_RUNTIME_NAMES:
        assert runtime.module(requirement_name).__name__ == requirement_name


def test_legacy_ovhierarchy_can_still_be_preflighted_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime_modules(monkeypatch)

    runtime = load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
        requirements=(*REQUIRED_RUNTIME_REQUIREMENTS, *LEGACY_RUNTIME_REQUIREMENTS),
    )

    assert runtime.requirement_names == ("ovstage", "ovhierarchy")
    assert runtime.module("ovhierarchy").__name__ == "ovhierarchy"


def _ovrtx_borrow_module(*, missing_api: str | None = None) -> ModuleType:
    module = ModuleType("ovrtx")

    class AttachMode:
        BORROW = 0

    class RendererConfig:
        pass

    class Renderer:
        def attach_ovstage(self) -> None:
            return None

        def detach_ovstage(self) -> None:
            return None

        def step(self) -> None:
            return None

    module.AttachMode = AttachMode
    module.RendererConfig = RendererConfig
    module.Renderer = Renderer
    if missing_api == "ovrtx.AttachMode.BORROW":
        del AttachMode.BORROW
    elif missing_api == "ovrtx.RendererConfig":
        del module.RendererConfig
    elif missing_api == "ovrtx.Renderer":
        del module.Renderer
    elif missing_api is not None:
        setattr(Renderer, missing_api.rsplit(".", 1)[-1], None)
    return module


@pytest.mark.parametrize(
    "missing_api",
    (
        "ovrtx.RendererConfig",
        "ovrtx.Renderer",
        "ovrtx.Renderer.attach_ovstage",
        "ovrtx.Renderer.detach_ovstage",
        "ovrtx.Renderer.step",
    ),
)
def test_ovrtx_borrow_preflight_names_the_exact_missing_api(
    monkeypatch: pytest.MonkeyPatch,
    missing_api: str,
) -> None:
    module = _ovrtx_borrow_module(missing_api=missing_api)
    monkeypatch.setattr(
        preflight_module,
        "_import_requirement_module",
        lambda _requirement: module,
    )

    with pytest.raises(OvstageRuntimePreflightError) as exc_info:
        load_required_runtimes(
            module_name=PROVIDER_NAME,
            entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
            requirements=(OVRTX_RUNTIME_REQUIREMENT,),
        )

    assert isinstance(exc_info.value.__cause__, MissingRuntimeApiError)
    assert exc_info.value.__cause__.api_name == missing_api
    assert missing_api in str(exc_info.value)


def test_ovrtx_borrow_preflight_accepts_current_default_borrow_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _ovrtx_borrow_module()
    del module.AttachMode
    monkeypatch.setattr(
        preflight_module,
        "_import_requirement_module",
        lambda _requirement: module,
    )

    runtime = load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
        requirements=(OVRTX_RUNTIME_REQUIREMENT,),
    )

    assert runtime.module("ovrtx") is module


def test_ovstage_preflight_requires_callable_stage_with_exact_api_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("ovstage")
    module.Stage = object()
    monkeypatch.setattr(
        preflight_module,
        "_import_requirement_module",
        lambda _requirement: module,
    )

    with pytest.raises(OvstageRuntimePreflightError) as exc_info:
        load_required_runtimes(
            module_name=PROVIDER_NAME,
            entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
        )

    assert isinstance(exc_info.value.__cause__, MissingRuntimeApiError)
    assert exc_info.value.__cause__.api_name == "ovstage.Stage"
    assert "ovstage.Stage" in str(exc_info.value)

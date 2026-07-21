# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for common data-adapter entry-point discovery and selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pytest

from ovui_data_adapters.common import (
    ADAPTER_ENTRY_POINT_GROUP,
    AdapterFactories,
    AdapterRegistry,
    DuplicateAdapterProviderError,
    discover_adapter_modules,
    select_adapter,
)
import ovui_data_adapters.common._adapter_registry as registry_module


RegisterCallable = Callable[[AdapterRegistry], None]


@dataclass(frozen=True)
class FakeEntryPoint:
    name: str
    value: str
    register: RegisterCallable

    def load(self) -> RegisterCallable:
        return self.register


def _factories(label: str) -> AdapterFactories:
    return AdapterFactories(stage=lambda: label)


def _register_provider(
    name: str,
    *,
    priority: int = 0,
    requirements: tuple[str, ...] = (),
) -> RegisterCallable:
    def register(registry: AdapterRegistry) -> None:
        registry.register_adapter(
            name=name,
            priority=priority,
            requirements=requirements,
            factories=_factories(name),
        )

    return register


def _raising_register(exc: Exception) -> RegisterCallable:
    def register(registry: AdapterRegistry) -> None:
        raise exc

    return register


def _install_entry_points(
    monkeypatch: pytest.MonkeyPatch,
    entries: tuple[FakeEntryPoint, ...],
) -> None:
    def fake_entry_points(*, group: str):
        assert group == ADAPTER_ENTRY_POINT_GROUP
        return entries

    monkeypatch.setattr(registry_module, "entry_points", fake_entry_points)


def test_discovery_registers_multiple_providers_from_fake_entry_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_entry_points(
        monkeypatch,
        (
            FakeEntryPoint(
                "beta",
                "fake_beta:register",
                _register_provider("beta", priority=20, requirements=("ovrtx",)),
            ),
            FakeEntryPoint(
                "alpha",
                "fake_alpha:register",
                _register_provider("alpha", priority=10, requirements=("ovstage",)),
            ),
        ),
    )

    registry = discover_adapter_modules()

    providers = registry.available_adapters()
    assert [provider.name for provider in providers] == ["alpha", "beta"]
    assert providers[0].priority == 10
    assert providers[0].requirements == ("ovstage",)
    assert providers[0].factories.stage() == "alpha"
    assert providers[1].priority == 20
    assert providers[1].requirements == ("ovrtx",)
    assert registry.load_failures == ()


def test_discovery_records_register_failure_without_aborting_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_entry_points(
        monkeypatch,
        (
            FakeEntryPoint(
                "broken",
                "fake_broken:register",
                _raising_register(RuntimeError("runtime module unavailable")),
            ),
            FakeEntryPoint(
                "working",
                "fake_working:register",
                _register_provider("working"),
            ),
        ),
    )

    registry = discover_adapter_modules()

    assert [provider.name for provider in registry.available_adapters()] == ["working"]
    assert len(registry.load_failures) == 1
    assert registry.module_load_failures == registry.load_failures
    failure = registry.load_failures[0]
    assert failure.name == "broken"
    assert failure.value == "fake_broken:register"
    assert failure.exception_type == "RuntimeError"
    assert failure.message == "runtime module unavailable"
    assert any("RuntimeError" in line for line in failure.traceback_summary)


def test_requested_provider_selection_wins_over_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_entry_points(
        monkeypatch,
        (
            FakeEntryPoint(
                "low",
                "fake_low:register",
                _register_provider("low", priority=1),
            ),
            FakeEntryPoint(
                "high",
                "fake_high:register",
                _register_provider("high", priority=100),
            ),
        ),
    )
    registry = discover_adapter_modules()

    selected = select_adapter(registry, requested_name="low")

    assert selected.name == "low"
    assert registry.active_provider == selected
    assert selected.factories.stage() == "low"


def test_single_provider_is_selected_without_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_entry_points(
        monkeypatch,
        (
            FakeEntryPoint(
                "only",
                "fake_only:register",
                _register_provider("only", priority=-10),
            ),
        ),
    )
    registry = discover_adapter_modules()

    selected = select_adapter(registry)

    assert selected.name == "only"
    assert registry.active_provider == selected


def test_priority_selection_is_deterministic_for_multiple_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_entry_points(
        monkeypatch,
        (
            FakeEntryPoint(
                "beta",
                "fake_beta:register",
                _register_provider("beta", priority=50),
            ),
            FakeEntryPoint(
                "gamma",
                "fake_gamma:register",
                _register_provider("gamma", priority=10),
            ),
            FakeEntryPoint(
                "alpha",
                "fake_alpha:register",
                _register_provider("alpha", priority=50),
            ),
        ),
    )
    registry = discover_adapter_modules()

    selected = select_adapter(registry)

    assert selected.name == "alpha"
    assert selected.priority == 50
    assert registry.active_provider == selected


def test_duplicate_provider_name_from_fake_entry_point_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_entry_points(
        monkeypatch,
        (
            FakeEntryPoint(
                "first",
                "fake_first:register",
                _register_provider("same", priority=10),
            ),
            FakeEntryPoint(
                "second",
                "fake_second:register",
                _register_provider("same", priority=100),
            ),
        ),
    )

    registry = discover_adapter_modules()

    providers = registry.available_adapters()
    assert [provider.name for provider in providers] == ["same"]
    assert providers[0].priority == 10
    assert len(registry.load_failures) == 1
    failure = registry.load_failures[0]
    assert failure.name == "second"
    assert failure.value == "fake_second:register"
    assert failure.exception_type == DuplicateAdapterProviderError.__name__
    assert failure.message == "adapter provider already registered: same"

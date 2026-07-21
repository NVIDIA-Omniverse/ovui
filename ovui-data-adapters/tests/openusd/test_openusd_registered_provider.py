# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""OpenUSD provider registration through the common adapter registry."""

from __future__ import annotations

from importlib.metadata import entry_points

import pytest

from ovui_data_adapters.common import (
    ADAPTER_ENTRY_POINT_GROUP,
    discover_adapter_modules,
    select_adapter,
)


pytest.importorskip("pxr", reason="OpenUSD runtime is unavailable")


def test_openusd_entry_point_metadata_uses_common_adapter_group() -> None:
    candidates = {
        entry_point.name: entry_point
        for entry_point in entry_points(group=ADAPTER_ENTRY_POINT_GROUP)
    }

    entry_point = candidates.get("openusd")

    assert entry_point is not None
    assert entry_point.group == ADAPTER_ENTRY_POINT_GROUP
    assert entry_point.value == "ovui_data_adapters.openusd.register:register"


def test_openusd_provider_is_discoverable_and_selectable_through_common() -> None:
    registry = discover_adapter_modules()

    provider = registry.require_adapter("openusd")
    selected = select_adapter(registry, requested_name="openusd")

    assert selected is provider
    assert registry.active_provider is provider
    assert provider.name == "openusd"
    assert "openusd" in provider.requirements
    assert "ovrtx" not in provider.requirements
    assert callable(provider.factories.stage)
    assert callable(provider.factories.properties)
    assert callable(provider.factories.transforms)
    assert callable(provider.factories.renderer)
    assert callable(provider.factories.layers)
    assert callable(provider.factories.session)
    assert all(failure.name != "openusd" for failure in registry.load_failures)

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Entry-point registration for the ovstage data-adapter provider."""

from __future__ import annotations

from typing import Any

from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    PROVIDER_PRIORITY,
    PROVIDER_REQUIREMENTS,
    build_factories,
)
from ovui_data_adapters.ovstage.runtime_preflight import OvstageRuntimePreflightError


def register(registry: Any) -> None:
    try:
        factories = build_factories()
    except OvstageRuntimePreflightError as exc:
        registry.report_module_load_failure(
            PROVIDER_NAME,
            PROVIDER_ENTRY_POINT_VALUE,
            exc,
        )
        return

    registry.register_adapter(
        name=PROVIDER_NAME,
        priority=PROVIDER_PRIORITY,
        requirements=PROVIDER_REQUIREMENTS,
        factories=factories,
    )

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovstage data-adapter scaffold registered through common."""

from ovui_data_adapters.ovstage._scene import (
    OvstagePopulationFailure,
    OvstageScene,
    OvstageSceneOpenError,
)
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    PROVIDER_PRIORITY,
    PROVIDER_REQUIREMENTS,
    OvstagePhysicsControlError,
    OvstagePhysicsControlFailure,
    OvstagePhysicsControls,
    OvstageProviderSession,
    build_factories,
)
from ovui_data_adapters.ovstage.register import register
from ovui_data_adapters.ovstage.runtime_preflight import (
    REQUIRED_RUNTIME_REQUIREMENTS,
    LoadedRuntimes,
    OvstageRuntimePreflightError,
    load_required_runtimes,
)

__all__ = [
    "PROVIDER_ENTRY_POINT_VALUE",
    "PROVIDER_NAME",
    "PROVIDER_PRIORITY",
    "PROVIDER_REQUIREMENTS",
    "REQUIRED_RUNTIME_REQUIREMENTS",
    "LoadedRuntimes",
    "OvstagePopulationFailure",
    "OvstagePhysicsControlError",
    "OvstagePhysicsControlFailure",
    "OvstagePhysicsControls",
    "OvstageProviderSession",
    "OvstageScene",
    "OvstageSceneOpenError",
    "OvstageRuntimePreflightError",
    "build_factories",
    "load_required_runtimes",
    "register",
]

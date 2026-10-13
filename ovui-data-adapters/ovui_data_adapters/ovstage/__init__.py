# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ovstage data-adapter scaffold registered through common."""

from ovui_data_adapters.ovstage._scene import (
    OvstagePopulationFailure,
    OvstageScene,
    OvstageSceneOpenError,
    open_scene_from_file,
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
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter
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
    "OvstageRendererAdapter",
    "OvstageScene",
    "OvstageSceneOpenError",
    "OvstageRuntimePreflightError",
    "build_factories",
    "load_required_runtimes",
    "open_scene_from_file",
    "register",
]

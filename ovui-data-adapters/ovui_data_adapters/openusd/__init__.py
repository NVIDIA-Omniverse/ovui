# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""OpenUSD-specific data-adapter implementations.

Step 11 introduced the first relocated module: ``commands`` — three
concrete USD-mutation undo commands (``SetVisibilityCommand``,
``DeletePrimCommand``, ``NamespaceEditCommand``). Step 12 added
``UsdPropertyAdapter``, the USD-backed concrete property adapter.
Step 13 relocates the ``read_bound_camera`` parser and
``UsdStageAdapter`` itself; the moved files carry zero ``ovui_widgets.*``
runtime imports and rely on protocol-typed interfaces from
the common adapter interfaces.
"""

from ovui_data_adapters.openusd.bound_camera import read_bound_camera
from ovui_data_adapters.openusd.commands import (
    CameraPoseCommand,
    DeletePrimCommand,
    NamespaceEditCommand,
    SetVisibilityCommand,
)
from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter
from ovui_data_adapters.openusd.property_adapter import UsdPropertyAdapter
from ovui_data_adapters.openusd.renderer_adapter import (
    AVAILABLE,
    OvRtxRendererAdapter,
)
from ovui_data_adapters.openusd.provider import OpenUSDProviderSession
from ovui_data_adapters.openusd.stage_adapter import HAS_USD, UsdStageAdapter
from ovui_data_adapters.openusd.transform_adapter import UsdTransformAdapter

__all__ = [
    "AVAILABLE",
    "CameraPoseCommand",
    "DeletePrimCommand",
    "HAS_USD",
    "NamespaceEditCommand",
    "OvRtxRendererAdapter",
    "OpenUSDProviderSession",
    "SetVisibilityCommand",
    "UsdLayerStackAdapter",
    "UsdPropertyAdapter",
    "UsdStageAdapter",
    "UsdTransformAdapter",
    "read_bound_camera",
]

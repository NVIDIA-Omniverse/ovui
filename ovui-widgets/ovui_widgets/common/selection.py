# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Compatibility exports for selection state and eventing.

The canonical frontend-neutral implementation lives in
``ovui_data_adapters.services.selection``.
"""

from ovui_data_adapters.services.selection import (
    SelectionBus,
    SelectionBusError,
    SelectionChangedEvent,
    SelectionItem,
    SelectionSnapshot,
    Subscription,
)

__all__ = [
    "SelectionBus",
    "SelectionBusError",
    "SelectionChangedEvent",
    "SelectionItem",
    "SelectionSnapshot",
    "Subscription",
]

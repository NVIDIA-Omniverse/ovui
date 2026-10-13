# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

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

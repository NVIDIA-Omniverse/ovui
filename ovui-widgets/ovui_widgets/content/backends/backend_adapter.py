# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compatibility exports for the content backend service.

The canonical implementation lives in
``ovui_data_adapters.services.content.backends.backend_adapter``.
"""

from ovui_data_adapters.services.content.backends.backend_adapter import (
    BackendAdapter,
    BackendChangeEvent,
    BackendFileFlags,
    BackendListEntry,
    BackendResult,
)

__all__ = [
    "BackendAdapter",
    "BackendChangeEvent",
    "BackendFileFlags",
    "BackendListEntry",
    "BackendResult",
]

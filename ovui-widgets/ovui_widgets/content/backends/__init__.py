# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compatibility exports for content backend services.

Canonical backend contracts and local filesystem behavior live in
``ovui_data_adapters.services.content.backends``.
"""

from ovui_data_adapters.services.content.backends import (
    BackendAdapter,
    BackendChangeEvent,
    BackendFileFlags,
    BackendListEntry,
    BackendResult,
    LocalFSBackend,
)

__all__ = [
    "BackendAdapter",
    "BackendChangeEvent",
    "BackendFileFlags",
    "BackendListEntry",
    "BackendResult",
    "LocalFSBackend",
]

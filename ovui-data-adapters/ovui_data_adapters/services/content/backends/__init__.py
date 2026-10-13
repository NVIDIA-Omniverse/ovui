# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""URL-based content storage backend service."""

from ovui_data_adapters.services.content.backends.backend_adapter import (
    BackendAdapter,
    BackendChangeEvent,
    BackendFileFlags,
    BackendListEntry,
    BackendResult,
)
from ovui_data_adapters.services.content.backends.local_fs_backend import LocalFSBackend

__all__ = [
    "BackendAdapter",
    "BackendChangeEvent",
    "BackendFileFlags",
    "BackendListEntry",
    "BackendResult",
    "LocalFSBackend",
]

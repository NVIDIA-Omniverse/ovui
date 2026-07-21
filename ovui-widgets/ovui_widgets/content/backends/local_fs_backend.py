# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Compatibility exports for the local filesystem content backend service.

The canonical implementation lives in
``ovui_data_adapters.services.content.backends.local_fs_backend``.
"""

from ovui_data_adapters.services.content.backends.local_fs_backend import (
    BackendAdapter,
    BackendFileFlags,
    BackendListEntry,
    BackendResult,
    LocalFSBackend,
    _canonicalise,
    _fspath_to_url,
    _SCHEME,
    _stat_to_flags,
    _url_to_fspath,
    _WIN_HIDDEN_ATTR,
)

__all__ = [
    "BackendAdapter",
    "BackendFileFlags",
    "BackendListEntry",
    "BackendResult",
    "LocalFSBackend",
    "_SCHEME",
    "_WIN_HIDDEN_ATTR",
    "_canonicalise",
    "_fspath_to_url",
    "_stat_to_flags",
    "_url_to_fspath",
]

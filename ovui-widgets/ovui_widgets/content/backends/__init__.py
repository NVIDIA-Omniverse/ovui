# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

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

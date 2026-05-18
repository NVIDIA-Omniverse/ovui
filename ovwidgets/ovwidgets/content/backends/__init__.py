# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovwidgets.content.backends: URL-based storage abstraction for the content browser.

Every content-browser read, write, stat, list, copy, move, delete, or
change-subscription funnels through :class:`BackendAdapter`. This is
ovgear's equivalent of ``omni.client`` — see
the content browser behavior and the content browser implementation step 1.
"""

from ovwidgets.content.backends.backend_adapter import (
    BackendAdapter,
    BackendChangeEvent,
    BackendFileFlags,
    BackendListEntry,
    BackendResult,
)
from ovwidgets.content.backends.local_fs_backend import LocalFSBackend

__all__ = [
    "BackendAdapter",
    "BackendChangeEvent",
    "BackendFileFlags",
    "BackendListEntry",
    "BackendResult",
    "LocalFSBackend",
]

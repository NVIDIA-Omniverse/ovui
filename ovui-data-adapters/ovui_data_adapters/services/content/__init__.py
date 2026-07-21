# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Frontend-neutral content services."""

from ovui_data_adapters.services.content.asset_types import (
    AssetCategory,
    AssetTypeDef,
    categories,
    get_category,
    get_display_name,
    get_icon_url_key,
    is_asset_category,
    register_extensions,
)
from ovui_data_adapters.services.content.clipboard import ContentClipboard
from ovui_data_adapters.services.content.file_operations import (
    ContentFileRecord,
    duplicate_items,
    next_copy_name,
)
from ovui_data_adapters.services.content.navigation import (
    BOOKMARKS_SETTINGS_KEY,
    SETTINGS_KEY,
    BookmarksManager,
    RecentFileList,
)

__all__ = [
    "AssetCategory",
    "AssetTypeDef",
    "BOOKMARKS_SETTINGS_KEY",
    "BookmarksManager",
    "ContentClipboard",
    "ContentFileRecord",
    "RecentFileList",
    "SETTINGS_KEY",
    "categories",
    "duplicate_items",
    "get_category",
    "get_display_name",
    "get_icon_url_key",
    "is_asset_category",
    "next_copy_name",
    "register_extensions",
]

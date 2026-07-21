# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Compatibility exports for content asset classification.

The canonical implementation lives in
``ovui_data_adapters.services.content.asset_types``. Icon assets and URL
registration remain in ovui_widgets.
"""

from ovui_data_adapters.services.content.asset_types import (
    _CATALOG,
    AssetCategory,
    AssetTypeDef,
    categories,
    get_category,
    get_display_name,
    get_icon_url_key,
    is_asset_category,
    register_extensions,
)

__all__ = [
    "AssetCategory",
    "AssetTypeDef",
    "categories",
    "get_category",
    "get_display_name",
    "get_icon_url_key",
    "is_asset_category",
    "register_extensions",
]

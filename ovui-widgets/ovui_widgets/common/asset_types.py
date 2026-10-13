# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

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

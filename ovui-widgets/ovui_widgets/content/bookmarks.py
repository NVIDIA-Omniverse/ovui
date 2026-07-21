# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Compatibility path for content bookmark persistence behavior.

The reusable manager now lives in
``ovui_data_adapters.services.content.navigation``. UI collection models,
context menus, buttons, and visual rows stay under ``ovui_widgets.content``.
"""

from ovui_data_adapters.services.content.navigation import (
    BOOKMARKS_SETTINGS_KEY,
    SETTINGS_KEY,
    BookmarksManager,
)

__all__ = ["BOOKMARKS_SETTINGS_KEY", "SETTINGS_KEY", "BookmarksManager"]

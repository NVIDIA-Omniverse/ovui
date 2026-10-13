# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

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

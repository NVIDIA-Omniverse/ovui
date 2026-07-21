# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Content Browser dockable window shell.

Houses :class:`ContentBrowserWindow` — the :class:`ManagedWindow`
that hosts the embeddable :class:`FileBrowserWidget`. See
the content browser behavior for the window-layer role and
the content browser implementation step 10 for the dockable shell.
"""

from ovui_widgets.content.window.content_browser_window import (
    ContentBrowserWindow,
)

__all__ = ["ContentBrowserWindow"]

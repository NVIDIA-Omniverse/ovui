# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

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

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Embeddable content-browser widget and its building blocks.

See the content browser behavior / §7 and the content browser implementation steps
6-33. This package hosts the pieces of the browser that can be
embedded in any window — the item/model/delegate/view — without the
window chrome (title, menus, splitters) which belongs to
``ovui_widgets.content.window`` in later steps.
"""

from ovui_widgets.content.widget.browser_bar import (
    BrowserBar,
    VisitedHistory,
)
from ovui_widgets.content.widget.collections import CollectionItem
from ovui_widgets.content.widget.column_delegate import (
    AbstractColumnDelegate,
    ColumnDelegateRegistry,
)
from ovui_widgets.content.widget.confirm_delete_dialog import (
    ConfirmDeleteDialog,
)
from ovui_widgets.content.widget.confirm_overwrite_dialog import (
    ConfirmOverwriteDialog,
    OverwriteChoice,
)
from ovui_widgets.content.widget.context_menu import FileContextMenu
from ovui_widgets.content.widget.drop_indicator import DropIndicator
from ovui_widgets.content.widget.file_bar import FileBar
from ovui_widgets.content.widget.file_browser_delegate import (
    FileBrowserDelegate,
    TreeFolderDelegate,
)
from ovui_widgets.content.widget.file_browser_model import (
    FileBrowserModel,
    FileBrowserSortPolicy,
)
from ovui_widgets.content.widget.file_browser_widget import (
    FileBrowserWidget,
)
from ovui_widgets.content.widget.file_card import FileCard
from ovui_widgets.content.widget.file_grid_view import FileGridView
from ovui_widgets.content.widget.file_item import FileItem
from ovui_widgets.content.widget.filter_button import FilterButton
from ovui_widgets.content.widget.highlight_label import HighlightLabel
from ovui_widgets.content.widget.navigation_model import (
    BookmarksCollection,
    MyComputerCollection,
    NavigationDelegate,
    NavigationModel,
    RecentFilesCollection,
)
from ovui_widgets.content.widget.options_menu import OptionsButton
from ovui_widgets.content.widget.path_field import PathField
from ovui_widgets.content.widget.rename_controller import RenameController
from ovui_widgets.content.widget.search_field import SearchField
from ovui_widgets.content.widget.simple_input_dialog import SimpleInputDialog
from ovui_widgets.content.widget.zoom_bar import SCALE_MAP, ZoomBar

# Compatibility alias: legacy code used ContentBrowserWidget as the primary
# widget class name.  Both names now resolve to the same class object.
ContentBrowserWidget = FileBrowserWidget

__all__ = [
    "AbstractColumnDelegate",
    "BookmarksCollection",
    "BrowserBar",
    "CollectionItem",
    "ColumnDelegateRegistry",
    "ConfirmDeleteDialog",
    "ConfirmOverwriteDialog",
    "ContentBrowserWidget",
    "DropIndicator",
    "FileBar",
    "FileBrowserDelegate",
    "FileBrowserModel",
    "FileBrowserSortPolicy",
    "FileBrowserWidget",
    "FileCard",
    "FileContextMenu",
    "FileGridView",
    "FileItem",
    "FilterButton",
    "HighlightLabel",
    "MyComputerCollection",
    "NavigationDelegate",
    "NavigationModel",
    "OptionsButton",
    "OverwriteChoice",
    "PathField",
    "RecentFilesCollection",
    "RenameController",
    "SCALE_MAP",
    "SearchField",
    "SimpleInputDialog",
    "TreeFolderDelegate",
    "VisitedHistory",
    "ZoomBar",
]

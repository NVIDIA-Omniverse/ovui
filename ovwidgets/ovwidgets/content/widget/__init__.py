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
``ovwidgets.content.window`` in later steps.
"""

from ovwidgets.content.widget.browser_bar import (
    BrowserBar,
    VisitedHistory,
)
from ovwidgets.content.widget.collections import CollectionItem
from ovwidgets.content.widget.column_delegate import (
    AbstractColumnDelegate,
    ColumnDelegateRegistry,
)
from ovwidgets.content.widget.confirm_delete_dialog import (
    ConfirmDeleteDialog,
)
from ovwidgets.content.widget.confirm_overwrite_dialog import (
    ConfirmOverwriteDialog,
    OverwriteChoice,
)
from ovwidgets.content.widget.context_menu import FileContextMenu
from ovwidgets.content.widget.drop_indicator import DropIndicator
from ovwidgets.content.widget.file_bar import FileBar
from ovwidgets.content.widget.file_browser_delegate import (
    FileBrowserDelegate,
    TreeFolderDelegate,
)
from ovwidgets.content.widget.file_browser_model import (
    FileBrowserModel,
    FileBrowserSortPolicy,
)
from ovwidgets.content.widget.file_browser_widget import (
    FileBrowserWidget,
)
from ovwidgets.content.widget.file_card import FileCard
from ovwidgets.content.widget.file_grid_view import FileGridView
from ovwidgets.content.widget.file_item import FileItem
from ovwidgets.content.widget.filter_button import FilterButton
from ovwidgets.content.widget.highlight_label import HighlightLabel
from ovwidgets.content.widget.navigation_model import (
    BookmarksCollection,
    MyComputerCollection,
    NavigationDelegate,
    NavigationModel,
    RecentFilesCollection,
)
from ovwidgets.content.widget.options_menu import OptionsButton
from ovwidgets.content.widget.path_field import PathField
from ovwidgets.content.widget.rename_controller import RenameController
from ovwidgets.content.widget.search_field import SearchField
from ovwidgets.content.widget.simple_input_dialog import SimpleInputDialog
from ovwidgets.content.widget.zoom_bar import SCALE_MAP, ZoomBar

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

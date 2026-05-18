# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovwidgets.content: URL-based file/asset browser peer widget package.

See the content browser behavior and the content browser implementation for the
step-by-step build-out. The package is organised after the Kit
``omni.kit.widget.filebrowser`` split:

- ``widget/`` — embeddable tree/grid widget plus its item/model/delegate.
- ``window/`` — dockable shell that wraps the widget.
- ``bookmarks.py`` — :class:`BookmarksManager` (Step 44) for the
  persisted ``name → url`` favourites surfaced by the nav pane's
  ``BookmarksCollection``.
"""

from ovwidgets.content.bookmarks import BookmarksManager
from ovwidgets.content.file_exporter import FileExporterHelper
from ovwidgets.content.file_importer import FileImporterHelper
from ovwidgets.content.file_picker_dialog import FilePickerDialog
from ovwidgets.content.window import ContentBrowserWindow

__all__ = [
    "BookmarksManager",
    "ContentBrowserWindow",
    "FileExporterHelper",
    "FileImporterHelper",
    "FilePickerDialog",
]

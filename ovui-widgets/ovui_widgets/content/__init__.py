# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovui_widgets.content: URL-based file/asset browser peer widget package.

See the content browser behavior and the content browser implementation for the
step-by-step build-out. The package is organised after the Kit
``omni.kit.widget.filebrowser`` split:

- ``widget/`` — embeddable tree/grid widget plus its item/model/delegate.
- ``window/`` — dockable shell that wraps the widget.
- ``bookmarks.py`` — :class:`BookmarksManager` (Step 44) for the
  persisted ``name → url`` favourites surfaced by the nav pane's
  ``BookmarksCollection``.
"""

from importlib import import_module

__all__ = [
    "BookmarksManager",
    "ContentBrowserWindow",
    "FileExporterHelper",
    "FileImporterHelper",
    "FilePickerDialog",
]

_LAZY_EXPORTS = {
    "BookmarksManager": ("ovui_widgets.content.bookmarks", "BookmarksManager"),
    "ContentBrowserWindow": ("ovui_widgets.content.window", "ContentBrowserWindow"),
    "FileExporterHelper": ("ovui_widgets.content.file_exporter", "FileExporterHelper"),
    "FileImporterHelper": ("ovui_widgets.content.file_importer", "FileImporterHelper"),
    "FilePickerDialog": ("ovui_widgets.content.file_picker_dialog", "FilePickerDialog"),
}


def __getattr__(name: str):
    """Load UI-heavy content exports only when callers request them."""
    try:
        module_name, attr_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value

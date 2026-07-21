# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Collection items for the content browser's left navigation pane.

the content browser behavior and the content browser implementation step 42. A collection
is a virtual root in the navigation tree — Bookmarks, My Computer,
Recent Files — whose children enumerate real URLs (drive mount points,
bookmarked folders, recently-opened files). The base :class:`CollectionItem`
is an abstract :class:`omni.ui.AbstractItem` that every concrete
collection subclasses; the navigation model (Step 42) assembles them
in display order and dispatches ``get_item_children`` through them.

* :class:`MyComputerCollection` — Step 43 (``collections/my_computer.py``).
* :class:`BookmarksCollection` — Step 44 (``collections/bookmarks.py``).
* :class:`RecentFilesCollection` — Step 46 (``collections/recent.py``).
"""

from ovui_widgets.content.widget.collections.base import CollectionItem
from ovui_widgets.content.widget.collections.bookmarks import (
    BookmarksCollection,
)
from ovui_widgets.content.widget.collections.my_computer import (
    MyComputerCollection,
)
from ovui_widgets.content.widget.collections.recent import (
    RecentFileItem,
    RecentFilesCollection,
)

__all__ = [
    "BookmarksCollection",
    "CollectionItem",
    "MyComputerCollection",
    "RecentFileItem",
    "RecentFilesCollection",
]

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""CollectionItem — abstract virtual-root node for the navigation pane.

See the content browser behavior and the content browser implementation step 42.

A collection is a virtual top-level entry in the navigation tree
(Bookmarks / My Computer / Recent / …) that enumerates its children
on demand. Unlike :class:`FileItem`, a :class:`CollectionItem` does
*not* correspond to a single backend URL — it is a logical group
whose :meth:`get_children` call returns real :class:`FileItem`
instances the user can click through into the detail pane.

Subclasses provide :meth:`get_children` and set ``identifier`` /
``title`` / ``icon_key`` at construction. :class:`NavigationModel`
treats every instance uniformly — it does not know about any
concrete subclass — so the plug-in surface for adding new
collections is "subclass + instantiate + hand to the model".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

import omni.ui as ui

if TYPE_CHECKING:
    from ovui_widgets.content.backends.backend_adapter import BackendAdapter
    from ovui_widgets.content.widget.file_item import FileItem


class CollectionItem(ui.AbstractItem):
    """Abstract virtual-root node for the navigation tree.

    A :class:`CollectionItem` is expandable (``is_folder = True``) and
    renders via a single Name column in the nav pane. Its children —
    produced by :meth:`get_children` — are :class:`FileItem` instances
    pointing at real backend URLs (drive roots, bookmarked folders,
    recent-file paths). Clicking a :class:`CollectionItem` root in the
    nav tree is a no-op for navigation; clicking one of its
    :class:`FileItem` children re-roots the detail pane at that URL.

    Fields:

    * ``identifier`` — stable string key (``"bookmarks"``, ``"my-computer"``,
      ``"recent"``). Used by the architecture-§13.1 scheme-dispatch table
      in later steps so a typed URL can be routed to the right collection.
    * ``title`` — user-visible display name ("Bookmarks", "My Computer",
      …). The nav pane renders this through the delegate's Name column.
    * ``icon_key`` — ``ovui_widgets.common.style.urls`` key for the collection's 16×16
      icon. Mirrors :attr:`FileItem.icon_key` so the nav-pane delegate
      can look up the icon path the same way it does for files.

    Subclasses supply all three at construction and override
    :meth:`get_children` to enumerate the real URLs behind the collection.
    """

    def __init__(
        self,
        identifier: str,
        title: str,
        icon_key: str,
    ) -> None:
        super().__init__()
        self._identifier = identifier
        self._title = title
        self._icon_key = icon_key
        self._name_model: Optional[ui.SimpleStringModel] = None

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def identifier(self) -> str:
        """Stable string key for this collection (``"bookmarks"``, …)."""
        return self._identifier

    @property
    def title(self) -> str:
        """User-visible display name ("Bookmarks", "My Computer", …)."""
        return self._title

    @property
    def icon_key(self) -> str:
        """``ovui_widgets.common.style.urls`` key for the collection's nav-pane icon."""
        return self._icon_key

    @property
    def name(self) -> str:
        """Alias for :attr:`title` so the nav-pane delegate can treat
        collection roots and :class:`FileItem` children uniformly — both
        expose a ``name`` that the Name column reads.
        """
        return self._title

    @property
    def is_folder(self) -> bool:
        """Collections are always expandable."""
        return True

    # ── Value model (for the TreeView's Name column) ─────────────────────────

    def get_name_model(self) -> ui.SimpleStringModel:
        """Return (and cache) a :class:`ui.SimpleStringModel` of :attr:`title`.

        Mirrors :meth:`FileItem.get_name_model` so the navigation-pane
        delegate can call either shape through the same accessor when it
        needs an ``ui.AbstractValueModel`` for the Name column's label.
        """
        if self._name_model is None:
            self._name_model = ui.SimpleStringModel(self._title)
        return self._name_model

    # ── Children — subclass hook ──────────────────────────────────────────────

    def get_children(
        self, backend: "BackendAdapter",
    ) -> List["FileItem"]:
        """Enumerate the :class:`FileItem` children of this collection.

        Subclasses MUST override. The navigation model calls this on
        every ``get_item_children`` dispatch for the collection; the
        call is expected to be cheap enough to run on-demand (a dict
        lookup against a bookmarks manager, a ``/proc/mounts`` parse,
        etc.). The default implementation returns ``[]`` so a stub
        subclass that has not yet been fleshed out renders as an empty
        (but present) nav-tree root — the user sees the collection
        header with no children rather than a rendering error.

        The returned list's order is honoured by the navigation model —
        no secondary sort is applied. Subclasses that want a specific
        display order (alphabetical bookmarks, most-recent-first recent
        files) sort the list themselves before returning.
        """
        return []

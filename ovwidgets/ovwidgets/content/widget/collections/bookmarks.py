# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""BookmarksCollection — navigation-pane "Bookmarks" root.

See the content browser behavior (bookmark collection) and
the content browser implementation step 44. Subscribes to a :class:`BookmarksManager` and
renders one :class:`FileItem` child per persisted bookmark; changes
to the manager (``add`` / ``remove`` / ``rename``) invalidate the
cached children and fire an ``on_changed`` hook so the hosting
:class:`NavigationModel` can emit ``_item_changed`` and repaint the
nav TreeView.

The caching + change hook shape mirrors
:class:`MyComputerCollection` — see its module docstring for the
rationale behind holding Python references to the children
(``omni.ui.TreeView`` stores items by raw C++ pointer via pybind11,
and fresh :class:`FileItem` instances per :meth:`get_children` call
lose their Python-subclass identity on the delegate-callback
round-trip).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, List, Optional

from ovwidgets.content.backends.backend_adapter import BackendFileFlags, BackendResult
from ovwidgets.content.widget.collections.base import CollectionItem
from ovwidgets.content.widget.file_item import FileItem

if TYPE_CHECKING:
    from ovwidgets.common.settings import Subscription
    from ovwidgets.content.backends.backend_adapter import BackendAdapter
    from ovwidgets.content.bookmarks import BookmarksManager


class BookmarksCollection(CollectionItem):
    """Navigation-pane virtual root for persisted folder bookmarks.

    Constructor accepts an optional :class:`BookmarksManager` — the
    navigation model wires one in when the hosting application's
    :class:`Settings` is available, and leaves it ``None`` when it is
    not (bare :class:`NavigationModel` construction in unit tests). A
    ``None`` manager renders an empty collection root; attached, the
    children are one :class:`FileItem` per entry in the manager's
    mapping.

    Change propagation:

    1. The user / code calls :meth:`BookmarksManager.add` /
       :meth:`~BookmarksManager.remove` / :meth:`~BookmarksManager.rename`.
    2. The manager writes to :class:`Settings`; subscribers fire.
    3. This collection's subscription drops the cached children and
       fires :attr:`_on_changed` so the owning
       :class:`NavigationModel` can emit ``_item_changed`` on the
       collection — which triggers the TreeView to re-query
       ``get_item_children`` and render the updated list.
    """

    def __init__(
        self, manager: Optional["BookmarksManager"] = None,
    ) -> None:
        super().__init__(
            identifier="bookmarks",
            title="Bookmarks",
            icon_key="content_bookmark",
        )
        self._manager = manager
        # Cached children. ``None`` means "not yet enumerated" — the
        # next :meth:`get_children` call will ask the manager and
        # build the list. Dropped by :meth:`refresh` / by the
        # manager's change-notification wire-up below so a mutation
        # propagates through the render.
        self._children_cache: Optional[List[FileItem]] = None
        # Hook installed by :class:`NavigationModel` so the model can
        # emit its protected :meth:`_item_changed` without the
        # collection reaching into the model directly.
        self._on_changed: Optional[Callable[[], None]] = None
        # Held as an instance attribute so the RAII subscription
        # stays alive for the lifetime of the collection; a local
        # variable would be garbage-collected and the callback would
        # stop firing immediately.
        self._subscription: Optional["Subscription"] = None
        if manager is not None:
            self._subscription = manager.subscribe_changed(
                self._handle_manager_changed,
            )

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def manager(self) -> Optional["BookmarksManager"]:
        """The attached :class:`BookmarksManager`, or ``None`` if none."""
        return self._manager

    def get_children(
        self, backend: "BackendAdapter",
    ) -> List[FileItem]:
        """Return the cached :class:`FileItem` children — one per bookmark.

        Cached on the collection instance so the nav-pane render path
        holds a stable set of Python-subclass references (see the
        module docstring for the pybind11 / TreeView constraint).
        A manager mutation drops the cache via
        :meth:`_handle_manager_changed`; an explicit caller can drop
        it via :meth:`refresh`.
        """
        if self._children_cache is None:
            self._children_cache = self._enumerate(backend)
        return self._children_cache

    def refresh(self) -> None:
        """Invalidate the cached children so the next :meth:`get_children`
        call re-enumerates from the manager.

        Exposed so the hosting widget can force a rebuild without a
        manager mutation — e.g. after the backend changes and the
        existing bookmark URLs need to be re-statted against the new
        backend's notion of "is folder".
        """
        self._children_cache = None

    def set_on_changed(
        self, callback: Optional[Callable[[], None]],
    ) -> None:
        """Register ``callback`` to fire after a manager mutation.

        :class:`NavigationModel` installs a callback that invokes its
        own protected :meth:`_item_changed` so the nav TreeView
        re-queries this collection's children. ``None`` clears the
        hook — used when the model tears down.
        """
        self._on_changed = callback

    # ── Internals ────────────────────────────────────────────────────────────

    def _handle_manager_changed(self) -> None:
        """Invalidate the children cache and fan out ``on_changed``.

        Bound into the manager's subscription list at construction.
        Drops the cache first so anyone who reads :meth:`get_children`
        from inside the ``on_changed`` callback sees the updated
        children rather than the pre-mutation snapshot.
        """
        self._children_cache = None
        if self._on_changed is not None:
            self._on_changed()

    def _enumerate(self, backend: "BackendAdapter") -> List[FileItem]:
        """Build one :class:`FileItem` per bookmark in display order.

        Each URL is ``stat``-ed against the backend so the
        ``is_folder`` flag on the resulting :class:`FileItem` matches
        reality — a bookmark pointing at a file (rare in v1; Step 45's
        "Add Bookmark" only surfaces on folders, but nothing in the
        manager API prevents a non-folder URL) renders with the file
        glyph rather than the folder glyph. Stat failures default to
        ``is_folder=True`` so an unreachable / renamed target still
        shows up in the nav pane and the user can remove the stale
        entry through a future context-menu action rather than the
        bookmark silently disappearing.
        """
        if self._manager is None:
            return []
        items: List[FileItem] = []
        for name, url in self._manager.list().items():
            is_folder = self._is_folder(backend, url)
            items.append(FileItem(url=url, name=name, is_folder=is_folder))
        return items

    @staticmethod
    def _is_folder(backend: "BackendAdapter", url: str) -> bool:
        """Return ``True`` if ``url`` resolves to a folder in ``backend``.

        Falls back to ``True`` when the backend can't stat the URL —
        an unreachable bookmark renders as a (potentially stale)
        folder entry so the user still sees it in the nav pane.
        """
        result, entry = backend.stat(url)
        if result is not BackendResult.OK or entry is None:
            return True
        return bool(entry.flags & BackendFileFlags.IS_FOLDER)

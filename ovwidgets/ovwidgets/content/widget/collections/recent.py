# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""RecentFilesCollection — navigation-pane "Recent" root.

See the content browser behavior (file-event-history layer) and
the content browser implementation step 46. Subscribes to :class:`Settings` for the
``ui.recent_files`` key and renders one child per recently-opened
file, most-recent-first.

The source of truth for the ordered list is
:class:`ovwidgets.common.recent_files.RecentFileList`; the owning
:class:`ovwidgets.app.application.Application` writes to it on every
:meth:`~ovwidgets.app.application.Application.open_file` call and persists
the snapshot through :class:`Settings`. This collection holds the
same :class:`RecentFileList` reference when available — so an
in-process write shows up immediately — and subscribes to
:class:`Settings` so an out-of-process write (settings file reloaded
mid-session, a future "clear recent files" action that only writes
the key) still repaints the nav pane.

Non-existent entries (``backend.stat(url) != OK``) are still rendered
as children — the user can see them and, in a future step, remove
them via a context menu — but are flagged via
:attr:`RecentFileItem.is_missing` so the navigation delegate paints
them with the ``Content.Row.Name::missing`` style (grey, matching the
``::disabled`` variant — ovui has no italic font face so the "grey +
italic" spec degrades to "grey only").
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Callable, List, Optional

from ovwidgets.content.backends.backend_adapter import BackendResult
from ovwidgets.content.widget.collections.base import CollectionItem
from ovwidgets.content.widget.file_item import FileItem

if TYPE_CHECKING:
    from ovwidgets.common.recent_files import RecentFileList
    from ovwidgets.common.settings import Settings, Subscription
    from ovwidgets.content.backends.backend_adapter import BackendAdapter


# The :class:`Settings` key that persists the recent-file list. The
# :class:`ovwidgets.app.application.Application` writes to this key on every
# ``open_file`` call and the key is where persistence round-trips
# through :class:`ovwidgets.common.settings.Settings._load_from_disk`. Match
# :meth:`Application.open_file` exactly.
_SETTINGS_KEY = "ui.recent_files"


class RecentFileItem(FileItem):
    """A :class:`FileItem` that remembers whether its backend URL
    currently resolves.

    ``is_missing`` is ``True`` when :meth:`BackendAdapter.stat`
    returned a non-OK result at enumeration time — the file has been
    renamed, moved, or the backing storage is offline. The navigation
    delegate keys the row's name style on this flag (greyed-out) so
    stale entries read visually distinct from live ones without being
    silently dropped (the user may still want to remove them).

    Everything else behaves exactly like :class:`FileItem` — the
    subclass adds a property and nothing else. The existing delegate
    render path treats :class:`RecentFileItem` identically to
    :class:`FileItem` through ``isinstance`` checks; only the
    ``getattr(item, "is_missing", False)`` probe in the Name column
    is aware of the extra state.
    """

    def __init__(
        self,
        url: str,
        name: str,
        is_folder: bool = False,
        is_missing: bool = False,
    ) -> None:
        super().__init__(url=url, name=name, is_folder=is_folder)
        self._is_missing = bool(is_missing)

    @property
    def is_missing(self) -> bool:
        """``True`` when the backend cannot stat this item's URL."""
        return self._is_missing


class RecentFilesCollection(CollectionItem):
    """Navigation-pane virtual root for recently-opened files.

    Child enumeration order matches
    :meth:`ovwidgets.common.recent_files.RecentFileList.get_ordered` — most
    recently opened first. Cached on the collection instance so the
    TreeView's pybind11 -> ``ui.AbstractItem`` boundary preserves
    :class:`RecentFileItem` identity (see the
    :class:`ovwidgets.content.widget.collections.my_computer.MyComputerCollection`
    docstring for the pointer-identity constraint).

    Change propagation mirrors
    :class:`ovwidgets.content.widget.collections.bookmarks.BookmarksCollection`:

    1. :meth:`Application.open_file` (or any caller) writes the new
       list via :meth:`Settings.set`.
    2. :class:`Settings` fans the key change out to subscribers.
    3. This collection's subscription drops the cached children and
       invokes :attr:`_on_changed` so the owning
       :class:`NavigationModel` emits ``_item_changed`` on the
       collection — triggering TreeView re-query + repaint.
    """

    def __init__(
        self,
        recent_files: Optional["RecentFileList"] = None,
        settings: Optional["Settings"] = None,
    ) -> None:
        super().__init__(
            identifier="recent",
            title="Recent",
            # ovui's :class:`RasterImageProvider` uses stb_image which
            # cannot decode SVG, so the icon key must resolve to a PNG.
            # ``asset_archive`` reads as a "history / stack of items"
            # glyph — the closest match in the current style set until
            # a dedicated clock / recent icon ships.
            icon_key="asset_archive",
        )
        self._recent_files = recent_files
        self._settings = settings
        # Cached children — ``None`` means "not yet enumerated". Drop
        # via :meth:`refresh` or through the settings-change fan-out.
        # Hard Python reference so TreeView's pybind11 binding retains
        # the :class:`RecentFileItem` subclass identity across
        # delegate-callback round-trips.
        self._children_cache: Optional[List[FileItem]] = None
        # Hook installed by :class:`NavigationModel` so a mutation
        # emits :meth:`_item_changed` on the collection root without
        # the collection reaching back into the model directly.
        self._on_changed: Optional[Callable[[], None]] = None
        # RAII-held :class:`Subscription` — a local would be GC'd and
        # the callback would stop firing. ``None`` when no
        # :class:`Settings` was supplied.
        self._subscription: Optional["Subscription"] = None
        if settings is not None:
            self._subscription = settings.subscribe(
                _SETTINGS_KEY, self._handle_settings_changed,
            )

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def recent_files(self) -> Optional["RecentFileList"]:
        """The attached :class:`RecentFileList`, or ``None`` if none."""
        return self._recent_files

    @property
    def settings(self) -> Optional["Settings"]:
        """The attached :class:`Settings`, or ``None`` if none."""
        return self._settings

    def get_children(
        self, backend: "BackendAdapter",
    ) -> List[FileItem]:
        if self._children_cache is None:
            self._children_cache = self._enumerate(backend)
        return self._children_cache

    def refresh(self) -> None:
        """Invalidate the cached children so the next
        :meth:`get_children` re-enumerates from the current source.

        Useful when the backend changes (LocalFSBackend → NucleusBackend)
        and the existing ``is_missing`` flags need to be re-statted
        against the new backend's view of the filesystem.
        """
        self._children_cache = None

    def set_on_changed(
        self, callback: Optional[Callable[[], None]],
    ) -> None:
        """Register ``callback`` to fire on every recent-files change.

        :class:`NavigationModel` installs a callback that invokes its
        own protected :meth:`_item_changed`. ``None`` clears the hook
        (on model teardown).
        """
        self._on_changed = callback

    # ── Internals ────────────────────────────────────────────────────────────

    def _handle_settings_changed(self, key: str, value: object) -> None:
        """Drop the children cache and fan ``on_changed`` out.

        Bound into :meth:`Settings.subscribe` at construction. Cache
        is dropped first so a handler that reads :meth:`get_children`
        from inside ``on_changed`` sees the post-mutation snapshot
        (mirrors :class:`BookmarksCollection._handle_manager_changed`).
        """
        self._children_cache = None
        if self._on_changed is not None:
            self._on_changed()

    def _ordered_paths(self) -> List[str]:
        """Return the recent-file paths, most-recent-first.

        Prefers the in-memory :class:`RecentFileList` when present —
        :meth:`Application.open_file` writes to that first and to
        :class:`Settings` second, so reading from the list picks up
        the newest addition without waiting for the settings fan-out.
        Falls back to :meth:`Settings.get` when no :class:`RecentFileList`
        was supplied (e.g. a test harness wiring only :class:`Settings`).
        Returns ``[]`` when neither source is available.
        """
        if self._recent_files is not None:
            return list(self._recent_files.get_ordered())
        if self._settings is not None:
            return list(self._settings.get(_SETTINGS_KEY, []) or [])
        return []

    def _enumerate(self, backend: "BackendAdapter") -> List[FileItem]:
        """Build one :class:`RecentFileItem` per recent-files entry.

        Each path is ``stat``-ed against the backend: a non-OK result
        marks the item ``is_missing=True``. ``is_folder`` is always
        ``False`` for recent files — the recent-files list only
        records files that went through :meth:`Application.open_file`
        (the content browser behavior). The display name is the
        path's basename so a row reads as the file's leaf rather than
        the full path.
        """
        items: List[FileItem] = []
        for path in self._ordered_paths():
            if not path:
                continue
            url = path
            name = os.path.basename(path) or path
            result, _entry = backend.stat(url)
            is_missing = result is not BackendResult.OK
            items.append(
                RecentFileItem(
                    url=url,
                    name=name,
                    is_folder=False,
                    is_missing=is_missing,
                ),
            )
        return items

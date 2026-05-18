# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""FileItem — lazy item cache node for the content browser.

See the content browser behavior (Item Layer) / §5.1 (cache
membership) and the content browser implementation step 6. ``FileItem`` is the counterpart
of Kit's ``FileBrowserItem``: a single cached node in a lazy tree that
the model (Step 7) assembles into an ``omni.ui.AbstractItemModel``.

One instance represents one backend URL — folder or leaf. It holds
everything a view needs to render a row: name, size, modified time,
icon URL key, asset category, and — for folders — the cached
children. Everything UI-facing is allocated lazily: the
``SimpleStringModel`` instances that power the three built-in columns
(name / size / date) are created on first request, not on construction,
so items that never render a given column never pay for its value
model.

``populate`` is **synchronous**. The model layer is responsible for
running it off a timer / thread / async coroutine if/when that's
desired. Keeping it sync makes ``FileItem`` trivially testable without
spinning up a :class:`ovwidgets.app.application.Application` event loop, and
matches the design in the content browser implementation step 6 where async dispatch lives
one level up.

Thread safety:
- Folders carry a ``threading.Lock``. Leaves carry a :class:`_NoLock`
  (no-op context manager) — they never mutate children, so the lock is
  pure overhead there.
- ``add_child`` / ``remove_child`` / ``populate`` / ``children`` take
  the lock on folders. ``remove_child`` uses ``dict.pop`` rather than
  ``del`` so an iterator that holds a reference to the popped item
  does not break (see the content browser behavior OM-34661).
"""

from __future__ import annotations

import datetime
import threading
from collections import OrderedDict
from typing import Callable, ContextManager, Dict, List, Optional

import omni.ui as ui

from ovwidgets.common.asset_types import AssetCategory, get_category
from ovwidgets.content.backends.backend_adapter import (
    BackendAdapter,
    BackendFileFlags,
    BackendListEntry,
    BackendResult,
)

# ──────────────────────────────────────────────────────────────────────────────
# No-op lock for leaf items
# ──────────────────────────────────────────────────────────────────────────────

class _NoLock:
    """Context manager with the :class:`threading.Lock` surface but no cost.

    Leaf ``FileItem`` instances never mutate a children dict, so a real
    lock would be pure overhead. The architecture (§4.2) nonetheless
    keeps ``add_child`` / ``remove_child`` / ``children`` under a mutex
    so the folder-vs-leaf branch is invisible to callers — the
    lock-or-no-lock contract is decided once at construction and the
    call sites look identical afterwards.
    """

    def __enter__(self) -> "_NoLock":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Formatters (pure — no FileItem state)
# ──────────────────────────────────────────────────────────────────────────────

_SIZE_UNITS = (
    (1024 ** 3, "GB"),
    (1024 ** 2, "MB"),
    (1024,      "KB"),
)


def _format_size(bytes_: int) -> str:
    """Return a 1024-based human-readable size string.

    Matches the content browser behavior ("1024-based GB/MB/KB, not
    decimal MB") and Kit's ``FileBrowserItem.size_as_string``. Values
    below 1 KiB render as a bare byte count with a "B" suffix.
    """
    value = int(bytes_)
    if value < 0:
        value = 0
    for threshold, suffix in _SIZE_UNITS:
        if value >= threshold:
            return f"{value / threshold:.1f} {suffix}"
    return f"{value} B"


def _format_date(unix_ts: float) -> str:
    """Format a Unix timestamp as ``YYYY-MM-DD HH:MM`` in local time.

    Empty / zero timestamps render as an empty string so the date
    column does not advertise a meaningless "1970-01-01" for freshly
    constructed items whose metadata has not been filled in yet.
    """
    if not unix_ts:
        return ""
    return datetime.datetime.fromtimestamp(unix_ts).strftime("%Y-%m-%d %H:%M")


# ──────────────────────────────────────────────────────────────────────────────
# FileItem
# ──────────────────────────────────────────────────────────────────────────────

# Mapping from asset category → icon URL key for non-folder items. Only
# categories that can appear on a leaf are listed here; folders are
# handled separately in the constructor because the backend's
# ``IS_FOLDER`` flag is authoritative for them — not the extension.
# :class:`AssetCategory.UNKNOWN` is the fallback and does not need an
# entry (``dict.get(..., "asset_unknown")`` covers it).
_LEAF_ICON_KEY_BY_CATEGORY: Dict[AssetCategory, str] = {
    AssetCategory.USD:      "asset_usd",
    AssetCategory.IMAGE:    "asset_image",
    AssetCategory.MATERIAL: "asset_material",
    AssetCategory.MODEL:    "asset_model",
    AssetCategory.SOUND:    "asset_sound",
    AssetCategory.SCRIPT:   "asset_script",
    AssetCategory.VOLUME:   "asset_volume",
    AssetCategory.TEXT:     "asset_text",
    AssetCategory.ARCHIVE:  "asset_archive",
}


class FileItem(ui.AbstractItem):
    """One cached node in the content-browser tree.

    Constructed by the model layer (Step 7) on first observation of a
    URL; subsequently reused across populates. The set of mutable
    fields is intentionally narrow — ``_size`` and ``_modified`` track
    metadata that can drift across populates; everything else
    (``_url``, ``_name``, ``_is_folder``, ``_icon_key``, ``_category``)
    is fixed at construction. Reassignment there would imply the item
    has moved or changed type, which the model handles by dropping the
    item and creating a replacement rather than mutating in place.

    The ``_populated`` flag is the state machine for lazy children. It
    starts ``False``, flips to ``True`` when :meth:`populate` succeeds,
    and is reset by :meth:`mark_dirty` so the next
    ``get_item_children`` call repopulates from the backend.
    """

    def __init__(
        self,
        url: str,
        name: str,
        is_folder: bool,
        size: int = 0,
        modified: float = 0.0,
        parent: Optional["FileItem"] = None,
    ) -> None:
        super().__init__()
        self._url = url
        self._name = name
        self._is_folder = is_folder
        self._size = size
        self._modified = modified
        self._parent = parent
        self._children: "OrderedDict[str, FileItem]" = OrderedDict()
        self._populated = False

        if is_folder:
            self._icon_key = "asset_folder"
            self._category = AssetCategory.FOLDER
        else:
            self._category = get_category(name)
            self._icon_key = _LEAF_ICON_KEY_BY_CATEGORY.get(
                self._category, "asset_unknown",
            )

        # Lazy SimpleStringModel slots — allocated on the first
        # ``get_*_model`` call by a column delegate. Items that never
        # render a given column never pay for its model.
        self._name_model: Optional[ui.SimpleStringModel] = None
        self._size_model: Optional[ui.SimpleStringModel] = None
        self._date_model: Optional[ui.SimpleStringModel] = None

        # Step 25: custom thumbnail URL (populated by
        # :meth:`FileBrowserModel._populate_thumbnails`) and an optional
        # one-argumentless callback the model / card can set to react to
        # the URL becoming available without re-querying the item.
        # ``None`` means "no thumbnail discovered" — the card falls back
        # to the default icon for the item's ``icon_key``.
        self._custom_thumbnail: Optional[str] = None
        self._on_thumbnail_changed: Optional[Callable[[], None]] = None

        # Only folders need a real lock — leaves never mutate children.
        # Annotated as :class:`ContextManager` because the code only
        # uses the ``__enter__`` / ``__exit__`` surface; the full
        # ``Lock`` API (``acquire`` / ``release`` / ``locked``) would
        # unnecessarily rule out :class:`_NoLock` at type-check time.
        self._mutex: ContextManager[object] = (
            threading.Lock() if is_folder else _NoLock()
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def url(self) -> str:
        return self._url

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_folder(self) -> bool:
        return self._is_folder

    @property
    def size(self) -> int:
        return self._size

    @property
    def modified(self) -> float:
        return self._modified

    @property
    def parent(self) -> Optional["FileItem"]:
        return self._parent

    @property
    def icon_key(self) -> str:
        return self._icon_key

    @property
    def category(self) -> AssetCategory:
        return self._category

    @property
    def populated(self) -> bool:
        return self._populated

    @property
    def custom_thumbnail(self) -> Optional[str]:
        """URL of a custom thumbnail discovered for this item, or ``None``.

        Step 25 (``.thumbs/256x256/<name>.png`` discovery — see
        the content browser behavior). Set by
        :meth:`FileBrowserModel._populate_thumbnails` after a parent's
        children are materialised; consumed by :class:`FileCard`'s front
        buffer when the card builds. ``None`` is the "no thumbnail" state
        — the card stays on the default icon.
        """
        return self._custom_thumbnail

    @property
    def children(self) -> List["FileItem"]:
        """Snapshot the child dict under the item's mutex.

        Returns a fresh ``list`` so iterators the caller builds from
        the snapshot are not invalidated by a concurrent populate. The
        returned order is the underlying ``OrderedDict``'s insertion
        order: surviving children keep their slot across repopulates,
        and new children append at the end. Callers that need a
        specific sort (by name / size / date) should reorder the
        snapshot themselves — the item itself does not sort.
        """
        with self._mutex:
            return list(self._children.values())

    # ── Lazy value models ─────────────────────────────────────────────────────

    def get_name_model(self) -> ui.SimpleStringModel:
        """Return (and cache) the name column's value model."""
        if self._name_model is None:
            self._name_model = ui.SimpleStringModel(self._name)
        return self._name_model

    def get_size_model(self) -> ui.SimpleStringModel:
        """Return (and cache) the size column's value model.

        Folders render an empty string rather than "0 B" so the size
        column stays empty for containers, matching Kit
        ``FileBrowserItem`` behaviour.
        """
        if self._size_model is None:
            value = "" if self._is_folder else _format_size(self._size)
            self._size_model = ui.SimpleStringModel(value)
        return self._size_model

    def get_date_model(self) -> ui.SimpleStringModel:
        """Return (and cache) the date column's value model."""
        if self._date_model is None:
            self._date_model = ui.SimpleStringModel(_format_date(self._modified))
        return self._date_model

    # ── Mutation (model-owned — callers go through the model in Step 7) ──────

    def add_child(self, item: "FileItem") -> None:
        """Insert ``item`` under this folder, overwriting any name collision.

        The parent back-reference is rewritten so the child's
        ``parent`` property stays consistent if it was constructed
        parent-less. ``OrderedDict`` overwrite preserves the key's
        original position when the name already existed.
        """
        with self._mutex:
            self._children[item.name] = item
            item._parent = self

    def remove_child(self, name: str) -> Optional["FileItem"]:
        """Detach the named child.

        Uses ``dict.pop`` rather than ``del`` specifically so an
        iterator that still holds a reference to the returned item
        does not raise ``RuntimeError: dictionary changed size during
        iteration``. See the content browser behavior (OM-34661).
        Returns the removed item, or ``None`` if it was not present.
        """
        with self._mutex:
            return self._children.pop(name, None)

    def update_metadata(self, entry: BackendListEntry) -> None:
        """Apply a fresh :class:`BackendListEntry` to this item.

        Mutates ``_size`` / ``_modified`` and, when their value models
        have already been created, pushes new strings into them so any
        widget bound to those models repaints. The name is not
        rewritten from the entry — a rename implies a different URL,
        and the model handles renames by creating a replacement item
        rather than mutating this one in place. (The the content browser implementation step 6 sketch includes a ``_name_model.set_value`` call at
        this point; it is intentionally omitted here for the same
        reason.)
        """
        self._size = entry.size
        self._modified = entry.modified_time
        if self._size_model is not None:
            value = "" if self._is_folder else _format_size(entry.size)
            self._size_model.set_value(value)
        if self._date_model is not None:
            self._date_model.set_value(_format_date(entry.modified_time))

    def set_custom_thumbnail(self, url: Optional[str]) -> None:
        """Attach a custom-thumbnail URL and fire the changed callback.

        ``url`` may be a non-empty string (thumbnail URL — typically
        ``<parent>/.thumbs/256x256/<name>.png`` or its ``.auto.png``
        fallback) or ``None`` to clear. Setting the same value twice is
        a cheap no-op on the storage side but still fires
        ``_on_thumbnail_changed`` — the callback may want to know the
        discovery pass ran even if nothing changed.

        See the content browser behavior (manual vs auto fallback)
        and the content browser implementation step 25 (thumbnail discovery). The callback
        is ``None`` by default; a model or card that wants per-item
        change notifications assigns to ``_on_thumbnail_changed``
        directly. The model's aggregate
        :meth:`FileBrowserModel._schedule_item_changed` dispatch is
        the primary refresh path — the per-item callback is a hook for
        future, more targeted refreshes (e.g. a card updating itself
        without a full grid rebuild).
        """
        self._custom_thumbnail = url
        fn = self._on_thumbnail_changed
        if fn is not None:
            fn()

    def mark_dirty(self) -> None:
        """Flag the cache stale so the next :meth:`populate` re-runs.

        The model layer calls this when it learns the backend's view
        of the folder has drifted (explicit refresh, change event, or
        bookmarked-folder restore). The in-memory children dict is
        untouched — the next populate diffs against it so stable items
        retain their expansion state.
        """
        self._populated = False

    def populate(self, backend: BackendAdapter) -> BackendResult:
        """Synchronously populate this folder's children from ``backend``.

        Calls :meth:`BackendAdapter.list_dir`, then reconciles the
        returned listing against the current ``_children`` dict:

        - Existing children whose name is still present get
          :meth:`update_metadata` (so the existing ``FileItem``
          object, its expansion state, and any live references are
          preserved).
        - Names absent from the new listing are removed via
          :meth:`remove_child`.
        - New names get a fresh :class:`FileItem` added via
          :meth:`add_child`.

        FileItem refresh state machine:

        - **Non-folder** items return :attr:`BackendResult.ERROR`
          without contacting the backend — they have no children.
        - **Already populated** folders return
          :attr:`BackendResult.OK` without contacting the backend. A
          refresh must be requested by first calling
          :meth:`mark_dirty`; this keeps the method safe to call from
          the model's "ensure populated" pathway on every
          ``get_item_children`` without repeated backend traffic.
        - **Backend error** propagates unchanged and leaves
          ``_populated`` ``False`` so a retry goes through.
        - **Backend OK** sets ``_populated = True`` after reconciling.

        The list_dir call is deliberately outside the reconcile mutex:
        the plan treats the lock as defensive insurance for a future
        threading extension, not as a barrier that should block while
        a remote backend stalls. Holding it across a potentially slow
        ``list_dir`` would make every ``children`` read wait for that
        round-trip. The model layer is single-threaded (Step 7)
        irrespective of this choice.
        """
        if not self._is_folder:
            return BackendResult.ERROR

        if self._populated:
            return BackendResult.OK

        result, entries = backend.list_dir(self._url)
        if result is not BackendResult.OK:
            return result

        new_names = {entry.name for entry in entries}

        # Reconcile under the mutex so concurrent iterators see a
        # consistent snapshot. Mutation is a three-phase diff: update
        # survivors, delete gones, add news. Add/update is O(N) over
        # the listing; delete is O(M) over the existing children but
        # only iterates names actually due for removal.
        with self._mutex:
            stale = [n for n in self._children if n not in new_names]
            for name in stale:
                self._children.pop(name, None)

            for entry in entries:
                existing = self._children.get(entry.name)
                if existing is not None:
                    existing.update_metadata(entry)
                    continue
                is_folder = bool(entry.flags & BackendFileFlags.IS_FOLDER)
                child_url = backend.join_url(self._url, entry.name)
                child = FileItem(
                    url=child_url,
                    name=entry.name,
                    is_folder=is_folder,
                    size=entry.size,
                    modified=entry.modified_time,
                    parent=self,
                )
                self._children[entry.name] = child

        self._populated = True
        return BackendResult.OK

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Frontend-neutral content navigation and persistence state.

This module owns the reusable behavior behind recent-file ordering and
bookmark persistence. Content browser widgets, tree collections, context
menus, bookmark buttons, missing-file row decoration, and application
singleton policy stay with the frontend that renders them.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from ovui_data_adapters.services.settings import Settings, Subscription


BOOKMARKS_SETTINGS_KEY = "ui.content.bookmarks"
SETTINGS_KEY = BOOKMARKS_SETTINGS_KEY


class RecentFileList:
    """Ordered list of recently opened file paths, capped at ``MAX`` entries.

    Call :meth:`add` after each successful open. The caller owns persistence
    into a settings store and any application-wide singleton policy.
    """

    MAX = 10

    def __init__(self, initial: Optional[List[str]] = None) -> None:
        self._items: deque[str] = deque(initial or [], maxlen=self.MAX)

    def add(self, path: str) -> None:
        """Add ``path`` to the top, promoting an existing entry if present."""
        if path in self._items:
            self._items.remove(path)
        self._items.appendleft(path)

    def get_ordered(self) -> List[str]:
        """Return paths most-recently-opened first."""
        return list(self._items)


class BookmarksManager:
    """Persistent folder-bookmark store backed by :class:`Settings`.

    The manager is intentionally UI-free: no widget imports, no file item
    construction, and no app singleton lookup. It stores a ``name -> url``
    mapping under :data:`SETTINGS_KEY` and exposes zero-argument change
    subscriptions so a frontend can refresh itself from :meth:`list`.
    """

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings
        stored = settings.get(SETTINGS_KEY, {}) or {}
        self._entries: Dict[str, str] = dict(stored)

    def add(self, name: str, url: str) -> None:
        """Add or overwrite the bookmark named ``name`` to point at ``url``."""
        if self._entries.get(name) == url:
            return
        self._entries[name] = url
        self._persist()

    def remove(self, name: str) -> None:
        """Remove ``name`` if it exists."""
        if name not in self._entries:
            return
        del self._entries[name]
        self._persist()

    def rename(self, old: str, new: str) -> None:
        """Rename bookmark ``old`` to ``new``, preserving its URL."""
        if old not in self._entries:
            return
        if new == old:
            return
        if new in self._entries:
            raise ValueError(
                f"cannot rename bookmark {old!r} -> {new!r}: "
                f"a bookmark named {new!r} already exists",
            )
        self._entries[new] = self._entries.pop(old)
        self._persist()

    def list(self) -> Dict[str, str]:
        """Return a copy of the current ``name -> url`` mapping."""
        return dict(self._entries)

    def subscribe_changed(
        self, callback: Callable[[], None],
    ) -> "Subscription":
        """Register ``callback`` to fire after a bookmark mutation."""

        def _handle(_key: str, _value: Any) -> None:
            callback()

        return self._settings.subscribe(SETTINGS_KEY, _handle)

    def _persist(self) -> None:
        """Write the current mapping to :class:`Settings`."""
        self._settings.set(SETTINGS_KEY, dict(self._entries))


__all__ = [
    "BOOKMARKS_SETTINGS_KEY",
    "SETTINGS_KEY",
    "BookmarksManager",
    "RecentFileList",
]

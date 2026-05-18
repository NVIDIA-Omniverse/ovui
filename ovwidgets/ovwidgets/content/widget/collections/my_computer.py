# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""MyComputerCollection — drives / mount points + user folders.

See the content browser behavior and the content browser implementation step 43.

The "My Computer" entry in the navigation pane enumerates the real
disk roots a user can jump to — Windows drive letters (``C:/``,
``D:/``, …) or POSIX mount points (``/``, ``/home``, ``/mnt/*``) —
plus the handful of user-folder shortcuts (Desktop / Documents /
Downloads / Pictures) that Kit's filebrowser surfaces for quick
access.

The children list recomputes on every :meth:`get_children` call —
mounts / drives can appear and disappear at runtime (a USB stick is
plugged, a network share is mapped) and caching them would show a
stale list. The enumeration cost is a single ``/proc/mounts`` read
(cheap) or a ``GetLogicalDrives`` bitmask read (cheaper) so re-reading
each expand is effectively free.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from ovwidgets.content.widget.collections.base import CollectionItem
from ovwidgets.content.widget.collections.disk_partitions import (
    FSTYPE_BLOCKLIST,
    disk_partitions,
)
from ovwidgets.content.widget.file_item import FileItem

if TYPE_CHECKING:
    from ovwidgets.content.backends.backend_adapter import BackendAdapter


# User-folder shortcut names, in the display order Kit's filebrowser
# uses. Only folders that actually exist on disk are surfaced — on a
# fresh Linux install Downloads / Pictures may not exist, and showing
# a broken navigation target is worse than omitting it.
_USER_FOLDER_NAMES: tuple = (
    "Desktop",
    "Documents",
    "Downloads",
    "Pictures",
)


# Windows drive-letter range — 26 letters from A..Z.
_DRIVE_LETTER_COUNT = 26


class MyComputerCollection(CollectionItem):
    """Navigation-pane "My Computer" root — drives, mounts, user folders.

    Child enumeration per platform:

    * **Windows** — ``ctypes.windll.kernel32.GetLogicalDrives()`` bitmask;
      one :class:`FileItem` per set bit at ``file:///{LETTER}:/``.
    * **Linux / macOS** — parse ``/proc/mounts`` via
      :func:`disk_partitions`, filter out kernel-virtual filesystems
      (:data:`FSTYPE_BLOCKLIST`), deduplicate mount points, and insert
      ``/`` at the top if it wasn't already present (so the root is
      always available even on exotic setups where ``/`` is not
      listed as a separate mount line).

    User folders (Desktop / Documents / Downloads / Pictures) are
    appended after the platform-specific roots so the user sees
    "here are the disks; here are your usual working directories" in
    one consistent order.
    """

    def __init__(self) -> None:
        super().__init__(
            identifier="my-computer",
            title="My Computer",
            icon_key="content_home",
        )
        # Cache of enumerated children. Populated on first
        # :meth:`get_children` call and reused on subsequent calls.
        # The cache is a hard Python reference so :class:`omni.ui.TreeView`
        # (which stores items by raw C++ pointer via pybind11) can
        # reconstruct their Python-subclass identity — without it, the
        # FileItem children come back as bare :class:`ui.AbstractItem`
        # on delegate render callbacks and the Name / icon render path
        # silently bails. :meth:`refresh` invalidates the cache so a
        # future auto-refresh hook can re-enumerate on mount changes.
        self._children_cache: Optional[List[FileItem]] = None

    def get_children(
        self, backend: "BackendAdapter",
    ) -> List[FileItem]:
        if self._children_cache is None:
            self._children_cache = self._enumerate()
        return self._children_cache

    def refresh(self) -> None:
        """Drop the cached children so the next :meth:`get_children`
        call re-enumerates drives / mounts / user folders.

        Intended for a future hook that listens for mount changes
        (e.g. a USB drive plugged / unplugged) and nudges the nav
        pane to re-render. The cache-based render path (see
        ``__init__``) means the widget has to call :meth:`refresh`
        rather than relying on :meth:`get_children` seeing a fresh
        ``/proc/mounts`` every call.
        """
        self._children_cache = None

    def _enumerate(self) -> List[FileItem]:
        if os.name == "nt":
            roots = self._windows_drives()
        else:
            roots = self._posix_mounts()
        return roots + self._user_folders()

    # ── Platform-specific enumeration ────────────────────────────────────────

    def _windows_drives(self) -> List[FileItem]:
        """Return one :class:`FileItem` per Windows drive letter set in
        the ``GetLogicalDrives`` bitmask.

        Drive roots are returned as ``file:///{LETTER}:/`` so they
        canonicalise against :meth:`LocalFSBackend.normalize_url`'s
        lowercase drive-letter convention — the URL shape a subsequent
        ``navigate_to`` call expects.
        """
        import ctypes

        bitmask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
        drives: List[FileItem] = []
        for index in range(_DRIVE_LETTER_COUNT):
            if not (bitmask & (1 << index)):
                continue
            letter = chr(ord("A") + index)
            url = f"file:///{letter}:/"
            display = f"{letter}:/"
            drives.append(FileItem(url=url, name=display, is_folder=True))
        return drives

    def _posix_mounts(self) -> List[FileItem]:
        """Return one :class:`FileItem` per real mount point from
        ``/proc/mounts``, skipping kernel-virtual filesystems and
        deduplicating repeated mount points (a single directory that
        appears twice in the table because the kernel mounted a new
        filesystem on top of it).

        Inserts ``/`` at the top of the list if no partition reports
        the root mount — some hardened configurations hide the root
        entry and the UX guarantee is that "My Computer" always lets
        the user reach ``/``.
        """
        partitions = disk_partitions()
        items: List[FileItem] = []
        seen: set = set()
        for partition in partitions:
            if partition.fstype in FSTYPE_BLOCKLIST:
                continue
            mountpoint = partition.mountpoint
            if mountpoint in seen:
                continue
            seen.add(mountpoint)
            items.append(
                FileItem(
                    url=f"file://{mountpoint}",
                    name=mountpoint,
                    is_folder=True,
                ),
            )
        if "/" not in seen:
            items.insert(
                0,
                FileItem(url="file:///", name="/", is_folder=True),
            )
        return items

    # ── User folders ─────────────────────────────────────────────────────────

    def _user_folders(self) -> List[FileItem]:
        """Return FileItems for Desktop / Documents / Downloads / Pictures
        that exist on disk.

        On POSIX we use ``Path.home() / name``; on Windows the
        architecture spec (§14.2) calls for ``SHGetKnownFolderPath``
        via ctypes to resolve redirected / localised paths. That
        ctypes binding is out of scope for Step 43 — Windows support
        in this codebase is a v2 target — so the Windows branch uses
        the same ``Path.home()`` path, which is correct for the
        default (non-redirected) user-folder layout. When a Windows
        user has redirected their Documents to OneDrive, the
        ``Path.home() / 'Documents'`` path will not exist and the
        folder is silently omitted rather than pointing at nothing.
        """
        home = Path.home()
        folders: List[FileItem] = []
        for name in _USER_FOLDER_NAMES:
            path = home / name
            if not path.exists():
                continue
            url = f"file://{path}"
            folders.append(
                FileItem(url=url, name=name, is_folder=True),
            )
        return folders

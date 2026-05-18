# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Recent files list for USD Viewer.

Maintains an ordered list of the last MAX recently opened file paths.
Re-opening an existing path promotes it to the top. Persists via Settings.
"""

from collections import deque
from typing import List, Optional


class RecentFileList:
    """Ordered deque of recently opened file paths, capped at MAX entries.

    Call add() after each successful open. Caller is responsible for persisting
    get_ordered() to settings and reloading at startup.

    Process-wide singleton accessor (added in implementation Step 4 per
    Rev 8 §5.10 + Plan Rev 2 §4 Step 4): :meth:`RecentFileList.instance`
    returns the singleton; :meth:`RecentFileList.set_instance` registers /
    clears it. Application registers its own ``RecentFileList`` instance at
    startup so widget code can read the same list via
    :meth:`RecentFileList.instance` without reaching into
    ``Application.instance()._recent_files``. Until Application registers,
    :meth:`instance` returns a freshly-constructed default — useful in
    unit tests that exercise widget code without a live application.
    """

    MAX = 10

    _instance: "Optional[RecentFileList]" = None

    @classmethod
    def instance(cls) -> "RecentFileList":
        """Return the process-wide ``RecentFileList`` instance (lazy default)."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def set_instance(cls, recent_files: "Optional[RecentFileList]") -> None:
        """Register / clear the process-wide ``RecentFileList`` instance.

        Called by :class:`ovwidgets.app.application.Application` at
        ``__init__`` (with the live list) and at ``shutdown`` (with
        ``None`` to clear). Tests that need isolation can also call this
        with a freshly-constructed ``RecentFileList`` and reset to
        ``None`` at teardown.
        """
        cls._instance = recent_files

    def __init__(self, initial: Optional[List[str]] = None) -> None:
        self._items: deque = deque(initial or [], maxlen=self.MAX)

    def add(self, path: str) -> None:
        """Add path to the top. Promotes if already present; drops oldest if full."""
        if path in self._items:
            self._items.remove(path)
        self._items.appendleft(path)

    def get_ordered(self) -> List[str]:
        """Return paths most-recently-opened first."""
        return list(self._items)

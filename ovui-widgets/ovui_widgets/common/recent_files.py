# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Compatibility path for recent-file navigation state.

The reusable ordering behavior now lives in
``ovui_data_adapters.services.content.navigation``. This ovui_widgets wrapper
keeps the app/widget singleton policy at the UI application layer.
"""

from typing import Optional

from ovui_data_adapters.services.content.navigation import (
    RecentFileList as _ServiceRecentFileList,
)


class RecentFileList(_ServiceRecentFileList):
    """ovui-widgets compatibility wrapper with application singleton policy."""

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

        Called by :class:`ovui_widgets.app.application.Application` at
        ``__init__`` (with the live list) and at ``shutdown`` (with
        ``None`` to clear). Tests that need isolation can also call this
        with a freshly-constructed ``RecentFileList`` and reset to
        ``None`` at teardown.
        """
        cls._instance = recent_files


__all__ = ["RecentFileList"]

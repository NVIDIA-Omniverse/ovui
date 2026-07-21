# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Frontend-neutral internal clipboard state for content operations.

This module models only the process-local cut/copy state that content
frontends share. It does not integrate with the operating-system clipboard,
does not repaint widgets, and does not own application singleton policy.
"""

from __future__ import annotations

from typing import Sequence


class ContentClipboard:
    """Mutable cut/copy clipboard state for content URLs."""

    def __init__(self) -> None:
        self._urls: list[str] = []
        self._is_cut = False

    def save_to_clipboard(
        self, urls: Sequence[str], is_cut: bool = False,
    ) -> None:
        """Replace the clipboard contents with ``urls``."""
        self._urls = list(urls)
        self._is_cut = bool(is_cut)

    def get_clipboard_urls(self) -> list[str]:
        """Return a fresh copy of the current clipboard URLs."""
        return list(self._urls)

    def is_clipboard_cut(self) -> bool:
        """Return ``True`` when the current clipboard mode is Cut."""
        return self._is_cut

    def is_path_cut(self, url: str) -> bool:
        """Return ``True`` when ``url`` is in the current Cut selection."""
        return self._is_cut and url in self._urls

    def clear_clipboard(self) -> None:
        """Empty the clipboard and reset the cut flag."""
        self._urls.clear()
        self._is_cut = False


__all__ = ["ContentClipboard"]

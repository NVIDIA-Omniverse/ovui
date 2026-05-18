# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""DropVisualController — tracks drag-over target for visual feedback.

Used by StageWidget drag-drop reparent feedback.
"""

from __future__ import annotations

from typing import Any


class DropVisualController:
    """Tracks the current drag-over target and drop position.

    State is updated by HierarchyModel.drop_accepted and cleared on drop/cancel.
    """

    def __init__(self) -> None:
        self._current_target = None
        self._current_position: int = -1

    def show_drop_target(self, item: Any, position: int) -> None:
        """Record the current hover target and drop location (-1=on, 0=above, 1=below)."""
        self._current_target = item
        self._current_position = position

    def clear(self) -> None:
        """Remove any active drop highlight state."""
        self._current_target = None
        self._current_position = -1

    @property
    def current_target(self) -> Any:
        return self._current_target

    @property
    def current_position(self) -> int:
        return self._current_position

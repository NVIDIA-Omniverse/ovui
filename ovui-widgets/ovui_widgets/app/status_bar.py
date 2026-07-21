# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""StatusBar widget — thin label row at the bottom of the main window."""

from typing import Any

import omni.ui as ui


class StatusBar:
    """
    A thin label row at the bottom of the main window.
    Shows status messages with optional severity styling.

    Uses style_type_name_override="OvGear.StatusBar" with name=level
    for severity-based styling (matches GLOBAL_STYLES from Step 3).
    """

    def __init__(self, parent_frame: Any, call_later_fn: Any = None) -> None:
        """Build the status bar inside the given frame.

        call_later_fn: if provided, used to schedule auto-clear after duration_ms.
        """
        self._frame = parent_frame
        self._label = None
        self._clear_task = None
        self._call_later = call_later_fn
        self._build()
        self._set_frame_visible(True)

    def _build(self) -> None:
        """Create the status bar UI."""
        with self._frame:
            self._label = ui.Label(
                "",
                style_type_name_override="OvGear.StatusBar",
                height=24,
            )

    def _set_frame_visible(self, _visible: bool) -> None:
        """Keep the MainWindow status frame reserved to avoid viewport relayout."""
        try:
            self._frame.visible = True
        except Exception:
            pass

    def show_message(self, text: str, duration_ms: int = 3000, level: str = "") -> None:
        """Display a message. Clears after duration_ms.
        level can be: '', 'error', 'warning', 'success'."""
        if self._label is None:
            return
        self._set_frame_visible(bool(text))
        self._label.text = text
        self._label.name = level if level else ""
        if self._clear_task is not None:
            self._clear_task.cancel()
            self._clear_task = None
        if self._call_later and duration_ms > 0:
            self._clear_task = self._call_later(duration_ms / 1000.0, self.clear)

    def clear(self) -> None:
        """Clear the status message."""
        if self._label:
            self._label.text = ""
            self._label.name = ""
        self._set_frame_visible(False)
        self._clear_task = None

    @property
    def label(self) -> Any:
        """The underlying ui.Label widget."""
        return self._label

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Centralised error-reporting facade.

ErrorReporter is the single point for error logging and
user-facing status messages.
"""

import sys
from typing import Any, Optional


def _get_level_style(level: str) -> dict:
    """Return a style dict with the shade-aware text color for *level*.

    Evaluated at call time so the correct color is returned after any
    ui.set_shade() call — unlike a module-level constant which would capture
    the shade value at import time.
    """
    from omni.ui import color as cl
    if level == "error":
        return {"color": cl.status_error}
    if level == "warning":
        return {"color": cl.status_warning}
    if level == "success":
        return {"color": cl.status_success}
    return {"color": cl.text_primary}


class ErrorReporter:
    """
    Central error reporting and status messaging.

    ErrorReporter is the single point for error logging and
    user-facing status messages. Initially logs to stderr. When initialized
    with a ui.Label (Step 56 API), status messages are shown directly in the
    UI label with color coding and auto-dismiss via app.call_later().
    """

    _status_bar = None          # Legacy: StatusBar widget (Step 7 API)
    _status_label = None        # Direct ui.Label reference (Step 56 API)
    _dismiss_handle = None      # CallbackHandle for auto-dismiss timer
    _app = None                 # Application reference for call_later()

    @classmethod
    def initialize(cls, app: Any, status_label: Any) -> None:
        """Wire ErrorReporter to the UI label. Call from Application after UI is built."""
        cls._app = app
        cls._status_label = status_label

    @classmethod
    def log_error(cls, module: str, message: str, exc: Optional[Exception] = None) -> None:
        """Log an error to stderr. Include exception info if provided."""
        msg = f"[ERROR] [{module}] {message}"
        if exc:
            msg += f"\n  Exception: {type(exc).__name__}: {exc}"
        print(msg, file=sys.stderr)

    @classmethod
    def log_warning(cls, module: str, message: str) -> None:
        """Log a warning to stderr."""
        print(f"[WARNING] [{module}] {message}", file=sys.stderr)

    @classmethod
    def log_info(cls, module: str, message: str) -> None:
        """Log info to stderr."""
        print(f"[INFO] [{module}] {message}", file=sys.stderr)

    # Maximum length of a status-bar message before truncation.
    # The status-bar label sits on a transparent overlay and grows
    # vertically when given a string with embedded newlines, which then
    # bleeds over the Property Inspector panel below. Single-line
    # messages kept under this budget fit the one-row slot at any
    # reasonable window width.
    _STATUS_MAX_LEN = 160

    @classmethod
    def _sanitize_status_text(cls, message: str) -> str:
        """Collapse newlines and truncate so the label stays single-line.

        Multi-line status messages (e.g. a full ``RuntimeError`` traceback
        from ovrtx renderer construction) otherwise wrap inside the
        overlay :class:`ui.Label` and overlap the Property Inspector —
        QA BUG-001.
        """
        if not message:
            return ""
        flat = " ".join(message.split())
        if len(flat) > cls._STATUS_MAX_LEN:
            flat = flat[: cls._STATUS_MAX_LEN - 1].rstrip() + "\u2026"
        return flat

    @classmethod
    def show_status(cls, message: str, duration_ms: int = 3000, level: str = "") -> None:
        """Show a status message in the status bar or stderr.

        When initialized: sets label text with color coding and schedules
        auto-dismiss via app.call_later(). duration_ms=0 means no auto-dismiss.
        Message text is flattened to a single line and truncated via
        :meth:`_sanitize_status_text` before being written to the label,
        so multi-line error strings cannot wrap into adjacent panels.
        """
        display = cls._sanitize_status_text(message)
        if cls._status_label is not None:
            style = _get_level_style(level)
            cls._status_label.text = display
            cls._status_label.set_style(style)
            if cls._dismiss_handle is not None:
                cls._dismiss_handle.cancel()
                cls._dismiss_handle = None
            if duration_ms > 0 and cls._app is not None:
                cls._dismiss_handle = cls._app.call_later(
                    duration_ms / 1000.0, cls._clear_status
                )
        elif cls._status_bar is not None:
            cls._status_bar.show_message(display, duration_ms, level)
        else:
            print(f"[STATUS:{level or 'info'}] {message}", file=sys.stderr)

    @classmethod
    def show_error(cls, message: str, duration_ms: int = 5000) -> None:
        """Show an error status message."""
        cls.show_status(message, duration_ms, level="error")

    @classmethod
    def show_warning(cls, message: str, duration_ms: int = 4000) -> None:
        """Show a warning status message."""
        cls.show_status(message, duration_ms, level="warning")

    @classmethod
    def show_success(cls, message: str, duration_ms: int = 3000) -> None:
        """Show a success status message."""
        cls.show_status(message, duration_ms, level="success")

    @classmethod
    def _clear_status(cls) -> None:
        """Reset status label text to empty. Called by auto-dismiss timer."""
        if cls._status_label is not None:
            cls._status_label.text = ""
        cls._dismiss_handle = None

    @classmethod
    def _set_status_bar(cls, bar: Any) -> None:
        """Called by Application when StatusBar is created."""
        cls._status_bar = bar

    @classmethod
    def _clear_status_bar(cls) -> None:
        """Called on shutdown. Clears all reporter state."""
        cls._status_bar = None
        cls._status_label = None
        cls._app = None
        if cls._dismiss_handle is not None:
            cls._dismiss_handle.cancel()
        cls._dismiss_handle = None

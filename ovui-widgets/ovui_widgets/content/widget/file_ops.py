# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Compatibility file-operation helpers used by the content-browser context menu.

See the content browser behavior (specialized menus — "Open in
File Browser", "Copy URL Link") and the content browser implementation step 37. This module
holds the three "convenience" ops introduced at Step 37:

* :func:`duplicate_items` — copy each selected item into its parent
  folder with a " Copy" suffix. Drives Ctrl+D and the context-menu
  "Duplicate" entry. Collision avoidance: if the target name already
  has a " Copy" or " Copy N" suffix, the suffix is incremented rather
  than appended again (``foo Copy.txt`` → ``foo Copy 2.txt``). The
  helper also scans the destination folder's listing so a concurrent
  name already-present in the parent does not collide.
* :func:`open_in_native_browser` — reveal a local URL in the host OS's
  native file manager (``xdg-open`` / ``open`` / ``os.startfile``).
  Non-local schemes (``mock://``, ``omniverse://``, …) are refused —
  the OS file manager can't display them. Returns ``True`` on a
  successful dispatch so the caller can branch for status reporting.
* :func:`copy_url_to_clipboard` — v1 stub: logs the URL via
  :class:`ErrorReporter` (stderr + status-bar success line). Real OS
  clipboard integration lands when ovui surfaces one (architecture
  §17.4 "Copy URL Link" in Kit's Local menu); the string export here
  is enough for the user to read the URL off the status bar in the
  meantime.

Why a standalone module rather than methods on :class:`FileContextMenu`?
The menu is already ~1.4k LOC and its responsibilities (spec building,
paste-state FSM, dialog handoff) are orthogonal to these pure helpers.
Keeping file-ops as module-level functions:

* Keeps the historical ovui_widgets import path while delegating duplicate
  name / duplicate batch policy to
  ``ovui_data_adapters.services.content.file_operations``.
* Keeps OS-native browser and status/logging helpers here because those
  are frontend/runtime integrations, not frontend-neutral services.
* Avoids loading the menu module when a future, non-menu caller wants
  Duplicate (e.g. a drag-drop Step 38 that fires Duplicate on
  Ctrl+drop).
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable, List, Optional, Tuple

from ovui_widgets.common.error_reporter import ErrorReporter
from ovui_widgets.content.backends.backend_adapter import BackendAdapter
from ovui_widgets.content.widget.file_item import FileItem
from ovui_data_adapters.services.content.file_operations import (
    ContentFileRecord,
    _next_copy_name,
    duplicate_items as _service_duplicate_items,
)

# ──────────────────────────────────────────────────────────────────────────────
# Copy-name generation
# ──────────────────────────────────────────────────────────────────────────────

# Duplicate-name generation and duplicate batch policy are canonical in
# ``ovui_data_adapters.services.content.file_operations``. This module keeps the
# historical widget import path and adapts ``FileItem`` to a neutral record.


# ──────────────────────────────────────────────────────────────────────────────
# Duplicate
# ──────────────────────────────────────────────────────────────────────────────


def duplicate_items(
    backend: BackendAdapter,
    items: List[FileItem],
    refresh_parent_fn: Optional[Callable[[str], None]] = None,
) -> Tuple[int, List[Tuple[str, str]]]:
    """Duplicate each :class:`FileItem` into its parent folder.

    Semantics:

    * Each item is copied to ``{parent}/{next_copy_name}`` via
      :meth:`BackendAdapter.copy` with ``overwrite=False``. The new
      name is computed from the item's current name plus the sibling
      listing so duplicate-of-a-duplicate increments the suffix
      (``foo Copy.txt`` → ``foo Copy 2.txt``).
    * Per-item failure is recorded but the batch keeps going — the
      user authorised the whole selection by pressing Ctrl+D or
      clicking Duplicate, so an inconsistent partial state is less
      confusing than "aborted at item 3 with no feedback".
    * ``refresh_parent_fn`` (if provided) is invoked once per unique
      parent URL after the batch finishes — deduplicated so a
      multi-item duplicate in the same folder does not refresh the
      folder N times. This is the seam the context menu uses to
      trigger its model-refresh path; leaving it optional keeps the
      helper testable without a widget.

    Returns ``(success_count, errors)`` where ``errors`` is a list of
    ``(source_url, result_name)`` tuples — same shape as the Paste
    helper returns, so the caller can funnel them through the same
    :class:`ErrorReporter` formatting path.

    An empty ``items`` list returns ``(0, [])`` with no backend calls.
    """
    records = [
        ContentFileRecord(
            url=item.url,
            name=item.name,
            is_folder=item.is_folder,
        )
        for item in items
    ]
    return _service_duplicate_items(
        backend,
        records,
        refresh_parent_fn=refresh_parent_fn,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Open in native file browser
# ──────────────────────────────────────────────────────────────────────────────

# ``file://`` scheme prefix. Duplicated from :mod:`local_fs_backend` so
# this module does not reach across the backend boundary for a single
# string literal; keeping the constant here also means a future
# non-local-FS backend that can still map to a native path (e.g. a
# locally-cached Nucleus mount) can be added to the eligibility check
# without touching the local backend.
_LOCAL_SCHEME = "file://"


def _is_local_url(url: str) -> bool:
    """Return ``True`` if ``url`` can be opened by the OS file manager.

    Local-FS URLs use ``file://`` or a raw filesystem path; any URL
    carrying a scheme other than ``file://`` is not addressable by the
    native browser and is refused. Empty strings are also refused.
    """
    if not url:
        return False
    if url.startswith(_LOCAL_SCHEME):
        return True
    # A URL with a scheme other than ``file://`` — ``mock://``,
    # ``omniverse://``, ``http://`` — is rejected. ``"://"`` as a
    # substring is the unambiguous marker; a Windows path like
    # ``C:/foo`` never contains ``://``.
    return "://" not in url


def _url_to_native_path(url: str) -> str:
    """Translate ``url`` to an OS-native path for ``xdg-open`` / ``open``.

    Mirrors :func:`ovui_widgets.content.backends.local_fs_backend._url_to_fspath` —
    strips the ``file://`` prefix, drops the spurious leading slash
    before a Windows drive letter, and expands ``~``.
    """
    path = url
    if path.startswith(_LOCAL_SCHEME):
        path = path[len(_LOCAL_SCHEME):]
        if os.name == "nt" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
    return os.path.expanduser(path)


def open_in_native_browser(url: str) -> bool:
    """Reveal ``url`` in the host OS's native file manager.

    Returns ``True`` on successful dispatch, ``False`` if the URL is
    not a local-FS URL, does not exist on disk, or the native command
    raises.

    Platform dispatch:

    * Windows → :func:`os.startfile` (opens the default handler; for a
      folder that's Explorer).
    * macOS → ``open <path>`` (Finder for folders, default app for
      files).
    * Linux / other POSIX → ``xdg-open <path>`` (GNOME Files, Dolphin,
      Nautilus, …; any FD.O-compliant file manager).

    ``subprocess.run`` is used rather than ``Popen`` because the helper
    exits the moment the OS launcher has been told about the path —
    the file manager's own lifecycle is outside our control. ``check``
    is left ``False`` so a legitimately-absent handler (headless Linux
    without ``xdg-utils``) does not raise into the menu click path; the
    ``False`` return is the caller's signal to show a warning.
    """
    if not _is_local_url(url):
        return False
    path = _url_to_native_path(url)
    if not os.path.exists(path):
        return False
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except (OSError, subprocess.SubprocessError):
        # ``OSError`` covers ``FileNotFoundError`` (no ``xdg-open`` /
        # ``open`` on PATH); ``SubprocessError`` covers anything the
        # subprocess machinery itself raises. Swallow and return False
        # so the caller can surface a status-bar warning without this
        # helper leaking a traceback into the menu click path.
        return False
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Copy URL to clipboard (v1 — terminal-only)
# ──────────────────────────────────────────────────────────────────────────────

# Log / status vocabulary. Module constants so the test module can
# assert against exact strings without duplicating the literals in
# production code.
_LOG_COPY_URL_MODULE = "FileOps"
_LOG_COPY_URL_MESSAGE = "Copy URL: {url}"
_STATUS_COPY_URL_SUCCESS = "URL: {url}"


def copy_url_to_clipboard(url: str) -> None:
    """Export ``url`` to the user — v1 logs + shows a status-bar line.

    v1 predates an ovui-native OS-clipboard surface (architecture
    §17.4 Kit's Local menu uses ``omni.kit.clipboard`` which we do not
    bundle). The v1 export is two-pronged:

    * A stderr line via :meth:`ErrorReporter.log_info` so a developer
      running the app in a terminal can copy the URL verbatim.
    * A success-style status-bar line via
      :meth:`ErrorReporter.show_success` so the user gets an
      in-app signal that the click landed.

    An empty / falsy ``url`` is a silent no-op — a plug-in that wires
    Copy-URL into a non-item context would otherwise log a misleading
    empty-string line.
    """
    if not url:
        return
    ErrorReporter.log_info(
        _LOG_COPY_URL_MODULE,
        _LOG_COPY_URL_MESSAGE.format(url=url),
    )
    ErrorReporter.show_success(_STATUS_COPY_URL_SUCCESS.format(url=url))


__all__ = [
    "copy_url_to_clipboard",
    "duplicate_items",
    "open_in_native_browser",
]

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Abstract backend adapter for URL-based storage.

See the content browser behavior and the content browser implementation step 1.

``BackendAdapter`` plays the role ``omni.client`` does for Kit: a uniform
URL-based API for stat / list / read / write / copy / move / delete /
subscribe across whatever storage a frontend happens to be talking to.
The first service implementation ships a local-filesystem backend, but
callers go through this ABC so future Nucleus / HTTP / S3 backends can
plug in without touching frontend model or widget layers.

Enum names are aligned with ``omni.client`` (``Result`` /
``ItemFlags`` / ``ListEntry``) so the architecture document's Kit
references translate directly.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, Flag, auto
from typing import Callable, List, Optional, Tuple

from ovui_data_adapters.common import SubscriptionProtocol

# ──────────────────────────────────────────────────────────────────────────────
# Enums and Flags
# ──────────────────────────────────────────────────────────────────────────────

class BackendResult(Enum):
    """Result code returned by every mutating ``BackendAdapter`` call.

    Unlike ``omni.client.Result`` this is a plain ``Enum``, not a
    ``str`` subclass: we have no C++ serialization constraint to honour
    and a plain enum can't be accidentally compared against the wrong
    string literal. Consumers branch with ``==``.
    """

    OK = auto()
    ERROR_NOT_FOUND = auto()
    ERROR_ACCESS_DENIED = auto()
    ERROR_ALREADY_EXISTS = auto()
    ERROR_CONNECTION = auto()
    ERROR_NOT_SUPPORTED = auto()
    ERROR = auto()


class BackendFileFlags(Flag):
    """Bitmask describing a single ``BackendListEntry``.

    ``Flag`` (not ``IntFlag``) is used deliberately — matches the
    convention already set by :class:`ovui_data_adapters.common.ItemFlags` and
    :class:`ovui_data_adapters.common.BadgeFlags`.
    This prevents silent coercion to ``int`` in arithmetic contexts.
    """

    NONE = 0
    IS_FOLDER = auto()
    IS_HIDDEN = auto()
    IS_SYMLINK = auto()
    IS_READABLE = auto()
    IS_WRITABLE = auto()


# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BackendListEntry:
    """Single entry from :meth:`BackendAdapter.stat` or
    :meth:`BackendAdapter.list_dir`. Mirrors ``omni.client.ListEntry``
    (see the content browser behavior)."""

    name: str                # Leaf name (basename of the URL).
    flags: BackendFileFlags  # Bitmask.
    size: int                # Size in bytes; 0 for folders.
    modified_time: float     # Unix timestamp, seconds since epoch.
    created_time: float      # Unix timestamp, seconds since epoch.


@dataclass(frozen=True)
class BackendChangeEvent:
    """Emitted by :meth:`BackendAdapter.subscribe_changes` when a
    watched path changes (see the content browser behavior and
    §6.1).

    ``event_type`` is a free-form ``str`` rather than an enum so
    adapters can emit backend-specific subtypes (e.g. a future
    ``NucleusBackend`` could emit ``"locked"``). Consumers match the
    known set (``"created" | "deleted" | "updated" | "obliterated"``)
    and ignore unknown types.
    """

    url: str                            # Watched root URL.
    event_type: str                     # e.g. "created" | "deleted" | "updated" | "obliterated".
    entry: Optional[BackendListEntry]   # The entry involved, if known.


# ──────────────────────────────────────────────────────────────────────────────
# Abstract Base Class
# ──────────────────────────────────────────────────────────────────────────────

class BackendAdapter(ABC):
    """Abstract backend — plays the role ``omni.client`` does for Kit.

    Every read, write, stat, list, copy, move, delete, or change-
    subscription in the content service stack goes through BackendAdapter.
    See the content browser behavior and the content browser implementation step 1 for the rationale.

    All methods are synchronous. Adapters that back remote storage in a
    future revision can run their own threads internally and marshal results
    through a frontend-owned scheduler; the backend service does not own the
    UI or app loop.
    """

    # ── Scheme support ──

    @abstractmethod
    def supports_url(self, url: str) -> bool:
        """Return ``True`` if this backend can handle ``url``.

        Used by a future dispatcher to pick between registered
        backends. ``LocalFSBackend`` accepts ``file://`` URLs plus raw
        absolute paths; a future ``NucleusBackend`` would accept
        ``omniverse://``.
        """

    # ── Reads ──

    @abstractmethod
    def stat(self, url: str) -> Tuple[BackendResult, Optional[BackendListEntry]]:
        """Return metadata for the single entry at ``url``.

        On success returns ``(BackendResult.OK, entry)``. On failure
        returns ``(error_code, None)``.
        """

    @abstractmethod
    def list_dir(self, url: str) -> Tuple[BackendResult, List[BackendListEntry]]:
        """List children of the folder at ``url``.

        On success returns ``(BackendResult.OK, [entry, ...])``. If
        ``url`` does not refer to a folder the backend must return an
        empty list and an appropriate error code (``ERROR_NOT_FOUND``
        or similar) — never raise.
        """

    # ── Writes ──

    @abstractmethod
    def create_folder(self, url: str) -> BackendResult:
        """Create an empty folder at ``url``. Non-recursive — the
        parent must already exist."""

    @abstractmethod
    def copy(self, src_url: str, dst_url: str, overwrite: bool = False) -> BackendResult:
        """Copy the entry at ``src_url`` to ``dst_url``.

        Returns :attr:`BackendResult.ERROR_ALREADY_EXISTS` when
        ``dst_url`` exists and ``overwrite`` is ``False``.
        """

    @abstractmethod
    def move(self, src_url: str, dst_url: str, overwrite: bool = False) -> BackendResult:
        """Rename or move the entry at ``src_url`` to ``dst_url``.

        Backends may implement this as copy+delete when the source and
        destination live on different volumes.
        """

    @abstractmethod
    def delete(self, url: str) -> BackendResult:
        """Delete the entry at ``url``. Folders are deleted
        recursively."""

    # ── URL utilities ──

    @abstractmethod
    def normalize_url(self, url: str) -> str:
        """Return the canonical form of ``url``.

        Must round-trip through :meth:`parent_url` / :meth:`join_url`
        without further rewrites. Rules differ per backend:
        ``LocalFSBackend`` uses :class:`pathlib.PurePath`; a Nucleus
        backend would need URL percent-encoding.
        """

    @abstractmethod
    def join_url(self, base: str, child: str) -> str:
        """Append ``child`` name to ``base`` URL, returning a new
        URL."""

    @abstractmethod
    def parent_url(self, url: str) -> Optional[str]:
        """Return the URL of the folder containing ``url`` or ``None``
        if ``url`` is already a root."""

    @abstractmethod
    def basename(self, url: str) -> str:
        """Return the leaf name of ``url`` (the portion after the last
        separator)."""

    # ── Live updates ──

    def subscribe_changes(
        self, url: str, callback: Callable[[BackendChangeEvent], None]
    ) -> SubscriptionProtocol:
        """Subscribe to filesystem changes under ``url``.

        The default implementation returns a no-op subscription so
        backends without change notification can skip implementing it
        — consumers fall back to manual
        ``refresh_current_directory``. Concrete backends that can
        watch (``LocalFSBackend`` via ``watchdog``, a hypothetical
        ``NucleusBackend`` via
        ``omni.client.list_subscribe_with_callback``) override this
        method and dispatch :class:`BackendChangeEvent` instances to
        ``callback``.

        The returned object satisfies
        :class:`ovui_data_adapters.common.SubscriptionProtocol` — it has
        ``cancel()`` and ``__del__`` — so consumers can hold it without
        caring whether the backend actually subscribes.
        """

        class _NoOpSubscription:
            def cancel(self) -> None:
                pass

            def __del__(self) -> None:
                pass

        return _NoOpSubscription()

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Frontend-neutral settings store and observer semantics.

This module owns only generic key/value storage, synchronous key-specific
notifications, subscription lifetime, and JSON persistence. Application
defaults, singleton registration policy, UI theme keys, viewport defaults,
and widget-specific schemas stay with the frontend that owns them.
"""

from __future__ import annotations

import json
import os
import weakref
from collections.abc import Mapping
from typing import Any, Callable

_SENTINEL = object()


def _copy_default(value: Any) -> Any:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    return value



def _retain_failed_revocation(owner: object, handle: object) -> None:
    stale = getattr(owner, "_stale_subscription_handles", None)
    if stale is None:
        try:
            stale = []
            setattr(owner, "_stale_subscription_handles", stale)
        except Exception:
            return
    # Identity-deduplicated: repeated failures of ONE handle retain it
    # exactly once. Retention is NEVER capped: every live registration
    # keeps durable owner-side revocation ownership, and the collection
    # is finite by construction — at most one small handle per admitted
    # registration.
    if not any(existing is handle for existing in stale):
        stale.append(handle)


def _drain_stale_revocations(owner: object) -> None:
    """Retry every retained failed revocation; drop the resolved ones."""
    stale = getattr(owner, "_stale_subscription_handles", None)
    if not stale:
        return
    remaining = []
    for handle in stale:
        try:
            handle.cancel()
        except BaseException:  # noqa: BLE001 — still owned for retry
            if not any(existing is handle for existing in remaining):
                remaining.append(handle)
    stale[:] = remaining

class Subscription:
    """RAII subscription handle. Call :meth:`cancel` to unsubscribe."""

    def __init__(
        self,
        settings_ref: "weakref.ref[Any]",
        key: str,
        callback: Callable[[str, Any], None],
    ) -> None:
        self._settings_ref = settings_ref
        self._key = key
        self._callback = callback
        self._cancelled = False

    def cancel(self) -> None:
        """Remove this subscriber from the settings store."""
        if self._cancelled:
            return
        settings = self._settings_ref()
        if settings is not None:
            # Mark cancelled only AFTER removal succeeded: a failed
            # revocation stays owned by the STORE (GC-safe) and retryable.
            try:
                settings._remove_subscriber(self._key, self._callback)
            except BaseException:
                _retain_failed_revocation(settings, self)
                raise
        self._cancelled = True

    def __del__(self) -> None:
        try:
            self.cancel()
        except BaseException:  # noqa: BLE001 — never unraisable: the
            # owner already retains durable revocation ownership.
            pass


class Settings:
    """Key/value settings store with pub/sub notification and JSON persistence."""

    def __init__(self, defaults: Mapping[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = {}
        self._subscribers: dict[str, list[Callable[[str, Any], None]]] = {}
        for key, value in (defaults or {}).items():
            self._data[key] = _copy_default(value)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value. Returns ``default`` if ``key`` is missing."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a setting value and notify subscribers only when it changes."""
        old = self._data.get(key, _SENTINEL)
        if old is not _SENTINEL and old == value:
            return
        self._data[key] = value
        for cb in list(self._subscribers.get(key, [])):
            cb(key, value)

    def get_string(self, key: str, default: str = "") -> str:
        """Return a setting as ``str``."""
        val = self.get(key, default)
        return str(val)

    def subscribe(
        self, key: str, callback: Callable[[str, Any], None]
    ) -> Subscription:
        """Subscribe to changes on one key."""
        if key not in self._subscribers:
            self._subscribers[key] = []

        _drain_stale_revocations(self)
        self._subscribers[key].append(callback)
        return Subscription(weakref.ref(self), key, callback)

    def _remove_subscriber(
        self, key: str, callback: Callable[[str, Any], None]
    ) -> None:
        subs = self._subscribers.get(key)
        if subs and callback in subs:
            subs.remove(callback)

    def load_from_file(self, path: str) -> None:
        """Load settings from a JSON file, merging with existing settings."""
        with open(path) as f:
            data = json.load(f)
        for key, value in data.items():
            self.set(key, value)

    def save_to_file(self, path: str) -> None:
        """Save current settings to a JSON file, creating parent dirs as needed."""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self._data, f, indent=2)


__all__ = ["Settings", "Subscription"]

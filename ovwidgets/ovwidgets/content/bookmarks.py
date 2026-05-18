# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""BookmarksManager — persistent folder bookmarks for the content browser.

See the content browser behavior (bookmark collection) and
the content browser implementation step 44. The manager owns the persistent ``name → url``
mapping that powers the navigation pane's :class:`BookmarksCollection`.
It is the headless half of the bookmark feature; the UI half
(:class:`BookmarksCollection`) lives under
:mod:`ovwidgets.content.widget.collections.bookmarks` and
subscribes to this manager for change notifications.

Persistence is delegated to :class:`ovwidgets.common.settings.Settings`: the
full mapping is serialised as a JSON-compatible dict under the single
key ``ui.content.bookmarks``. That means a manager instantiated with a
:class:`Settings` that already holds a persisted dict (loaded from
disk at application startup) initialises with the previous session's
bookmarks automatically, and every mutation ``add`` / ``remove`` /
``rename`` writes the new dict back so the next startup sees the
updated state.

Change notifications fan out through :meth:`subscribe_changed`, which
returns an RAII :class:`ovwidgets.common.settings.Subscription`. Subscribers are
fired whenever the stored dict actually changes — :class:`Settings`
deduplicates no-op writes, so ``add`` / ``remove`` / ``rename`` calls
that leave the mapping unchanged do not notify. The callback shape is
deliberately zero-argument: a listener interested in the current
state calls :meth:`list` to read it, rather than having the mapping
shipped through the callback signature and coupling the caller to
:class:`Settings`'s ``(key, value)`` convention.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict

if TYPE_CHECKING:
    from ovwidgets.common.settings import Settings, Subscription


# The single Settings key under which the full ``name → url`` mapping
# is persisted. Module-level so tests can reference it directly
# without duplicating the string literal.
SETTINGS_KEY = "ui.content.bookmarks"


class BookmarksManager:
    """Persistent folder-bookmark store backed by :class:`Settings`.

    Construction reads the stored dict (or an empty dict if no
    bookmarks have ever been saved) into an in-memory mirror. Every
    mutation updates the mirror first, then writes the whole mapping
    back to :class:`Settings` under :data:`SETTINGS_KEY` so the
    on-disk representation always matches the live state.

    The manager is intentionally UI-free: no :mod:`omni.ui` imports,
    no :class:`FileItem` construction. That keeps it testable without
    an :class:`ovwidgets.app.application.Application` event loop and lets a
    non-UI caller (e.g. a future headless exporter) drive bookmarks
    directly through :meth:`add` / :meth:`remove` / :meth:`rename`.

    Thread safety: single-threaded. The navigation model is driven
    from the UI thread; mutations on a background thread would need
    external locking (none is expected in v1).
    """

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings
        stored = settings.get(SETTINGS_KEY, {}) or {}
        # Defensive copy so a caller that holds a ref to the stored
        # dict does not observe / influence the manager's mirror.
        self._entries: Dict[str, str] = dict(stored)

    # ── Public mutation API ──────────────────────────────────────────────────

    def add(self, name: str, url: str) -> None:
        """Add or overwrite the bookmark named ``name`` to point at ``url``.

        Idempotent: adding an existing ``(name, url)`` pair is a no-op
        and produces no change notification. Re-binding an existing
        name to a different URL overwrites — the architecture's
        bookmark model uses name as the primary key, not URL.
        """
        if self._entries.get(name) == url:
            return
        self._entries[name] = url
        self._persist()

    def remove(self, name: str) -> None:
        """Remove the bookmark named ``name``.

        Silently no-ops if ``name`` is not bookmarked — the UX calling
        convention here is "make sure this bookmark does not exist",
        which matches the Step 45 "Remove Bookmark" context-menu item
        that cannot always know whether the entry was already gone
        (e.g. deleted in another process).
        """
        if name not in self._entries:
            return
        del self._entries[name]
        self._persist()

    def rename(self, old: str, new: str) -> None:
        """Rename the bookmark ``old`` → ``new``, preserving its URL.

        No-ops if ``old`` does not exist or ``new == old``. Raises
        :class:`ValueError` when ``new`` would collide with an
        existing bookmark — silently overwriting the other bookmark
        during a rename would destroy user data, so the caller must
        resolve the conflict explicitly (e.g. remove the existing one
        first, then rename).
        """
        if old not in self._entries:
            return
        if new == old:
            return
        if new in self._entries:
            raise ValueError(
                f"cannot rename bookmark {old!r} → {new!r}: "
                f"a bookmark named {new!r} already exists",
            )
        self._entries[new] = self._entries.pop(old)
        self._persist()

    # ── Read API ─────────────────────────────────────────────────────────────

    def list(self) -> Dict[str, str]:
        """Return a copy of the current ``name → url`` mapping.

        A fresh :class:`dict` so callers cannot mutate the manager's
        internal state through the returned reference. Iteration order
        follows the insertion order preserved by :class:`dict` (Python
        3.7+) — the order bookmarks were added in across the lifetime
        of the persistent store.
        """
        return dict(self._entries)

    # ── Change subscription ──────────────────────────────────────────────────

    def subscribe_changed(
        self, callback: Callable[[], None],
    ) -> "Subscription":
        """Register ``callback`` to fire after a bookmark add/remove/rename.

        Returns an RAII :class:`ovwidgets.common.settings.Subscription` whose
        :meth:`cancel` (and :meth:`__del__`) removes the callback from
        the underlying :class:`Settings` store. The callback is
        zero-argument: listeners that need the post-change mapping
        call :meth:`list` themselves.

        No-op mutations (``add`` of an existing pair; ``remove`` of an
        absent name; ``rename`` with ``old == new``) do not fire
        because :class:`Settings` deduplicates writes — the dict
        stored under :data:`SETTINGS_KEY` is unchanged, so subscribers
        see no event.
        """

        # Wrap the user's zero-arg callback into the ``(key, value)``
        # shape :class:`Settings.subscribe` expects. Storing the
        # wrapper as a distinct local closure means the returned
        # :class:`Subscription`'s :meth:`cancel` removes exactly this
        # registration, independent of other subscribers using the
        # same ``callback`` object.
        def _handle(_key: str, _value: Any) -> None:
            callback()

        return self._settings.subscribe(SETTINGS_KEY, _handle)

    # ── Internals ────────────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Write the current mapping to :class:`Settings`.

        Persists a fresh copy of the in-memory dict so subscribers
        (and a future :meth:`Settings.save_to_file` dump) observe an
        independent snapshot that cannot be mutated retroactively by
        a subsequent manager mutation. :class:`Settings.set`
        deduplicates unchanged values — a mutation that happens to
        leave the mapping identical (e.g. an overwrite with the same
        URL) skips the subscriber notification automatically.
        """
        self._settings.set(SETTINGS_KEY, dict(self._entries))

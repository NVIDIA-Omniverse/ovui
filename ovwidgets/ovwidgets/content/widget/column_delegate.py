# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Column delegate abstraction + registry for the content browser.

the content browser behavior and the content browser implementation step 30
(``ColumnDelegateRegistry.register()`` is the stable extension seam for
third-party columns).

This module introduces the seam; no in-tree column uses it yet — the
built-in Name / Size / Date columns keep their direct-dispatch path
in :class:`FileBrowserDelegate` because they rely on the model's
:meth:`~FileBrowserModel.get_item_value_model` rather than a delegate
class. The registry is reserved for **plug-in** columns (ACL, Tags,
etc. in the Kit reference) that render entirely from their own
:meth:`AbstractColumnDelegate.build_widget` against a
:class:`FileItem`.

Design decisions (diverge intentionally from Kit's ``omni.kit.widget.filebrowser``):

* **Sync ``build_widget``**. Kit's :class:`AbstractColumnDelegate` is
  ``async`` so a plug-in can await a backend stat/tag query. ovui does
  not run the tree-view delegate inside an event loop; forcing async
  here would require a Kit-style ``ensure_future`` wrapper the browser
  does not own. v1 plug-ins run synchronously — see §8.1 for the
  trade-off. Future work may introduce an ``async_build_widget`` hook
  once ovui exposes a coroutine-friendly dispatch.
* **Fresh instance per render**. Kit's
  :meth:`FileBrowserTreeView._on_column_delegate_changed` caches one
  ``delegate_type()`` per view so per-view async futures can live on
  ``self``. Because build is sync here, the cache buys nothing; a fresh
  instance per ``build_widget`` call keeps the dispatch state-free and
  removes the need for a view-level ``_on_column_delegate_changed``
  subscription. The registry's change event is still published so a
  future caller (column-width recompute on the widget layer, Step 10+)
  can hook in without further API changes.
* **Duplicate-name = :class:`ValueError`**. Kit silently rejects duplicates
  with a misleading "Unknown column delegate" log (see
  the content browser behavior). Raising forces the caller to notice
  and either cancel the prior subscription or pick a different name.
* **RAII via explicit ``cancel``** (not ``__del__``). Same convention as
  :class:`ovwidgets.property.widget.scheme_registry.PropertySchemeRegistry` —
  the caller holds the subscription handle and calls ``cancel()``
  explicitly so anonymous subscriptions don't evaporate at garbage-
  collection time. The handle is idempotent: second ``cancel`` is a
  no-op.
"""

from __future__ import annotations

import abc
from typing import Any, Callable, Dict, List, Optional, Type

import omni.ui as ui

from ovwidgets.content.widget.file_item import FileItem

# ──────────────────────────────────────────────────────────────────────────────
# AbstractColumnDelegate
# ──────────────────────────────────────────────────────────────────────────────


class AbstractColumnDelegate(abc.ABC):
    """Base class for a plug-in column's cell renderer.

    Subclasses declare ``name`` (the registry key + header text) and
    implement :meth:`build_widget`; :attr:`initial_width` and
    :meth:`build_header` have sensible defaults that plug-ins may
    override.

    Subclasses are stored in the :class:`ColumnDelegateRegistry` as
    **classes**, not instances; the dispatcher in
    :class:`FileBrowserDelegate` constructs a fresh instance on every
    cell render. Subclass ``__init__`` should therefore be cheap and
    deterministic — if an implementation needs expensive per-view state
    it should stash it on a module-level cache keyed by
    ``FileItem.url``, not on ``self``.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Registry key + default column header text.

        Must be stable across the subclass's lifetime: the registry's
        duplicate-name check uses the value returned at registration
        time. Changing the name post-registration would leave the
        registry keyed on the old name and silently break the dispatch.
        """

    @property
    def initial_width(self) -> Any:
        """Default column width.

        Return a :class:`omni.ui.Fraction` to participate in flex
        allocation, or a :class:`omni.ui.Pixel` to claim a fixed width.
        Default is ``ui.Fraction(1)`` — one flex unit, same weight as
        the built-in Name column. Plug-ins with short cell content
        (ACL flags, tag counts) typically override to ``ui.Pixel(40)``
        so they steal fixed width off the end of the row; see
        the content browser behavior
        """
        return ui.Fraction(1)

    def build_header(self) -> None:
        """Optional header hook — default renders nothing.

        v1 wiring in :class:`FileBrowserDelegate.build_header` only
        dispatches built-in columns; plug-in column headers are
        deferred until the widget-level column-width pipeline lands
        (Step 10+ / the content browser behavior). Subclasses may
        override today, but the override is not reached by the current
        delegate. Documented as a forward-compatibility hook.
        """

    @abc.abstractmethod
    def build_widget(self, item: FileItem) -> None:
        """Render the plug-in column cell for ``item``.

        Called from inside an existing build context set up by
        :class:`FileBrowserDelegate.build_widget` — the implementation
        should emit a single :class:`omni.ui` widget (or an ``HStack``
        of widgets) and return. No return value is consumed. Exceptions
        propagate to the caller; the delegate does not wrap the call
        in a ``try/except`` so a plug-in bug fails loudly during
        development rather than rendering an invisible empty cell.
        """


# ──────────────────────────────────────────────────────────────────────────────
# Subscription
# ──────────────────────────────────────────────────────────────────────────────


class _ColumnDelegateSubscription:
    """RAII handle returned by :meth:`ColumnDelegateRegistry.register`.

    Follows the ``_WidgetSubscription`` pattern in
    :mod:`ovwidgets.property.widget.scheme_registry` — callers hold the
    handle to keep the registration live and call :meth:`cancel` to
    unregister. No ``__del__`` auto-cancel so anonymous-subscription
    lifetimes don't surprise callers by evaporating at garbage-
    collection time.

    :meth:`cancel` drops the entry on first call and self-nulls — a
    second ``cancel`` is a no-op, so the common sequence (``cancel``
    → someone else registers a replacement under the same name →
    forgotten ``cancel`` on the stale handle fires again) keeps the
    replacement alive.
    """

    def __init__(
        self,
        registry: "ColumnDelegateRegistry",
        name: str,
    ) -> None:
        self._registry: Optional["ColumnDelegateRegistry"] = registry
        self._name: Optional[str] = name

    def cancel(self) -> None:
        if self._registry is None or self._name is None:
            return
        self._registry._unregister(self._name)
        self._registry = None
        self._name = None


class _ChangedSubscription:
    """RAII handle returned by :meth:`ColumnDelegateRegistry.subscribe_changed`.

    Identical shape to :class:`_ColumnDelegateSubscription` but drops a
    callback rather than a named delegate. Kept as a distinct class so
    ``isinstance`` checks on returned handles can tell the two
    subscription kinds apart — relevant for any future consumer that
    unions them into a single ``List[object]`` lifetime bag.
    """

    def __init__(
        self,
        registry: "ColumnDelegateRegistry",
        cb: Callable[[], None],
    ) -> None:
        self._registry: Optional["ColumnDelegateRegistry"] = registry
        self._cb: Optional[Callable[[], None]] = cb

    def cancel(self) -> None:
        if self._registry is None or self._cb is None:
            return
        self._registry._unsubscribe_changed(self._cb)
        self._registry = None
        self._cb = None


# ──────────────────────────────────────────────────────────────────────────────
# ColumnDelegateRegistry
# ──────────────────────────────────────────────────────────────────────────────


class ColumnDelegateRegistry:
    """Singleton registry of plug-in column delegates.

    Access via :meth:`instance`; register via :meth:`register`; query
    via :meth:`get_registered_names` / :meth:`get_delegate_class`;
    observe via :meth:`subscribe_changed`. The registry is process-wide
    — a single extension registering ``"ACL"`` surfaces the ACL column
    in every open content-browser window.

    Ordering: :meth:`get_registered_names` returns names in
    **registration order**, mirroring the built-in columns' left-to-
    right layout contract. Kit sorts alphabetically
    (:ref:`§8.2 <content-window-architecture-8-2>`); registration order
    reads more predictably for a consumer who just called ``register``
    and expects their column to appear at the end.
    """

    _instance: Optional["ColumnDelegateRegistry"] = None

    def __init__(self) -> None:
        self._delegates: Dict[str, Type[AbstractColumnDelegate]] = {}
        # Registration-order list. Keeping it separate from the dict so
        # iteration order survives a Python 3.6-early dict implementation
        # even though CPython 3.7+ makes dicts ordered — the list reads
        # as the authoritative "visible columns" contract without
        # relying on a language-version guarantee.
        self._order: List[str] = []
        self._changed_cbs: List[Callable[[], None]] = []

    @classmethod
    def instance(cls) -> "ColumnDelegateRegistry":
        """Return the process-wide singleton, creating it on first call."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset_for_tests(cls) -> None:
        """Drop the singleton so the next :meth:`instance` call rebuilds it.

        Internal; not part of the public API. Tests that exercise
        registration semantics call this in setup/teardown so a
        registration from one test cannot leak into another. Production
        callers must not touch this — dropping the singleton mid-flight
        would strand existing subscription handles (their ``cancel``
        becomes a no-op because the registry they pointed at is gone).
        """
        cls._instance = None

    # ── Public registration API ─────────────────────────────────────────────

    def register(
        self,
        name: str,
        delegate_class: Type[AbstractColumnDelegate],
    ) -> _ColumnDelegateSubscription:
        """Register ``delegate_class`` under ``name``.

        Stores the **class**, not an instance — the dispatcher
        constructs a fresh instance per cell render so plug-ins don't
        share state across rows. Raises :class:`ValueError` if ``name``
        is already registered (callers that want to replace an existing
        entry must cancel the prior subscription first) or if
        ``delegate_class`` does not subclass
        :class:`AbstractColumnDelegate`.

        Returns a :class:`_ColumnDelegateSubscription` whose
        :meth:`~_ColumnDelegateSubscription.cancel` unregisters and
        notifies :meth:`subscribe_changed` listeners.
        """
        if not (
            isinstance(delegate_class, type)
            and issubclass(delegate_class, AbstractColumnDelegate)
        ):
            raise ValueError(
                f"ColumnDelegateRegistry: {delegate_class!r} is not a "
                "subclass of AbstractColumnDelegate"
            )
        if name in self._delegates:
            raise ValueError(
                f"ColumnDelegateRegistry: column {name!r} is already "
                "registered — cancel the prior subscription first"
            )
        self._delegates[name] = delegate_class
        self._order.append(name)
        self._notify_changed()
        return _ColumnDelegateSubscription(self, name)

    def subscribe_changed(
        self, cb: Callable[[], None],
    ) -> _ChangedSubscription:
        """Invoke ``cb`` every time a column registers or unregisters.

        Callbacks take no arguments — interested parties read the
        current state via :meth:`get_registered_names` /
        :meth:`get_delegate_class`. Same convention as Kit's
        ``subscribe_delegate_changed``
        (the content browser behavior).

        Returns a :class:`_ChangedSubscription` whose
        :meth:`~_ChangedSubscription.cancel` detaches the callback.
        """
        self._changed_cbs.append(cb)
        return _ChangedSubscription(self, cb)

    # ── Query API ──────────────────────────────────────────────────────────

    def get_registered_names(self) -> List[str]:
        """Return registered column names in registration order.

        Returns a fresh list so callers may mutate their copy without
        corrupting the registry's internal order bookkeeping.
        """
        return list(self._order)

    def get_delegate_class(
        self, name: str,
    ) -> Optional[Type[AbstractColumnDelegate]]:
        """Return the delegate class registered under ``name``, or ``None``."""
        return self._delegates.get(name)

    # ── Subscription internals ─────────────────────────────────────────────

    def _unregister(self, name: str) -> None:
        if name not in self._delegates:
            return
        del self._delegates[name]
        self._order = [n for n in self._order if n != name]
        self._notify_changed()

    def _unsubscribe_changed(self, cb: Callable[[], None]) -> None:
        try:
            self._changed_cbs.remove(cb)
        except ValueError:
            # Double-cancel is a silent no-op; matches
            # ``_ColumnDelegateSubscription`` semantics so callers can
            # lose track of which handles are live without a hazard.
            return

    def _notify_changed(self) -> None:
        # Iterate over a snapshot so a callback that re-enters the
        # registry (registering or cancelling another entry during its
        # own callback) does not mutate the list we are walking.
        for cb in list(self._changed_cbs):
            cb()

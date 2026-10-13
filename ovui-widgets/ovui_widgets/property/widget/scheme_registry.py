# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""``PropertySchemeRegistry`` — scheme-keyed widget & delegate registry.

property window scheme behavior / the property inspector step 6.5–6.6. Class-level singleton that
:class:`~ovui_widgets.property.window.PropertyWindow` consults on every rebuild
to decide which :class:`~ovui_widgets.property.widget.PropertyWidget` sections
to show. Third-party extensions plug in here without touching the
window — the same hook the Kit-side ``omni.kit.window.property``
:meth:`register_widget` / :meth:`register_scheme_delegate` APIs expose
(the property inspector behavior).

Scope
-----

* :meth:`register_widget` stores a zero-arg widget factory keyed by
  ``(scheme, name)`` with an integer ``order`` and a ``top_stack``
  tiebreak flag. Returns a :class:`_WidgetSubscription` whose
  :meth:`~_WidgetSubscription.cancel` unregisters the factory.
* :meth:`register_scheme_delegate` accepts
  :class:`~ovui_widgets.property.widget.scheme_delegate.PropertySchemeDelegate`
  registrations under ``(scheme, name)``. Step 6.6 wires the actual
  dispatch: :meth:`get_widgets_for_payload` runs every delegate for
  the scheme (plus ``"default"`` delegates) on every call, unions
  their :meth:`get_widgets` / :meth:`get_unwanted_widgets` outputs,
  and filters the registered-widget list by the wanted-wins-over-
  unwanted rule documented on :class:`PropertySchemeDelegate`.
* :meth:`get_widgets_for_payload` invokes every factory registered
  for ``"default"`` **plus** the requested scheme (deduplicated when
  the caller's scheme *is* ``"default"``), sorted by ``(order, not
  top_stack, insertion_count)``, then applies delegate filtering.
  Each factory is called fresh on every invocation so each
  :class:`PropertyWindow` rebuild gets its own instance — widgets
  that need per-window state (notably
  :class:`~ovui_widgets.property.widget.AttributesWidget`) stay isolated
  across multiple windows sharing the singleton registry.

Default registration
--------------------

At module-import time this module registers
:class:`~ovui_widgets.property.widget.AttributesWidget` under scheme
``"default"`` with ``order=100``, ``top_stack=False``. The
"default" scheme is treated as a universal scheme — widgets under it
surface for every payload regardless of the payload's actual scheme —
so the Step 6.2 catch-all behaviour ("AttributesWidget always
appears") is preserved even after Step 6.6 starts branching on
payload scheme.

AttributesWidget window binding
-------------------------------

:class:`AttributesWidget` reads its adapter / selection / filter
state from a :class:`PropertyWindow` back-reference. Scheme-registered
instances are constructed *without* a window (per Step 6.5's
:meth:`AttributesWidget.__init__` default of ``window=None``), then
:meth:`PropertyWindow._build_registered_widgets` calls
:meth:`AttributesWidget.set_window` on each returned instance before
invoking :meth:`on_new_payload`. The hand-off is duck-typed via
``hasattr(w, "set_window")`` so non-AttributesWidget factories are
unaffected.

Re-entry / lifetime
-------------------

The singleton survives for the life of the interpreter; tests
reset via :meth:`_reset_for_tests` in setup/teardown so stale
registrations from one test cannot leak into another. The reset
re-runs :func:`_register_defaults` so every test observes the same
baseline ("default" scheme → AttributesWidget) as production.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from ovui_widgets.property.payload import PropertyPayload
    from ovui_widgets.property.widget.property_widget import PropertyWidget
    from ovui_widgets.property.widget.scheme_delegate import PropertySchemeDelegate


# ---------------------------------------------------------------------------
# Registration records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _WidgetEntry:
    """One ``(scheme, name)`` registration for a widget factory.

    ``insertion`` is a monotonic counter drawn from the registry at
    registration time and threaded across both ``_widgets`` and
    ``_delegates`` dicts so the cross-scheme merge in
    :meth:`PropertySchemeRegistry.get_widgets_for_payload` produces a
    stable registration-order tiebreak even when widgets span multiple
    scheme buckets.
    """

    name: str
    factory: Callable[[], "PropertyWidget"]
    order: int
    top_stack: bool
    insertion: int


@dataclass(frozen=True)
class _DelegateEntry:
    """One ``(scheme, name)`` registration for a scheme delegate.

    Consulted by :meth:`PropertySchemeRegistry.get_widgets_for_payload`:
    its stored :class:`PropertySchemeDelegate` is asked for
    :meth:`get_widgets(payload) <PropertySchemeDelegate.get_widgets>`
    and :meth:`get_unwanted_widgets(payload)
    <PropertySchemeDelegate.get_unwanted_widgets>` on every call.
    """

    name: str
    delegate: "PropertySchemeDelegate"
    insertion: int


# ---------------------------------------------------------------------------
# Subscription handles
# ---------------------------------------------------------------------------


class _WidgetSubscription:
    """RAII handle returned by :meth:`PropertySchemeRegistry.register_widget`.

    Follows the ``_BuilderSubscription`` /
    ``_HandlerSubscription`` pattern elsewhere in ovui_widgets.property —
    callers hold the handle to keep the registration live and call
    :meth:`cancel` to unregister. No ``__del__`` auto-cancel, so
    anonymous-subscription lifetimes don't surprise callers by
    evaporating at garbage-collection time.

    ``cancel`` drops the ``(scheme, name)`` entry on first call and
    self-nulls — a second ``cancel`` is a no-op. The handle is bound to
    its exact registration generation (the unique entry record created
    by this ``register_widget`` call), so a stale ``cancel`` — after
    the entry was authoritatively removed and an independent owner
    registered a replacement under the same key, even one reusing the
    same factory object or class — no-ops instead of removing the
    replacement: re-registering the same object creates a NEW entry
    record that an old handle cannot match.
    """

    def __init__(
        self,
        registry: "PropertySchemeRegistry",
        scheme: str,
        name: str,
        entry: "_WidgetEntry",
    ) -> None:
        self._registry: Optional["PropertySchemeRegistry"] = registry
        self._scheme: Optional[str] = scheme
        self._name: Optional[str] = name
        self._entry: Optional["_WidgetEntry"] = entry

    def cancel(self) -> None:
        if (
            self._registry is None
            or self._scheme is None
            or self._entry is None
        ):
            return
        self._registry._remove_widget_entry(self._scheme, self._entry)
        self._registry = None
        self._scheme = None
        self._name = None
        self._entry = None


class _DelegateSubscription:
    """RAII handle returned by :meth:`PropertySchemeRegistry.register_scheme_delegate`.

    Mirrors :class:`_WidgetSubscription` exactly — separate class so
    callers can tell widget and delegate subscriptions apart in type
    annotations / ``isinstance`` checks, which becomes relevant in
    When delegates drive widget visibility, this registry, like the widget
    handle, it is bound to its exact registration generation (entry
    record) and never removes a same-key replacement, even one reusing
    the same delegate instance.
    """

    def __init__(
        self,
        registry: "PropertySchemeRegistry",
        scheme: str,
        name: str,
        entry: "_DelegateEntry",
    ) -> None:
        self._registry: Optional["PropertySchemeRegistry"] = registry
        self._scheme: Optional[str] = scheme
        self._name: Optional[str] = name
        self._entry: Optional["_DelegateEntry"] = entry

    def cancel(self) -> None:
        if (
            self._registry is None
            or self._scheme is None
            or self._entry is None
        ):
            return
        self._registry._remove_delegate_entry(self._scheme, self._entry)
        self._registry = None
        self._scheme = None
        self._name = None
        self._entry = None


# ---------------------------------------------------------------------------
# Registry singleton
# ---------------------------------------------------------------------------


_DEFAULT_SCHEME = "default"


class PropertySchemeRegistry:
    """Singleton scheme → widget-factory / delegate registry.

    Access the instance via :meth:`instance`; register factories via
    :meth:`register_widget` and delegates via
    :meth:`register_scheme_delegate`; query during rebuild via
    :meth:`get_widgets_for_payload`.

    The registry is constructed lazily on first :meth:`instance` call;
    the constructor runs :func:`_register_defaults` so every caller
    observes the built-in ``"default"`` scheme →
    :class:`AttributesWidget` mapping regardless of module-import
    order.
    """

    _instance: Optional["PropertySchemeRegistry"] = None

    def __init__(self) -> None:
        self._widgets: Dict[str, List[_WidgetEntry]] = {}
        self._delegates: Dict[str, List[_DelegateEntry]] = {}
        # Monotonic insertion counter, shared across widget and
        # delegate registrations so a stable cross-scheme registration
        # order survives the merge in :meth:`get_widgets_for_payload`.
        self._counter: int = 0
        # Weak identity ledger of every widget instance this registry
        # has handed out from :meth:`get_widgets_for_payload`. Detects
        # factories that return the same (singleton) instance across
        # dispatches — which would share per-window state — without
        # ever keeping a widget alive.
        self._issued_widgets: (
            "weakref.WeakValueDictionary[int, PropertyWidget]"
        ) = weakref.WeakValueDictionary()

    @classmethod
    def instance(cls) -> "PropertySchemeRegistry":
        """Return the process-wide singleton, creating it on first call.

        Defaults are registered inside :func:`_register_defaults`
        immediately after construction so every caller that touches
        the singleton sees the built-in ``"default"`` →
        :class:`AttributesWidget` mapping, regardless of whether
        :mod:`ovui_widgets.property.window` or the test module imported this
        module first.
        """
        if cls._instance is None:
            cls._instance = cls()
            _register_defaults(cls._instance)
        return cls._instance

    @classmethod
    def _reset_for_tests(cls) -> None:
        """Drop the singleton so the next :meth:`instance` call rebuilds it.

        Internal; not part of the public API. Tests that exercise
        registration semantics call this in setup/teardown so a
        registration from one test can't leak into assertion state of
        another. Production callers must not touch this — dropping the
        singleton mid-flight would strand existing subscription
        handles (their ``cancel`` becomes a no-op because the registry
        they pointed at is gone).
        """
        cls._instance = None

    # ------------------------------------------------------------------
    # Public registration API
    # ------------------------------------------------------------------

    def register_widget(
        self,
        scheme: str,
        name: str,
        widget_factory: Callable[[], "PropertyWidget"],
        order: int = 100,
        top_stack: bool = False,
    ) -> _WidgetSubscription:
        """Register ``widget_factory`` under ``(scheme, name)``.

        ``widget_factory`` is a zero-argument callable returning a
        :class:`PropertyWidget`. It is invoked fresh on every
        :meth:`get_widgets_for_payload` call, so per-window state is
        never shared across :class:`PropertyWindow` rebuilds. Returning
        a fresh, unshared ``PropertyWidget`` per invocation is a
        REQUIRED registrar precondition: dispatch rejects ``None``,
        non-``PropertyWidget`` results, instances shared with another
        factory in the same dispatch, and instances the factory already
        issued earlier (see :meth:`get_widgets_for_payload`).

        ``order`` is the primary sort key (lower = earlier); ``100`` is
        the conventional "middle of the stack" position matching Kit's
        default slot order. ``top_stack=True`` wins the tiebreak among
        widgets with the same ``order`` value; among entries with the
        same ``order`` *and* ``top_stack``, registration order wins.

        Raises :class:`ValueError` if ``(scheme, name)`` is already
        registered — callers that want to replace an existing entry
        must cancel the prior subscription first. Returns a
        :class:`_WidgetSubscription` whose :meth:`~_WidgetSubscription.cancel`
        unregisters.
        """
        entries = self._widgets.setdefault(scheme, [])
        if any(e.name == name for e in entries):
            raise ValueError(
                f"PropertySchemeRegistry: widget {name!r} already "
                f"registered for scheme {scheme!r}"
            )
        entry = _WidgetEntry(
            name=name,
            factory=widget_factory,
            order=order,
            top_stack=top_stack,
            insertion=self._counter,
        )
        entries.append(entry)
        self._counter += 1
        return _WidgetSubscription(self, scheme, name, entry)

    def register_scheme_delegate(
        self,
        scheme: str,
        name: str,
        delegate: "PropertySchemeDelegate",
    ) -> _DelegateSubscription:
        """Register ``delegate`` under ``(scheme, name)``.

        ``delegate`` is a
        :class:`~ovui_widgets.property.widget.scheme_delegate.PropertySchemeDelegate`
        whose :meth:`get_widgets(payload) <PropertySchemeDelegate.get_widgets>`
        and :meth:`get_unwanted_widgets(payload)
        <PropertySchemeDelegate.get_unwanted_widgets>` are consulted on
        every :meth:`get_widgets_for_payload` call to decide which
        named widgets surface for the current payload. Delegates
        registered under ``"default"`` apply universally — they
        contribute to every payload scheme for consistency with how
        ``"default"`` widgets surface.

        Raises :class:`ValueError` on duplicate ``(scheme, name)``.
        Returns a :class:`_DelegateSubscription` whose
        :meth:`~_DelegateSubscription.cancel` unregisters.
        """
        entries = self._delegates.setdefault(scheme, [])
        if any(e.name == name for e in entries):
            raise ValueError(
                f"PropertySchemeRegistry: delegate {name!r} already "
                f"registered for scheme {scheme!r}"
            )
        entry = _DelegateEntry(
            name=name,
            delegate=delegate,
            insertion=self._counter,
        )
        entries.append(entry)
        self._counter += 1
        return _DelegateSubscription(self, scheme, name, entry)

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get_widgets_for_payload(
        self,
        scheme: str,
        payload: "PropertyPayload",
    ) -> List["PropertyWidget"]:
        """Return ordered widget instances for ``scheme`` / ``payload``.

        Merges widgets registered under ``"default"`` with widgets
        registered under ``scheme`` (deduplicated when ``scheme`` is
        already ``"default"``), sorts by ``(order, not top_stack,
        insertion)``, then applies delegate filtering before invoking
        every surviving factory.

        ``"default"`` is the universal scheme — widgets there surface
        for every payload, so the Step 6.2 catch-all
        :class:`AttributesWidget` keeps appearing after Step 6.6 starts
        switching on the payload's actual scheme. Scheme-specific
        widgets (Step 6.4 :class:`SchemaPropertyWidget` subclasses)
        register under specific schemes and stack on top of the
        ``"default"`` entries sorted by the ordering rules.

        Delegate filtering (Step 6.6)
        -----------------------------

        After the candidate widget list is sorted, every
        :class:`~ovui_widgets.property.widget.scheme_delegate.PropertySchemeDelegate`
        registered for ``scheme`` plus every delegate registered for
        ``"default"`` (for parity with widget universality) is asked
        for :meth:`get_widgets(payload) <PropertySchemeDelegate.get_widgets>`
        and :meth:`get_unwanted_widgets(payload)
        <PropertySchemeDelegate.get_unwanted_widgets>`. Their outputs
        are unioned into two name sets; a candidate widget survives
        the filter iff its name is in the wanted set *or* not in the
        unwanted set — i.e. "wanted wins over unwanted". When no
        delegates are registered, both sets are empty and every
        candidate passes, preserving Step 6.5's catch-all behaviour.

        Sort order is preserved across filtering: the filter step
        walks the already-sorted list in order and keeps only the
        survivors, so the final factories run in the same order they
        would without delegates.
        """
        entries: List[_WidgetEntry] = list(self._widgets.get(_DEFAULT_SCHEME, []))
        if scheme != _DEFAULT_SCHEME:
            entries.extend(self._widgets.get(scheme, []))
        entries.sort(key=lambda e: (e.order, not e.top_stack, e.insertion))

        wanted, unwanted = self._collect_delegate_names(scheme, payload)
        survivors = [
            entry for entry in entries
            if entry.name in wanted or entry.name not in unwanted
        ]
        # Construction is an ownership transaction with an enforced
        # freshness contract: every factory result must be a fresh,
        # previously unproduced PropertyWidget instance, unshared within
        # this dispatch — a REQUIRED registrar precondition, rejected
        # here rather than surfacing as a less precise host failure
        # later. Each accepted identity is retired into the weak ledger
        # IMMEDIATELY — before the next factory runs — so an instance
        # destroyed by this transaction's rollback can never be handed
        # out by a later dispatch (use-after-destroy). A later factory
        # or validation failure destroys every unique earlier instance
        # exactly once (all destruction attempted, even hostile objects
        # whose ``destroy`` lookup raises) before the initiating
        # factory/validation error — always the primary exception —
        # propagates. Without this, a widget built by an earlier
        # factory would belong to nobody: the registry had returned it
        # and the window never received the list.
        widgets: List["PropertyWidget"] = []
        try:
            for entry in survivors:
                widget = entry.factory()
                self._validate_fresh_widget(entry.name, widget, widgets)
                self._retire_widget_identity(widget)
                widgets.append(widget)
        except BaseException:
            destroyed_ids: Set[int] = set()
            for widget in widgets:
                if id(widget) in destroyed_ids:
                    continue
                destroyed_ids.add(id(widget))
                try:
                    destroy = getattr(widget, "destroy", None)
                    if callable(destroy):
                        destroy()
                except BaseException:
                    # Rollback failures never mask the initiating error.
                    pass
            raise
        return widgets

    def _retire_widget_identity(self, widget: "PropertyWidget") -> None:
        """Record ``widget`` as produced, whether or not it is returned.

        Retirement happens at acceptance time, not on transaction
        success: a rolled-back instance stays in the ledger for as long
        as it is alive, so a singleton-style factory can never get the
        registry to return an already-destroyed widget.
        """
        try:
            self._issued_widgets[id(widget)] = widget
        except TypeError:
            # Non-weak-referenceable instances cannot be tracked for
            # cross-dispatch reuse; within-dispatch freshness still
            # holds.
            pass

    def _validate_fresh_widget(
        self,
        name: str,
        widget: object,
        transaction: List["PropertyWidget"],
    ) -> None:
        """Enforce the fresh-``PropertyWidget`` factory contract.

        Rejects ``None``/foreign results (``TypeError``), an instance
        already produced earlier in the same dispatch (``ValueError``),
        and an instance produced in ANY earlier dispatch — returned or
        destroyed by that dispatch's rollback alike — handed back again
        by a singleton-style factory (``ValueError``, via the weak
        identity ledger).
        """
        from ovui_widgets.property.widget.property_widget import PropertyWidget

        if not isinstance(widget, PropertyWidget):
            raise TypeError(
                f"PropertySchemeRegistry: factory for widget {name!r} "
                f"returned {widget!r} instead of a fresh PropertyWidget "
                "instance"
            )
        if any(existing is widget for existing in transaction):
            raise ValueError(
                f"PropertySchemeRegistry: factory for widget {name!r} "
                "returned an instance already produced by another factory "
                "in this dispatch; factories must return unshared widgets"
            )
        if self._issued_widgets.get(id(widget)) is widget:
            raise ValueError(
                f"PropertySchemeRegistry: factory for widget {name!r} "
                "returned an instance it already issued in an earlier "
                "dispatch (possibly destroyed by that dispatch's "
                "rollback); factories must construct a fresh widget per "
                "call"
            )

    def _collect_delegate_names(
        self,
        scheme: str,
        payload: "PropertyPayload",
    ) -> Tuple[Set[str], Set[str]]:
        """Union delegate :meth:`get_widgets` / :meth:`get_unwanted_widgets`.

        Delegates registered under ``"default"`` are consulted for
        every scheme (mirroring how ``"default"`` widgets surface
        universally); delegates registered under ``scheme`` are
        consulted on top. Returns ``(wanted, unwanted)`` as sets of
        widget names — empty when no delegates exist for either
        scheme so the caller's filter becomes a no-op.
        """
        wanted: Set[str] = set()
        unwanted: Set[str] = set()
        delegate_entries: List[_DelegateEntry] = list(
            self._delegates.get(_DEFAULT_SCHEME, [])
        )
        if scheme != _DEFAULT_SCHEME:
            delegate_entries.extend(self._delegates.get(scheme, []))
        for entry in delegate_entries:
            wanted.update(entry.delegate.get_widgets(payload))
            unwanted.update(entry.delegate.get_unwanted_widgets(payload))
        return wanted, unwanted

    # ------------------------------------------------------------------
    # Authoritative inspection/removal
    #
    # Registration owners that must recover from failed handle
    # cancellation (or a registration that mutated the registry before
    # its handle could be returned) need a way to verify and clean the
    # actual registry state. Recovery must use the atomic
    # ``remove_*_if_matches`` operations: ownership comparison (exact
    # object identity of the registered factory/delegate) and removal
    # happen in one registry call with no reentrant gap, so stale
    # cleanup can never remove an independently installed replacement —
    # not even one of the same class. A split ``find_*`` +
    # key-only ``remove_*`` sequence cannot make that guarantee and the
    # key-only removers exist for administrative use only.
    # ------------------------------------------------------------------

    def find_widget(
        self, scheme: str, name: str
    ) -> Optional[Callable[[], "PropertyWidget"]]:
        """Return the registered factory for ``(scheme, name)``, or ``None``."""
        for entry in self._widgets.get(scheme, []):
            if entry.name == name:
                return entry.factory
        return None

    def find_scheme_delegate(
        self, scheme: str, name: str
    ) -> Optional["PropertySchemeDelegate"]:
        """Return the registered delegate for ``(scheme, name)``, or ``None``."""
        for entry in self._delegates.get(scheme, []):
            if entry.name == name:
                return entry.delegate
        return None

    def remove_widget_if_matches(
        self,
        scheme: str,
        name: str,
        expected_factory: Callable[[], "PropertyWidget"],
    ) -> bool:
        """Atomically remove ``(scheme, name)`` iff ``expected_factory`` owns it.

        Returns ``True`` only when the registered entry's factory *is*
        ``expected_factory`` (object identity) and it was removed. This
        is the recovery operation for owners whose handle cancellation
        failed or whose registration mutated the registry before its
        handle was returned. PRECONDITION: the caller must register a
        unique factory object per registration generation (as
        ``_SchemeRegistration``-style owners do) — object identity
        cannot distinguish generations when the same callable is
        removed and re-registered, so reused objects would make a stale
        recovery remove the newer generation. Handle cancellation does
        not have this caveat: handles bind to the entry record itself.
        """
        entries = self._widgets.get(scheme, [])
        for entry in entries:
            if entry.name == name:
                if entry.factory is not expected_factory:
                    return False
                self._widgets[scheme] = [e for e in entries if e is not entry]
                return True
        return False

    def remove_delegate_if_matches(
        self,
        scheme: str,
        name: str,
        expected_delegate: "PropertySchemeDelegate",
    ) -> bool:
        """Atomically remove the delegate iff ``expected_delegate`` owns it.

        Object-identity counterpart of :meth:`remove_widget_if_matches`
        for delegate entries.
        """
        entries = self._delegates.get(scheme, [])
        for entry in entries:
            if entry.name == name:
                if entry.delegate is not expected_delegate:
                    return False
                self._delegates[scheme] = [e for e in entries if e is not entry]
                return True
        return False

    def remove_widget(self, scheme: str, name: str) -> bool:
        """Remove the widget entry for ``(scheme, name)`` by key alone.

        Administrative operation: it asserts no ownership, so recovery
        paths must use :meth:`remove_widget_if_matches` instead — a
        key-only removal after a separate ownership check can delete a
        replacement installed between the two calls.
        """
        entries = self._widgets.get(scheme, [])
        if not any(entry.name == name for entry in entries):
            return False
        self._widgets[scheme] = [entry for entry in entries if entry.name != name]
        return True

    def remove_scheme_delegate(self, scheme: str, name: str) -> bool:
        """Remove the delegate entry for ``(scheme, name)`` by key alone.

        Administrative counterpart of :meth:`remove_widget`; recovery
        paths must use :meth:`remove_delegate_if_matches`.
        """
        entries = self._delegates.get(scheme, [])
        if not any(entry.name == name for entry in entries):
            return False
        self._delegates[scheme] = [entry for entry in entries if entry.name != name]
        return True

    # ------------------------------------------------------------------
    # Generation-conditional removal — only called from the
    # subscription handles. The entry record IS the registration
    # generation: re-registering the same factory/delegate object under
    # the same key creates a new record, so a stale handle's removal
    # no-ops instead of dropping the new generation.
    # ------------------------------------------------------------------

    def _remove_widget_entry(self, scheme: str, entry: _WidgetEntry) -> bool:
        entries = self._widgets.get(scheme, [])
        if not any(existing is entry for existing in entries):
            return False
        self._widgets[scheme] = [e for e in entries if e is not entry]
        return True

    def _remove_delegate_entry(self, scheme: str, entry: _DelegateEntry) -> bool:
        entries = self._delegates.get(scheme, [])
        if not any(existing is entry for existing in entries):
            return False
        self._delegates[scheme] = [e for e in entries if e is not entry]
        return True

    # ------------------------------------------------------------------
    # Administrative internals — key-only removal for tests/tooling.
    # Subscription handles do NOT route through these; they use the
    # generation-conditional removal above so a stale cancel can never
    # drop a same-key replacement.
    # ------------------------------------------------------------------

    def _unregister_widget(self, scheme: str, name: str) -> None:
        entries = self._widgets.get(scheme)
        if not entries:
            return
        self._widgets[scheme] = [e for e in entries if e.name != name]

    def _unregister_delegate(self, scheme: str, name: str) -> None:
        entries = self._delegates.get(scheme)
        if not entries:
            return
        self._delegates[scheme] = [e for e in entries if e.name != name]


# ---------------------------------------------------------------------------
# Default registrations
# ---------------------------------------------------------------------------


def _register_defaults(registry: "PropertySchemeRegistry") -> None:
    """Register the built-in ``"default"`` → :class:`AttributesWidget` mapping.

    The :class:`AttributesWidget` import is local rather than at module
    top so ``scheme_registry.py`` stays importable without pulling in
    the concrete widget class hierarchy
    (``attributes_widget`` → ``simple_property_widget`` →
    ``property_widget``). That matters in two places: tests that want
    to exercise just the registry machinery (and monkey-patch the
    defaults before they land), and any future callers that depend on
    the registry's API but ship their own widgets. Deferring the
    import to first :meth:`instance` call also keeps module-load
    ordering insensitive to how callers enter the subpackage.

    :class:`AttributesWidget` is registered with ``order=100`` (the
    default "middle of the stack" slot) and ``top_stack=False``.
    Third-party schema widgets that want to stack above or below the
    catch-all pick an ``order`` below 100 or above 100 respectively;
    ties are broken by ``top_stack`` then registration order.
    """
    from ovui_widgets.property.widget.attributes_widget import AttributesWidget

    registry.register_widget(
        _DEFAULT_SCHEME, "attributes", AttributesWidget
    )

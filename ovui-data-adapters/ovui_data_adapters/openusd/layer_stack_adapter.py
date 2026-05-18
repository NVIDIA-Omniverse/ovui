# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Concrete :class:`LayerStackAdapter` backed by ``pxr.Usd``.

LAYERS-PLAN Step 4 landed the **read-only half** (queries + silent
subscription channel). LAYERS-PLAN Step 5 wires the Tf/Sdf notice
handlers, batched flush, per-identifier dedup, and dirty-poll safety
net on top of that. Mutation methods (add/remove sublayer, set
mute/lock, save, reload, …) landed in Step 6.

Constraint G2 (Kit-free import rule) — Kit-free: imports only stdlib, ``pxr``, and
:mod:`ovui_data_adapters.common` for the abstract contracts
(``LayerStackAdapter`` ABC, ``SubscriptionProtocol``,
``UndoManagerProtocol``). Step 15 of the data-adapters plan completed
the dependency-direction invariant: the file no longer imports
``ovwidgets.common.settings.Subscription``,
``ovwidgets.common.undo.UndoManager``, ``ErrorReporter``, or the
``ovwidgets.common.scheduler`` — these are replaced by the private
:class:`_LayerStackSubscription`, :class:`UndoManagerProtocol`, stdlib
``logging``, and a synchronous flush fallback respectively. No
``omni.kit.*``, ``omni.usd.UsdContext``, or ``carb.*`` touches anywhere
in this file.

:class:`Sdf.Layer` references never leak across the adapter boundary. The
adapter keeps them in a private :attr:`_sdf_layers` dict keyed by identifier;
:class:`LayerHandle` instances carry only the public ``identifier`` string.
"""

from __future__ import annotations

import logging
import os
import threading
import weakref
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Set

from pxr import Sdf, Tf, Usd, UsdUtils

from ovui_data_adapters.common import (
    LayerEvent,
    LayerEventType,
    LayerHandle,
    LayerSnapshot,
    LayerStackAdapter,
    PrimSpecDescriptor,
    PrimSpecifier,
    SubscriptionProtocol,
    UndoManagerProtocol,
)


_LOGGER = logging.getLogger(__name__)


class _LayerStackSubscription:
    """Private subscription handle for ``UsdLayerStackAdapter.subscribe_events``.

    Step 15: replaces the prior dependency on
    ``ovwidgets.common.settings.Subscription`` so the moved openusd
    layer-stack adapter carries zero ``ovwidgets.*`` runtime imports.
    Structurally satisfies :class:`SubscriptionProtocol` from
    :mod:`ovui_data_adapters.common` — a no-arg ``cancel()`` method is
    the only required surface. Mirrors the ``_StageSubscription``
    pattern introduced in Step 13 for ``UsdStageAdapter``.
    """

    def __init__(
        self,
        owner_ref: "weakref.ref[Any]",
        key: str,
        callback: Callable,
    ) -> None:
        self._owner_ref = owner_ref
        self._key = key
        self._callback = callback
        self._cancelled = False

    def cancel(self) -> None:
        """Remove this subscriber from the owning adapter."""
        if self._cancelled:
            return
        self._cancelled = True
        owner = self._owner_ref()
        if owner is not None:
            owner._remove_subscriber(self._key, self._callback)

    def __del__(self) -> None:
        self.cancel()


_AUTO_AUTHORING_MARKER = "__DELTA_LAYER__"
"""Substring marker for Kit's auto-authoring delta layers.

Kit's auto-authoring system (see LAYERS-WINDOW-ARCHITECTURE §8) injects an
anonymous sublayer with ``__DELTA_LAYER__`` in its identifier. OvGear does not
create delta layers in v1, but third-party stages authored in Kit may carry
one — filter it out so it does not show in the Layers window.
"""

_ANONYMOUS_DISPLAY_NAME = "anonymous"
"""Display-name text for anonymous layers (no file path)."""

OVGEAR_LAYER_KEY = "ovgear_layer"
"""Top-level ``customLayerData`` namespace used by OvGear (writes always land here)."""

KIT_LAYER_KEY = "omni_layer"
"""Kit's equivalent namespace (LAYERS-ARCHITECTURE §7.6). Read-only fallback."""

AUTHORING_LAYER_KEY = "authoring_layer"
"""Sub-key under a layer namespace: identifier of the stage's edit target."""

LOCKED_KEY = "locked"
"""Sub-key under a layer namespace: ``{identifier: True}`` map of locked layers."""

_LOCK_NAMESPACES = (OVGEAR_LAYER_KEY, KIT_LAYER_KEY)
"""Custom-layer-data namespaces the adapter inspects for lock / edit-target state.

OvGear writes under :data:`OVGEAR_LAYER_KEY`. Stages saved by Kit use
:data:`KIT_LAYER_KEY`; reading both keeps locks and edit-target round-tripping
across applications (LAYERS-ARCHITECTURE §7.6 deliberate interop).
"""

_SUBLAYER_INFO_KEYS = frozenset({"subLayers", "subLayerOffsets"})
"""``Sdf.Notice.LayerInfoDidChange.key`` values that flag a sublayer edit.

Appending/removing a sublayer fires one notice per key (``subLayers`` plus
``subLayerOffsets``); either is enough to classify as SUBLAYERS_CHANGED.
"""

_TRACKED_INFO_KEYS = frozenset({
    "upAxis",
    "metersPerUnit",
    "startTimeCode",
    "endTimeCode",
    "framesPerSecond",
    "timeCodesPerSecond",
    "comment",
    "documentation",
})
"""Stage-level metadata fields whose change emits INFO_CHANGED.

Other ``LayerInfoDidChange`` keys (``customLayerData``, ``colorConfiguration``,
etc.) are currently ignored — add them here if the UI needs to react.
"""


# Classification tokens stored in ``_pending[identifier]``. Strings so the
# set remains small, hashable, and trivially serialisable in debug dumps.
#
# ``_TOKEN_SUBLAYERS`` / ``info:<field>`` classify the change precisely and
# emit the matching ``LayerEvent``. ``_TOKEN_TOUCHED`` is a marker that a
# layer was edited in some way — it *arms* the flush but does not itself
# emit an event; the dirty-poll inside the flush decides whether a real
# ``DIRTY_STATE_CHANGED`` event is warranted by diffing against the
# snapshot. This indirection covers the case where ``LayersDidChange``
# fires for an edit that doesn't flip dirtiness (e.g. the layer was
# already dirty), avoiding spurious ``DIRTY_STATE_CHANGED`` events.
_TOKEN_SUBLAYERS = "__sublayers__"
_TOKEN_TOUCHED = "__touched__"
_TOKEN_INFO_PREFIX = "info:"


_SPECIFIER_TO_PRIM_SPECIFIER: Dict[Any, PrimSpecifier] = {
    Sdf.SpecifierDef: PrimSpecifier.DEF,
    Sdf.SpecifierOver: PrimSpecifier.OVER,
    Sdf.SpecifierClass: PrimSpecifier.CLASS,
}
"""Map ``Sdf.Specifier`` values to the Kit-free :class:`PrimSpecifier`.

Uses a plain dict rather than a chain of ``if`` comparisons so the lookup
is O(1) and the mapping is obvious at a glance. Unknown values (a future
USD version adding a specifier) fall back to ``OVER`` at the call site —
the least-destructive choice for the UI.
"""


def _descriptor_from_prim_spec(spec: Any) -> PrimSpecDescriptor:
    """Project an ``Sdf.PrimSpec`` onto the Kit-free :class:`PrimSpecDescriptor`.

    ``has_reference`` / ``has_payload`` use ``HasInfo`` with the well-known
    string keys (``"references"`` / ``"payload"``) rather than the
    ``hasReferences`` / ``hasPayloads`` attributes — those only reflect the
    explicit list, while ``HasInfo`` also returns ``True`` for
    prepended / appended items authored on the spec.
    """
    return PrimSpecDescriptor(
        path=str(spec.path),
        type_name=spec.typeName or "",
        specifier=_SPECIFIER_TO_PRIM_SPECIFIER.get(
            spec.specifier, PrimSpecifier.OVER
        ),
        has_reference=bool(spec.HasInfo("references")),
        has_payload=bool(spec.HasInfo("payload")),
        is_instanceable=bool(spec.instanceable),
    )


def _extract_key(notice: Any) -> Optional[str]:
    """Return the string key of a ``LayerInfoDidChange`` notice.

    In the current pxr Python bindings ``notice.key`` is a bound method;
    older / hypothetical bindings expose it as a plain attribute. Handle
    both so the adapter stays portable across USD builds.
    """
    key = getattr(notice, "key", None)
    if callable(key):
        try:
            key = key()
        except TypeError:
            return None
    return key if isinstance(key, str) else None


class UsdLayerStackAdapter(LayerStackAdapter):
    """USD-backed :class:`LayerStackAdapter` over one ``Usd.Stage``.

    One adapter wraps exactly one stage. Construction snapshots the current
    layer set and lock map; callers must re-create the adapter if the backing
    stage is swapped (which is the Kit pattern — one ``Layers`` instance per
    ``UsdContext``).

    Subscription is wired but silent until Step 5 registers Tf/Sdf notices.
    """

    def __init__(self, stage: Usd.Stage, undo: UndoManagerProtocol) -> None:
        self._stage = stage
        self._undo = undo

        # Subscribers list first — initialise before anything that might
        # (in future steps) emit an event synchronously during construction.
        # Shape matches SelectionBus / MockLayerStack so ``Subscription.
        # cancel`` routes through the same ``_remove_subscriber`` hook.
        self._subscribers: List[Callable[[LayerEvent], None]] = []

        # Handle cache: identifier → LayerHandle. Handles are immutable and
        # interchangeable across calls, but we cache them so ``==`` and
        # ``is`` both behave consistently for the UI's item models.
        self._layer_cache: Dict[str, LayerHandle] = {}

        # Private ``Sdf.Layer`` store. Never exposed. Holding strong refs
        # here mirrors the stage's own composition arcs and keeps Sdf.Find
        # lookups stable for the adapter's lifetime.
        self._sdf_layers: Dict[str, Sdf.Layer] = {}

        # Lock-state map: identifier → locked. Initialised from the root
        # layer's customLayerData (``locked`` dict under ``ovgear_layer`` /
        # ``omni_layer``). Mutators write back via :meth:`_persist_lock_map`.
        self._lock_map: Dict[str, bool] = self._restore_lock_map()

        # Guard flag: when ``True``, notice handlers treat root-layer
        # dirtiness / info changes as self-inflicted (writes to
        # ``customLayerData``) and skip the enqueue. The post-write
        # ``_dirty_snapshot`` refresh handles the deferred dirty-poll.
        # See LAYERS-PLAN Step 7 for the full rationale.
        self._persisting: bool = False

        # Prime the handle cache with the well-known root / session layers
        # so downstream ``find_layer`` / sublayer walks never have to
        # round-trip through ``Sdf.Layer.Find`` for these. ``Usd.Stage``
        # always has a root layer; session layer is optional when the
        # stage was opened with ``LoadNone`` or similar — guard only that.
        self._register(stage.GetRootLayer())
        session = stage.GetSessionLayer()
        if session is not None:
            self._register(session)

        # ── Step 5: notice batching state (inactive until attach_stage) ──
        # All three dicts/flags plus ``_destroyed`` are guarded by
        # ``_pending_lock``. The handlers run on whatever thread USD fires
        # them from (main during normal edits, worker during ``Stage.Open``
        # or async asset resolution), so every touch of these fields must
        # hold the lock. ``_dirty_snapshot`` is main-thread-only (only the
        # flush reads/writes it).
        self._pending_lock = threading.Lock()
        self._pending: Dict[str, Set[str]] = defaultdict(set)
        self._pending_edit_target_change = False
        self._flush_scheduled = False
        self._flush_handle: Any = None
        self._notice_keys: List[Any] = []
        self._dirty_snapshot: Dict[str, bool] = {}
        self._destroyed = True  # attach_stage flips to False.
        self._call_later: Optional[Callable[[float, Callable], Any]] = None

        # Restore the persisted edit target (if any) from customLayerData.
        # Must happen after ``_register(root)`` has primed the cache but
        # before any caller can query ``get_edit_target_identifier``. No
        # subscribers can be attached yet, so the ``StageEditTargetChanged``
        # notice fired by ``SetEditTarget`` is harmless — attach_stage
        # hasn't registered its handler.
        self._restore_authoring_layer()

    # ── Internal helpers ─────────────────────────────────────────────

    def _register(self, sdf_layer: Sdf.Layer) -> LayerHandle:
        """Intern ``sdf_layer`` in both caches and return its handle."""
        identifier = sdf_layer.identifier
        handle = self._layer_cache.get(identifier)
        if handle is None:
            handle = LayerHandle(identifier=identifier)
            self._layer_cache[identifier] = handle
        # Always refresh the Sdf ref — ``Sdf.Layer.Find`` may return a
        # different Python wrapper around the same C++ layer after reload.
        self._sdf_layers[identifier] = sdf_layer
        return handle

    def _sdf_for(self, layer: LayerHandle) -> Optional[Sdf.Layer]:
        """Return the backing ``Sdf.Layer`` for ``layer`` or ``None``.

        Falls back to ``Sdf.Layer.Find`` when the cache misses (e.g. the
        handle was minted from an identifier that has since been loaded
        from disk). Returns ``None`` if the layer cannot be resolved —
        which :meth:`is_missing` treats as the "missing" sentinel.
        """
        sdf = self._sdf_layers.get(layer.identifier)
        if sdf is not None:
            return sdf
        found = Sdf.Layer.Find(layer.identifier)
        if found is not None:
            self._sdf_layers[layer.identifier] = found
        return found

    def _restore_lock_map(self) -> Dict[str, bool]:
        """Read the lock-state snapshot from the root layer's customLayerData.

        LAYERS-PLAN Step 7 names: reads :data:`OVGEAR_LAYER_KEY` first, then
        falls back to :data:`KIT_LAYER_KEY` so stages last saved by Kit still
        round-trip their locks. The legacy boolean form (single "root is
        locked" flag, from Step 6's schema) is also accepted — same shape,
        different value type.

        Only ``locked=True`` entries are materialised; cleared locks are
        dropped so :meth:`is_locked` can short-circuit on a missing key.
        Writes always go through :meth:`_persist_lock_map` / :meth:`_write_custom_data`
        under :data:`OVGEAR_LAYER_KEY` — never under :data:`KIT_LAYER_KEY`.
        """
        root = self._stage.GetRootLayer()
        custom = root.customLayerData or {}
        for namespace in _LOCK_NAMESPACES:
            ns = custom.get(namespace)
            if not isinstance(ns, dict):
                continue
            locked_value = ns.get(LOCKED_KEY)
            if isinstance(locked_value, dict):
                return {
                    identifier: True
                    for identifier, locked in locked_value.items()
                    if isinstance(identifier, str)
                    and isinstance(locked, bool)
                    and locked
                }
            if isinstance(locked_value, bool):
                return {root.identifier: True} if locked_value else {}
        return {}

    def _restore_authoring_layer(self) -> None:
        """Apply a persisted edit-target choice from root-layer customLayerData.

        Reads :data:`AUTHORING_LAYER_KEY` under :data:`OVGEAR_LAYER_KEY` first,
        falling back to :data:`KIT_LAYER_KEY` for Kit-authored stages. When a
        valid identifier is found **and** its ``Sdf.Layer`` is resident, the
        stage's edit target is reset to it via ``GetEditTargetForLocalLayer``.
        Silent no-op when the key is missing, ill-typed, or names a layer that
        is no longer part of the stack (e.g. the sublayer was removed since
        last save).
        """
        root = self._stage.GetRootLayer()
        custom = root.customLayerData or {}
        stored: Optional[str] = None
        for namespace in _LOCK_NAMESPACES:
            ns = custom.get(namespace)
            if not isinstance(ns, dict):
                continue
            candidate = ns.get(AUTHORING_LAYER_KEY)
            if isinstance(candidate, str) and candidate:
                stored = candidate
                break
        if stored is None:
            return
        sdf_layer = Sdf.Layer.Find(stored)
        if sdf_layer is None:
            # Sublayer removed since last save — leave the stage's default
            # edit target (root) in place. The stale key is harmless; a
            # future persist call will either refresh or leave it untouched.
            return
        try:
            self._stage.SetEditTarget(
                self._stage.GetEditTargetForLocalLayer(sdf_layer)
            )
        except Tf.ErrorException:
            # ``GetEditTargetForLocalLayer`` rejects layers that aren't
            # part of the local layer stack. Treat as "persisted identifier
            # is no longer valid" and leave root as the edit target.
            return

    def _is_auto_authoring_delta(self, identifier: str) -> bool:
        """``True`` iff ``identifier`` names an auto-authoring delta layer."""
        return identifier.startswith("anon:") and _AUTO_AUTHORING_MARKER in identifier

    # ── Stack discovery ──────────────────────────────────────────────

    def get_root_layer(self) -> LayerHandle:
        return self._register(self._stage.GetRootLayer())

    def get_session_layer(self) -> Optional[LayerHandle]:
        session = self._stage.GetSessionLayer()
        if session is None:
            return None
        return self._register(session)

    def get_sublayer_identifiers(self, parent: LayerHandle) -> List[str]:
        sdf = self._sdf_for(parent)
        if sdf is None:
            return []
        result: List[str] = []
        for rel in sdf.subLayerPaths:
            absolute = sdf.ComputeAbsolutePath(rel)
            if self._is_auto_authoring_delta(absolute):
                continue
            result.append(absolute)
            # Opportunistically register the child so subsequent queries
            # against this identifier (``find_layer``, ``is_dirty``, …)
            # short-circuit without going back through ``Sdf.Layer.Find``.
            if absolute not in self._sdf_layers:
                child = Sdf.Layer.Find(absolute)
                if child is not None:
                    self._register(child)
        return result

    def find_layer(self, identifier: str) -> Optional[LayerHandle]:
        if identifier in self._layer_cache:
            return self._layer_cache[identifier]
        sdf = Sdf.Layer.Find(identifier)
        if sdf is None:
            return None
        return self._register(sdf)

    def get_layer_stack_identifiers(
        self,
        include_session: bool = False,
        include_anonymous: bool = True,
    ) -> List[str]:
        result: List[str] = []
        visited: set[str] = set()

        if include_session:
            session = self._stage.GetSessionLayer()
            if session is not None:
                visited.add(session.identifier)
                if include_anonymous or not session.anonymous:
                    result.append(session.identifier)

        self._walk(
            self._stage.GetRootLayer(), include_anonymous, result, visited
        )
        return result

    def _walk(
        self,
        sdf_layer: Optional[Sdf.Layer],
        include_anonymous: bool,
        result: List[str],
        visited: set,
    ) -> None:
        if sdf_layer is None or sdf_layer.identifier in visited:
            return
        visited.add(sdf_layer.identifier)
        if include_anonymous or not sdf_layer.anonymous:
            result.append(sdf_layer.identifier)
        for rel in sdf_layer.subLayerPaths:
            absolute = sdf_layer.ComputeAbsolutePath(rel)
            if self._is_auto_authoring_delta(absolute):
                continue
            child = Sdf.Layer.Find(absolute)
            if child is None:
                # Missing sublayer: surface the identifier once so the UI
                # can render a missing-row, but do not recurse.
                if absolute not in visited:
                    visited.add(absolute)
                    is_anon = absolute.startswith("anon:")
                    if include_anonymous or not is_anon:
                        result.append(absolute)
                continue
            self._walk(child, include_anonymous, result, visited)

    # ── Display ──────────────────────────────────────────────────────

    def get_display_name(self, layer: LayerHandle) -> str:
        sdf = self._sdf_for(layer)
        if sdf is None:
            # Missing layer — fall back to the basename of the identifier
            # so the UI has something to show.
            return os.path.basename(layer.identifier) or layer.identifier
        if sdf.anonymous:
            return _ANONYMOUS_DISPLAY_NAME
        name = Sdf.Layer.GetDisplayNameFromIdentifier(sdf.identifier)
        if name:
            return name
        return os.path.basename(sdf.identifier) or sdf.identifier

    def get_layer_owner(self, layer: LayerHandle) -> str:
        sdf = self._sdf_for(layer)
        if sdf is None or sdf.anonymous:
            return ""
        real_path = sdf.realPath
        if not real_path or not os.path.exists(real_path):
            return ""
        try:
            uid = os.stat(real_path).st_uid
        except OSError:
            return ""
        try:
            import pwd  # POSIX-only; guarded for headless-Windows test runs.

            return pwd.getpwuid(uid).pw_name
        except (ImportError, KeyError):
            return str(uid)

    # ── State flags ──────────────────────────────────────────────────

    def is_anonymous(self, layer: LayerHandle) -> bool:
        sdf = self._sdf_for(layer)
        if sdf is None:
            return False
        return bool(sdf.anonymous)

    def is_dirty(self, layer: LayerHandle) -> bool:
        sdf = self._sdf_for(layer)
        if sdf is None:
            return False
        return bool(sdf.dirty)

    def is_muted(self, layer: LayerHandle) -> bool:
        return bool(self._stage.IsLayerMuted(layer.identifier))

    def is_locked(self, layer: LayerHandle) -> bool:
        return self._lock_map.get(layer.identifier, False)

    def is_read_only_on_disk(self, layer: LayerHandle) -> bool:
        sdf = self._sdf_for(layer)
        if sdf is None or sdf.anonymous:
            return False
        real_path = sdf.realPath
        if not real_path or not os.path.exists(real_path):
            return False
        return not os.access(real_path, os.W_OK)

    def is_missing(self, layer: LayerHandle) -> bool:
        return self._sdf_for(layer) is None

    # ── Edit target ──────────────────────────────────────────────────

    def get_edit_target_identifier(self) -> str:
        return self._stage.GetEditTarget().GetLayer().identifier

    # ── Change subscription ──────────────────────────────────────────

    def subscribe_events(
        self,
        callback: Callable[[LayerEvent], None],
    ) -> SubscriptionProtocol:
        self._subscribers.append(callback)
        return _LayerStackSubscription(weakref.ref(self), "events", callback)

    def _remove_subscriber(self, key: str, callback: Callable) -> None:
        # ``key`` is part of the SubscriptionProtocol cancel contract; unused
        # here because this adapter has a single channel.
        del key
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    # ── Mutations (Step 6) ───────────────────────────────────────────
    #
    # Commands in Phase F wrap these with undo/redo logic. The adapter
    # itself never pushes to ``UndoManager`` — the ``self._undo`` field
    # is held for future command wiring but unused here.
    #
    # Event emission strategy:
    # * ``set_edit_target`` — ``stage.SetEditTarget`` fires
    #   ``Usd.Notice.StageEditTargetChanged``, which the existing
    #   :meth:`_on_edit_target_changed` handler converts into an
    #   ``EDIT_TARGET_CHANGED`` event on the next flush. The mutator
    #   does NOT emit synchronously (would double-fire).
    # * ``set_mute`` — ``stage.MuteLayer`` does NOT fire a useful Sdf
    #   notice. Mutator emits ``MUTE_STATE_CHANGED`` synchronously via
    #   :meth:`_dispatch`.
    # * ``set_lock`` — purely Kit-level; USD never fires for it.
    #   Mutator emits ``LOCK_STATE_CHANGED`` synchronously.
    # * Sublayer mutations — ``layer.subLayerPaths`` changes fire
    #   ``LayerInfoDidChange(key="subLayers")``, which the existing
    #   handler converts into ``SUBLAYERS_CHANGED`` on the next flush.
    # * ``save_layer`` / ``reload_layer`` — clearing the dirty bit fires
    #   ``LayerDirtinessChanged`` and is picked up by the dirty-poll
    #   on the next flush.

    def set_edit_target(self, identifier: str) -> None:
        sdf_layer = self._resolve_identifier(identifier)
        if sdf_layer is None:
            raise KeyError(f"Unknown layer identifier: {identifier!r}")
        self._stage.SetEditTarget(
            self._stage.GetEditTargetForLocalLayer(sdf_layer)
        )

    def set_mute(self, identifier: str, muted: bool) -> None:
        already = bool(self._stage.IsLayerMuted(identifier))
        if already == muted:
            return
        if muted:
            self._stage.MuteLayer(identifier)
        else:
            self._stage.UnmuteLayer(identifier)
        # USD's mute/unmute fires ObjectsChanged but not a notice we
        # classify as MUTE_STATE_CHANGED — emit synchronously.
        self._dispatch(LayerEvent(
            event_type=LayerEventType.MUTE_STATE_CHANGED,
            identifiers=(identifier,),
        ))

    def set_lock(self, identifier: str, locked: bool) -> None:
        current = self._lock_map.get(identifier, False)
        if current == locked:
            return
        if locked:
            self._lock_map[identifier] = True
        else:
            self._lock_map.pop(identifier, None)
        self._persist_lock_map()
        self._dispatch(LayerEvent(
            event_type=LayerEventType.LOCK_STATE_CHANGED,
            identifiers=(identifier,),
        ))

    def create_sublayer(
        self,
        parent_id: str,
        position: int,
        new_layer_path: str,
        transfer_root_content: bool = False,
    ) -> str:
        parent = self._require_sdf(parent_id)
        if new_layer_path == "":
            new_layer = Sdf.Layer.CreateAnonymous()
        else:
            # ``CreateNew`` throws if the target path already exists on
            # disk. Guard with ``Find``: if any layer with that identifier
            # is already resident, surface a ``ValueError`` rather than a
            # confusing ``Tf.ErrorException``.
            if Sdf.Layer.Find(new_layer_path) is not None:
                raise ValueError(
                    f"Layer already exists with identifier: {new_layer_path!r}"
                )
            new_layer = Sdf.Layer.CreateNew(new_layer_path)
            if new_layer is None:
                raise RuntimeError(
                    f"Sdf.Layer.CreateNew returned None for path: "
                    f"{new_layer_path!r}"
                )
        self._register(new_layer)

        identifier = new_layer.identifier
        insert_path = identifier if new_layer.anonymous else new_layer_path
        if position < 0 or position > len(parent.subLayerPaths):
            parent.subLayerPaths.append(insert_path)
        else:
            parent.subLayerPaths.insert(position, insert_path)

        if transfer_root_content:
            self._transfer_root_content_to(new_layer)
        return identifier

    def insert_sublayer(
        self,
        parent_id: str,
        position: int,
        sublayer_path: str,
    ) -> None:
        parent = self._require_sdf(parent_id)
        if position < 0 or position > len(parent.subLayerPaths):
            parent.subLayerPaths.append(sublayer_path)
        else:
            parent.subLayerPaths.insert(position, sublayer_path)
        # Opportunistically register the child if it resolves now; it may
        # stay unresolved (missing file), in which case it surfaces via
        # ``is_missing`` without a crash.
        child = Sdf.Layer.FindOrOpen(sublayer_path)
        if child is not None:
            self._register(child)

    def remove_sublayer(self, parent_id: str, position: int) -> str:
        parent = self._require_sdf(parent_id)
        if position < 0 or position >= len(parent.subLayerPaths):
            raise IndexError(
                f"sublayer position {position} out of range for {parent_id!r}"
            )
        raw = parent.subLayerPaths[position]
        identifier = parent.ComputeAbsolutePath(raw)
        del parent.subLayerPaths[position]
        # Deliberately leave ``_sdf_layers[identifier]`` intact — the
        # removed layer may still be referenced from another parent or
        # re-inserted by undo. Dropping it here would force a fresh
        # ``Sdf.Layer.Find`` on every undo and lose the strong ref that
        # keeps anonymous layers alive.
        return identifier

    def move_sublayer(
        self,
        from_parent_id: str,
        from_position: int,
        to_parent_id: str,
        to_position: int,
        remove_source: bool = True,
    ) -> None:
        # v1 caveat: the raw path string is transferred as-is — a relative
        # entry under the source parent stays relative to *that* parent
        # under the destination, which resolves incorrectly when the two
        # parents have different base paths. Commands in Phase F can
        # normalise via ``ComputeAbsolutePath`` before calling; the
        # adapter stays deliberately dumb so the copy-reference
        # (``remove_source=False``) variant round-trips without loss.
        source = self._require_sdf(from_parent_id)
        destination = self._require_sdf(to_parent_id)
        if from_position < 0 or from_position >= len(source.subLayerPaths):
            raise IndexError(
                f"sublayer position {from_position} out of range for "
                f"{from_parent_id!r}"
            )
        path = source.subLayerPaths[from_position]

        if remove_source:
            del source.subLayerPaths[from_position]
            # Same-parent reorder: the delete shifted indices, so an
            # insert at a later slot must be adjusted down by one.
            if source is destination and to_position > from_position:
                to_position -= 1

        if to_position < 0 or to_position > len(destination.subLayerPaths):
            destination.subLayerPaths.append(path)
        else:
            destination.subLayerPaths.insert(to_position, path)

    def replace_sublayer(
        self,
        parent_id: str,
        position: int,
        new_identifier: str,
    ) -> str:
        parent = self._require_sdf(parent_id)
        if position < 0 or position >= len(parent.subLayerPaths):
            raise IndexError(
                f"sublayer position {position} out of range for {parent_id!r}"
            )
        raw_old = parent.subLayerPaths[position]
        old_identifier = parent.ComputeAbsolutePath(raw_old)
        # Single assignment — the ListProxy fires one
        # ``LayerInfoDidChange(key="subLayers")`` notice, which becomes
        # exactly one SUBLAYERS_CHANGED event on the next flush. A
        # naive ``del`` + ``insert`` would dispatch twice.
        parent.subLayerPaths[position] = new_identifier
        child = Sdf.Layer.FindOrOpen(new_identifier)
        if child is not None:
            self._register(child)
        return old_identifier

    # ── Merge / Flatten support (Step 42) ────────────────────────────

    def _find_parent_identifier_of(
        self, identifier: str
    ) -> Optional[str]:
        """Return the identifier of the first parent that sublayers ``identifier``.

        Walks every cached layer's ``subLayerPaths`` (resolved to
        absolute identifiers) and returns the first parent that
        references ``identifier``. Returns ``None`` when the layer is
        not referenced from any cached parent (top-level / session /
        detached).
        """
        for parent_id, parent_sdf in self._sdf_layers.items():
            for rel in parent_sdf.subLayerPaths:
                if parent_sdf.ComputeAbsolutePath(rel) == identifier:
                    return parent_id
        return None

    def snapshot_layer(self, identifier: str) -> LayerSnapshot:
        layer = self._require_sdf(identifier)
        parent_id = self._find_parent_identifier_of(identifier)
        position = -1
        if parent_id is not None:
            parent_sdf = self._sdf_layers[parent_id]
            for idx, rel in enumerate(parent_sdf.subLayerPaths):
                if parent_sdf.ComputeAbsolutePath(rel) == identifier:
                    position = idx
                    break
        # ``ExportToString`` returns the full USDA dump of the layer
        # — stage metadata, customLayerData, every prim spec, and the
        # ``subLayers`` list. ``ImportFromString`` on the restore path
        # rebuilds the layer bit-identically.
        content = layer.ExportToString()
        sublayers = tuple(
            layer.ComputeAbsolutePath(rel) for rel in layer.subLayerPaths
        )
        return LayerSnapshot(
            identifier=identifier,
            parent_identifier=parent_id,
            position_in_parent=position,
            was_edit_target=(
                identifier == self.get_edit_target_identifier()
            ),
            anonymous=bool(layer.anonymous),
            content=content,
            custom_layer_data=dict(layer.customLayerData or {}),
            mute_state=self.is_muted(LayerHandle(identifier)),
            lock_state=self.is_locked(LayerHandle(identifier)),
            sublayer_identifiers=sublayers,
        )

    def restore_layer_from_snapshot(
        self, snapshot: LayerSnapshot
    ) -> str:
        # Build the restored layer first, then re-insert into parent.
        # Anonymous layers mint a fresh identifier on
        # ``Sdf.Layer.CreateAnonymous`` — the new id must be returned to
        # the caller so it can update its internal references.
        if snapshot.anonymous:
            restored = Sdf.Layer.CreateAnonymous(".usda")
            restored.ImportFromString(snapshot.content)
            identifier = restored.identifier
        else:
            existing = Sdf.Layer.Find(snapshot.identifier)
            if existing is not None:
                restored = existing
                restored.ImportFromString(snapshot.content)
            else:
                # File was removed from disk during the merge. Try to
                # reopen the on-disk copy first; if that fails, recreate
                # by importing the USDA blob into a fresh anonymous
                # layer keyed at the original path (``FindOrOpen``
                # creates on miss for supported paths).
                restored = Sdf.Layer.FindOrOpen(snapshot.identifier)
                if restored is None:
                    restored = Sdf.Layer.CreateNew(snapshot.identifier)
                if restored is None:
                    raise RuntimeError(
                        f"Could not restore layer {snapshot.identifier!r} "
                        f"from snapshot"
                    )
                restored.ImportFromString(snapshot.content)
            identifier = snapshot.identifier

        self._register(restored)

        if snapshot.custom_layer_data:
            restored.customLayerData = dict(snapshot.custom_layer_data)

        if snapshot.parent_identifier is not None:
            parent_sdf = self._resolve_identifier(snapshot.parent_identifier)
            if parent_sdf is None:
                raise KeyError(
                    f"restore_layer_from_snapshot: parent "
                    f"{snapshot.parent_identifier!r} not found"
                )
            insert_path = (
                identifier if snapshot.anonymous else snapshot.identifier
            )
            # Skip re-insert when the layer is already referenced — the
            # destination half of a merge-down undo never unlinked the
            # layer; re-inserting would double-link it.
            already_linked = any(
                parent_sdf.ComputeAbsolutePath(rel) == identifier
                for rel in parent_sdf.subLayerPaths
            )
            if not already_linked:
                position = snapshot.position_in_parent
                if position < 0 or position > len(parent_sdf.subLayerPaths):
                    parent_sdf.subLayerPaths.append(insert_path)
                else:
                    parent_sdf.subLayerPaths.insert(position, insert_path)

        # Replay mute + lock bits.
        if snapshot.mute_state and not self.is_muted(LayerHandle(identifier)):
            self._stage.MuteLayer(identifier)
            self._dispatch(LayerEvent(
                event_type=LayerEventType.MUTE_STATE_CHANGED,
                identifiers=(identifier,),
            ))
        if snapshot.lock_state and not self._lock_map.get(identifier, False):
            self._lock_map[identifier] = True
            self._persist_lock_map()
            self._dispatch(LayerEvent(
                event_type=LayerEventType.LOCK_STATE_CHANGED,
                identifiers=(identifier,),
            ))

        if snapshot.was_edit_target:
            try:
                self._stage.SetEditTarget(
                    self._stage.GetEditTargetForLocalLayer(restored)
                )
            except Tf.ErrorException:
                # Layer is not part of the local stack yet (e.g. the
                # snapshot's parent was also restored in the same
                # undo frame but hasn't propagated yet). The base
                # command's state-restore pass re-runs edit-target
                # after ``undo_impl``; we leave it to that path.
                pass

        return identifier

    def transfer_layer_content(
        self, src_identifier: str, dst_identifier: str
    ) -> None:
        src = self._require_sdf(src_identifier)
        dst = self._require_sdf(dst_identifier)
        # Snapshot the source's prim-spec names so the iteration is not
        # invalidated by any side-effects of ``CopySpec`` (which
        # dispatches notices that can, via batched flush, race back
        # into layer-cache bookkeeping in a future iteration).
        names: List[str] = [spec.name for spec in src.rootPrims]
        for name in names:
            Sdf.CopySpec(src, f"/{name}", dst, f"/{name}")

    # ── Prim-spec mutation (Step 31a) ────────────────────────────────

    def export_prim_spec(self, layer_id: str, path: str) -> str:
        layer = self._require_sdf(layer_id)
        spec = layer.GetPrimAtPath(path)
        if spec is None:
            raise KeyError(
                f"layer {layer_id!r} has no prim spec at {path!r}"
            )
        # Round-trip through an anonymous holding layer. ``CopySpec``
        # preserves nested children + attributes; ``ExportToString``
        # serialises the whole thing as USDA so
        # :meth:`import_prim_spec` can rebuild it bit-identically.
        holder = Sdf.Layer.CreateAnonymous(".usda")
        Sdf.CreatePrimInLayer(holder, path)
        Sdf.CopySpec(layer, path, holder, path)
        return holder.ExportToString()

    def remove_prim_spec(self, layer_id: str, path: str) -> None:
        layer = self._require_sdf(layer_id)
        spec = layer.GetPrimAtPath(path)
        if spec is None:
            raise KeyError(
                f"layer {layer_id!r} has no prim spec at {path!r}"
            )
        parent_path = spec.path.GetParentPath()
        if parent_path == Sdf.Path.absoluteRootPath:
            parent_spec = layer.pseudoRoot
        else:
            parent_spec = layer.GetPrimAtPath(parent_path)
        if parent_spec is None:
            raise KeyError(
                f"layer {layer_id!r}: parent {parent_path} missing for {path!r}"
            )
        # ``SdfPrimSpecView.__delitem__`` expects the leaf name, not
        # the full Sdf.Path (mirrors ``_transfer_root_content_to``'s
        # ``del root.rootPrims[name]`` pattern). The subsequent
        # ``LayersDidChange`` notice fires DIRTY_STATE_CHANGED naturally.
        del parent_spec.nameChildren[spec.name]

    def import_prim_spec(self, layer_id: str, path: str, usda: str) -> None:
        layer = self._require_sdf(layer_id)
        holder = Sdf.Layer.CreateAnonymous(".usda")
        holder.ImportFromString(usda)
        # ``CreatePrimInLayer`` is idempotent and walks the path,
        # creating any missing intermediate specs so ``CopySpec`` has
        # a receiver. Without this the copy raises when ``path`` is
        # nested below a prim that was itself removed earlier in the
        # command batch.
        Sdf.CreatePrimInLayer(layer, path)
        Sdf.CopySpec(holder, path, layer, path)

    # ── Prim-spec discovery (Step 47) ────────────────────────────────

    def get_prim_specs(
        self, layer_identifier: str, parent_path: str = "/"
    ) -> List[PrimSpecDescriptor]:
        layer = self._require_sdf(layer_identifier)
        if parent_path == "/":
            children = list(layer.rootPrims)
        else:
            parent_spec = layer.GetPrimAtPath(parent_path)
            if parent_spec is None:
                raise KeyError(
                    f"layer {layer_identifier!r} has no prim spec at "
                    f"{parent_path!r}"
                )
            children = list(parent_spec.nameChildren)
        return [_descriptor_from_prim_spec(spec) for spec in children]

    def has_prim_spec(self, layer_identifier: str, spec_path: str) -> bool:
        layer = self._require_sdf(layer_identifier)
        # ``/`` maps to the pseudo-root, which is always present on a
        # valid layer. Treat the root as "has a spec" so callers that
        # check existence before walking children get a truthful answer
        # without extra special-casing.
        if spec_path == "/":
            return True
        return layer.GetPrimAtPath(spec_path) is not None

    # ── File I/O ─────────────────────────────────────────────────────

    def save_layer(self, identifier: str) -> bool:
        sdf_layer = self._resolve_identifier(identifier)
        if sdf_layer is None or sdf_layer.anonymous:
            return False
        try:
            return bool(sdf_layer.Save())
        except Exception as exc:
            # ``Sdf.Layer.Save`` raises ``Tf.ErrorException`` when the
            # destination is read-only or the resolver refuses the write.
            # Log then return ``False`` — callers (commands) read the bool
            # and surface a user-facing error without crashing the frame.
            self._report_error("save_layer", identifier, exc)
            return False

    def save_layer_as(
        self,
        identifier: str,
        new_path: str,
        replace_in_parent: bool,
    ) -> Optional[str]:
        if not new_path:
            return None
        sdf_layer = self._resolve_identifier(identifier)
        if sdf_layer is None:
            return None
        try:
            ok = bool(sdf_layer.Export(new_path))
        except Exception as exc:
            self._report_error("save_layer_as", identifier, exc)
            return None
        if not ok:
            return None

        exported = Sdf.Layer.FindOrOpen(new_path)
        if exported is None:
            return None
        new_identifier = exported.identifier
        self._register(exported)

        if replace_in_parent:
            # Walk every resident parent and rewrite the sublayer entry.
            # Iterate by index rather than materialising the ListProxy —
            # ``list(parent.subLayerPaths)`` can fail under Boost.Python
            # after a fresh ``Export`` call, and we're mutating the proxy
            # in place anyway.
            # Subsequent ``LayerInfoDidChange`` notices emit the
            # SUBLAYERS_CHANGED events for each affected parent.
            for parent_id in list(self._sdf_layers):
                parent = Sdf.Layer.Find(parent_id)
                if parent is None:
                    continue
                for idx in range(len(parent.subLayerPaths)):
                    raw = parent.subLayerPaths[idx]
                    if parent.ComputeAbsolutePath(raw) == identifier:
                        parent.subLayerPaths[idx] = new_path
        return new_identifier

    def reload_layer(self, identifier: str) -> bool:
        sdf_layer = self._resolve_identifier(identifier)
        if sdf_layer is None:
            return False
        try:
            return bool(sdf_layer.Reload())
        except Exception as exc:
            self._report_error("reload_layer", identifier, exc)
            return False

    # ── Mutation helpers ─────────────────────────────────────────────

    def _resolve_identifier(self, identifier: str) -> Optional[Sdf.Layer]:
        """Return the ``Sdf.Layer`` for ``identifier`` or ``None``.

        Lookup order: cached registration, then ``Sdf.Layer.Find``. A
        successful fallback re-registers the layer so subsequent reads
        short-circuit.
        """
        sdf = self._sdf_layers.get(identifier)
        if sdf is not None:
            return sdf
        found = Sdf.Layer.Find(identifier)
        if found is not None:
            self._register(found)
            return found
        return None

    def _require_sdf(self, identifier: str) -> Sdf.Layer:
        """Strict variant of :meth:`_resolve_identifier` — raises on miss."""
        sdf = self._resolve_identifier(identifier)
        if sdf is None:
            raise KeyError(f"Unknown layer identifier: {identifier!r}")
        return sdf

    def _report_error(self, operation: str, identifier: str, exc: Exception) -> None:
        """Log a mutation failure without breaking the caller.

        Step 15: emits via stdlib ``logging`` instead of
        ``ovwidgets.common.error_reporter`` so the openusd file carries
        no ``ovwidgets.*`` imports. Bare-test environments simply see
        the log line on the configured handler; the ``bool`` return
        contract still tells the caller the operation failed.
        """
        try:
            _LOGGER.error(
                "UsdLayerStackAdapter: %s failed for %r: %s",
                operation,
                identifier,
                exc,
                exc_info=exc,
            )
        except Exception:
            # logging itself must never break the mutation flow.
            pass

    def _write_custom_data(self, key: str, value: Any) -> None:
        """Persist ``value`` under ``OVGEAR_LAYER_KEY.key`` on the root layer.

        ``Sdf.Layer.customLayerData`` returns a read-only ``Vt.Dictionary``
        proxy — nested assignments (``d[k1][k2] = v``) are silently dropped
        because the outer getter returns a fresh copy every call. The only
        safe pattern is read-full → copy-modify → write-full, which this
        helper centralises.

        The write dirties the root layer, which would otherwise trigger a
        self-inflicted ``DIRTY_STATE_CHANGED`` event:

        * The ``_persisting`` flag blocks notice-driven enqueues during the
          write itself (see :meth:`_on_layer_info_did_change` and
          :meth:`_on_layers_did_change`).
        * The post-write ``_dirty_snapshot`` refresh aligns the baseline to
          the new dirty state so the next flush's dirty-poll sees no drift.

        Kit interop: writes ALWAYS target :data:`OVGEAR_LAYER_KEY`. Reads
        check :data:`KIT_LAYER_KEY` as a fallback (LAYERS-ARCHITECTURE §7.6).
        """
        root = self._stage.GetRootLayer()
        full = dict(root.customLayerData or {})
        sub = dict(full.get(OVGEAR_LAYER_KEY, {}))
        sub[key] = value
        full[OVGEAR_LAYER_KEY] = sub
        self._persisting = True
        try:
            root.customLayerData = full
        finally:
            self._persisting = False
        # Re-align the snapshot so the deferred dirty-poll doesn't emit
        # for our own edit. The root is genuinely dirty now; a subsequent
        # stage.Save() clears it back to False, and that transition IS
        # surfaced normally via the next poll.
        self._dirty_snapshot[root.identifier] = bool(root.dirty)

    def _persist_lock_map(self) -> None:
        """Persist ``self._lock_map`` into the root layer's customLayerData."""
        self._write_custom_data(
            LOCKED_KEY,
            {
                identifier: True
                for identifier, locked in self._lock_map.items()
                if locked
            },
        )

    def persist_layer_state_before_save(self, stage: Usd.Stage) -> None:
        """Write edit-target + lock map to customLayerData just before ``stage.Save()``.

        Called by the save flow (e.g. ``Application.save_file``) because USD
        offers no ``StageSettingsSaving``-equivalent notice. The adapter
        refuses to run against a stage that isn't the one it wraps — passing
        the stage explicitly makes the contract self-documenting and catches
        adapter/stage mismatches at the call site rather than via silent
        no-op.
        """
        if stage is not self._stage:
            raise ValueError(
                "persist_layer_state_before_save called with a stage other "
                "than the one this adapter wraps"
            )
        current_target = self._stage.GetEditTarget().GetLayer().identifier
        self._write_custom_data(AUTHORING_LAYER_KEY, current_target)
        # ``_persist_lock_map`` re-writes the lock map even if unchanged,
        # which is fine — it's idempotent and keeps the two keys consistent
        # in a single save window.
        self._persist_lock_map()

    def _transfer_root_content_to(self, target: Sdf.Layer) -> None:
        """Move every root-prim spec (+ stage metadata) from root onto ``target``.

        LAYERS-PLAN Step 7:
          * Copy stage-level metadata (``upAxis``, ``metersPerUnit``,
            time codes, ``customLayerData``, …) via
            :func:`UsdUtils.CopyLayerMetadata`.
          * Strip :data:`OVGEAR_LAYER_KEY` and :data:`KIT_LAYER_KEY` from
            the copied ``customLayerData`` so the child does not inherit
            the parent's persisted edit-target / lock map — otherwise,
            re-opening a stage that references the child layer would
            restore the parent's edit-target choice onto the child.
          * Copy prim specs via :func:`Sdf.CopySpec` and clear them from
            the root, matching the "split root into a sublayer" gesture
            in LAYERS-ARCHITECTURE §13.3.
        """
        root = self._stage.GetRootLayer()

        UsdUtils.CopyLayerMetadata(root, target)

        # Strip our own (and Kit's) customLayerData keys from the target.
        # ``CopyLayerMetadata`` copies ``customLayerData`` wholesale;
        # leaving ``ovgear_layer.authoring_layer`` on the child would
        # point it at the parent's edit target on future opens.
        target_custom = dict(target.customLayerData or {})
        changed = False
        for namespace in (OVGEAR_LAYER_KEY, KIT_LAYER_KEY):
            if namespace in target_custom:
                del target_custom[namespace]
                changed = True
        if changed:
            target.customLayerData = target_custom

        # Snapshot the prim-spec list before mutating, else deletion
        # invalidates the iterator.
        names: List[str] = [spec.name for spec in root.rootPrims]
        for name in names:
            Sdf.CopySpec(root, f"/{name}", target, f"/{name}")
        for name in names:
            # ``SdfPrimSpecView.__delitem__`` takes the prim name — the
            # leading slash of an Sdf path is not part of the key.
            del root.rootPrims[name]

    # ── Lifecycle (Step 5) ───────────────────────────────────────────

    def attach_stage(
        self,
        call_later: Optional[Callable[[float, Callable], Any]] = None,
    ) -> None:
        """Register Tf/Sdf notice handlers and arm the batched flush.

        ``call_later`` is the deferred-execution primitive used to schedule a
        flush on the next frame. In production the host application injects
        its ``call_later`` callback; tests may pass a custom callable
        (e.g. an immediate-executor) to drive flushes synchronously. If no
        ``call_later`` override is provided, scheduling falls through to a
        synchronous flush so ``attach_stage`` stays usable in bare
        integration tests.

        Not idempotent: calling :meth:`attach_stage` twice without an
        intervening :meth:`detach_stage` raises :class:`RuntimeError`
        rather than silently double-registering (which would leak notice
        keys and cause every event to be dispatched twice).
        """
        if not self._destroyed:
            raise RuntimeError(
                "UsdLayerStackAdapter.attach_stage called twice without "
                "an intervening detach_stage()"
            )
        self._call_later = call_later
        with self._pending_lock:
            self._destroyed = False
            self._pending.clear()
            self._pending_edit_target_change = False
            self._flush_scheduled = False
            self._flush_handle = None

        # Seed the dirty-state snapshot so the first poll has a baseline.
        # We diff against this snapshot on every flush; any missing entry
        # is seeded silently (no synthetic event on first observation).
        for identifier, sdf_layer in list(self._sdf_layers.items()):
            self._dirty_snapshot[identifier] = bool(sdf_layer.dirty)

        # Register globally (not per-layer) and filter by sender / layer
        # identity inside each handler. Per-layer registration would
        # require one key per sublayer, which drifts as sublayers are
        # added/removed mid-session; global + identifier filter is cheaper
        # and stays correct under sublayer churn.
        #
        # ``LayersDidChangeSentPerLayer`` fires for every spec edit and
        # exposes the affected layers via ``GetLayers()``. We use it to
        # *arm a flush* whenever any cached layer changes; the dirty-poll
        # inside the flush then emits the actual DIRTY_STATE_CHANGED
        # events. Note that ``Sdf.Notice.LayerDirtinessChanged`` is **not**
        # registered — its Python binding reports ``sender=None`` for
        # in-memory / anonymous layers, making per-identifier filtering
        # impossible. The dirty-poll safety net covers both cases.
        self._notice_keys = [
            Tf.Notice.RegisterGlobally(
                Sdf.Notice.LayerInfoDidChange, self._on_layer_info_did_change
            ),
            Tf.Notice.RegisterGlobally(
                Sdf.Notice.LayersDidChangeSentPerLayer,
                self._on_layers_did_change,
            ),
            Tf.Notice.RegisterGlobally(
                Sdf.Notice.LayerDirtinessChanged,
                self._on_layer_dirtiness_changed,
            ),
            Tf.Notice.Register(
                Usd.Notice.StageEditTargetChanged,
                self._on_edit_target_changed,
                self._stage,
            ),
        ]

    def detach_stage(self) -> None:
        """Unwire notices and tear down batching state.

        Shutdown order (LAYERS-PLAN Step 5):
          1. Flip ``_destroyed`` under the lock so any in-flight flush early-
             returns.
          2. Revoke every Tf.Notice key so no more handlers fire.
          3. Cancel the pending :class:`CallbackHandle` if the scheduler
             returned a cancellable handle. A ``None`` handle is harmless —
             the ``_destroyed`` guard inside the flush covers it.
          4. Clear ``_pending`` and ``_dirty_snapshot``. The ``_sdf_layers``
             and ``_layer_cache`` dicts are deliberately retained so that
             read-only queries still work on a detached adapter.

        Idempotent: calling on an already-detached adapter is a no-op.
        """
        if self._destroyed:
            return
        with self._pending_lock:
            self._destroyed = True
            self._pending.clear()
            self._pending_edit_target_change = False
            self._flush_scheduled = False
            flush_handle, self._flush_handle = self._flush_handle, None

        for key in self._notice_keys:
            # ``Revoke()`` is idempotent and safe to call on a key whose
            # handler has already fired.
            key.Revoke()
        self._notice_keys.clear()

        if flush_handle is not None:
            cancel = getattr(flush_handle, "cancel", None)
            if callable(cancel):
                cancel()

        self._dirty_snapshot.clear()
        # Deliberately *do not* clear ``_sdf_layers`` or ``_layer_cache``:
        # read-only queries (``get_display_name``, ``is_missing``, …) must
        # still work after detach. If the caller destroys the adapter, the
        # dicts go away with the instance.

    # ── Notice handlers ─────────────────────────────────────────────

    def _on_layer_info_did_change(
        self, notice: Any, sender: Any
    ) -> None:
        """``Sdf.Notice.LayerInfoDidChange`` — info or sublayer change.

        ``notice.key()`` returns the changed field name (``"subLayers"``,
        ``"comment"``, ``"upAxis"``, …). ``sender`` is the ``Sdf.Layer``
        that changed. We filter by identifier membership in
        ``_sdf_layers`` so edits to unrelated layers (other stages in the
        same process) never enter our queue.
        """
        identifier = getattr(sender, "identifier", None)
        if identifier is None:
            return
        key = _extract_key(notice)
        with self._pending_lock:
            if self._destroyed or identifier not in self._sdf_layers:
                return
            # Self-inflicted customLayerData write: skip so the persist
            # flow does not generate phantom INFO / SUBLAYERS events.
            if self._persisting and identifier == self._stage.GetRootLayer().identifier:
                return
            if key in _SUBLAYER_INFO_KEYS:
                self._pending[identifier].add(_TOKEN_SUBLAYERS)
            elif key in _TRACKED_INFO_KEYS:
                self._pending[identifier].add(f"{_TOKEN_INFO_PREFIX}{key}")
            else:
                # Unknown info key — ignore. The dirty-poll safety net
                # still catches resulting dirty-state flips.
                return
        self._schedule_flush_threadsafe()

    def _on_layer_dirtiness_changed(self, notice: Any, sender: Any) -> None:
        """``Sdf.Notice.LayerDirtinessChanged`` — dirty flag flipped.

        The Python binding reports ``sender=None`` for in-memory /
        anonymous layers, so we can't filter by identifier here. Instead
        we just arm the flush unconditionally; the dirty-poll then diffs
        every cached layer's current ``dirty`` bit against the snapshot
        and emits the real event. This handler exists to cover the
        ``Save``-path gap where ``LayersDidChangeSentPerLayer`` does
        not fire (Sdf emits only a dirtiness change when a layer is
        saved to disk).
        """
        del notice, sender
        with self._pending_lock:
            if self._destroyed:
                return
        self._schedule_flush_threadsafe()

    def _on_layers_did_change(self, notice: Any, sender: Any) -> None:
        """``Sdf.Notice.LayersDidChangeSentPerLayer`` — generic spec edit.

        Used purely to *arm* a flush on any spec-level mutation; the
        dirty-poll inside :meth:`_flush_from_main` then emits the actual
        ``DIRTY_STATE_CHANGED`` event. We don't try to classify the
        change here — the Python binding exposes only the layer list,
        not the ``Sdf.ChangeList`` entries — so trying to distinguish
        e.g. attribute-edit vs. prim-add on the notice side would be
        speculative. The poll is authoritative.
        """
        del sender
        try:
            layers = notice.GetLayers()
        except Exception:
            return
        with self._pending_lock:
            if self._destroyed:
                return
            root_id = self._stage.GetRootLayer().identifier
            any_relevant = False
            for layer in layers:
                identifier = getattr(layer, "identifier", None)
                if identifier is None or identifier not in self._sdf_layers:
                    continue
                # Self-inflicted customLayerData writes dirty the root —
                # skip the touch so the persist flow does not queue a
                # spurious dirty-poll signal.
                if self._persisting and identifier == root_id:
                    continue
                # Marker entry; the dirty-poll will decide whether
                # this translates into an actual DIRTY_STATE_CHANGED
                # or is a no-op (e.g. edit on an already-dirty layer).
                self._pending[identifier].add(_TOKEN_TOUCHED)
                any_relevant = True
            if not any_relevant:
                return
        self._schedule_flush_threadsafe()

    def _on_edit_target_changed(self, notice: Any, sender: Any) -> None:
        """``Usd.Notice.StageEditTargetChanged`` — stage edit target switched."""
        del notice
        # Sender is the stage (registration was stage-scoped). Defend against
        # the stage identity changing mid-run by checking it still matches.
        if sender is not self._stage:
            return
        with self._pending_lock:
            if self._destroyed:
                return
            self._pending_edit_target_change = True
        self._schedule_flush_threadsafe()

    # ── Flush scheduling + dispatch ──────────────────────────────────

    def _schedule_flush_threadsafe(self) -> None:
        """Arm a one-shot flush on the next frame (idempotent, thread-safe).

        Called from notice handlers, which may be on any thread. The
        check-and-set under ``_pending_lock`` guarantees only one flush is
        scheduled per batch window. ``_flush_scheduled`` is a dedicated
        bool so the logic does not depend on the scheduler returning a
        non-None handle — some call_later implementations return ``None``.
        """
        with self._pending_lock:
            if self._destroyed or self._flush_scheduled:
                return
            self._flush_scheduled = True

        # Step 15: dropped the lazy ``ovwidgets.common.scheduler`` import.
        # The host application's ``call_later`` callback (injected via the
        # constructor) drives the deferred flush; bare-test environments
        # with no ``call_later`` registered fall through to a synchronous
        # flush, which is safe because those paths are already on the main
        # thread and the dirty-poll safety net catches anything missed.
        scheduler = self._call_later
        if scheduler is None:
            self._flush_from_main()
            return

        try:
            handle = scheduler(0.0, self._flush_from_main)
        except RuntimeError:
            # Injected scheduler raised (e.g., loop torn down during
            # shutdown). Flush synchronously — same rationale as the
            # ``call_later is None`` branch above.
            self._flush_from_main()
            return

        with self._pending_lock:
            # Only store the handle if the flush hasn't already fired
            # (possible with an immediate-mode scheduler). Under the flag
            # model, ``_flush_scheduled=False`` means the flush already ran.
            if self._flush_scheduled:
                self._flush_handle = handle

    def _flush_from_main(self) -> None:
        """Drain the pending batch and dispatch one event per change type.

        Runs on the main thread (scheduled via ``call_later``). Swaps the
        pending dict under lock before building events so subscribers that
        mutate USD during dispatch re-fill a *fresh* ``_pending`` and
        re-arm a new flush — no event loss, no re-entrance crash.
        """
        with self._pending_lock:
            self._flush_scheduled = False
            self._flush_handle = None
            if self._destroyed:
                return
            pending = self._pending
            self._pending = defaultdict(set)
            edit_target_changed = self._pending_edit_target_change
            self._pending_edit_target_change = False

        events = self._build_events_from_pending(pending, edit_target_changed)
        events.extend(self._dirty_poll())

        for event in events:
            self._dispatch(event)

    def _build_events_from_pending(
        self,
        pending: Dict[str, Set[str]],
        edit_target_changed: bool,
    ) -> List[LayerEvent]:
        """Group the per-identifier change set into ``LayerEvent`` objects.

        One event per type so subscribers can cheaply switch on
        ``event_type``. Identifiers are sorted for determinism in tests.
        """
        events: List[LayerEvent] = []

        if edit_target_changed:
            events.append(LayerEvent(event_type=LayerEventType.EDIT_TARGET_CHANGED))

        sublayer_ids: List[str] = []
        info_fields: Dict[str, List[str]] = defaultdict(list)

        for identifier, tokens in pending.items():
            if _TOKEN_SUBLAYERS in tokens:
                sublayer_ids.append(identifier)
            for tok in tokens:
                if tok.startswith(_TOKEN_INFO_PREFIX):
                    info_fields[identifier].append(tok[len(_TOKEN_INFO_PREFIX):])
            # ``_TOKEN_TOUCHED`` has no direct event — it only armed the
            # flush; the dirty-poll emits the DIRTY_STATE_CHANGED event.

        if sublayer_ids:
            events.append(LayerEvent(
                event_type=LayerEventType.SUBLAYERS_CHANGED,
                identifiers=tuple(sorted(sublayer_ids)),
            ))
        if info_fields:
            events.append(LayerEvent(
                event_type=LayerEventType.INFO_CHANGED,
                identifiers=tuple(sorted(info_fields)),
                info_fields={
                    identifier: tuple(sorted(fields))
                    for identifier, fields in info_fields.items()
                },
            ))

        return events

    def _dirty_poll(self) -> List[LayerEvent]:
        """Emit synthetic ``DIRTY_STATE_CHANGED`` for any snapshot drift.

        LAYERS-WINDOW-ARCHITECTURE §34.14 flags that Kit misses
        ``DIRTY_STATE_CHANGED`` for some USD backends. The poll diffs every
        cached layer's current ``dirty`` flag against ``_dirty_snapshot`` —
        any mismatch emits a synthetic event and updates the snapshot.
        Cost: O(k) where k is the number of cached layers (typically <50).

        Skips the root layer while ``_persisting`` is set — the mid-write
        dirtiness is self-inflicted by :meth:`_write_custom_data` and the
        snapshot refresh at the end of that write realigns the baseline
        so the post-save poll still catches the genuine clean transition.
        """
        drifted: List[str] = []
        root_id = self._stage.GetRootLayer().identifier
        persisting = self._persisting
        # Snapshot the identifier list once so we are stable against the
        # handle cache being mutated during iteration (no mutations expected
        # on the main thread during flush, but defensive is cheap here).
        for identifier, sdf_layer in list(self._sdf_layers.items()):
            if persisting and identifier == root_id:
                continue
            try:
                current = bool(sdf_layer.dirty)
            except Exception:
                # Layer was closed/invalidated between cache insert and
                # poll. Drop from snapshot; next round will re-seed.
                self._dirty_snapshot.pop(identifier, None)
                continue
            previous = self._dirty_snapshot.get(identifier)
            if previous is None:
                # First observation — seed silently. The layer was added
                # since the last flush; no synthetic event needed because
                # a ``DIRTY_STATE_CHANGED`` / ``SUBLAYERS_CHANGED`` notice
                # for the add was (or will be) handled through the normal
                # path.
                self._dirty_snapshot[identifier] = current
                continue
            if current != previous:
                self._dirty_snapshot[identifier] = current
                drifted.append(identifier)

        if not drifted:
            return []
        return [LayerEvent(
            event_type=LayerEventType.DIRTY_STATE_CHANGED,
            identifiers=tuple(sorted(drifted)),
        )]

    def _dispatch(self, event: LayerEvent) -> None:
        """Invoke every subscriber; one bad handler never breaks the batch.

        A raising subscriber is reported via stdlib :mod:`logging` and the
        dispatcher moves on to the next. The flush loop must stay robust
        against third-party subscription bugs.
        """
        for callback in list(self._subscribers):
            try:
                callback(event)
            except Exception as exc:
                try:
                    _LOGGER.error(
                        "UsdLayerStackAdapter: subscriber raised during event dispatch: %s",
                        exc,
                        exc_info=exc,
                    )
                except Exception:
                    # logging itself must never break dispatch.
                    pass

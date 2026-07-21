# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tree model for the Layers ``ui.TreeView`` (LAYERS-PLAN Step 13).

:class:`LayerModel` subclasses :class:`omni.ui.AbstractItemModel` and
exposes the root layer (and, optionally, the session layer) as the
top-level rows of the Layers widget. Step 13 renders a single column
with layer display names only — sublayer recursion lands in Step 14,
and the multi-column delegate (edit-target, mute, lock, dirty, save)
arrives in Step 17+.

The model wraps a :class:`~ovui_widgets.common.adapters.LayerStackAdapter` (the
adapter boundary keeps the widget package Kit-free — widget-window split /
constraint G2) and subscribes to its :class:`LayerEvent` stream so
every structural change triggers a rebuild. Batching and targeted
refresh are deliberately deferred to Steps 21 and 31; Step 13 uses
the simplest possible dispatcher: a structural event → full rebuild,
a flag event → invalidate affected items + repaint.

Step 26 completes the edit-target propagation plumbing landed in Step
24: :meth:`_update_edit_target` now fires ``_item_changed(ancestor)``
for every ancestor whose ``_has_edit_target_descendant`` flag flipped
during a clear- or set-phase walk, so the Step-25 half-green leading
icon (``Layers.LeadingIcon::has_descendant``) re-renders mid-session
rather than only on first paint.
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import omni.ui as ui
from ovui_data_adapters.common import LayerEvent, LayerEventType, LayerHandle, LayerStackAdapter

from ovui_widgets.common.error_reporter import ErrorReporter
from ovui_widgets.common.settings import Subscription
from ovui_widgets.layers.commands.file_io_commands import (
    ReloadLayerCommand,
    SaveLayerAsCommand,
    SaveLayerCommand,
)
from ovui_widgets.layers.commands.layer_commands import SetEditTargetCommand
from ovui_widgets.layers.commands.sublayer_commands import (
    InsertSublayerCommand,
    MoveSublayerCommand,
    RemoveSublayerCommand,
)
from ovui_widgets.layers.drop_visual_controller import DropVisualController
from ovui_widgets.layers.layer_item import LayerItem
from ovui_widgets.layers.layer_settings import LayerSettings
from ovui_widgets.layers.models.layer_name_model import LayerNameValueModel
from ovui_widgets.layers.models.lock_model import LockValueModel
from ovui_widgets.layers.models.mute_model import LocalMuteValueModel
from ovui_widgets.layers.models.save_all_model import SaveAllValueModel
from ovui_widgets.layers.models.save_model import SaveValueModel
from ovui_widgets.layers.prim_spec_item import PrimSpecItem

if TYPE_CHECKING:  # pragma: no cover — type-hint guard
    from ovui_widgets.common.services import WidgetServices


@dataclass
class DefaultLayerSettings:
    """Stand-in for :class:`LayerSettings` until Step 52 ships persistence.

    Mirrors the attribute surface documented in
    LAYERS-WINDOW-ARCHITECTURE §15 with the defaults Kit uses. Only
    :attr:`show_session_layer` is consumed by Step 13; the rest of
    the fields are declared so Phase K (Step 51+) can switch the real
    :class:`LayerSettings` in without touching call sites in the
    model. Plan finding A-3 explicitly tracks this decision.
    """

    show_session_layer: bool = True
    show_layer_contents: bool = True
    show_missing_reference: bool = True
    show_info_notification: bool = True
    show_merge_or_flatten_warning: bool = True
    show_layer_file_extension: bool = True


class LayerModel(ui.AbstractItemModel):
    """TreeView data model backed by a :class:`LayerStackAdapter`.

    Exposes :attr:`root_item` (and optionally :attr:`session_item`)
    as the top-level rows. Layer display names are served through
    :class:`ui.SimpleStringModel` value models cached on each
    :class:`LayerItem`; Step 17 replaces them with
    ``LayerNameValueModel`` instances that also carry edit-target /
    missing state for the delegate.
    """

    # Column count fixed at 7 in Step 17 — order matches
    # LAYERS-WINDOW-ARCHITECTURE §20.5 and LAYERS-PLAN Step 17:
    #   0 name · 1 live · 2 save · 3 local-mute · 4 global-mute ·
    #   5 latest · 6 lock. Steps 18-22 replace the placeholder value
    #   models on cols 1-6 with per-item ones tied to the real flags.
    NUM_COLUMNS = 7

    # Shared no-op value model handed back for the not-yet-graduated
    # columns (Steps 20-22 replace the remainder). ``ui.TreeView``
    # requires a non-``None`` return from ``get_item_value_model`` to
    # lay the cell out — the string model carries an empty label so the
    # placeholder cells are blank but still rendered. One instance is
    # enough because the placeholder is stateless and its contents never
    # change.
    _PLACEHOLDER_VALUE_MODEL: "Optional[ui.SimpleStringModel]" = None

    # Lazy per-item value-model factory table (LAYERS-PLAN Logic F4).
    # Maps ``column_id`` → ``(LayerItem attribute, value-model class)``.
    # :meth:`get_item_value_model` looks up the slot on the item, and
    # if it's ``None`` constructs the model and caches it so repeated
    # reads return the same instance. Steps 20-22 add the remaining
    # entries; empty columns fall through to the shared placeholder.
    _COLUMN_MODEL_FACTORIES: "Dict[int, tuple]" = {
        0: ("_name_model", LayerNameValueModel),
        2: ("_save_model", SaveValueModel),
        3: ("_local_mute_model", LocalMuteValueModel),
        6: ("_lock_model", LockValueModel),
    }

    def __init__(
        self,
        adapter: Optional[LayerStackAdapter],
        services: "Optional[WidgetServices]" = None,
        settings: "Optional[DefaultLayerSettings | LayerSettings]" = None,
        before_save_all_fn: "Optional[Callable[[], bool | None]]" = None,
    ) -> None:
        super().__init__()
        self._adapter: Optional[LayerStackAdapter] = None
        self._services: "Optional[WidgetServices]" = services
        self._before_save_all_fn = before_save_all_fn
        # Step 52 — accept either the persistent :class:`LayerSettings`
        # (real app path) or the dataclass :class:`DefaultLayerSettings`
        # (unit-test path). Both expose the same attribute surface so
        # the model's read sites (``self._settings.show_session_layer``
        # etc.) stay untouched; the only asymmetry is the subscription
        # hookup a few lines down.
        self._settings: "DefaultLayerSettings | LayerSettings" = (
            settings if settings is not None else DefaultLayerSettings()
        )
        # Step 52 — per-key subscriptions so a flipped persistent
        # setting (e.g. the Step 53 Options dropdown) reshapes the tree
        # without a manual ``rebuild`` call. Only the tree-shape keys
        # are watched; toast / dialog toggles are read on-demand by
        # their call sites. Populated here, cancelled in :meth:`destroy`.
        self._settings_subs: List[Subscription] = []
        if isinstance(self._settings, LayerSettings):
            self._settings_subs = self._settings.subscribe_tree_rebuild(
                self._on_settings_changed
            )

        # Top-level items — populated by :meth:`_reset_root`.
        self._root_item: Optional[LayerItem] = None
        self._session_item: Optional[LayerItem] = None

        # Identifier → every :class:`LayerItem` that wraps it. A layer
        # may appear as a sublayer of multiple parents in USD, so we
        # keep every instance so Step 21's state-propagation pass can
        # fan-out edit-target / mute markers across all clones.
        self._sublayers_cache: Dict[str, List[LayerItem]] = defaultdict(list)

        # Identifier → first :class:`LayerItem` — fast lookup used by
        # :meth:`_on_layer_event` to route flag-change notifications.
        # Step 14 populates this with sublayer items; in Step 13 it
        # holds only the top-level rows.
        self._items_by_id: Dict[str, LayerItem] = {}

        # Edit-target identifier snapshot (refreshed on every reset;
        # Step 21 will consume it from the marker-walk pass).
        self._edit_target_identifier: str = ""

        # Selected tree rows (LAYERS-PLAN Step 16 / Step 50). The list
        # carries the union of :class:`LayerItem` and
        # :class:`PrimSpecItem` — Phase J wires prim-spec rows into the
        # same tree, so the Del hotkey (Step 50) needs the prim-spec
        # entries here as well. ``LayerWindow`` wires
        # ``tree_view.set_selection_changed_fn`` to call
        # :meth:`set_selected_items` so context-menu / rename / command
        # code reads one source of truth.
        self._selected_items: List[Any] = []

        self._event_sub: Optional[Subscription] = None
        self._destroyed: bool = False

        # ── Step 44 drop-visual controller ───────────────────────────
        # Holds the transient drag-over state the
        # :class:`~ovui_widgets.layers.layer_delegate.LayerDelegate` consults
        # while painting row backgrounds. The controller is constructed
        # eagerly (rather than lazily by the delegate) so that tests
        # which exercise :meth:`drop_accepted` in isolation — without
        # ever building a delegate — can still assert on the state the
        # paint pipeline would have consumed. Mutations happen
        # exclusively inside :meth:`drop_accepted` and :meth:`drop`;
        # :meth:`_fire_drop_indicator_refresh` routes the paired
        # :meth:`_item_changed` calls so stale indicator rows clear in
        # lockstep with the new target lighting up.
        self._drop_visual: DropVisualController = DropVisualController()

        # ── Step 35 Save-All aggregate model ─────────────────────────
        # Constructed lazily by :meth:`get_save_all_model` when the
        # window first builds its toolbar. Cached here (rather than on
        # a :class:`LayerItem`) because the model aggregates *across*
        # layers — it has no single owning row. :meth:`_flush_events`
        # fires :meth:`_value_changed` on it on every dirty / sublayer
        # event so the toolbar badge repaints without a full rebuild.
        self._save_all_model: Optional[SaveAllValueModel] = None

        # ── Step 32 event batching ───────────────────────────────────
        # Events arrive on the notice thread (for the USD adapter) or
        # synchronously from the mock adapter's test driver. Either way
        # we append here and schedule a single per-frame flush via
        # :attr:`Application.call_later` — 50 attribute sets in one
        # frame produce one ``_flush_events`` call, not 50 full
        # rebuilds (LAYERS-WINDOW-ARCHITECTURE §34.14). When
        # :attr:`_app` is ``None`` (headless test construction), the
        # scheduling hop is skipped and the flush runs inline so tests
        # see the pre-Step-32 synchronous semantics they were written
        # against.
        self._pending_events: List[LayerEvent] = []
        self._flush_scheduled: bool = False

        # ── Step 51 name-search filter ────────────────────────────────
        # Stores the lower-cased search text that :meth:`filter_by_text`
        # is currently filtering by; empty string means "no filter".
        # :class:`LayerItem` flags ``_filtered`` / ``_child_filtered``
        # are kept in sync with this text by :meth:`_apply_filter` so
        # :meth:`get_item_children` can fan the match-set into the
        # ``ui.TreeView`` without re-scanning the adapter on every
        # paint.
        self._filter_text: str = ""

        # Route construction through :meth:`set_adapter` so the attach
        # path is the single place that subscribes events + builds the
        # tree. Keeps the re-target lifecycle (Step 15) symmetric with
        # first-time attach and removes a whole class of drift bugs.
        self.set_adapter(adapter)

    # ── ui.AbstractItemModel overrides ───────────────────────────────

    def begin_edit(self, item: Any) -> None:
        """Terminate ovui's native TreeView edit-transaction fallback."""

    def end_edit(self, item: Any) -> None:
        """Terminate ovui's native TreeView edit-transaction fallback."""

    def get_item_children(self, item: Any) -> List[Any]:
        """Return the children for ``item`` (``None`` → top-level rows).

        Session layer comes before root when visible, matching Kit's
        layer-window convention (LAYERS-WINDOW-ARCHITECTURE §14.5).

        Step 48 extends the method:

        - :class:`LayerItem` children are ``[*sublayers, *prim_specs]``
          when :attr:`DefaultLayerSettings.show_layer_contents` is
          ``True`` and prim specs are lazily loaded on first access
          via :meth:`_ensure_prim_specs_loaded`. The order matches
          LAYERS-PLAN Step 48's "sublayers first, then prim specs"
          convention so the sublayer → prim-spec gradient stays visual
          (layer rows at the top, spec rows at the bottom of the
          branch).
        - :class:`PrimSpecItem` children are the lazy descriptor-walk
          emitted by :meth:`PrimSpecItem.children`, so expanding a
          prim-spec row reads the adapter on demand and the collapsed
          branches hold no per-row cost (LAYERS-WINDOW-ARCHITECTURE
          §17.5 / §18).
        """
        filter_active = bool(self._filter_text)
        if item is None:
            items: List[LayerItem] = []
            if (
                self._session_item is not None
                and self._settings.show_session_layer
            ):
                if not filter_active or self._matches_filter(
                    self._session_item
                ):
                    items.append(self._session_item)
            if self._root_item is not None:
                if not filter_active or self._matches_filter(self._root_item):
                    items.append(self._root_item)
            return items
        if isinstance(item, LayerItem):
            # Step 51 — drop sublayer rows whose subtree has no match.
            # ``_matches_filter`` covers "self matches" and "descendant
            # matches" so the ancestor-promotion contract from the plan
            # (parents of hits stay visible) comes for free.
            if filter_active:
                children: List[Any] = [
                    s for s in item.sublayers if self._matches_filter(s)
                ]
            else:
                children = list(item.sublayers)
            if self._settings.show_layer_contents:
                self._ensure_prim_specs_loaded(item)
                children.extend(item._prim_specs)
            return children
        if isinstance(item, PrimSpecItem):
            if self._adapter is None:
                return []
            return list(item.children(self._adapter))
        return []

    def can_item_have_children(self, item: Any) -> bool:
        if item is None:
            return True
        if isinstance(item, LayerItem):
            if item.sublayers:
                # Step 51 — under an active filter the chevron is only
                # "expandable" if some sublayer passes the filter;
                # otherwise drop into the prim-spec branch so rows with
                # no visible sublayers but visible prim specs still
                # expand.
                if not self._filter_text or any(
                    self._matches_filter(s) for s in item.sublayers
                ):
                    return True
            if self._settings.show_layer_contents:
                # Populate the cache so the chevron decision stays
                # accurate without a repeated adapter round-trip on
                # every paint. The helper short-circuits once loaded
                # and degrades to ``[]`` on adapter failure, so the
                # branch is cheap after the first call.
                self._ensure_prim_specs_loaded(item)
                return bool(item._prim_specs)
            return False
        if isinstance(item, PrimSpecItem):
            if self._adapter is None:
                return False
            return bool(item.children(self._adapter))
        return False

    def _ensure_prim_specs_loaded(self, layer_item: LayerItem) -> None:
        """Load ``layer_item``'s top-level prim specs on first access.

        LAYERS-PLAN Step 48 — prim specs materialise lazily so a
        layer with thousands of root prims pays zero per-row cost
        until the user expands the layer. The load walks
        :meth:`LayerStackAdapter.get_prim_specs` at ``/`` and wraps
        each descriptor in a fresh :class:`PrimSpecItem`. Result is
        stored on the :class:`LayerItem` (``_prim_specs`` +
        ``_prim_specs_loaded``) so a subsequent call is a no-op until
        :meth:`LayerItem.invalidate_prim_specs` fires.

        Degrades to an empty list on :class:`KeyError` (the layer
        identifier no longer resolves — a peer command may have torn
        it down mid-paint) so the tree view renders a childless leaf
        instead of propagating the exception through
        :meth:`get_item_children`.
        """
        if layer_item._prim_specs_loaded:
            return
        if self._adapter is None:
            layer_item._prim_specs = []
            layer_item._prim_specs_loaded = True
            return
        try:
            descriptors = self._adapter.get_prim_specs(
                layer_item.identifier, "/"
            )
        except KeyError:
            descriptors = []
        layer_item._prim_specs = [
            PrimSpecItem(layer_item, d) for d in descriptors
        ]
        layer_item._prim_specs_loaded = True

    def _invalidate_prim_specs(self, layer_item: LayerItem) -> None:
        """Drop ``layer_item``'s cached prim-spec rows + descendants.

        LAYERS-PLAN Step 48 — fires on structural events that may
        have altered the layer's root prim hierarchy so the next
        :meth:`get_item_children` call re-reads the adapter. Walks
        the cached :class:`PrimSpecItem` subtree as well so nested
        expansions are invalidated in lockstep with the root.
        """
        for spec in layer_item._prim_specs:
            self._walk_prim_spec_invalidate(spec)
        layer_item.invalidate_prim_specs()

    def _walk_prim_spec_invalidate(self, spec: PrimSpecItem) -> None:
        """Invalidate cached descendants of ``spec`` (Step 48).

        Only walks the subtree that has actually been materialised —
        collapsed branches never cached any children, so there is
        nothing to drop there. Reads ``spec._children`` directly
        (rather than through :meth:`PrimSpecItem.children`) so the
        walk does not accidentally re-hit the adapter on an item
        whose cache is about to be cleared.
        """
        cached = spec._children
        if cached is None:
            return
        for child in cached:
            self._walk_prim_spec_invalidate(child)
        spec.invalidate_children()

    # ── Prim-spec lookup (LAYERS-PLAN Step 57) ───────────────────────

    def find_prim_spec(
        self, layer_item: LayerItem, path: str
    ) -> Optional[PrimSpecItem]:
        """Return ``layer_item``'s :class:`PrimSpecItem` for ``path``.

        LAYERS-PLAN Step 57 — :class:`LayerSelectionWatch` uses this to
        resolve a :class:`SelectionBus` prim path into the tree row
        that should be revealed. Materialises the cache lazily on the
        walk: the top-level prim specs are loaded through
        :meth:`_ensure_prim_specs_loaded`, and each descendant hop
        pulls its children through :meth:`PrimSpecItem.children` so a
        deep path (e.g. ``/World/Set/Hero``) transparently expands the
        cache on the way down.

        Returns ``None`` when the layer simply does not carry a spec
        at ``path`` — a prim existing in stage does not imply a spec
        exists in every layer, so a missing spec is the expected
        outcome for layers that don't author the prim. ``/`` and the
        empty string resolve to ``None`` because the tree does not
        render the pseudo-root as its own :class:`PrimSpecItem`.
        """
        if self._destroyed or self._adapter is None:
            return None
        if path in ("", "/"):
            return None
        # Ensure the top-level prim specs are materialised on the layer
        # — the bus event may be the first time the user interacts with
        # this layer's subtree, so the cache is likely empty.
        self._ensure_prim_specs_loaded(layer_item)
        # Walk each prefix segment of ``path`` and pull down one level
        # of cached children. Quitting early on a segment miss avoids
        # hitting the adapter for branches that can't contain the spec.
        parts = [segment for segment in path.split("/") if segment]
        if not parts:
            return None
        current: Optional[PrimSpecItem] = None
        children: List[PrimSpecItem] = list(layer_item._prim_specs)
        accumulated = ""
        for segment in parts:
            accumulated = f"{accumulated}/{segment}"
            match: Optional[PrimSpecItem] = None
            for spec in children:
                if spec.path == accumulated:
                    match = spec
                    break
            if match is None:
                return None
            current = match
            if accumulated == path:
                return current
            children = list(current.children(self._adapter))
        return current

    def _find_items(self, identifier: str) -> List[LayerItem]:
        """Return every :class:`LayerItem` that wraps ``identifier``.

        LAYERS-PLAN Step 57 — a thin named alias over
        :attr:`_sublayers_cache` so call sites read the intent ("find
        the items for this identifier") rather than the underlying
        dict. Returns an empty list for an unknown identifier; a
        single layer may appear in the list multiple times when the
        sublayer graph mounts it under more than one parent (cloned
        sublayers).
        """
        return list(self._sublayers_cache.get(identifier, ()))

    def get_item_value_model_count(self, item: Any) -> int:
        return self.NUM_COLUMNS

    def get_item_value_model(
        self,
        item: Any,
        column_id: int,
    ) -> Optional[ui.AbstractValueModel]:
        """Return the value model for ``(item, column_id)``.

        Per-column value models graduate into :attr:`_COLUMN_MODEL_FACTORIES`
        one step at a time. On first access for a given column the
        factory constructs the model and caches it on the owning
        :class:`LayerItem`; every subsequent read returns the same
        instance (LAYERS-PLAN Logic F4 — lazy per-item assignment):

        - Column 0 — :class:`LayerNameValueModel` (Step 18): display
          name + state suffix (``(Authoring Layer)``, ``(Missing)``,
          ``(Anonymous)``, ``(Read Only)``) + a color role string the
          delegate routes into the ``Layers.NameLabel::<role>`` style
          selector.
        - Column 2 — :class:`SaveValueModel` (Step 19): dirty-and-
          saveable boolean + click-to-save write surface.
        - Column 3 — :class:`LocalMuteValueModel` (Step 20): local-
          mute boolean + click-to-toggle write surface.
        - Column 6 — :class:`LockValueModel` (Step 21): lock boolean
          + click-to-toggle write surface.

        Columns without a factory entry fall back to a shared empty
        :class:`ui.SimpleStringModel` — an inert placeholder so the
        ``ui.TreeView`` can still lay the cell out without faulting on
        ``None``. Step 22 graduates the remaining live / global-mute /
        latest columns.
        """
        if not isinstance(item, LayerItem):
            return None
        factory = self._COLUMN_MODEL_FACTORIES.get(column_id)
        if factory is not None:
            attr, klass = factory
            model = getattr(item, attr, None)
            if model is None:
                model = klass(self, item)
                setattr(item, attr, model)
            return model
        if 1 <= column_id < self.NUM_COLUMNS:
            if LayerModel._PLACEHOLDER_VALUE_MODEL is None:
                LayerModel._PLACEHOLDER_VALUE_MODEL = ui.SimpleStringModel("")
            return LayerModel._PLACEHOLDER_VALUE_MODEL
        return None

    # ── Drag-drop (LAYERS-PLAN Step 43) ──────────────────────────────

    def get_drag_mime_data(self, item: Any) -> str:
        """Return the drag payload for ``item`` — the layer identifier.

        ovui calls this once when a drag starts. Returning an empty
        string tells ovui the row cannot be dragged, which we use to
        keep the reserved root and session rows pinned: an item with no
        parent is a top-level row and has no parent sublayer slot to
        move out of.
        """
        if not isinstance(item, LayerItem):
            return ""
        if item.parent is None:
            return ""
        return item.identifier

    def drop_accepted(
        self,
        target_item: Any,
        source: Any,
        drop_location: int = -1,
    ) -> bool:
        """Return ``True`` when ``source`` may be dropped on ``target_item``.

        Drop-location semantics (LAYERS-PLAN Step 43):

        - ``drop_location == -1`` — drop "onto" ``target_item``. The
          target becomes the new parent; the source is appended to the
          target's sublayer list.
        - ``drop_location >= 0`` — drop "between" rows. The source is
          inserted at index ``drop_location`` inside the target's
          *parent* sublayer list. Dropping between top-level rows has
          no parent to receive the sublayer, so those drops reject.

        Only :class:`LayerItem` → :class:`LayerItem` drags land in v1
        (Step 43). External file drops graduate in Step 45; prim-spec
        moves land with Phase J.

        Step 44 also records the outcome on the drop-visual controller
        so the delegate can paint a green drop-target overlay on a
        valid hover or a red rejected overlay with the rejection
        reason on an invalid one (LAYERS-PLAN UX fix B3 — silent
        rejection is the Step 43 behaviour we're replacing).
        """
        if not isinstance(target_item, LayerItem):
            # Non-LayerItem targets (defensive — Phase J prim-spec rows
            # or a string payload) cannot carry an indicator anywhere;
            # drop any live state so the last valid hover doesn't
            # linger when the cursor leaves a tree into an unrelated
            # area.
            self._clear_drop_visual()
            return False
        if isinstance(source, LayerItem):
            ok, reason = self._can_move_layer(target_item, source, drop_location)
            if ok:
                self._set_drop_visual_valid(target_item, drop_location)
            else:
                # ``reason`` is always populated on reject — the
                # explicit ``or`` keeps the indicator tooltip readable
                # even if a future branch forgets to supply one.
                self._set_drop_visual_rejected(
                    target_item,
                    drop_location,
                    reason or "Cannot drop on this target",
                )
            return ok
        # Step 45 — external file drop from the OS. ovui hands the
        # path(s) as a string (or a list of strings for multi-select).
        paths = _extract_file_paths(source)
        if paths is not None:
            ok, reason = self._can_insert_file_sublayer(
                target_item, drop_location, paths
            )
            if ok:
                self._set_drop_visual_valid(target_item, drop_location)
            else:
                self._set_drop_visual_rejected(
                    target_item,
                    drop_location,
                    reason or "Cannot drop on this target",
                )
            return ok
        # Truly unrecognised payload (a test feeding garbage, or a
        # future drag source we haven't taught the model). Mirror the
        # indicator so the user sees the red outline instead of a
        # silent no-op.
        self._set_drop_visual_rejected(
            target_item,
            drop_location,
            "Cannot drop: unsupported drag source",
        )
        return False

    def drop(
        self,
        target_item: Any,
        source: Any,
        drop_location: int = -1,
    ) -> None:
        """Execute a validated drop by pushing a :class:`MoveSublayerCommand`.

        Runs :meth:`_can_move_layer` a second time — :meth:`drop_accepted`
        already validated on hover, but a peer command could have
        mutated the tree between the hover and the release (e.g. the
        user locks the target in another window mid-drag), so the final
        gate is authoritative.

        ``drop_location == -1`` targets the row itself as new parent;
        otherwise ``target_item.parent`` is the new parent and
        ``drop_location`` is the insert index. Headless construction
        (``app`` is ``None``) bypasses the undo stack and calls the
        adapter directly — mirrors the :meth:`_request_save` fallback
        so bare-model unit tests can exercise the drop path without
        fabricating an :class:`~ovui_widgets.common.undo.UndoManager`.
        """
        if self._destroyed or self._adapter is None:
            self._clear_drop_visual()
            return
        if not isinstance(target_item, LayerItem):
            self._clear_drop_visual()
            return
        if not isinstance(source, LayerItem):
            # Step 45 — external file drop: route string/list payloads
            # through :meth:`_perform_file_sublayer_drop` so a dragged
            # ``.usda`` file lands as an :class:`InsertSublayerCommand`
            # under the hovered row (or its parent, for between-drops).
            paths = _extract_file_paths(source)
            if paths is not None:
                self._perform_file_sublayer_drop(
                    target_item, drop_location, paths
                )
                return
            self._clear_drop_visual()
            return
        ok, reason = self._can_move_layer(target_item, source, drop_location)
        if not ok:
            # Step 44 — surface the Step 43 silent rejection as a toast
            # so the user knows *why* the drag didn't land. Skipped in
            # headless / test construction (``app is None``) because
            # :class:`ErrorReporter` routes through the app's status
            # label when initialised; the stderr fallback is fine to
            # fire either way but we keep it gated on the live app so
            # bare-model tests don't spew warnings every reject.
            if self._services is not None and reason:
                ErrorReporter.show_warning(reason)
            self._clear_drop_visual()
            return
        source_parent = source.parent
        if source_parent is None:
            self._clear_drop_visual()
            return
        try:
            from_pos = source_parent._sublayers.index(source)
        except ValueError:
            self._clear_drop_visual()
            return
        from_parent_id = source_parent.identifier

        if drop_location == -1:
            to_parent_id = target_item.identifier
            to_pos = -1
        else:
            new_parent = target_item.parent
            if new_parent is None:
                self._clear_drop_visual()
                return
            to_parent_id = new_parent.identifier
            to_pos = drop_location

        # Clear the indicator *before* the mutation so the row that
        # carried the highlight has a chance to repaint without it —
        # the subsequent ``MoveSublayerCommand`` fires its own
        # :meth:`_item_changed` cascade, so the repaint is cheap.
        self._clear_drop_visual()

        services = self._services
        if services is None:
            self._adapter.move_sublayer(
                from_parent_id, from_pos, to_parent_id, to_pos
            )
            return
        cmd = MoveSublayerCommand(
            self._adapter,
            services.selection_bus,
            from_parent_id,
            from_pos,
            to_parent_id,
            to_pos,
        )
        services.undo_manager.push(cmd)

    def _can_move_layer(
        self,
        target: LayerItem,
        source: LayerItem,
        drop_location: int,
    ) -> Tuple[bool, Optional[str]]:
        """Validate a layer-row drag (LAYERS-PLAN Step 43/44/46).

        Returns ``(ok, reason)``: on accept ``reason`` is ``None``; on
        reject ``reason`` is a one-line human-readable explanation the
        Step 44 drop-visual controller surfaces as a tooltip and
        :class:`~ovui_widgets.common.error_reporter.ErrorReporter` toast. Rejection
        copy matches the bullet list in LAYERS-PLAN Step 44/46 so the
        user-facing strings stay stable across steps.

        Rejects when:

        - ``source is target`` — dragging a row onto itself is a no-op
          the user almost certainly didn't mean.
        - ``source.parent is None`` — root / session rows are pinned;
          they have no parent sublayer slot to move out of.
        - The source or target layer was removed from the adapter
          between drag-start and drop-release (Step 46 edge case — a
          peer command tore the tree down while the cursor was held).
          The LayerItem objects are still live Python refs but their
          identifiers no longer resolve, so any ``is_locked`` /
          ``is_muted`` read through the adapter would raise
          ``KeyError``.
        - ``source.is_locked`` or the *source's parent* is locked
          (Step 46). A locked layer is not movable; a locked parent
          does not release its children. The rejection copy matches
          the plan's "Cannot move locked layer" wording so the toast
          is stable.
        - The move would create a cycle — making ``source`` a child of
          ``target`` (or ``target.parent``) must not place ``source``
          under one of its own descendants.
        - The destination parent is not writable — locked, muted, or
          read-only-on-disk. :meth:`LayerItem.is_writable` delegates
          to the adapter's composite check; we fan the rejection out
          into separate "locked" / "muted" / "not writable" branches
          so the user sees the specific reason on the tooltip.
        - The destination parent itself is ``None`` in a "drop between"
          request — top-level rows have no parent sublayer list.
        - The between-drop slot resolves to the source's current slot
          in its current parent (Step 46 no-op guard). ``move_sublayer``
          handles a null move idempotently but pushing a
          :class:`MoveSublayerCommand` that changes nothing clutters
          the undo stack; reject here so the user sees "already at
          this position" instead of an invisible history entry.
        """
        if source is target:
            return False, "Cannot drop: source and target are the same row"
        if source.parent is None:
            return (
                False,
                "Cannot drop: root and session layers cannot be moved",
            )

        # ── Step 46 · Stale source / target guard ───────────────────
        # A peer command (context-menu Remove, Flatten, Merge, or a
        # USD notice from another window) may have removed the source
        # or target layer between the hover-time ``drop_accepted``
        # and this release-time ``drop``. Both LayerItem refs survive
        # as Python objects on the drag-context side, so the
        # ``is_locked`` / ``is_writable`` reads below would raise
        # ``KeyError`` via the adapter's ``_require`` on a missing
        # identifier. Guard with ``find_layer`` so the reject path
        # fires the normal red-outline indicator instead of an
        # uncaught exception propagating through ovui's dispatch.
        adapter = self._adapter
        if adapter is not None:
            if adapter.find_layer(source.identifier) is None:
                return False, "Cannot drop: source layer no longer exists"
            if adapter.find_layer(target.identifier) is None:
                return False, "Cannot drop: target layer no longer exists"

        # ── Step 46 · Source / source-parent lock guard ─────────────
        # Independent of the destination: a locked source cannot be
        # moved out of its parent, and a locked parent refuses to
        # give up any of its children. Plan wording mandates a single
        # "Cannot move locked layer" string so the toast is stable
        # whichever side the lock sits on.
        source_parent = source.parent
        if source.is_locked:
            return False, "Cannot move locked layer"
        if source_parent.is_locked:
            return False, "Cannot move locked layer"

        if drop_location == -1:
            new_parent: Optional[LayerItem] = target
        else:
            new_parent = target.parent
            if new_parent is None:
                return (
                    False,
                    "Cannot drop: top-level rows cannot accept a between-drop",
                )

        # Circular guard: walk new_parent's ancestor chain (including
        # new_parent itself) and reject if source appears anywhere.
        # Re-parenting source underneath one of its own descendants
        # would leave the subtree pointing at itself.
        node: Optional[LayerItem] = new_parent
        while node is not None:
            if node is source:
                return (
                    False,
                    "Cannot drop: would create circular reference",
                )
            node = node.parent

        if not new_parent.is_writable:
            # Surface the specific writability reason so the tooltip
            # tells the user *why* the target rejected the drop. Lock
            # and mute take precedence over the generic "not writable"
            # branch because those are the flags the user can toggle
            # in-UI; read-only-on-disk falls through to the default.
            if new_parent.is_locked:
                return False, "Cannot drop: target layer is locked"
            if new_parent.is_muted:
                return False, "Cannot drop: target layer is muted"
            return False, "Cannot drop: target layer is not writable"

        # ── Step 46 · No-op same-position drop guard ────────────────
        # Between-drop that lands the source at its own current slot.
        # The adapter's ``move_sublayer`` is idempotent for null moves,
        # but the Step 43 command pipeline still records a history
        # entry; rejecting here keeps the undo stack clean and hands
        # the user a clear "already here" reason on the tooltip
        # instead of a silent-but-pointless gesture. Same-parent
        # pop-then-insert treats ``to_pos == from_pos`` and
        # ``to_pos == from_pos + 1`` as the same landing slot, so we
        # reject both variants.
        if drop_location >= 0 and source_parent is new_parent:
            try:
                current_pos = source_parent._sublayers.index(source)
            except ValueError:
                current_pos = -1
            if current_pos >= 0 and drop_location in (
                current_pos,
                current_pos + 1,
            ):
                return (
                    False,
                    "Cannot drop: source is already at this position",
                )
        return True, None

    # ── Step 45 external file drop ───────────────────────────────────

    def _can_insert_file_sublayer(
        self,
        target: LayerItem,
        drop_location: int,
        paths: List[str],
    ) -> Tuple[bool, Optional[str]]:
        """Validate a drop of OS-provided file path(s) onto ``target``.

        ``paths`` is the normalised list coming out of
        :func:`_extract_file_paths`. Every entry must carry a USD
        extension (``.usd`` / ``.usda`` / ``.usdc``, case-insensitive);
        mixed batches (e.g. one ``.usda`` and one ``.png``) reject the
        whole drop so the user sees a red-outline rejection instead of
        a partial commit in :meth:`drop`.

        The destination-parent rules mirror
        :meth:`_can_move_layer`: ``drop_location == -1`` targets the
        row itself as the new parent, ``drop_location >= 0`` targets
        the row's parent. ``target.parent is None`` reserved rows
        still accept drop-onto (the session / root layer both take
        sublayer inserts — only the move command forbids dragging the
        reserved rows themselves).
        """
        if not paths:
            return False, "Cannot drop: no file path provided"
        for path in paths:
            if not _is_valid_usd_path(path):
                return (
                    False,
                    "Cannot drop: only .usd, .usda and .usdc files are supported",
                )

        if drop_location == -1:
            new_parent: Optional[LayerItem] = target
        else:
            new_parent = target.parent
            if new_parent is None:
                return (
                    False,
                    "Cannot drop: top-level rows cannot accept a between-drop",
                )
        if not new_parent.is_writable:
            if new_parent.is_locked:
                return False, "Cannot drop: target layer is locked"
            if new_parent.is_muted:
                return False, "Cannot drop: target layer is muted"
            return False, "Cannot drop: target layer is not writable"
        return True, None

    def _perform_file_sublayer_drop(
        self,
        target: LayerItem,
        drop_location: int,
        paths: List[str],
    ) -> None:
        """Execute a validated external file drop onto ``target``.

        Re-validates through :meth:`_can_insert_file_sublayer` — the
        hover check may be stale by the time the mouse releases (e.g.
        a peer command locked the target mid-drag). Resolves the
        destination ``(parent_id, position)`` using the Step-43
        semantics, then pushes one :class:`InsertSublayerCommand` per
        path. Multi-file drops wrap the pushes in a single
        :meth:`UndoManager.begin_group` / :meth:`UndoManager.end_group`
        labelled ``"Insert files"`` so one Ctrl+Z rewinds the whole
        batch. Single-file drops skip the group wrapper and push
        directly — the user reads a "Insert foo.usda" entry in the
        history rather than a generic "Insert files" containing one.

        Headless construction (``app`` is ``None``) calls
        :meth:`~ovui_widgets.common.adapters.LayerStackAdapter.insert_sublayer`
        directly, matching the :meth:`drop` fallback so bare-model
        unit tests can exercise the drop path without fabricating an
        :class:`~ovui_widgets.common.undo.UndoManager`.
        """
        ok, reason = self._can_insert_file_sublayer(
            target, drop_location, paths
        )
        if not ok:
            if self._services is not None and reason:
                ErrorReporter.show_warning(reason)
            self._clear_drop_visual()
            return
        if drop_location == -1:
            parent_id = target.identifier
            position = -1
        else:
            new_parent = target.parent
            if new_parent is None:
                self._clear_drop_visual()
                return
            parent_id = new_parent.identifier
            position = drop_location

        # Clear the indicator before mutation so the row that carried
        # the highlight has a chance to repaint without it — each
        # :class:`InsertSublayerCommand` fires its own
        # :meth:`_item_changed` cascade.
        self._clear_drop_visual()
        self._insert_file_sublayers(parent_id, position, paths)

    def _insert_file_sublayers(
        self,
        parent_id: str,
        position: int,
        paths: List[str],
    ) -> None:
        """Push :class:`InsertSublayerCommand` entries for ``paths``.

        Shared by the on-row drop path and the empty-area drop
        handler in :class:`LayerWindow`. The empty-area path passes
        ``parent_id = root identifier`` and ``position = -1`` (append),
        so the same validation + command pipeline serves both
        gestures.

        ``position == -1`` means "append" — every subsequent
        command in a multi-file drop also uses ``-1`` so the files
        land in the order they were dropped. A positive ``position``
        is pre-incremented per file so the second file lands after
        the first one the group just pushed (otherwise every file
        would stack up at the same slot and the user would see the
        order reversed).
        """
        if self._destroyed or self._adapter is None or not paths:
            return
        services = self._services
        if services is None:
            for offset, path in enumerate(paths):
                insert_at = position if position < 0 else position + offset
                self._adapter.insert_sublayer(parent_id, insert_at, path)
            return
        if len(paths) == 1:
            cmd = InsertSublayerCommand(
                self._adapter,
                services.selection_bus,
                parent_id,
                position,
                paths[0],
            )
            services.undo_manager.push(cmd)
            return
        services.undo_manager.begin_group("Insert files")
        try:
            for offset, path in enumerate(paths):
                insert_at = position if position < 0 else position + offset
                cmd = InsertSublayerCommand(
                    self._adapter,
                    services.selection_bus,
                    parent_id,
                    insert_at,
                    path,
                )
                services.undo_manager.push(cmd)
        finally:
            services.undo_manager.end_group()

    def request_insert_file_sublayers_at_root(
        self, source: Any
    ) -> bool:
        """Drop hook for the window's empty-area drop target (Step 45).

        The ``ui.TreeView`` routes row / between-row drops through
        :meth:`drop`, but drops onto the scroll area below the last
        row land on the underlying :class:`ui.Rectangle` the window
        installs in :meth:`LayerWindow._build_ui`. This method is the
        bridge: parse the mime payload, validate the extensions, and
        append the files as sublayers of the root layer. Returns
        ``True`` when the drop was handled so tests can assert the
        validation branch. No-op on a destroyed / detached model.
        """
        if self._destroyed or self._adapter is None:
            return False
        root_item = self._root_item
        if root_item is None:
            return False
        paths = _extract_file_paths(source)
        if not paths:
            return False
        if not all(_is_valid_usd_path(p) for p in paths):
            if self._services is not None:
                ErrorReporter.show_warning(
                    "Cannot drop: only .usd, .usda and .usdc files are supported"
                )
            return False
        self._insert_file_sublayers(root_item.identifier, -1, paths)
        return True

    # ── Step 44 drop-visual helpers ──────────────────────────────────

    @property
    def drop_visual(self) -> DropVisualController:
        """The drop-visual controller the delegate consults for indicators.

        Exposed so tests can assert indicator state without reaching
        into the private slot, and so :class:`LayerDelegate` can read
        it without importing a second module for what is conceptually
        one piece of model state.
        """
        return self._drop_visual

    def _set_drop_visual_valid(
        self, target: LayerItem, drop_location: int
    ) -> None:
        """Mark ``target`` as a valid drop and repaint the affected rows."""
        previous = self._drop_visual.show_valid(target, drop_location)
        self._fire_drop_indicator_refresh(previous, target)

    def _set_drop_visual_rejected(
        self, target: LayerItem, drop_location: int, reason: str
    ) -> None:
        """Mark ``target`` as an invalid drop and repaint the affected rows."""
        previous = self._drop_visual.show_rejected(
            target, drop_location, reason
        )
        self._fire_drop_indicator_refresh(previous, target)

    def _clear_drop_visual(self) -> None:
        """Clear indicator state and repaint the formerly highlighted row."""
        previous = self._drop_visual.clear()
        self._fire_drop_indicator_refresh(previous, None)

    def _fire_drop_indicator_refresh(
        self,
        previous: Optional[LayerItem],
        current: Optional[LayerItem],
    ) -> None:
        """Emit ``_item_changed`` on the rows whose indicator just changed.

        Fires for the previously highlighted row (to clear its
        indicator) and the new row (to paint the new indicator) —
        skipping when they're the same item so ovui doesn't
        double-repaint a no-op hover refresh. No-op on a destroyed
        model so late callbacks are safe.
        """
        if self._destroyed:
            return
        if previous is current:
            if current is not None:
                self._item_changed(current)
            return
        if previous is not None:
            self._item_changed(previous)
        if current is not None:
            self._item_changed(current)

    # ── Accessors used by the window / tests ─────────────────────────

    @property
    def adapter(self) -> Optional[LayerStackAdapter]:
        return self._adapter

    @property
    def services(self) -> "Optional[WidgetServices]":
        """Return the :class:`WidgetServices` services object, or ``None`` in
        unit-test construction. Value models read this to push commands
        through ``services.undo_manager``; a ``None`` return means the
        model has no undo stack and write-paths should call the
        adapter directly. Step 11.2 hard-removed the legacy ``.app``
        property — there is no deprecation alias.
        """
        return self._services

    @property
    def root_item(self) -> Optional[LayerItem]:
        return self._root_item

    @property
    def session_item(self) -> Optional[LayerItem]:
        return self._session_item

    @property
    def settings(self) -> DefaultLayerSettings:
        return self._settings

    # ── Selection (LAYERS-PLAN Step 16) ──────────────────────────────

    @property
    def selected_items(self) -> List[Any]:
        """Currently selected rows — a defensive copy of the internal list.

        Entries are either :class:`LayerItem` or :class:`PrimSpecItem`;
        callers that only want one variety filter with ``isinstance``.
        """
        return list(self._selected_items)

    def set_selected_items(self, items: List[Any]) -> None:
        """Record the TreeView's new selection (Step 16 / Step 50).

        Accepts the union of :class:`LayerItem` and :class:`PrimSpecItem`
        — Phase J mixes prim-spec rows into the same tree, and the Del
        hotkey (Step 50) reads the prim-spec entries out of this list.
        Other row types are filtered out defensively. No event is fired
        yet; the listener API ships with :class:`LayerSelectionWatch`
        in Step 55. No-op on a destroyed model so a late callback from
        a torn-down widget is harmless.
        """
        if self._destroyed:
            return
        self._selected_items = [
            i for i in items if isinstance(i, (LayerItem, PrimSpecItem))
        ]

    # ── Name-search filter (LAYERS-PLAN Step 51) ─────────────────────

    @property
    def filter_text(self) -> str:
        """The active search text (empty string when no filter is set).

        Exposed for the window / tests so they can read the model's
        filter state without reaching into the private slot.
        """
        return self._filter_text

    def filter_by_text(self, text: str) -> None:
        """Set the active name-search filter (LAYERS-PLAN Step 51).

        Accepts a plain string; a ``None`` / empty value clears the
        filter. Match is case-insensitive substring against each layer's
        adapter ``get_display_name`` — prim-spec name matching is
        deferred (the plan lists it as an optional extension but Step
        51's Verify bullet checks layer-name filtering only).

        Clearing the filter (empty text) resets every
        :attr:`LayerItem.filtered` / :attr:`LayerItem.child_filtered`
        flag to ``False`` so a stale match-set does not bleed through
        the next paint. Applying a non-empty filter walks the root +
        session subtrees, sets ``_filtered`` on matching layers, and
        propagates ``_child_filtered`` up each matching row's ancestor
        chain so the ancestor-promotion contract ("parents of hits stay
        visible") the plan spells out falls out of the same walk.

        A single ``_item_changed(None)`` repaint is enough: the
        ``ui.TreeView`` re-queries :meth:`get_item_children` for every
        row, and our filter check there consumes the flags the walk
        just populated. Same-text calls short-circuit so a debounce
        flush that re-emits the current query does no work.
        """
        if self._destroyed:
            return
        new_text = text or ""
        if new_text == self._filter_text:
            return
        self._filter_text = new_text
        if new_text:
            lowered = new_text.lower()
            if self._root_item is not None:
                self._apply_filter(self._root_item, lowered)
            if self._session_item is not None:
                self._apply_filter(self._session_item, lowered)
        else:
            if self._root_item is not None:
                self._clear_filter_flags(self._root_item)
            if self._session_item is not None:
                self._clear_filter_flags(self._session_item)
        self._item_changed(None)

    def _apply_filter(self, item: LayerItem, lowered_text: str) -> bool:
        """Recursively mark ``item`` + descendants for ``lowered_text``.

        Returns ``True`` when ``item`` itself or any descendant matched,
        so the caller can decide whether ``item._child_filtered``
        should be ``True``. Walks sublayers depth-first; flag
        assignments rest on the lazily-built sublayer subtree so
        filtering a freshly constructed model does not re-hit the
        adapter.
        """
        self_match = lowered_text in item.display_name.lower()
        descendant_match = False
        for sublayer in item.sublayers:
            if self._apply_filter(sublayer, lowered_text):
                descendant_match = True
        item._filtered = self_match
        item._child_filtered = descendant_match
        return self_match or descendant_match

    def _clear_filter_flags(self, item: LayerItem) -> None:
        """Reset ``_filtered`` / ``_child_filtered`` on ``item`` + subtree.

        Called by :meth:`filter_by_text` when the filter is cleared so
        a subsequent "no filter active" paint does not see leftover
        match bits from the previous search.
        """
        item._filtered = False
        item._child_filtered = False
        for sublayer in item.sublayers:
            self._clear_filter_flags(sublayer)

    def _matches_filter(self, item: LayerItem) -> bool:
        """``True`` if ``item`` or any descendant passes the active filter.

        Queried by :meth:`get_item_children` and
        :meth:`can_item_have_children` while the filter is active; a
        ``False`` return means the subtree is entirely filtered out and
        the row should not be emitted / expandable.
        """
        return item._filtered or item._child_filtered

    def has_any_filter_match(self) -> bool:
        """``True`` iff the active filter leaves at least one row visible.

        Window's empty-state overlay reads this to decide whether to
        paint the "No matching layers" label. Trivially ``True`` when
        no filter is active — every row passes, so there is never an
        empty state to show.
        """
        if not self._filter_text:
            return True
        if self._root_item is not None and self._matches_filter(self._root_item):
            return True
        if (
            self._session_item is not None
            and self._settings.show_session_layer
            and self._matches_filter(self._session_item)
        ):
            return True
        return False

    # ── Settings-change notification (LAYERS-PLAN Step 52) ───────────

    def _on_settings_changed(self, _key: str, _value: Any) -> None:
        """Handle a persistent :class:`LayerSettings` key change.

        Fires from the :class:`Settings` subscriber thread (same thread
        as the mutation in practice — :class:`Settings.set` invokes
        subscribers synchronously). Triggers a full
        ``_item_changed(None)`` so ``ui.TreeView`` re-queries
        :meth:`get_item_children` and the new toggle takes effect on
        the next paint without a manual rebuild call.

        Prim-spec caches are also invalidated because
        ``show_layer_contents`` reshapes each layer's child list —
        expanding a layer whose stale cache still held prim specs
        after the flag flipped off would paint rows that should have
        disappeared. Walking the subtree costs pennies (the cache is
        already populated) and guarantees the next paint reflects the
        live setting.
        """
        self.refresh_layer_contents()

    def refresh_layer_contents(self) -> None:
        """Force prim-spec rows to re-query the backing layer stack.

        Stage-level resyncs can add or remove prim specs without changing the
        sublayer structure. If the tree already cached an empty root branch,
        a later Create-menu prim must invalidate that cache so Layers reflects
        the authored specs on the next paint.
        """
        if self._destroyed:
            return
        if self._root_item is not None:
            self._invalidate_prim_specs_walk(self._root_item)
        if self._session_item is not None:
            self._invalidate_prim_specs_walk(self._session_item)
        self._item_changed(None)

    def _invalidate_prim_specs_walk(self, layer_item: LayerItem) -> None:
        """Recursively invalidate prim-spec caches under ``layer_item``.

        Step 52 — a ``show_layer_contents`` flip must drop every
        cached prim-spec row beneath the tree so the subsequent
        :meth:`get_item_children` call re-computes the child list
        against the fresh flag. Sublayers share the per-item cache
        through their own :class:`LayerItem` so the walk fans out
        naturally.
        """
        self._invalidate_prim_specs(layer_item)
        for sublayer in layer_item.sublayers:
            self._invalidate_prim_specs_walk(sublayer)

    # ── Lifecycle ────────────────────────────────────────────────────

    def set_adapter(self, adapter: Optional[LayerStackAdapter]) -> None:
        """Re-target the model at ``adapter`` (or ``None`` to clear).

        LAYERS-PLAN Step 15 lifecycle: cancels the previous adapter's
        event subscription, walks the cached sublayer tree via
        :meth:`_destroy_subtree` to purge per-identifier caches, then
        either subscribes to the new adapter and loads its root + sub-
        layers, or leaves the tree empty when ``adapter`` is ``None``.
        Always fires ``item_changed(None)`` so any bound ``ui.TreeView``
        re-queries the top-level rows on the next paint.

        Safe on a destroyed model (no-op). Calling with the same live
        adapter still tears the tree down and re-loads — cheap and keeps
        the semantics identical to a detach+attach pair; callers that
        want an optimization should pass the same object through
        ``set_adapter`` exactly once.
        """
        if self._destroyed:
            return
        if self._event_sub is not None:
            self._event_sub.cancel()
            self._event_sub = None
        if self._root_item is not None:
            self._destroy_subtree(self._root_item)
        if self._session_item is not None:
            self._destroy_subtree(self._session_item)
        self._root_item = None
        self._session_item = None
        self._items_by_id.clear()
        self._sublayers_cache.clear()
        self._edit_target_identifier = ""
        # Selection references items from the previous adapter; drop
        # them so the retarget path cannot leak a LayerItem into the
        # new tree's ``_selected_items`` list (Step 16).
        self._selected_items = []
        # Drop any events queued against the old adapter's identifiers
        # so a post-swap flush doesn't try to route them through the
        # new tree (Step 32).
        self._pending_events = []
        self._flush_scheduled = False

        self._adapter = adapter
        if adapter is not None:
            try:
                self._event_sub = adapter.subscribe_events(self._on_layer_event)
            except NotImplementedError:
                self._event_sub = None
            self._reset_root()
            # Step 51 — re-apply the active filter across the freshly
            # built tree so a stage swap doesn't silently discard the
            # user's search text. The flag pass piggybacks on the
            # existing root / session items; nothing fires a second
            # ``_item_changed`` because the one below already forces a
            # full top-level re-query.
            if self._filter_text:
                lowered = self._filter_text.lower()
                if self._root_item is not None:
                    self._apply_filter(self._root_item, lowered)
                if self._session_item is not None:
                    self._apply_filter(self._session_item, lowered)
        self._item_changed(None)
        # Step 35 — the Save-All badge follows the new stack's dirty
        # state; re-reading ``get_value_as_bool`` on the next paint is
        # enough, but we fire ``_value_changed`` so any subscriber
        # (toolbar toggle, test harness) sees the swap immediately
        # without waiting for another event.
        if self._save_all_model is not None:
            self._save_all_model._value_changed()

    def destroy(self) -> None:
        """Tear down the model and release every adapter resource.

        Idempotent: subsequent calls are no-ops. Cancels the event
        subscription, walks the full subtree through
        :meth:`_destroy_subtree` (Step 14), nulls every top-level
        reference, and drops the adapter handle so garbage collection
        can reclaim the graph. The model must not receive further
        events after :meth:`destroy` — :meth:`_on_layer_event` short-
        circuits defensively on a destroyed or rootless state to guard
        against a late callback that slipped past unsubscribe.
        """
        if self._destroyed:
            return
        if self._event_sub is not None:
            self._event_sub.cancel()
            self._event_sub = None
        # Step 52 — release every persistent-settings subscription so
        # the store does not keep a bound method alive on the dead
        # model (which would both leak the model and fire
        # ``_item_changed`` into a torn-down tree).
        for sub in self._settings_subs:
            sub.cancel()
        self._settings_subs = []
        if self._root_item is not None:
            self._destroy_subtree(self._root_item)
        if self._session_item is not None:
            self._destroy_subtree(self._session_item)
        self._root_item = None
        self._session_item = None
        self._items_by_id.clear()
        self._sublayers_cache.clear()
        self._edit_target_identifier = ""
        self._selected_items = []
        self._pending_events = []
        self._flush_scheduled = False
        # Drop the Save-All singleton so the destroyed model cannot
        # be reached through a stray toolbar reference after destroy.
        self._save_all_model = None
        # Clear the drop-visual controller so a late hover callback
        # (ovui doesn't emit a "drag cancelled" event, so it can
        # arrive after destroy) doesn't leave an item reference
        # pinned on the torn-down controller.
        self._drop_visual.clear()
        self._adapter = None
        self._destroyed = True

    # ── Internal machinery ───────────────────────────────────────────

    def _reset_root(self) -> None:
        """Rebuild the top-level items and their sublayer subtrees.

        The session-layer toggle gates *rendering* inside
        :meth:`get_item_children`, not construction, so flipping the
        setting doesn't thrash the cache — that matches how Kit's own
        ``LayerModel`` handles it (LAYERS-WINDOW-ARCHITECTURE §16.7).
        Step 14 extends this with a recursive :meth:`_load_sublayers`
        pass so every descendant layer appears as its own tree row.
        """
        self._items_by_id.clear()
        self._sublayers_cache.clear()

        try:
            root_handle = self._adapter.get_root_layer()
        except NotImplementedError:
            self._root_item = None
            self._session_item = None
            self._edit_target_identifier = ""
            return
        self._root_item = LayerItem(self._adapter, root_handle.identifier)
        self._items_by_id[root_handle.identifier] = self._root_item
        self._sublayers_cache[root_handle.identifier].append(self._root_item)
        self._load_sublayers(self._root_item)

        session_handle = self._adapter.get_session_layer()
        if session_handle is not None:
            self._session_item = LayerItem(
                self._adapter,
                session_handle.identifier,
                is_session_layer=True,
            )
            self._items_by_id[session_handle.identifier] = self._session_item
            self._sublayers_cache[session_handle.identifier].append(
                self._session_item
            )
            self._load_sublayers(self._session_item)
        else:
            self._session_item = None

        # Edit-target tracking (LAYERS-PLAN Step 24). Resetting to the
        # empty string here — rather than copying the adapter snapshot
        # straight into ``_edit_target_identifier`` — lets
        # :meth:`_update_edit_target` perform a clean "no old target →
        # fresh target" transition that marks the new items *and* walks
        # the ancestor chain to populate ``_has_edit_target_descendant``.
        # The previous Step-13 path stashed the identifier but never
        # pushed the flag, so the Step-18 name suffix stayed silent
        # until an explicit ``adapter.set_edit_target`` event fired.
        self._edit_target_identifier = ""
        self._update_edit_target(self._adapter.get_edit_target_identifier())

    def _load_sublayers(self, layer_item: LayerItem) -> bool:
        """Materialise ``layer_item``'s sublayer subtree from the adapter.

        Returns ``True`` when the direct-child list actually changed
        (added, removed, or reordered). Walks in depth-first order so a
        single top-level call populates every descendant. Previously
        materialised children are reused by identifier to preserve
        value-model bindings and flag-cache state across structural
        rebuilds; orphans (children that vanished from the adapter's
        list) are destroyed via :meth:`_destroy_subtree` so the
        per-identifier caches don't leak stale rows.

        Cycle guard (LAYERS-WINDOW-ARCHITECTURE §16.8 / plan §14): walk
        the parent chain looking for a matching identifier. If we find
        one, skip this sublayer — USD allows cyclic sublayer references
        (they just emit a composition error) and the tree must stop
        recursing rather than blow the stack.
        """
        sublayer_ids = self._adapter.get_sublayer_identifiers(
            LayerHandle(layer_item.identifier)
        )

        previous = layer_item._sublayers
        old_by_id: Dict[str, LayerItem] = {s.identifier: s for s in previous}
        new_sublayers: List[LayerItem] = []
        changed = len(sublayer_ids) != len(previous)

        for idx, sid in enumerate(sublayer_ids):
            # Cycle guard — walk parent chain for the same identifier.
            ancestor: Optional[LayerItem] = layer_item
            while ancestor is not None and ancestor.identifier != sid:
                ancestor = ancestor.parent
            if ancestor is not None:
                continue

            existing = old_by_id.pop(sid, None)
            if existing is not None:
                sublayer = existing
                if idx >= len(previous) or previous[idx] is not existing:
                    changed = True
            else:
                sublayer = LayerItem(self._adapter, sid, parent=layer_item)
                self._sublayers_cache[sid].append(sublayer)
                # First appearance of this identifier anywhere in the
                # tree wins the fast-path lookup slot. Later clones stay
                # reachable through ``_sublayers_cache``.
                self._items_by_id.setdefault(sid, sublayer)
                changed = True

            sublayer.refresh_flags()
            self._load_sublayers(sublayer)
            new_sublayers.append(sublayer)

        for orphan in old_by_id.values():
            self._destroy_subtree(orphan)
            changed = True

        layer_item._sublayers = new_sublayers
        return changed

    def _destroy_subtree(self, item: LayerItem) -> None:
        """Detach ``item`` and every descendant from the per-id caches.

        Called by :meth:`_load_sublayers` when the adapter drops a
        sublayer; Step 15 will also call it from :meth:`destroy` to
        purge the full tree. When the removed instance owned the
        ``_items_by_id`` slot for its identifier, promote another
        cached instance (same layer sublayered in a different parent)
        into that slot so subsequent flag events still land on a live
        row.
        """
        for child in list(item._sublayers):
            self._destroy_subtree(child)
        item._sublayers = []
        # Step 48 — release the cached prim-spec subtree so a detached
        # layer does not pin a chain of :class:`PrimSpecItem` instances
        # through ``_prim_specs``. ``invalidate_prim_specs`` resets the
        # sentinel so the cache is correctly marked "not loaded" even
        # though the item is about to drop out of the tree entirely.
        self._invalidate_prim_specs(item)

        cache = self._sublayers_cache.get(item.identifier)
        if cache is not None and item in cache:
            cache.remove(item)
            if not cache:
                self._sublayers_cache.pop(item.identifier, None)

        if self._items_by_id.get(item.identifier) is item:
            remaining = self._sublayers_cache.get(item.identifier)
            if remaining:
                self._items_by_id[item.identifier] = remaining[0]
            else:
                self._items_by_id.pop(item.identifier, None)

    def _update_edit_target(self, new_id: str) -> None:
        """Swap the tracked edit-target identifier to ``new_id``.

        LAYERS-PLAN Step 24 — fan the change across every clone of the
        old and new target identifiers and propagate the
        ``_has_edit_target_descendant`` flag up each clone's parent
        chain:

        1. **No-op** when ``new_id`` equals the stored identifier — the
           adapter re-emits ``EDIT_TARGET_CHANGED`` on a few edge paths
           (session swap, live-session join) even when the effective
           target didn't change, and re-firing the UI repaint is pure
           churn.
        2. **Clear phase.** For every clone of the *old* identifier
           (found via ``_sublayers_cache``), unset ``_is_edit_target``
           and walk the parent chain clearing
           ``_has_edit_target_descendant``. Only one edit target exists
           at a time, so the "some other branch still contains an edit
           target?" check becomes trivial: we're about to set the new
           target's ancestor flags, so any ancestor that should stay
           ``True`` will get re-set below. Visited ancestors are
           recorded so Step 26's notification pass can repaint them.
        3. **Set phase.** For every clone of the *new* identifier, set
           ``_is_edit_target = True`` and walk its parent chain marking
           ``_has_edit_target_descendant = True``. An ancestor shared
           between the old and new chains ends up at the intended
           value because the set phase runs after the clear phase, and
           the shared ancestor is entered once in the notification set
           so the user sees no flicker from a clear → set toggle.
        4. **Notify.** Fire ``_value_changed()`` on the
           :class:`LayerNameValueModel` of every *target* clone (old
           and new) so the Step-18 suffix (``(Authoring Layer)``)
           appears / disappears without a full-tree rebuild. Fire
           ``_item_changed(item)`` on the same clones so ovui repaints
           the row. Step 26 additionally fires ``_item_changed(ancestor)``
           on every ancestor whose ``_has_edit_target_descendant`` flag
           was touched by either the clear or the set phase, so the
           half-green leading icon flips on / off without waiting for
           a structural rebuild. Ancestors are deduplicated by object
           identity (``id(ancestor)``) so a sibling swap that re-enters
           the same root only fires once.

        Cloned layers: a single identifier may sit in ``_sublayers_cache``
        under multiple parents because USD allows the same layer to be
        sublayered in more than one place. Every clone flips in
        lockstep; otherwise a user editing "layer A" would see the
        authoring-layer badge on only one of its rows.

        Safe on an empty tree: ``_sublayers_cache.get(id, ())`` returns
        the empty tuple for unknown ids, so the clear / set loops are
        no-ops during initial construction when ``_edit_target_identifier``
        starts at ``""``.
        """
        old_id = self._edit_target_identifier
        if new_id == old_id:
            return

        touched_targets: List[LayerItem] = []
        # Ancestors dedup by ``id(ancestor)`` rather than a ``set`` of
        # items: :class:`ui.AbstractItem` makes no hashability guarantee
        # we want to rely on across future ovui versions, and the
        # object-identity semantics are what the dedup actually means
        # here ("same row already queued, don't fire twice").
        touched_ancestor_ids: set = set()
        touched_ancestors: List[LayerItem] = []

        def _record_ancestors(start: Optional[LayerItem]) -> None:
            ancestor = start
            while ancestor is not None:
                if id(ancestor) not in touched_ancestor_ids:
                    touched_ancestor_ids.add(id(ancestor))
                    touched_ancestors.append(ancestor)
                ancestor = ancestor.parent

        for item in self._sublayers_cache.get(old_id, ()):
            item._is_edit_target = False
            touched_targets.append(item)
            ancestor = item.parent
            while ancestor is not None:
                ancestor._has_edit_target_descendant = False
                ancestor = ancestor.parent
            _record_ancestors(item.parent)

        self._edit_target_identifier = new_id

        for item in self._sublayers_cache.get(new_id, ()):
            item._is_edit_target = True
            touched_targets.append(item)
            ancestor = item.parent
            while ancestor is not None:
                ancestor._has_edit_target_descendant = True
                ancestor = ancestor.parent
            _record_ancestors(item.parent)

        for item in touched_targets:
            name_model = item._name_model
            if name_model is not None:
                # Only the name column shows the authoring-layer suffix
                # in Step 24; poking its value model is enough to repaint
                # the label. Step 25 added the row-level green overlay
                # and the full-row ``_item_changed`` fire below re-runs
                # ``build_widget`` so the overlay swap paints cleanly.
                name_model._value_changed()
            self._item_changed(item)

        # Step 26: ancestors repaint so the half-green leading icon
        # (``Layers.LeadingIcon::has_descendant``) flips without
        # waiting for a structural rebuild. Already-rendered ancestor
        # rows were silent through Step 25 — the Step-25 delegate
        # resolved the icon on first paint from the flag set here,
        # but a mid-session edit-target swap would leave a stale
        # full-/half-/no-green icon until the user forced a repaint
        # (hover, expand, scroll). Skip ancestors that were already
        # notified as a target clone (root → child swap — root sits in
        # both sets): firing twice re-runs ``build_widget`` twice for
        # the same row.
        target_ids = {id(t) for t in touched_targets}
        for ancestor in touched_ancestors:
            if id(ancestor) in target_ids:
                continue
            self._item_changed(ancestor)

    # Step 32 replaces the Step-13 per-event dispatcher with a two-pass
    # flush: events queue into ``_pending_events`` on whatever thread
    # fires them, a single ``call_later(0, …)`` schedules the flush on
    # the main thread, and the flush processes a *batch* — structural
    # first, then per-event targeted updates, then a dirty-bit poll.
    # This preserves non-structural events in the same frame as a
    # structural one (Logic F1) and fans every event across every
    # cached clone of an identifier.

    def _on_layer_event(self, event: LayerEvent) -> None:
        """Enqueue an adapter event for the next frame's flush.

        Step 32 batching — every incoming event is deferred to a
        single per-frame :meth:`_flush_events` call scheduled through
        :attr:`Application.call_later`. A busy stage can fire hundreds
        of DIRTY / MUTE / LOCK notifications per frame; the previous
        Step-13 dispatcher would rebuild the tree once per event,
        which is the pathology LAYERS-WINDOW-ARCHITECTURE §34.14
        flags. The flush itself lives on a single thread and consumes
        the whole queue in one pass.

        Step 15 defensive short-circuit: if the model has been
        destroyed or detached from its adapter (``_adapter`` is
        ``None``) a late callback that slipped past the subscription
        cancel still must not reach into a nulled root.
        """
        if (
            self._destroyed
            or self._adapter is None
            or self._root_item is None
        ):
            return
        self._pending_events.append(event)
        if self._flush_scheduled:
            return
        self._flush_scheduled = True
        # Real frame loop — defer through ``call_later`` so many
        # events in the same tick coalesce into one
        # ``_flush_events`` call. Headless tests construct the model
        # with ``services=None`` (or a ``SimpleNamespace`` lacking
        # ``call_later``); keep the synchronous per-event semantics
        # those tests were written against by flushing inline. Either
        # path hits the same ``_flush_events`` body so batching and
        # single-event dispatch share exactly one implementation.
        services = self._services
        call_later = getattr(services, "call_later", None) if services else None
        if callable(call_later):
            call_later(0.0, self._flush_events)
        else:
            self._flush_events()

    def _flush_events(self) -> None:
        """Process the queued batch of adapter events (Step 32).

        Three-pass algorithm:

        1. **Structural pass.** If *any* ``SUBLAYERS_CHANGED`` event
           is in the batch, reload the sublayer subtree under the
           existing root / session items (rather than re-minting the
           items themselves — existing references stay valid) and
           force edit-target propagation so the
           ``_has_edit_target_descendant`` chain is rebuilt on the
           fresh child instances. Unlike the Step-13 handler this
           does **not** ``return`` — the per-event pass below still
           runs so a non-structural event in the same batch is not
           silently dropped (Logic F1).

        2. **Targeted event pass.** Iterate the batch once; each
           event type gets a narrow handler that invalidates the
           affected flag cache on every cached clone of the
           identifier and fires :meth:`_notify_model` on the right
           per-column value model(s). ``MUTE_STATE_CHANGED`` and
           ``LOCK_STATE_CHANGED`` also cascade into descendants (so
           the Step-32 ``muted_or_parent_muted`` /
           ``locked_or_parent_locked`` chain repaints every row
           beneath a toggled ancestor) and call
           :meth:`_maybe_auto_heal_edit_target` after every mute /
           lock toggle so a user muting the authoring layer does not
           fall into USD's silent-edit-rejection trap
           (LAYERS-WINDOW-ARCHITECTURE §37.9 #9).
           ``INFO_CHANGED`` pokes the name model only — v1 has no
           metadata-driven visuals; Property-panel integration in
           Phase L will subscribe to the adapter directly.
           ``FILE_PERMISSION_CHANGED`` invalidates the flag cache
           and repaints the name / save / lock columns so a file
           flipping to read-only on disk surfaces immediately.

        3. **Dirty-poll safety net.** Some USD backends drop
           ``DIRTY_STATE_CHANGED`` notices on very fast edit bursts
           (LAYERS-WINDOW-ARCHITECTURE §34.14 / Kit's own FIXME).
           Polling every cached layer once per flush catches the
           missed transitions at O(k) per frame where k is the
           cached-layer count.

        Late-fire guard: ``_flush_events`` always clears
        :attr:`_flush_scheduled` so a subsequent event schedules a new
        flush. When the model was destroyed between schedule and tick
        the method drops any residual events and exits without
        touching a nulled root.
        """
        self._flush_scheduled = False
        if (
            self._destroyed
            or self._adapter is None
            or self._root_item is None
        ):
            self._pending_events = []
            return
        events, self._pending_events = self._pending_events, []
        if not events:
            return

        structural = any(
            e.event_type is LayerEventType.SUBLAYERS_CHANGED
            for e in events
        )

        if structural:
            # Step 48 — invalidate every cached prim-spec subtree
            # ahead of the sublayer reload. A structural event is the
            # widest signal the adapter emits on prim-spec mutations
            # in v1 (there is no dedicated ``PRIM_SPECS_CHANGED``
            # event yet), so clearing the caches keeps the tree
            # consistent with the backing stage after import /
            # remove / flatten / merge operations. The invalidation
            # is cheap — only materialised branches carry state.
            for layer_item in self._items_by_id.values():
                self._invalidate_prim_specs(layer_item)
            self._load_sublayers(self._root_item)
            if self._session_item is not None:
                self._load_sublayers(self._session_item)
            # Force a clean re-propagation so the
            # ``_has_edit_target_descendant`` chain rebuilds on any
            # fresh :class:`LayerItem` instances created by
            # :meth:`_load_sublayers` (Logic U4).
            current_edit = self._adapter.get_edit_target_identifier()
            self._edit_target_identifier = ""
            self._update_edit_target(current_edit)
            # Step 51 — structural events can add / remove sublayers
            # whose name may match the active filter, so re-walk the
            # match set across the freshly loaded subtree before the
            # ``_item_changed(None)`` below drives the TreeView to
            # re-query :meth:`get_item_children`.
            if self._filter_text:
                lowered = self._filter_text.lower()
                self._apply_filter(self._root_item, lowered)
                if self._session_item is not None:
                    self._apply_filter(self._session_item, lowered)
            self._item_changed(None)

        mute_or_lock_fired = False
        for event in events:
            et = event.event_type
            if et is LayerEventType.SUBLAYERS_CHANGED:
                # Handled by the structural pass; nothing to add here.
                continue

            if et is LayerEventType.EDIT_TARGET_CHANGED:
                self._update_edit_target(
                    self._adapter.get_edit_target_identifier()
                )
                continue

            if et is LayerEventType.DIRTY_STATE_CHANGED:
                for identifier in event.identifiers:
                    clones = self._sublayers_cache.get(identifier, ())
                    if not clones:
                        continue
                    # Sync the cached dirty bit to the adapter's
                    # truth so the poll pass below doesn't fire a
                    # redundant ``_value_changed`` on the same clone
                    # this frame (every notify is a row repaint).
                    # The rest of the flag cache is marked stale —
                    # a dirty flip often coincides with writability
                    # changes at the USD layer, and the next read
                    # via the property accessors re-queries cheaply.
                    adapter_dirty = self._adapter.is_dirty(
                        LayerHandle(identifier)
                    )
                    for clone in clones:
                        clone._is_dirty = adapter_dirty
                        clone._flags_dirty = True
                        self._notify_model(clone, "save")
                continue

            if et is LayerEventType.MUTE_STATE_CHANGED:
                mute_or_lock_fired = True
                for identifier in event.identifiers:
                    for clone in self._sublayers_cache.get(
                        identifier, ()
                    ):
                        clone.invalidate_flags()
                        self._notify_model(
                            clone, "name", "local_mute", "save"
                        )
                        # Cascade: muting a parent dims every
                        # descendant row (LAYERS-WINDOW-ARCHITECTURE
                        # §17.4). ``muted_or_parent_muted`` walks the
                        # parent chain on read, so the descendants'
                        # *own* flag cache doesn't need to change —
                        # we only need to invalidate it and poke
                        # their name models so the Label re-queries
                        # the color role on the next paint.
                        self._cascade_invalidate_and_notify(
                            clone, ("name",)
                        )
                continue

            if et is LayerEventType.LOCK_STATE_CHANGED:
                mute_or_lock_fired = True
                for identifier in event.identifiers:
                    for clone in self._sublayers_cache.get(
                        identifier, ()
                    ):
                        clone.invalidate_flags()
                        self._notify_model(clone, "name", "lock", "save")
                        self._cascade_invalidate_and_notify(
                            clone, ("name",)
                        )
                continue

            if et is LayerEventType.INFO_CHANGED:
                # v1 has no info-driven visuals; the name model
                # re-queries display-name state so future
                # metadata-backed suffix toggles (e.g. a "Show File
                # Extension" user setting) pick up mid-session edits
                # without a tree-wide rebuild (Completeness M-11).
                for identifier in event.identifiers:
                    for clone in self._sublayers_cache.get(
                        identifier, ()
                    ):
                        # INFO_CHANGED can carry the ``missing``
                        # token from the mock adapter — mirror the
                        # Step 32 plan and invalidate the flag
                        # cache so the next read picks up any
                        # metadata-driven bit flip (missing, read
                        # only) without waiting for an adapter-
                        # specific event.
                        clone.invalidate_flags()
                        self._notify_model(clone, "name")
                continue

            if et is LayerEventType.FILE_PERMISSION_CHANGED:
                # An on-disk permission flip reshapes writability:
                # the save indicator gates on writability and the
                # name label's ``get_color_role`` can switch to
                # ``disabled`` when the file becomes read-only.
                # The *lock* column represents the Kit-level lock
                # bit (custom-data backed), which a disk-permission
                # flip does not touch — so its value model stays
                # silent here.
                for identifier in event.identifiers:
                    for clone in self._sublayers_cache.get(
                        identifier, ()
                    ):
                        clone.invalidate_flags()
                        self._notify_model(clone, "name", "save")
                continue

            # OUTDATE_STATE_CHANGED: reserved for Phase M (outdate
            # badge). Swallow silently — the enum value exists so
            # the UI can stub-handle it.

        if mute_or_lock_fired:
            # Auto-heal after the per-event loop has run so a mute
            # and a follow-up unmute of the same layer in the same
            # batch cancel out before the heal decides to move the
            # edit target.
            self._maybe_auto_heal_edit_target()

        # Dirty-poll safety net — see docstring intro for rationale.
        self._poll_dirty_state()

        # Step 35 — the Save-All badge aggregates across every layer in
        # the stack, so any event that could flip a dirty bit or change
        # the layer set invalidates the aggregate. ``_value_changed``
        # does not walk the stack itself; ovui re-queries
        # :meth:`SaveAllValueModel.get_value_as_bool` on the next paint,
        # so the poke stays cheap even when the toolbar is off-screen.
        if self._save_all_model is not None:
            self._save_all_model._value_changed()

    def _notify_model(self, item: LayerItem, *model_names: str) -> None:
        """Fire ``_value_changed`` on named lazy-constructed value
        models and ``_item_changed`` on the tree view for ``item``.

        Models that weren't constructed yet (because the column was
        never rendered — Logic F4) are skipped without error.
        ``_item_changed`` always fires so ovui rebuilds the row's
        cells even if every column was still collapsed at the time
        of the event.
        """
        for name in model_names:
            model = getattr(item, f"_{name}_model", None)
            if model is not None:
                model._value_changed()
        self._item_changed(item)

    def _cascade_invalidate_and_notify(
        self,
        item: LayerItem,
        notify: Tuple[str, ...],
    ) -> None:
        """Walk ``item``'s sublayer subtree, invalidating flag caches
        and firing :meth:`_notify_model` on each descendant.

        Implements Completeness E-5: muting or locking a parent must
        re-render every descendant row so the Step-32 ``disabled``
        color role kicks in (via ``muted_or_parent_muted`` /
        ``locked_or_parent_locked``). Descendants' own per-layer
        ``is_muted`` / ``is_locked`` bits do not change, but the
        cached flag snapshot is invalidated defensively — the next
        read is a cheap dict lookup and the cascade query walks the
        parent chain anyway.
        """
        for child in item.sublayers:
            child.invalidate_flags()
            self._notify_model(child, *notify)
            self._cascade_invalidate_and_notify(child, notify)

    def _poll_dirty_state(self) -> None:
        """Per-frame dirty-bit reconciliation (Step 32, Kit parity).

        USD's ``DIRTY_STATE_CHANGED`` notice is occasionally lost in
        tight edit bursts — LAYERS-WINDOW-ARCHITECTURE §34.14 calls
        out Kit's own ``_update_dirtiness`` as a FIXME band-aid. We
        match that shape: for every cached layer, compare the
        adapter's truth against the item's cached bit and synthesise
        a ``_notify_model`` when they disagree. The diff is run even
        when :attr:`LayerItem._flags_dirty` is set — a stale cache
        that happens to still agree with the adapter is fine to
        leave, but a stale cache that disagrees is precisely the
        missed-event case this poll exists to catch. The cost is one
        adapter call per cached layer per flush — O(k) where k is
        the cached-layer count.
        """
        for identifier, clones in list(self._sublayers_cache.items()):
            layer_handle = LayerHandle(identifier)
            adapter_dirty = self._adapter.is_dirty(layer_handle)
            for clone in clones:
                # Bypass the property accessor to avoid churning
                # through ``refresh_flags`` for every cached layer
                # per frame — we only need the cached bit.
                if clone._is_dirty != adapter_dirty:
                    clone._is_dirty = adapter_dirty
                    # Don't flip ``_flags_dirty``: the other five
                    # bits may still be legitimately stale from
                    # their own invalidation path, and the next
                    # read via the property accessor will refresh
                    # them regardless.
                    self._notify_model(clone, "save")

    def _maybe_auto_heal_edit_target(self) -> None:
        """Auto-heal the edit target when the user mutes or locks it.

        LAYERS-WINDOW-ARCHITECTURE §16.6 / §37.9 #9 — USD silently
        rejects edits on a muted layer, and the Kit lock bit is
        advisory but UI-enforced. If the user toggles one of those
        on the current edit target, subsequent attribute edits
        vanish without warning. We repair the state by pushing a
        :class:`SetEditTargetCommand` back to the root layer (a
        safe baseline: root is never muted or locked in a healthy
        stack) and surfacing a warning status message so the user
        knows why authoring jumped.

        Headless / test construction goes through the adapter
        directly because there's no :class:`Application` (no undo
        stack to push to, no status bar to warn through) — this
        mirrors :meth:`LocalMuteValueModel.set_value`'s fallback.
        """
        current_id = self._edit_target_identifier
        if not current_id:
            return
        handle = self._adapter.find_layer(current_id)
        if handle is None:
            return
        muted = self._adapter.is_muted(handle)
        locked = self._adapter.is_locked(handle)
        if not (muted or locked):
            return
        root_id = self._root_item.identifier
        if current_id == root_id:
            # Root somehow became muted or locked — nothing safer to
            # fall back to. Leave the target in place rather than
            # churn; the user sees the ``disabled`` color role on
            # the authoring row which is itself the warning signal.
            return
        reason = "muted" if muted else "locked"
        services = self._services
        if services is None:
            self._adapter.set_edit_target(root_id)
            return
        cmd = SetEditTargetCommand(
            self._adapter,
            services.selection_bus,
            root_id,
        )
        services.undo_manager.push(cmd)
        # Status toast — the status bar is only live after the full
        # Application startup; in any other context the reporter's
        # fallback prints to stderr which is fine for tests.
        try:
            from ovui_widgets.common.error_reporter import ErrorReporter

            ErrorReporter.show_warning(
                f"Authoring Layer switched to root — "
                f"previous target is now {reason}"
            )
        except Exception:
            # Status UI is a visual nicety; never let a reporter
            # failure mask the actual auto-heal.
            pass

    # ── Save flow (LAYERS-PLAN Step 34) ──────────────────────────────

    def _request_save(self, item: LayerItem) -> None:
        """Route a save click on ``item`` to the command pipeline.

        Step 34 — the per-row floppy in column 2 drives this. For a
        concrete (non-anonymous) layer we push a :class:`SaveLayerCommand`
        through :attr:`Application.undo_manager`. The command is
        ``non_undoable`` so it executes, reports any
        :class:`IOError` / :class:`PermissionError` through the shared
        :class:`~ovui_widgets.common.error_reporter.ErrorReporter`, and clears the
        redo stack without landing on the undo stack (matches the Kit
        convention — users never see an "Undo Save" entry).

        Anonymous layers carry no file path: a plain save would fail
        before it hit disk. Step 36 routes them to
        :meth:`_request_save_as` which opens a file picker, captures
        the chosen path, and pushes a
        :class:`~ovui_widgets.layers.commands.SaveLayerAsCommand` that writes
        the file and rewrites every parent sublayer reference to the
        new identifier in one undoable unit.

        Headless / unit-test construction (``app`` is ``None``) falls
        back to a direct adapter call so the value model stays
        testable without faking an ``UndoManager`` — mirrors the
        fallback in :meth:`LocalMuteValueModel.set_value`.
        """
        if self._destroyed or self._adapter is None:
            return
        if item.is_anonymous:
            self._request_save_as(item)
            return
        services = self._services
        if services is None:
            self._adapter.save_layer(item.identifier)
            return
        cmd = SaveLayerCommand(
            self._adapter,
            services.selection_bus,
            item.identifier,
            ErrorReporter,
        )
        services.undo_manager.push(cmd)

    # ── Save-All flow (LAYERS-PLAN Step 35) ──────────────────────────

    def get_save_all_model(self) -> SaveAllValueModel:
        """Return the cached aggregate :class:`SaveAllValueModel`.

        The Save-All button is window-scoped, not row-scoped, so the
        model lives on the :class:`LayerModel` rather than on any
        :class:`LayerItem`. Constructed lazily on first call so a
        headless :class:`LayerModel` (tests that never touch the
        toolbar) never pays for it; subsequent calls return the same
        instance so :meth:`_flush_events`' repaint-poke reaches the
        widget the window built around it.
        """
        if self._save_all_model is None:
            self._save_all_model = SaveAllValueModel(self)
        return self._save_all_model

    def _request_save_all(self) -> None:
        """Save every dirty, non-anonymous layer in a single group.

        Step 35 — the Save-All toolbar button drives this. Each
        :class:`SaveLayerCommand` is ``non_undoable`` (Step 33) so
        the group wrapper exists *for batching*, not for undo
        history — :meth:`UndoManager.end_group` sees an empty
        commands list and auto-discards the group rather than
        appending a no-op entry.

        Anonymous layers are excluded (Step 36 will route them
        through a save-as dialog); the filter lives in
        :meth:`SaveAllValueModel.get_dirty_identifiers` so the
        badge and this click path use the exact same rule.

        No-op when nothing is dirty (prevents an empty ``begin / end``
        pair from firing a ``_notify`` on the undo stack) or when the
        model has been detached / destroyed.

        Headless fallback (``app`` is ``None``) calls
        :meth:`~ovui_widgets.common.adapters.LayerStackAdapter.save_layer`
        directly for each dirty identifier, mirroring
        :meth:`_request_save`'s unit-test-friendly path.
        """
        if self._destroyed or self._adapter is None:
            return
        if (
            self._before_save_all_fn is not None
            and self._before_save_all_fn() is False
        ):
            return
        dirty_ids = self.get_save_all_model().get_dirty_identifiers()
        if not dirty_ids:
            return
        services = self._services
        if services is None:
            for identifier in dirty_ids:
                self._adapter.save_layer(identifier)
            return
        services.undo_manager.begin_group("Save All")
        try:
            for identifier in dirty_ids:
                cmd = SaveLayerCommand(
                    self._adapter,
                    services.selection_bus,
                    identifier,
                    ErrorReporter,
                )
                services.undo_manager.push(cmd)
        finally:
            services.undo_manager.end_group()

    # ── Save-As flow (LAYERS-PLAN Step 36) ───────────────────────────

    def _request_save_as(
        self,
        item: LayerItem,
        replace_in_parent: bool = True,
    ) -> None:
        """Open a save-as file picker for ``item`` and execute save-as.

        Step 36 — anonymous layers (and, by explicit caller request,
        any concrete layer the user wants to clone to a new path)
        route through here. The flow is:

        1. Compute a sensible default filename (display name + the
           USD extension preferred by :mod:`ovui_widgets.common.file_dialogs`).
        2. Open a modal :func:`~ovui_widgets.common.file_dialogs.save_file_dialog`.
           While the user is interacting, this method returns — the
           save happens asynchronously in the callback.
        3. On Save, push a :class:`SaveLayerAsCommand` through
           :attr:`Application.undo_manager` so the parent-reference
           swap is undoable (the file write itself is not — see
           :class:`SaveLayerAsCommand` docstring).
        4. On Cancel, the callback is a no-op; nothing is pushed.

        ``replace_in_parent`` defaults to ``True`` because the
        anonymous-layer path is the primary driver — the whole
        point of saving an anonymous sublayer is so its parent
        keeps referencing the now-persisted file rather than an
        in-memory anon identifier the adapter will forget on stage
        close. Concrete "Save As…" gestures that want a clone
        without relinking the parent pass ``replace_in_parent=False``.

        No-op on a destroyed / detached model. When the file-dialog
        module cannot build a window (headless / event-loop-uninit
        contexts), the dialog's own cancel path fires and this
        method returns silently — callers should not rely on the
        command being pushed.
        """
        if self._destroyed or self._adapter is None:
            return
        services = self._services
        if services is None:
            # Headless tests drive the command directly — no dialog.
            return

        # Lazy import so the file_dialogs module only gets loaded
        # when a save-as is actually requested. Keeps pure unit-test
        # imports cheap and avoids a circular import between the
        # ovui_widgets.app and ovui_widgets.layers packages at module-load time.
        from ovui_widgets.common.file_dialogs import save_file_dialog

        default_name = _default_save_as_filename(item)

        def _on_selected(chosen_path: str) -> None:
            def _commit() -> None:
                self._perform_save_as(
                    item.identifier,
                    chosen_path,
                    replace_in_parent=replace_in_parent,
                )

            if os.path.exists(chosen_path):
                # Save As is the only Layers path allowed to overwrite a
                # separate filesystem artifact. Make that destructive edge
                # explicit and visible; Cancel leaves both disk and undo
                # history untouched.
                from ovui_widgets.common.dialogs import confirm_dialog

                confirm_dialog(
                    title="Replace Existing Layer",
                    message=(
                        f"A file already exists at {chosen_path!r}.\n"
                        "Replace it with this layer?"
                    ),
                    on_confirm=_commit,
                    confirm_label="Replace",
                    cancel_label="Cancel",
                )
                return
            _commit()

        save_file_dialog(
            title=f"Save '{item.display_name or item.identifier}' as...",
            default_name=default_name,
            on_selected=_on_selected,
        )

    def _perform_save_as(
        self,
        source_identifier: str,
        new_path: str,
        replace_in_parent: bool = True,
    ) -> None:
        """Push the :class:`SaveLayerAsCommand` for a selected path.

        Split out from :meth:`_request_save_as` so tests can drive
        the command-pipeline half without faking the file dialog:
        the dialog's ``on_selected`` callback is *exactly* a call
        to this method. Keeps the dialog a thin shell and the
        command wiring independently testable.

        Destroyed / detached / missing-adapter / missing-app guards
        match :meth:`_request_save` — a late click on a torn-down
        window must not reach a nulled adapter.
        """
        if self._destroyed or self._adapter is None:
            return
        services = self._services
        if services is None:
            return
        cmd = SaveLayerAsCommand(
            self._adapter,
            services.selection_bus,
            source_identifier,
            new_path,
            replace_in_parent=replace_in_parent,
            error_reporter=ErrorReporter,
        )
        services.undo_manager.push(cmd)


    # ── Remove / Reload flows (LAYERS-PLAN Step 37) ──────────────────

    def _request_remove_sublayer(
        self,
        parent_id: str,
        position: int,
    ) -> None:
        """Remove the sublayer at ``(parent_id, position)`` with dirty guard.

        Step 37 — this is the UI-facing entry point that a future
        context-menu "Remove Layer" action (Step 38) and any other
        remove gesture route through. The flow:

        1. Resolve the sublayer identifier from the adapter so we can
           look up its dirty state. A missing parent / out-of-range
           position silently no-ops (a late click after the stack
           shifted beneath us).
        2. Clean (non-dirty) layers skip the dialog entirely and push
           a :class:`RemoveSublayerCommand` straight through the
           undo manager — same shape as Step-30 behaviour.
        3. Dirty layers open
           :func:`~ovui_widgets.common.dialogs.confirm_dirty_remove_dialog`. The
           three buttons route to:

           - **Save & Remove** — push a :class:`SaveLayerCommand`
             followed by a :class:`RemoveSublayerCommand` inside an
             undo group labelled ``"Save & Remove"``. The save itself
             is ``non_undoable`` so the group ends up storing just
             the remove command for Undo history purposes.
           - **Remove Without Saving** — push a plain
             :class:`RemoveSublayerCommand` that discards the edits.
           - **Cancel** — no command pushed; the dialog dismissal
             leaves the stack unchanged.

        Headless / unit-test construction (``app`` is ``None``) falls
        back to a direct adapter ``remove_sublayer`` call for clean
        layers; dirty layers are left untouched because there is no
        dialog to prompt the user (a test that wants to exercise the
        dirty path passes ``app`` or drives
        :class:`RemoveSublayerCommand` with ``confirm_callback``
        directly).
        """
        if self._destroyed or self._adapter is None:
            return
        parent_handle = self._adapter.find_layer(parent_id)
        if parent_handle is None:
            return
        children = self._adapter.get_sublayer_identifiers(parent_handle)
        if position < 0 or position >= len(children):
            return
        child_id = children[position]
        child_handle = self._adapter.find_layer(child_id)
        is_dirty = (
            child_handle is not None
            and self._adapter.is_dirty(child_handle)
        )

        services = self._services
        if not is_dirty:
            if services is None:
                self._adapter.remove_sublayer(parent_id, position)
                return
            cmd = RemoveSublayerCommand(
                self._adapter,
                services.selection_bus,
                parent_id,
                position,
            )
            services.undo_manager.push(cmd)
            return

        if services is None:
            # No dialog to prompt through; leaving the dirty layer in
            # place matches the "abort on cancel" branch. Tests that
            # want the remove to proceed drive the command directly.
            return

        # Lazy import mirrors file_dialogs: the dialog module only
        # loads when a confirm-prompt is actually needed.
        from ovui_widgets.common.dialogs import confirm_dirty_remove_dialog

        layer_name = self._resolve_layer_display_name(child_id)

        def _on_save_and_remove() -> None:
            self._perform_save_and_remove(parent_id, position, child_id)

        def _on_remove_without_saving() -> None:
            self._perform_remove_sublayer(parent_id, position)

        confirm_dirty_remove_dialog(
            layer_name=layer_name,
            on_save_and_remove=_on_save_and_remove,
            on_remove_without_saving=_on_remove_without_saving,
        )

    def _perform_remove_sublayer(
        self,
        parent_id: str,
        position: int,
    ) -> None:
        """Push a :class:`RemoveSublayerCommand` without a confirm guard.

        Split out from :meth:`_request_remove_sublayer` so tests can
        drive the command half without fabricating a dialog click and
        so the dialog's callback stays a one-liner. Destroyed /
        detached / missing-adapter / missing-app guards match
        :meth:`_request_save`.
        """
        if self._destroyed or self._adapter is None:
            return
        services = self._services
        if services is None:
            self._adapter.remove_sublayer(parent_id, position)
            return
        cmd = RemoveSublayerCommand(
            self._adapter,
            services.selection_bus,
            parent_id,
            position,
        )
        services.undo_manager.push(cmd)

    def _perform_save_and_remove(
        self,
        parent_id: str,
        position: int,
        child_id: str,
    ) -> None:
        """Save ``child_id`` to disk, then remove it from the parent stack.

        Wraps a :class:`SaveLayerCommand` + :class:`RemoveSublayerCommand`
        pair in an undo group so Undo rewinds the remove as a single
        history entry. The save itself is ``non_undoable`` so the
        group collapses to the remove in the undo stack (Step 33).
        Anonymous layers cannot be saved directly — Save & Remove
        on an anonymous layer delegates the save to
        :meth:`_request_save_as`, which opens a file picker; the
        remove then waits on that picker's callback.
        """
        if self._destroyed or self._adapter is None:
            return
        services = self._services
        if services is None:
            return
        child_handle = self._adapter.find_layer(child_id)
        is_anonymous = (
            child_handle is not None
            and self._adapter.is_anonymous(child_handle)
        )
        if is_anonymous:
            # Anonymous layers need a Save-As file picker before the
            # remove can run — the file the remove is preserving
            # doesn't exist on disk yet. Route through the Save-As
            # callback so the remove fires only after the picker
            # returns a path (and is silent on dialog cancel).
            self._save_as_then_remove(parent_id, position, child_id)
            return
        services.undo_manager.begin_group("Save & Remove")
        try:
            save_cmd = SaveLayerCommand(
                self._adapter,
                services.selection_bus,
                child_id,
                ErrorReporter,
            )
            services.undo_manager.push(save_cmd)
            remove_cmd = RemoveSublayerCommand(
                self._adapter,
                services.selection_bus,
                parent_id,
                position,
            )
            services.undo_manager.push(remove_cmd)
        finally:
            services.undo_manager.end_group()

    def _save_as_then_remove(
        self,
        parent_id: str,
        position: int,
        child_id: str,
    ) -> None:
        """Anonymous-layer path for Save & Remove.

        The save-as dialog captures the user's chosen path; on
        confirm the adapter writes the file *and* rewrites the
        parent's sublayer reference to point at the new identifier
        (via :class:`SaveLayerAsCommand` with
        ``replace_in_parent=True``). The subsequent remove would
        target the now-rewritten reference, so we look up the
        fresh child identifier after the save and route through a
        standard :class:`RemoveSublayerCommand`. Cancel on the
        dialog leaves the layer in place.
        """
        if self._destroyed or self._adapter is None:
            return
        services = self._services
        if services is None:
            return
        from ovui_widgets.common.file_dialogs import save_file_dialog

        # Build the item the file-picker expects from the identifier
        # alone — anonymous item's display name is the identifier.
        source_handle = self._adapter.find_layer(child_id)
        if source_handle is None:
            return
        display_name = self._adapter.get_display_name(source_handle)
        default_name = _default_save_as_filename_from_name(display_name)

        def _on_selected(chosen_path: str) -> None:
            services.undo_manager.begin_group("Save & Remove")
            try:
                save_as_cmd = SaveLayerAsCommand(
                    self._adapter,
                    services.selection_bus,
                    child_id,
                    chosen_path,
                    replace_in_parent=True,
                    error_reporter=ErrorReporter,
                )
                services.undo_manager.push(save_as_cmd)
                # The save-as command rewrote the parent's slot to
                # ``chosen_path`` (anonymous → concrete). Remove the
                # newly-concrete sublayer at the original slot —
                # positions are stable because the save-as swap is
                # in-place.
                remove_cmd = RemoveSublayerCommand(
                    self._adapter,
                    services.selection_bus,
                    parent_id,
                    position,
                )
                services.undo_manager.push(remove_cmd)
            finally:
                services.undo_manager.end_group()

        save_file_dialog(
            title=f"Save '{display_name or child_id}' as...",
            default_name=default_name,
            on_selected=_on_selected,
        )

    def _request_reload(self, item: LayerItem) -> None:
        """Reload ``item`` from disk, with a dirty-state confirm guard.

        Step 37 — UI-facing entry point for the reload gesture.
        Clean layers skip the dialog and push a
        :class:`ReloadLayerCommand` directly. Dirty layers open
        :func:`~ovui_widgets.common.dialogs.confirm_reload_dialog`; on Reload
        the command pushes, on Cancel nothing happens. Anonymous
        layers are silently ignored — ``reload_layer`` has no file
        to re-read, so the adapter call would fail anyway.

        Headless / unit-test construction (``app`` is ``None``)
        calls :meth:`~ovui_widgets.common.adapters.LayerStackAdapter.reload_layer`
        directly on clean layers, mirroring :meth:`_request_save`'s
        fallback; dirty layers are left untouched in that context.
        """
        if self._destroyed or self._adapter is None:
            return
        handle = self._adapter.find_layer(item.identifier)
        if handle is None:
            return
        if self._adapter.is_anonymous(handle):
            return
        is_dirty = self._adapter.is_dirty(handle)

        services = self._services
        if not is_dirty:
            if services is None:
                self._adapter.reload_layer(item.identifier)
                return
            cmd = ReloadLayerCommand(
                self._adapter,
                services.selection_bus,
                item.identifier,
                ErrorReporter,
            )
            services.undo_manager.push(cmd)
            return

        if services is None:
            return

        from ovui_widgets.common.dialogs import confirm_reload_dialog

        layer_name = item.display_name or item.identifier

        def _on_reload() -> None:
            self._perform_reload(item.identifier)

        confirm_reload_dialog(layer_name=layer_name, on_reload=_on_reload)

    def _perform_reload(self, identifier: str) -> None:
        """Push a :class:`ReloadLayerCommand` without a confirm guard.

        Split out from :meth:`_request_reload` so tests can drive
        the command half directly and so the dialog callback stays
        a one-liner. Destroyed / detached / missing-app guards
        mirror :meth:`_request_save`.
        """
        if self._destroyed or self._adapter is None:
            return
        services = self._services
        if services is None:
            self._adapter.reload_layer(identifier)
            return
        cmd = ReloadLayerCommand(
            self._adapter,
            services.selection_bus,
            identifier,
            ErrorReporter,
        )
        services.undo_manager.push(cmd)

    def _resolve_layer_display_name(self, identifier: str) -> str:
        """Return a user-facing name for ``identifier`` (dialog header).

        Uses the cached :class:`LayerItem` when one exists so the
        dialog's title reads the same as the tree row. Falls back to
        the adapter's ``get_display_name`` (and finally the raw
        identifier) so a late-arriving remove gesture on a
        not-yet-rendered layer still produces a sensible prompt.
        """
        item = self._items_by_id.get(identifier)
        if item is not None:
            name = item.display_name
            if name:
                return name
        handle = self._adapter.find_layer(identifier)
        if handle is not None:
            name = self._adapter.get_display_name(handle)
            if name:
                return name
        return identifier


# LAYERS-PLAN Step 45 only accepts the three "real" USD formats — the
# binary package format ``.usdz`` is explicitly out of scope because
# USD's ``SdfLayer.InsertSubLayerPath`` cannot reference one directly
# (packages must be opened through ``UsdStage``, not added as
# sublayers). Keep the tuple lowercase so the suffix check can stay
# a simple case-insensitive ``.endswith`` test.
_LAYERS_SUBLAYER_EXTENSIONS = (".usd", ".usda", ".usdc")


def _is_valid_usd_path(path: str) -> bool:
    """Return ``True`` when ``path`` ends with a sublayer-compatible USD suffix.

    Case-insensitive because OS file browsers happily hand out
    ``.USDA`` on Windows filesystems. Empty strings reject (``.usd``
    suffix test on ``""`` is false anyway, but the explicit guard
    protects callers that still ``and path`` upstream). ``.usdz``
    packages reject intentionally — see :data:`_LAYERS_SUBLAYER_EXTENSIONS`.
    """
    if not isinstance(path, str) or not path:
        return False
    lower = path.lower()
    return any(lower.endswith(ext) for ext in _LAYERS_SUBLAYER_EXTENSIONS)


def _extract_file_paths(source: Any) -> Optional[List[str]]:
    """Normalise an ovui drop ``source`` into a list of file paths.

    ovui's ``AbstractItemModel`` drop hook hands the payload in one of
    three shapes depending on the platform drag source:

    - A plain ``str`` — single file path (the common Linux / macOS
      case).
    - A ``str`` with embedded newlines — multi-file drop from
      Windows file explorers that serialise as
      ``"/path/one.usda\\n/path/two.usda"``.
    - A ``list`` of strings — defensive support for hosts that
      pre-split; the Step-45 plan explicitly calls this shape out.

    Any other shape (``None``, :class:`LayerItem`, a number, an empty
    list after stripping) returns ``None`` so the caller can route
    through the "unsupported payload" branch. The returned list is
    always non-empty when not ``None``.
    """
    if isinstance(source, str):
        lines = [line.strip() for line in source.splitlines() if line.strip()]
        if not lines:
            return None
        return lines
    if isinstance(source, (list, tuple)):
        paths: List[str] = []
        for entry in source:
            if isinstance(entry, str) and entry.strip():
                paths.append(entry.strip())
        return paths or None
    return None


def _default_save_as_filename_from_name(display_name: str) -> str:
    """Derive a dialog default filename from a display name.

    Mirrors :func:`_default_save_as_filename` but takes the raw
    string rather than a :class:`LayerItem` — used by the Save-&-
    Remove flow on anonymous layers, where the caller already has
    the display name in hand.
    """
    raw = display_name or "untitled"
    if raw.startswith("anon:"):
        raw = raw[len("anon:"):] or "untitled"
    lower = raw.lower()
    if not any(
        lower.endswith(ext)
        for ext in (".usd", ".usda", ".usdc", ".usdz")
    ):
        raw = f"{raw}.usda"
    return raw


def _default_save_as_filename(item: LayerItem) -> str:
    """Return a reasonable default filename for ``item`` in the dialog.

    Anonymous layers don't have a real filename, so we fall back to
    the display name — which for an anonymous layer is the identifier
    string (``anon:0`` on the mock, ``anon:...usda`` in USD). We
    strip the ``anon:`` prefix so the user sees a writable-looking
    suggestion, and append ``.usda`` if the stripped value lacks a
    USD extension. Concrete layers keep their existing extension.
    """
    raw = item.display_name or item.identifier or "untitled"
    if raw.startswith("anon:"):
        raw = raw[len("anon:"):] or "untitled"
    lower = raw.lower()
    if not any(
        lower.endswith(ext)
        for ext in (".usd", ".usda", ".usdc", ".usdz")
    ):
        raw = f"{raw}.usda"
    return raw

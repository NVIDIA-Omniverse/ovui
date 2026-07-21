# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tree-selection observer (LAYERS-PLAN Steps 55-57 / ARCHITECTURE §24.5).

Watches the Layers ``ui.TreeView``'s selection slot, fans out focused-
:class:`LayerItem` changes to listeners, publishes prim-spec row
clicks to :class:`~ovui_widgets.common.selection.SelectionBus` (Step 56), and
mirrors external bus selections back into the tree by expanding
ancestor rows and setting the matching :class:`PrimSpecItem`
selection (Step 57).

§24.6 — "exactly one LayerItem" rule: multi-layer selections and any
selection that contains a :class:`~ovui_widgets.layers.prim_spec_item.PrimSpecItem`
resolve to ``None`` because the downstream Property panel can only
render one layer at a time. Clearing the selection also resolves to
``None``.

The watch owns ``ui.TreeView.set_selection_changed_fn`` for its
lifetime; Step 55a destroys / recreates one per window-visibility
transition so the per-frame selection sync stops costing cycles when
the Layers panel is hidden. The bus subscription shares the same
lifetime so the hide-show cycle tears both ingress paths down in
lockstep.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, List, Optional

from ovui_widgets.common.selection import SelectionBusError
from ovui_widgets.common.settings import Subscription
from ovui_widgets.layers.commands.base import LAYERS_COMMAND_SOURCE, LAYERS_UNDO_SOURCE
from ovui_widgets.layers.layer_item import LayerItem
from ovui_widgets.layers.prim_spec_item import PrimSpecItem

if TYPE_CHECKING:  # pragma: no cover — type-hint guard
    from ovui_widgets.common.selection import SelectionBus, SelectionChangedEvent
    from ovui_widgets.layers.layer_model import LayerModel


#: Namespaced source string published by :meth:`_forward_prim_specs`.
#:
#: LAYERS-PLAN Step 56 pins this to ``"ovui_widgets.layers:select"`` so Stage /
#: Viewport / Property subscribers can short-circuit selections that
#: originate in the Layers panel without colliding with peer
#: publishers. Step 57's inbound subscription short-circuits on both
#: :data:`LAYERS_SELECT_SOURCE` and ``LAYERS_UNDO_SOURCE`` (self-
#: originated click vs. layer-undo command replay) to break the
#: feedback loop.
LAYERS_SELECT_SOURCE = "ovui_widgets.layers:select"


#: Sources whose :class:`SelectionBus` events the watch must ignore.
#:
#: LAYERS-PLAN Step 57 — both the self-originated click
#: (:data:`LAYERS_SELECT_SOURCE`) and the layer-undo replay
#: (:data:`LAYERS_UNDO_SOURCE` from
#: :class:`~ovui_widgets.layers.commands.base.AbstractLayerCommand`) loop the
#: bus back to this watch. Re-syncing the tree in response would
#: either re-publish the same paths (feedback loop) or fight an in-
#: flight undo restore.
#:
#: :data:`LAYERS_COMMAND_SOURCE` is included for symmetry: a future
#: command that publishes during its ``do_impl`` would otherwise
#: trigger an expand-and-select fan-out on its own authoring event.
LAYERS_OWN_SOURCES = frozenset(
    {LAYERS_SELECT_SOURCE, LAYERS_UNDO_SOURCE, LAYERS_COMMAND_SOURCE}
)


#: Deferred-execution primitive used when a reentrant
#: :class:`SelectionBusError` forces :meth:`_forward_prim_specs` to
#: retry on the next frame. Mirrors the signature of
#: :meth:`ovui_widgets.app.application.Application.call_later` so production code
#: can pass it through verbatim; tests may pass any callable.
CallLater = Callable[[float, Callable[[], None]], Any]


# Public focus-listener signature. ``fn(layer_item_or_none)`` — the
# newly-focused :class:`LayerItem`, or ``None`` when the selection
# resolves to the multi / prim-spec / empty case.
LayerFocusListener = Callable[[Optional[LayerItem]], None]

# "Any selection change" hook — used by :class:`LayerWindow` to mirror
# the tree's live selection into :class:`LayerModel` and refresh the
# footer buttons on every click (not just focus transitions). Kept
# separate from :data:`LayerFocusListener` so the plan's §24.5 focus
# protocol stays narrow.
SelectionChangeHook = Callable[[List[Any]], None]


class LayerSelectionWatch:
    """Observes the Layers tree's selection and fires focus listeners.

    Constructor arguments match the Step 55 plan and the signature
    Step 55a wires through :meth:`LayerWindow._on_visibility_changed`:
    the tree view is the source of raw selection events, the layer
    model is held for Step 56's prim-spec forwarding, and the
    selection bus is held for Step 57's external-selection → tree
    sync. Step 55 uses only the tree view + optional ``on_change``
    hook; the model / bus are accepted now so later steps can extend
    the class without disturbing call sites.
    """

    def __init__(
        self,
        tree_view: Any,
        layer_model: "LayerModel",
        selection_bus: "SelectionBus",
        *,
        on_change: Optional[SelectionChangeHook] = None,
        call_later: Optional[CallLater] = None,
    ) -> None:
        self._tree_view: Any = tree_view
        self._model: Optional["LayerModel"] = layer_model
        self._bus: Optional["SelectionBus"] = selection_bus
        self._on_change: Optional[SelectionChangeHook] = on_change
        # Step 56 — scheduler used to defer a prim-spec publish past a
        # reentrant :class:`SelectionBusError`. Optional so headless /
        # mock harnesses that never hit reentrancy can pass ``None``;
        # :class:`LayerWindow` threads through
        # :meth:`Application.call_later`.
        self._call_later: Optional[CallLater] = call_later
        self._focused_layer: Optional[LayerItem] = None
        self._listeners: List[LayerFocusListener] = []
        # Step 57 — set while applying a :class:`SelectionBus` event
        # so the tree-driven forwarder (:meth:`_forward_prim_specs`)
        # does not re-publish the paths it is about to mirror back.
        # The plan's elide check covers the identical-tuple case; the
        # flag covers partial-match cases (edit-target layer carries a
        # subset of the bus paths) where a re-publish would silently
        # narrow the Stage selection.
        self._applying_bus_event: bool = False
        # Step 57 — subscription to :class:`SelectionBus` for the
        # inbound tree-expand-and-select path. The watch owns the
        # handle for its lifetime and cancels it in :meth:`destroy`
        # so the hide-show cycle (Step 55a) tears the subscription
        # down in lockstep with the tree view.
        self._bus_sub: Optional[Subscription] = None
        if tree_view is not None:
            tree_view.set_selection_changed_fn(
                self._on_tree_selection_changed
            )
        if selection_bus is not None:
            self._bus_sub = selection_bus.subscribe(self._on_bus_event)

    # ── Public API ───────────────────────────────────────────────────

    def add_listener(self, fn: LayerFocusListener) -> None:
        """Register ``fn`` for focused-layer change callbacks.

        ``fn`` fires with the newly-focused :class:`LayerItem` when
        the tree selection resolves to exactly one LayerItem, and
        with ``None`` on cleared / multi / prim-spec selections. A
        listener already registered is not added twice.
        """
        if fn not in self._listeners:
            self._listeners.append(fn)

    def remove_listener(self, fn: LayerFocusListener) -> None:
        """Unregister ``fn``. Silently no-ops if ``fn`` was never registered."""
        if fn in self._listeners:
            self._listeners.remove(fn)

    @property
    def focused_layer(self) -> Optional[LayerItem]:
        """The currently-focused :class:`LayerItem`, or ``None``."""
        return self._focused_layer

    def destroy(self) -> None:
        """Detach from the tree view and release every held reference.

        Step 55a calls this on window-hide so the selection sync stops
        costing cycles when the panel is off-screen. Idempotent — a
        second call is a no-op because every slot is re-null-checked.
        """
        tv = self._tree_view
        self._tree_view = None
        if tv is not None:
            try:
                tv.set_selection_changed_fn(None)
            except Exception:
                # A torn-down ``ui.TreeView`` may reject callback
                # removal — dropping our reference still stops the
                # watch from dispatching into dead widgets.
                pass
        # Step 57 — cancel the bus subscription so the bus cannot
        # dispatch into a torn-down watch. Nulling the handle after
        # cancel matches the pattern used for ``_event_sub`` in
        # :class:`LayerModel`.
        if self._bus_sub is not None:
            self._bus_sub.cancel()
            self._bus_sub = None
        self._listeners = []
        self._focused_layer = None
        self._model = None
        self._bus = None
        self._on_change = None
        self._call_later = None
        self._applying_bus_event = False

    # ── Internals ────────────────────────────────────────────────────

    def _on_tree_selection_changed(self, selection: List[Any]) -> None:
        """Tree-view callback — the single ingress for every selection change.

        Copies ``selection`` into a fresh list so downstream hooks
        that stash / sort the items cannot mutate the tree view's
        private backing list. Invokes the any-change hook first (so
        the model / footer see the new selection before any listener
        does), then resolves the "exactly one LayerItem" focus under
        §24.6 and fans out to focus listeners when it differs from
        the current focus.
        """
        items = list(selection)
        if self._on_change is not None:
            self._on_change(items)
        # §24.6 — the focused layer is the single item in the tree
        # selection, and only if it is itself a :class:`LayerItem`.
        # Multi-select, empty select, a lone prim-spec row, or any
        # mixed (layer + prim-spec) selection resolves to ``None`` so
        # the Property panel's consumer never has to arbitrate.
        if len(items) == 1 and isinstance(items[0], LayerItem):
            new_focus: Optional[LayerItem] = items[0]
        else:
            new_focus = None
        if new_focus is not self._focused_layer:
            self._focused_layer = new_focus
            # Snapshot the listener list so a listener that
            # unsubscribes itself mid-dispatch cannot perturb the
            # iteration.
            for fn in list(self._listeners):
                fn(new_focus)
        # Step 56 — after the §24.5 focus fan-out, forward any
        # :class:`PrimSpecItem` rows in the selection to the bus so
        # Stage / Property react to Layers-panel clicks exactly like a
        # click in the Stage tree.
        self._forward_prim_specs(items)

    # ── Prim-spec → SelectionBus (Step 56) ───────────────────────────

    def _forward_prim_specs(self, selection: List[Any]) -> None:
        """Publish every :class:`PrimSpecItem` in ``selection`` to the bus.

        LAYERS-PLAN Step 56 — the Layers panel's click-to-select path
        for prim specs. Filters ``selection`` to just the
        :class:`PrimSpecItem` rows (a mixed
        ``[LayerItem, PrimSpecItem]`` selection publishes *only* the
        prim-spec paths — the layer row already resolved to the §24.6
        focus-None case and has no downstream meaning to the bus),
        elides when the bus already holds the same ordered tuple
        (self-echo arriving from Step 57's inbound tree-sync), and
        publishes under :data:`LAYERS_SELECT_SOURCE` so Stage /
        Viewport / Property can short-circuit their own re-publish in
        :func:`Application._on_mock_selection`-style subscribers.

        An empty prim-spec slice is deliberately **not** a clear: a
        user click on a :class:`LayerItem` must not wipe the external
        prim-selection held by Stage / Property. Step 55's focus
        listener covers layer-row consumers; the bus stays intact.
        """
        if self._bus is None:
            return
        # Step 57 — the bus-driven selection pass sets this flag; any
        # tree-view callback that fires while the flag is up is a
        # consequence of our own ``self._tree_view.selection = ...``
        # write and must not re-publish, because a partial-match
        # selection (edit-target layer lacks one of the bus paths)
        # would otherwise silently narrow the Stage selection.
        if self._applying_bus_event:
            return
        prim_paths = [
            item.path for item in selection if isinstance(item, PrimSpecItem)
        ]
        if not prim_paths:
            return
        self._publish_prim_paths(prim_paths)

    def _publish_prim_paths(self, prim_paths: List[str]) -> None:
        """Elide-and-publish helper shared by the direct path and retry.

        The reentrancy-retry path routes through this same helper so
        the elide check runs on the deferred frame too — by then the
        bus may already hold the paths (the original reentrant
        publisher could have landed them), in which case the retry is
        a no-op.
        """
        bus = self._bus
        if bus is None:
            return
        if tuple(prim_paths) == tuple(bus.get_snapshot().paths()):
            return
        try:
            bus.publish(prim_paths, source=LAYERS_SELECT_SOURCE)
        except SelectionBusError:
            # A peer subscriber is on the call stack publishing through
            # us. Defer to the next frame so the outer publish can
            # unwind :attr:`SelectionBus._publishing` before we retry.
            # Silently drop the retry in harnesses that did not wire a
            # scheduler — those environments never exercise reentrancy.
            scheduler = self._call_later
            if scheduler is None:
                return
            paths_snapshot = list(prim_paths)
            scheduler(0, lambda: self._publish_prim_paths(paths_snapshot))

    # ── SelectionBus → tree (Step 57) ────────────────────────────────

    def _on_bus_event(self, event: "SelectionChangedEvent") -> None:
        """Mirror an external :class:`SelectionBus` selection into the tree.

        LAYERS-PLAN Step 57 — a Stage / Viewport / Property click
        publishes a prim-path selection; the Layers window answers by
        expanding the edit-target layer to reveal the matching
        :class:`PrimSpecItem` rows and selecting them. Sources we own
        (:data:`LAYERS_SELECT_SOURCE` — our own forwarder,
        :data:`LAYERS_UNDO_SOURCE` — a layer-undo replay,
        :data:`LAYERS_COMMAND_SOURCE` — a layer-command do-phase) are
        dropped so the inbound path only fires for genuinely external
        publishers.

        Missing prims (the edit-target layer does not carry a spec for
        a given path) are skipped silently — USD composition lets a
        prim exist in stage without a matching spec on every layer, so
        a "no row for this path" branch is the expected case, not an
        error. When *every* path misses, the tree selection still gets
        updated to the (empty) matching-specs list so stale highlights
        clear in lockstep with the external selection.

        Guards against feedback loops via two layers:

        1. :data:`LAYERS_OWN_SOURCES` — drop the event outright when
           the publisher was the Layers package (self-originated).
        2. :attr:`_applying_bus_event` — while the inbound selection
           write is in flight, the tree's own ``selection_changed`` fn
           must not re-publish, because a partial resolve (some paths
           have no spec on the edit-target layer) would silently
           narrow the bus selection if forwarded back.
        """
        if event.source in LAYERS_OWN_SOURCES:
            return
        model = self._model
        tree = self._tree_view
        if model is None or tree is None:
            return
        edit_target = getattr(model, "_edit_target_identifier", "")
        if not edit_target:
            return
        edit_target_items = model._find_items(edit_target)
        if not edit_target_items:
            return
        layer = edit_target_items[0]
        matching_specs: List[PrimSpecItem] = []
        for path in event.snapshot.paths():
            spec = model.find_prim_spec(layer, path)
            if spec is None:
                continue
            matching_specs.append(spec)
            self._expand_ancestors(spec)
        self._applying_bus_event = True
        try:
            try:
                tree.selection = matching_specs
            except Exception:
                # A torn-down :class:`ui.TreeView` (hide→show races)
                # may reject the assignment; dropping the write keeps
                # the bus subscriber from raising into the publisher.
                return
        finally:
            self._applying_bus_event = False

    def _expand_ancestors(self, spec: PrimSpecItem) -> None:
        """Expand every ancestor row so ``spec`` is visible in the tree.

        LAYERS-PLAN Step 57 — walks up the
        :class:`PrimSpecItem` chain via :attr:`PrimSpecItem.parent`,
        then up the :class:`LayerItem` chain via
        :attr:`LayerItem.parent`, calling
        :meth:`ui.TreeView.set_expanded` with ``recursive=False`` on
        each hop. ``recursive=True`` would over-expand sibling
        branches (a large layer might have thousands of specs) and
        cost noticeably in the paint pass.

        Exceptions from :meth:`set_expanded` are swallowed: some
        :class:`ui.TreeView` teardown paths reject the call, but a
        partially-expanded tree is still the correct user-visible
        outcome — failing the whole mirror pass over one dead hop
        would leave the tree in a worse state than continuing.
        """
        tree = self._tree_view
        if tree is None:
            return
        # Walk prim-spec ancestors.
        node: Optional[PrimSpecItem] = spec.parent
        while node is not None:
            self._safe_set_expanded(node)
            node = node.parent
        # Walk layer-item ancestors — includes the owning LayerItem
        # itself because its chevron must be open for any spec row
        # underneath it to render.
        layer_node: Optional[LayerItem] = spec.layer_item
        while layer_node is not None:
            self._safe_set_expanded(layer_node)
            layer_node = layer_node.parent

    def _safe_set_expanded(self, item: Any) -> None:
        """Call ``tree_view.set_expanded(item, True, False)`` defensively.

        Swallows the exception path documented on
        :meth:`_expand_ancestors` so a single dead hop does not
        abort the ancestor walk.
        """
        tree = self._tree_view
        if tree is None:
            return
        try:
            tree.set_expanded(item, True, False)
        except Exception:
            return

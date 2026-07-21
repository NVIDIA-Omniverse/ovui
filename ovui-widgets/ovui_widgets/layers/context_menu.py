# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Right-click context menu for the Layers tree (LAYERS-PLAN Steps 38 / 39).

Step 38 was the **framework step** for Phase H: it introduced the
declarative :class:`ContextMenuEntry` / :class:`MenuContext` data
objects, the :class:`ContextMenuBuilder` that builds an ``omni.ui.Menu``
from a filtered entry list, and the shared predicate helpers every
entry's ``show_fn`` composes against.

Step 39 replaces the Step-38 proof-of-life placeholders with the
**edit-target and sublayer-creation** entries: "Set as Authoring
Layer", "Create Sublayer", "Insert Sublayer…", and "New Anonymous
Sublayer". Steps 40-42 continue filling in the remaining groups
(Save / Save-As / Reload, Remove, Mute / Lock, Merge / Flatten).

Mirrors LAYERS-WINDOW-ARCHITECTURE §22.1:

- Each entry is a dataclass with a ``label``, a ``show_fn`` (a list of
  predicates — **all** must return ``True`` for the entry to render), a
  ``click_fn``, and optional ``icon`` / ``separator_before`` / ``enabled_fn``
  metadata. The **list-of-predicates** (rather than a single callable)
  matches Kit's own widget-layers context menu verbatim and lets callers
  compose narrow single-purpose checks without building ad-hoc
  combinators.
- :class:`MenuContext` captures the per-invocation state the predicates
  and click handlers read: the right-clicked :class:`LayerItem` (``None``
  for an empty-area click), the live tree selection, the owning
  :class:`LayerModel` and :class:`Application`. Building this object
  once per right-click — rather than threading the four fields through
  every predicate signature — matches Kit's ``objects`` dict pattern
  and keeps the predicate signatures uniform for future composition.
- :meth:`ContextMenuBuilder.show_at` destroys the previous menu before
  rebuilding so a second right-click on a different row never leaves
  the first row's stale entries visible (LAYERS-WINDOW-ARCHITECTURE
  Logic F3). Every :class:`ui.MenuItem` captures ``entry`` **and**
  ``ctx`` in default-arg bindings (``lambda e=entry, c=ctx:``) so a
  subsequent invocation that rebinds ``ctx`` can't mutate the
  previously-built item's click semantics — this is the I8 closure
  bug the plan's verify clause targets.
- :meth:`ContextMenuBuilder._canonical_order` fixes the group ordering
  regardless of entry registration order so the user always finds the
  most-used action (Set Authoring Layer — Step 39) at the top and the
  destructive actions (Remove Layer — Step 40, Flatten — Step 42)
  below a separator further down. Step 38 only registers two groups,
  but the ordering contract is already honoured so later steps can
  add entries anywhere in the list without breaking layout.

The module exports both the public dataclasses / builder *and* the
predicate helpers (``is_layer_item``, ``is_not_missing``, …) because
tests and Steps 39-42 compose new entries directly against the same
predicate surface. The helpers are pure functions of ``MenuContext``
— headlessly testable without a live menu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, List, Optional

from ovui_widgets.layers.layer_item import LayerItem

if TYPE_CHECKING:  # pragma: no cover — type-hint guard
    from ovui_widgets.common.services import WidgetServices
    from ovui_widgets.layers.layer_model import LayerModel


# Canonical-order groups. Step 38 registers entries into two groups
# (SELECTION and STATE); Steps 39-42 append to the remaining groups.
# Lower numbers render first; a separator is drawn between adjacent
# groups in :meth:`ContextMenuBuilder._canonical_order` whenever both
# groups contribute a visible entry. The numeric values are not a
# dense enum — leaving gaps lets future insertions land cleanly.
GROUP_EDIT_TARGET = 10   # "Set Authoring Layer" (Step 39)
GROUP_CREATE = 20        # Create / Insert / New Anonymous Sublayer (Step 39)
GROUP_STATE = 30         # Mute / Unmute / Lock / Unlock (Step 41)
GROUP_FILE_IO = 40       # Save / Save As / Reload (Step 40)
GROUP_DESTRUCTIVE = 50   # Remove Layer / Merge Down / Flatten (Steps 40, 42)
GROUP_UTILITY = 60       # Copy URL (Step 62)


Predicate = Callable[["MenuContext"], bool]
ClickHandler = Callable[["MenuContext"], None]


@dataclass
class MenuContext:
    """Per-right-click snapshot the predicates and click handlers read.

    Captured once by the delegate's mouse handler so every predicate in
    the entry list — plus the triggered ``click_fn`` — sees the same
    item, selection list, and model / app references. Built as a
    mutable-dataclass because downstream predicates may want to cache
    a resolved value (e.g., ``item.is_writable``) but Step 38's
    predicates never mutate the snapshot; the mutability is a future
    extension point rather than a live contract.

    Fields:

    - ``item`` — the :class:`LayerItem` under the cursor, or ``None`` for
      an empty-area right-click. The empty-area case exists because the
      Layers panel is mostly tree rows but clicking in the scroll
      padding below the last row should still produce a reduced menu
      (LAYERS-PLAN Step 38 empty-area gesture).
    - ``tree_selection`` — a defensive copy of
      :attr:`LayerModel.selected_items` at the moment of the right-
      click. Used by ``no_items_selected`` and by multi-target actions
      (Step 41 "Lock Layer and Descendants"). Captured up-front so a
      predicate reading ``len(ctx.tree_selection)`` is immune to a
      racy selection mutation while the menu is open.
    - ``model`` — the :class:`LayerModel` that owns the tree; predicates
      read ``model._edit_target_identifier`` to gate "Set Authoring
      Layer", click handlers call ``model._request_save`` / etc.
    - ``app`` — the :class:`Application` instance, or ``None`` in
      headless construction. Click handlers push commands through
      ``services.undo_manager``; headless tests drive the click handlers
      directly and tolerate a ``None`` app by short-circuiting.
    """

    item: Optional[LayerItem]
    tree_selection: List[LayerItem]
    model: "LayerModel"
    services: "Optional[WidgetServices]"


@dataclass
class ContextMenuEntry:
    """One row in the declarative context-menu entry list.

    Mirrors LAYERS-WINDOW-ARCHITECTURE §22.1's dict shape but uses a
    dataclass so Python type-checking catches misspelt field names at
    import time rather than the first right-click.

    - ``label`` — the display string. When ``label_fn`` is ``None``
      this is the label rendered in the menu; when ``label_fn`` is
      present it supplies the live label (e.g. "Mute Layer" vs
      "Unmute Layer" — Step 41) and ``label`` is retained as a stable
      identifier for tests that look up the entry by a canonical name.
    - ``label_fn`` — optional ``Callable[[MenuContext], str]`` that
      returns the label to render, evaluated against the live
      :class:`MenuContext` on every :meth:`ContextMenuBuilder.show_at`.
      Step 41's Mute/Unmute and Lock/Unlock entries use this to flip
      their labels based on the clicked layer's current state without
      needing two separate entries that would both have to ``show_fn``-
      gate on opposite sides of the same predicate.
    - ``show_fn`` — a list of :class:`Predicate` callables. **All must
      return True** for the entry to render. An empty list means
      "always show" — rare but useful for unconditional utility items
      like Copy URL.
    - ``click_fn`` — executed on ``ui.MenuItem.triggered``. Wrapped by
      :meth:`ContextMenuBuilder.show_at` in a default-arg closure so a
      rebuild of the menu with a fresh context can't invalidate a
      pending click on the previous build.
    - ``icon`` — optional icon filename for future SVG integration
      (Step 24's icon pack); Step 38 builders ignore this and render
      text-only rows.
    - ``separator_before`` — draw a ``ui.Separator`` immediately before
      this entry. Used sparingly: most separators come from the
      :attr:`group` boundary in :meth:`_canonical_order`; this flag is
      for intra-group dividers (e.g., between "Save" and "Save As" —
      Step 40).
    - ``enabled_fn`` — optional predicate; ``True`` means the menu item
      renders enabled, ``False`` means greyed out but still visible.
      Distinct from ``show_fn``: hidden entries disappear entirely,
      disabled entries are visible affordances that explain *why* the
      action is unavailable (Kit convention — LAYERS-WINDOW-ARCHITECTURE
      §22.1 Copy URL disable semantics).
    - ``group`` — canonical-order bucket (see the ``GROUP_*`` module
      constants). Entries within the same group render in registration
      order; groups themselves render in ascending numeric order with
      separators between non-empty adjacent groups.
    """

    label: str
    show_fn: List[Predicate]
    click_fn: ClickHandler
    icon: Optional[str] = None
    separator_before: bool = False
    enabled_fn: Optional[Predicate] = None
    label_fn: Optional[Callable[["MenuContext"], str]] = None
    group: int = GROUP_UTILITY


# ── Predicate helpers ────────────────────────────────────────────────
#
# Predicates take a :class:`MenuContext` and return a plain ``bool`` so
# the ``all(pred(ctx) for pred in entry.show_fn)`` evaluation in
# :meth:`ContextMenuBuilder.show_at` short-circuits naturally. Every
# predicate is pure and side-effect-free so a predicate failure inside
# one entry never affects the next entry's evaluation; tests exercise
# each predicate in isolation against hand-built :class:`MenuContext`
# instances.
#
# LAYERS-WINDOW-ARCHITECTURE §22.3 documents the exact semantics Kit
# uses; we reproduce that surface here but keep the names short (drop
# the redundant ``_layer`` suffix on the ``is_layer_*`` predicates that
# already take a :class:`LayerItem`-bearing context).


def is_layer_item(ctx: MenuContext) -> bool:
    """The right-click landed on a :class:`LayerItem` row.

    ``False`` for an empty-area right-click (``ctx.item is None``) and
    for any future non-:class:`LayerItem` row that mixes into the tree
    (Phase J's :class:`PrimSpecItem`). This is the first predicate on
    almost every entry — a layer-targeted action on a non-layer row is
    definitionally invalid.
    """
    return isinstance(ctx.item, LayerItem)


def no_items_selected(ctx: MenuContext) -> bool:
    """Tree has no selected rows.

    Used by the empty-area "Create Sublayer (root)" entries in Step 39:
    those entries only appear when the user hasn't picked a specific
    layer to parent the new sublayer under. Step 38 exposes the
    predicate so the Step 39 patch is additive.
    """
    return not ctx.tree_selection


def is_empty_area(ctx: MenuContext) -> bool:
    """The right-click landed in the empty scroll area (no layer row).

    Complement to :func:`is_layer_item`: the empty-area entries
    (Step 39 root-level Create / Insert / New Anonymous Sublayer)
    gate on ``ctx.item is None`` so they never compete with the
    on-layer entries when the user right-clicks an actual row. The
    plan's verify clause explicitly distinguishes the two menus ("no
    selection" empty-area vs "scoped to clicked layer"); using
    ``ctx.item is None`` as the gate keeps the two menus disjoint
    regardless of whether the user happened to have a selection
    active elsewhere.
    """
    return ctx.item is None


def has_any_items_selected(ctx: MenuContext) -> bool:
    """Tree has at least one selected row.

    Mirror predicate to :func:`no_items_selected`. Used by entries that
    depend on a live selection (Copy URL — Step 62 — copies every
    selected row's identifier, so selection must be non-empty).
    """
    return bool(ctx.tree_selection)


def is_single_selection(ctx: MenuContext) -> bool:
    """Exactly one row is selected.

    Multi-select-aware entries (Step 41 "Lock Layer and Descendants")
    operate on the selection; single-target entries (Step 39 "Set
    Authoring Layer") shouldn't appear when the user has picked
    multiple rows because the action wouldn't know which layer to
    author into.
    """
    return len(ctx.tree_selection) == 1


def is_not_missing(ctx: MenuContext) -> bool:
    """The right-clicked layer resolved on disk.

    Most write-path actions require the file to exist — a Save on a
    missing layer would re-create the file with whatever the in-memory
    layer happens to hold, which is rarely what the user wants. Empty-
    area right-clicks (``item is None``) return ``False`` because an
    empty-area click targets no layer at all.
    """
    if not isinstance(ctx.item, LayerItem):
        return False
    return not ctx.item.is_missing


def is_not_anonymous(ctx: MenuContext) -> bool:
    """The right-clicked layer has a concrete file path.

    Anonymous layers (identifier starts with ``anon:`` in USD; see
    :meth:`LayerStackAdapter.is_anonymous`) cannot be saved through
    the vanilla Save path — the adapter has no path to write to. Used
    by the "Save" entry (Step 40); the Save-As entry does NOT require
    this predicate because Save-As supplies the path through a file
    picker.
    """
    if not isinstance(ctx.item, LayerItem):
        return False
    return not ctx.item.is_anonymous


def is_writable(ctx: MenuContext) -> bool:
    """The right-clicked layer accepts writes.

    Delegates to :attr:`LayerItem.is_writable`, which in turn delegates
    to :meth:`LayerStackAdapter.is_writable` — the canonical composite
    check (not locked, not muted, not read-only on disk). Gating write
    actions on this keeps the menu honest: a greyed-out entry would
    still hint the action exists, but our convention for unwritable
    layers is to hide the entry so the menu reads as "these are the
    actions available right now".
    """
    if not isinstance(ctx.item, LayerItem):
        return False
    return ctx.item.is_writable


def is_not_current_edit_target(ctx: MenuContext) -> bool:
    """The right-clicked layer is NOT the current authoring layer.

    Gates the "Set Authoring Layer" entry — setting the authoring layer
    to the current authoring layer is a no-op. Reads
    ``model._edit_target_identifier`` rather than :attr:`LayerItem.is_edit_target`
    because the model field is the canonical source (Step 24); the item
    flag is a per-item cache the delegate uses for painting.
    """
    if not isinstance(ctx.item, LayerItem):
        return False
    return ctx.item.identifier != ctx.model._edit_target_identifier


def is_layer_dirty(ctx: MenuContext) -> bool:
    """The right-clicked layer has unsaved in-memory edits.

    Gates the "Save" entry (Step 40) — a clean layer has nothing to
    save, and offering a Save on it would confuse the user into
    thinking something happened. Route through :attr:`LayerItem.is_dirty`
    so the flag cache picks up the latest adapter state without a
    redundant re-read.
    """
    if not isinstance(ctx.item, LayerItem):
        return False
    return ctx.item.is_dirty


def is_layer_muted(ctx: MenuContext) -> bool:
    """The right-clicked layer is locally muted.

    Gates the dynamic Mute / Unmute label in Step 41: a muted layer
    shows "Unmute", an unmuted layer shows "Mute". Step 38 exposes the
    predicate so Step 41 can plug in a single ``label_fn`` callable
    that branches on this return value.
    """
    if not isinstance(ctx.item, LayerItem):
        return False
    return ctx.item.is_muted


def is_layer_locked(ctx: MenuContext) -> bool:
    """The right-clicked layer is locked against authoring.

    Companion predicate to :func:`is_layer_muted`; used by the Step 41
    dynamic "Lock" / "Unlock" label. Does NOT read
    :attr:`LayerItem.locked_or_parent_locked` — the menu action is on
    *this* layer's lock bit, not the cascade.
    """
    if not isinstance(ctx.item, LayerItem):
        return False
    return ctx.item.is_locked


def is_not_root_layer(ctx: MenuContext) -> bool:
    """The right-clicked layer is NOT the tree's root layer.

    Root is reserved: it can't be removed (it's the stack's entry
    point) and Save-As on root has special edit-target handling (plan
    finding A-4). Used by "Remove Layer" (Step 40) and "Save As"
    (Step 40). ``model.root_item`` may be ``None`` in a pre-build
    state; we return ``False`` defensively so no action fires on a
    half-initialised tree.
    """
    if not isinstance(ctx.item, LayerItem):
        return False
    root = ctx.model.root_item
    if root is None:
        return False
    return ctx.item.identifier != root.identifier


def is_not_session_layer(ctx: MenuContext) -> bool:
    """The right-clicked layer is NOT the session layer.

    Session layer is also reserved (Kit's ``is_not_reserved_layer``
    predicate excludes both root and session). Step 38 splits the two
    checks so a caller that wants to allow session-layer gestures (the
    "New Anonymous Sublayer" entry — Step 39 — gates on session layer)
    doesn't inherit the root exclusion.
    """
    if not isinstance(ctx.item, LayerItem):
        return False
    return not ctx.item.is_session_layer


def is_not_reserved(ctx: MenuContext) -> bool:
    """The right-clicked layer is neither root nor session.

    Composite of :func:`is_not_root_layer` and
    :func:`is_not_session_layer`. Most destructive / rename gestures
    gate on this; entries in Steps 40 and 42 consume it directly.
    """
    return is_not_root_layer(ctx) and is_not_session_layer(ctx)


def can_edit_root(ctx: MenuContext) -> bool:
    """The tree's root layer is writable.

    Gates the empty-area "Create Sublayer" / "Insert Sublayer" entries
    (Step 39) — those entries would parent a new sublayer under root,
    so root must accept the authoring edit. Returns ``False`` when
    root is missing (pre-build state) or not writable.
    """
    root = ctx.model.root_item
    if root is None:
        return False
    return root.is_writable


def has_sibling_below(ctx: MenuContext) -> bool:
    """The right-clicked layer has another sublayer immediately below it.

    Gates the Step-42 "Merge Down" entry: Merge Down is only
    meaningful when a destination sibling exists to receive the
    merged content. Returns ``False`` for top-level rows (session /
    root-less parents) and for the last sibling in a parent's
    sublayer list.

    Reads the parent's live sublayer list through the adapter rather
    than the cached :attr:`LayerItem.sublayers` so a peer remove
    between menu popup and click takes effect immediately — a stale
    cache could offer Merge Down on a row whose sibling-below was
    already removed.
    """
    item = ctx.item
    if not isinstance(item, LayerItem):
        return False
    parent = item.parent
    if parent is None:
        return False
    adapter = ctx.model._adapter
    if adapter is None:
        return False
    parent_handle = adapter.find_layer(parent.identifier)
    if parent_handle is None:
        return False
    siblings = adapter.get_sublayer_identifiers(parent_handle)
    try:
        position = siblings.index(item.identifier)
    except ValueError:
        return False
    return position + 1 < len(siblings)


def has_sublayers(ctx: MenuContext) -> bool:
    """The right-clicked layer has at least one direct sublayer.

    Gates the Step-42 "Flatten Sublayers" entry: flattening a layer
    with no sublayers is a no-op, and offering it would confuse the
    user. Reads :attr:`LayerItem.sublayers` — the in-memory tree built
    by :class:`LayerModel` — rather than the adapter so the check is
    O(1) and immune to a mid-menu recomposition.
    """
    item = ctx.item
    if not isinstance(item, LayerItem):
        return False
    return bool(item.sublayers)


# ── ContextMenuBuilder ───────────────────────────────────────────────


class ContextMenuBuilder:
    """Builds and shows the right-click context menu for the Layers tree.

    One builder per :class:`LayerWindow` / :class:`LayerModel` pair;
    the delegate's mouse handler dispatches a :class:`MenuContext` to
    :meth:`show_at`, which destroys any previous menu, evaluates every
    registered entry's :attr:`ContextMenuEntry.show_fn` against the
    context, and builds a fresh :class:`omni.ui.Menu` containing the
    entries that passed.

    Step 39 registers the real edit-target and sublayer-creation
    entries (replacing Step 38's two proof-of-life placeholders):
    "Set as Authoring Layer", the on-layer Create / Insert / New
    Anonymous Sublayer trio, and the empty-area Create / Insert / New
    Anonymous Sublayer trio. Steps 40-42 populate the remaining
    groups (Save / Save-As / Reload / Remove, Mute / Lock, Merge /
    Flatten, Copy URL).

    :meth:`register_entry` is the additive API: later steps append
    their entries without rewriting Step 38's structure. Tests drive
    :meth:`build_entries_for` to introspect which entries a given
    context would render without actually painting the menu — this
    keeps the unit tests headless.
    """

    # Module-level import guard: the builder only imports ``omni.ui``
    # when :meth:`show_at` runs, so tests can construct and drive the
    # builder from a headless Python context without pulling in ovui.
    # The pure predicate + build-entries API never touches ui.
    def __init__(
        self,
        model: "LayerModel",
        services: "Optional[WidgetServices]" = None,
    ) -> None:
        self._model = model
        self._services = services
        self._entries: List[ContextMenuEntry] = []
        # The most-recently-shown :class:`ui.Menu`. Held so the next
        # :meth:`show_at` can destroy it before building a new one — a
        # stale menu would otherwise keep firing against a
        # :class:`MenuContext` that no longer reflects the tree state
        # (LAYERS-WINDOW-ARCHITECTURE Logic F3).
        self._menu: Any = None
        # Read-only Inspector evidence for the currently shown popup. The
        # widgets remain owned by ``_menu``; this list only maps stable action
        # labels to enabled state and real screenshot-space geometry after a
        # user right-click. It is cleared before every rebuild and on destroy.
        self._inspector_menu_items: List[tuple[str, bool, Any]] = []
        self._inspector_menu_anchor: tuple[float, float] | None = None
        self._register_default_entries()

    # ── Registration / introspection ─────────────────────────────────

    def register_entry(self, entry: ContextMenuEntry) -> None:
        """Append ``entry`` to the declarative entry list.

        Steps 39-42 call this with their own entries; Step 38's
        :meth:`_register_default_entries` populates the initial
        two-entry baseline. The order callers register in does not
        determine visible order — :meth:`_canonical_order` re-groups
        by :attr:`ContextMenuEntry.group` on every :meth:`show_at`.
        """
        self._entries.append(entry)

    @property
    def entries(self) -> List[ContextMenuEntry]:
        """Defensive copy of the registered entry list.

        Tests assert against this; callers must not mutate the list in
        place because registration order within a group is preserved
        by :meth:`_canonical_order` and a sort on a shared reference
        would break that ordering.
        """
        return list(self._entries)

    def build_entries_for(
        self, ctx: MenuContext
    ) -> List[ContextMenuEntry]:
        """Return the entries whose :attr:`show_fn` all pass for ``ctx``.

        Called by :meth:`show_at` to filter the entry list before
        building the menu; tests call it directly to assert which
        entries would appear for a given context without needing a
        live ui backend. Returns a fresh list so a caller's post-
        filter mutation doesn't affect the canonical order.
        """
        visible: List[ContextMenuEntry] = []
        for entry in self._canonical_order():
            if all(pred(ctx) for pred in entry.show_fn):
                visible.append(entry)
        return visible

    # ── Canonical ordering ───────────────────────────────────────────

    def _canonical_order(self) -> List[ContextMenuEntry]:
        """Group registered entries by :attr:`ContextMenuEntry.group`.

        LAYERS-PLAN UX D1 — the user always finds the same action in
        the same place, regardless of which extension registered it
        first. Groups render in ascending numeric order; within a
        group, registration order wins (first-registered is first-
        rendered). Empty groups are skipped; separator rendering
        between groups is a :meth:`show_at` responsibility because the
        separator lives in the ``ui.Menu`` context, not in the entry
        list.

        Implementation is a stable sort on the ``group`` key — Python's
        ``sorted`` is stable, so entries with the same group retain
        their registration order without us threading a secondary
        sort key.
        """
        return sorted(self._entries, key=lambda e: e.group)

    # ── Menu build / show ────────────────────────────────────────────

    def show_at(self, x: float, y: float, ctx: MenuContext) -> Any:
        """Build and show the context menu at screen-space ``(x, y)``.

        Destroys any previously-shown menu before building the new one
        — a left-over menu would keep firing against a stale context
        (LAYERS-WINDOW-ARCHITECTURE Logic F3). Evaluates every entry's
        ``show_fn`` against ``ctx`` and renders the passing entries
        grouped by :attr:`ContextMenuEntry.group` with a
        :class:`ui.Separator` between adjacent non-empty groups.

        The lambda that binds ``entry`` and ``ctx`` captures both via
        default arguments (``lambda e=entry, c=ctx:``). This is the
        textbook fix for the closure-over-loop-variable bug: without
        the defaults, every rebuilt ``ui.MenuItem`` would fire with
        the *last* loop iteration's entry/context pair because Python
        closes over the name, not the value. Tested explicitly by
        :func:`tests.test_layer_context_menu.test_closure_captures_ctx`.

        Returns the built :class:`ui.Menu` so callers can hold a
        reference — without one, ovui's reference-count teardown drops
        the popup the instant this method returns. The builder also
        pins the menu internally (:attr:`_menu`) so the next
        :meth:`show_at` has a handle to destroy, but returning it lets
        tests that run against a live ui poke at the menu directly.
        """
        import omni.ui as ui

        from ovui_widgets.common.menu import create_flat_menu

        # Tear down the previous menu before building a new one. Guard
        # against a double-destroy on a builder whose previous menu
        # was already collected (``ui.Menu.destroy`` is idempotent on
        # a live menu but raises on a freed handle in some ovui
        # builds); the broad except keeps the hot path robust.
        if self._menu is not None:
            try:
                self._menu.destroy()
            except Exception:
                pass
            self._menu = None

        self._inspector_menu_items = []
        self._inspector_menu_anchor = (float(x), float(y))

        menu = create_flat_menu()
        self._menu = menu
        visible = self.build_entries_for(ctx)
        with menu:
            last_group: Optional[int] = None
            for entry in visible:
                # Group-boundary separator: only drawn between two
                # non-empty groups, so a single-group menu renders
                # flat (no leading separator) and an all-empty menu
                # renders empty.
                if last_group is not None and entry.group != last_group:
                    ui.Separator()
                # Intra-group separator — for "Save" / "Save As" pairs
                # (Step 40) that want a visual gap within one group.
                if entry.separator_before and last_group == entry.group:
                    ui.Separator()
                enabled = True
                if entry.enabled_fn is not None:
                    try:
                        enabled = bool(entry.enabled_fn(ctx))
                    except Exception:
                        enabled = False
                label = entry.label
                if entry.label_fn is not None:
                    try:
                        label = str(entry.label_fn(ctx))
                    except Exception:
                        label = entry.label
                menu_item = ui.MenuItem(
                    label,
                    enabled=enabled,
                    triggered_fn=lambda e=entry, c=ctx: e.click_fn(c),
                )
                self._inspector_menu_items.append((label, enabled, menu_item))
                last_group = entry.group
        menu.show_at(float(x), float(y))
        return menu

    def destroy(self) -> None:
        """Drop the pinned menu so the owning window can be collected.

        Called from :meth:`LayerWindow.destroy` to release the held
        :class:`ui.Menu` reference before the delegate + model graph
        is torn down. Idempotent — a second destroy is a no-op so the
        window's teardown sequence can re-enter the method without a
        guard at the call site.
        """
        if self._menu is not None:
            try:
                self._menu.destroy()
            except Exception:
                pass
            self._menu = None
        self._inspector_menu_items = []
        self._inspector_menu_anchor = None

    # ── Default (Step 39) entries ────────────────────────────────────

    def _register_default_entries(self) -> None:
        """Populate the Step-39 edit-target and sublayer-creation entries.

        Seven entries land here:

        1. **"Set as Authoring Layer"** — on-layer, gated on
           :func:`is_layer_item` + :func:`is_not_current_edit_target`.
           Disabled (greyed out) when the layer is not writable
           (muted / locked / read-only) so the user still sees the
           affordance but cannot push a command the adapter would
           reject. Pushes :class:`SetEditTargetCommand`.
        2. **"Create Sublayer"** (on-layer) — gated on
           :func:`is_layer_item`; disabled on a non-writable layer.
           Opens :func:`save_file_dialog` with default
           ``"untitled.usda"``; on confirm pushes
           :class:`CreateSublayerCommand` with the clicked layer as
           parent and ``-1`` (append) as position.
        3. **"Insert Sublayer…"** (on-layer) — same gates as #2.
           Opens :func:`save_file_dialog` (no default name); on
           confirm pushes :class:`InsertSublayerCommand` for an
           existing USD file.
        4. **"New Anonymous Sublayer"** (on-layer) — same gates.
           Pushes :class:`CreateSublayerCommand` with ``new_layer_path=""``
           (adapter mints an anonymous identifier). No dialog.
        5-7. Empty-area counterparts of 2-4 (Create / Insert / New
           Anonymous), each gated on :func:`is_empty_area` and
           :func:`can_edit_root`. The new sublayer lands under the
           root layer.

        The on-layer entries' ``show_fn`` deliberately does *not*
        include :func:`is_writable`; they surface on every layer row
        (including muted / locked) but ``enabled_fn=is_writable`` greys
        them out so the user sees *why* the action is unavailable.
        This matches Kit's convention — hidden entries disappear
        entirely, disabled entries are visible affordances.

        Empty-area entries use :func:`is_empty_area` (``ctx.item is
        None``) rather than the plan's
        :func:`no_items_selected` so they never compete with the
        on-layer entries on a row right-click: predicates are
        composed AND, and a row click always has ``item is not None``
        regardless of whether a separate row is selected in the tree.
        The two menus stay disjoint without a dedicated
        "select-on-right-click" gesture.
        """
        # Lazy import — the commands submodule pulls in the undo stack
        # which is lightweight but unnecessary for unit tests that
        # drive predicates only.
        from ovui_widgets.layers.commands.layer_commands import SetEditTargetCommand
        from ovui_widgets.layers.commands.sublayer_commands import (
            CreateSublayerCommand,
            InsertSublayerCommand,
        )

        # ── Entry 1 — "Set as Authoring Layer" ───────────────────────

        def _set_authoring_click(ctx: MenuContext) -> None:
            if not isinstance(ctx.item, LayerItem):
                return
            services = ctx.services
            if services is None:
                return
            adapter = ctx.model._adapter
            if adapter is None:
                return
            cmd = SetEditTargetCommand(
                adapter,
                services.selection_bus,
                ctx.item.identifier,
            )
            services.undo_manager.push(cmd)

        self.register_entry(
            ContextMenuEntry(
                label="Set as Authoring Layer",
                show_fn=[is_layer_item, is_not_current_edit_target],
                click_fn=_set_authoring_click,
                enabled_fn=is_writable,
                group=GROUP_EDIT_TARGET,
            )
        )

        # ── Entries 2-4 — on-layer Create / Insert / New Anonymous ───

        def _create_sublayer_for(ctx: MenuContext, parent_id: str) -> None:
            """Open save-file dialog; on confirm push CreateSublayerCommand."""
            services = ctx.services
            if services is None:
                return
            adapter = ctx.model._adapter
            if adapter is None:
                return
            # Lazy import matches the rest of the context-menu dialog
            # surface (Steps 36-37) so pure predicate unit tests stay
            # ovui-free.
            from ovui_widgets.common.file_dialogs import save_file_dialog

            def _on_selected(chosen_path: str) -> None:
                cmd = CreateSublayerCommand(
                    adapter,
                    services.selection_bus,
                    parent_id,
                    -1,
                    chosen_path,
                    transfer_root_content=False,
                )
                services.undo_manager.push(cmd)

            save_file_dialog(
                title=f"Create Sublayer under '{parent_id}'",
                default_name="untitled.usda",
                on_selected=_on_selected,
            )

        def _insert_sublayer_for(ctx: MenuContext, parent_id: str) -> None:
            """Open file picker; on confirm push InsertSublayerCommand."""
            services = ctx.services
            if services is None:
                return
            adapter = ctx.model._adapter
            if adapter is None:
                return
            from ovui_widgets.common.file_dialogs import save_file_dialog

            def _on_selected(chosen_path: str) -> None:
                cmd = InsertSublayerCommand(
                    adapter,
                    services.selection_bus,
                    parent_id,
                    -1,
                    chosen_path,
                )
                services.undo_manager.push(cmd)

            # ovui v3 has no Open-file modal (constraint G2: no Kit);
            # the Step-36 helper is a StringField + OK / Cancel that
            # works as well for typing an existing path. The default
            # name is blank so the field starts empty — the user types
            # or pastes the full path to the layer they want to import.
            save_file_dialog(
                title=f"Insert Sublayer into '{parent_id}'",
                default_name="",
                on_selected=_on_selected,
            )

        def _new_anonymous_sublayer_for(
            ctx: MenuContext, parent_id: str
        ) -> None:
            """Push CreateSublayerCommand(path='') — anonymous layer."""
            services = ctx.services
            if services is None:
                return
            adapter = ctx.model._adapter
            if adapter is None:
                return
            cmd = CreateSublayerCommand(
                adapter,
                services.selection_bus,
                parent_id,
                -1,
                "",
                transfer_root_content=False,
            )
            services.undo_manager.push(cmd)

        def _on_layer_create_click(ctx: MenuContext) -> None:
            if not isinstance(ctx.item, LayerItem):
                return
            _create_sublayer_for(ctx, ctx.item.identifier)

        def _on_layer_insert_click(ctx: MenuContext) -> None:
            if not isinstance(ctx.item, LayerItem):
                return
            _insert_sublayer_for(ctx, ctx.item.identifier)

        def _on_layer_anon_click(ctx: MenuContext) -> None:
            if not isinstance(ctx.item, LayerItem):
                return
            _new_anonymous_sublayer_for(ctx, ctx.item.identifier)

        self.register_entry(
            ContextMenuEntry(
                label="Create Sublayer",
                show_fn=[is_layer_item],
                click_fn=_on_layer_create_click,
                enabled_fn=is_writable,
                group=GROUP_CREATE,
            )
        )
        self.register_entry(
            ContextMenuEntry(
                label="Insert Sublayer...",
                show_fn=[is_layer_item],
                click_fn=_on_layer_insert_click,
                enabled_fn=is_writable,
                group=GROUP_CREATE,
            )
        )
        self.register_entry(
            ContextMenuEntry(
                label="New Anonymous Sublayer",
                show_fn=[is_layer_item],
                click_fn=_on_layer_anon_click,
                enabled_fn=is_writable,
                group=GROUP_CREATE,
            )
        )

        # ── Entries 5-7 — empty-area Create / Insert / New Anonymous ─

        def _empty_area_create_click(ctx: MenuContext) -> None:
            root = ctx.model.root_item
            if root is None:
                return
            _create_sublayer_for(ctx, root.identifier)

        def _empty_area_insert_click(ctx: MenuContext) -> None:
            root = ctx.model.root_item
            if root is None:
                return
            _insert_sublayer_for(ctx, root.identifier)

        def _empty_area_anon_click(ctx: MenuContext) -> None:
            root = ctx.model.root_item
            if root is None:
                return
            _new_anonymous_sublayer_for(ctx, root.identifier)

        self.register_entry(
            ContextMenuEntry(
                label="Create Sublayer",
                show_fn=[is_empty_area, can_edit_root],
                click_fn=_empty_area_create_click,
                group=GROUP_CREATE,
            )
        )
        self.register_entry(
            ContextMenuEntry(
                label="Insert Sublayer...",
                show_fn=[is_empty_area, can_edit_root],
                click_fn=_empty_area_insert_click,
                group=GROUP_CREATE,
            )
        )
        self.register_entry(
            ContextMenuEntry(
                label="New Anonymous Sublayer",
                show_fn=[is_empty_area, can_edit_root],
                click_fn=_empty_area_anon_click,
                group=GROUP_CREATE,
            )
        )

        self._register_file_io_entries()
        self._register_mute_lock_entries()
        self._register_merge_flatten_entries()

    # ── Step 40 — Save / Save As / Reload / Remove ───────────────────

    def _register_file_io_entries(self) -> None:
        """Append the Step-40 file-I/O and removal entries.

        Four entries land here:

        - **"Save"** (:data:`GROUP_FILE_IO`) — gated on
          :func:`is_layer_item` + :func:`is_layer_dirty`. Click routes
          through :meth:`LayerModel._request_save` which either pushes
          a :class:`~ovui_widgets.layers.commands.SaveLayerCommand` (concrete
          dirty layer) or forwards to :meth:`_request_save_as` (anonymous
          dirty layer → file-picker flow). Reusing the model entry
          point rather than building a second command path keeps the
          column-2 click and the context-menu click behaving
          identically — no divergent edge cases to audit.
        - **"Save As..."** (:data:`GROUP_FILE_IO`) — gated on
          :func:`is_layer_item` + :func:`is_not_root_layer`. Always
          visible on a non-root layer (even clean concrete ones — a
          "clone this layer to a new path" gesture is legitimate on
          clean layers too). Click opens the Step-36 file picker via
          :meth:`LayerModel._request_save_as`; on confirm the resulting
          :class:`~ovui_widgets.layers.commands.SaveLayerAsCommand` writes the
          new file and, by default, rewrites the parent's sublayer
          reference to the new identifier.
        - **"Reload"** (:data:`GROUP_FILE_IO`) — gated on
          :func:`is_layer_item` + :func:`is_not_anonymous`. Anonymous
          layers have no file to reload from, so the entry hides
          entirely rather than grey out — the user sees only gestures
          that make physical sense. Click routes through
          :meth:`LayerModel._request_reload`, which opens the Step-37
          :func:`~ovui_widgets.common.dialogs.confirm_reload_dialog` when the layer
          is dirty and skips the prompt for clean layers.
        - **"Remove"** (:data:`GROUP_DESTRUCTIVE`) — gated on
          :func:`is_layer_item` + :func:`is_not_root_layer`. Root lives
          in its own group and cannot be removed (it's the tree's
          anchor); the predicate silently hides the entry on root
          rather than showing a disabled row. Click resolves the
          clicked item's parent identifier and position in the parent's
          sublayer list, then routes through
          :meth:`LayerModel._request_remove_sublayer` which opens the
          Step-37 :func:`~ovui_widgets.common.dialogs.confirm_dirty_remove_dialog`
          for dirty layers and pushes a
          :class:`~ovui_widgets.layers.commands.RemoveSublayerCommand` directly
          for clean ones.

        Separator behaviour: the file-I/O trio shares
        :data:`GROUP_FILE_IO` with each other and the Remove entry
        sits in :data:`GROUP_DESTRUCTIVE`. The builder's canonical-
        order pass draws an automatic separator between groups, so
        the menu naturally renders as
        ``[Create group] | [File-I/O group] | [Remove]`` with a
        divider between each — no manual separator registration
        needed. The declarative contract keeps the menu layout
        self-adjusting as later steps (Step 41 Mute/Lock, Step 42
        Merge/Flatten) drop entries into further groups.
        """

        # ── "Save" ──────────────────────────────────────────────────

        def _save_click(ctx: MenuContext) -> None:
            if not isinstance(ctx.item, LayerItem):
                return
            ctx.model._request_save(ctx.item)

        self.register_entry(
            ContextMenuEntry(
                label="Save",
                show_fn=[is_layer_item, is_layer_dirty],
                click_fn=_save_click,
                group=GROUP_FILE_IO,
            )
        )

        # ── "Save As..." ────────────────────────────────────────────

        def _save_as_click(ctx: MenuContext) -> None:
            if not isinstance(ctx.item, LayerItem):
                return
            ctx.model._request_save_as(ctx.item)

        self.register_entry(
            ContextMenuEntry(
                label="Save As...",
                show_fn=[is_layer_item, is_not_root_layer],
                click_fn=_save_as_click,
                group=GROUP_FILE_IO,
            )
        )

        # ── "Reload" ────────────────────────────────────────────────

        def _reload_click(ctx: MenuContext) -> None:
            if not isinstance(ctx.item, LayerItem):
                return
            ctx.model._request_reload(ctx.item)

        self.register_entry(
            ContextMenuEntry(
                label="Reload",
                show_fn=[is_layer_item, is_not_anonymous],
                click_fn=_reload_click,
                group=GROUP_FILE_IO,
            )
        )

        # ── "Remove" ────────────────────────────────────────────────

        def _remove_click(ctx: MenuContext) -> None:
            """Resolve (parent, position) for the clicked row and remove.

            A context-menu Remove is always a sublayer-level gesture —
            the root is filtered out by :func:`is_not_root_layer`. We
            look up the clicked item's parent via :attr:`LayerItem._parent`
            (populated by :meth:`LayerModel._build_tree`) and compute
            the slot index from the adapter's live sublayer list.
            Reading position from the adapter rather than a cached
            ``_sublayers.index(...)`` means a peer command that
            reordered siblings between the menu popup and the click
            can't land the remove on the wrong slot.
            """
            item = ctx.item
            if not isinstance(item, LayerItem):
                return
            parent = item._parent
            if parent is None:
                return
            adapter = ctx.model._adapter
            if adapter is None:
                return
            parent_handle = adapter.find_layer(parent.identifier)
            if parent_handle is None:
                return
            children = adapter.get_sublayer_identifiers(parent_handle)
            if item.identifier not in children:
                return
            position = children.index(item.identifier)
            ctx.model._request_remove_sublayer(parent.identifier, position)

        self.register_entry(
            ContextMenuEntry(
                label="Remove",
                show_fn=[is_layer_item, is_not_root_layer],
                click_fn=_remove_click,
                group=GROUP_DESTRUCTIVE,
            )
        )

    # ── Step 41 — Mute / Unmute / Lock / Unlock + recursive lock ─────

    def _register_mute_lock_entries(self) -> None:
        """Append the Step-41 mute / lock entries to ``GROUP_STATE``.

        Four entries land here:

        - **"Mute Layer" / "Unmute Layer"** — single entry whose
          :attr:`ContextMenuEntry.label_fn` flips the label based on
          the clicked layer's :attr:`LayerItem.is_muted`. Click pushes
          :class:`~ovui_widgets.layers.commands.SetLayerMutenessCommand` with
          the opposite of the current state; the adapter's
          :meth:`~LayerStackAdapter.set_mute` is idempotent, so a
          redundant push through the column-2 eye click is harmless
          but we still flip the bit through the command pipeline so
          the undo stack tracks the gesture.
        - **"Lock Layer" / "Unlock Layer"** — same shape for the
          lock bit, routed through
          :class:`~ovui_widgets.layers.commands.SetLayerLockCommand`. The
          per-layer bit only; recursive locking is the job of the
          two entries below.
        - **"Lock Layer and Descendants"** — walks the clicked item's
          subtree (including the clicked layer itself) and pushes one
          :class:`SetLayerLockCommand` per not-already-locked layer
          inside a single :meth:`UndoManager.begin_group` /
          :meth:`UndoManager.end_group` wrapper. One Ctrl+Z undoes the
          whole tree-lock in a single step (plan Verify clause).
        - **"Unlock Layer and Descendants"** — inverse of the above;
          pushes one command per currently-locked layer in the subtree.

        All four entries share :data:`GROUP_STATE`; the canonical-order
        pass in :meth:`_canonical_order` places them between the
        create group (20) and the file-I/O group (40) and draws
        automatic separators between adjacent non-empty groups — no
        manual separator registration is needed, matching the task's
        "separator before the mute/lock group" requirement.

        Subtree traversal uses :attr:`LayerItem.sublayers` (the in-memory
        tree built by :class:`LayerModel`) rather than walking the
        adapter directly. The in-memory tree already reflects the
        cycle-guard from :meth:`LayerModel._load_sublayers`, so we
        can't recurse into a USD sublayer cycle. Duplicated
        identifiers (a layer sublayered in two places) are deduped via
        a ``seen`` set so a single tree-lock emits at most one command
        per identifier — locking the same layer twice would produce
        a no-op second command and clutter the group accumulator.
        """

        # ── Lazy import — keeps unit tests that only exercise
        # predicates ovui-free (same pattern as Steps 39 / 40).
        from ovui_widgets.layers.commands.layer_commands import (
            SetLayerLockCommand,
            SetLayerMutenessCommand,
        )

        # ── "Mute Layer" / "Unmute Layer" ───────────────────────────

        def _mute_label(ctx: MenuContext) -> str:
            if isinstance(ctx.item, LayerItem) and ctx.item.is_muted:
                return "Unmute Layer"
            return "Mute Layer"

        def _mute_click(ctx: MenuContext) -> None:
            item = ctx.item
            if not isinstance(item, LayerItem):
                return
            services = ctx.services
            if services is None:
                return
            adapter = ctx.model._adapter
            if adapter is None:
                return
            cmd = SetLayerMutenessCommand(
                adapter,
                services.selection_bus,
                item.identifier,
                not item.is_muted,
            )
            services.undo_manager.push(cmd)

        self.register_entry(
            ContextMenuEntry(
                label="Mute Layer",
                show_fn=[is_layer_item],
                click_fn=_mute_click,
                label_fn=_mute_label,
                group=GROUP_STATE,
            )
        )

        # ── "Lock Layer" / "Unlock Layer" ───────────────────────────

        def _lock_label(ctx: MenuContext) -> str:
            if isinstance(ctx.item, LayerItem) and ctx.item.is_locked:
                return "Unlock Layer"
            return "Lock Layer"

        def _lock_click(ctx: MenuContext) -> None:
            item = ctx.item
            if not isinstance(item, LayerItem):
                return
            services = ctx.services
            if services is None:
                return
            adapter = ctx.model._adapter
            if adapter is None:
                return
            cmd = SetLayerLockCommand(
                adapter,
                services.selection_bus,
                item.identifier,
                not item.is_locked,
            )
            services.undo_manager.push(cmd)

        self.register_entry(
            ContextMenuEntry(
                label="Lock Layer",
                show_fn=[is_layer_item],
                click_fn=_lock_click,
                label_fn=_lock_label,
                group=GROUP_STATE,
            )
        )

        # ── "Lock/Unlock Layer and Descendants" ─────────────────────

        def _collect_subtree(
            root: LayerItem,
        ) -> List[LayerItem]:
            """Depth-first walk of ``root`` + every descendant.

            Dedupes by identifier so a layer sublayered in two places
            contributes exactly one entry. The order is stable
            (depth-first pre-order) so the undo group replays in a
            predictable order; the order doesn't matter for the
            per-layer lock bit, but it helps a future test assert on
            the exact command sequence.
            """
            seen: set = set()
            out: List[LayerItem] = []

            def _walk(node: LayerItem) -> None:
                if node.identifier in seen:
                    return
                seen.add(node.identifier)
                out.append(node)
                for sub in node.sublayers:
                    _walk(sub)

            _walk(root)
            return out

        def _tree_lock_click(ctx: MenuContext, target_locked: bool) -> None:
            item = ctx.item
            if not isinstance(item, LayerItem):
                return
            services = ctx.services
            if services is None:
                return
            adapter = ctx.model._adapter
            if adapter is None:
                return
            targets = [
                node
                for node in _collect_subtree(item)
                if node.is_locked != target_locked
            ]
            if not targets:
                return
            label = "Lock tree" if target_locked else "Unlock tree"
            undo_manager = services.undo_manager
            undo_manager.begin_group(label)
            try:
                for node in targets:
                    cmd = SetLayerLockCommand(
                        adapter,
                        services.selection_bus,
                        node.identifier,
                        target_locked,
                    )
                    undo_manager.push(cmd)
            finally:
                undo_manager.end_group()

        def _lock_tree_click(ctx: MenuContext) -> None:
            _tree_lock_click(ctx, True)

        def _unlock_tree_click(ctx: MenuContext) -> None:
            _tree_lock_click(ctx, False)

        self.register_entry(
            ContextMenuEntry(
                label="Lock Layer and Descendants",
                show_fn=[is_layer_item],
                click_fn=_lock_tree_click,
                group=GROUP_STATE,
            )
        )
        self.register_entry(
            ContextMenuEntry(
                label="Unlock Layer and Descendants",
                show_fn=[is_layer_item],
                click_fn=_unlock_tree_click,
                group=GROUP_STATE,
            )
        )

    # ── Step 42 — Merge Down / Flatten Sublayers ─────────────────────

    def _register_merge_flatten_entries(self) -> None:
        """Append the Step-42 merge / flatten entries to ``GROUP_DESTRUCTIVE``.

        Two entries land here:

        - **"Merge Down"** — gated on :func:`is_layer_item` +
          :func:`is_writable` + :func:`has_sibling_below`. Click resolves
          the source layer's position in its parent, opens the
          :func:`~ovui_widgets.common.dialogs.confirm_merge_down_dialog` scary
          confirmation, and on confirm pushes a
          :class:`~ovui_widgets.layers.commands.MergeDownCommand`. The command
          snapshots both layers for a full undo round-trip.
        - **"Flatten Sublayers"** — gated on :func:`is_layer_item` +
          :func:`is_writable` + :func:`has_sublayers`. Opens
          :func:`~ovui_widgets.common.dialogs.confirm_flatten_dialog` with the
          sublayer count, and on confirm pushes a
          :class:`~ovui_widgets.layers.commands.FlattenSublayersCommand`.

        Both entries sit in :data:`GROUP_DESTRUCTIVE`, after the
        Step-40 "Remove" entry. Canonical order renders the full
        destructive group at the bottom of the menu with a separator
        above — the user reaches it last.

        The confirmation dialog is opened lazily (``on_confirm``
        callback pushes the command) so a cancel leaves the undo /
        redo stacks untouched. When the application instance is not
        available (headless unit tests) or the dialog could not be
        built (missing ui backend), the click short-circuits without
        pushing anything — cancel-equivalent.
        """
        from ovui_widgets.layers.commands.merge_flatten_commands import (
            FlattenSublayersCommand,
            MergeDownCommand,
        )

        # ── "Merge Down" ────────────────────────────────────────────

        def _merge_down_click(ctx: MenuContext) -> None:
            item = ctx.item
            if not isinstance(item, LayerItem):
                return
            parent = item.parent
            if parent is None:
                return
            services = ctx.services
            if services is None:
                return
            adapter = ctx.model._adapter
            if adapter is None:
                return
            parent_handle = adapter.find_layer(parent.identifier)
            if parent_handle is None:
                return
            siblings = adapter.get_sublayer_identifiers(parent_handle)
            try:
                position = siblings.index(item.identifier)
            except ValueError:
                return
            if position + 1 >= len(siblings):
                return
            destination_id = siblings[position + 1]
            source_name = adapter.get_display_name(
                adapter.find_layer(item.identifier) or parent_handle
            )
            dest_handle = adapter.find_layer(destination_id)
            destination_name = (
                adapter.get_display_name(dest_handle)
                if dest_handle is not None
                else destination_id
            )

            def _on_confirm() -> None:
                cmd = MergeDownCommand(
                    adapter,
                    services.selection_bus,
                    parent.identifier,
                    position,
                )
                services.undo_manager.push(cmd)

            # Lazy import matches the rest of the context-menu dialog
            # surface — keeps pure predicate unit tests ovui-free.
            from ovui_widgets.common.dialogs import confirm_merge_down_dialog

            confirm_merge_down_dialog(
                source_name=source_name,
                destination_name=destination_name,
                on_merge=_on_confirm,
            )

        self.register_entry(
            ContextMenuEntry(
                label="Merge Down",
                show_fn=[is_layer_item, is_writable, has_sibling_below],
                click_fn=_merge_down_click,
                group=GROUP_DESTRUCTIVE,
            )
        )

        # ── "Flatten Sublayers" ─────────────────────────────────────

        def _flatten_click(ctx: MenuContext) -> None:
            item = ctx.item
            if not isinstance(item, LayerItem):
                return
            services = ctx.services
            if services is None:
                return
            adapter = ctx.model._adapter
            if adapter is None:
                return
            parent_handle = adapter.find_layer(item.identifier)
            if parent_handle is None:
                return
            sublayer_ids = adapter.get_sublayer_identifiers(parent_handle)
            if not sublayer_ids:
                return
            parent_name = adapter.get_display_name(parent_handle)

            def _on_confirm() -> None:
                cmd = FlattenSublayersCommand(
                    adapter,
                    services.selection_bus,
                    item.identifier,
                )
                services.undo_manager.push(cmd)

            from ovui_widgets.common.dialogs import confirm_flatten_dialog

            confirm_flatten_dialog(
                parent_name=parent_name,
                sublayer_count=len(sublayer_ids),
                on_flatten=_on_confirm,
            )

        self.register_entry(
            ContextMenuEntry(
                label="Flatten Sublayers",
                show_fn=[is_layer_item, is_writable, has_sublayers],
                click_fn=_flatten_click,
                group=GROUP_DESTRUCTIVE,
            )
        )

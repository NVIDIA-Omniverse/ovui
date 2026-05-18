# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Row object for a single layer in the Layers tree (LAYERS-PLAN Step 12).

:class:`LayerItem` is a :class:`omni.ui.AbstractItem`. Every row in the
Layers ``ui.TreeView`` — root, session, sublayers, live-session ``.live``
children — is one of these.

The item holds an ``identifier`` string + a reference to the owning
:class:`~ovwidgets.common.adapters.LayerStackAdapter`; it never reaches into
``pxr``. This is the Kit-free equivalent of Kit's
``omni.kit.widget.layers.LayerItem`` (which stores an ``Sdf.Layer``
directly) — we go through the adapter boundary instead so the widget
package remains backend-agnostic (LAYERS-WINDOW-ARCHITECTURE §17,
widget-window split / constraint G2).

Flag caching follows the same dirty-bit pattern as
:class:`ovwidgets.stage.widget.hierarchy_model.HierarchyItem`: the seven
state flags are re-read lazily on first access after
:meth:`invalidate_flags`, not on every render.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

import omni.ui as ui
from ovui_data_adapters.common import LayerHandle, LayerStackAdapter

if TYPE_CHECKING:  # pragma: no cover — type-hint guard
    # Value models land in Phase D (Step 18+); referenced here only so the
    # column-cache attribute annotations type-check cleanly.
    from ovwidgets.layers.models.layer_name_model import LayerNameValueModel
    from ovwidgets.layers.models.lock_model import LockValueModel
    from ovwidgets.layers.models.mute_model import LocalMuteValueModel
    from ovwidgets.layers.models.save_model import SaveValueModel


class LayerItem(ui.AbstractItem):
    """One row in the Layers tree, tied to a ``LayerStackAdapter`` identifier.

    Construction is intentionally cheap: no adapter calls are made until
    a state-flag property is read or :meth:`refresh_flags` is invoked.
    The sublayer list is built by :class:`LayerModel` (Step 13+); the
    prim-spec list is built in Phase J.
    """

    def __init__(
        self,
        adapter: LayerStackAdapter,
        identifier: str,
        parent: Optional["LayerItem"] = None,
        is_session_layer: bool = False,
    ) -> None:
        super().__init__()
        self._adapter: LayerStackAdapter = adapter
        self._identifier: str = identifier
        self._parent: Optional["LayerItem"] = parent
        self._is_session_layer: bool = is_session_layer

        # Tree structure — populated by LayerModel / later phases.
        self._sublayers: List["LayerItem"] = []
        # Prim-spec rows (Phase J, LAYERS-PLAN Step 48). Materialised
        # lazily by :class:`LayerModel` on the first
        # :meth:`get_item_children` call that targets this layer item;
        # ``_prim_specs_loaded`` distinguishes "never queried" from
        # "queried and empty" so a childless layer does not re-hit the
        # adapter on every paint. Typed as :class:`Any` so Step 12 has
        # no forward-reference dependency on a class that only becomes
        # importable in Step 48.
        self._prim_specs: List[Any] = []
        self._prim_specs_loaded: bool = False

        # Flag cache with dirty bit. ``True`` means "the cached flag
        # fields are stale and must be refreshed from the adapter on
        # next access". Starts dirty so the very first property read
        # hits the adapter.
        self._flags_dirty: bool = True
        self._is_dirty: bool = False
        self._is_muted: bool = False
        self._is_locked: bool = False
        self._is_missing: bool = False
        self._is_read_only: bool = False
        self._is_anonymous: bool = False

        # Edit-target state — not read from the adapter; propagated by
        # :class:`LayerModel` (Phase E) after it resolves
        # ``get_edit_target_identifier()`` and walks the parent chain.
        self._is_edit_target: bool = False
        self._has_edit_target_descendant: bool = False

        # Keyboard-focus state (LAYERS-PLAN Step 62). Set by
        # :class:`LayerWindow` whenever the tree's selection collapses
        # to a single row so the delegate paints a 1-px focus ring.
        # Never read from the adapter — purely a UI-side flag.
        self._is_focused: bool = False

        # Filter state (Phase K). ``_filtered`` — this item matches the
        # active search; ``_child_filtered`` — some descendant matches.
        self._filtered: bool = False
        self._child_filtered: bool = False

        # Column value models — lazily constructed on first access in
        # Phase D (LAYERS-PLAN Logic F4). Left ``None`` here so the
        # constructor performs no allocation tied to columns that are
        # never rendered (a collapsed row never asks for its save
        # model, so we don't pay for it). Step 22 adds the live /
        # latest slots alongside these.
        self._name_model: Optional["LayerNameValueModel"] = None
        self._save_model: Optional["SaveValueModel"] = None
        self._local_mute_model: Optional["LocalMuteValueModel"] = None
        self._lock_model: Optional["LockValueModel"] = None

    # ── Identity / navigation ────────────────────────────────────────

    @property
    def identifier(self) -> str:
        """Stable adapter key (matches ``Sdf.Layer.identifier`` in USD adapters)."""
        return self._identifier

    @property
    def parent(self) -> Optional["LayerItem"]:
        """The containing ``LayerItem``, or ``None`` for top-level rows."""
        return self._parent

    @property
    def is_session_layer(self) -> bool:
        """``True`` for the single session-layer row (root of the session branch)."""
        return self._is_session_layer

    @property
    def sublayers(self) -> List["LayerItem"]:
        """Direct sublayer rows. Mutated by :class:`LayerModel`."""
        return self._sublayers

    @property
    def prim_specs(self) -> List[Any]:
        """Lazy prim-spec rows — empty until Phase J."""
        return self._prim_specs

    @property
    def display_name(self) -> str:
        """Human-readable name as reported by the adapter.

        Read through every time — display name can change (e.g. the
        layer got renamed on disk) and the adapter is the source of
        truth. Value-model caching lands in Phase D.
        """
        return self._adapter.get_display_name(LayerHandle(self._identifier))

    @property
    def depth(self) -> int:
        """Distance from the top-level row (0 = root or session)."""
        depth = 0
        node = self._parent
        while node is not None:
            depth += 1
            node = node._parent
        return depth

    # ── Edit-target state (set by LayerModel) ────────────────────────

    @property
    def is_edit_target(self) -> bool:
        """This layer is the current authoring target (the starred row)."""
        return self._is_edit_target

    @is_edit_target.setter
    def is_edit_target(self, value: bool) -> None:
        self._is_edit_target = bool(value)

    @property
    def has_edit_target_descendant(self) -> bool:
        """Some descendant of this layer is the current edit target.

        Used by the delegate to draw the half-green "ancestor of edit
        target" icon on collapsed parents (LAYERS-WINDOW-ARCHITECTURE
        §17.3).
        """
        return self._has_edit_target_descendant

    @has_edit_target_descendant.setter
    def has_edit_target_descendant(self, value: bool) -> None:
        self._has_edit_target_descendant = bool(value)

    @property
    def is_focused(self) -> bool:
        """This row is the single keyboard-focus target (Step 62).

        The delegate paints a 1-px accent-tinted focus ring around the
        row when this flag is ``True``. Set by :class:`LayerWindow`
        from :meth:`_on_tree_selection_changed` so single-item
        selections collapse to a focused row; multi-select clears the
        focus ring because there is no single "next arrow target".
        """
        return self._is_focused

    @is_focused.setter
    def is_focused(self, value: bool) -> None:
        self._is_focused = bool(value)

    # ── Filter state (set by LayerModel in Phase K) ──────────────────

    @property
    def filtered(self) -> bool:
        """This row matches the active search text."""
        return self._filtered

    @filtered.setter
    def filtered(self, value: bool) -> None:
        self._filtered = bool(value)

    @property
    def child_filtered(self) -> bool:
        """Some descendant row matches the active search text."""
        return self._child_filtered

    @child_filtered.setter
    def child_filtered(self, value: bool) -> None:
        self._child_filtered = bool(value)

    # ── Flag cache ───────────────────────────────────────────────────

    def invalidate_flags(self) -> None:
        """Mark the cached flag snapshot stale.

        Called by :class:`LayerModel` on every incoming
        :class:`~ovwidgets.common.adapters.LayerEvent` that touches a flag on
        this layer. The next flag-property read will re-query the
        adapter.
        """
        self._flags_dirty = True

    # Kept as an alias because the plan prose and the HierarchyItem
    # precedent both spell the invalidator ``mark_dirty``. Same method,
    # same semantics.
    mark_dirty = invalidate_flags

    def invalidate_prim_specs(self) -> None:
        """Drop the cached prim-spec child rows (LAYERS-PLAN Step 48).

        :class:`LayerModel` calls this on structural events that may
        have mutated the layer's top-level prim hierarchy so the next
        :meth:`get_item_children` query re-reads descriptors from the
        adapter rather than returning stale rows.
        """
        self._prim_specs = []
        self._prim_specs_loaded = False

    def refresh_flags(self) -> None:
        """Re-read all seven state flags from the adapter.

        No-op if ``_flags_dirty`` is ``False``. Calling this while clean
        is therefore safe and cheap; property accessors rely on it to
        return consistent results without duplicated dispatch.
        """
        if not self._flags_dirty:
            return
        handle = LayerHandle(self._identifier)
        self._is_dirty = self._adapter.is_dirty(handle)
        self._is_muted = self._adapter.is_muted(handle)
        self._is_locked = self._adapter.is_locked(handle)
        self._is_missing = self._adapter.is_missing(handle)
        self._is_read_only = self._adapter.is_read_only_on_disk(handle)
        self._is_anonymous = self._adapter.is_anonymous(handle)
        self._flags_dirty = False

    # ── State-flag properties (auto-refresh on access) ───────────────

    @property
    def is_dirty(self) -> bool:
        """Layer has unsaved edits."""
        self.refresh_flags()
        return self._is_dirty

    @property
    def is_muted(self) -> bool:
        """Layer is muted (excluded from composition)."""
        self.refresh_flags()
        return self._is_muted

    @property
    def is_locked(self) -> bool:
        """Layer is locked against authoring (advisory)."""
        self.refresh_flags()
        return self._is_locked

    @property
    def is_missing(self) -> bool:
        """Layer could not be resolved by the adapter."""
        self.refresh_flags()
        return self._is_missing

    @property
    def is_read_only(self) -> bool:
        """Backing file is not writable by the current user."""
        self.refresh_flags()
        return self._is_read_only

    @property
    def is_anonymous(self) -> bool:
        """Layer is in-memory only (no file path)."""
        self.refresh_flags()
        return self._is_anonymous

    @property
    def is_writable(self) -> bool:
        """Composite writability: not locked, not muted, not read-only on disk.

        Delegates to :meth:`LayerStackAdapter.is_writable` so every adapter
        (including subclasses that override for a faster path) shares a
        single definition.
        """
        return self._adapter.is_writable(LayerHandle(self._identifier))

    # ── Cascade flags (LAYERS-PLAN Step 32) ──────────────────────────

    @property
    def muted_or_parent_muted(self) -> bool:
        """``True`` if this layer — or any ancestor — is muted.

        USD composition mutes a layer *and* every layer beneath it in
        the sublayer tree: editing a row under a muted parent still
        persists to USD but the composed stage ignores the whole
        branch. The Layers row must signal that by switching to the
        ``disabled`` color role. Walks the parent chain so the cascade
        is always a fresh read; :meth:`invalidate_flags` on the
        ancestor is enough to flip every descendant's answer on the
        very next render.
        """
        node: Optional["LayerItem"] = self
        while node is not None:
            if node.is_muted:
                return True
            node = node._parent
        return False

    @property
    def locked_or_parent_locked(self) -> bool:
        """``True`` if this layer — or any ancestor — is locked.

        Lock cascade follows the same convention as mute cascade
        (LAYERS-WINDOW-ARCHITECTURE §17.4): a locked parent renders
        every descendant as non-editable in the UI even though the
        per-layer lock bit on the child is ``False``. Walks the parent
        chain on every read so an ancestor toggle fans out without
        needing an explicit flag push.
        """
        node: Optional["LayerItem"] = self
        while node is not None:
            if node.is_locked:
                return True
            node = node._parent
        return False

    # ── Introspection ────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"LayerItem(identifier={self._identifier!r}, "
            f"session={self._is_session_layer}, depth={self.depth})"
        )

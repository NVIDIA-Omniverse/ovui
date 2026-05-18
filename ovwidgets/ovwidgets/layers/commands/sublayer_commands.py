# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Sublayer-manipulation commands (LAYERS-PLAN Step 30 / Step 31 / Step 31a).

Six concrete :class:`AbstractLayerCommand` subclasses that wrap the
adapter's sublayer-list and prim-spec mutators so create / insert /
remove / move / replace gestures (plus prim-spec delete) join the
undo stack:

- :class:`CreateSublayerCommand` — mint a fresh (named or anonymous)
  sublayer under a parent. ``do_impl`` calls
  :meth:`~ovwidgets.common.adapters.LayerStackAdapter.create_sublayer` on the
  first execution and stores the minted identifier; subsequent redo
  calls re-insert the same identifier rather than minting a second
  layer record (the adapter keeps the record alive once created).
  ``undo_impl`` finds the current position of the created identifier
  in the parent's sublayer list and removes it — the position may
  have shifted since ``do`` if a peer command moved siblings around.

- :class:`InsertSublayerCommand` — insert an *existing* layer
  reference under a parent. Symmetrical to create: ``do_impl`` calls
  :meth:`~ovwidgets.common.adapters.LayerStackAdapter.insert_sublayer` and
  ``undo_impl`` removes the identifier from the parent again.

- :class:`RemoveSublayerCommand` — remove the sublayer at a given
  slot. ``do_impl`` snapshots enough state to round-trip: the
  identifier at the slot, its per-layer mute + lock bits, and — if
  the removed layer was the edit target — the stack's edit target.
  When the removed layer is the current edit target, ``do_impl``
  first flips the edit target to root so the removal does not leave
  the adapter pointing at a detached layer. ``undo_impl`` reinserts
  the layer at the original position and restores mute + lock; the
  base class's :meth:`~AbstractLayerCommand._restore_state` handles
  the edit-target revert after ``undo_impl`` has already reinserted
  the layer so ``find_layer`` + ``is_writable`` succeed.

- :class:`MoveSublayerCommand` — move a sublayer from one slot to
  another, within the same parent (reorder) or across parents.
  ``do_impl`` snapshots the identifier at ``(from_parent, from_pos)``
  on the first call so undo can locate the layer in its new slot by
  identifier (robust against peer reorders between ``do`` and
  ``undo``). The adapter's own ``move_sublayer`` owns the index-shift
  arithmetic for same-parent reorders — this command is a thin
  undoable wrapper.

- :class:`ReplaceSublayerCommand` — swap the identifier at
  ``(parent, position)`` for a new one via the adapter's atomic
  :meth:`~ovwidgets.common.adapters.LayerStackAdapter.replace_sublayer`.
  Used by Save-As-with-replace (Step 36). ``do_impl`` captures the old
  identifier on the first call; ``undo_impl`` re-replaces to put it
  back.

- :class:`RemovePrimSpecsCommand` — delete a batch of prim specs
  across one or more layers. ``do_impl`` serialises each spec via
  :meth:`~ovwidgets.common.adapters.LayerStackAdapter.export_prim_spec`
  *before* removing it so ``undo_impl`` can restore the exact bytes
  through :meth:`~ovwidgets.common.adapters.LayerStackAdapter.import_prim_spec`.
  The undo walks the snapshots in reverse so nested specs reappear
  inside their parents rather than racing ahead of them.

See LAYERS-PLAN Step 30 / Step 31 / Step 31a and
LAYERS-WINDOW-ARCHITECTURE §13.3 / §13.4 for the full design contract.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from ovui_data_adapters.common import LayerStackAdapter

from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.undo import CommandCancelled
from ovwidgets.layers.commands.base import AbstractLayerCommand


class CreateSublayerCommand(AbstractLayerCommand):
    """Create a new sublayer under ``parent_id`` at ``position``.

    ``new_layer_path`` follows
    :meth:`~ovwidgets.common.adapters.LayerStackAdapter.create_sublayer`
    semantics — an empty string mints an anonymous layer, otherwise
    a fresh file is created at the given path. ``position`` uses
    :meth:`list.insert` semantics (``-1`` appends).
    ``transfer_root_content`` propagates the "split root to sublayer"
    flag from the plan's Phase-H gesture.

    ``do_impl`` on the first call asks the adapter to mint the layer
    and stores the returned identifier. On redo, the identifier is
    already known and the adapter already holds the layer record, so
    we route through
    :meth:`~ovwidgets.common.adapters.LayerStackAdapter.insert_sublayer`
    instead of re-minting — this keeps named paths safe (the adapter
    refuses to clobber an existing path) and prevents anonymous
    identifier drift (repeated ``create_sublayer("")`` would each
    mint a fresh ``anon:N``).
    """

    def __init__(
        self,
        adapter: LayerStackAdapter,
        selection_bus: SelectionBus,
        parent_id: str,
        position: int,
        new_layer_path: str,
        transfer_root_content: bool = False,
    ) -> None:
        super().__init__(adapter, selection_bus)
        self._parent_id = parent_id
        self._position = position
        self._new_layer_path = new_layer_path
        self._transfer_root_content = bool(transfer_root_content)
        self._created_identifier: Optional[str] = None

    def do_impl(self) -> None:
        if self._created_identifier is None:
            self._created_identifier = self._adapter.create_sublayer(
                self._parent_id,
                self._position,
                self._new_layer_path,
                self._transfer_root_content,
            )
        else:
            # Redo path: the layer record still lives in the adapter
            # (undo only unlinks it from the parent's sublayer list).
            # Re-insert by identifier rather than re-creating so named
            # paths don't trip the adapter's clobber guard and anon
            # layers don't drift to a fresh ``anon:N``.
            self._adapter.insert_sublayer(
                self._parent_id,
                self._position,
                self._created_identifier,
            )

    def undo_impl(self) -> None:
        if self._created_identifier is None:
            return
        parent_handle = self._adapter.find_layer(self._parent_id)
        if parent_handle is None:
            return
        children = self._adapter.get_sublayer_identifiers(parent_handle)
        if self._created_identifier in children:
            pos = children.index(self._created_identifier)
            self._adapter.remove_sublayer(self._parent_id, pos)


class InsertSublayerCommand(AbstractLayerCommand):
    """Insert an *existing* layer reference under ``parent_id``.

    Used by the "Insert Sublayer" gesture and the Content-Browser
    "Insert As Sublayer" menu entry — both supply a path to a layer
    that already exists on disk, and the adapter stores it as a
    sublayer reference without minting a new file.

    ``undo_impl`` finds the current position of ``sublayer_path``
    under the parent and removes it by index — we search by
    identifier rather than remembering the inserted index because a
    peer command may have reordered siblings between ``do`` and
    ``undo`` (same rationale as
    :meth:`CreateSublayerCommand.undo_impl`).
    """

    def __init__(
        self,
        adapter: LayerStackAdapter,
        selection_bus: SelectionBus,
        parent_id: str,
        position: int,
        sublayer_path: str,
    ) -> None:
        super().__init__(adapter, selection_bus)
        self._parent_id = parent_id
        self._position = position
        self._sublayer_path = sublayer_path

    def do_impl(self) -> None:
        self._adapter.insert_sublayer(
            self._parent_id, self._position, self._sublayer_path
        )

    def undo_impl(self) -> None:
        parent_handle = self._adapter.find_layer(self._parent_id)
        if parent_handle is None:
            return
        children = self._adapter.get_sublayer_identifiers(parent_handle)
        if self._sublayer_path in children:
            pos = children.index(self._sublayer_path)
            self._adapter.remove_sublayer(self._parent_id, pos)


class RemoveSublayerCommand(AbstractLayerCommand):
    """Remove the sublayer at ``(parent_id, position)``.

    ``do_impl`` snapshots enough state for a round-trip:

    - The identifier currently at the slot — stored so ``undo_impl``
      can reinsert the same reference and so peer subscribers can
      see a stable target in the emitted event stream.
    - The removed layer's mute + lock bits — the USD-backed adapter
      may clear these on removal, so we restore them explicitly.
      The mock adapter persists the ``MockLayer`` record after
      removal, making the restore a harmless no-op there.
    - An edit-target-was-here flag — if the removed layer was the
      stack's edit target, ``do_impl`` flips the target to root
      *before* the removal so the adapter never points at a
      detached layer. The base class's
      :meth:`~AbstractLayerCommand._restore_state` reverts the edit
      target after ``undo_impl`` has already reinserted the layer
      (so the re-target's ``find_layer`` + ``is_writable`` check
      succeeds).

    ``undo_impl`` reinserts by identifier at the original slot, then
    replays mute + lock bits; edit-target restoration happens in the
    base class's state-restore phase.
    """

    def __init__(
        self,
        adapter: LayerStackAdapter,
        selection_bus: SelectionBus,
        parent_id: str,
        position: int,
        confirm_callback: Optional[Callable[[str], bool]] = None,
    ) -> None:
        super().__init__(adapter, selection_bus)
        self._parent_id = parent_id
        self._position = position
        self._removed_identifier: Optional[str] = None
        self._was_muted: bool = False
        self._was_locked: bool = False
        self._was_edit_target: bool = False
        # LAYERS-PLAN Step 37 guard hook. ``confirm_callback(child_id)``
        # returns ``True`` to proceed, ``False`` to abort with
        # :class:`~ovwidgets.common.undo.CommandCancelled`. Tests drive this
        # synchronously (no dialog); at runtime the caller decides
        # before push whether to pass a gate (see
        # ``LayerModel._request_remove_sublayer``). Only consulted on
        # the first ``do`` — a redo replays the captured state without
        # re-asking.
        self._confirm_callback = confirm_callback

    def do_impl(self) -> None:
        parent_handle = self._adapter.find_layer(self._parent_id)
        if parent_handle is None:
            raise KeyError(
                f"RemoveSublayerCommand: parent {self._parent_id!r} not found"
            )
        children = self._adapter.get_sublayer_identifiers(parent_handle)
        if self._position < 0 or self._position >= len(children):
            raise IndexError(
                f"RemoveSublayerCommand: position {self._position} "
                f"out of range for parent {self._parent_id!r}"
            )
        identifier = children[self._position]

        # First-do guard hook — any caller that wants a pre-remove
        # confirm (dirty-layer prompt, read-only stack warning) plugs
        # in a callback. A ``False`` return short-circuits the push
        # via :class:`~ovwidgets.common.undo.CommandCancelled`, which
        # :meth:`UndoManager.push` catches and discards without
        # mutating the undo/redo stacks. Only runs on the first
        # ``do`` — a later redo replays the captured state directly.
        if (
            self._removed_identifier is None
            and self._confirm_callback is not None
        ):
            if not self._confirm_callback(identifier):
                raise CommandCancelled()

        # Snapshot mute + lock only on the first do; redo must not
        # re-capture post-undo state (which could differ if another
        # command mutated the layer in between).
        if self._removed_identifier is None:
            self._removed_identifier = identifier
            removed_handle = self._adapter.find_layer(identifier)
            if removed_handle is not None:
                self._was_muted = self._adapter.is_muted(removed_handle)
                self._was_locked = self._adapter.is_locked(removed_handle)
            self._was_edit_target = (
                self._adapter.get_edit_target_identifier() == identifier
            )

        # If the layer we're about to remove is the edit target, move
        # the target to root first so the adapter never points at a
        # detached layer during the brief window inside ``remove_sublayer``.
        if self._was_edit_target:
            root_identifier = self._adapter.get_root_layer().identifier
            if self._adapter.get_edit_target_identifier() != root_identifier:
                self._adapter.set_edit_target(root_identifier)

        self._adapter.remove_sublayer(self._parent_id, self._position)

    def undo_impl(self) -> None:
        if self._removed_identifier is None:
            return
        # Reinsert at the original slot. ``insert_sublayer`` tolerates
        # unknown identifiers by creating a missing-layer stub, but
        # after ``do_impl`` the record still lives in the adapter so
        # this lands the original layer back in place.
        self._adapter.insert_sublayer(
            self._parent_id, self._position, self._removed_identifier
        )
        # Replay mute + lock. The mock's setters no-op when the bit
        # already matches; the USD adapter may have cleared them on
        # removal, so the explicit re-set matters there.
        self._adapter.set_mute(self._removed_identifier, self._was_muted)
        self._adapter.set_lock(self._removed_identifier, self._was_locked)


class MoveSublayerCommand(AbstractLayerCommand):
    """Move a sublayer from ``(from_parent_id, from_position)`` to
    ``(to_parent_id, to_position)``.

    The two slots may share a parent (reorder within one layer's
    sublayer list) or live under different parents (cross-parent
    relocation). The adapter's
    :meth:`~ovwidgets.common.adapters.LayerStackAdapter.move_sublayer` owns
    the destination-index adjustment for same-parent reorders (pop
    then insert semantics); this command layers undo on top of it.

    ``do_impl`` snapshots the identifier at ``(from_parent_id,
    from_position)`` on the first execution and stores it on
    :attr:`_moved_identifier`. On undo, the layer's *current* position
    in the destination parent is located by identifier rather than by
    the stored ``to_position`` — a peer command may have reordered
    siblings between ``do`` and ``undo``, and the adapter's own
    pop-then-insert can settle the layer one slot off from the raw
    ``to_position`` argument (same-parent reorders to a later slot).
    Undo then re-invokes ``move_sublayer`` with the current position
    as source and the original ``from_position`` as target.

    A "null move" (``from == to``) is still undoable for consistency
    with the undo-group wrapper — both do and undo resolve to
    idempotent adapter calls.
    """

    def __init__(
        self,
        adapter: LayerStackAdapter,
        selection_bus: SelectionBus,
        from_parent_id: str,
        from_position: int,
        to_parent_id: str,
        to_position: int,
    ) -> None:
        super().__init__(adapter, selection_bus)
        self._from_parent_id = from_parent_id
        self._from_position = from_position
        self._to_parent_id = to_parent_id
        self._to_position = to_position
        self._moved_identifier: Optional[str] = None

    def do_impl(self) -> None:
        if self._moved_identifier is None:
            parent_handle = self._adapter.find_layer(self._from_parent_id)
            if parent_handle is None:
                raise KeyError(
                    f"MoveSublayerCommand: parent "
                    f"{self._from_parent_id!r} not found"
                )
            children = self._adapter.get_sublayer_identifiers(parent_handle)
            if (
                self._from_position < 0
                or self._from_position >= len(children)
            ):
                raise IndexError(
                    f"MoveSublayerCommand: from_position "
                    f"{self._from_position} out of range for "
                    f"{self._from_parent_id!r}"
                )
            self._moved_identifier = children[self._from_position]

        self._adapter.move_sublayer(
            self._from_parent_id,
            self._from_position,
            self._to_parent_id,
            self._to_position,
        )

    def undo_impl(self) -> None:
        if self._moved_identifier is None:
            return
        to_parent_handle = self._adapter.find_layer(self._to_parent_id)
        if to_parent_handle is None:
            return
        children_to = self._adapter.get_sublayer_identifiers(to_parent_handle)
        if self._moved_identifier not in children_to:
            return
        current_pos = children_to.index(self._moved_identifier)
        # Adapter's ``move_sublayer`` treats ``to_position`` as the
        # insert-before index in the *pre-pop* list and compensates for
        # the pop when ``to_position > from_position`` under the same
        # parent. That shift is applied inside the adapter, so when the
        # undo target slot sits strictly after the current slot (within
        # the same parent), we pre-inflate ``to_position`` by one to
        # cancel the adapter's subtraction. Without this, undoing a
        # backward same-parent move lands the element one slot short of
        # its origin (e.g. [A,B,C] → move pos 2 → pos 0 → [C,A,B] →
        # undo would settle at [A,C,B] instead of restoring [A,B,C]).
        target_position = self._from_position
        if (
            self._from_parent_id == self._to_parent_id
            and target_position > current_pos
        ):
            target_position += 1
        self._adapter.move_sublayer(
            self._to_parent_id,
            current_pos,
            self._from_parent_id,
            target_position,
        )


class ReplaceSublayerCommand(AbstractLayerCommand):
    """Swap the identifier at ``(parent_id, position)`` for ``new_identifier``.

    Routes through the adapter's atomic
    :meth:`~ovwidgets.common.adapters.LayerStackAdapter.replace_sublayer` so
    the parent fires a single ``SUBLAYERS_CHANGED`` event rather than
    the remove + insert pair a naive implementation would dispatch.

    ``do_impl`` records the old identifier (returned by the adapter)
    on the first execution so ``undo_impl`` can restore it. Redo
    re-reads whatever identifier currently occupies the slot and
    replaces it again with ``new_identifier`` — the redo path does not
    overwrite :attr:`_old_identifier`, so repeated undo/redo cycles
    remain anchored to the original "before" state.

    Used by the Save-As-with-replace flow (LAYERS-PLAN Step 36) and
    by the Property panel's layer-path edit gesture (deferred to v2).
    """

    def __init__(
        self,
        adapter: LayerStackAdapter,
        selection_bus: SelectionBus,
        parent_id: str,
        position: int,
        new_identifier: str,
    ) -> None:
        super().__init__(adapter, selection_bus)
        self._parent_id = parent_id
        self._position = position
        self._new_identifier = new_identifier
        self._old_identifier: Optional[str] = None

    def do_impl(self) -> None:
        replaced = self._adapter.replace_sublayer(
            self._parent_id, self._position, self._new_identifier
        )
        if self._old_identifier is None:
            self._old_identifier = replaced

    def undo_impl(self) -> None:
        if self._old_identifier is None:
            return
        self._adapter.replace_sublayer(
            self._parent_id, self._position, self._old_identifier
        )


class RemovePrimSpecsCommand(AbstractLayerCommand):
    """Remove a batch of prim specs identified by ``(layer_id, path)`` pairs.

    The entries are processed in the order supplied during ``do_impl``;
    each spec is serialised via
    :meth:`~ovwidgets.common.adapters.LayerStackAdapter.export_prim_spec`
    *before* the removal so the opaque USDA token survives the delete.

    ``undo_impl`` replays the snapshots in reverse order so a nested
    spec (e.g. ``/World/Cube/Shader``) lands after its parent
    (``/World/Cube``) has been restored — otherwise the adapter's
    ``import_prim_spec`` would have to synthesise parents, which
    USD's ``Sdf.CopySpec`` does not support when the whole subtree
    was removed. The reverse walk also keeps the operation reversible
    under repeated undo/redo: redo uses the stored snapshots (captured
    on first ``do``) instead of re-exporting, so a peer command that
    re-dirtied a spec between undo and redo cannot leak into the
    snapshot history.
    """

    def __init__(
        self,
        adapter: LayerStackAdapter,
        selection_bus: SelectionBus,
        entries: List[Tuple[str, str]],
    ) -> None:
        super().__init__(adapter, selection_bus)
        # Copy so the caller's list mutations don't leak in.
        self._entries: List[Tuple[str, str]] = list(entries)
        # ``(layer_id, path, usda)`` triples captured on first do; empty
        # on subsequent redos, which means they reuse the same tokens.
        self._snapshots: List[Tuple[str, str, str]] = []
        self._snapshotted: bool = False

    def do_impl(self) -> None:
        if not self._snapshotted:
            for layer_id, path in self._entries:
                usda = self._adapter.export_prim_spec(layer_id, path)
                self._snapshots.append((layer_id, path, usda))
                self._adapter.remove_prim_spec(layer_id, path)
            self._snapshotted = True
        else:
            # Redo: the snapshots already capture the "before" state,
            # so simply re-apply the removals. Re-exporting here would
            # risk a mismatch if a peer command edited the spec
            # between the first do and the redo — the snapshot from
            # the first do is the authoritative "before".
            for layer_id, path, _ in self._snapshots:
                self._adapter.remove_prim_spec(layer_id, path)

    def undo_impl(self) -> None:
        # Reverse order: restore deepest-removed-first so parents
        # exist by the time nested children land. ``import_prim_spec``
        # is defensive enough to materialise one-level-deep parents,
        # but it cannot reconstruct an entire subtree from a leaf.
        for layer_id, path, usda in reversed(self._snapshots):
            self._adapter.import_prim_spec(layer_id, path, usda)

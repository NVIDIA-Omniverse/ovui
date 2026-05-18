# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Merge / Flatten layer commands (LAYERS-PLAN Step 42).

Two destructive, undoable commands that combine the Step-42
:meth:`~ovwidgets.common.adapters.LayerStackAdapter.snapshot_layer` +
:meth:`~ovwidgets.common.adapters.LayerStackAdapter.restore_layer_from_snapshot`
+ :meth:`~ovwidgets.common.adapters.LayerStackAdapter.transfer_layer_content`
primitives into higher-level merge gestures:

- :class:`MergeDownCommand` — collapse a sublayer into the sibling
  below it. Snapshots source + destination before the merge; undo
  replays both snapshots to restore the pre-merge state byte-for-byte.
- :class:`FlattenSublayersCommand` — collapse every direct sublayer of
  a parent layer into the parent itself. Snapshots the parent plus
  each direct sublayer; undo restores the parent and each sublayer at
  its original position.

Both commands are "scary-by-design": callers should route the click
through a confirmation dialog (see
:func:`ovwidgets.common.dialogs.confirm_merge_dialog` /
:func:`ovwidgets.common.dialogs.confirm_flatten_dialog`) before pushing the
command, because a merge is undoable but overwrites the stage's
composition result — a subsequent peer edit between undo and redo can
mask state the user expected to see.

Unlike Kit's native ``MergeLayers`` / ``FlattenLayers`` — which rely
on omni.kit.commands infrastructure we do not have — these commands
take the snapshot/restore round-trip approach documented in
LAYERS-PLAN's Logic F5. The snapshots live on the command instance and
are released when the command drops off the undo stack
(:meth:`UndoManager.clear` or the stack's natural eviction).
"""

from __future__ import annotations

from typing import List, Optional

from ovui_data_adapters.common import LayerSnapshot, LayerStackAdapter

from ovwidgets.common.selection import SelectionBus
from ovwidgets.layers.commands.base import AbstractLayerCommand


class MergeDownCommand(AbstractLayerCommand):
    """Merge the layer at ``(parent_id, source_position)`` into the layer below.

    The "below" layer is the sibling at ``source_position + 1`` in the
    parent's sublayer list. Merge Down is only meaningful when a
    sibling below exists — callers should gate the gesture on the
    :func:`~ovwidgets.layers.context_menu.has_sibling_below` predicate before
    pushing.

    ``do_impl`` snapshots both the source and destination layers (so
    undo can restore both), invokes
    :meth:`~ovwidgets.common.adapters.LayerStackAdapter.transfer_layer_content`
    to copy the source's root prim specs onto the destination, then
    calls :meth:`~ovwidgets.common.adapters.LayerStackAdapter.remove_sublayer`
    to unlink the source from the parent.

    ``undo_impl`` first restores the destination from its pre-merge
    snapshot (overwriting the merged-in specs), then restores the
    source at its original position. The order matters — restoring
    the destination first means a subsequent ``find_layer`` from the
    source restore can still locate the parent's updated sublayer
    list.
    """

    def __init__(
        self,
        adapter: LayerStackAdapter,
        selection_bus: SelectionBus,
        parent_id: str,
        source_position: int,
    ) -> None:
        super().__init__(adapter, selection_bus)
        self._parent_id = parent_id
        self._source_position = source_position
        self._source_snapshot: Optional[LayerSnapshot] = None
        self._destination_snapshot: Optional[LayerSnapshot] = None
        self._source_identifier: Optional[str] = None
        self._destination_identifier: Optional[str] = None

    def do_impl(self) -> None:
        if self._source_snapshot is None:
            parent_handle = self._adapter.find_layer(self._parent_id)
            if parent_handle is None:
                raise KeyError(
                    f"MergeDownCommand: parent {self._parent_id!r} not found"
                )
            children = self._adapter.get_sublayer_identifiers(parent_handle)
            if (
                self._source_position < 0
                or self._source_position + 1 >= len(children)
            ):
                raise IndexError(
                    f"MergeDownCommand: no sibling below position "
                    f"{self._source_position} in parent {self._parent_id!r}"
                )
            self._source_identifier = children[self._source_position]
            self._destination_identifier = children[self._source_position + 1]
            self._source_snapshot = self._adapter.snapshot_layer(
                self._source_identifier
            )
            self._destination_snapshot = self._adapter.snapshot_layer(
                self._destination_identifier
            )

        assert self._source_identifier is not None
        assert self._destination_identifier is not None
        self._adapter.transfer_layer_content(
            self._source_identifier, self._destination_identifier
        )
        self._adapter.remove_sublayer(
            self._parent_id, self._source_position
        )

    def undo_impl(self) -> None:
        if self._source_snapshot is None or self._destination_snapshot is None:
            return
        # Restore destination first so its customLayerData / content
        # reverts to the pre-merge state before the source slots back
        # in. Ordering matters when the two layers share anonymous
        # identifiers or customLayerData keys.
        self._adapter.restore_layer_from_snapshot(
            self._destination_snapshot
        )
        self._adapter.restore_layer_from_snapshot(self._source_snapshot)


class FlattenSublayersCommand(AbstractLayerCommand):
    """Merge every direct sublayer of ``parent_id`` into the parent itself.

    Walks the parent's direct-sublayer list at ``do`` time, snapshots
    the parent and each sublayer, then transfers each sublayer's
    content into the parent in strength order (weakest-first so
    stronger opinions overwrite weaker ones — matches USD's native
    flatten semantics), finally removing the sublayers from the
    parent's :attr:`subLayerPaths`.

    Direct sublayers only: v1 does not recursively flatten grandchild
    layers. A sub-sublayer remains referenced by its direct-sublayer
    parent, so removing the direct sublayer removes the composition
    path for the whole subtree — but the snapshots capture each direct
    sublayer's ``subLayerPaths`` verbatim, so undo re-establishes the
    original tree shape.

    ``undo_impl`` restores the parent from its pre-flatten snapshot
    (wipes the merged-in specs), then re-creates each direct sublayer
    at its original position in **forward** order so peer-subscriber
    events fire in the same sequence as the original tree build.
    """

    def __init__(
        self,
        adapter: LayerStackAdapter,
        selection_bus: SelectionBus,
        parent_id: str,
    ) -> None:
        super().__init__(adapter, selection_bus)
        self._parent_id = parent_id
        self._parent_snapshot: Optional[LayerSnapshot] = None
        self._sublayer_snapshots: List[LayerSnapshot] = []

    def do_impl(self) -> None:
        if self._parent_snapshot is None:
            parent_handle = self._adapter.find_layer(self._parent_id)
            if parent_handle is None:
                raise KeyError(
                    f"FlattenSublayersCommand: parent "
                    f"{self._parent_id!r} not found"
                )
            children = self._adapter.get_sublayer_identifiers(parent_handle)
            if not children:
                # Nothing to flatten — the caller should have gated on
                # :func:`has_sublayers`, but guard here so a stale
                # predicate (post-peer-remove) doesn't land a no-op
                # command with corrupt state.
                return
            self._parent_snapshot = self._adapter.snapshot_layer(
                self._parent_id
            )
            # Snapshot children in their document order. ``restore`` on
            # undo walks the list forward so each sublayer ends up at
            # its original position.
            for child_id in children:
                self._sublayer_snapshots.append(
                    self._adapter.snapshot_layer(child_id)
                )

        # Transfer content weakest-first: the LAST sublayer (strongest
        # in USD composition) lands in the parent last, so its
        # opinions win on overlapping paths. This matches the native
        # Kit ``FlattenLayers`` semantics.
        for snap in reversed(self._sublayer_snapshots):
            self._adapter.transfer_layer_content(
                snap.identifier, self._parent_id
            )
        # Remove sublayers back-to-front so earlier indices stay valid
        # through the iteration.
        for idx in range(len(self._sublayer_snapshots) - 1, -1, -1):
            self._adapter.remove_sublayer(self._parent_id, idx)

    def undo_impl(self) -> None:
        if self._parent_snapshot is None:
            return
        # Restore the parent's pre-flatten state first so the merged-
        # in specs revert. Then re-materialise each direct sublayer in
        # document order — the snapshots carry the original
        # ``position_in_parent`` so each insert lands in the right slot
        # even if the earlier re-inserts shifted the list.
        self._adapter.restore_layer_from_snapshot(self._parent_snapshot)
        for snap in self._sublayer_snapshots:
            self._adapter.restore_layer_from_snapshot(snap)

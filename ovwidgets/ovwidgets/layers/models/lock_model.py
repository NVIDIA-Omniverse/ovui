# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Lock-column value model for the Layers ``TreeView`` (LAYERS-PLAN Step 21).

:class:`LockValueModel` is the :class:`omni.ui.AbstractValueModel`
that drives column 6 (the padlock icon) of the Layers tree.

Read surface:

- :meth:`get_value_as_bool` returns ``True`` iff the layer is currently
  locked. The delegate reads this each paint to choose the closed-
  padlock vs open-padlock primitive and the ``name=`` style override.

Write surface:

- :meth:`set_value` pushes a :class:`SetLayerLockCommand` through the
  owning :class:`~ovwidgets.app.application.Application`'s
  :class:`~ovwidgets.common.undo.UndoManager` so the lock toggle joins the undo
  stack (LAYERS-PLAN Step 29). The adapter's ``set_lock`` fires
  ``LOCK_STATE_CHANGED`` synchronously when the bit actually flips
  (no event on a no-op). When the owning :class:`LayerModel` has no
  attached :class:`Application` (e.g. unit-test construction with
  ``LayerModel(adapter)``), the command path is bypassed and the
  adapter is called directly — the undoable path requires an
  ``UndoManager`` and a :class:`~ovwidgets.common.selection.SelectionBus`, both
  of which live on :class:`Application`.

The delegate synthesises a *toggle* click by reading
:meth:`get_value_as_bool` and passing its negation into
:meth:`set_value`, so the argument **is** the new desired state — same
contract as :class:`~ovwidgets.layers.models.mute_model.LocalMuteValueModel`.
Unlike :class:`~ovwidgets.layers.models.save_model.SaveValueModel` (whose
boolean payload is ignored because "save" is not a toggle), the lock
model honours the passed-in target state.

Like the other per-column models the instance is constructed lazily on
first access and cached on :attr:`LayerItem._lock_model` so repeated
reads share one object (LAYERS-PLAN Logic F4). The cache is reset
alongside the rest of the subtree during detach / re-target (Step 15)
via :meth:`LayerModel._destroy_subtree`.

When the adapter emits ``LOCK_STATE_CHANGED`` the owning
:class:`LayerModel` calls :meth:`_value_changed` on the cached lock
model so ovui repaints the cell without waiting for a full-tree
``_item_changed(None)`` pass. The recursive lock variant from Step 41
will still land on this model — it just propagates through additional
identifiers in one event — so the refresh plumbing stays stable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import omni.ui as ui

from ovwidgets.layers.commands import SetLayerLockCommand

if TYPE_CHECKING:  # pragma: no cover — type-hint guard
    from ovwidgets.layers.layer_item import LayerItem
    from ovwidgets.layers.layer_model import LayerModel


class LockValueModel(ui.AbstractValueModel):
    """Column-6 value model: lock boolean + click-toggle write surface."""

    def __init__(
        self,
        layer_model: "LayerModel",
        layer_item: "LayerItem",
    ) -> None:
        super().__init__()
        self._model = layer_model
        self._item = layer_item

    # ── Read surface ─────────────────────────────────────────────────

    def get_value_as_bool(self) -> bool:
        """``True`` iff the layer is currently locked.

        Reads through :attr:`LayerItem.is_locked`, which auto-refreshes
        the item's flag cache on access. Step 41's recursive-lock
        gesture writes the same bit on every descendant — each row's
        own model still reports the per-layer state.
        """
        return self._item.is_locked

    # ── Write surface ────────────────────────────────────────────────

    def set_value(self, locked: bool) -> None:
        """Request the new lock state from the adapter.

        ``locked`` is the **target** state, not a toggle — the delegate
        synthesises the toggle by calling ``set_value(not
        get_value_as_bool())``. The toggle is routed through a
        :class:`SetLayerLockCommand` so ``Ctrl+Z`` reverses it.

        No-op on a detached adapter (a late click after
        :meth:`LayerModel.set_adapter` cleared the reference). When
        the owning :class:`LayerModel` has no attached
        :class:`Application` (unit-test construction) the command path
        is bypassed and the adapter is written to directly so the
        model stays testable without faking an ``UndoManager``.
        """
        adapter = self._model.adapter
        if adapter is None:
            return
        target = bool(locked)
        # Skip no-op clicks before they allocate a command — otherwise
        # the adapter's own no-op guard silently makes do() a no-op
        # while undo() still flips the bit, creating a ghost undo
        # entry that reverses a change that never happened.
        if self._item.is_locked == target:
            return
        services = self._model.services
        if services is None:
            adapter.set_lock(self._item.identifier, target)
            return
        cmd = SetLayerLockCommand(
            adapter,
            services.selection_bus,
            self._item.identifier,
            target,
        )
        services.undo_manager.push(cmd)

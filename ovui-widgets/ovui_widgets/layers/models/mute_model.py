# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Local-muteness value model for the Layers ``TreeView`` (LAYERS-PLAN Step 20).

:class:`LocalMuteValueModel` is the :class:`omni.ui.AbstractValueModel`
that drives column 3 (the local-mute eye icon) of the Layers tree.

Read surface:

- :meth:`get_value_as_bool` returns ``True`` iff the layer is currently
  locally muted. The delegate reads this each paint to choose the open-
  eye vs closed-eye primitive and the ``name=`` style override.

Write surface:

- :meth:`set_value` pushes a :class:`SetLayerMutenessCommand` through
  the owning :class:`~ovui_widgets.app.application.Application`'s
  :class:`~ovui_widgets.common.undo.UndoManager` so the mute toggle joins the undo
  stack (LAYERS-PLAN Step 29). The adapter's ``set_mute`` fires
  ``MUTE_STATE_CHANGED`` synchronously when the bit actually flips
  (no event on a no-op). When the owning :class:`LayerModel` has no
  attached :class:`Application` (e.g. unit-test construction with
  ``LayerModel(adapter)``), the command path is bypassed and the
  adapter is called directly — the undoable path requires an
  ``UndoManager`` and a :class:`~ovui_widgets.common.selection.SelectionBus`, both
  of which live on :class:`Application`.

The delegate synthesises a *toggle* click by reading
:meth:`get_value_as_bool` and passing its negation into
:meth:`set_value`, so the argument **is** the new desired state (unlike
:class:`~ovui_widgets.layers.models.save_model.SaveValueModel`, whose boolean
payload is ignored — clicking "save" is not a toggle).

Like the other per-column models the instance is constructed lazily on
first access and cached on :attr:`LayerItem._local_mute_model` so
repeated reads share one object (LAYERS-PLAN Logic F4). The cache is
reset alongside the rest of the subtree during detach / re-target
(Step 15) via :meth:`LayerModel._destroy_subtree`.

When the adapter emits ``MUTE_STATE_CHANGED`` the owning
:class:`LayerModel` calls :meth:`_value_changed` on the cached mute
model so ovui repaints the cell without waiting for a full-tree
``_item_changed(None)`` pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import omni.ui as ui

from ovui_widgets.layers.commands import SetLayerMutenessCommand

if TYPE_CHECKING:  # pragma: no cover — type-hint guard
    from ovui_widgets.layers.layer_item import LayerItem
    from ovui_widgets.layers.layer_model import LayerModel


class LocalMuteValueModel(ui.AbstractValueModel):
    """Column-3 value model: local-mute boolean + click-toggle write surface."""

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
        """``True`` iff the layer is currently locally muted.

        Reads through :attr:`LayerItem.is_muted`, which auto-refreshes
        the item's flag cache on access. The global-mute scope
        (Step 22 / v1 Known Limitation) is not considered here — this
        column tracks the local bit only.
        """
        return self._item.is_muted

    # ── Write surface ────────────────────────────────────────────────

    def set_value(self, muted: bool) -> None:
        """Request the new mute state from the adapter.

        ``muted`` is the **target** state, not a toggle — the delegate
        synthesises the toggle by calling ``set_value(not
        get_value_as_bool())``. The toggle is routed through a
        :class:`SetLayerMutenessCommand` so ``Ctrl+Z`` reverses it.

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
        target = bool(muted)
        # Skip no-op clicks before they allocate a command — otherwise
        # the adapter's own no-op guard silently makes do() a no-op
        # while undo() still flips the bit, creating a ghost undo
        # entry that reverses a change that never happened.
        if self._item.is_muted == target:
            return
        services = self._model.services
        if services is None:
            adapter.set_mute(self._item.identifier, target)
            return
        cmd = SetLayerMutenessCommand(
            adapter,
            services.selection_bus,
            self._item.identifier,
            target,
        )
        services.undo_manager.push(cmd)

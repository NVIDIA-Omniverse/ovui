# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Save-column value model for the Layers ``TreeView`` (LAYERS-PLAN Step 19).

:class:`SaveValueModel` is the :class:`omni.ui.AbstractValueModel` that
drives column 2 (the dirty / save indicator) of the Layers tree. It
reports the layer's saveable-and-dirty state as a boolean and, on
``set_value``, asks the adapter to persist the layer.

Read surface:

- :meth:`get_value_as_bool` returns ``True`` iff the layer is dirty
  and the save flow can do *something* with it. Concrete layers
  qualify when they are writable on disk; anonymous dirty layers
  also qualify because Step 36 routes their click into a save-as
  file picker (the picker asks the user for a path and then the
  save runs). Missing layers cannot be saved — their click does not
  light the icon.

Write surface:

- :meth:`set_value` delegates to
  :meth:`~ovui_widgets.layers.layer_model.LayerModel._request_save`, which
  Step 34 uses to push a :class:`SaveLayerCommand` through the owning
  :class:`~ovui_widgets.app.application.Application`'s
  :class:`~ovui_widgets.common.undo.UndoManager`. Step 36 extends the anonymous
  branch of ``_request_save``: instead of short-circuiting, the
  model opens a save-as file picker and (on Save) pushes a
  :class:`SaveLayerAsCommand` so the write + parent-reference swap
  lands as one undoable unit. The command path keeps save errors on
  a single reporting surface and clears the redo stack even though
  the save itself never lands on the undo stack
  (``non_undoable = True``). When the model has no attached
  :class:`Application` (unit-test construction) the command path is
  bypassed and the adapter is called directly so the value model
  stays testable without faking an ``UndoManager``. No-op when the
  layer cannot be saved (the delegate also prevents the click from
  landing, but the model checks defensively so a programmatic call
  is safe).

The model is **stateless read-through**: every
:meth:`get_value_as_bool` call re-queries the item's cached flags
(which themselves go through the adapter via
:meth:`~ovui_widgets.layers.layer_item.LayerItem.refresh_flags`). When the
adapter emits ``DIRTY_STATE_CHANGED`` the owning :class:`LayerModel`
calls :meth:`_value_changed` on the save model so ovui repaints the
cell.

Lazy per-item caching (LAYERS-PLAN Logic F4): instances are constructed
on first access by :meth:`LayerModel.get_item_value_model` and cached
on :attr:`LayerItem._save_model` so repeated reads share one object.
The cache is reset alongside the rest of the subtree during detach /
re-target (Step 15) via :meth:`LayerModel._destroy_subtree`, which
drops references to the owning :class:`LayerItem`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import omni.ui as ui

if TYPE_CHECKING:  # pragma: no cover — type-hint guard
    from ovui_widgets.layers.layer_item import LayerItem
    from ovui_widgets.layers.layer_model import LayerModel


class SaveValueModel(ui.AbstractValueModel):
    """Column-2 value model: dirty-and-saveable boolean + click-to-save."""

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
        """``True`` iff the layer is dirty and the save flow can act on it.

        Missing layers clamp to ``False`` — the adapter cannot
        resolve them, so neither the direct save nor the save-as
        path works. Anonymous layers **do** light the icon when
        dirty: Step 36 routes their click into the save-as file
        picker, so the icon correctly advertises an actionable
        gesture (the picker asks the user for a destination path,
        then the write + parent-reference swap runs as a
        :class:`SaveLayerAsCommand`).
        """
        item = self._item
        if item.is_missing:
            return False
        return item.is_dirty

    # ── Write surface ────────────────────────────────────────────────

    def set_value(self, _value: bool) -> None:
        """Trigger the save flow for the backing layer.

        The argument is ignored — clicking the save icon is a "do it"
        gesture, not a toggle. Step 34 routes the click through
        :meth:`LayerModel._request_save` so the save runs as a
        :class:`SaveLayerCommand` on the :class:`UndoManager` (errors
        land on the shared :class:`ErrorReporter`, redo stack clears
        even though the save itself is ``non_undoable``).

        No-op on a detached adapter (a late click after
        :meth:`LayerModel.set_adapter` cleared the reference). Also a
        no-op when :meth:`get_value_as_bool` would return ``False`` —
        the delegate does not bind the click handler in that case, but
        the model guards defensively so programmatic calls stay safe.
        """
        if self._model.adapter is None:
            return
        if not self.get_value_as_bool():
            return
        self._model._request_save(self._item)

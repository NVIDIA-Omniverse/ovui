# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Aggregate Save-All value model (LAYERS-PLAN Step 35).

:class:`SaveAllValueModel` drives the Save-All toolbar button in the
Layers window header. It reports *any layer in the stack is dirty and
saveable* as a boolean and, on :meth:`set_value`, triggers a grouped
save of every such layer.

Read surface:

- :meth:`get_value_as_bool` walks the adapter's
  :meth:`~ovwidgets.common.adapters.LayerStackAdapter.get_layer_stack_identifiers`
  list (session included; anonymous layers excluded because they have
  no file path — Step 36 routes their save through a save-as dialog)
  and returns ``True`` as soon as one is dirty. The walk is O(n) in
  the size of the stack; for UI-scale stacks (hundreds of layers at
  most) the per-frame cost is negligible, and the model only re-reads
  when the window renders the button or :meth:`_value_changed` fires.

- :meth:`get_dirty_identifiers` returns the same filtered list
  (dirty + non-anonymous) in discovery order so the click handler
  pushes one :class:`~ovwidgets.layers.commands.SaveLayerCommand` per
  layer. Exposed as a helper so tests and the window share the exact
  filter rules the badge uses.

Write surface:

- :meth:`set_value` delegates to
  :meth:`~ovwidgets.layers.layer_model.LayerModel._request_save_all`. The
  argument is ignored (same "do it" contract as
  :class:`~ovwidgets.layers.models.save_model.SaveValueModel`). A no-op
  when the aggregate is already ``False`` so a programmatic click on
  a clean stack cannot fire an empty undo group.

Badge invalidation: the cached :class:`SaveAllValueModel` is notified
by :meth:`~ovwidgets.layers.layer_model.LayerModel._flush_events` whenever
any layer's dirty bit flips or the sublayer structure changes. A
single :meth:`_value_changed` call is enough — the ``ui.TreeView`` /
toolbar delegate re-reads :meth:`get_value_as_bool` on the next paint.

Unlike the per-row :class:`SaveValueModel` there is no per-item
caching surface: the model is a singleton per :class:`LayerModel`,
constructed once by the window when it builds the toolbar strip.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

import omni.ui as ui

if TYPE_CHECKING:  # pragma: no cover — type-hint guard
    from ovwidgets.layers.layer_model import LayerModel


class SaveAllValueModel(ui.AbstractValueModel):
    """Aggregate dirty-and-saveable boolean + click-to-save-all surface."""

    def __init__(self, layer_model: "LayerModel") -> None:
        super().__init__()
        self._model = layer_model

    # ── Read surface ─────────────────────────────────────────────────

    def get_value_as_bool(self) -> bool:
        """``True`` iff any concrete layer in the stack is dirty.

        "Concrete" means non-anonymous: anonymous layers have no file
        path so Save-All cannot persist them without first routing
        through Step-36's save-as dialog. The session layer is
        included in the scan — a session layer backed by a file is a
        legitimate save target even though it is excluded from the
        Save-All badge on pure Kit-style anonymous sessions.

        Returns ``False`` on a detached adapter so a late repaint
        after :meth:`LayerModel.set_adapter` cleared the reference
        does not light the badge.
        """
        return bool(self.get_dirty_identifiers())

    def get_dirty_identifiers(self) -> List[str]:
        """The layers Save-All would actually save, in discovery order.

        One source of truth for the click handler and the badge so a
        future rule change (e.g. "skip read-only-on-disk layers") lands
        in one place. Returns an empty list when the adapter is
        detached — the click handler short-circuits the same way
        so nothing downstream tries to push an empty group.
        """
        adapter = self._model.adapter
        if adapter is None:
            return []
        dirty: List[str] = []
        for identifier in adapter.get_layer_stack_identifiers(
            include_session=True,
            include_anonymous=False,
        ):
            handle = adapter.find_layer(identifier)
            if handle is None:
                continue
            if adapter.is_dirty(handle):
                dirty.append(identifier)
        return dirty

    # ── Write surface ────────────────────────────────────────────────

    def set_value(self, _value: bool) -> None:
        """Kick off the Save-All flow on the owning :class:`LayerModel`.

        Argument ignored — the toolbar button has no "save vs not save"
        state to pass through; clicking it is unconditional intent to
        persist every dirty layer. Routes through
        :meth:`LayerModel._request_save_all` so the command pipeline
        (grouping, error reporter, headless fallback) lives in one
        place and the value model stays a thin delivery surface.
        """
        if not self.get_value_as_bool():
            # Nothing to save — do not start an empty undo group.
            return
        self._model._request_save_all()

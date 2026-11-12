# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""VisibilityValueModel — eye-checkbox model with inverted, selection-aware semantics.

VisibilityValueModel supplies the StageWidget eye-checkbox behavior.

``get_value_as_bool()`` returns ``True`` when the item itself is authored
**invisible** ("checked" ⇒ the eye-closed icon draws). An item that is
hidden only through a hidden ancestor reads ``False``: its own state is not
hidden. ``get_visibility_state()`` returns the three states, so the eye can
show that inherited case apart. ``set_value(hidden)`` authors visibility on
the item only (``StageAdapter.set_own_visibility``): it never shows a hidden
ancestor or hides that ancestor's other children. If the owning item is
part of a multi-selection, *every* selected item is toggled in the same undo
group (DAW-style group operation). Instance proxies are gated out via
``is_enabled``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import omni.ui as ui
from ovui_data_adapters.common import VisibilityState

if TYPE_CHECKING:
    from ovui_data_adapters.common import StageAdapter

    from ovui_widgets.stage.hierarchy_model import HierarchyItem, HierarchyModel


class VisibilityValueModel(ui.AbstractValueModel):
    """Inverted, selection-aware value model for the Visibility column.

    Parameters
    ----------
    item
        The :class:`HierarchyItem` this model drives.
    adapter
        The :class:`StageAdapter` the model reads and writes through.
    model
        The owning :class:`HierarchyModel` — used to read the current
        selection so a group toggle can target every selected row.
    """

    def __init__(
        self,
        item: "HierarchyItem",
        adapter: "StageAdapter",
        model: "HierarchyModel",
    ) -> None:
        super().__init__()
        self._item = item
        self._adapter = adapter
        self._model = model

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_visibility_state(self) -> VisibilityState:
        """Return the item's visibility: visible, invisible, or inherited invisible."""
        return self._adapter.compute_visibility(self._item.adapter_item)

    def get_value_as_bool(self) -> bool:
        """Return True when the item itself is authored invisible (eye closed)."""
        return self.get_visibility_state() is VisibilityState.INVISIBLE

    def get_value_as_int(self) -> int:
        return 1 if self.get_value_as_bool() else 0

    def get_value_as_float(self) -> float:
        return float(self.get_value_as_int())

    def get_value_as_string(self) -> str:
        return "true" if self.get_value_as_bool() else "false"

    # ── Write ─────────────────────────────────────────────────────────────────

    def set_value(self, value) -> None:
        """Set the hidden state; group-toggles every selected item if applicable.

        ``value`` is the inverted convention: True hides, False shows. Each
        target is authored alone, so showing an item under a hidden ancestor
        leaves it hidden through that ancestor. A single undo group wraps the
        whole batch so one click produces one undo entry regardless of
        selection size.
        """
        hidden = bool(value)
        visible = not hidden
        selected = self._model._selected_items
        if self._item in selected and len(selected) > 1:
            candidates = [s.adapter_item for s in selected]
        else:
            candidates = [self._item.adapter_item]
        targets = [
            target for target in candidates
            if self._adapter.can_edit_visibility(target)
        ]
        if not targets:
            return

        # Transactional acquisition: if begin raises, no scope exists and
        # there is nothing to abort — the error propagates untouched.
        self._adapter.begin_undo_group("Toggle Visibility")
        try:
            for target in targets:
                self._adapter.set_own_visibility(target, visible)
        except BaseException as member_error:
            # Structured scope ownership: a failed member aborts the whole
            # group so completed members are compensated instead of leaving
            # a partial, undoable scope behind. The member error stays
            # primary: abort/cleanup failures attach to it as notes and
            # never displace it.
            abort = getattr(self._adapter, "abort_undo_group", None)
            try:
                if callable(abort):
                    abort()
                else:
                    self._adapter.end_undo_group()
            except BaseException as cleanup_error:
                add_note = getattr(member_error, "add_note", None)
                if callable(add_note):
                    add_note(
                        "scope cleanup also failed: "
                        f"{type(cleanup_error).__name__}: {cleanup_error}"
                    )
            raise
        else:
            self._adapter.end_undo_group()

    # ── Enablement ────────────────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        """False for items the adapter cannot edit (e.g. instance proxies).

        Matches the StageWidget visibility callback shape.
        """
        return self._adapter.can_edit_visibility(self._item.adapter_item)

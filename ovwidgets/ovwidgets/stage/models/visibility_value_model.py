# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""VisibilityValueModel — eye-checkbox model with inverted, selection-aware semantics.

VisibilityValueModel supplies the StageWidget eye-checkbox behavior.

``get_value_as_bool()`` returns ``True`` when the item is effectively
**invisible** — the convention Kit's visibility checkbox uses ("checked" ⇒
the eye-closed icon draws, so the prim is hidden). ``set_value(hidden)``
toggles visibility; if the owning item is part of a multi-selection,
*every* selected item is toggled in the same undo group (DAW-style group
operation). Instance proxies are gated out via ``is_enabled``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import omni.ui as ui
from ovui_data_adapters.common import VisibilityState

if TYPE_CHECKING:
    from ovui_data_adapters.common import StageAdapter

    from ovwidgets.stage.hierarchy_model import HierarchyItem, HierarchyModel


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

    def get_value_as_bool(self) -> bool:
        """Return True when the item is effectively invisible (eye closed)."""
        state = self._adapter.compute_visibility(self._item.adapter_item)
        return state != VisibilityState.VISIBLE

    def get_value_as_int(self) -> int:
        return 1 if self.get_value_as_bool() else 0

    def get_value_as_float(self) -> float:
        return float(self.get_value_as_int())

    def get_value_as_string(self) -> str:
        return "true" if self.get_value_as_bool() else "false"

    # ── Write ─────────────────────────────────────────────────────────────────

    def set_value(self, value) -> None:
        """Set the hidden state; group-toggles every selected item if applicable.

        ``value`` is the inverted convention: True hides, False shows. A
        single undo group wraps the whole batch so one click produces one
        undo entry regardless of selection size.
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

        self._adapter.begin_undo_group("Toggle Visibility")
        try:
            for target in targets:
                self._adapter.set_visibility(target, visible)
        finally:
            self._adapter.end_undo_group()

    # ── Enablement ────────────────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        """False for items the adapter cannot edit (e.g. instance proxies).

        Matches the StageWidget visibility callback shape.
        """
        return self._adapter.can_edit_visibility(self._item.adapter_item)

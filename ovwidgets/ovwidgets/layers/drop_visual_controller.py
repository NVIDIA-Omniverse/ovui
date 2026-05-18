# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Drop-visual controller for the Layers tree (LAYERS-PLAN Step 44).

:class:`DropVisualController` owns the transient drag-over state the
:class:`~ovwidgets.layers.layer_delegate.LayerDelegate` consults when it paints
the row background: which :class:`~ovwidgets.layers.layer_item.LayerItem` the
cursor is over, the ovui-provided ``drop_location`` (``-1`` means "drop
onto this row"; ``>= 0`` means "insert at this index in the target's
parent sublayer list"), whether the move validates, and — when it
doesn't — the human-readable rejection reason for the Step 44 toast.

The controller is **state only** (mirrors
:class:`ovwidgets.stage.drop_visual_controller.DropVisualController`). The
model is responsible for asking the controller to refresh and for
calling :meth:`ui.AbstractItemModel._item_changed` on the items whose
indicator state just changed so ovui triggers a repaint. This keeps the
delegate a pure function of ``(model, controller)`` — one model → one
delegate → one controller — and avoids a second repaint pipeline
concurrent with the model's own notification tree.

The delegate reads :meth:`indicator_for` for the current row and paints
one of four named overlays (see the module selectors in
:mod:`ovwidgets.layers.style`):

- ``"drop_target"`` — valid ``drop_location == -1`` hover; the target
  becomes the new parent. Delegate paints a green outline across the
  full row.
- ``"drop_rejected"`` — hover fails :meth:`LayerModel._can_move_layer`.
  Delegate paints a red outline across the row so the user gets
  immediate feedback instead of the silent rejection Step 43 left
  behind (LAYERS-PLAN UX bug B3).
- ``"drop_above"`` / ``"drop_below"`` — valid between-drop (the target
  row's parent list receives the move at ``drop_location``). Delegate
  paints a thin horizontal line at the top or bottom of the target
  row. The above / below choice falls out of comparing
  ``drop_location`` to the target's own position inside its parent
  sublayer list: ``drop_location <= target_pos`` → line above (source
  lands at or before target); ``drop_location > target_pos`` → line
  below (source lands after target).

The indicator is cleared when the drop releases (accept *or* reject)
and whenever a new hover lands on a different target so stale
highlights never linger between adjacent-row drags. ovui does not emit
a "drag cancelled without release" signal, so a cancelled drag may
leave the last hover highlight painted until the next
``_item_changed`` pass — an acceptable cost that matches the Stage
window's Step 71 behaviour.
"""

from __future__ import annotations

from typing import Any, Optional

from ovwidgets.layers.layer_item import LayerItem

# Indicator name tokens — the delegate pipes these through
# ``Layers.DropIndicator::<name>`` style selectors so a theme swap
# touches one style block rather than every delegate site. Kept as
# module-level constants so tests and the delegate both reference the
# same string without having to hard-code it.
INDICATOR_NONE = ""
INDICATOR_DROP_TARGET = "drop_target"
INDICATOR_DROP_ABOVE = "drop_above"
INDICATOR_DROP_BELOW = "drop_below"
INDICATOR_DROP_REJECTED = "drop_rejected"


class DropVisualController:
    """Tracks the active drag-over target for delegate rendering.

    Exposes read-only accessors for tests and the delegate; mutations go
    through :meth:`show_valid`, :meth:`show_rejected`, and :meth:`clear`.
    Every mutator returns the previous target so the model can fire
    :meth:`ui.AbstractItemModel._item_changed` on the stale row before
    firing it on the new one — one repaint per row that visibly
    changed, no extra paints on rows whose indicator was already empty.
    """

    def __init__(self) -> None:
        self._target: Optional[LayerItem] = None
        self._drop_location: int = -1
        self._is_valid: bool = False
        self._rejection_reason: Optional[str] = None

    # ── Mutators ────────────────────────────────────────────────────

    def show_valid(
        self, target: LayerItem, drop_location: int
    ) -> Optional[LayerItem]:
        """Mark ``target`` as a valid drop at ``drop_location``.

        Returns the previously held target (or ``None``) so the caller
        can request a repaint on the stale row.
        """
        previous = self._target
        self._target = target
        self._drop_location = drop_location
        self._is_valid = True
        self._rejection_reason = None
        return previous

    def show_rejected(
        self,
        target: LayerItem,
        drop_location: int,
        reason: str,
    ) -> Optional[LayerItem]:
        """Mark ``target`` as an invalid drop with ``reason``.

        ``reason`` is surfaced verbatim by the delegate as a row tooltip
        and by the model as the :class:`~ovwidgets.common.error_reporter.ErrorReporter`
        warning posted on drop-release over an invalid target.
        """
        previous = self._target
        self._target = target
        self._drop_location = drop_location
        self._is_valid = False
        self._rejection_reason = reason
        return previous

    def clear(self) -> Optional[LayerItem]:
        """Drop any active indicator state.

        Returns the previously held target (or ``None``) — the model
        repaints that row to remove the stale indicator.
        """
        previous = self._target
        self._target = None
        self._drop_location = -1
        self._is_valid = False
        self._rejection_reason = None
        return previous

    # ── Accessors ──────────────────────────────────────────────────

    @property
    def current_target(self) -> Optional[LayerItem]:
        return self._target

    @property
    def current_drop_location(self) -> int:
        return self._drop_location

    @property
    def is_valid(self) -> bool:
        return self._is_valid

    @property
    def rejection_reason(self) -> Optional[str]:
        return self._rejection_reason

    # ── Render helpers ─────────────────────────────────────────────

    def indicator_for(self, item: Any) -> str:
        """Return the indicator name the delegate should paint for ``item``.

        - :data:`INDICATOR_NONE` when ``item`` is not the current target.
        - :data:`INDICATOR_DROP_TARGET` for a valid drop-onto hover.
        - :data:`INDICATOR_DROP_REJECTED` for any invalid hover (onto or
          between) — a rejected between-drop reads as a row-level reject
          because the user hasn't committed to a direction yet, and a
          full-row red outline beats a half-length line for visibility.
        - :data:`INDICATOR_DROP_ABOVE` / :data:`INDICATOR_DROP_BELOW`
          for a valid between-drop; the side is chosen from
          ``drop_location`` versus the target's position in its parent.

        Defensive against a target whose parent was mutated between the
        hover and the paint (a peer command moves the target, or the
        tree rebuilt while the cursor was held): falls back to
        :data:`INDICATOR_DROP_ABOVE` because a top-line reads as a
        safer default than a misplaced bottom-line, and the user's
        next hover refreshes state.
        """
        if self._target is None or item is not self._target:
            return INDICATOR_NONE
        if not self._is_valid:
            return INDICATOR_DROP_REJECTED
        if self._drop_location == -1:
            return INDICATOR_DROP_TARGET
        if not isinstance(item, LayerItem) or item.parent is None:
            return INDICATOR_DROP_ABOVE
        try:
            target_pos = item.parent._sublayers.index(item)
        except ValueError:
            return INDICATOR_DROP_ABOVE
        if self._drop_location <= target_pos:
            return INDICATOR_DROP_ABOVE
        return INDICATOR_DROP_BELOW

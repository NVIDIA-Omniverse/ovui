# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""DropIndicator — visual feedback coordinator for content-browser drop targets.

See the content browser implementation step 41 and the content browser behavior (drag-drop
visual feedback). Mirrors the :class:`ovwidgets.stage.widget.DropVisualController`
pattern but paints three distinct visuals the Content Browser needs:

* **Row highlight** — 30% opacity tint on the tree row currently under
  the drag cursor. Applied via :meth:`show_row_highlight` with a direct
  widget reference; cleared by :meth:`clear` or a subsequent
  :meth:`show_row_highlight` on a different row. The tint uses
  :data:`omni.ui.color.treeview_drop_indicator` so the feedback reads
  the same across light / dark themes (theme-aware content style rules).

* **Card highlight** — ``Content.Card::drop_hover`` style variant
  applied to the card's hit rect via :meth:`show_card_highlight`. Only
  the variant name flips; no widget swap — the card's hit rect is the
  same :class:`ui.Rectangle` before / during / after hover.

* **Between-items line** — the y-coordinate of a 2-px horizontal line
  the delegate can paint between two rows. Stored as state by
  :meth:`show_between_line`; the hosting widget reads
  :attr:`between_line_y` to decide whether / where to paint the line.

:meth:`clear` reverts every active highlight. The controller is
defensive by design: post-destroy widgets (card rect, row widget) are
tolerated via attribute guards so a race between a drop-event clear
and an ovui widget teardown does not raise.

Lifecycle mirrors the rest of the content-browser widget package: the
controller is plain Python with no widget-owned state — it is safe to
construct outside a build context, carry across builds, and drop
without an explicit destroy step.
"""

from __future__ import annotations

from typing import Any, Optional

from omni.ui import color as cl

# Style-variant name flipped onto a :class:`FileCard._rect` during a
# drop-hover. Paired with :data:`ovwidgets.content.style.CONTENT_STYLES`
# entry ``Content.Card::drop_hover`` — updating the variant name must
# match both sites. Kept as a module constant so tests can import and
# assert against the string rather than duplicating the literal.
_CARD_DROP_HOVER_VARIANT = "drop_hover"


class DropIndicator:
    """Tracks and paints drop-target visual feedback across the content browser.

    Three channels, independent of each other:

    * :meth:`show_row_highlight` — tints a tree row widget.
    * :meth:`show_card_highlight` — flips a grid card's style variant.
    * :meth:`show_between_line` — records a y-coordinate for a
      between-rows line (the delegate queries :attr:`between_line_y` on
      its next render to paint the line).

    Only one target per channel is active at a time. Calling a
    ``show_*`` method with a new target silently reverts the previous
    one in the same channel so a drag sweeping across the tree leaves
    at most one row tinted at any moment.

    :meth:`clear` reverts all three channels in one call — used by the
    widget-level drop dispatcher at drop-end / drop-outside to remove
    every trace of the in-flight drag.
    """

    def __init__(self) -> None:
        # Row-highlight channel. ``_active_row`` is the widget ref we
        # mutated on :meth:`show_row_highlight`; ``_active_row_style`` is
        # the style dict it had before we overwrote it so :meth:`clear`
        # can restore the original.
        self._active_row: Optional[Any] = None
        self._active_row_style: Any = None

        # Card-highlight channel. ``_active_card`` is the
        # :class:`FileCard` we mutated; ``_active_card_prev_name`` is
        # the ``name`` the card's hit rect had before we flipped it to
        # ``drop_hover`` so the reverting path restores it verbatim.
        self._active_card: Optional[Any] = None
        self._active_card_prev_name: str = ""

        # Between-line channel. ``None`` means "no line active"; a
        # float means "paint a 2-px line at this y". The widget layer
        # reads the coordinate off :attr:`between_line_y` — the
        # indicator intentionally does not own the line widget itself
        # so the host can decide the paint context (overlay frame,
        # inside a ZStack, etc.) without the indicator forcing a
        # particular parent.
        self._between_line_y: Optional[float] = None

    # ── Row highlight ────────────────────────────────────────────────────────

    def show_row_highlight(self, row_widget: Any) -> None:
        """Tint ``row_widget``'s background with the drop-indicator colour.

        The tint uses :data:`cl.treeview_drop_indicator` — the same
        token :mod:`ovwidgets.app.style` registers for the Stage Browser's
        drop feedback (theme-aware content style rules) so both browsers paint the same
        shade on drag-over.

        Passing ``None`` is a silent no-op — the caller may not have a
        widget ref to hand in during an early-frame dispatch and we
        would rather absorb the call than raise.

        Re-highlighting the currently-active row is idempotent. A
        highlight on a different row first reverts the previous row's
        style so at most one row is tinted at any moment.
        """
        if row_widget is None:
            return
        if row_widget is self._active_row:
            return
        if self._active_row is not None:
            self._revert_row()
        self._active_row = row_widget
        self._active_row_style = self._read_row_style(row_widget)
        self._apply_row_style(row_widget)

    def _read_row_style(self, row_widget: Any) -> Any:
        """Snapshot ``row_widget``'s current ``style`` attribute for later restore.

        Widgets that have never had a style set expose ``style`` as an
        empty mapping; reading the attribute is safe either way.
        Wrapped in an ``AttributeError`` guard so a widget subclass
        without a ``style`` attribute still passes through the
        highlight path cleanly.
        """
        try:
            return getattr(row_widget, "style", None)
        except Exception:  # noqa: BLE001
            return None

    def _apply_row_style(self, row_widget: Any) -> None:
        """Paint the drop-indicator tint onto ``row_widget``.

        Uses the widget's ``set_style`` method when available —
        :class:`ui.HStack` / :class:`ui.ZStack` accept inline style
        overrides through that surface. A missing ``set_style`` method
        falls through silently; the highlight becomes a no-op for that
        widget rather than crashing the drop dispatch.
        """
        setter = getattr(row_widget, "set_style", None)
        if setter is None:
            return
        try:
            setter({"background_color": cl.treeview_drop_indicator})
        except Exception:  # noqa: BLE001
            # The ovui build can be picky about which property keys a
            # given widget accepts; absorbing the failure keeps the
            # drop dispatch clean for the paths where the tint fails.
            pass

    def _revert_row(self) -> None:
        """Restore the previously-active row's style and drop our handles."""
        if self._active_row is None:
            return
        setter = getattr(self._active_row, "set_style", None)
        if setter is not None:
            try:
                setter(self._active_row_style or {})
            except Exception:  # noqa: BLE001
                pass
        self._active_row = None
        self._active_row_style = None

    # ── Card highlight ───────────────────────────────────────────────────────

    def show_card_highlight(self, card: Any) -> None:
        """Flip ``card``'s hit rect to the ``Content.Card::drop_hover`` variant.

        The variant name is written to ``card._rect.name`` — the hit
        rect is the single :class:`ui.Rectangle` the card paints its
        background on, so the style lookup resolves to
        ``Content.Card::drop_hover`` for the duration of the hover.

        Passing ``None`` or a card with no live ``_rect`` (post-destroy
        race) is a silent no-op. Re-highlighting the currently-active
        card is idempotent; a highlight on a different card first
        reverts the previous card's variant so at most one card is in
        drop-hover state at any moment.
        """
        if card is None:
            return
        if card is self._active_card:
            return
        if self._active_card is not None:
            self._revert_card()
        rect = getattr(card, "_rect", None)
        if rect is None:
            return
        try:
            self._active_card_prev_name = str(getattr(rect, "name", "") or "")
        except Exception:  # noqa: BLE001
            self._active_card_prev_name = ""
        self._active_card = card
        try:
            rect.name = _CARD_DROP_HOVER_VARIANT
        except Exception:  # noqa: BLE001
            # Assigning ``name`` on a freshly-destroyed rect can raise;
            # undo the tracking so :meth:`clear` does not try to revert
            # a rect we never actually mutated.
            self._active_card = None
            self._active_card_prev_name = ""

    def _revert_card(self) -> None:
        """Restore the previously-active card's ``name`` to its pre-hover value."""
        if self._active_card is None:
            return
        rect = getattr(self._active_card, "_rect", None)
        if rect is not None:
            try:
                rect.name = self._active_card_prev_name
            except Exception:  # noqa: BLE001
                pass
        self._active_card = None
        self._active_card_prev_name = ""

    # ── Between-items line ───────────────────────────────────────────────────

    def show_between_line(self, y_position: float) -> None:
        """Record a y-coordinate for the between-rows drop indicator line.

        The indicator is a 2-px horizontal line the hosting delegate
        paints between two rows when a drag's drop target is a row
        boundary rather than a row body. The controller stores the
        coordinate only; the widget layer reads :attr:`between_line_y`
        on its next render to decide whether / where to paint the
        line. Keeping the line-widget ownership with the delegate
        means the indicator does not force a particular parent
        context on the paint site.

        Non-numeric input is a silent no-op — a defensive guard for
        callers that forward a stale y-coordinate from an event stream.
        """
        try:
            self._between_line_y = float(y_position)
        except (TypeError, ValueError):
            return

    # ── Clear ────────────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Revert every active highlight across all three channels.

        Called by the widget-level drop dispatcher on drop-end (the
        user released the mouse) or drop-outside (the cursor left all
        valid targets). Leaves the controller in its freshly-constructed
        state — a subsequent ``show_*`` call behaves as if the previous
        drag never happened.
        """
        self._revert_row()
        self._revert_card()
        self._between_line_y = None

    # ── Read-only accessors ──────────────────────────────────────────────────

    @property
    def current_row(self) -> Optional[Any]:
        """Currently-highlighted row widget, or ``None`` when inactive."""
        return self._active_row

    @property
    def current_card(self) -> Optional[Any]:
        """Currently-highlighted :class:`FileCard`, or ``None`` when inactive."""
        return self._active_card

    @property
    def between_line_y(self) -> Optional[float]:
        """Y-coordinate of the active between-rows line, or ``None``."""
        return self._between_line_y

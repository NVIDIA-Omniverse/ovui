# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""FileGridView — scrolling grid of :class:`FileCard` widgets (Step 22).

See the content browser behavior (grid view) and the content browser implementation step 22.
The grid is the default view for asset-heavy folders: a
:class:`ui.ScrollingFrame` wrapping a :class:`ui.VGrid` whose cells are
:class:`FileCard` instances — one per :class:`FileItem` in the current
root's sorted children list.

Key invariants from the architecture:

* **Lazy card build** (§9.2 OM-63433). Each card is wrapped in a
  :class:`ui.Frame` whose ``build_fn`` instantiates the
  :class:`FileCard`. The outer frames are cheap; the cards themselves
  (with their back-buffer :class:`ui.ImageWithProvider` + front-buffer
  :class:`ui.Image`) only materialise when the containing frame
  actually scrolls into view. Opens a folder of 10 000 cards without
  blocking on 10 000 image loads.
* **Grid owns selection** (§9.7 OM-70157). The model is a pure data
  source; selection semantics — single click, Ctrl-toggle, Shift-range
  — live on the view. Shift-range uses the model's sorted child order
  (the same order :meth:`refresh` captured into :attr:`_ordered_urls`)
  so the range matches what the user sees on screen.
* **Selection indexed by URL.** Cards can be destroyed + rebuilt when
  the scale changes or the root re-roots, and a refreshed model may
  hand back a fresh :class:`FileItem` Python object for the same URL.
  Keying selection by URL means a rebuild survives the transition
  without losing the user's selection — architecture §9.2 calls this
  out explicitly as the reason the Kit grid carries
  ``_pending_selections``.

Not wired into :class:`FileBrowserWidget` yet — that happens in Step 24
when the zoom bar toggles between the tree and grid views.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

import omni.ui as ui

from ovui_widgets.content.widget.file_browser_model import FileBrowserModel
from ovui_widgets.content.widget.file_card import FileCard
from ovui_widgets.content.widget.file_item import FileItem

if TYPE_CHECKING:
    from ovui_widgets.content.widget.drop_indicator import DropIndicator


# GLFW modifier bit flags delivered by ovui mouse-pressed callbacks.
# Mirror the constants in :mod:`ovui_widgets.app.application` (Kit does not
# expose the ``carb.input`` enum in this ovui build); lifted here so
# this module does not import the application surface (which would
# drag the singleton into every test that just instantiates a grid).
_MOD_SHIFT = 1
_MOD_CTRL = 2

# Extra vertical room reserved under the image square for the card's
# label band. Matches :data:`FileCard._LABEL_HEIGHT` — the grid's
# row height has to account for the label pixels the card actually
# renders, otherwise the VGrid would clip the label off the bottom
# of each row.
_LABEL_BAND_HEIGHT = 18

# Default card edge in logical pixels at scale 1.0. The reduced edge keeps
# the grid closer to the dense reference thumbnails while FileCard itself
# still accepts larger explicit sizes from tests and callers.
_DEFAULT_CARD_SIZE = 76

# Extra cell stride around the fixed card footprint. The reference Content
# Browser at 75% zoom uses a roughly 80 px horizontal thumbnail cadence while
# its cyan asset glyph stays about 48 px wide. Keeping the card size unchanged
# preserves the accepted icon scale; these gutters only loosen the VGrid cell
# rhythm around the real filesystem cards.
_CELL_HORIZONTAL_GUTTER = 23
_CELL_VERTICAL_GUTTER = 13


class FileGridView:
    """Scrolling grid of :class:`FileCard` tiles over a :class:`FileBrowserModel`.

    Construction builds the scrolling frame + grid into the surrounding
    ovui build context — same contract as :class:`FileBrowserWidget` /
    :class:`BrowserBar` / :class:`PathField`.

    After construction, :meth:`refresh` populates cards from the model's
    current root children. :meth:`set_scale` rescales card dimensions.
    :meth:`get_selection` / :meth:`set_selection` expose the grid's
    internal selection (not the model's — architecture §9.7 is explicit
    that selection belongs to the view, not the data layer).

    Handlers:

    * ``on_click(item, button, modifier)`` — fired on every
      :meth:`FileCard` click, *after* the grid has updated its own
      selection. Dispatch for right-click context menus (Step 31), etc.
    * ``on_right_click(item, x_screen, y_screen)`` — Step 31 pop-a-menu
      hook. Fired when a card dispatches a right-button press; the
      screen coords come straight from :meth:`FileCard` so the grid
      does not own the local-to-screen translation. A ``None`` handler
      is a silent no-op so tests can instantiate without wiring one.
    * ``on_empty_right_click(x_screen, y_screen)`` — Step 31 fallback
      for right-clicks that land outside any card (gaps between cards
      in the grid). Wired via :meth:`set_mouse_pressed_fn` on the
      inner scrolling frame; a click absorbed by a card does not fire
      this handler because the card's hit rect consumes the event.
    * ``on_double_click(item)`` — fired on a left-button double-click.
      A folder card should drill in; a leaf card should open the asset
      (Step 54). Either handler may be ``None`` — the grid treats the
      absence as a silent no-op.
    """

    def __init__(
        self,
        model: FileBrowserModel,
        on_click: Optional[Callable[[FileItem, int, int], None]] = None,
        on_double_click: Optional[Callable[[FileItem], None]] = None,
        on_right_click: Optional[
            Callable[[FileItem, float, float], None]
        ] = None,
        on_empty_right_click: Optional[
            Callable[[float, float], None]
        ] = None,
        on_card_drag: Optional[Callable[[], str]] = None,
        on_card_drop: Optional[Callable[[FileItem, str], None]] = None,
        drop_indicator: Optional["DropIndicator"] = None,
    ) -> None:
        self._model: Optional[FileBrowserModel] = model
        self._on_click = on_click
        self._on_double_click = on_double_click
        self._on_right_click = on_right_click
        self._on_empty_right_click = on_empty_right_click
        # Step 41 — shared drop-hover coordinator. ``None`` keeps card
        # builds free of the indicator wiring; a real instance (owned
        # by :class:`FileBrowserWidget`) gets threaded into every card
        # so a drag over one card tints it via the same controller
        # that any other surface in the browser would consult.
        self._drop_indicator: Optional["DropIndicator"] = drop_indicator
        # Step 38 — card-level drag-drop handlers. ``on_card_drag``
        # builds the MIME payload for a card-initiated drag (typically
        # ``"\n"``-joined URLs from the grid's selection); ``on_card_drop``
        # routes a drop onto a folder card into the widget's drop
        # dispatcher. Both are ``None`` for callers that have not opted
        # into the drag-drop surface — cards built under a ``None``
        # handler skip the corresponding ovui slot (see
        # :meth:`FileCard.build`).
        self._on_card_drag: Optional[Callable[[], str]] = on_card_drag
        self._on_card_drop: Optional[Callable[[FileItem, str], None]] = (
            on_card_drop
        )
        # Step 33: the host widget's :class:`RenameController`; ``None``
        # until :meth:`set_rename_controller` is called. Each card
        # constructed in :meth:`_build_card_in_frame` receives this
        # reference so the card can branch its label build between the
        # default label and an inline :class:`ui.StringField` when the
        # item is the active rename target.
        self._rename_controller: Optional[Any] = None

        # Scale-aware card size. ``_card_size`` is the base edge (76 px)
        # and ``_scale`` multiplies into it on :meth:`set_scale`. The
        # effective card edge is :meth:`_effective_size`; the VGrid
        # adds explicit cell gutters around that footprint so the
        # thumbnail cadence matches the reference without scaling the
        # accepted cyan icon artwork.
        self._card_size: int = _DEFAULT_CARD_SIZE
        self._scale: float = 1.0

        # url → live :class:`FileCard`. Populated lazily by the outer
        # :class:`ui.Frame`'s ``build_fn`` when a cell scrolls into view
        # (architecture §9.2 OM-63433). Cards are destroyed + dropped
        # on :meth:`refresh` / :meth:`set_scale` / :meth:`destroy`.
        self._cards: Dict[str, FileCard] = {}

        # Ordered URL list — mirrors the model's ``get_item_children``
        # output at the time :meth:`refresh` ran. Shift-click range
        # selection uses this ordering so the range matches exactly
        # what the user sees on screen, even if the model's sort
        # policy changes between refreshes.
        self._ordered_urls: List[str] = []

        # url → :class:`FileItem` snapshot taken at :meth:`refresh` time.
        # The model may hand back a fresh :class:`FileItem` object for
        # the same URL after a repopulate; holding the snapshot keeps
        # :meth:`get_selection` returning whatever item the grid last
        # saw, matching the cards the user is actually looking at.
        self._items_by_url: Dict[str, FileItem] = {}

        # Grid-owned selection (architecture §9.7). Stored as URLs so a
        # refresh that swaps the :class:`FileItem` Python objects out
        # does not silently drop the selection; ``_selection_urls`` is
        # the insertion-order list that :meth:`get_selection` iterates,
        # ``_selection_set`` gives O(1) membership for the click path.
        self._selection_urls: List[str] = []
        self._selection_set: set = set()
        # Shift-click anchor — URL of the most recently single-clicked
        # card. ``None`` means no anchor; the first shift-click in that
        # state falls back to single-select to avoid a surprise
        # range-from-nowhere.
        self._last_clicked_url: Optional[str] = None

        # Widget refs.
        self._scrolling_frame: Optional[ui.ScrollingFrame] = None
        self._vgrid: Optional[ui.VGrid] = None

        self.build()

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Build the scrolling frame + VGrid into the current ovui context.

        Layout::

            ScrollingFrame (identifier=content_browser_grid_view)
            └── VGrid (column_width=size+gutter, row_height=size+label+gutter)
                ├── Frame (build_fn=lambda: FileCard(item[0]))
                ├── Frame (build_fn=lambda: FileCard(item[1]))
                └── ...

        The horizontal scrollbar is switched off because the VGrid
        derives its column count from the available width — there is
        no need for horizontal scrolling, and showing an always-on
        horizontal bar would steal vertical pixels from the last row
        of cards at every zoom level.
        """
        self._scrolling_frame = ui.ScrollingFrame(
            identifier="content_browser_grid_view",
            horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
            vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED,
            style_type_name_override="Content.ScrollingFrame",
        )
        with self._scrolling_frame:
            self._vgrid = ui.VGrid(
                column_width=self._column_width(),
                row_height=self._row_height(),
                content_clipping=True,
            )
            with self._vgrid:
                self._populate_cards()
        # Step 31: a right-click that lands in the gap between cards
        # passes through the VGrid (a layout, not a hit target) and
        # reaches the scrolling frame. Wiring a mouse-pressed handler
        # on the frame fires for those empty-space clicks; clicks
        # absorbed by a card's hit rect do not reach here. Used by
        # :class:`FileBrowserWidget` to pop the empty-space context
        # menu (Create Folder / Paste / Refresh).
        self._scrolling_frame.set_mouse_pressed_fn(
            self._dispatch_scrolling_frame_pressed,
        )

    def set_rename_controller(self, controller: Optional[Any]) -> None:
        """Inject the widget's :class:`RenameController` (Step 33).

        Cards built after this call receive the controller at
        construction so their label-band builder can route the active
        rename target through an inline :class:`ui.StringField`.
        Passing ``None`` detaches the controller — the widget's
        :meth:`destroy` path calls this before nulling its own ref so a
        late card-builder closure cannot pick up a stale controller.
        """
        self._rename_controller = controller

    # ── Sizing helpers ───────────────────────────────────────────────────────

    def _effective_size(self) -> int:
        """Card edge in pixels at the current zoom scale."""
        return max(1, int(self._card_size * self._scale))

    def _column_width(self) -> int:
        """VGrid column stride — card edge plus reference-style gutter."""
        return self._effective_size() + _CELL_HORIZONTAL_GUTTER

    def _row_height(self) -> int:
        """VGrid row stride — card edge, label band, and vertical gutter."""
        return (
            self._effective_size()
            + _LABEL_BAND_HEIGHT
            + _CELL_VERTICAL_GUTTER
        )

    # ── Card population ──────────────────────────────────────────────────────

    def _populate_cards(self) -> None:
        """Enumerate the model's root children and emit one Frame per item.

        Must be called inside a ``with self._vgrid:`` block so the
        frames attach as VGrid cells. Each frame carries a ``build_fn``
        that materialises the :class:`FileCard` lazily — the card's
        back-buffer :class:`ui.ImageWithProvider` and front-buffer
        :class:`ui.Image` only allocate when the frame scrolls into
        view (architecture §9.2 OM-63433).
        """
        if self._model is None:
            return
        children = self._model.get_item_children(None)
        for child in children:
            if not isinstance(child, FileItem):
                continue
            self._ordered_urls.append(child.url)
            self._items_by_url[child.url] = child
            # Default-arg binding captures ``child`` by value so every
            # frame's closure resolves to the right item even after the
            # loop variable moves on.
            ui.Frame(
                build_fn=lambda item=child: self._build_card_in_frame(item),
            )

    def _dispatch_scrolling_frame_pressed(
        self, x: Any, y: Any, button: Any, modifier: Any,
    ) -> None:
        """Route a frame-level right-press to ``on_empty_right_click``.

        Step 31. Fires when the user right-clicks the grid background
        (VGrid gaps, trailing empty area below the last row). Card
        clicks do not reach here — the card's hit :class:`ui.Rectangle`
        consumes the event. The frame reports widget-local coordinates;
        translating by the frame's screen position yields the absolute
        coords :meth:`ui.Menu.show_at` expects.

        Non-right buttons pass through to plain scroll / focus handling
        — we only intercept ``button == 1`` because the empty-space
        context menu is the only side effect the grid owns here.
        """
        if int(button) != 1:
            return
        if self._on_empty_right_click is None:
            return
        screen_x = float(x)
        screen_y = float(y)
        if self._scrolling_frame is not None:
            screen_x += float(self._scrolling_frame.screen_position_x)
            screen_y += float(self._scrolling_frame.screen_position_y)
        self._on_empty_right_click(screen_x, screen_y)

    def _build_card_in_frame(self, item: FileItem) -> None:
        """Build the :class:`FileCard` for ``item`` — called by Frame's build_fn.

        Runs once per frame realisation. Stores the card in
        :attr:`_cards` so :meth:`set_selection` / :meth:`refresh` /
        :meth:`destroy` can reach it without walking the VGrid, and
        restores any pre-existing selection so a card that lands after
        :meth:`set_selection` already ran still paints correctly.

        Step 29: reads the model's current ``text_filter`` and passes
        it into the card constructor so a non-empty filter routes the
        label through :class:`HighlightLabel`. The filter is read
        fresh per card rather than latched at :meth:`refresh` time
        because a filter change is itself what triggers the refresh
        via :meth:`FileBrowserModel._schedule_item_changed`, so the
        two are always consistent by the time this method runs.
        """
        search_term = ""
        if self._model is not None:
            search_term = self._model.text_filter
        card = FileCard(
            item,
            on_click=lambda btn, mod, i=item: self._handle_card_click(i, btn, mod),
            on_double_click=lambda i=item: self._handle_card_double_click(i),
            size=self._effective_size(),
            search_term=search_term,
            on_right_click=(
                lambda sx, sy, i=item: self._handle_card_right_click(i, sx, sy)
            ),
            rename_controller=self._rename_controller,
            on_drag=self._on_card_drag,
            on_drop=self._on_card_drop,
            drop_indicator=self._drop_indicator,
        )
        self._cards[item.url] = card
        if item.url in self._selection_set:
            card.set_selected(True)

    # ── Click routing ────────────────────────────────────────────────────────

    def _handle_card_click(
        self, item: FileItem, button: int, modifier: int,
    ) -> None:
        """Apply the grid's selection policy, then forward to ``on_click``.

        Only the left mouse button drives selection changes — right /
        middle-button presses are passed through to ``on_click`` with
        the selection untouched so a future context-menu handler
        (Step 31) can open a menu without clobbering multi-selection.

        Left-button modifier handling (architecture §9.7):

        * ``Ctrl`` → toggle this card's membership in the selection;
          leave the anchor alone so a subsequent Shift-click still
          ranges from the last single-click.
        * ``Shift`` → select the range from the last single-click
          anchor to this card, in :attr:`_ordered_urls` order.
        * No modifier → replace the selection with this card alone and
          move the anchor here.
        """
        if button == 0:
            if modifier & _MOD_CTRL:
                self._toggle_in_selection(item)
            elif modifier & _MOD_SHIFT:
                self._range_select(item)
            else:
                self._set_selection_single(item)
                self._last_clicked_url = item.url
        if self._on_click is not None:
            self._on_click(item, button, modifier)

    def _handle_card_double_click(self, item: FileItem) -> None:
        """Forward a left-button double-click to ``on_double_click``."""
        if self._on_double_click is not None:
            self._on_double_click(item)

    def _handle_card_right_click(
        self, item: FileItem, x_screen: float, y_screen: float,
    ) -> None:
        """Forward a card right-click to ``on_right_click`` (Step 31).

        The card computed screen coords before calling here so
        :meth:`ui.Menu.show_at` at the caller side does not need
        another conversion. A right-click on a card outside the
        current selection is left *not* to mutate selection — Kit's
        grid behaves the same, and clobbering the multi-selection on
        a right-click would surprise users who intended a batch
        action via the context menu.
        """
        if self._on_right_click is not None:
            self._on_right_click(item, float(x_screen), float(y_screen))

    def _set_selection_single(self, item: FileItem) -> None:
        """Replace the selection with only ``item`` and paint the diff."""
        old = list(self._selection_urls)
        self._selection_urls = [item.url]
        self._selection_set = {item.url}
        for prev_url in old:
            if prev_url == item.url:
                continue
            prev_card = self._cards.get(prev_url)
            if prev_card is not None:
                prev_card.set_selected(False)
        card = self._cards.get(item.url)
        if card is not None:
            card.set_selected(True)

    def _toggle_in_selection(self, item: FileItem) -> None:
        """Add ``item`` to the selection if absent; remove it if present."""
        card = self._cards.get(item.url)
        if item.url in self._selection_set:
            self._selection_urls.remove(item.url)
            self._selection_set.discard(item.url)
            if card is not None:
                card.set_selected(False)
        else:
            self._selection_urls.append(item.url)
            self._selection_set.add(item.url)
            if card is not None:
                card.set_selected(True)

    def _range_select(self, item: FileItem) -> None:
        """Select every URL between the anchor and ``item`` inclusive.

        Uses :attr:`_ordered_urls` — the model's sort order captured at
        the last :meth:`refresh` — so the range matches what the user
        sees on screen rather than a stale iteration order. If the
        anchor is missing (never single-clicked, or the anchor's row
        has been refreshed out) we degrade gracefully to a single-click
        at the target.
        """
        if (
            self._last_clicked_url is None
            or self._last_clicked_url not in self._ordered_urls
            or item.url not in self._ordered_urls
        ):
            self._set_selection_single(item)
            self._last_clicked_url = item.url
            return
        start = self._ordered_urls.index(self._last_clicked_url)
        end = self._ordered_urls.index(item.url)
        if start > end:
            start, end = end, start
        new_urls = list(self._ordered_urls[start:end + 1])
        new_set = set(new_urls)
        for prev_url in list(self._selection_urls):
            if prev_url not in new_set:
                prev_card = self._cards.get(prev_url)
                if prev_card is not None:
                    prev_card.set_selected(False)
        for new_url in new_urls:
            if new_url not in self._selection_set:
                new_card = self._cards.get(new_url)
                if new_card is not None:
                    new_card.set_selected(True)
        self._selection_urls = new_urls
        self._selection_set = new_set

    # ── Public API ───────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Rebuild every card from the model's current root children.

        Destroys existing cards, clears the VGrid, and walks
        :meth:`FileBrowserModel.get_item_children` to emit one
        ``build_fn``-backed :class:`ui.Frame` per child. The selection
        is preserved across the rebuild because it is keyed by URL —
        any surviving URLs get their cards restored to
        ``selected=True`` in :meth:`_build_card_in_frame` when the
        next render pass fires each frame's build callback.
        """
        self._clear_cards()
        if self._vgrid is None:
            return
        self._vgrid.clear()
        with self._vgrid:
            self._populate_cards()

    def set_scale(self, scale: float) -> None:
        """Update the card size and VGrid column / row dimensions.

        :class:`FileCard` fixes its size at construction time, so a
        scale change requires a full card rebuild. Selection survives
        via :meth:`refresh`'s URL-indexed restore.
        """
        try:
            new_scale = float(scale)
        except (TypeError, ValueError):
            return
        if new_scale <= 0.0:
            return
        self._scale = new_scale
        if self._vgrid is not None:
            self._vgrid.column_width = ui.Pixel(self._column_width())
            self._vgrid.row_height = ui.Pixel(self._row_height())
        self.refresh()

    def get_selection(self) -> List[FileItem]:
        """Return the selected :class:`FileItem` instances in click order.

        URLs are resolved through :attr:`_items_by_url` — the snapshot
        :meth:`refresh` took of the model's children. URLs whose items
        have aged out of the grid (e.g. the folder has since
        repopulated without them) are silently skipped, matching Kit's
        behaviour on a torn-down card.
        """
        result: List[FileItem] = []
        for url in self._selection_urls:
            item = self._items_by_url.get(url)
            if item is not None:
                result.append(item)
        return result

    def set_selection(self, items: List[FileItem]) -> None:
        """Overwrite the selection with ``items`` and repaint card states.

        Accepts any iterable of :class:`FileItem`; duplicates are
        deduplicated on URL. The Shift-click anchor moves to the last
        item in ``items`` so a subsequent Shift-click ranges from
        there; passing an empty list clears the anchor.
        """
        new_urls: List[str] = []
        seen: set = set()
        for item in items:
            if not isinstance(item, FileItem):
                continue
            if item.url in seen:
                continue
            seen.add(item.url)
            new_urls.append(item.url)
        new_set = set(new_urls)

        for prev_url in list(self._selection_urls):
            if prev_url not in new_set:
                prev_card = self._cards.get(prev_url)
                if prev_card is not None:
                    prev_card.set_selected(False)
        for new_url in new_urls:
            if new_url not in self._selection_set:
                new_card = self._cards.get(new_url)
                if new_card is not None:
                    new_card.set_selected(True)

        self._selection_urls = new_urls
        self._selection_set = new_set
        self._last_clicked_url = new_urls[-1] if new_urls else None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _clear_cards(self) -> None:
        """Destroy every live card and drop the ordered-URL snapshot.

        Does not touch selection — :meth:`refresh` deliberately keeps
        :attr:`_selection_urls` alive so cards rebuilt from surviving
        URLs repaint as selected.
        """
        for card in list(self._cards.values()):
            card.destroy()
        self._cards.clear()
        self._ordered_urls = []
        self._items_by_url = {}

    def destroy(self) -> None:
        """Release every card + widget ref and drop handler references.

        Idempotent — attribute guards short-circuit a second call.
        """
        self._clear_cards()
        if self._scrolling_frame is not None:
            # Step 31: cut the frame's right-click subscription before
            # the Python ref drops. Without this, the bound method
            # keeps the grid alive through ovui's internal callback
            # slot until the C++ frame itself tears down.
            self._scrolling_frame.set_mouse_pressed_fn(None)
        self._scrolling_frame = None
        self._vgrid = None
        self._selection_urls = []
        self._selection_set = set()
        self._last_clicked_url = None
        self._model = None
        # Drop handler refs last so a pending card-build closure that
        # still holds the grid through a captured ``self`` falls
        # through to the ``None`` guards rather than firing into a
        # half-destroyed grid.
        self._on_click = None
        self._on_double_click = None
        self._on_right_click = None
        self._on_empty_right_click = None
        # Step 38 — drag / drop handler refs follow the same teardown
        # rule: a card built moments before destroy may still hold a
        # bound-method reference through its lambda closures, so
        # clearing the grid's refs here makes a late dispatch fall
        # through to the card-level ``None`` guards.
        self._on_card_drag = None
        self._on_card_drop = None
        # Step 41 — drop the indicator ref so a stale card-build
        # closure in flight falls through to the card-level ``None``
        # guards rather than mutating a controller the widget has
        # already cleared.
        self._drop_indicator = None

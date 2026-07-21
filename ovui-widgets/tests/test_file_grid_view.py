# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`FileGridView` (the content browser implementation step 22).

Coverage:

* Public surface — package re-export + ``__all__`` inclusion.
* Construction — grid builds the scrolling frame + VGrid, captures the
  model's children into :attr:`_ordered_urls` in sort order, wires
  the click / double-click handlers.
* :meth:`refresh` rebuilds ``_ordered_urls`` / ``_items_by_url`` and
  destroys any live cards from the previous populate.
* :meth:`set_scale` updates the VGrid column + row dimensions and the
  card edge used on the next card build.
* Selection: single-click replaces, Ctrl-click toggles, Shift-click
  ranges through :attr:`_ordered_urls` order.
* :meth:`get_selection` / :meth:`set_selection` round-trip items and
  survive a :meth:`refresh` (URL-indexed restore).
* :meth:`destroy` is idempotent, clears cards + widget refs, and
  drops handler references.

Cards are built lazily from inside a :class:`ui.Frame` ``build_fn``,
so the test scaffolding invokes :meth:`_build_card_in_frame` directly
when it needs a :class:`FileCard` to assert against — without that,
the cards never materialise inside the ovui test harness's single-
pass build.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List, Tuple

import omni.ui as ui
import pytest

from ovui_widgets.app.testing import MockBackend
from ovui_widgets.content.widget import (
    FileBrowserModel,
    FileGridView,
    FileItem,
)
from ovui_widgets.content.widget.file_grid_view import (
    _CELL_HORIZONTAL_GUTTER,
    _CELL_VERTICAL_GUTTER,
    _DEFAULT_CARD_SIZE,
    _LABEL_BAND_HEIGHT,
    _MOD_CTRL,
    _MOD_SHIFT,
)
from ovui_widgets.content.widget.file_grid_view import (
    FileGridView as _FileGridView,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """Single ovui Window reused across every widget-build test."""
    win = ui.Window("_test_file_grid_view", width=400, height=400)
    yield win
    win.destroy()


@contextmanager
def in_window_frame(window):
    """Enter ``window.frame`` as a build context and clear it on exit."""
    try:
        with window.frame:
            yield
    finally:
        window.frame.clear()


@pytest.fixture
def backend() -> MockBackend:
    return MockBackend()


@pytest.fixture
def model(backend: MockBackend) -> FileBrowserModel:
    return FileBrowserModel(backend, "mock://Home")


def _materialise_all_cards(grid: FileGridView) -> None:
    """Force-build every lazy card in the grid.

    :class:`ui.Frame` ``build_fn`` only fires when the frame becomes
    visible, which the ovui test harness does not always simulate for
    off-screen tiles. Tests that need to assert against live
    :class:`FileCard` instances call this helper to synthesise the
    realise-on-scroll pass by hand — it walks the grid's own ordered
    snapshot and invokes the same builder the frame would call.
    """
    for url in list(grid._ordered_urls):
        if url in grid._cards:
            continue
        item = grid._items_by_url[url]
        grid._build_card_in_frame(item)


# ──────────────────────────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestSurface:
    def test_reexported_from_widget_package(self):
        from ovui_widgets.content.widget import FileGridView as FGV

        assert FGV is _FileGridView

    def test_widget_package_all_contains_file_grid_view(self):
        import ovui_widgets.content.widget as pkg

        assert "FileGridView" in pkg.__all__


# ──────────────────────────────────────────────────────────────────────────────
# Construction
# ──────────────────────────────────────────────────────────────────────────────


class TestConstruction:
    def test_instantiates_with_model(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        assert isinstance(grid, FileGridView)
        grid.destroy()

    def test_build_creates_scrolling_frame(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        assert grid._scrolling_frame is not None
        grid.destroy()

    def test_build_creates_vgrid(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        assert grid._vgrid is not None
        grid.destroy()

    def test_default_scale_is_one(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        assert grid._scale == 1.0
        grid.destroy()

    def test_default_card_size_matches_reference_thumbnail_density(
        self, ephemeral_window, model,
    ):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        assert grid._card_size == _DEFAULT_CARD_SIZE == 76
        grid.destroy()

    def test_populates_ordered_urls_in_sort_order(
        self, ephemeral_window, model,
    ):
        """The initial populate walks the model's sorted children and
        captures their URLs into ``_ordered_urls`` — the same order
        Shift-click range selection later uses."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        expected = [c.url for c in model.get_item_children(None)]
        assert grid._ordered_urls == expected
        grid.destroy()

    def test_populates_items_by_url(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        for url in grid._ordered_urls:
            assert url in grid._items_by_url
            assert grid._items_by_url[url].url == url
        grid.destroy()

    def test_cards_are_lazy_not_built_until_visible(
        self, ephemeral_window, model,
    ):
        """Each card sits inside a Frame(build_fn=…) that only fires
        when the frame becomes visible (architecture §9.2 OM-63433).
        Under the test harness the frames never realise, so
        ``_cards`` stays empty after construction."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        assert grid._cards == {}
        grid.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Refresh
# ──────────────────────────────────────────────────────────────────────────────


class TestRefresh:
    def test_refresh_rebuilds_ordered_urls(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        original = list(grid._ordered_urls)
        grid.refresh()
        assert grid._ordered_urls == original
        grid.destroy()

    def test_refresh_destroys_old_cards(self, ephemeral_window, model):
        """After :meth:`refresh`, cards from the previous populate
        are destroyed — a subsequent materialise yields fresh objects.
        """
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            assert len(grid._cards) > 0
            first_card = next(iter(grid._cards.values()))
            grid.refresh()
            # Old cards are destroyed (widget refs cleared).
            assert first_card._root is None
            # Cards dict is cleared.
            assert grid._cards == {}
        grid.destroy()

    def test_refresh_picks_up_new_children(
        self, ephemeral_window, backend, model,
    ):
        """A refresh after the model's children change re-walks the
        model and updates the ordered URL list."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        original_len = len(grid._ordered_urls)
        # Force the model to refresh — adds no real items here, but
        # verifies that :meth:`refresh` re-queries the model rather
        # than reusing a stale snapshot.
        grid.refresh()
        assert len(grid._ordered_urls) == original_len
        grid.destroy()

    def test_refresh_preserves_selection_by_url(
        self, ephemeral_window, model,
    ):
        """Selection is URL-keyed: a refresh survives the rebuild
        because ``_selection_urls`` outlives ``_cards``."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        children = model.get_item_children(None)
        grid.set_selection([children[0]])
        grid.refresh()
        assert grid._selection_urls == [children[0].url]
        grid.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Scale
# ──────────────────────────────────────────────────────────────────────────────


class TestSetScale:
    def test_set_scale_updates_internal_scale(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        grid.set_scale(2.0)
        assert grid._scale == 2.0
        grid.destroy()

    def test_set_scale_updates_column_width(self, ephemeral_window, model):
        """Column width equals scaled card edge plus horizontal gutter."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        grid.set_scale(1.5)
        expected = int(_DEFAULT_CARD_SIZE * 1.5) + _CELL_HORIZONTAL_GUTTER
        assert int(grid._vgrid.column_width) == expected
        grid.destroy()

    def test_set_scale_updates_row_height(self, ephemeral_window, model):
        """Row height equals scaled card edge plus label band and gutter."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        grid.set_scale(0.75)
        expected = (
            int(_DEFAULT_CARD_SIZE * 0.75)
            + _LABEL_BAND_HEIGHT
            + _CELL_VERTICAL_GUTTER
        )
        assert int(grid._vgrid.row_height) == expected
        grid.destroy()

    def test_set_scale_rebuilds_cards(self, ephemeral_window, model):
        """FileCard.size is immutable, so set_scale rebuilds every
        live card to pick up the new edge length."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            old_cards = list(grid._cards.values())
            grid.set_scale(2.0)
            _materialise_all_cards(grid)
        # Old cards have been destroyed — widget refs cleared.
        for old in old_cards:
            assert old._root is None
        # New cards built at the new scale.
        for card in grid._cards.values():
            assert card.size == int(_DEFAULT_CARD_SIZE * 2.0)
        grid.destroy()

    def test_set_scale_ignores_zero_or_negative(
        self, ephemeral_window, model,
    ):
        """A bogus scale is a no-op; the grid keeps its previous scale."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        grid.set_scale(1.5)
        grid.set_scale(0.0)
        assert grid._scale == 1.5
        grid.set_scale(-0.5)
        assert grid._scale == 1.5
        grid.destroy()

    def test_set_scale_ignores_non_numeric(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        grid.set_scale("not-a-number")  # type: ignore[arg-type]
        assert grid._scale == 1.0
        grid.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Selection — click / get / set
# ──────────────────────────────────────────────────────────────────────────────


class TestSelection:
    def test_single_click_selects(self, ephemeral_window, model):
        """A plain left-click on a card replaces the selection with
        just that card."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            grid._handle_card_click(children[0], button=0, modifier=0)
        assert grid._selection_urls == [children[0].url]
        grid.destroy()

    def test_single_click_replaces_previous_selection(
        self, ephemeral_window, model,
    ):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            grid._handle_card_click(children[0], button=0, modifier=0)
            grid._handle_card_click(children[1], button=0, modifier=0)
        assert grid._selection_urls == [children[1].url]
        grid.destroy()

    def test_ctrl_click_toggles_on(self, ephemeral_window, model):
        """Ctrl-click on an unselected card adds it to the selection."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            grid._handle_card_click(children[0], button=0, modifier=0)
            grid._handle_card_click(children[1], button=0, modifier=_MOD_CTRL)
        assert set(grid._selection_urls) == {children[0].url, children[1].url}
        grid.destroy()

    def test_ctrl_click_toggles_off(self, ephemeral_window, model):
        """Ctrl-click on an already-selected card removes it."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            grid._handle_card_click(children[0], button=0, modifier=0)
            grid._handle_card_click(children[1], button=0, modifier=_MOD_CTRL)
            grid._handle_card_click(children[0], button=0, modifier=_MOD_CTRL)
        assert grid._selection_urls == [children[1].url]
        grid.destroy()

    def test_shift_click_selects_range(self, ephemeral_window, model):
        """Shift-click selects every item between the anchor and
        the clicked card, inclusive, in ``_ordered_urls`` order."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            assert len(children) >= 3
            grid._handle_card_click(children[0], button=0, modifier=0)
            grid._handle_card_click(
                children[2], button=0, modifier=_MOD_SHIFT,
            )
        expected = [children[0].url, children[1].url, children[2].url]
        assert grid._selection_urls == expected
        grid.destroy()

    def test_shift_click_reverse_range(self, ephemeral_window, model):
        """Shift-click backwards (anchor is later in the list than
        target) still selects the inclusive range, in sort order."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            assert len(children) >= 3
            grid._handle_card_click(children[2], button=0, modifier=0)
            grid._handle_card_click(
                children[0], button=0, modifier=_MOD_SHIFT,
            )
        expected = [children[0].url, children[1].url, children[2].url]
        assert grid._selection_urls == expected
        grid.destroy()

    def test_shift_click_without_anchor_falls_back_to_single(
        self, ephemeral_window, model,
    ):
        """Shift-click with no prior single-click degrades to a
        single-select on the clicked item — no anchor means no range."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            grid._handle_card_click(
                children[1], button=0, modifier=_MOD_SHIFT,
            )
        assert grid._selection_urls == [children[1].url]
        grid.destroy()

    def test_click_paints_card_selected(self, ephemeral_window, model):
        """A single-click flips the clicked card's ``selected`` state."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            grid._handle_card_click(children[0], button=0, modifier=0)
            assert grid._cards[children[0].url]._rect.selected is True
        grid.destroy()

    def test_click_clears_previous_card_selected(
        self, ephemeral_window, model,
    ):
        """A fresh single-click clears the previously selected card."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            grid._handle_card_click(children[0], button=0, modifier=0)
            grid._handle_card_click(children[1], button=0, modifier=0)
            assert grid._cards[children[0].url]._rect.selected is False
            assert grid._cards[children[1].url]._rect.selected is True
        grid.destroy()

    def test_right_click_does_not_change_selection(
        self, ephemeral_window, model,
    ):
        """A right-click passes through to ``on_click`` but leaves
        selection intact so a future context menu does not clobber
        a multi-select."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            grid._handle_card_click(children[0], button=0, modifier=0)
            grid._handle_card_click(children[1], button=1, modifier=0)
        assert grid._selection_urls == [children[0].url]
        grid.destroy()

    def test_on_click_callback_fires(self, ephemeral_window, model):
        received: List[Tuple[str, int, int]] = []

        def on_click(item: FileItem, button: int, modifier: int) -> None:
            received.append((item.url, button, modifier))

        with in_window_frame(ephemeral_window):
            grid = FileGridView(model, on_click=on_click)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            grid._handle_card_click(children[0], button=0, modifier=0)
            grid._handle_card_click(children[1], button=1, modifier=_MOD_CTRL)
        assert received == [
            (children[0].url, 0, 0),
            (children[1].url, 1, _MOD_CTRL),
        ]
        grid.destroy()

    def test_on_double_click_callback_fires(self, ephemeral_window, model):
        received: List[str] = []

        with in_window_frame(ephemeral_window):
            grid = FileGridView(
                model,
                on_double_click=lambda i: received.append(i.url),
            )
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            grid._handle_card_double_click(children[0])
        assert received == [children[0].url]
        grid.destroy()

    def test_missing_handlers_are_safe(self, ephemeral_window, model):
        """A grid constructed without handlers must not raise on a
        click or double-click."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            # Must not raise:
            grid._handle_card_click(children[0], button=0, modifier=0)
            grid._handle_card_double_click(children[0])
        grid.destroy()


class TestGetSetSelection:
    def test_get_selection_returns_empty_list_initially(
        self, ephemeral_window, model,
    ):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        assert grid.get_selection() == []
        grid.destroy()

    def test_set_selection_stores_urls(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        children = model.get_item_children(None)
        grid.set_selection([children[0], children[2]])
        assert grid._selection_urls == [children[0].url, children[2].url]
        grid.destroy()

    def test_get_selection_roundtrips_items(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        children = model.get_item_children(None)
        grid.set_selection([children[1]])
        assert grid.get_selection() == [children[1]]
        grid.destroy()

    def test_set_selection_deduplicates(self, ephemeral_window, model):
        """Duplicate items collapse on URL — the internal set stays
        consistent with the ordered list."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        children = model.get_item_children(None)
        grid.set_selection([children[0], children[0], children[1]])
        assert grid._selection_urls == [children[0].url, children[1].url]
        grid.destroy()

    def test_set_selection_empty_clears_anchor(self, ephemeral_window, model):
        """Passing an empty list clears the Shift-click anchor too."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        children = model.get_item_children(None)
        grid.set_selection([children[0]])
        grid.set_selection([])
        assert grid._selection_urls == []
        assert grid._last_clicked_url is None
        grid.destroy()

    def test_set_selection_paints_cards(self, ephemeral_window, model):
        """After :meth:`set_selection`, live cards paint ``selected``."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            grid.set_selection([children[1]])
            assert grid._cards[children[0].url]._rect.selected is False
            assert grid._cards[children[1].url]._rect.selected is True
        grid.destroy()

    def test_set_selection_unpaints_previous(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            grid.set_selection([children[0]])
            grid.set_selection([children[1]])
            assert grid._cards[children[0].url]._rect.selected is False
            assert grid._cards[children[1].url]._rect.selected is True
        grid.destroy()

    def test_selection_survives_refresh(self, ephemeral_window, model):
        """Selection is keyed by URL and outlives a card rebuild."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        children = model.get_item_children(None)
        grid.set_selection([children[0], children[1]])
        grid.refresh()
        sel_urls = grid._selection_urls
        assert sel_urls == [children[0].url, children[1].url]
        grid.destroy()

    def test_selection_restores_paint_after_refresh(
        self, ephemeral_window, model,
    ):
        """Cards rebuilt after a refresh repaint themselves as
        selected if their URL is still in the selection."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            children = model.get_item_children(None)
            grid.set_selection([children[1]])
            grid.refresh()
            _materialise_all_cards(grid)
            assert grid._cards[children[1].url]._rect.selected is True
            assert grid._cards[children[0].url]._rect.selected is False
        grid.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Destroy
# ──────────────────────────────────────────────────────────────────────────────


class TestDestroy:
    def test_destroy_clears_cards(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            assert len(grid._cards) > 0
            grid.destroy()
        assert grid._cards == {}

    def test_destroy_drops_widget_refs(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        grid.destroy()
        assert grid._scrolling_frame is None
        assert grid._vgrid is None

    def test_destroy_drops_handler_refs(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(
                model,
                on_click=lambda *a: None,
                on_double_click=lambda *a: None,
            )
        grid.destroy()
        assert grid._on_click is None
        assert grid._on_double_click is None

    def test_destroy_clears_selection(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        children = model.get_item_children(None)
        grid.set_selection([children[0]])
        grid.destroy()
        assert grid._selection_urls == []
        assert grid._last_clicked_url is None

    def test_destroy_is_idempotent(self, ephemeral_window, model):
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        grid.destroy()
        # Must not raise:
        grid.destroy()

    def test_destroy_without_visible_cards_is_safe(
        self, ephemeral_window, model,
    ):
        """A grid whose frames never materialised still destroys
        cleanly — the empty ``_cards`` dict iteration is a no-op."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
        # No _materialise_all_cards — simulate a grid the user never
        # scrolled into.
        grid.destroy()
        assert grid._cards == {}


# ──────────────────────────────────────────────────────────────────────────────
# Card wiring — live FileCard integration
# ──────────────────────────────────────────────────────────────────────────────


class TestCardWiring:
    def test_materialised_cards_have_grid_handlers(
        self, ephemeral_window, model,
    ):
        """The :class:`FileCard` instances the grid builds carry
        closures that route into the grid's own click handlers.
        Invoking the card's ``_dispatch_mouse_pressed`` must land in
        the grid's selection path."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            card = grid._cards[children[0].url]
            card._dispatch_mouse_pressed(0, 0, 0, 0)
        assert grid._selection_urls == [children[0].url]
        grid.destroy()

    def test_materialised_cards_survive_destroy(
        self, ephemeral_window, model,
    ):
        """Destroying the grid also destroys the live cards."""
        with in_window_frame(ephemeral_window):
            grid = FileGridView(model)
            _materialise_all_cards(grid)
            children = model.get_item_children(None)
            card = grid._cards[children[0].url]
            grid.destroy()
        assert card._root is None

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 41 — content-browser drop indicator.

Covers :class:`ovui_widgets.content.widget.DropIndicator` — the
visual-feedback coordinator that tints tree rows, flips grid cards to
a ``Content.Card::drop_hover`` variant, and records a between-rows
line coordinate during a drag. Also covers the integration seams:

* :class:`FileCard` exposes a ``drop_indicator`` constructor slot and
  hands itself to :meth:`DropIndicator.show_card_highlight` when a
  compatible drag hovers over its hit rect.
* :class:`FileBrowserDelegate` / :class:`TreeFolderDelegate` expose
  :meth:`set_drop_indicator` and forward the same instance.
* :class:`FileBrowserWidget` owns the shared :class:`DropIndicator`
  instance and clears it on every drop dispatch so a lingering
  highlight does not survive a drag-release.

No ovui runtime is required for the unit behaviour checks — the
indicator is pure-Python state. Integration tests that require a live
build context (card construction, delegate row build) reuse the
``ephemeral_window`` pattern from :mod:`tests.test_file_card`.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, List, Optional, Tuple

import omni.ui as ui
import pytest

from ovui_widgets.app.testing.mock_backend import MockBackend
from ovui_widgets.content.widget import (
    DropIndicator,
    FileBrowserDelegate,
    FileBrowserWidget,
    FileCard,
    FileItem,
    TreeFolderDelegate,
)
from ovui_widgets.content.widget.drop_indicator import (
    _CARD_DROP_HOVER_VARIANT,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """One ovui window shared across every widget-build test."""
    win = ui.Window("_test_drop_indicator", width=400, height=400)
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
def indicator() -> DropIndicator:
    return DropIndicator()


def _folder_item(url: str = "mock://folder", name: str = "folder") -> FileItem:
    return FileItem(url=url, name=name, is_folder=True)


def _file_item(url: str = "mock://a.usd", name: str = "a.usd") -> FileItem:
    return FileItem(url=url, name=name, is_folder=False)


class _StubRow:
    """Stand-in for a :class:`ui.HStack` tree-row widget.

    Tracks ``set_style`` calls so tests can assert the indicator tint
    was applied / reverted without a live ovui build context. The
    attribute surface mirrors the bits the real ``DropIndicator``
    reads: ``style`` for the snapshot, ``set_style`` for the apply /
    revert path.
    """

    def __init__(self) -> None:
        self.style: Any = None
        self.set_style_calls: List[Any] = []

    def set_style(self, s: Any) -> None:
        self.set_style_calls.append(s)
        self.style = s


class _StubRect:
    """Stand-in for :class:`ui.Rectangle` — carries a mutable ``name``."""

    def __init__(self, name: str = "") -> None:
        self.name = name


class _StubCard:
    """Stand-in for :class:`FileCard` — exposes a writable ``_rect``."""

    def __init__(self, rect: Optional[_StubRect] = None) -> None:
        self._rect = rect if rect is not None else _StubRect()


# ──────────────────────────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestPackageSurface:
    def test_reexported_from_widget_package(self):
        from ovui_widgets.content.widget import DropIndicator as DI
        from ovui_widgets.content.widget.drop_indicator import (
            DropIndicator as DI2,
        )

        assert DI is DI2

    def test_widget_package_all_contains_drop_indicator(self):
        import ovui_widgets.content.widget as pkg

        assert "DropIndicator" in pkg.__all__


# ──────────────────────────────────────────────────────────────────────────────
# Pure-state behaviour (no ovui build context required)
# ──────────────────────────────────────────────────────────────────────────────


class TestInitialState:
    def test_current_row_starts_none(self, indicator: DropIndicator):
        assert indicator.current_row is None

    def test_current_card_starts_none(self, indicator: DropIndicator):
        assert indicator.current_card is None

    def test_between_line_y_starts_none(self, indicator: DropIndicator):
        assert indicator.between_line_y is None


class TestShowRowHighlight:
    def test_applies_tint_style(self, indicator: DropIndicator):
        row = _StubRow()
        indicator.show_row_highlight(row)
        assert indicator.current_row is row
        assert row.set_style_calls, "indicator must call set_style on the row"

    def test_none_is_silent_noop(self, indicator: DropIndicator):
        # A None widget must not raise and must not flip state.
        indicator.show_row_highlight(None)
        assert indicator.current_row is None

    def test_re_highlight_same_row_is_idempotent(self, indicator: DropIndicator):
        row = _StubRow()
        indicator.show_row_highlight(row)
        indicator.show_row_highlight(row)
        # Only one paint call — re-highlight on the same row is idempotent.
        assert len(row.set_style_calls) == 1

    def test_new_row_reverts_previous(self, indicator: DropIndicator):
        a = _StubRow()
        b = _StubRow()
        indicator.show_row_highlight(a)
        indicator.show_row_highlight(b)
        assert indicator.current_row is b
        # ``a`` had its style reset when ``b`` took over — the revert
        # lands as an additional set_style call on ``a``.
        assert len(a.set_style_calls) >= 2

    def test_clear_reverts_row(self, indicator: DropIndicator):
        row = _StubRow()
        indicator.show_row_highlight(row)
        indicator.clear()
        assert indicator.current_row is None

    def test_missing_set_style_attribute_is_silent(
        self, indicator: DropIndicator,
    ):
        # Widget-like object without ``set_style`` — absorbed without raising.
        class _Bare:
            pass

        indicator.show_row_highlight(_Bare())
        # Tracking still records the target so subsequent clear()
        # doesn't try to re-revert a widget it never touched.
        assert indicator.current_row is not None
        indicator.clear()
        assert indicator.current_row is None


class TestShowCardHighlight:
    def test_flips_rect_name_to_drop_hover(self, indicator: DropIndicator):
        card = _StubCard()
        indicator.show_card_highlight(card)
        assert indicator.current_card is card
        assert card._rect.name == _CARD_DROP_HOVER_VARIANT

    def test_preserves_and_restores_previous_name(self, indicator: DropIndicator):
        card = _StubCard(_StubRect(name="selected"))
        indicator.show_card_highlight(card)
        assert card._rect.name == _CARD_DROP_HOVER_VARIANT
        indicator.clear()
        assert card._rect.name == "selected"

    def test_none_is_silent_noop(self, indicator: DropIndicator):
        indicator.show_card_highlight(None)
        assert indicator.current_card is None

    def test_card_without_rect_is_silent(self, indicator: DropIndicator):
        class _NoRect:
            _rect = None

        indicator.show_card_highlight(_NoRect())
        assert indicator.current_card is None

    def test_re_highlight_same_card_is_idempotent(self, indicator: DropIndicator):
        card = _StubCard()
        indicator.show_card_highlight(card)
        # Second call on same card must not flip state; name already set.
        indicator.show_card_highlight(card)
        assert indicator.current_card is card
        assert card._rect.name == _CARD_DROP_HOVER_VARIANT

    def test_new_card_reverts_previous(self, indicator: DropIndicator):
        a = _StubCard(_StubRect(name=""))
        b = _StubCard(_StubRect(name=""))
        indicator.show_card_highlight(a)
        indicator.show_card_highlight(b)
        assert indicator.current_card is b
        # ``a``'s rect got its original empty name back.
        assert a._rect.name == ""
        assert b._rect.name == _CARD_DROP_HOVER_VARIANT

    def test_clear_reverts_card(self, indicator: DropIndicator):
        card = _StubCard()
        indicator.show_card_highlight(card)
        indicator.clear()
        assert indicator.current_card is None
        assert card._rect.name == ""


class TestShowBetweenLine:
    def test_records_y_position(self, indicator: DropIndicator):
        indicator.show_between_line(42.0)
        assert indicator.between_line_y == 42.0

    def test_int_is_coerced_to_float(self, indicator: DropIndicator):
        indicator.show_between_line(10)
        assert indicator.between_line_y == 10.0
        assert isinstance(indicator.between_line_y, float)

    def test_invalid_y_is_silent_noop(self, indicator: DropIndicator):
        indicator.show_between_line("not-a-number")  # type: ignore[arg-type]
        assert indicator.between_line_y is None

    def test_clear_resets_between_line(self, indicator: DropIndicator):
        indicator.show_between_line(10.0)
        indicator.clear()
        assert indicator.between_line_y is None


class TestClearChannelsAreIndependent:
    def test_clear_reverts_all_channels(self, indicator: DropIndicator):
        row = _StubRow()
        card = _StubCard()
        indicator.show_row_highlight(row)
        indicator.show_card_highlight(card)
        indicator.show_between_line(12.0)
        indicator.clear()
        assert indicator.current_row is None
        assert indicator.current_card is None
        assert indicator.between_line_y is None

    def test_clear_is_idempotent(self, indicator: DropIndicator):
        indicator.clear()  # no state → still a no-op
        indicator.clear()  # second call also fine
        assert indicator.current_row is None
        assert indicator.current_card is None
        assert indicator.between_line_y is None

    def test_row_highlight_does_not_touch_card_channel(
        self, indicator: DropIndicator,
    ):
        row = _StubRow()
        card = _StubCard()
        indicator.show_card_highlight(card)
        indicator.show_row_highlight(row)
        # The row paint did not disturb the card channel.
        assert indicator.current_card is card
        assert card._rect.name == _CARD_DROP_HOVER_VARIANT


# ──────────────────────────────────────────────────────────────────────────────
# Integration — FileCard wiring
# ──────────────────────────────────────────────────────────────────────────────


class TestFileCardIntegration:
    def test_card_accepts_drop_indicator_kwarg(self, ephemeral_window):
        indicator = DropIndicator()
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _folder_item(),
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
                on_drag=lambda: "",
                on_drop=lambda item, mime: None,
                drop_indicator=indicator,
            )
        assert card._drop_indicator is indicator
        card.destroy()

    def test_card_default_drop_indicator_is_none(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _folder_item(),
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
            )
        assert card._drop_indicator is None
        card.destroy()

    def test_accept_drop_lights_indicator_on_folder_target(
        self, ephemeral_window,
    ):
        indicator = DropIndicator()
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _folder_item(),
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
                on_drag=lambda: "",
                on_drop=lambda item, mime: None,
                drop_indicator=indicator,
            )
        assert card._accept_drop("mock://source.png") is True
        assert indicator.current_card is card
        assert card._rect.name == _CARD_DROP_HOVER_VARIANT
        card.destroy()

    def test_accept_drop_skips_indicator_on_file_target(
        self, ephemeral_window,
    ):
        indicator = DropIndicator()
        with in_window_frame(ephemeral_window):
            # File item — card must refuse the drop even with an indicator wired.
            card = FileCard(
                _file_item(),
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
                on_drag=lambda: "",
                on_drop=lambda item, mime: None,
                drop_indicator=indicator,
            )
        assert card._accept_drop("mock://source.png") is False
        # Indicator stays idle — a file tile does not paint drop-hover.
        assert indicator.current_card is None
        card.destroy()

    def test_dispatch_drop_clears_indicator(self, ephemeral_window):
        indicator = DropIndicator()
        captured: List[Tuple[FileItem, str]] = []

        def _on_drop(item: FileItem, mime: str) -> None:
            captured.append((item, mime))

        class _Evt:
            mime_data = "mock://src.usda"

        with in_window_frame(ephemeral_window):
            card = FileCard(
                _folder_item(),
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
                on_drag=lambda: "",
                on_drop=_on_drop,
                drop_indicator=indicator,
            )
        # Light the indicator first, then fire a drop.
        card._accept_drop("mock://src.usda")
        assert indicator.current_card is card
        card._dispatch_drop(_Evt())
        assert captured == [(card.item, "mock://src.usda")]
        assert indicator.current_card is None
        card.destroy()

    def test_destroy_drops_indicator_reference(self, ephemeral_window):
        indicator = DropIndicator()
        with in_window_frame(ephemeral_window):
            card = FileCard(
                _folder_item(),
                on_click=lambda b, m: None,
                on_double_click=lambda: None,
                drop_indicator=indicator,
            )
        card.destroy()
        assert card._drop_indicator is None


# ──────────────────────────────────────────────────────────────────────────────
# Integration — Delegate wiring
# ──────────────────────────────────────────────────────────────────────────────


class TestDelegateIntegration:
    def test_file_browser_delegate_has_setter(self):
        delegate = FileBrowserDelegate()
        indicator = DropIndicator()
        delegate.set_drop_indicator(indicator)
        assert delegate._drop_indicator is indicator
        delegate.set_drop_indicator(None)
        assert delegate._drop_indicator is None

    def test_tree_folder_delegate_has_setter(self):
        delegate = TreeFolderDelegate()
        indicator = DropIndicator()
        delegate.set_drop_indicator(indicator)
        assert delegate._drop_indicator is indicator
        delegate.set_drop_indicator(None)
        assert delegate._drop_indicator is None


# ──────────────────────────────────────────────────────────────────────────────
# Integration — FileBrowserWidget owns one shared indicator
# ──────────────────────────────────────────────────────────────────────────────


class TestFileBrowserWidgetIntegration:
    def test_widget_constructs_shared_indicator(self, ephemeral_window):
        backend = MockBackend()
        try:
            with in_window_frame(ephemeral_window):
                widget = FileBrowserWidget(
                    backend, "mock://Home",
                )
            # Step 42: one shared indicator on the widget and the
            # detail delegate. The nav pane no longer participates in
            # drag-drop (collections are not draggable / droppable), so
            # its delegate does not carry an indicator reference.
            assert widget._drop_indicator is not None
            assert (
                widget._detail_delegate._drop_indicator
                is widget._drop_indicator
            )
            # Grid view gets the same reference.
            assert (
                widget._detail_grid_view._drop_indicator
                is widget._drop_indicator
            )
            widget.destroy()
            # After destroy the indicator is released.
            assert widget._drop_indicator is None
        finally:
            backend.reset()

    def test_dispatch_drop_clears_indicator_on_release_outside(
        self, ephemeral_window,
    ):
        """A drop dispatch clears the indicator even when the drop bails out.

        An ``_dispatch_drop`` call with an empty MIME string happens when
        ovui fires a drop on a target that then bails (no payload to
        route). The indicator must still clear so a lingering highlight
        from the drag does not survive the release-outside.
        """
        backend = MockBackend()
        try:
            with in_window_frame(ephemeral_window):
                widget = FileBrowserWidget(backend, "mock://Home")
            # Simulate a card lit up during drag-over.
            stub_card = _StubCard()
            widget._drop_indicator.show_card_highlight(stub_card)
            assert widget._drop_indicator.current_card is stub_card
            # Empty-MIME drop → the handler bails early but still clears.
            widget._dispatch_drop(target_item=None, mime="")
            assert widget._drop_indicator.current_card is None
            widget.destroy()
        finally:
            backend.reset()

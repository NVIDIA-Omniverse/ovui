# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the Content Browser :class:`HighlightLabel` (the content browser implementation step 29).

The filename includes ``content_`` because ``tests/test_highlight_label.py``
is already owned by the :mod:`ovwidgets.property` Property Panel variant
(Step 7.1 of the property panel work). Both widgets share a conceptual
role — yellow-paint-the-matching-substring — but they are separate
classes in separate packages with separate style namespaces
(:class:`Content.HighlightLabel` vs :class:`Property.LabelColumn`) and
non-overlapping construction contracts, so two distinct test modules
prevent the two suites from leaking state across each other.

Coverage:

* Public surface — package re-export, ``__all__`` inclusion, palette
  token, style dict entries.
* :func:`split_selection` — the pure segment-splitter (no ovui build
  context needed) covering the architecture §33.5 contract:
  single match, multiple matches, case-insensitive, no match, empty
  text, empty search.
* Construction — widget refs populated, correct label count for each
  case, style suffixes applied (``::normal`` / ``::highlight``).
* :meth:`HighlightLabel.set_text` — rebuild semantics: clearing the
  search term, swapping the text, idempotent double-call.
* :meth:`HighlightLabel.destroy` — idempotent, widget refs cleared,
  :meth:`set_text` post-destroy is a silent no-op.
* Integration — :class:`FileBrowserModel.text_filter` property is
  exposed and reads back the last :meth:`set_text_filter` value.

The widget-build tests follow the ``tests/test_search_field.py`` shape:
an ``ephemeral_window`` fixture holds one ovui :class:`ui.Window` for
the module, and an ``in_window_frame`` context manager wraps each
build inside that window's frame. Splitter tests are pure Python.
"""

from __future__ import annotations

from contextlib import contextmanager

import omni.ui as ui
import pytest

from ovwidgets.content.widget import HighlightLabel
from ovwidgets.content.widget.highlight_label import (
    HighlightLabel as _HighlightLabel,
)
from ovwidgets.content.widget.highlight_label import (
    split_selection,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """Single ovui Window reused across every widget-build test."""
    win = ui.Window("_test_content_highlight_label", width=400, height=40)
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


# ──────────────────────────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestSurface:
    def test_highlight_label_reexported_from_widget_package(self):
        from ovwidgets.content.widget import HighlightLabel as HL

        assert HL is _HighlightLabel

    def test_widget_package_all_contains_highlight_label(self):
        import ovwidgets.content.widget as pkg

        assert "HighlightLabel" in pkg.__all__

    def test_palette_has_highlight_highlight_token(self):
        """Step 29 adds a warm-yellow :class:`cl.highlight_highlight`."""
        from omni.ui import color as cl

        import ovwidgets.app
        import ovwidgets.app.style  # noqa: F401 — register palette shades

        # The shade accessor resolves the registered name as a string
        # subclass (``_ShadeName``). Checking ``str()`` confirms the
        # ``cl.shade(..., name="highlight_highlight")`` call landed.
        assert str(cl.highlight_highlight) == "highlight_highlight"

    def test_content_highlight_label_styles_registered(self):
        """Style dict carries the ``::highlight`` / ``::normal`` variants."""
        from ovwidgets.content.style import CONTENT_STYLES

        assert "Content.HighlightLabel" in CONTENT_STYLES
        assert "Content.HighlightLabel::highlight" in CONTENT_STYLES
        assert "Content.HighlightLabel::normal" in CONTENT_STYLES

    def test_highlight_variant_uses_yellow_token(self):
        """``::highlight`` paints with :class:`cl.highlight_highlight`."""
        from omni.ui import color as cl

        from ovwidgets.content.style import CONTENT_STYLES

        style = CONTENT_STYLES["Content.HighlightLabel::highlight"]
        # ``style["color"]`` is a ``_ShadeName`` that stringifies to
        # the registered shade key — identity comparison against
        # ``cl.highlight_highlight`` is the ovui idiom.
        assert str(style["color"]) == str(cl.highlight_highlight)


# ──────────────────────────────────────────────────────────────────────────────
# split_selection — pure splitter
# ──────────────────────────────────────────────────────────────────────────────


class TestSplitSelection:
    def test_empty_text_returns_empty_list(self):
        assert split_selection("", "foo") == []

    def test_empty_text_empty_selection(self):
        assert split_selection("", "") == []

    def test_no_selection_returns_text_and_empty(self):
        """Architecture §33.5: no selection → ``[text, ""]``."""
        assert split_selection("hello", "") == ["hello", ""]

    def test_full_match_returns_empty_and_text(self):
        """Architecture §33.5: full match → ``["", text]``."""
        assert split_selection("hello", "hello") == ["", "hello"]

    def test_single_match_midway(self):
        """Single substring match in the middle of the text."""
        # Architecture contract: trailing non-match run is NOT padded
        # with an empty cell — the result terminates on the real tail.
        assert split_selection("foobar", "ob") == ["fo", "ob", "ar"]

    def test_multiple_matches(self):
        """Architecture §33.5 canonical example."""
        assert split_selection("helloworld", "o") == [
            "hell", "o", "w", "o", "rld",
        ]

    def test_case_insensitive_by_default(self):
        """Mixed-case needle matches any casing in the haystack."""
        # ``World`` matches the mixed-case ``Hello WORLD``; the match
        # segment preserves the original casing of the haystack.
        # Match consumes the final character so no trailing empty
        # non-match cell is appended.
        assert split_selection("Hello WORLD", "world") == [
            "Hello ", "WORLD",
        ]

    def test_case_sensitive_when_flag_set(self):
        """``match_case=True`` suppresses mismatched casing matches."""
        assert split_selection("Hello WORLD", "world", match_case=True) == [
            "Hello WORLD",
        ]

    def test_match_at_start(self):
        """Match at index 0 → leading empty non-match segment."""
        assert split_selection("foobar", "foo") == ["", "foo", "bar"]

    def test_match_at_end(self):
        """Match terminating the text — no trailing empty appended."""
        assert split_selection("barfoo", "foo") == ["bar", "foo"]

    def test_back_to_back_matches(self):
        """Two matches with no characters between them."""
        assert split_selection("foofoo", "foo") == [
            "", "foo", "", "foo",
        ]

    def test_no_match(self):
        """No match found → the full text in a single non-match cell."""
        assert split_selection("foobar", "xyz") == ["foobar"]


# ──────────────────────────────────────────────────────────────────────────────
# Construction
# ──────────────────────────────────────────────────────────────────────────────


class TestConstruction:
    def test_builds_refs_with_match(self, ephemeral_window):
        """A text+term pair produces the expected label count."""
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(text="hello", search_term="l")
        try:
            assert hl._root is not None
            assert hl._hstack is not None
            # "hello" with "l" splits to ["he", "l", "", "l", "o", ""]
            # — non-empty cells are 4: "he", "l", "l", "o".
            assert len(hl._labels) == 4
            assert hl.text == "hello"
            assert hl.search_term == "l"
        finally:
            hl.destroy()

    def test_builds_with_no_search_term(self, ephemeral_window):
        """Empty search term = one label for the whole text."""
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(text="demo.usda", search_term="")
        try:
            assert len(hl._labels) == 1
            assert hl._labels[0].text == "demo.usda"
        finally:
            hl.destroy()

    def test_builds_with_empty_text(self, ephemeral_window):
        """Empty text = zero labels emitted (splitter returns ``[]``)."""
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(text="", search_term="foo")
        try:
            assert hl._labels == []
        finally:
            hl.destroy()

    def test_no_match_renders_whole_text_once(self, ephemeral_window):
        """Text without the search term renders as a single non-match label."""
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(text="readme.md", search_term="foo")
        try:
            assert len(hl._labels) == 1
            assert hl._labels[0].text == "readme.md"
        finally:
            hl.destroy()

    def test_full_match_renders_one_label(self, ephemeral_window):
        """Text identical to the search term renders as one match label."""
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(text="foo", search_term="foo")
        try:
            assert len(hl._labels) == 1
            assert hl._labels[0].text == "foo"
        finally:
            hl.destroy()

    def test_case_insensitive_match(self, ephemeral_window):
        """Search term casing does not affect which cells highlight."""
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(text="Demo.USDA", search_term="demo")
        try:
            # Splitter preserves the original casing of the match cell.
            texts = [lbl.text for lbl in hl._labels]
            assert texts == ["Demo", ".USDA"]
        finally:
            hl.destroy()

    def test_multiple_matches_in_one_name(self, ephemeral_window):
        """Two matches in one text produce two highlight cells."""
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(text="foofoo", search_term="foo")
        try:
            # "foofoo" with "foo" → ["", "foo", "", "foo"] → two
            # non-empty cells, both highlight.
            texts = [lbl.text for lbl in hl._labels]
            assert texts == ["foo", "foo"]
            names = [lbl.name for lbl in hl._labels]
            assert names == ["highlight", "highlight"]
        finally:
            hl.destroy()

    def test_variant_names_applied(self, ephemeral_window):
        """Even-index cells → ``name="normal"``; odd-index → ``name="highlight"``.

        The splitter yields ``["foo", "bar", "baz"]`` for text
        ``foobarbaz`` + needle ``bar``; the rendered labels are
        ``foo`` (normal), ``bar`` (highlight), ``baz`` (normal).
        The label's ``style_type_name_override`` stays constant
        (``Content.HighlightLabel``) and the ``name`` attribute
        carries the variant so ovui resolves ``::normal`` /
        ``::highlight`` selectors from the CONTENT_STYLES dict.
        """
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(text="foobarbaz", search_term="bar")
        try:
            overrides = [
                lbl.style_type_name_override for lbl in hl._labels
            ]
            assert overrides == [
                "Content.HighlightLabel",
                "Content.HighlightLabel",
                "Content.HighlightLabel",
            ]
            names = [lbl.name for lbl in hl._labels]
            assert names == ["normal", "highlight", "normal"]
        finally:
            hl.destroy()

    def test_custom_style_type_namespace(self, ephemeral_window):
        """``style_type_name_override`` replaces the default namespace."""
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(
                text="ab",
                search_term="a",
                style_type_name_override="Custom.Thing",
            )
        try:
            overrides = [
                lbl.style_type_name_override for lbl in hl._labels
            ]
            names = [lbl.name for lbl in hl._labels]
            # "ab" with "a" → ["", "a", "b"] — two non-empty.
            assert overrides == ["Custom.Thing", "Custom.Thing"]
            assert names == ["highlight", "normal"]
        finally:
            hl.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# set_text
# ──────────────────────────────────────────────────────────────────────────────


class TestSetText:
    def test_rebuild_with_different_text(self, ephemeral_window):
        """A fresh text+term pair replaces the internal label stack."""
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(text="hello", search_term="l")
            hl.set_text("demo.usda", "demo")
        try:
            assert hl.text == "demo.usda"
            assert hl.search_term == "demo"
            # "demo.usda" with "demo" → ["", "demo", ".usda", ""] →
            # two non-empty cells.
            assert len(hl._labels) == 2
            assert [lbl.text for lbl in hl._labels] == ["demo", ".usda"]
        finally:
            hl.destroy()

    def test_set_text_clearing_search(self, ephemeral_window):
        """Clearing the search term collapses to a single normal label."""
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(text="hello", search_term="l")
            hl.set_text("hello", "")
        try:
            assert len(hl._labels) == 1
            names = [lbl.name for lbl in hl._labels]
            assert names == ["normal"]
        finally:
            hl.destroy()

    def test_set_text_empty_text(self, ephemeral_window):
        """Empty text produces zero rendered labels."""
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(text="hello", search_term="l")
            hl.set_text("", "foo")
        try:
            assert hl._labels == []
        finally:
            hl.destroy()

    def test_set_text_idempotent(self, ephemeral_window):
        """Re-setting the same text+term pair keeps the label count stable."""
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(text="hello", search_term="l")
            hl.set_text("hello", "l")
            hl.set_text("hello", "l")
        try:
            # Same cells rendered as the initial build.
            assert len(hl._labels) == 4
        finally:
            hl.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Destroy
# ──────────────────────────────────────────────────────────────────────────────


class TestDestroy:
    def test_destroy_clears_refs(self, ephemeral_window):
        """Every widget ref is ``None`` after a destroy call."""
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(text="hello", search_term="l")
        hl.destroy()
        assert hl._root is None
        assert hl._hstack is None
        assert hl._labels == []

    def test_destroy_is_idempotent(self, ephemeral_window):
        """A second destroy is a silent no-op."""
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(text="hello", search_term="l")
        hl.destroy()
        hl.destroy()
        assert hl._root is None

    def test_set_text_after_destroy_is_noop(self, ephemeral_window):
        """:meth:`set_text` post-destroy does not crash and stores state."""
        with in_window_frame(ephemeral_window):
            hl = HighlightLabel(text="hello", search_term="l")
        hl.destroy()
        # No raise; the state assignment still happens (cheap and
        # harmless) but no widgets are rebuilt.
        hl.set_text("other", "ot")
        assert hl._labels == []


# ──────────────────────────────────────────────────────────────────────────────
# FileBrowserModel.text_filter property — delegate/card wiring pre-requisite
# ──────────────────────────────────────────────────────────────────────────────


class TestModelTextFilterProperty:
    def test_default_is_empty_string(self):
        """Fresh model reports no active filter."""
        from ovwidgets.app.testing.mock_backend import MockBackend
        from ovwidgets.content.widget import FileBrowserModel

        model = FileBrowserModel(MockBackend(), "mock://Home")
        try:
            assert model.text_filter == ""
        finally:
            model.destroy()

    def test_reflects_set_text_filter(self):
        """``text_filter`` reads back whatever ``set_text_filter`` wrote."""
        from ovwidgets.app.testing.mock_backend import MockBackend
        from ovwidgets.content.widget import FileBrowserModel

        model = FileBrowserModel(MockBackend(), "mock://Home")
        try:
            model.set_text_filter("demo")
            assert model.text_filter == "demo"
            model.set_text_filter("")
            assert model.text_filter == ""
        finally:
            model.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# FileCard integration — search_term ctor kwarg swaps label to HighlightLabel
# ──────────────────────────────────────────────────────────────────────────────


class TestFileCardSearchTermWiring:
    def test_card_uses_highlight_label_when_search_active(
        self, ephemeral_window,
    ):
        """Non-empty ``search_term`` routes the card label through HighlightLabel."""
        from ovwidgets.content.widget.file_card import FileCard
        from ovwidgets.content.widget.file_item import FileItem

        item = FileItem(
            url="mock://a/demo.usda", name="demo.usda", is_folder=False,
        )
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item, on_click=lambda *_: None, on_double_click=lambda: None,
                search_term="demo",
            )
        try:
            assert card._highlight_label is not None
            assert card._label is None
            # "demo.usda" with "demo" → two non-empty cells.
            assert len(card._highlight_label._labels) == 2
        finally:
            card.destroy()

    def test_card_uses_plain_label_when_no_search(self, ephemeral_window):
        """Empty / default ``search_term`` keeps the plain :class:`ui.Label`."""
        from ovwidgets.content.widget.file_card import FileCard
        from ovwidgets.content.widget.file_item import FileItem

        item = FileItem(
            url="mock://a/demo.usda", name="demo.usda", is_folder=False,
        )
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item, on_click=lambda *_: None, on_double_click=lambda: None,
            )
        try:
            assert card._highlight_label is None
            assert card._label is not None
        finally:
            card.destroy()

    def test_card_destroy_clears_highlight_label(self, ephemeral_window):
        """Card destroy tears down the HighlightLabel it owned."""
        from ovwidgets.content.widget.file_card import FileCard
        from ovwidgets.content.widget.file_item import FileItem

        item = FileItem(
            url="mock://a/demo.usda", name="demo.usda", is_folder=False,
        )
        with in_window_frame(ephemeral_window):
            card = FileCard(
                item, on_click=lambda *_: None, on_double_click=lambda: None,
                search_term="demo",
            )
        card.destroy()
        assert card._highlight_label is None

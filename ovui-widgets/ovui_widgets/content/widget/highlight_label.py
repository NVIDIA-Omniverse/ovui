# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""HighlightLabel — match-highlighted label for search results.

Step 29 (the content browser implementation step F, the content browser behavior). When the
Content Browser has an active search filter, the file / folder name in
the Name column (Step 8 :class:`FileBrowserDelegate`) and in each grid
card (Step 21 :class:`FileCard`) glows yellow on every substring match
of the search term. The rest of the name keeps the surrounding widget's
normal text colour.

Implementation mirrors Kit's ``omni.kit.widget.highlight_label``: the
widget builds an :class:`ui.HStack` of alternating :class:`ui.Label`
cells — non-match / match / non-match / match / … — and applies
``Content.HighlightLabel::highlight`` to the match cells while the
non-match cells carry ``Content.HighlightLabel::normal``. Matching is
case-insensitive on both the haystack and the needle; the original
case of the rendered name is preserved so the user reads their files
exactly as they are named on disk.

Construction builds the widget into the current ovui build context —
same contract as :class:`FileCard` and the other Step 20–28 widgets.
Callers may later call :meth:`set_text` to re-render with a different
text or search term (e.g. when the model's filter changes); the method
tears down the previous label stack and rebuilds it in place.
"""

from __future__ import annotations

from typing import List, Optional

import omni.ui as ui

# Fixed height of the rendered row. Matches the 22 px row height used
# by :class:`FileBrowserDelegate` and the 20 px label band used by
# :class:`FileCard` so the widget can stand in for either host's
# :class:`ui.Label` without changing the surrounding geometry. The
# per-use site overrides via ``height=`` when a tighter fit is needed.
_DEFAULT_HEIGHT = 22


def split_selection(
    text: str,
    selection: str,
    match_case: bool = False,
) -> List[str]:
    """Split ``text`` into alternating non-match / match segments.

    Mirrors ``omni.kit.widget.highlight_label.split_selection`` behavior:

    * ``split_selection("hello", "") == ["hello", ""]`` — no selection.
    * ``split_selection("hello", "hello") == ["", "hello"]`` — full
      match. The leading ``""`` keeps the "starts with non-match"
      invariant callers rely on.
    * ``split_selection("helloworld", "o") == ["hell", "o", "w", "o", "rld"]``
      — two matches inside a longer string.

    Invariants:

    * Even indices are non-match runs; odd indices are match runs.
    * The list always starts with a non-match cell (possibly empty when
      the match begins at position 0).
    * A trailing match-run is **not** padded with an empty tail — the
      length is even only if the final character was a non-match.
    * Empty ``text`` returns an empty list so callers can short-circuit
      the "nothing to render" case without special-casing downstream.

    Case-insensitive by default. ``match_case=True`` flips to a
    case-sensitive search. The returned segments always come from the
    original ``text`` so the user sees the name with its on-disk case
    preserved.
    """
    if not text:
        return []
    if not selection:
        return [text, ""]
    haystack = text if match_case else text.lower()
    needle = selection if match_case else selection.lower()
    needle_len = len(needle)
    if needle_len == 0:
        return [text, ""]
    result: List[str] = []
    cursor = 0
    while cursor <= len(text):
        hit = haystack.find(needle, cursor)
        if hit < 0:
            # No further matches — append the remaining tail as a
            # non-match cell and stop. When nothing has been emitted
            # yet this yields the "full string, no match" shape; when
            # at least one match has landed it yields the trailing
            # non-match run after the final match (both documented in
            # architecture §33.5).
            result.append(text[cursor:])
            break
        # Emit the non-match chunk (possibly empty when the match lands
        # at ``cursor``) followed by the match. Empty non-match chunks
        # are kept in the list so the alternation (non-match at even
        # indices, match at odd indices) stays consistent for callers
        # that address segments positionally.
        result.append(text[cursor:hit])
        result.append(text[hit:hit + needle_len])
        cursor = hit + needle_len
        if cursor == len(text):
            # Final match consumed the last character — stop here
            # without tacking on an empty trailing non-match cell so
            # the architecture's ``["", "hello"]`` shape for full
            # matches is preserved.
            break
    return result


class HighlightLabel:
    """Alternating-label match highlighter for a single text string.

    Pass the initial ``text`` and ``search_term`` to the constructor
    (either may be empty) and the widget paints itself into the
    surrounding build context. The non-match segments inherit
    ``Content.HighlightLabel::normal`` and the match segments
    ``Content.HighlightLabel::highlight`` — callers that want a
    different type-name base (e.g. to carry their own alignment /
    font-size overrides) can pass ``style_type_name_override`` which
    replaces the default ``Content.HighlightLabel`` namespace.

    :meth:`set_text` replaces the current text / search pair and
    rebuilds the internal label stack in place; use it when the host
    filter changes without rebuilding the whole containing row.
    :meth:`destroy` releases the internal refs; callers should invoke
    it on teardown so ovui's internal subscriptions drop cleanly.
    """

    # ovui variant selector: ``name`` maps to the ``::<variant>``
    # selector suffix (e.g. ``Content.HighlightLabel::highlight``).
    # Confirmed against :class:`FileBrowserDelegate`'s ``::disabled``
    # variant dispatch and the style naming rules naming rules: the
    # type name stays constant, the variant moves to the ``name``
    # attribute. Passing the full ``"Type::variant"`` string as
    # ``style_type_name_override`` is a no-op at resolution time;
    # ovui looks up the base type and then applies the variant by
    # reading the widget's ``name``.
    _NORMAL_VARIANT = "normal"
    _HIGHLIGHT_VARIANT = "highlight"

    def __init__(
        self,
        text: str = "",
        search_term: str = "",
        match_case: bool = False,
        height: int = _DEFAULT_HEIGHT,
        alignment: ui.Alignment = ui.Alignment.LEFT_CENTER,
        style_type_name_override: str = "Content.HighlightLabel",
    ) -> None:
        self._text: str = text
        self._search_term: str = search_term
        self._match_case: bool = bool(match_case)
        self._height: int = int(height)
        self._alignment = alignment
        self._style_type: str = style_type_name_override

        # Widget refs — populated by :meth:`_build`, cleared by
        # :meth:`destroy`. ``None`` pre-build / post-destroy so
        # straggling callbacks from a teardown race hit the guards.
        self._root: Optional[ui.Frame] = None
        self._hstack: Optional[ui.HStack] = None
        self._labels: List[ui.Label] = []

        self._build()

    # ── Build ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        """Build the outer Frame + inner HStack of alternating labels."""
        self._root = ui.Frame(
            height=self._height,
            style_type_name_override=self._style_type,
        )
        with self._root:
            self._hstack = ui.HStack(spacing=0)
            with self._hstack:
                self._populate_labels()

    def _populate_labels(self) -> None:
        """Emit one :class:`ui.Label` per segment and pin a trailing Spacer.

        Must be called inside a ``with self._hstack:`` block so the
        labels attach as HStack cells. Empty segments are skipped —
        painting a zero-length :class:`ui.Label` would still reserve a
        pixel of layout slack on some ovui builds and read as a thin
        gap between adjacent segments.

        A trailing :class:`ui.Spacer` consumes whatever horizontal
        space the labels do not, so the whole composite left-aligns
        inside the caller's slot — same visual contract as the
        :class:`ui.Label` it replaces (``alignment=LEFT_CENTER``
        combined with the caller's flanking :class:`ui.Spacer`).
        """
        self._labels = []
        segments = split_selection(
            self._text, self._search_term, match_case=self._match_case,
        )
        # ``split_selection`` alternates non-match / match / non-match /
        # …; even indices are non-match, odd indices are match.
        for index, segment in enumerate(segments):
            if not segment:
                continue
            is_match = (index % 2) == 1
            variant = (
                self._HIGHLIGHT_VARIANT if is_match else self._NORMAL_VARIANT
            )
            label = ui.Label(
                segment,
                word_wrap=False,
                alignment=self._alignment,
                height=self._height,
                # ``width=0`` is the omni.ui idiom for "size to
                # content" on a label — same convention
                # :class:`PathField` uses for the breadcrumb segment
                # buttons. Without it, an HStack child defaults to
                # ``Fraction(1.0)`` and every cell would stretch
                # equally regardless of glyph run length.
                width=0,
                style_type_name_override=self._style_type,
                name=variant,
            )
            self._labels.append(label)
        # Trailing flex spacer soaks up the remaining pane width so the
        # stack reads as left-aligned against the Name column / card
        # bounds rather than stretching its last label across the slot.
        ui.Spacer()

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def text(self) -> str:
        """Current rendered text (un-split)."""
        return self._text

    @property
    def search_term(self) -> str:
        """Current search term driving highlight painting."""
        return self._search_term

    @property
    def segments(self) -> List[str]:
        """Return the current alternating non-match / match split."""
        return split_selection(
            self._text, self._search_term, match_case=self._match_case,
        )

    def set_text(self, text: str, search_term: str = "") -> None:
        """Replace the text / search pair and rebuild the label stack.

        Tears down the current :class:`ui.HStack` of labels via
        :meth:`ui.HStack.clear` and re-emits a fresh set against the
        new ``text`` / ``search_term``. The outer :class:`ui.Frame`
        stays live so the caller's slot does not visibly reflow.

        Post-:meth:`destroy` this is a silent no-op — the ``None``
        guard on :attr:`_hstack` short-circuits the rebuild.
        """
        self._text = text
        self._search_term = search_term
        if self._hstack is None:
            return
        self._hstack.clear()
        self._labels = []
        with self._hstack:
            self._populate_labels()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def destroy(self) -> None:
        """Drop internal widget refs.

        Idempotent — a second call finds every ref already ``None`` and
        falls through. ovui does not provide an explicit per-label
        destroy hook; nulling the Python refs is sufficient because the
        containing :class:`ui.Frame` owns the C++ widget tree and
        collapses it when its own ref is released by the caller's
        build-context teardown.
        """
        self._labels = []
        self._hstack = None
        self._root = None

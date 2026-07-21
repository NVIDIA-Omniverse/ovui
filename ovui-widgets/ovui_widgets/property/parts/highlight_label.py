# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Label widget that renders search-match substrings in an accent colour.

highlight-label behavior / the property inspector behavior Step 7.1 of
the property inspector implementation. A :class:`HighlightLabel` replaces the plain
:class:`ui.Label` each attribute row builds in its label slot: when the
Property Window's filter text is a case-insensitive substring of the
attribute's ``display_name``, the matching portion(s) render with the
``Property.LabelColumn::highlight`` state selector (an accent colour from
the theme) while the non-matching portions keep the normal
``Property.LabelColumn`` colour. When the filter is empty or does not
match, the widget behaves identically to a single :class:`ui.Label`
— no wrapper :class:`ui.HStack` is introduced, so the layout output is
byte-identical to the pre-7.1 render for the unfiltered case.

Multiple occurrences are all highlighted: a filter of ``"e"`` against
``"Subdivision Scheme"`` produces three highlighted ``"e"`` runs
separated by two plain runs, not just the first.

The widget exposes the three attributes the existing row-test surface
pins on (``.name``, ``.style_type_name_override``, ``.text``) as proxy
properties forwarded to the first (primary) underlying label. That
keeps ``tests/test_attribute_rows.py``'s regression guards
(``row._label.name == "not_authored"``, etc.) passing unchanged — the
Step 4.2 ``::not_authored`` state selector still attaches to the primary
label's ``name`` field.
"""

from __future__ import annotations

from typing import Any, List, Tuple

import omni.ui as ui

# ---------------------------------------------------------------------------
# Pure helper — segment computation
# ---------------------------------------------------------------------------


def _compute_segments(text: str, match: str) -> List[Tuple[str, bool]]:
    """Split ``text`` into alternating (segment, is_match) runs.

    Case-insensitive — matches are detected by lower-casing both ``text``
    and ``match`` before searching, but the returned segments preserve
    the original casing of ``text`` (so ``"Intensity"`` highlighted with
    ``"in"`` still renders the leading capital ``"I"`` in the match run).

    Empty-match and no-match both collapse to a single non-match run
    carrying the full ``text`` — the caller treats this as "equivalent
    to a plain label" and skips the multi-label path.

    Multiple occurrences all surface as separate match runs; a filter
    of ``"e"`` against ``"Subdivision Scheme"`` produces
    ``[("Subdivision Sch", False), ("e", True), ("m", False), ("e", True)]``
    (two matches, three plain runs). Overlapping matches don't happen —
    the function advances past each match by ``len(match)`` so a filter
    of ``"aa"`` against ``"aaaa"`` yields two non-overlapping matches.

    Pure function; no ovui dependency — testable without a ui context.
    """
    if not match:
        return [(text, False)]
    lower_text = text.lower()
    lower_match = match.lower()
    match_len = len(lower_match)
    segments: List[Tuple[str, bool]] = []
    cursor = 0
    while cursor < len(text):
        idx = lower_text.find(lower_match, cursor)
        if idx < 0:
            segments.append((text[cursor:], False))
            break
        if idx > cursor:
            segments.append((text[cursor:idx], False))
        segments.append((text[idx:idx + match_len], True))
        cursor = idx + match_len
    if not segments:
        return [(text, False)]
    return segments


# ---------------------------------------------------------------------------
# HighlightLabel widget
# ---------------------------------------------------------------------------


_HIGHLIGHT_STATE_NAME = "highlight"


class HighlightLabel:
    """Label wrapper that highlights search-match substrings.

    Constructs child :class:`ui.Label` widgets in the ambient ovui
    scope (same scope a plain ``ui.Label(...)`` call would use). When
    ``match`` is empty or does not appear in ``text``, exactly one
    :class:`ui.Label` is built — identical to a plain-label render, so
    the widget carries zero layout cost when the filter is empty. When
    one or more matches exist, the widget wraps its segment labels
    inside an :class:`ui.HStack` so the segments appear inline; the
    outer ``width`` kwarg goes on the HStack while non-layout kwargs
    (``style_type_name_override``, ``name``, etc.) flow through to each
    segment.

    The ``name`` kwarg (used by the row code to drive the
    ``::not_authored`` state selector via ``"not_authored"``) is applied
    verbatim to every non-match segment; match segments override it
    with ``"highlight"`` so the ``Property.LabelColumn::highlight``
    state selector fires. An attribute that is both unauthored *and*
    has a filter match shows the highlight colour for the match runs
    and the not-authored (muted) colour for the surrounding runs —
    highlight-wins-on-match rather than stacking the two states, which
    omni.ui's single-name state selector can't express anyway.

    Proxy attributes:

    * ``.name`` — the first (primary) label's ``name``. In the no-match
      case that's the whole label; in the match case it's the first
      non-match or match run, whichever appears first in ``text``.
    * ``.style_type_name_override`` — same delegation.
    * ``.text`` — always the original (unsplit) ``text`` argument, not
      the first label's ``.text``; callers asserting the rendered
      string should see the full display_name, not just the first
      segment.
    """

    def __init__(
        self,
        text: str,
        match: str = "",
        *,
        width: Any = None,
        style_type_name_override: str = "Property.LabelColumn",
        name: str = "",
        **label_kwargs: Any,
    ) -> None:
        """Build the label(s) in the current ovui scope.

        ``width`` is applied to the outer container (the single label
        in the no-match case; the wrapping ``ui.HStack`` in the match
        case). Extra keyword arguments are forwarded to every child
        :class:`ui.Label` — callers can pass ``tooltip`` /
        ``alignment`` / etc. the same way they would to a plain label.
        """
        self._text = text
        self._match = match
        self._segments = _compute_segments(text, match)
        self._labels: List[ui.Label] = []
        self._container: Any = None
        self._style_type = style_type_name_override
        self._name = name
        self._width = width
        self._label_kwargs = label_kwargs
        self._has_matches = any(is_match for _, is_match in self._segments)
        self._build_ui()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Emit ``ui.Label`` widgets into the ambient ovui scope.

        No-match path: a single label with the outer ``width`` applied
        so the pre-7.1 layout is preserved byte-for-byte.

        Match path: an outer ``ui.HStack`` (claiming the outer
        ``width``) with one label per segment plus a trailing
        :class:`ui.Spacer`. The Spacer is critical — an HStack with
        no sized children distributes its width evenly, which would
        insert visible gaps between the match and non-match segments;
        pinning each segment to the natural text width and letting
        the Spacer absorb the remainder packs the segments tightly
        against the left edge and visually matches the pre-7.1
        single-label output. Each segment is sized with
        :class:`ui.Pixel` width from its rendered text extent so the
        runs hug each other with zero internal spacing.

        Match segments set ``name="highlight"`` so the
        ``Property.LabelColumn::highlight`` selector paints the
        accent colour; non-match segments inherit the row-level
        ``name`` (usually ``""`` or ``"not_authored"``). Every segment
        carries the same ``style_type_name_override`` so a single
        theme entry drives the whole label row.
        """
        if not self._has_matches:
            self._container = self._make_label(
                self._text, self._name, apply_width=True
            )
            self._labels = [self._container]
            return
        stack_kwargs: dict = {"spacing": 0}
        if self._width is not None:
            stack_kwargs["width"] = self._width
        self._container = ui.HStack(**stack_kwargs)
        with self._container:
            for segment_text, is_match in self._segments:
                segment_name = _HIGHLIGHT_STATE_NAME if is_match else self._name
                self._labels.append(
                    self._make_label(segment_text, segment_name, apply_width=False)
                )
            ui.Spacer()

    def _make_label(self, text: str, name: str, apply_width: bool) -> ui.Label:
        """Construct one child :class:`ui.Label` with the shared kwargs.

        ``apply_width`` is True only for the no-match single-label case
        — in the match case the width lives on the wrapping
        ``ui.HStack`` and each segment sizes to its text content so
        segments pack inline.
        """
        kwargs = dict(self._label_kwargs)
        kwargs["style_type_name_override"] = self._style_type
        kwargs["name"] = name
        if apply_width and self._width is not None:
            kwargs["width"] = self._width
        return ui.Label(text, **kwargs)

    # ------------------------------------------------------------------
    # Proxy attributes — keep pre-7.1 row-test assertions working
    # ------------------------------------------------------------------

    @property
    def text(self) -> str:
        """The original, unsplit display text."""
        return self._text

    @property
    def name(self) -> str:
        """State name of the primary (first) label.

        Matches the pre-7.1 ``ui.Label.name`` surface so
        ``tests/test_attribute_rows.py`` regressions on
        ``row._label.name`` still fire.
        """
        if not self._labels:
            return self._name
        return self._labels[0].name

    @property
    def style_type_name_override(self) -> str:
        """Style type of the primary label (``Property.LabelColumn``)."""
        if not self._labels:
            return self._style_type
        return self._labels[0].style_type_name_override

    @property
    def labels(self) -> List[ui.Label]:
        """Ordered list of child labels — one per segment.

        Tests use this to inspect per-segment text / state without
        depending on the match/no-match container-type difference
        (single label vs. HStack wrapper).
        """
        return list(self._labels)

    @property
    def segments(self) -> List[Tuple[str, bool]]:
        """Computed ``[(text, is_match), ...]`` tuples for the label.

        Exposed so tests can assert segmentation without depending on
        omni.ui widget construction. The list always has at least one
        entry: the no-match case returns a single ``(text, False)``
        tuple.
        """
        return list(self._segments)

    @property
    def has_matches(self) -> bool:
        """Whether at least one match-segment was produced."""
        return self._has_matches

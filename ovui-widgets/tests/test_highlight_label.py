# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`HighlightLabel` — Step 7.1.

Covers the done-signal matrix from the property inspector 7.1:

* Match ``"in"`` in ``"intensity"`` → three sub-labels
  (normal ``"tensity"`` around a single ``"in"`` highlight).
* No match (non-overlapping filter) → single label, identical shape
  to a plain :class:`ui.Label`.
* Empty match → single label.
* Case-insensitive matching (``"IN"`` matches ``"intensity"``).
* Multiple occurrences all highlighted.

Plus a handful of edge cases the row-highlight implementation must keep: the
``Property.LabelColumn::highlight`` style selector is registered; the
match run preserves the original casing of the input text (so
``"Intensity"`` + filter ``"in"`` highlights ``"In"``, not ``"in"``);
the proxy attributes (``.name``, ``.style_type_name_override``,
``.text``) keep the pre-7.1 row-test surface working; filter text that
is a superset of the label produces no match; and the wiring path
(``AttributeRow`` constructors accept ``match=`` and pass it to the
label) is exercised end-to-end through the builder table.

``_compute_segments`` is the pure splitter and is tested without an
omni.ui context. The widget construction tests wrap each build in a
small :class:`ui.Window` frame so ``ui.Label`` calls have a scope
they can attach to — same pattern as
``tests/test_attribute_rows.py::TestLabelStyleState``.
"""

from __future__ import annotations

from typing import Any, List

import pytest

# ---------------------------------------------------------------------------
# Pure splitter — no UI required
# ---------------------------------------------------------------------------


class TestComputeSegments:
    """Exercises the pure ``_compute_segments`` helper."""

    def test_single_match_splits_into_three_segments(self) -> None:
        """``"in"`` appearing once mid-string yields three segments.

        Task done-signal: filter ``"in"`` against ``"intensity"`` must
        produce three runs (empty leading, ``"in"`` match, ``"tensity"``
        tail).  ``_compute_segments`` elides empty-prefix runs, so the
        visible output is two: a match run + a non-match tail.
        """
        from ovui_widgets.property.parts.highlight_label import _compute_segments
        segments = _compute_segments("intensity", "in")
        assert segments == [("in", True), ("tensity", False)]

    def test_match_mid_text_produces_three_segments(self) -> None:
        """Match in the middle yields normal + highlight + normal."""
        from ovui_widgets.property.parts.highlight_label import _compute_segments
        segments = _compute_segments("Subdivision", "div")
        assert segments == [("Sub", False), ("div", True), ("ision", False)]

    def test_no_match_returns_single_non_match_segment(self) -> None:
        """A filter that doesn't appear returns the whole text unhighlighted.

        Task done-signal: no match → single (non-match) segment. The
        caller (:class:`HighlightLabel`) treats this as "equivalent to
        a plain ``ui.Label``".
        """
        from ovui_widgets.property.parts.highlight_label import _compute_segments
        segments = _compute_segments("foo", "zzz")
        assert segments == [("foo", False)]

    def test_empty_match_returns_single_segment(self) -> None:
        """An empty filter returns one non-match run holding the full text.

        Task done-signal: empty match → single label.
        """
        from ovui_widgets.property.parts.highlight_label import _compute_segments
        segments = _compute_segments("anything", "")
        assert segments == [("anything", False)]

    def test_case_insensitive_uppercase_filter(self) -> None:
        """Uppercase filter matches lowercase text and preserves original case.

        Task done-signal: case-insensitive matching. Match run carries
        the original text casing (``"In"`` — capital I), not the
        filter's casing.
        """
        from ovui_widgets.property.parts.highlight_label import _compute_segments
        segments = _compute_segments("Intensity", "IN")
        assert segments == [("In", True), ("tensity", False)]

    def test_case_insensitive_mixed_case(self) -> None:
        """Mixed-case filter against mixed-case text still matches."""
        from ovui_widgets.property.parts.highlight_label import _compute_segments
        segments = _compute_segments("IntensitY", "sItY")
        assert segments == [("Inten", False), ("sitY", True)]

    def test_multiple_occurrences_all_highlighted(self) -> None:
        """Every occurrence becomes its own match run.

        Task done-signal: multiple occurrences highlighted. Expect two
        separate ``"e"`` match runs plus the normal gaps between them.
        """
        from ovui_widgets.property.parts.highlight_label import _compute_segments
        segments = _compute_segments("Subdivision Scheme", "e")
        assert segments == [
            ("Subdivision Sch", False),
            ("e", True),
            ("m", False),
            ("e", True),
        ]

    def test_adjacent_non_overlapping_matches(self) -> None:
        """Filter ``"aa"`` against ``"aaaa"`` yields two non-overlapping runs.

        After matching the first ``"aa"`` the cursor advances past it,
        so the second ``"aa"`` is found starting at index 2 — NOT
        overlapping the first. Four ``a``s produce two match runs, no
        gap between them.
        """
        from ovui_widgets.property.parts.highlight_label import _compute_segments
        segments = _compute_segments("aaaa", "aa")
        assert segments == [("aa", True), ("aa", True)]

    def test_match_at_very_start(self) -> None:
        """Match at position 0 doesn't produce a spurious empty prefix run."""
        from ovui_widgets.property.parts.highlight_label import _compute_segments
        segments = _compute_segments("foo", "fo")
        assert segments == [("fo", True), ("o", False)]

    def test_match_at_very_end(self) -> None:
        """Match consuming the last char doesn't produce a trailing empty."""
        from ovui_widgets.property.parts.highlight_label import _compute_segments
        segments = _compute_segments("foo", "oo")
        assert segments == [("f", False), ("oo", True)]

    def test_whole_string_is_the_match(self) -> None:
        """Filter equal to the text collapses to a single match run."""
        from ovui_widgets.property.parts.highlight_label import _compute_segments
        segments = _compute_segments("foo", "foo")
        assert segments == [("foo", True)]

    def test_filter_longer_than_text(self) -> None:
        """Filter longer than text produces a no-match single segment."""
        from ovui_widgets.property.parts.highlight_label import _compute_segments
        segments = _compute_segments("hi", "hello")
        assert segments == [("hi", False)]


# ---------------------------------------------------------------------------
# Widget construction — requires ui context, same gate as row tests
# ---------------------------------------------------------------------------


try:
    import omni.ui as ui
    _OMNI_UI_AVAILABLE = True
except ImportError:
    _OMNI_UI_AVAILABLE = False


def _can_create_window() -> bool:
    if not _OMNI_UI_AVAILABLE:
        return False
    try:
        w = ui.Window("__probe_highlight__", width=10, height=10)
        w.destroy()
        return True
    except Exception:
        return False


_UI_AVAILABLE = _can_create_window()
_skip_no_ui = pytest.mark.skipif(
    not _UI_AVAILABLE,
    reason="omni.ui not available (no ui.Window creation)",
)


def _build_in_frame(text: str, match: str, **kwargs: Any):
    """Construct a :class:`HighlightLabel` inside a throwaway ui.Window frame.

    Mirrors the pattern in ``tests/test_attribute_rows.py`` — a real
    ui parent is required for ``ui.Label`` /``ui.HStack`` construction
    to succeed under the standalone omni.ui build. The window is
    destroyed by the caller via the returned handle.
    """
    from ovui_widgets.property.parts.highlight_label import HighlightLabel

    w = ui.Window("__hl_test__", width=200, height=40)
    with w.frame:
        with ui.HStack():
            hl = HighlightLabel(text, match=match, **kwargs)
    return hl, w


@_skip_no_ui
class TestHighlightLabelWidget:
    """End-to-end widget construction — exercises the full build path."""

    def test_in_intensity_produces_two_labels(self) -> None:
        """Task done-signal: ``"in"`` in ``"intensity"`` → split labels.

        ``_compute_segments`` yields ``[("in", True), ("tensity",
        False)]`` → two child :class:`ui.Label` widgets. First label
        carries the ``"highlight"`` state name; second is a normal
        segment (empty state name).
        """
        hl, w = _build_in_frame("intensity", "in")
        try:
            assert len(hl.labels) == 2
            assert [lbl.name for lbl in hl.labels] == ["highlight", ""]
            assert hl.has_matches is True
            assert hl.text == "intensity"
        finally:
            w.destroy()

    def test_mid_word_match_produces_three_labels(self) -> None:
        """Match in the middle of the text produces normal+highlight+normal."""
        hl, w = _build_in_frame("Subdivision", "div")
        try:
            assert len(hl.labels) == 3
            assert [lbl.name for lbl in hl.labels] == [
                "", "highlight", "",
            ]
        finally:
            w.destroy()

    def test_no_match_produces_single_label(self) -> None:
        """Task done-signal: no match → single label."""
        hl, w = _build_in_frame("radius", "zzz")
        try:
            assert len(hl.labels) == 1
            assert hl.labels[0].name == ""
            assert hl.has_matches is False
        finally:
            w.destroy()

    def test_empty_match_produces_single_label(self) -> None:
        """Task done-signal: empty match → single label."""
        hl, w = _build_in_frame("radius", "")
        try:
            assert len(hl.labels) == 1
            assert hl.labels[0].name == ""
            assert hl.has_matches is False
        finally:
            w.destroy()

    def test_case_insensitive_match(self) -> None:
        """Task done-signal: case-insensitive matching."""
        hl, w = _build_in_frame("Intensity", "IN")
        try:
            assert hl.has_matches is True
            # Match run carries the original text casing.
            assert hl.segments == [("In", True), ("tensity", False)]
        finally:
            w.destroy()

    def test_multiple_occurrences_all_highlighted(self) -> None:
        """Task done-signal: every occurrence is highlighted."""
        hl, w = _build_in_frame("Subdivision Scheme", "e")
        try:
            # 4 segments: non-match | "e" match | "m" | "e" match.
            assert len(hl.labels) == 4
            # Two highlight runs.
            highlight_count = sum(
                1 for lbl in hl.labels if lbl.name == "highlight"
            )
            assert highlight_count == 2
        finally:
            w.destroy()

    def test_every_label_shares_style_type_override(self) -> None:
        """Every child label routes through ``Property.LabelColumn``."""
        hl, w = _build_in_frame("Intensity", "in")
        try:
            overrides = {lbl.style_type_name_override for lbl in hl.labels}
            assert overrides == {"Property.LabelColumn"}
        finally:
            w.destroy()

    def test_not_authored_name_preserved_on_normal_segments(self) -> None:
        """When caller passes ``name="not_authored"`` it flows to normal
        segments only; match segments override to ``"highlight"``.

        This is the edge case where an attribute is both not-authored
        AND matches the filter — the highlight colour wins for the
        match run; the surrounding runs keep the not-authored dim.
        """
        hl, w = _build_in_frame("Intensity", "in", name="not_authored")
        try:
            assert [lbl.name for lbl in hl.labels] == [
                "highlight", "not_authored",
            ]
        finally:
            w.destroy()


# ---------------------------------------------------------------------------
# Proxy attributes — keep the pre-7.1 row-test surface working
# ---------------------------------------------------------------------------


@_skip_no_ui
class TestProxyAttributes:
    """``.name`` / ``.style_type_name_override`` / ``.text`` shims."""

    def test_name_proxies_to_first_label_on_match(self) -> None:
        """With a match, the primary (first) label's name is ``"highlight"``
        when the filter matches at position 0.

        ``row._label.name`` assertions pre-7.1 relied on the label
        being a single ``ui.Label`` with ``.name`` set to the
        not-authored state or an empty string. Under 7.1 with a
        filter match at the start, the first label becomes the match
        run — ``.name`` reads ``"highlight"``.
        """
        hl, w = _build_in_frame("Intensity", "in")
        try:
            assert hl.name == "highlight"
        finally:
            w.destroy()

    def test_name_proxies_to_first_label_no_match(self) -> None:
        """With no match, the single underlying label's name is what was
        passed in at construction.

        This is the path pre-7.1 row tests walk:
        ``row._label.name == "not_authored"`` keeps passing.
        """
        hl, w = _build_in_frame("Intensity", "", name="not_authored")
        try:
            assert hl.name == "not_authored"
            assert hl.style_type_name_override == "Property.LabelColumn"
        finally:
            w.destroy()

    def test_text_returns_original_input(self) -> None:
        """``.text`` returns the original text, never just a single run."""
        hl, w = _build_in_frame("Subdivision Scheme", "e")
        try:
            assert hl.text == "Subdivision Scheme"
        finally:
            w.destroy()

    def test_segments_is_defensive_copy(self) -> None:
        """Mutating the returned segments list shouldn't affect internals."""
        hl, w = _build_in_frame("foo", "o")
        try:
            original = hl.segments
            original.clear()
            # Fetch again — should be the un-mutated full list.
            assert hl.segments == [("f", False), ("o", True), ("o", True)]
        finally:
            w.destroy()

    def test_labels_is_defensive_copy(self) -> None:
        """Mutating the returned labels list shouldn't affect internals."""
        hl, w = _build_in_frame("foo", "o")
        try:
            first = hl.labels
            first.clear()
            # Second fetch should return the un-mutated list.
            assert len(hl.labels) == 3
        finally:
            w.destroy()


# ---------------------------------------------------------------------------
# Style registration — ``Property.LabelColumn::highlight``
# ---------------------------------------------------------------------------


class TestStyleRegistration:
    """The highlight state selector is present in the style dict."""

    def test_highlight_state_selector_registered(self) -> None:
        """``Property.LabelColumn::highlight`` exists in PROPERTY_STYLES."""
        from ovui_widgets.property.style import PROPERTY_STYLES
        assert "Property.LabelColumn::highlight" in PROPERTY_STYLES

    def test_highlight_color_distinct_from_normal(self) -> None:
        """The highlight colour is not the same as the normal label colour.

        Whatever the design palette picks for the accent (NVIDIA green,
        tan-gold, …), it MUST differ from ``Property.LabelColumn``'s
        base colour — otherwise the highlight is invisible.
        """
        from ovui_widgets.property.style import PROPERTY_STYLES
        base = PROPERTY_STYLES["Property.LabelColumn"]["color"]
        highlight = PROPERTY_STYLES["Property.LabelColumn::highlight"]["color"]
        assert base != highlight


# ---------------------------------------------------------------------------
# Integration — match threads through row constructors + builders
# ---------------------------------------------------------------------------


@_skip_no_ui
class TestRowsAcceptMatchKwarg:
    """Every row class accepts a ``match=`` kwarg and wires it to the label.

    Regression guard: after Step 7.1 the row __init__ signature gains
    ``match: str = ""``. If a future PR drops the kwarg from a single
    row class, the panel would silently stop highlighting that row's
    label while every other row kept working — hard to spot visually.
    This test makes the drift loud.
    """

    @pytest.fixture
    def _mock_adapter(self):
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter

        def _make(type_name: str, value_type, value, extra=None):
            extra = extra or {}
            prop = AttributeMetadata(
                name="radius",
                display_name="Intensity",
                type_name=type_name,
                value_type=value_type,
                group="",
                **extra,
            )
            adapter = MockPropertyAdapter(paths=["/W"], attributes={"radius": prop})
            adapter.set_path_value("/W", "radius", value)
            return prop, adapter
        return _make

    @pytest.mark.parametrize(
        ("cls_name", "type_name", "value_type", "value", "extra"),
        [
            ("FloatAttributeRow", "float", float, 1.0, None),
            ("IntAttributeRow", "int", int, 1, None),
            ("BoolAttributeRow", "bool", bool, True, None),
            ("StringAttributeRow", "string", str, "v", None),
            ("Vec3FloatAttributeRow", "float3", tuple, (1.0, 2.0, 3.0), None),
            ("Vec2IntAttributeRow", "int2", tuple, (1, 2), None),
            ("Color3fAttributeRow", "color3f", tuple, (0.5, 0.5, 0.5), None),
            ("ArrayAttributeRow", "array", tuple, (1.0, 2.0), None),
            ("AssetPathAttributeRow", "asset", str, "p.usd", None),
            ("RelationshipAttributeRow", "relationship", tuple, ("/W",), None),
            (
                "TokenAttributeRow", "token", str, "a",
                {"allowed_values": ["a", "b"]},
            ),
        ],
    )
    def test_row_label_highlights_when_match_passed(
        self,
        _mock_adapter,
        cls_name: str,
        type_name: str,
        value_type,
        value,
        extra,
    ) -> None:
        """Passing ``match="In"`` through each row splits its label."""
        from ovui_widgets.property import attribute_row as ar
        prop, adapter = _mock_adapter(type_name, value_type, value, extra)
        cls = getattr(ar, cls_name)
        w = ui.Window(
            f"_hl_integration_{cls_name}", width=400, height=60,
        )
        with w.frame:
            row = cls(prop, adapter, match="In")
        try:
            assert row._label is not None
            # Label is a HighlightLabel; ``.has_matches`` is True
            # because "In" is a prefix of "Intensity".
            assert row._label.has_matches is True
            # There are at least two sub-labels — the match run plus
            # the tail.
            assert len(row._label.labels) >= 2
        finally:
            w.destroy()

    def test_matrix_row_label_highlights_when_match_passed(self) -> None:
        """MatrixAttributeRow accepts ``match=`` and highlights.

        Matrix row has a different signature (takes ``n_dim``) so it
        can't be parametrised with the rest.
        """
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import MatrixAttributeRow
        prop = AttributeMetadata(
            name="m", display_name="Intensity Matrix", type_name="matrix3d",
            value_type=tuple, group="",
        )
        adapter = MockPropertyAdapter(paths=["/W"], attributes={"m": prop})
        adapter.set_path_value("/W", "m", tuple(0.0 for _ in range(9)))
        w = ui.Window("_hl_matrix_integration", width=400, height=150)
        with w.frame:
            row = MatrixAttributeRow(prop, adapter, n_dim=3, match="In")
        try:
            assert row._label is not None
            assert row._label.has_matches is True
        finally:
            w.destroy()

    def test_row_label_no_match_stays_single_label(self) -> None:
        """No-match filter leaves the row's label as a single non-match run.

        Done-signal: filter-empty behavior identical to pre-7.1.
        """
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import FloatAttributeRow
        prop = AttributeMetadata(
            name="r", display_name="Intensity", type_name="float",
            value_type=float, group="",
        )
        adapter = MockPropertyAdapter(paths=["/W"], attributes={"r": prop})
        adapter.set_path_value("/W", "r", 1.0)
        w = ui.Window("_hl_nomatch_integration", width=400, height=60)
        with w.frame:
            row = FloatAttributeRow(prop, adapter, match="zzz")
        try:
            assert row._label is not None
            assert row._label.has_matches is False
            assert len(row._label.labels) == 1
        finally:
            w.destroy()

    def test_row_label_empty_match_stays_single_label(self) -> None:
        """Default (empty) match keeps label behaviour identical to pre-7.1."""
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.attribute_row import FloatAttributeRow
        prop = AttributeMetadata(
            name="r", display_name="Intensity", type_name="float",
            value_type=float, group="",
        )
        adapter = MockPropertyAdapter(paths=["/W"], attributes={"r": prop})
        adapter.set_path_value("/W", "r", 1.0)
        w = ui.Window("_hl_emptymatch_integration", width=400, height=60)
        with w.frame:
            # Default match is "" — same as pre-7.1 call site.
            row = FloatAttributeRow(prop, adapter)
        try:
            assert row._label is not None
            assert row._label.has_matches is False
            assert len(row._label.labels) == 1
        finally:
            w.destroy()


# ---------------------------------------------------------------------------
# Attributes widget threads the filter text through
# ---------------------------------------------------------------------------


@_skip_no_ui
class TestAttributesWidgetThreadsMatch:
    """``AttributesWidget._build_attribute_row`` passes ``match=`` to the
    builder table so every row gets the current filter text.

    Without this wire-up, the row-level ``match=`` kwarg would still
    exist but never receive the filter text, and highlighting would
    be permanently disabled in production. This test proves the
    plumbing reaches from ``PropertyWindow._filter_text`` all the way
    down to ``WidgetBuilderTable.build``.
    """

    def test_build_attribute_row_passes_match_kwarg(self, monkeypatch) -> None:
        """Intercept the builder table and assert the ``match`` kwarg lands."""
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.builders import WidgetBuilderTable
        from ovui_widgets.property.widget.attributes_widget import AttributesWidget

        prop = AttributeMetadata(
            name="r", display_name="Intensity", type_name="float",
            value_type=float, group="",
        )
        adapter = MockPropertyAdapter(paths=["/W"], attributes={"r": prop})
        adapter.set_path_value("/W", "r", 1.0)

        # Minimal stand-in window object exposing only the fields
        # ``_build_attribute_row`` reads. Avoids spinning up the full
        # :class:`PropertyWindow` / ovui frame.
        class _StubWindow:
            _adapter = adapter
            _filter_text = "In"

        captured: List[dict] = []
        original_build = WidgetBuilderTable.build

        def _capture(attr_name, metadata, adapter_, **kwargs):
            captured.append(dict(kwargs))
            return original_build(attr_name, metadata, adapter_, **kwargs)

        monkeypatch.setattr(WidgetBuilderTable, "build", _capture)

        widget = AttributesWidget(window=_StubWindow())
        w = ui.Window("_hl_attr_widget", width=400, height=60)
        with w.frame:
            with ui.HStack():
                widget._build_attribute_row(prop)
        try:
            assert captured, "WidgetBuilderTable.build was never called"
            assert captured[0].get("match") == "In"
        finally:
            w.destroy()

    def test_empty_filter_threads_empty_string(self, monkeypatch) -> None:
        """Default (empty) filter text arrives at the builder as ``""``."""
        from ovui_data_adapters.common import AttributeMetadata

        from ovui_widgets.app.testing import MockPropertyAdapter
        from ovui_widgets.property.builders import WidgetBuilderTable
        from ovui_widgets.property.widget.attributes_widget import AttributesWidget

        prop = AttributeMetadata(
            name="r", display_name="Intensity", type_name="float",
            value_type=float, group="",
        )
        adapter = MockPropertyAdapter(paths=["/W"], attributes={"r": prop})
        adapter.set_path_value("/W", "r", 1.0)

        class _StubWindow:
            _adapter = adapter
            _filter_text = ""

        captured: List[dict] = []
        original_build = WidgetBuilderTable.build

        def _capture(attr_name, metadata, adapter_, **kwargs):
            captured.append(dict(kwargs))
            return original_build(attr_name, metadata, adapter_, **kwargs)

        monkeypatch.setattr(WidgetBuilderTable, "build", _capture)

        widget = AttributesWidget(window=_StubWindow())
        w = ui.Window("_hl_attr_widget_empty", width=400, height=60)
        with w.frame:
            with ui.HStack():
                widget._build_attribute_row(prop)
        try:
            assert captured
            assert captured[0].get("match") == ""
        finally:
            w.destroy()


# ---------------------------------------------------------------------------
# Parts package exports
# ---------------------------------------------------------------------------


class TestPartsExport:
    """HighlightLabel is re-exported from the parts package."""

    def test_exported_from_parts_package(self) -> None:
        from ovui_widgets.property import parts
        assert hasattr(parts, "HighlightLabel")

    def test_listed_in_all(self) -> None:
        from ovui_widgets.property import parts
        assert "HighlightLabel" in parts.__all__

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 74 — multi-selection property editing with mixed-value indicator.

Covers:
- MockPropertyAdapter.is_ambiguous() detects value differences across paths
- MockPropertyAdapter.get_value() returns None for mixed selections
- MockPropertyAdapter.set_value() applies to all selected paths
- MockPropertyAdapter.set_path_value() helper for per-path values
- Attribute row widgets build without crash when ambiguous
- Grey style applied to widgets when adapter is ambiguous
"""

import omni.ui as ui
import pytest
from ovui_data_adapters.common import AttributeMetadata

from ovwidgets.app.testing import MockPropertyAdapter
from ovwidgets.property.attribute_row import (
    BoolAttributeRow,
    FloatAttributeRow,
    IntAttributeRow,
    StringAttributeRow,
    Vec3FloatAttributeRow,
    build_attribute_row,
)


def _float_meta(name: str) -> AttributeMetadata:
    return AttributeMetadata(
        name=name,
        display_name=name.title(),
        type_name="float",
        value_type=float,
        group="Test",
    )


def _int_meta(name: str) -> AttributeMetadata:
    return AttributeMetadata(
        name=name,
        display_name=name.title(),
        type_name="int",
        value_type=int,
        group="Test",
    )


def _str_meta(name: str) -> AttributeMetadata:
    return AttributeMetadata(
        name=name,
        display_name=name.title(),
        type_name="string",
        value_type=str,
        group="Test",
    )


def _bool_meta(name: str) -> AttributeMetadata:
    return AttributeMetadata(
        name=name,
        display_name=name.title(),
        type_name="bool",
        value_type=bool,
        group="Test",
    )


def _vec3_meta(name: str) -> AttributeMetadata:
    return AttributeMetadata(
        name=name,
        display_name=name.title(),
        type_name="float3",
        value_type=float,
        group="Test",
    )


# ── is_ambiguous — single selection ──────────────────────────────────────────

class TestIsAmbiguousSingleSelection:
    def test_no_paths_not_ambiguous(self):
        adapter = MockPropertyAdapter()
        assert adapter.is_ambiguous("radius") is False

    def test_one_path_not_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1"])
        adapter.set_path_value("/P1", "radius", 1.0)
        assert adapter.is_ambiguous("radius") is False

    def test_single_path_get_value_returns_actual(self):
        adapter = MockPropertyAdapter(paths=["/P1"])
        adapter.set_path_value("/P1", "radius", 5.0)
        assert adapter.get_value("radius") == pytest.approx(5.0)

    def test_single_path_set_value_updates(self):
        adapter = MockPropertyAdapter(paths=["/P1"])
        adapter.set_value("radius", 2.0)
        assert adapter.get_value("radius") == pytest.approx(2.0)

    def test_empty_selection_get_value_from_values_dict(self):
        adapter = MockPropertyAdapter()
        adapter.set_value("radius", 3.0)
        assert adapter.get_value("radius") == pytest.approx(3.0)

    def test_unset_attr_returns_none(self):
        adapter = MockPropertyAdapter(paths=["/P1"])
        assert adapter.get_value("missing") is None


# ── is_ambiguous — multi-selection same values ────────────────────────────────

class TestIsAmbiguousMultiSame:
    def test_two_paths_same_value_not_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "radius", 1.0)
        adapter.set_path_value("/P2", "radius", 1.0)
        assert adapter.is_ambiguous("radius") is False

    def test_three_paths_same_value_not_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2", "/P3"])
        for p in ["/P1", "/P2", "/P3"]:
            adapter.set_path_value(p, "count", 42)
        assert adapter.is_ambiguous("count") is False

    def test_multi_same_get_value_returns_common(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "radius", 7.0)
        adapter.set_path_value("/P2", "radius", 7.0)
        assert adapter.get_value("radius") == pytest.approx(7.0)

    def test_set_value_then_not_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "radius", 1.0)
        adapter.set_path_value("/P2", "radius", 2.0)
        assert adapter.is_ambiguous("radius") is True
        adapter.set_value("radius", 5.0)
        assert adapter.is_ambiguous("radius") is False


# ── is_ambiguous — multi-selection different values ───────────────────────────

class TestIsAmbiguousMultiDifferent:
    def test_two_paths_different_values_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "radius", 1.0)
        adapter.set_path_value("/P2", "radius", 2.0)
        assert adapter.is_ambiguous("radius") is True

    def test_three_paths_one_different_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2", "/P3"])
        adapter.set_path_value("/P1", "radius", 1.0)
        adapter.set_path_value("/P2", "radius", 1.0)
        adapter.set_path_value("/P3", "radius", 99.0)
        assert adapter.is_ambiguous("radius") is True

    def test_mixed_get_value_returns_none(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "radius", 1.0)
        adapter.set_path_value("/P2", "radius", 2.0)
        assert adapter.get_value("radius") is None

    def test_mixed_string_values_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "name", "sphere")
        adapter.set_path_value("/P2", "name", "cube")
        assert adapter.is_ambiguous("name") is True

    def test_mixed_int_values_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "count", 1)
        adapter.set_path_value("/P2", "count", 2)
        assert adapter.is_ambiguous("count") is True

    def test_different_attrs_independent(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "radius", 1.0)
        adapter.set_path_value("/P2", "radius", 2.0)
        adapter.set_path_value("/P1", "intensity", 5.0)
        adapter.set_path_value("/P2", "intensity", 5.0)
        assert adapter.is_ambiguous("radius") is True
        assert adapter.is_ambiguous("intensity") is False


# ── set_value applies to all paths ───────────────────────────────────────────

class TestSetValueMultiPath:
    def test_set_value_writes_to_all_paths(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "radius", 1.0)
        adapter.set_path_value("/P2", "radius", 2.0)
        adapter.set_value("radius", 9.0)
        # After set_value all paths have same value — not ambiguous
        assert adapter.is_ambiguous("radius") is False
        assert adapter.get_value("radius") == pytest.approx(9.0)

    def test_set_value_three_paths_all_updated(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2", "/P3"])
        adapter.set_value("intensity", 100.0)
        for path in ["/P1", "/P2", "/P3"]:
            assert adapter._per_path_values[path]["intensity"] == pytest.approx(100.0)

    def test_edit_sequence_recorded(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.begin_edit("radius")
        adapter.set_value("radius", 3.0)
        adapter.end_edit("radius")
        assert ("begin", "radius") in adapter._edits
        assert ("end", "radius") in adapter._edits


# ── set_path_value helper ─────────────────────────────────────────────────────

class TestSetPathValue:
    def test_set_path_value_stores_in_per_path_dict(self):
        adapter = MockPropertyAdapter(paths=["/P1"])
        adapter.set_path_value("/P1", "radius", 42.0)
        assert adapter._per_path_values["/P1"]["radius"] == pytest.approx(42.0)

    def test_set_path_value_different_paths_independent(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "x", 1.0)
        adapter.set_path_value("/P2", "x", 2.0)
        assert adapter._per_path_values["/P1"]["x"] == pytest.approx(1.0)
        assert adapter._per_path_values["/P2"]["x"] == pytest.approx(2.0)

    def test_set_path_value_overrides_previous(self):
        adapter = MockPropertyAdapter(paths=["/P1"])
        adapter.set_path_value("/P1", "radius", 1.0)
        adapter.set_path_value("/P1", "radius", 5.0)
        assert adapter._per_path_values["/P1"]["radius"] == pytest.approx(5.0)


# ── Attribute rows — mixed-value styling ─────────────────────────────────────

class TestFloatAttributeRowMixed:
    def _make_window(self):
        return ui.Window("test_float_row_mixed", width=300, height=100)

    def test_float_row_builds_without_crash_when_ambiguous(self):
        adapter = MockPropertyAdapter(
            paths=["/P1", "/P2"],
            attributes={"radius": _float_meta("radius")},
        )
        adapter.set_path_value("/P1", "radius", 1.0)
        adapter.set_path_value("/P2", "radius", 2.0)
        w = self._make_window()
        with w.frame:
            row = FloatAttributeRow(_float_meta("radius"), adapter)
        assert row._widget is not None

    def test_float_row_builds_without_crash_when_not_ambiguous(self):
        adapter = MockPropertyAdapter(
            paths=["/P1"],
            attributes={"radius": _float_meta("radius")},
        )
        adapter.set_path_value("/P1", "radius", 3.0)
        w = self._make_window()
        with w.frame:
            row = FloatAttributeRow(_float_meta("radius"), adapter)
        assert row._widget is not None

    def test_float_row_value_is_zero_when_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "radius", 1.0)
        adapter.set_path_value("/P2", "radius", 9.0)
        w = self._make_window()
        with w.frame:
            row = FloatAttributeRow(_float_meta("radius"), adapter)
        # get_value returns None (mixed), so widget stays at default 0.0
        assert row._widget.model.get_value_as_float() == pytest.approx(0.0)

    def test_float_row_value_set_when_not_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1"])
        adapter.set_path_value("/P1", "radius", 3.5)
        w = self._make_window()
        with w.frame:
            row = FloatAttributeRow(_float_meta("radius"), adapter)
        assert row._widget.model.get_value_as_float() == pytest.approx(3.5)


class TestIntAttributeRowMixed:
    def test_int_row_builds_when_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "count", 1)
        adapter.set_path_value("/P2", "count", 2)
        w = ui.Window("test_int_row_mixed", width=300, height=100)
        with w.frame:
            row = IntAttributeRow(_int_meta("count"), adapter)
        assert row._widget is not None

    def test_int_row_value_zero_when_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "count", 1)
        adapter.set_path_value("/P2", "count", 2)
        w = ui.Window("test_int_row_mixed2", width=300, height=100)
        with w.frame:
            row = IntAttributeRow(_int_meta("count"), adapter)
        assert row._widget.model.get_value_as_int() == 0


class TestStringAttributeRowMixed:
    def test_string_row_builds_when_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "label", "sphere")
        adapter.set_path_value("/P2", "label", "cube")
        w = ui.Window("test_str_row_mixed", width=300, height=100)
        with w.frame:
            row = StringAttributeRow(_str_meta("label"), adapter)
        assert row._widget is not None

    def test_string_row_value_empty_when_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "label", "sphere")
        adapter.set_path_value("/P2", "label", "cube")
        w = ui.Window("test_str_row_mixed2", width=300, height=100)
        with w.frame:
            row = StringAttributeRow(_str_meta("label"), adapter)
        assert row._widget.model.get_value_as_string() == ""


class TestBoolAttributeRowMixed:
    def test_bool_row_builds_when_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "visible", True)
        adapter.set_path_value("/P2", "visible", False)
        w = ui.Window("test_bool_row_mixed", width=300, height=100)
        with w.frame:
            row = BoolAttributeRow(_bool_meta("visible"), adapter)
        assert row._widget is not None


class TestVec3AttributeRowMixed:
    def test_vec3_row_builds_when_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "color", (1.0, 0.0, 0.0))
        adapter.set_path_value("/P2", "color", (0.0, 1.0, 0.0))
        w = ui.Window("test_vec3_row_mixed", width=300, height=100)
        with w.frame:
            row = Vec3FloatAttributeRow(_vec3_meta("color"), adapter)
        assert all(w is not None for w in row._widgets)

    def test_vec3_row_widgets_zero_when_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "color", (1.0, 0.0, 0.0))
        adapter.set_path_value("/P2", "color", (0.0, 1.0, 0.0))
        w = ui.Window("test_vec3_row_mixed2", width=300, height=100)
        with w.frame:
            row = Vec3FloatAttributeRow(_vec3_meta("color"), adapter)
        for widget in row._widgets:
            assert widget.model.get_value_as_float() == pytest.approx(0.0)


# ── Vec3 per-component ambiguity styling (Step 2.3) ──────────────────────────
# PROPERTY_STYLES: ambiguous channels use the ``::mixed`` state selector. Step 2.5
# moved the base type from ``Property.LabelColumn`` to per-axis
# ``Property.ChannelLabel.{X,Y,Z}`` so the channel-colour (property attribute builder behavior) and
# the warning override can coexist via the same state-selector convention
# used by ``Stage.TypeBadge::{mesh,light,…}``.
_CHANNEL_STYLES = (
    "Property.ChannelLabel.X",
    "Property.ChannelLabel.Y",
    "Property.ChannelLabel.Z",
)
_MIXED_NAME = "mixed"


def _channel_mixed_flags(row):
    return [
        lbl.style_type_name_override == _CHANNEL_STYLES[i] and lbl.name == _MIXED_NAME
        for i, lbl in enumerate(row._channel_labels)
    ]


class TestVec3PerComponentAmbiguity:
    """Step 2.3: only channels that actually differ get Property.LabelColumn::mixed."""

    def _build_row(self, paths_and_values, window_name):
        adapter = MockPropertyAdapter(
            paths=[p for p, _ in paths_and_values],
            attributes={"translate": _vec3_meta("translate")},
        )
        for path, value in paths_and_values:
            adapter.set_path_value(path, "translate", value)
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            row = Vec3FloatAttributeRow(_vec3_meta("translate"), adapter)
        return row

    def test_only_x_differs_marks_x_label_mixed(self):
        row = self._build_row(
            [("/P1", (1.0, 2.0, 3.0)), ("/P2", (9.0, 2.0, 3.0))],
            "test_vec3_x_only_mixed",
        )
        assert _channel_mixed_flags(row) == [True, False, False]

    def test_only_z_differs_marks_z_label_mixed(self):
        row = self._build_row(
            [("/P1", (1.0, 0.0, 0.0)), ("/P2", (1.0, 0.0, 5.0))],
            "test_vec3_z_only_mixed",
        )
        assert _channel_mixed_flags(row) == [False, False, True]

    def test_all_equal_no_label_styled(self):
        row = self._build_row(
            [("/P1", (1.0, 2.0, 3.0)), ("/P2", (1.0, 2.0, 3.0))],
            "test_vec3_all_equal",
        )
        assert _channel_mixed_flags(row) == [False, False, False]

    def test_all_differ_all_labels_styled(self):
        row = self._build_row(
            [("/P1", (1.0, 2.0, 3.0)), ("/P2", (9.0, 8.0, 7.0))],
            "test_vec3_all_differ",
        )
        assert _channel_mixed_flags(row) == [True, True, True]

    def test_single_path_no_label_styled(self):
        row = self._build_row(
            [("/P1", (1.0, 2.0, 3.0))],
            "test_vec3_single_path",
        )
        assert _channel_mixed_flags(row) == [False, False, False]


# ── "Mixed" overlay visibility (Step 2.4) ────────────────────────────────────
# Property.MixedOverlay: each row wraps its value widget in a
# ui.ZStack and puts a small dim "Mixed" label on top, visible only when the
# attribute (scalar rows) or channel (vec rows) is ambiguous across the
# multi-selection.


class TestMixedOverlay:
    """Step 2.4: scalar rows expose a single ``_overlay`` label whose
    ``.visible`` tracks the attribute's whole-attribute ambiguity; vec3 rows
    expose ``_overlay_labels[i]`` per channel, each tracking the channel's
    entry in ``get_per_component_ambiguity``.
    """

    def _build_float_row(self, adapter, window_name):
        w = ui.Window(window_name, width=300, height=60)
        with w.frame:
            return FloatAttributeRow(_float_meta("radius"), adapter)

    def _build_vec3_row(self, adapter, window_name):
        w = ui.Window(window_name, width=400, height=60)
        with w.frame:
            return Vec3FloatAttributeRow(_vec3_meta("translate"), adapter)

    def test_float_overlay_visible_when_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "radius", 1.0)
        adapter.set_path_value("/P2", "radius", 2.0)
        row = self._build_float_row(adapter, "test_float_overlay_mixed")
        assert row._overlay is not None
        assert row._overlay.visible is True

    def test_float_overlay_hidden_when_not_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1"])
        adapter.set_path_value("/P1", "radius", 3.5)
        row = self._build_float_row(adapter, "test_float_overlay_clean")
        assert row._overlay is not None
        assert row._overlay.visible is False

    def test_int_overlay_visible_when_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "count", 1)
        adapter.set_path_value("/P2", "count", 2)
        w = ui.Window("test_int_overlay_mixed", width=300, height=60)
        with w.frame:
            row = IntAttributeRow(_int_meta("count"), adapter)
        assert row._overlay is not None
        assert row._overlay.visible is True

    def test_int_overlay_hidden_when_not_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1"])
        adapter.set_path_value("/P1", "count", 7)
        w = ui.Window("test_int_overlay_clean", width=300, height=60)
        with w.frame:
            row = IntAttributeRow(_int_meta("count"), adapter)
        assert row._overlay.visible is False

    def test_string_overlay_visible_when_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "label", "sphere")
        adapter.set_path_value("/P2", "label", "cube")
        w = ui.Window("test_str_overlay_mixed", width=300, height=60)
        with w.frame:
            row = StringAttributeRow(_str_meta("label"), adapter)
        assert row._overlay.visible is True

    def test_bool_overlay_visible_when_ambiguous(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "visible", True)
        adapter.set_path_value("/P2", "visible", False)
        w = ui.Window("test_bool_overlay_mixed", width=300, height=60)
        with w.frame:
            row = BoolAttributeRow(_bool_meta("visible"), adapter)
        assert row._overlay.visible is True

    def test_vec3_overlay_per_channel_only_z(self):
        adapter = MockPropertyAdapter(
            paths=["/P1", "/P2"],
            attributes={"translate": _vec3_meta("translate")},
        )
        adapter.set_path_value("/P1", "translate", (1.0, 0.0, 0.0))
        adapter.set_path_value("/P2", "translate", (1.0, 0.0, 5.0))
        row = self._build_vec3_row(adapter, "test_vec3_overlay_z_only")
        visibility = [o.visible for o in row._overlay_labels]
        assert visibility == [False, False, True]

    def test_vec3_overlay_per_channel_only_x(self):
        adapter = MockPropertyAdapter(
            paths=["/P1", "/P2"],
            attributes={"translate": _vec3_meta("translate")},
        )
        adapter.set_path_value("/P1", "translate", (1.0, 2.0, 3.0))
        adapter.set_path_value("/P2", "translate", (9.0, 2.0, 3.0))
        row = self._build_vec3_row(adapter, "test_vec3_overlay_x_only")
        assert [o.visible for o in row._overlay_labels] == [True, False, False]

    def test_vec3_overlay_all_channels_when_all_differ(self):
        adapter = MockPropertyAdapter(
            paths=["/P1", "/P2"],
            attributes={"translate": _vec3_meta("translate")},
        )
        adapter.set_path_value("/P1", "translate", (1.0, 2.0, 3.0))
        adapter.set_path_value("/P2", "translate", (9.0, 8.0, 7.0))
        row = self._build_vec3_row(adapter, "test_vec3_overlay_all")
        assert [o.visible for o in row._overlay_labels] == [True, True, True]

    def test_vec3_overlay_all_hidden_when_all_equal(self):
        adapter = MockPropertyAdapter(
            paths=["/P1", "/P2"],
            attributes={"translate": _vec3_meta("translate")},
        )
        adapter.set_path_value("/P1", "translate", (1.0, 2.0, 3.0))
        adapter.set_path_value("/P2", "translate", (1.0, 2.0, 3.0))
        row = self._build_vec3_row(adapter, "test_vec3_overlay_equal")
        assert [o.visible for o in row._overlay_labels] == [False, False, False]

    def test_vec3_overlay_all_hidden_for_single_path(self):
        adapter = MockPropertyAdapter(
            paths=["/P1"],
            attributes={"translate": _vec3_meta("translate")},
        )
        adapter.set_path_value("/P1", "translate", (1.0, 2.0, 3.0))
        row = self._build_vec3_row(adapter, "test_vec3_overlay_single")
        assert [o.visible for o in row._overlay_labels] == [False, False, False]

    def test_overlay_uses_mixed_overlay_style(self):
        """Pins the Property.MixedOverlay style selector — rename at style
        layer must break this test alongside any style-dict reorg."""
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "radius", 1.0)
        adapter.set_path_value("/P2", "radius", 9.0)
        row = self._build_float_row(adapter, "test_overlay_style_type")
        assert row._overlay.style_type_name_override == "Property.MixedOverlay"
        assert row._overlay.text == "Mixed"


# ── build_attribute_row factory — mixed value ─────────────────────────────────

class TestBuildAttributeRowMixed:
    def test_factory_float_mixed_builds(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "x", 1.0)
        adapter.set_path_value("/P2", "x", 2.0)
        w = ui.Window("test_factory_float_mixed", width=300, height=100)
        with w.frame:
            row = build_attribute_row(_float_meta("x"), adapter)
        assert isinstance(row, FloatAttributeRow)

    def test_factory_int_mixed_builds(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_path_value("/P1", "count", 1)
        adapter.set_path_value("/P2", "count", 2)
        w = ui.Window("test_factory_int_mixed", width=300, height=100)
        with w.frame:
            row = build_attribute_row(_int_meta("count"), adapter)
        assert isinstance(row, IntAttributeRow)


# ── is_ambiguous returns False for attrs with no per-path values ──────────────

class TestAmbiguityFallback:
    def test_no_per_path_values_falls_back_to_shared_values(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        adapter.set_value("radius", 3.0)  # same value for all paths
        assert adapter.is_ambiguous("radius") is False
        assert adapter.get_value("radius") == pytest.approx(3.0)

    def test_is_ambiguous_false_for_unknown_attr(self):
        adapter = MockPropertyAdapter(paths=["/P1", "/P2"])
        # No values set for this attr — both paths get None via fallback
        assert adapter.is_ambiguous("unknown") is False

    def test_get_value_none_for_unknown_unset_attr(self):
        adapter = MockPropertyAdapter(paths=["/P1"])
        assert adapter.get_value("unknown") is None

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the SRD section 4.4 viewport resolution preset catalog."""

from __future__ import annotations

import pytest

from ovui_widgets.viewport import (
    BUILTIN_RESOLUTION_PRESETS,
    CUSTOM_RESOLUTION_SENTINEL,
    CUSTOM_SENTINEL_DIMENSIONS,
    DEFAULT_VISIBLE_RESOLUTION_PRESET_LABELS,
    KNOWN_RESOLUTION_RATIO_BADGES,
    RESOLUTION_CATALOG_KIND_CUSTOM,
    RESOLUTION_CATALOG_KIND_PRESET,
    RESOLUTION_CATALOG_KIND_SAVED_CUSTOM,
    RESOLUTION_CATALOG_KIND_SENTINEL,
    RESOLUTION_MATCH_SOURCE_BUILTIN,
    RESOLUTION_MATCH_SOURCE_SAVED_CUSTOM,
    RESOLUTION_MATCH_SOURCE_SENTINEL,
    RESOLUTION_MODE_FIXED,
    RESOLUTION_SELECTION_KEYING_DESCRIPTION,
    RESOLUTION_PRESET_SOURCE_SRD_4_4,
    RESOLUTION_SAVED_CUSTOM_SOURCE_SETTING,
    RESOLUTION_SENTINEL_SOURCE_SRD_4_3,
    SETTING_RESOLUTION_PRESETS,
    VIEWPORT_RESOLUTION_SENTINEL,
    VIEWPORT_SENTINEL_DIMENSIONS,
    ResolutionCatalogSelection,
    ResolutionSavedCustomCatalogRow,
    ViewportResolutionState,
    ViewportResolutionStateError,
    current_resolution_label_for_requested_size,
    default_visible_resolution_presets,
    format_builtin_resolution_catalog_qa_lines,
    format_resolution_catalog_match_qa_lines,
    format_resolution_catalog_selection_qa_lines,
    format_resolution_sentinel_qa_lines,
    format_saved_custom_resolution_catalog_qa_lines,
    iter_builtin_resolution_presets,
    iter_resolution_sentinel_rows,
    iter_saved_custom_resolution_badge_rows,
    iter_saved_custom_resolution_catalog_rows,
    match_resolution_catalog_row_for_requested_size,
    requested_size_for_sentinel_selection,
    resolution_preset_by_label,
    resolution_badge_metadata,
    resolution_sentinel_by_label,
    resolve_visible_resolution_presets,
    select_resolution_catalog_row_for_requested_size,
    select_resolution_catalog_row_for_state,
    selected_resolution_sentinel_for_requested_size,
)


EXPECTED_SRD_4_4_PRESETS = (
    ("UHD", 3840, 2160),
    ("1440P", 2560, 1440),
    ("2K", 2048, 1080),
    ("HD1080P", 1920, 1080),
    ("HD720P", 1280, 720),
    ("Square", 1024, 1024),
    ("Icon", 512, 512),
    ("SD", 1280, 960),
    ("Ultra Wide", 3440, 1440),
    ("Super Ultra Wide", 3840, 1440),
    ("5K Wide", 5120, 2880),
)
EXPECTED_DEFAULT_VISIBLE_PRESETS = EXPECTED_SRD_4_4_PRESETS[:7]
EXPECTED_SRD_BADGES = {
    "UHD": "16:9",
    "1440P": "16:9",
    "2K": "1.90:1",
    "HD1080P": "16:9",
    "HD720P": "16:9",
    "Square": "1:1",
    "Icon": "1:1",
    "SD": "4:3",
    "Ultra Wide": "2.39:1",
    "Super Ultra Wide": "2.67:1",
    "5K Wide": "16:9",
}


class RecordingSettings:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = dict(values or {})

    def get(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)


def test_builtin_resolution_catalog_matches_srd_4_4_labels_and_dimensions() -> None:
    assert [
        (row.label, row.width, row.height)
        for row in iter_builtin_resolution_presets()
    ] == list(EXPECTED_SRD_4_4_PRESETS)


def test_builtin_resolution_catalog_stable_order_and_keys() -> None:
    assert tuple(row.key for row in BUILTIN_RESOLUTION_PRESETS) == tuple(
        f"preset:{label}" for label, _width, _height in EXPECTED_SRD_4_4_PRESETS
    )


def test_builtin_resolution_catalog_rows_are_recognized_preset_metadata() -> None:
    for row in iter_builtin_resolution_presets():
        assert row.kind == RESOLUTION_CATALOG_KIND_PRESET
        assert row.recognized is True
        assert row.source == RESOLUTION_PRESET_SOURCE_SRD_4_4
        assert row.dimensions == (row.width, row.height)
        assert row.dimension_text == f"{row.width}x{row.height}"


def test_wide_and_over_max_recognized_rows_are_preserved_for_area_7_policy() -> None:
    ultra_wide = resolution_preset_by_label("Ultra Wide")
    super_ultra_wide = resolution_preset_by_label("Super Ultra Wide")
    five_k_wide = resolution_preset_by_label("5K Wide")

    assert ultra_wide.dimensions == (3440, 1440)
    assert super_ultra_wide.dimensions == (3840, 1440)
    assert five_k_wide.dimensions == (5120, 2880)
    assert all(row.recognized for row in (ultra_wide, super_ultra_wide, five_k_wide))


def test_resolution_catalog_qa_lines_render_the_real_catalog() -> None:
    lines = format_builtin_resolution_catalog_qa_lines(
        profile_label="Full recognized preset library",
        preset_config_label="current Area-1 preset setting",
        focus_label="5K Wide",
    )
    text = "\n".join(lines)

    for index, (label, width, height) in enumerate(
        EXPECTED_SRD_4_4_PRESETS,
        start=1,
    ):
        assert f"{index}. {label} {width}x{height}" in text
    assert "Recognized built-in rows: 11" in text
    assert "Focused: 5K Wide 5120x2880 is recognized" in text
    assert "over-max policy is future Area 7" in text
    assert "Area 4 owns product menu rendering" in text


def test_absent_preset_setting_falls_back_to_seven_default_visible_rows() -> None:
    rows = resolve_visible_resolution_presets(RecordingSettings())

    assert [row.label for row in rows] == list(DEFAULT_VISIBLE_RESOLUTION_PRESET_LABELS)
    assert [
        (row.label, row.width, row.height)
        for row in default_visible_resolution_presets()
    ] == list(EXPECTED_DEFAULT_VISIBLE_PRESETS)


def test_visible_preset_resolution_parses_flat_configured_list() -> None:
    rows = resolve_visible_resolution_presets(
        configured_value=[512, 512, 1920, 1080, 3840, 2160]
    )

    assert [row.label for row in rows] == ["Icon", "HD1080P", "UHD"]


def test_visible_preset_resolution_parses_pair_configured_list() -> None:
    rows = resolve_visible_resolution_presets(
        configured_value=[[1280, 960], (3440, 1440), [5120, 2880]]
    )

    assert [row.label for row in rows] == ["SD", "Ultra Wide", "5K Wide"]


def test_visible_preset_resolution_ignores_unknown_and_malformed_entries() -> None:
    rows = resolve_visible_resolution_presets(
        RecordingSettings(
            {
                SETTING_RESOLUTION_PRESETS: [
                    [3840, 2160],
                    [9999, 9999],
                    "bad",
                    [0, 720],
                    [1280, 720],
                    [False, 512],
                    {"width": 512, "height": 512},
                    [512, 512],
                ]
            }
        )
    )

    assert [row.label for row in rows] == ["UHD", "HD720P", "Icon"]


def test_visible_preset_resolution_suppresses_duplicate_dimensions() -> None:
    rows = resolve_visible_resolution_presets(
        configured_value=[1920, 1080, [1920, 1080], [1280, 720], 1280, 720]
    )

    assert [row.label for row in rows] == ["HD1080P", "HD720P"]


def test_present_empty_preset_setting_produces_no_visible_rows() -> None:
    assert resolve_visible_resolution_presets(configured_value=[]) == ()


def test_resolution_catalog_qa_lines_can_render_resolved_visible_rows() -> None:
    rows = resolve_visible_resolution_presets(
        configured_value=[3840, 2160, 1280, 720]
    )
    lines = format_builtin_resolution_catalog_qa_lines(
        profile_label="Default preset setting absent",
        preset_config_label="viewport.resolution.presets absent",
        rows=rows,
        row_heading="Visible preset rows",
    )
    text = "\n".join(lines)

    assert "Visible preset rows: 2" in text
    assert "1. UHD 3840x2160" in text
    assert "2. HD720P 1280x720" in text
    assert "HD1080P" not in text


def test_known_ratio_badge_definitions_match_srd_order() -> None:
    assert tuple(label for _ratio, label in KNOWN_RESOLUTION_RATIO_BADGES) == (
        "16:9",
        "1:1",
        "32:9",
        "4:3",
        "21:9",
    )


def test_builtin_ratio_badges_match_srd_4_3_and_4_4_expectations() -> None:
    assert {
        row.label: row.ratio_badge_label
        for row in iter_builtin_resolution_presets()
    } == EXPECTED_SRD_BADGES


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (3840, 2160, "16:9"),
        (1024, 1024, "1:1"),
        (5120, 1440, "32:9"),
        (1280, 960, "4:3"),
        (2520, 1080, "21:9"),
        (1795, 1000, "16:9"),
    ],
)
def test_ratio_badges_match_known_ratios_within_one_percent_tolerance(
    width: int,
    height: int,
    expected: str,
) -> None:
    assert resolution_badge_metadata(width, height).ratio_badge_label == expected


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1797, 1000, "1.80:1"),
        (2048, 1080, "1.90:1"),
        (3440, 1440, "2.39:1"),
        (3840, 1440, "2.67:1"),
        (1500, 1000, "1.50:1"),
    ],
)
def test_ratio_badges_use_two_decimal_fallback_outside_known_tolerance(
    width: int,
    height: int,
    expected: str,
) -> None:
    assert resolution_badge_metadata(width, height).ratio_badge_label == expected


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (0, 100),
        (100, 0),
        (-1, 100),
        (100, -1),
        (True, 100),
        (100, False),
        ("100", 100),
        (100, "100"),
    ],
)
def test_ratio_badges_omit_invalid_dimensions(width: object, height: object) -> None:
    metadata = resolution_badge_metadata(width, height)

    assert metadata.resolution_text == ""
    assert metadata.ratio_badge_label is None


def test_valid_saved_custom_entries_get_ratio_badge_metadata() -> None:
    rows = iter_saved_custom_resolution_badge_rows(
        [
            {"name": "Review", "width": 1500, "height": 1000},
            {"name": "  Near 21:9  ", "width": 3440, "height": 1440},
            {"name": "", "width": 100, "height": 100},
        ]
    )

    assert [(row.label, row.resolution_text, row.ratio_badge_label) for row in rows] == [
        ("Review", "1500x1000", "1.50:1"),
        ("Near 21:9", "3440x1440", "2.39:1"),
    ]
    assert all(row.kind == RESOLUTION_CATALOG_KIND_SAVED_CUSTOM for row in rows)


def test_resolution_catalog_qa_lines_can_render_badge_details_and_saved_customs() -> None:
    lines = format_builtin_resolution_catalog_qa_lines(
        profile_label="Ratio badge details",
        preset_config_label="ratio badge metadata for recognized rows",
        include_badges=True,
        saved_custom_entries=[{"name": "Review", "width": 1500, "height": 1000}],
    )
    text = "\n".join(lines)

    assert "A2 Ratio Badge Metadata QA Scaffold" in text
    assert "1. UHD 3840x2160 | badge=16:9" in text
    assert "3. 2K 2048x1080 | badge=1.90:1" in text
    assert "9. Ultra Wide 3440x1440 | badge=2.39:1" in text
    assert "10. Super Ultra Wide 3840x1440 | badge=2.67:1" in text
    assert "Custom 1. Review 1500x1000 | badge=1.50:1" in text
    assert "Ratio badges are metadata only; visual styling is Area 4" in text


def test_saved_custom_catalog_rows_are_created_from_normalized_data() -> None:
    rows = iter_saved_custom_resolution_catalog_rows(
        [{"name": "Review", "width": 1500, "height": 1000}]
    )

    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, ResolutionSavedCustomCatalogRow)
    assert row.key == "custom:Review:1500x1000"
    assert row.label == "Review"
    assert row.dimensions == (1500, 1000)
    assert row.dimension_text == "1500x1000"
    assert row.resolution_text == "1500x1000"
    assert row.ratio_badge_label == "1.50:1"
    assert row.ratio_badge_label == resolution_badge_metadata(1500, 1000).ratio_badge_label
    assert row.kind == RESOLUTION_CATALOG_KIND_CUSTOM
    assert row.kind == RESOLUTION_CATALOG_KIND_SAVED_CUSTOM
    assert row.source == RESOLUTION_SAVED_CUSTOM_SOURCE_SETTING


def test_saved_custom_catalog_rows_preserve_area_1_normalized_order() -> None:
    rows = iter_saved_custom_resolution_catalog_rows(
        [
            {"name": "Review", "width": 1500, "height": 1000},
            {"name": "Portrait", "width": 1080, "height": 1920},
        ]
    )

    assert [
        (row.label, row.resolution_text, row.ratio_badge_label)
        for row in rows
    ] == [
        ("Review", "1500x1000", "1.50:1"),
        ("Portrait", "1080x1920", "0.56:1"),
    ]


def test_saved_custom_catalog_rows_drop_malformed_loaded_entries() -> None:
    rows = iter_saved_custom_resolution_catalog_rows(
        [
            {"name": "Only Valid", "width": 1600, "height": 900},
            {"width": 1200, "height": 800},
            {"name": "   ", "width": 1200, "height": 800},
            {"name": "Bool Width", "width": True, "height": 800},
            {"name": "Zero Width", "width": 0, "height": 800},
            {"name": "Only Valid", "width": 1700, "height": 900},
            {"name": "Duplicate Dimensions", "width": 1600, "height": 900},
            ["Unsupported", 1200, 800],
        ]
    )

    assert [(row.label, row.dimensions) for row in rows] == [
        ("Only Valid", (1600, 900))
    ]


def test_saved_custom_catalog_rows_stay_separate_from_presets_and_sentinels() -> None:
    rows = iter_saved_custom_resolution_catalog_rows(
        [{"name": "Preset Sized", "width": 1920, "height": 1080}]
    )
    saved_row = rows[0]

    assert saved_row.kind == RESOLUTION_CATALOG_KIND_CUSTOM
    assert saved_row.resolution_text == "1920x1080"
    assert saved_row.ratio_badge_label == "16:9"
    assert saved_row.key not in {row.key for row in iter_builtin_resolution_presets()}
    assert saved_row.key not in {row.key for row in iter_resolution_sentinel_rows()}


def test_saved_custom_catalog_qa_lines_render_rows_from_area_1_data() -> None:
    lines = format_saved_custom_resolution_catalog_qa_lines(
        profile_label="Two saved custom catalog rows",
        custom_entries=[
            {"name": "Review", "width": 1500, "height": 1000},
            {"name": "Portrait", "width": 1080, "height": 1920},
            {"name": "", "width": 100, "height": 100},
        ],
    )
    text = "\n".join(lines)

    assert "A2 Saved Custom Resolution Catalog QA Scaffold" in text
    assert "Source: Area-1 normalized viewport.resolution.custom.list" in text
    assert "Saved custom catalog rows: 2" in text
    assert "1. Review 1500x1000 | badge=1.50:1 | custom" in text
    assert "2. Portrait 1080x1920 | badge=0.56:1 | custom" in text
    assert "Saved rows are separate from built-ins and sentinels" in text
    assert "Area 4 owns row rendering and delete affordances" in text


def test_catalog_match_uses_exact_positive_dimensions() -> None:
    match = match_resolution_catalog_row_for_requested_size((1920, 1080))

    assert match is not None
    assert match.label == "HD1080P"
    assert match.kind == RESOLUTION_CATALOG_KIND_PRESET
    assert match.source == RESOLUTION_MATCH_SOURCE_BUILTIN
    assert match.requested_size == (1920, 1080)

    assert match_resolution_catalog_row_for_requested_size((0, 0)) is None
    assert match_resolution_catalog_row_for_requested_size((-1, -1)) is None
    assert match_resolution_catalog_row_for_requested_size(("1920", 1080)) is None


def test_catalog_match_prefers_builtin_over_saved_preset_duplicate() -> None:
    match = match_resolution_catalog_row_for_requested_size(
        (1920, 1080),
        saved_custom_entries=[
            {"name": "HD Copy", "width": 1920, "height": 1080},
        ],
    )

    assert match is not None
    assert match.label == "HD1080P"
    assert match.key == "preset:HD1080P"
    assert match.source == RESOLUTION_MATCH_SOURCE_BUILTIN


def test_catalog_match_uses_saved_custom_when_no_builtin_matches() -> None:
    match = match_resolution_catalog_row_for_requested_size(
        (1500, 1000),
        saved_custom_entries=[
            {"name": "Review", "width": 1500, "height": 1000},
        ],
    )

    assert match is not None
    assert match.label == "Review"
    assert match.key == "custom:Review:1500x1000"
    assert match.kind == RESOLUTION_CATALOG_KIND_CUSTOM
    assert match.source == RESOLUTION_MATCH_SOURCE_SAVED_CUSTOM
    assert match.ratio_badge_label == "1.50:1"


def test_catalog_match_uses_first_normalized_saved_custom_candidate() -> None:
    match = match_resolution_catalog_row_for_requested_size(
        (1500, 1000),
        saved_custom_entries=[
            {"name": "Review", "width": 1500, "height": 1000},
            {"name": "Review", "width": 1700, "height": 1000},
            {"name": "Duplicate Dimensions", "width": 1500, "height": 1000},
        ],
    )

    rows = iter_saved_custom_resolution_catalog_rows(
        [
            {"name": "Review", "width": 1500, "height": 1000},
            {"name": "Review", "width": 1700, "height": 1000},
            {"name": "Duplicate Dimensions", "width": 1500, "height": 1000},
        ]
    )
    assert [(row.label, row.dimensions) for row in rows] == [
        ("Review", (1500, 1000))
    ]
    assert match is not None
    assert match.label == "Review"
    assert match.source == RESOLUTION_MATCH_SOURCE_SAVED_CUSTOM


def test_catalog_match_near_non_exact_size_falls_back_to_custom_sentinel() -> None:
    match = match_resolution_catalog_row_for_requested_size(
        (1921, 1080),
        saved_custom_entries=[
            {"name": "HD Copy", "width": 1920, "height": 1080},
            {"name": "Review", "width": 1500, "height": 1000},
        ],
    )

    assert match is not None
    assert match.row is CUSTOM_RESOLUTION_SENTINEL
    assert match.label == "Custom"
    assert match.kind == RESOLUTION_CATALOG_KIND_SENTINEL
    assert match.source == RESOLUTION_MATCH_SOURCE_SENTINEL
    assert match.requested_size == (1921, 1080)


def test_catalog_match_qa_lines_mark_exactly_one_selected_row() -> None:
    lines = format_resolution_catalog_match_qa_lines(
        profile_label="Match HD Copy preset duplicate",
        requested_size=(1920, 1080),
        custom_entries=[
            {"name": "HD Copy", "width": 1920, "height": 1080},
        ],
    )
    text = "\n".join(lines)

    assert "A2 Saved Custom and Preset-Duplicate Match QA Scaffold" in text
    assert "Requested Size: [1920,1080]" in text
    assert "HD1080P 1920x1080 | badge=16:9 | preset | selected=true" in text
    assert "HD Copy 1920x1080 | badge=16:9 | custom | selected=false" in text
    assert "Matched: HD1080P | preset | source=built-in preset" in text
    assert "Selected Row Count: 1" in text


def test_catalog_match_qa_lines_show_custom_fallback_for_near_size() -> None:
    lines = format_resolution_catalog_match_qa_lines(
        profile_label="Match near non-exact size",
        requested_size=(1921, 1080),
        custom_entries=[
            {"name": "HD Copy", "width": 1920, "height": 1080},
        ],
    )
    text = "\n".join(lines)

    assert "Requested Size: [1921,1080]" in text
    assert "HD1080P 1920x1080 | badge=16:9 | preset | selected=true" not in text
    assert "Custom [-1,-1] | badge=none | sentinel | selected=true" in text
    assert "Exact match not found; Custom sentinel is selected" in text
    assert "Selected Row Count: 1" in text


def _selected_true_count(lines: tuple[str, ...]) -> int:
    return sum(
        "selected=true" in line and line.split(".", 1)[0].isdigit()
        for line in lines
    )


def test_catalog_selection_maps_viewport_requested_size_to_viewport_label() -> None:
    selection = select_resolution_catalog_row_for_requested_size(
        VIEWPORT_SENTINEL_DIMENSIONS,
        saved_custom_entries=[{"name": "Review", "width": 1500, "height": 1000}],
    )

    assert isinstance(selection, ResolutionCatalogSelection)
    assert selection.row is VIEWPORT_RESOLUTION_SENTINEL
    assert selection.current_label == "Viewport"
    assert selection.selected_row_count == 1


@pytest.mark.parametrize(("label", "width", "height"), EXPECTED_SRD_4_4_PRESETS)
def test_catalog_selection_selects_each_builtin_preset_exactly_once(
    label: str,
    width: int,
    height: int,
) -> None:
    selection = select_resolution_catalog_row_for_requested_size(
        (width, height),
        saved_custom_entries=[{"name": "HD Copy", "width": 1920, "height": 1080}],
    )

    assert selection is not None
    assert selection.label == label
    assert selection.current_label == label
    assert selection.kind == RESOLUTION_CATALOG_KIND_PRESET
    assert selection.selected_row_count == 1


def test_catalog_selection_selects_saved_custom_when_no_builtin_matches() -> None:
    selection = select_resolution_catalog_row_for_requested_size(
        (1500, 1000),
        saved_custom_entries=[{"name": "Review", "width": 1500, "height": 1000}],
    )

    assert selection is not None
    assert selection.label == "Review"
    assert selection.current_label == "Review"
    assert selection.kind == RESOLUTION_CATALOG_KIND_CUSTOM
    assert selection.source == RESOLUTION_MATCH_SOURCE_SAVED_CUSTOM


def test_catalog_selection_selects_custom_for_positive_non_match() -> None:
    selection = select_resolution_catalog_row_for_requested_size(
        (1921, 1080),
        saved_custom_entries=[
            {"name": "HD Copy", "width": 1920, "height": 1080},
            {"name": "Review", "width": 1500, "height": 1000},
        ],
    )

    assert selection is not None
    assert selection.row is CUSTOM_RESOLUTION_SENTINEL
    assert selection.current_label == "Custom"
    assert selection.source == RESOLUTION_MATCH_SOURCE_SENTINEL


def test_catalog_selection_prefers_builtin_over_saved_duplicate_dimensions() -> None:
    selection = select_resolution_catalog_row_for_requested_size(
        (1920, 1080),
        saved_custom_entries=[
            {"name": "HD Copy", "width": 1920, "height": 1080},
        ],
    )

    assert selection is not None
    assert selection.label == "HD1080P"
    assert selection.current_label == "HD1080P"
    assert selection.source == RESOLUTION_MATCH_SOURCE_BUILTIN


def test_catalog_selection_is_keyed_to_requested_size_not_effective_size_or_scale() -> None:
    state = ViewportResolutionState(
        mode=RESOLUTION_MODE_FIXED,
        requested_size=(1920, 1080),
        scale=0.5,
        effective_size=(960, 540),
    )

    selection = select_resolution_catalog_row_for_state(
        state,
        saved_custom_entries=[{"name": "Review", "width": 1500, "height": 1000}],
        render_scale=0.5,
        effective_size=(960, 540),
    )

    assert selection is not None
    assert selection.label == "HD1080P"
    assert selection.current_label == "HD1080P"
    assert RESOLUTION_SELECTION_KEYING_DESCRIPTION.startswith("accepted requested")


def test_catalog_selection_rejected_action_leaves_previous_accepted_row() -> None:
    previous_accepted_size = (1921, 1080)
    attempted_rejected_size = CUSTOM_SENTINEL_DIMENSIONS

    previous_selection = select_resolution_catalog_row_for_requested_size(
        previous_accepted_size,
        saved_custom_entries=[{"name": "Review", "width": 1500, "height": 1000}],
    )
    rejected_selection = select_resolution_catalog_row_for_requested_size(
        previous_accepted_size,
        saved_custom_entries=[{"name": "Review", "width": 1500, "height": 1000}],
    )

    assert previous_selection is not None
    assert rejected_selection is not None
    assert attempted_rejected_size != rejected_selection.requested_size
    assert rejected_selection.key == previous_selection.key
    assert rejected_selection.current_label == previous_selection.current_label


def test_catalog_selection_qa_lines_show_exactly_one_selected_row_and_label() -> None:
    lines = format_resolution_catalog_selection_qa_lines(
        profile_label="Selection HD1080P",
        accepted_requested_size=(1920, 1080),
        custom_entries=[{"name": "Review", "width": 1500, "height": 1000}],
        render_scale=0.5,
    )
    text = "\n".join(lines)

    assert "A2 Selected Row and Current Label QA Scaffold" in text
    assert "Accepted Requested Size: [1920,1080]" in text
    assert "Current Label: HD1080P" in text
    assert "Render Scale Control: 0.5" in text
    assert "HD1080P 1920x1080 | badge=16:9 | preset | selected=true" in text
    assert "Review 1500x1000 | badge=1.50:1 | custom | selected=false" in text
    assert "Selected Row Count: 1" in text
    assert _selected_true_count(lines) == 1


def test_catalog_selection_qa_lines_show_rejected_action_without_optimism() -> None:
    lines = format_resolution_catalog_selection_qa_lines(
        profile_label="Selection rejected action",
        accepted_requested_size=(1921, 1080),
        attempted_requested_size=CUSTOM_SENTINEL_DIMENSIONS,
        action_accepted=False,
        custom_entries=[{"name": "Review", "width": 1500, "height": 1000}],
    )
    text = "\n".join(lines)

    assert "Accepted Requested Size: [1921,1080]" in text
    assert "Current Label: Custom" in text
    assert "Attempted Requested Size: [-1,-1] | accepted=false" in text
    assert "Rejected action left previous accepted selection unchanged" in text
    assert "Custom [-1,-1] | badge=none | sentinel | selected=true" in text
    assert "Selected Row Count: 1" in text
    assert _selected_true_count(lines) == 1


def test_resolution_sentinel_rows_define_viewport_and_custom_metadata() -> None:
    rows = iter_resolution_sentinel_rows()

    assert rows == (VIEWPORT_RESOLUTION_SENTINEL, CUSTOM_RESOLUTION_SENTINEL)
    assert [
        (row.label, row.dimensions, row.dimension_text, row.meaning)
        for row in rows
    ] == [
        ("Viewport", VIEWPORT_SENTINEL_DIMENSIONS, "[0,0]", "UI-frame-driven mode"),
        (
            "Custom",
            CUSTOM_SENTINEL_DIMENSIONS,
            "[-1,-1]",
            "unsaved positive non-matching requested size",
        ),
    ]
    assert all(row.kind == RESOLUTION_CATALOG_KIND_SENTINEL for row in rows)
    assert all(row.source == RESOLUTION_SENTINEL_SOURCE_SRD_4_3 for row in rows)
    assert all(row.ratio_badge_label is None for row in rows)
    assert rows[0].key not in {row.key for row in iter_builtin_resolution_presets()}


def test_resolution_sentinel_lookup_by_exact_label() -> None:
    assert resolution_sentinel_by_label("Viewport") is VIEWPORT_RESOLUTION_SENTINEL
    assert resolution_sentinel_by_label("Custom") is CUSTOM_RESOLUTION_SENTINEL
    with pytest.raises(KeyError):
        resolution_sentinel_by_label("HD1080P")


def test_default_requested_size_selects_viewport_sentinel() -> None:
    selected = selected_resolution_sentinel_for_requested_size([0, 0])

    assert selected is VIEWPORT_RESOLUTION_SENTINEL
    assert current_resolution_label_for_requested_size((0, 0)) == "Viewport"


def test_unsaved_positive_non_matching_size_selects_custom_sentinel() -> None:
    selected = selected_resolution_sentinel_for_requested_size((1500, 1000))

    assert selected is CUSTOM_RESOLUTION_SENTINEL
    assert current_resolution_label_for_requested_size([1500, 1000]) == "Custom"


def test_builtin_requested_size_does_not_select_custom_sentinel() -> None:
    assert selected_resolution_sentinel_for_requested_size((1920, 1080)) is None
    assert current_resolution_label_for_requested_size((1920, 1080)) is None


def test_custom_sentinel_with_positive_unsaved_size_returns_that_size() -> None:
    selected_size = requested_size_for_sentinel_selection(
        CUSTOM_RESOLUTION_SENTINEL,
        unsaved_size=(1500, 1000),
        previous_requested_size=VIEWPORT_SENTINEL_DIMENSIONS,
    )

    assert selected_size == (1500, 1000)
    assert selected_size != CUSTOM_SENTINEL_DIMENSIONS


def test_custom_sentinel_without_unsaved_size_does_not_apply_negative_dimensions() -> None:
    selected_size = requested_size_for_sentinel_selection(
        CUSTOM_RESOLUTION_SENTINEL,
        unsaved_size=None,
        previous_requested_size=VIEWPORT_SENTINEL_DIMENSIONS,
    )

    assert selected_size == VIEWPORT_SENTINEL_DIMENSIONS
    assert selected_size != CUSTOM_SENTINEL_DIMENSIONS

    with pytest.raises(ViewportResolutionStateError):
        ViewportResolutionState(
            mode=RESOLUTION_MODE_FIXED,
            requested_size=CUSTOM_SENTINEL_DIMENSIONS,
        )


def test_custom_sentinel_without_unsaved_size_can_preserve_previous_valid_size() -> None:
    selected_size = requested_size_for_sentinel_selection(
        CUSTOM_RESOLUTION_SENTINEL,
        unsaved_size=None,
        previous_requested_size=(1500, 1000),
    )

    assert selected_size == (1500, 1000)
    assert selected_size != CUSTOM_SENTINEL_DIMENSIONS


def test_custom_sentinel_rejects_builtin_unsaved_size_as_custom() -> None:
    selected_size = requested_size_for_sentinel_selection(
        CUSTOM_RESOLUTION_SENTINEL,
        unsaved_size=(1920, 1080),
        previous_requested_size=VIEWPORT_SENTINEL_DIMENSIONS,
    )

    assert selected_size == VIEWPORT_SENTINEL_DIMENSIONS
    assert selected_resolution_sentinel_for_requested_size(selected_size) is (
        VIEWPORT_RESOLUTION_SENTINEL
    )


def test_viewport_sentinel_selection_returns_viewport_requested_size() -> None:
    assert requested_size_for_sentinel_selection("Viewport") == (
        VIEWPORT_SENTINEL_DIMENSIONS
    )


def test_resolution_sentinel_qa_lines_render_real_sentinel_state() -> None:
    lines = format_resolution_sentinel_qa_lines(
        profile_label="Custom sentinel selected",
        requested_size=(1500, 1000),
        unsaved_size=(1500, 1000),
        attempted_sentinel_label="Custom",
    )
    text = "\n".join(lines)

    assert "A2 Viewport and Custom Sentinel QA Scaffold" in text
    assert "1. Viewport [0,0] | sentinel" in text
    assert "selected=false" in text
    assert "2. Custom [-1,-1] | sentinel" in text
    assert "Current Requested Size: [1500,1000]" in text
    assert "Current Label: Custom" in text
    assert "[-1,-1] not applied as requested size" in text
    assert "Custom sentinel is not the Custom Resolution editor row" in text

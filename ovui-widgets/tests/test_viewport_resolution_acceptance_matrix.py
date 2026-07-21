# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re

import pytest


EXPECTED_AC_IDS = tuple(f"AC-{index:02d}" for index in range(1, 36))
AC_ID_RE = re.compile(r"^AC-\d{2}$")
TICKET_RE = re.compile(r"^A\d+-T\d{2}$")
OBSOLETE_EVIDENCE_TOKENS = (
    "obsolete-overlay-panel-evidence",
    "standalone-resolution-button-evidence",
    "toolbar-text-mirror-evidence",
)


@dataclass(frozen=True)
class CoverageRow:
    requirement_id: str
    owner_tickets: tuple[str, ...]
    scenario: str
    evidence_id: str
    evidence_type: str
    status: str
    evidence_refs: tuple[str, ...]


def _row(
    requirement_id: str,
    owner_tickets: tuple[str, ...],
    scenario: str,
    evidence_id: str,
    evidence_type: str,
    *evidence_refs: str,
    status: str = "PASS",
) -> CoverageRow:
    return CoverageRow(
        requirement_id=requirement_id,
        owner_tickets=owner_tickets,
        scenario=scenario,
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        status=status,
        evidence_refs=evidence_refs,
    )


AC_COVERAGE_MATRIX: tuple[CoverageRow, ...] = (
    _row(
        "AC-01",
        ("A0-T05", "A4-T01", "A8-T01"),
        "Open the viewport and verify toolbar order Settings, Move, Rotate, Scale, Camera.",
        "A8-T01-01-toolbar-order",
        "screenshot+toolbar-order-test",
        "viewport-resolution-impl/scratch/A8-T01/a8_t01_01_normal_openusd_viewport_hud.png",
    ),
    _row(
        "AC-02",
        ("A0-T04", "A7-T01", "A7-T02"),
        "Run degraded renderer/settings/stage profiles and verify Settings remains reachable with disabled reasons.",
        "A7-T01-03-no-renderer-disabled-reason",
        "guardrail-screenshot+unit",
        "viewport-resolution-impl/scratch/A7-T01/a7_t01_03_render_resolution_disabled_reason.png",
    ),
    _row(
        "AC-03",
        ("A4-T01", "A4-T02", "A4-T03", "A8-T01"),
        "Click Settings, open Viewport, and verify one top-level Viewport item with resolution controls.",
        "A8-T01-02-settings-one-viewport",
        "menu-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T01/a8_t01_02_settings_one_viewport_item.png",
        "viewport-resolution-impl/scratch/A8-T01/a8_t01_03_render_resolution_default_checked.png",
    ),
    _row(
        "AC-04",
        ("A1-T01", "A2-T07", "A3-T01", "A6-T07"),
        "Launch with default settings and verify Viewport checked, scale 100%, Fill disabled/off, HUD matches frame.",
        "A8-T01-03-default-render-resolution",
        "screenshot+state-test",
        "viewport-resolution-impl/scratch/A8-T01/a8_t01_03_render_resolution_default_checked.png",
    ),
    _row(
        "AC-05",
        ("A2-T01", "A2-T02", "A4-T04"),
        "Open Render Resolution and verify the default Kit fallback preset order and ratio badges.",
        "A4-T04-built-in-preset-row-coverage",
        "unit+menu-screenshot",
        "viewport-resolution-impl/scratch/A8-T01/a8_t01_03_render_resolution_default_checked.png",
    ),
    _row(
        "AC-06",
        ("A2-T01", "A3-T04", "A4-T04", "A7-T04"),
        "Use the full recognized preset profile and verify all eleven names, including over-max policy for 5K Wide.",
        "A7-T04-full-preset-over-max-5k",
        "guardrail-screenshot+unit",
        "viewport-resolution-impl/scratch/A7-T04/a7_t04_02_5k_disabled_reason.png",
    ),
    _row(
        "AC-07",
        ("A3-T02", "A4-T08", "A6-T07", "A8-T01"),
        "Select HD1080P at 100% and verify checked row, current label, render, and HUD 1920x1080.",
        "A8-T01-04-hd1080p-selected-1920",
        "acceptance-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T01/a8_t01_04_hd1080p_selected_checked.png",
        "viewport-resolution-impl/scratch/A8-T01/a8_t01_04b_hd1080p_hud_1920x1080.png",
    ),
    _row(
        "AC-08",
        ("A4-T08", "A4-T09", "A8-T02"),
        "Select Viewport after a fixed mode and verify Fill disabled/off and no fake fixed-fill state.",
        "A8-T02-06-viewport-mode-fill-disabled",
        "acceptance-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T02/a8_t02_06_viewport_mode_fill_disabled.png",
        "viewport-resolution-impl/scratch/A8-T02/a8_t02_06b_viewport_mode_hud_no_fake_fixed_fill.png",
    ),
    _row(
        "AC-09",
        ("A3-T02", "A4-T09", "A6-T07", "A8-T01"),
        "Select HD1080P, set Render Scale to 50%, and verify HD1080P remains checked with HUD 960x540.",
        "A8-T01-05-scale-50-hud-960",
        "acceptance-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T01/a8_t01_05_render_scale_50_checked.png",
        "viewport-resolution-impl/scratch/A8-T01/a8_t01_05b_render_scale_50_hud_960x540.png",
    ),
    _row(
        "AC-10",
        ("A3-T04", "A6-T07", "A7-T04"),
        "Select UHD at 200% and verify Area-3 clamp with visible max-bound policy.",
        "A7-T04-uhd-200-max-bound",
        "guardrail-screenshot+unit",
        "viewport-resolution-impl/scratch/A7-T04/a7_t04_04_uhd_200_capped_warning.png",
    ),
    _row(
        "AC-11",
        ("A5-T03", "A5-T04"),
        "With 16:9 link enabled, edit width to 1600 and verify height 900 and render apply.",
        "A5-T03-linked-width-1600-height-900",
        "unit+menu-screenshot",
        "viewport-resolution-impl/scratch/A5-T03/a5_t03_03_width_1600_height_900.png",
        "viewport-resolution-impl/scratch/A5-T03/a5_t03_04_accepted_1600x900_custom_hud.png",
    ),
    _row(
        "AC-12",
        ("A5-T03", "A5-T04"),
        "With 4:3 link enabled, edit height to 900 and verify width 1200 and render apply.",
        "A5-T03-linked-height-900-width-1200",
        "unit+menu-screenshot",
        "viewport-resolution-impl/scratch/A5-T03/a5_t03_05_ratio_4_3_height_900_width_1200.png",
    ),
    _row(
        "AC-13",
        ("A5-T01", "A5-T04", "A8-T03"),
        "Turn link off, enter 1500x1000, and verify custom ratio and render/HUD apply.",
        "A8-T03-04-unsaved-custom-1500x1000",
        "acceptance-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T03/a8_t03_04_height_keyboard_1000_custom_selected.png",
        "viewport-resolution-impl/scratch/A8-T03/a8_t03_04b_unsaved_custom_hud_1500x1000.png",
    ),
    _row(
        "AC-14",
        ("A3-T04", "A5-T05", "A5-T06"),
        "Enter below-minimum custom values and verify clamp/visible validation with no invalid renderer request.",
        "A5-T06-minimum-custom-clamp",
        "validation-screenshot+unit",
        "viewport-resolution-impl/scratch/A5-T06/a5_t06_02_min_feedback_64x64.png",
    ),
    _row(
        "AC-15",
        ("A5-T02", "A5-T05"),
        "Enter non-positive custom values and verify previous valid dimensions recover or clamp without invalid render.",
        "A5-T05-non-positive-revert",
        "validation-screenshot+unit",
        "viewport-resolution-impl/scratch/A5-T05/a5_t05_02_width_zero_error_restored.png",
        "viewport-resolution-impl/scratch/A5-T05/a5_t05_03_height_negative_error_restored.png",
    ),
    _row(
        "AC-16",
        ("A2-T07", "A5-T01", "A8-T03"),
        "Enter unsaved 1500x1000 and verify Custom sentinel checked until a saved/preset row matches.",
        "A8-T03-04-custom-sentinel-selected",
        "acceptance-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T03/a8_t03_04_height_keyboard_1000_custom_selected.png",
    ),
    _row(
        "AC-17",
        ("A1-T04", "A5-T08", "A5-T09", "A8-T03"),
        "Save unsaved 1500x1000 as Review and verify saved row appears and is checked/current.",
        "A8-T03-06-review-saved-selected",
        "acceptance-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T03/a8_t03_06_review_saved_row_selected.png",
    ),
    _row(
        "AC-18",
        ("A5-T08", "A5-T09"),
        "Open save dialog and verify empty/space-only name remains rejected with inline error.",
        "A5-T09-empty-name-validation",
        "dialog-screenshot+unit",
        "viewport-resolution-impl/scratch/A5-T09/a5_t09_02_empty_name_error_dialog_open.png",
        "viewport-resolution-impl/scratch/A5-T09/a5_t09_03_spaces_only_error_dialog_open.png",
    ),
    _row(
        "AC-19",
        ("A5-T09",),
        "Attempt a second Review save and verify duplicate-name rejection leaves the list unchanged.",
        "A5-T09-duplicate-name-validation",
        "dialog-screenshot+unit",
        "viewport-resolution-impl/scratch/A5-T09/a5_t09_05_duplicate_review_error_dialog_open.png",
    ),
    _row(
        "AC-20",
        ("A5-T07", "A8-T03"),
        "Set duplicate preset/saved dimensions and verify save disabled or existing saved row remains accepted.",
        "A8-T03-07-duplicate-dimensions-no-second-review",
        "acceptance-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T03/a8_t03_07_duplicate_dimensions_no_second_review.png",
        "viewport-resolution-impl/scratch/A8-T03/a8_t03_07a_duplicate_save_disabled_hover.png",
    ),
    _row(
        "AC-21",
        ("A5-T10", "A5-T11", "A6-T04"),
        "Delete saved Review and verify the row disappears, the list updates, and selection recovers safely.",
        "A5-T10-delete-review-selection-recovers",
        "delete-screenshot+unit",
        "viewport-resolution-impl/scratch/A5-T10/a5_t10_03_review_row_gone_after_delete.png",
        "viewport-resolution-impl/scratch/A5-T10/a5_t10_04_reopen_review_absent_rows_intact.png",
    ),
    _row(
        "AC-22",
        ("A3-T05", "A4-T09", "A6-T06", "A8-T02"),
        "Select HD720P in a non-16:9 viewport, enable Fill Viewport, and verify HUD/render preserves one requested side while extending the other.",
        "remaining-issues-hd720-fill-extends-from-requested",
        "regression-screenshot+unit",
        "viewport-resolution-impl/scratch/remaining-issues/after_04_hd720_fill_off_hud_1280x720.png",
        "viewport-resolution-impl/scratch/remaining-issues/after_05_hd720_fill_on_hud_extended.png",
    ),
    _row(
        "AC-23",
        ("A4-T09", "A8-T02"),
        "Switch fixed fill on, then Viewport, then fixed again and verify fill policy restores truthfully.",
        "A8-T02-05-square-fill-restored",
        "acceptance-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T02/a8_t02_05_reopen_square_fill_restored.png",
        "viewport-resolution-impl/scratch/A8-T02/a8_t02_06_viewport_mode_fill_disabled.png",
    ),
    _row(
        "AC-24",
        ("A1-T07", "A6-T01", "A6-T03", "A6-T04"),
        "Apply an external per-viewport resolution change and verify menu, fields, render, and HUD synchronize.",
        "A6-T04-external-resolution-open-menu-sync",
        "sync-screenshot+unit",
        "viewport-resolution-impl/scratch/A6-T04/a6_t04_02_open_menu_hd1080p_refreshed.png",
        "viewport-resolution-impl/scratch/A6-T04/a6_t04_04_companion_viewport_refreshed.png",
    ),
    _row(
        "AC-25",
        ("A1-T07", "A2-T05", "A6-T02", "A8-T05"),
        "Append a valid custom row externally or through another viewport and verify open menus show it without restart.",
        "A8-T05-05-review-shared-in-b-not-selected",
        "multi-viewport-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T05/a8_t05_05_viewport_b_review_visible_not_selected.png",
    ),
    _row(
        "AC-26",
        ("A1-T05", "A2-T05", "A7-T03"),
        "Load corrupt custom data with one valid row and verify invalid entries are suppressed without crash.",
        "A7-T03-corrupt-list-valid-row-visible",
        "guardrail-screenshot+unit",
        "viewport-resolution-impl/scratch/A7-T03/a7_t03_02_valid_rows_invalid_absent.png",
    ),
    _row(
        "AC-27",
        ("A1-T06", "A6-T03", "A8-T04"),
        "Save Review, scale 50%, quit/relaunch, and verify restored row, scale, fill, and HUD 750x500.",
        "A8-T04-07-restart-reopen-stable",
        "restart-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T04/a8_t04_05_relaunch_menu_review_scale50_fill_off.png",
        "viewport-resolution-impl/scratch/A8-T04/a8_t04_07_reopen_stable_no_duplicate_review.png",
    ),
    _row(
        "AC-28",
        ("A0-T03", "A1-T03", "A6-T08", "A8-T05"),
        "Use two viewports with stable IDs and verify independent active state with shared Review row.",
        "A8-T05-07-multi-viewport-final-independence",
        "multi-viewport-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T05/a8_t05_07_a_scale_change_b_unchanged_final.png",
    ),
    _row(
        "AC-29",
        ("A3-T06", "A3-T08", "A8-T01", "A8-T02"),
        "Record renderer frame dimensions for viewport, fixed, scaled, and fill cases and compare to effective formulas.",
        "A8-effective-render-frame-dimensions",
        "supplemental-unit+acceptance",
        "ovui-widgets/tests/test_viewport_resolution_effective.py",
        "ovui-widgets/tests/test_viewport_widget.py",
    ),
    _row(
        "AC-30",
        ("A3-T07", "A6-T07", "A8-T06"),
        "Select HD1080P in an OpenUSD-backed viewport and verify session RenderProduct updates while root stays clean.",
        "A8-T06-03-session-1920-root-clean",
        "layer-state-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T06/a8_t06_03_layer_report_session_1920_root_clean.png",
        "viewport-resolution-impl/scratch/A8-T06/a8_t06_06_final_root_clean_no_dirty_prompt.png",
    ),
    _row(
        "AC-31",
        ("A6-T05", "A7-T06"),
        "Rapidly resize in Viewport mode and verify coalescing, responsive toolbar/menu, and final HUD update.",
        "A7-T06-resize-storm-final-state",
        "resilience-screenshot+unit",
        "viewport-resolution-impl/scratch/A7-T06/a7_t06_05_resize_storm_with_menu_open_settled.png",
    ),
    _row(
        "AC-32",
        ("A6-T03", "A6-T04", "A6-T07", "A8-T01", "A8-T03"),
        "Select modes, edit custom size, scale, and render frames while row, label, fields, and HUD stay synchronized.",
        "A8-T03-06-review-hud-menu-sync",
        "acceptance-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T03/a8_t03_06_review_saved_row_selected.png",
        "viewport-resolution-impl/scratch/A8-T03/a8_t03_06b_review_saved_hud_1500x1000.png",
    ),
    _row(
        "AC-33",
        ("A6-T09",),
        "Destroy a viewport with menus/dialogs open and verify subscriptions cancel and no stale callbacks fire.",
        "A6-T09-05-close-after-resize-no-stale-surface",
        "lifecycle-screenshot+unit",
        "viewport-resolution-impl/scratch/A6-T09/a6_t09_05_close_after_resize_no_stale_surface.png",
    ),
    _row(
        "AC-34",
        ("A7-T08",),
        "Run ovui-only/missing-icon profiles and verify Settings -> Viewport remains operable without Kit extensions.",
        "A7-T08-05-ovui-only-selection-operable",
        "guardrail-screenshot+unit",
        "viewport-resolution-impl/scratch/A7-T08/a7_t08_05_ovui_only_selection_operable.png",
    ),
    _row(
        "AC-35",
        ("A7-T09", "A8-T01", "A8-T02", "A8-T03", "A8-T07"),
        "Use screenshot-first keyboard/mouse flows to verify toolbar, menus, rows, custom editor, scale/fill, HUD, and matrix review.",
        "A8-T07-05-no-orphans-filter",
        "screenshot-first-matrix+acceptance",
        "viewport-resolution-impl/scratch/A7-T09/a7_t09_10_no_renderer_disabled_focus_reasons.png",
        "viewport-resolution-impl/scratch/A8-T07/a8_t07_05_no_orphans_filter.png",
    ),
)


FR_NFR_COVERAGE_ROWS: tuple[CoverageRow, ...] = (
    _row(
        "FR-GROUP-ENTRY-MENU",
        ("A0-T05", "A4-T01", "A4-T02", "A4-T03", "A8-T01"),
        "FR-01 through FR-05: Settings entry, stable contribution ID, toolbar order, current label, and Viewport menu structure.",
        "FR-ENTRY-MENU-A8-T01",
        "grouped-fr-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T01/a8_t01_01_normal_openusd_viewport_hud.png",
        "viewport-resolution-impl/scratch/A8-T01/a8_t01_02_settings_one_viewport_item.png",
    ),
    _row(
        "FR-GROUP-CATALOG-SELECTION",
        ("A2-T01", "A2-T07", "A4-T04", "A4-T08", "A7-T04"),
        "FR-06 through FR-14: radio selection, Viewport row, presets, fixed writes, Viewport fallback, and over-max policy.",
        "FR-CATALOG-SELECTION-A8-T01-A7-T04",
        "grouped-fr-unit+guardrail",
        "viewport-resolution-impl/scratch/A8-T01/a8_t01_04_hd1080p_selected_checked.png",
        "viewport-resolution-impl/scratch/A7-T04/a7_t04_02_5k_disabled_reason.png",
    ),
    _row(
        "FR-GROUP-CUSTOM-SAVE-DELETE",
        ("A5-T01", "A5-T07", "A5-T09", "A5-T10", "A8-T03"),
        "FR-15 through FR-24: custom fields, ratio/link behavior, validation, save, append, delete, and selection recovery.",
        "FR-CUSTOM-A8-T03-A5",
        "grouped-fr-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T03/a8_t03_02_inline_custom_row_visible.png",
        "viewport-resolution-impl/scratch/A8-T03/a8_t03_06_review_saved_row_selected.png",
    ),
    _row(
        "FR-GROUP-SCALE-FILL-EFFECTIVE-HUD",
        ("A3-T02", "A3-T05", "A3-T06", "A4-T09", "A6-T07", "A8-T01", "A8-T02"),
        "FR-25 through FR-32 plus NFR-01/NFR-02/NFR-07/NFR-10: scale, fill, effective size, render frame, HUD, watches, and no per-frame writes.",
        "FR-SCALE-FILL-HUD-A8-T01-T02",
        "grouped-fr-acceptance+unit",
        "viewport-resolution-impl/scratch/A8-T01/a8_t01_05b_render_scale_50_hud_960x540.png",
        "viewport-resolution-impl/scratch/remaining-issues/after_05_hd720_fill_on_hud_extended.png",
    ),
    _row(
        "FR-GROUP-GUARDRAILS-LIFECYCLE",
        ("A6-T09", "A7-T01", "A7-T02", "A7-T03", "A7-T05", "A7-T06", "A7-T07"),
        "FR-33 through FR-40 plus NFR-03: lifecycle cleanup, missing capability states, corrupt lists, unsupported adapter, resize storm, and menu failure isolation.",
        "FR-GUARDRAILS-A6-A7",
        "grouped-fr-guardrail+unit",
        "viewport-resolution-impl/scratch/A6-T09/a6_t09_05_close_after_resize_no_stale_surface.png",
        "viewport-resolution-impl/scratch/A7-T07/a7_t07_05_reopen_same_fallback.png",
    ),
    _row(
        "FR/NFR-ROOT-LAYER-CLEAN",
        ("A3-T07", "A8-T06"),
        "FR-30 and NFR-08: OpenUSD RenderProduct resolution changes are authored in session scaffolding and do not dirty the user's root layer.",
        "A8-T06-root-layer-clean",
        "layer-state-screenshot+unit",
        "viewport-resolution-impl/scratch/A8-T06/a8_t06_03_layer_report_session_1920_root_clean.png",
        "viewport-resolution-impl/scratch/A8-T06/a8_t06_05_layer_report_session_960_root_clean.png",
    ),
    _row(
        "FR/NFR-NO-KIT-RUNTIME",
        ("A7-T08",),
        "FR-41, FR-42, and NFR-10: feature operates with ovui/ovui-widgets primitives and no Kit extension runtime dependency.",
        "A7-T08-no-kit-runtime-boundary",
        "ovui-only-screenshot+unit",
        "viewport-resolution-impl/scratch/A7-T08/a7_t08_05_ovui_only_selection_operable.png",
    ),
    _row(
        "FR/NFR-ACCESSIBILITY-SCREENSHOT-FIRST",
        ("A7-T09", "A8-T07"),
        "NFR-04, NFR-05, NFR-09, and AC-35: deterministic inspector targets, labels, tooltips, compact geometry, and screenshot-first evidence review.",
        "A8-T07-visible-matrix-review",
        "screenshot-first-matrix+keyboard-qa",
        "viewport-resolution-impl/scratch/A7-T09/a7_t09_02_settings_focus_tooltip.png",
        "viewport-resolution-impl/scratch/A8-T07/a8_t07_01_matrix_header.png",
    ),
)

COVERAGE_MATRIX: tuple[CoverageRow, ...] = AC_COVERAGE_MATRIX + FR_NFR_COVERAGE_ROWS


def validate_coverage_matrix(rows: tuple[CoverageRow, ...]) -> list[str]:
    errors: list[str] = []
    ac_ids = [row.requirement_id for row in rows if AC_ID_RE.match(row.requirement_id)]
    missing = sorted(set(EXPECTED_AC_IDS).difference(ac_ids))
    if missing:
        errors.append(f"missing AC rows: {', '.join(missing)}")
    unexpected = sorted(set(ac_ids).difference(EXPECTED_AC_IDS))
    if unexpected:
        errors.append(f"unexpected AC rows: {', '.join(unexpected)}")
    duplicates = sorted({item for item in ac_ids if ac_ids.count(item) > 1})
    if duplicates:
        errors.append(f"duplicate AC rows: {', '.join(duplicates)}")

    for row in rows:
        prefix = row.requirement_id
        if not row.owner_tickets:
            errors.append(f"{prefix}: blank owner tickets")
        elif not any(TICKET_RE.match(ticket) for ticket in row.owner_tickets):
            errors.append(f"{prefix}: no backward ticket owner")
        if not row.scenario.strip():
            errors.append(f"{prefix}: blank scenario")
        if not row.evidence_id.strip():
            errors.append(f"{prefix}: blank evidence id")
        if not row.evidence_type.strip():
            errors.append(f"{prefix}: blank evidence type")
        if not row.evidence_refs or not all(ref.strip() for ref in row.evidence_refs):
            errors.append(f"{prefix}: blank evidence references")
        if row.status != "PASS":
            errors.append(f"{prefix}: non-pass status {row.status!r}")
        evidence_payload = " ".join(
            (row.evidence_id, row.evidence_type, *row.evidence_refs)
        ).lower()
        for token in OBSOLETE_EVIDENCE_TOKENS:
            if token in evidence_payload:
                errors.append(f"{prefix}: obsolete evidence token {token}")
    return errors


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "viewport-resolution-impl").exists() and (
            candidate / "ovui-widgets"
        ).exists():
            return candidate
    return Path(__file__).resolve().parents[2]


def _repo_relative_ref_exists(ref: str) -> bool:
    if not ref.startswith(("viewport-resolution-impl/", "ovui-widgets/")):
        return True
    return (_repo_root() / ref).exists()


def _local_evidence_skip_reason() -> str | None:
    evidence_root = _repo_root() / "viewport-resolution-impl"
    if not evidence_root.exists():
        return (
            "local viewport-resolution-impl evidence artifacts are absent; "
            "skipping orchestration-only screenshot file validation"
        )
    return None


def _skip_without_local_evidence() -> None:
    reason = _local_evidence_skip_reason()
    if reason is not None:
        pytest.skip(reason)


def test_acceptance_matrix_contains_ac_01_through_ac_35_exactly_once() -> None:
    errors = validate_coverage_matrix(COVERAGE_MATRIX)
    assert errors == []
    assert tuple(row.requirement_id for row in AC_COVERAGE_MATRIX) == EXPECTED_AC_IDS


def test_acceptance_matrix_has_grouped_fr_nfr_traceability() -> None:
    group_ids = {row.requirement_id for row in FR_NFR_COVERAGE_ROWS}
    assert "FR/NFR-ROOT-LAYER-CLEAN" in group_ids
    assert "FR/NFR-NO-KIT-RUNTIME" in group_ids
    assert "FR/NFR-ACCESSIBILITY-SCREENSHOT-FIRST" in group_ids
    for row in FR_NFR_COVERAGE_ROWS:
        assert row.owner_tickets
        assert row.scenario
        assert row.evidence_id
        assert row.evidence_refs
        assert row.status == "PASS"


def test_acceptance_matrix_repo_relative_evidence_refs_exist() -> None:
    _skip_without_local_evidence()
    missing = [
        (row.requirement_id, ref)
        for row in COVERAGE_MATRIX
        for ref in row.evidence_refs
        if not _repo_relative_ref_exists(ref)
    ]
    assert missing == []


def test_acceptance_matrix_evidence_guard_detects_clean_checkout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        __name__ + "._repo_root",
        lambda: tmp_path,
    )
    assert "viewport-resolution-impl evidence artifacts are absent" in (
        _local_evidence_skip_reason() or ""
    )


def test_acceptance_matrix_rejects_missing_duplicate_blank_and_obsolete_rows() -> None:
    missing_ac_35 = tuple(
        row for row in COVERAGE_MATRIX if row.requirement_id != "AC-35"
    )
    assert "missing AC rows: AC-35" in validate_coverage_matrix(missing_ac_35)

    duplicate = COVERAGE_MATRIX + (AC_COVERAGE_MATRIX[0],)
    assert "duplicate AC rows: AC-01" in validate_coverage_matrix(duplicate)

    blank_owner = (replace(AC_COVERAGE_MATRIX[0], owner_tickets=()),) + COVERAGE_MATRIX[1:]
    assert "AC-01: blank owner tickets" in validate_coverage_matrix(blank_owner)

    blank_scenario = (
        replace(AC_COVERAGE_MATRIX[0], scenario=""),
    ) + COVERAGE_MATRIX[1:]
    assert "AC-01: blank scenario" in validate_coverage_matrix(blank_scenario)

    blank_evidence = (
        replace(AC_COVERAGE_MATRIX[0], evidence_id="", evidence_refs=()),
    ) + COVERAGE_MATRIX[1:]
    errors = validate_coverage_matrix(blank_evidence)
    assert "AC-01: blank evidence id" in errors
    assert "AC-01: blank evidence references" in errors

    obsolete = (
        replace(
            AC_COVERAGE_MATRIX[0],
            evidence_id="obsolete-overlay-panel-evidence",
        ),
    ) + COVERAGE_MATRIX[1:]
    assert (
        "AC-01: obsolete evidence token obsolete-overlay-panel-evidence"
        in validate_coverage_matrix(obsolete)
    )

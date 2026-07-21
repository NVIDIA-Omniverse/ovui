# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest


FINAL_EVIDENCE_ROOT = "viewport-resolution-impl/scratch/A8-T08"
OBSOLETE_UI_KEYS = (
    "overlay_panel",
    "standalone_resolution_button",
    "toolbar_resolution_text_mirror",
)
OBSOLETE_UI_ABSENT = {key: "ABSENT" for key in OBSOLETE_UI_KEYS}

FINAL_ACCEPTANCE_ENVIRONMENT = {
    "screenshot_tool": "omni.ui.testing.capture_screenshot",
    "headless": "OMNIUI_HEADLESS=1",
    "backend": "OMNIUI_BACKEND=vulkan",
    "viewport_size": "1280x720 review window",
    "interaction_model": "visible mouse_move/mouse_click review controls",
}


@dataclass(frozen=True)
class FinalEvidenceEntry:
    index: int
    output_ref: str
    label: str
    scenario: str
    source_refs: tuple[str, ...]
    source_tickets: tuple[str, ...]
    expected_visible: tuple[str, ...]
    status: str = "PASS"
    obsolete_ui: dict[str, str] | None = None

    def obsolete_status(self) -> dict[str, str]:
        return self.obsolete_ui or OBSOLETE_UI_ABSENT


def _entry(
    index: int,
    name: str,
    label: str,
    scenario: str,
    source_refs: tuple[str, ...],
    source_tickets: tuple[str, ...],
    expected_visible: tuple[str, ...],
) -> FinalEvidenceEntry:
    return FinalEvidenceEntry(
        index=index,
        output_ref=f"{FINAL_EVIDENCE_ROOT}/{name}",
        label=label,
        scenario=scenario,
        source_refs=source_refs,
        source_tickets=source_tickets,
        expected_visible=expected_visible,
    )


FINAL_ACCEPTANCE_EVIDENCE: tuple[FinalEvidenceEntry, ...] = (
    _entry(
        1,
        "a8_t08_01_final_launch_toolbar_hud.png",
        "Normal final launch: toolbar order, HUD, no obsolete UI",
        "Normal OpenUSD-backed launch shows Settings, Move, Rotate, Scale, Camera and existing HUD RES.",
        ("viewport-resolution-impl/scratch/A8-T01/a8_t01_01_normal_openusd_viewport_hud.png",),
        ("A8-T01", "A4-T01", "A6-T07"),
        (
            "Toolbar order: Settings, Move, Rotate, Scale, Camera",
            "Existing HUD RES line visible",
            "No overlay panel / standalone Resolution button / toolbar text mirror",
        ),
    ),
    _entry(
        2,
        "a8_t08_02_settings_one_viewport_item.png",
        "Settings menu with one Viewport item",
        "Visible Settings click opens one top-level Viewport item matching the corrected SRD mockup.",
        ("viewport-resolution-impl/scratch/A8-T01/a8_t01_02_settings_one_viewport_item.png",),
        ("A8-T01", "A4-T02"),
        ("Settings menu open", "Single Viewport item", "No extra Resolution button/readout"),
    ),
    _entry(
        3,
        "a8_t08_03_render_resolution_rows_saved_delete.png",
        "Render Resolution submenu rows, saved rows, delete affordance",
        "Render Resolution submenu shows current label, preset rows, Custom sentinel, saved Review row, and saved-row affordances.",
        (
            "viewport-resolution-impl/scratch/A8-T03/a8_t03_02_inline_custom_row_visible.png",
            "viewport-resolution-impl/scratch/A8-T03/a8_t03_06_review_saved_row_selected.png",
            "viewport-resolution-impl/scratch/A5-T10/a5_t10_01_review_row_delete_affordance.png",
        ),
        ("A8-T03", "A5-T10", "A4-T04", "A4-T05"),
        (
            "Current-selection label visible",
            "Preset rows with ratio badges",
            "Custom sentinel and saved Review row",
            "Delete affordance for saved rows",
        ),
    ),
    _entry(
        4,
        "a8_t08_04_inline_custom_non_hiding_row.png",
        "Embedded Custom Resolution row",
        "Inline Custom Resolution row remains in-menu with Width/Height labels, fields, link, ratio combo, and save affordance.",
        (
            "viewport-resolution-impl/scratch/A8-T03/a8_t03_02_inline_custom_row_visible.png",
            "viewport-resolution-impl/scratch/A8-T03/a8_t03_03_width_keyboard_1500_menu_open.png",
        ),
        ("A8-T03", "A4-T06", "A5-T01"),
        (
            "Width and Height labels/fields",
            "Link toggle",
            "Ratio combo",
            "Save icon",
            "Menu remains non-hiding during field interaction",
        ),
    ),
    _entry(
        5,
        "a8_t08_05_save_dialog_validation_flow.png",
        "Save Custom Viewport Resolution dialog",
        "Save dialog opens from the inline save affordance and validates the name path without replacing the inline row.",
        (
            "viewport-resolution-impl/scratch/A8-T03/a8_t03_05_save_dialog_review_dimensions.png",
            "viewport-resolution-impl/scratch/A5-T09/a5_t09_02_empty_name_error_dialog_open.png",
            "viewport-resolution-impl/scratch/A5-T09/a5_t09_05_duplicate_review_error_dialog_open.png",
        ),
        ("A8-T03", "A5-T08", "A5-T09"),
        (
            "Modal title visible",
            "Active dimensions visible",
            "Name validation path visible",
            "Normal Area-5 dialog behavior",
        ),
    ),
    _entry(
        6,
        "a8_t08_06_render_scale_hud_effective.png",
        "Render Scale flow and HUD effective size",
        "HD1080P remains selected while Render Scale 50% changes HUD/render effective size to 960x540.",
        (
            "viewport-resolution-impl/scratch/A8-T01/a8_t01_05_render_scale_50_checked.png",
            "viewport-resolution-impl/scratch/A8-T01/a8_t01_05b_render_scale_50_hud_960x540.png",
        ),
        ("A8-T01", "A4-T09", "A6-T07"),
        (
            "Render Scale reads 50%",
            "HD1080P remains current/checked",
            "HUD RES 960x540",
        ),
    ),
    _entry(
        7,
        "a8_t08_07_fill_viewport_hud_render_change.png",
        "Fill Viewport flow and render/HUD change",
        "HD720P fixed selection keeps HD720P checked while Fill Viewport changes HUD/render from 1280x720 to an extended 1394x720 in the final QA viewport.",
        (
            "viewport-resolution-impl/scratch/remaining-issues/after_04_hd720_fill_off_hud_1280x720.png",
            "viewport-resolution-impl/scratch/remaining-issues/after_05_hd720_fill_on_hud_extended.png",
        ),
        ("A8-T02", "A3-T05", "A6-T06", "A6-T07"),
        (
            "Fill Viewport checked",
            "HD720P remains selected",
            "HUD RES 1394x720 after fill",
        ),
    ),
    _entry(
        8,
        "a8_t08_08_guardrail_disabled_reason.png",
        "Guardrail disabled state with visible reason",
        "Degraded profiles keep Settings -> Viewport reachable and disable affected rows with visible reasons/no fake apply.",
        (
            "viewport-resolution-impl/scratch/A7-T01/a7_t01_03_render_resolution_disabled_reason.png",
            "viewport-resolution-impl/scratch/A7-T05/a7_t05_02_fixed_rows_disabled_reason.png",
            "viewport-resolution-impl/scratch/A7-T05/a7_t05_03_hd1080p_disabled_no_fake_apply.png",
        ),
        ("A7-T01", "A7-T05"),
        (
            "Settings and Viewport remain reachable",
            "Disabled reason visible",
            "No fake selected row/HUD apply",
        ),
    ),
    _entry(
        9,
        "a8_t08_09_persistence_after_restart.png",
        "Persistence after real restart",
        "Review 1500x1000, scale 50%, Fill off, and HUD 750x500 survive visible quit/relaunch.",
        (
            "viewport-resolution-impl/scratch/A8-T04/a8_t04_03_file_exit_before_quit.png",
            "viewport-resolution-impl/scratch/A8-T04/a8_t04_05_relaunch_menu_review_scale50_fill_off.png",
            "viewport-resolution-impl/scratch/A8-T04/a8_t04_06_relaunch_hud_750x500.png",
        ),
        ("A8-T04", "A1-T06"),
        (
            "Real quit/relaunch path recorded",
            "Review restored",
            "Render Scale 50% restored",
            "HUD RES 750x500",
        ),
    ),
    _entry(
        10,
        "a8_t08_10_multi_viewport_independence.png",
        "Two-viewport independence with shared saved rows",
        "Two visible viewports keep independent active state while Review is shared through the saved custom list.",
        (
            "viewport-resolution-impl/scratch/A8-T05/a8_t05_01_two_viewports_initial.png",
            "viewport-resolution-impl/scratch/A8-T05/a8_t05_05_viewport_b_review_visible_not_selected.png",
            "viewport-resolution-impl/scratch/A8-T05/a8_t05_07_a_scale_change_b_unchanged_final.png",
        ),
        ("A8-T05", "A6-T08"),
        (
            "Two viewport HUDs visible",
            "Shared Review row visible",
            "Foreign active selection/HUD unchanged",
        ),
    ),
    _entry(
        11,
        "a8_t08_11_openusd_session_root_clean.png",
        "OpenUSD session-layer report and clean root layer",
        "Visible OpenUSD report shows session RenderProduct effective resolution and root-layer resolution edits clean/none.",
        (
            "viewport-resolution-impl/scratch/A8-T06/a8_t06_03_layer_report_session_1920_root_clean.png",
            "viewport-resolution-impl/scratch/A8-T06/a8_t06_05_layer_report_session_960_root_clean.png",
            "viewport-resolution-impl/scratch/A8-T06/a8_t06_06_final_root_clean_no_dirty_prompt.png",
        ),
        ("A8-T06", "A3-T07"),
        (
            "Session RenderProduct resolution visible",
            "Root-layer resolution edits clean/none",
            "No root dirty prompt from resolution changes",
        ),
    ),
    _entry(
        12,
        "a8_t08_12_ac_matrix_no_orphans.png",
        "AC matrix no-orphans completion",
        "Coverage matrix proves AC-01 through AC-35 exactly once with no missing/duplicate/obsolete evidence rows.",
        (
            "viewport-resolution-impl/scratch/A8-T07/a8_t07_05_no_orphans_filter.png",
            "viewport-resolution-impl/scratch/A8-T07/a8_t07_07_restored_no_orphans_final.png",
        ),
        ("A8-T07",),
        (
            "No missing AC rows",
            "No duplicate AC rows",
            "No obsolete evidence rows",
            "Acceptance PASS",
        ),
    ),
    _entry(
        13,
        "a8_t08_13_final_mockup_conformance_checklist.png",
        "Final mockup conformance checklist",
        "Final review checklist marks SRD mockup conformance complete and obsolete UI absent.",
        (
            "viewport-resolution-impl/scratch/A8-T01/a8_t01_01_normal_openusd_viewport_hud.png",
            "viewport-resolution-impl/scratch/A8-T03/a8_t03_02_inline_custom_row_visible.png",
            "viewport-resolution-impl/scratch/A8-T07/a8_t07_07_restored_no_orphans_final.png",
        ),
        ("A8-T08", "A8-T07", "A8-T01", "A8-T03"),
        (
            "Mockup conformance complete",
            "Overlay panel absent",
            "Standalone Resolution button absent",
            "Toolbar resolution text mirror absent",
            "Only menu current label plus existing HUD RES are accepted readouts",
        ),
    ),
)


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


def validate_final_acceptance_evidence(
    entries: tuple[FinalEvidenceEntry, ...],
) -> list[str]:
    errors: list[str] = []
    expected_indices = list(range(1, 14))
    indices = [entry.index for entry in entries]
    if indices != expected_indices:
        errors.append(f"expected screenshot indices {expected_indices}, got {indices}")

    output_refs = [entry.output_ref for entry in entries]
    duplicates = sorted({ref for ref in output_refs if output_refs.count(ref) > 1})
    if duplicates:
        errors.append(f"duplicate output refs: {', '.join(duplicates)}")

    for entry in entries:
        prefix = f"A8-T08-{entry.index:02d}"
        if entry.status != "PASS":
            errors.append(f"{prefix}: non-pass status {entry.status!r}")
        if not entry.output_ref.startswith(FINAL_EVIDENCE_ROOT + "/"):
            errors.append(f"{prefix}: output ref outside A8-T08 scratch dir")
        for field_name in ("label", "scenario"):
            if not getattr(entry, field_name).strip():
                errors.append(f"{prefix}: blank {field_name}")
        if not entry.source_refs:
            errors.append(f"{prefix}: missing source refs")
        if not entry.source_tickets:
            errors.append(f"{prefix}: missing source tickets")
        if not entry.expected_visible:
            errors.append(f"{prefix}: missing expected visible labels")
        for key in OBSOLETE_UI_KEYS:
            if entry.obsolete_status().get(key) != "ABSENT":
                errors.append(f"{prefix}: obsolete UI {key} not absent")
    return errors


def final_acceptance_output_refs_exist() -> list[tuple[int, str]]:
    return [
        (entry.index, entry.output_ref)
        for entry in FINAL_ACCEPTANCE_EVIDENCE
        if not _repo_relative_ref_exists(entry.output_ref)
    ]


def test_final_acceptance_manifest_has_required_13_screenshots() -> None:
    assert validate_final_acceptance_evidence(FINAL_ACCEPTANCE_EVIDENCE) == []
    assert [entry.index for entry in FINAL_ACCEPTANCE_EVIDENCE] == list(range(1, 14))
    assert FINAL_ACCEPTANCE_EVIDENCE[-1].label == "Final mockup conformance checklist"


def test_final_acceptance_source_evidence_refs_exist() -> None:
    _skip_without_local_evidence()
    missing = [
        (entry.index, ref)
        for entry in FINAL_ACCEPTANCE_EVIDENCE
        for ref in entry.source_refs
        if not _repo_relative_ref_exists(ref)
    ]
    assert missing == []


def test_final_acceptance_output_review_screenshots_exist() -> None:
    _skip_without_local_evidence()
    assert final_acceptance_output_refs_exist() == []


def test_final_acceptance_evidence_guard_detects_clean_checkout(
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


def test_final_acceptance_rejects_missing_status_and_obsolete_ui() -> None:
    bad_status = (
        replace(FINAL_ACCEPTANCE_EVIDENCE[0], status="PENDING"),
    ) + FINAL_ACCEPTANCE_EVIDENCE[1:]
    assert "A8-T08-01: non-pass status 'PENDING'" in validate_final_acceptance_evidence(
        bad_status
    )

    bad_obsolete = (
        replace(
            FINAL_ACCEPTANCE_EVIDENCE[0],
            obsolete_ui={**OBSOLETE_UI_ABSENT, "overlay_panel": "PRESENT"},
        ),
    ) + FINAL_ACCEPTANCE_EVIDENCE[1:]
    assert (
        "A8-T08-01: obsolete UI overlay_panel not absent"
        in validate_final_acceptance_evidence(bad_obsolete)
    )


def test_final_acceptance_environment_metadata_is_present() -> None:
    assert FINAL_ACCEPTANCE_ENVIRONMENT["screenshot_tool"] == (
        "omni.ui.testing.capture_screenshot"
    )
    assert FINAL_ACCEPTANCE_ENVIRONMENT["headless"] == "OMNIUI_HEADLESS=1"
    assert FINAL_ACCEPTANCE_ENVIRONMENT["backend"] == "OMNIUI_BACKEND=vulkan"

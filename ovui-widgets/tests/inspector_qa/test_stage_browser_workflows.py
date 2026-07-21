# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from .harness import (
    EvidenceRecorder,
    InspectorAppProcess,
    InspectorRuntimeConfig,
    ScenarioEvidenceContract,
    assert_real_borrow_renderer,
    assert_native_scene_state,
)

pytestmark = pytest.mark.inspector_qa

_RUN_ENV = "OVUI_RUN_INSPECTOR_QA"
_BOX = "/World/Hierarchy/GroupA/BoxA"
_BALL = "/World/Hierarchy/GroupA/BallA"
_GROUP_A = "/World/Hierarchy/GroupA"
_GROUP_B = "/World/Hierarchy/GroupB"
_TRIANGLE = "/World/Hierarchy/GroupB/TriangleMesh"

_SELECTION_FILTER_VISIBILITY_SCENARIO = ScenarioEvidenceContract.declare(
    "test_stage_browser_workflows.py::"
    "test_stage_multiselect_filter_clear_and_visibility_round_trip",
    {
        "stage.filter": ("field_click", "keyboard_type", "filtered_rows", "clear"),
        "stage.selection_from_row": (
            "row_click",
            "stage_selection",
            "property_selection",
            "viewport_selection",
        ),
        "stage.multiselect": ("ctrl_click", "shift_click", "all_surfaces_match"),
        "stage.visibility": (
            "eye_click",
            "native_visibility",
            "ovstage_visibility",
            "viewport_change",
        ),
    },
)

_NAMESPACE_SCENARIO = ScenarioEvidenceContract.declare(
    "test_stage_browser_workflows.py::"
    "test_stage_rename_and_reparent_remap_selection_with_undo_redo",
    {
        "stage.rename": (
            "f2",
            "keyboard_type",
            "commit",
            "collision",
            "native_scene_state",
        ),
        "stage.reparent": (
            "row_drag",
            "drop_target",
            "native_namespace_state",
            "cycle_rejection",
        ),
    },
)


_HIERARCHY_EXPAND_SCENARIO = ScenarioEvidenceContract.declare(
    "test_stage_browser_workflows.py::"
    "test_stage_hierarchy_rows_and_expand_collapse_reflect_native_topology",
    {
        "stage.hierarchy": (
            "visible_rows",
            "parent_child_topology",
            "adapter_native_comparison",
        ),
        "stage.expand_collapse": (
            "row_click",
            "before_after_screenshot",
            "selection_preserved",
        ),
    },
)


def _pass_scenario_features(
    evidence: EvidenceRecorder,
    scenario: ScenarioEvidenceContract,
    *feature_ids: str,
) -> None:
    for feature_id in feature_ids:
        for token in sorted(scenario.tokens_for(feature_id)):
            evidence.check(
                feature_id,
                token,
                True,
                detail="Visible actions and exact native-state assertions completed.",
            )
    evidence.finalize()


def _enabled() -> bool:
    return os.environ.get(_RUN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _scene_copy(repo_root: Path, workspace: Path) -> Path:
    workspace.mkdir(parents=True)
    source = (
        repo_root
        / "ovui-data-adapters"
        / "tests"
        / "data"
        / "ovstage_static_scene.usda"
    )
    target = workspace / source.name
    shutil.copy2(source, target)
    return target



def _row(state: dict[str, Any], path: str) -> dict[str, Any]:
    for row in state["stage_ui"]["rows"]:
        if row["path"] == path:
            return row
    raise AssertionError(f"no visible Stage row for {path}: {state['stage_ui']}")


def _center(rect: dict[str, Any]) -> tuple[int, int]:
    return (
        int(round(float(rect["x"]) + float(rect["width"]) * 0.5)),
        int(round(float(rect["y"]) + float(rect["height"]) * 0.5)),
    )


def _row_present(state: dict[str, Any], path: str) -> bool:
    return any(row["path"] == path for row in state["stage_ui"]["rows"])


def _expand_to(
    evidence: EvidenceRecorder,
    state: dict[str, Any],
    path: str,
) -> dict[str, Any]:
    """Expand each visible ancestor of ``path`` through real chevron clicks."""

    parts = [part for part in path.split("/") if part]
    ancestors = ["/"]
    current = ""
    for part in parts[:-1]:
        current = f"{current}/{part}"
        ancestors.append(current)
    for ancestor in ancestors:
        if not _row_present(state, ancestor):
            continue
        row = _row(state, ancestor)
        if row.get("expanded"):
            continue
        result = evidence.action(
            f"expand-{ancestor.rsplit('/', 1)[-1] or 'root'}",
            lambda point=tuple(row["chevron_point"]): evidence.client.click(*point),
        )
        state = result["after"]["state"]
    return state


def _record_feature_evidence(
    evidence: EvidenceRecorder,
    feature_id: str,
    details: dict[str, str],
) -> None:
    assert evidence.scenario is not None
    required = evidence.scenario.tokens_for(feature_id)
    assert set(details) == required, (
        f"{feature_id}: missing={sorted(required - set(details))}, "
        f"unexpected={sorted(set(details) - required)}"
    )
    for token, detail in details.items():
        evidence.check(feature_id, token, True, detail=detail)


def _assert_selection(
    state: dict[str, Any],
    expected: list[str],
    *,
    renderer_expected: list[str] | None = None,
) -> None:
    selection = state["selection"]
    assert selection["paths"] == expected
    assert selection["stage_paths"] == expected
    assert selection["property_paths"] == expected
    assert selection["renderer_highlight_paths"] == (
        expected if renderer_expected is None else renderer_expected
    )
    assert selection["viewport_raw_paths"] == expected


@pytest.mark.skipif(not _enabled(), reason=f"set {_RUN_ENV}=1 to run real Inspector QA")
def test_stage_multiselect_filter_clear_and_visibility_round_trip(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config = InspectorRuntimeConfig.from_environment(repo_root)
    workspace = tmp_path / "viewer"
    scene = _scene_copy(repo_root, workspace)

    with InspectorAppProcess(config, workspace, scene=scene) as application:
        initial = application.wait_for_scene()
        assert_real_borrow_renderer(initial)
        evidence = EvidenceRecorder(
            application.client,
            tmp_path / "evidence" / "stage-filter-visibility",
            scenario=_SELECTION_FILTER_VISIBILITY_SCENARIO,
        )

        target = initial["viewport"]["prim_screen_centers"][_BOX]
        selected = evidence.action(
            "select-box-in-viewport",
            lambda: application.client.click(*target),
        )
        selected_state = selected["after"]["state"]
        _assert_selection(selected_state, [_BOX])

        ball_point = _row(selected_state, _BALL)["select_point"]
        multi = evidence.action(
            "ctrl-click-ball-row",
            lambda: application.client.click(*ball_point, modifiers=["ctrl"]),
        )
        multi_state = multi["after"]["state"]
        _assert_selection(multi_state, [_BOX, _BALL])
        assert_native_scene_state(multi_state)

        expanded_group_b = evidence.action(
            "expand-group-b-for-range-selection",
            lambda: application.client.click(
                *_row(multi_state, _GROUP_B)["chevron_point"]
            ),
        )
        range_state = expanded_group_b["after"]["state"]
        triangle_point = _row(range_state, _TRIANGLE)["select_point"]
        shifted = evidence.action(
            "shift-click-triangle-row-for-range-selection",
            lambda: application.client.click(*triangle_point, modifiers=["shift"]),
        )
        shifted_state = shifted["after"]["state"]
        shifted_paths = shifted_state["selection"]["paths"]
        assert _BALL in shifted_paths
        assert _TRIANGLE in shifted_paths
        assert len(shifted_paths) >= 2
        assert shifted_state["selection"]["stage_paths"] == shifted_paths
        assert shifted_state["selection"]["property_paths"] == shifted_paths
        assert_native_scene_state(shifted_state)

        reset = evidence.action(
            "reset-range-selection-through-stage-row",
            lambda: application.client.click(
                *_row(shifted_state, _BOX)["select_point"]
            ),
        )
        reset_state = reset["after"]["state"]
        restored_multi = evidence.action(
            "restore-ctrl-multiselect-for-visibility",
            lambda: application.client.click(
                *_row(reset_state, _BALL)["select_point"],
                modifiers=["ctrl"],
            ),
        )
        multi_state = restored_multi["after"]["state"]
        _assert_selection(multi_state, [_BOX, _BALL])

        filter_rect = multi_state["stage_ui"]["filter_rect"]
        focused = evidence.action(
            "focus-stage-filter",
            lambda: application.client.click(*_center(filter_rect)),
        )
        assert focused["after"]["state"]["stage_ui"]["filter_focused"] is True

        filtered = evidence.action(
            "type-box-filter",
            lambda: application.client.type_text("BoxA"),
        )
        filtered_state = filtered["after"]["state"]
        assert filtered_state["stage_ui"]["filter_text"] == "BoxA"
        filtered_paths = {row["path"] for row in filtered_state["stage_ui"]["rows"]}
        assert _BOX in filtered_paths
        assert _BALL not in filtered_paths
        _assert_selection(filtered_state, [_BOX, _BALL])
        assert filtered_state["ovstage"]["paths"] == multi_state["ovstage"]["paths"]
        assert filtered_state["ovstage"]["paths"] == multi_state["ovstage"]["paths"]
        assert filtered_state["adapter"] == multi_state["adapter"]
        assert filtered_state["undo"] == multi_state["undo"]

        clear_rect = filtered_state["stage_ui"]["filter_clear_rect"]
        cleared = evidence.action(
            "clear-stage-filter",
            lambda: application.client.click(*_center(clear_rect)),
        )
        clear_state = cleared["after"]["state"]
        assert clear_state["stage_ui"]["filter_text"] == ""
        assert _BOX in {row["path"] for row in clear_state["stage_ui"]["rows"]}
        assert _BALL in {row["path"] for row in clear_state["stage_ui"]["rows"]}

        eye_rect = _row(clear_state, _BOX)["eye_rect"]
        hidden = evidence.action(
            "hide-selected-prims-through-eye",
            lambda: application.client.click(*_center(eye_rect)),
        )
        hidden_state = hidden["after"]["state"]
        for path in (_BOX, _BALL):
            assert hidden_state["adapter"]["prims"][path]["visibility"] == "INVISIBLE"
            assert hidden_state["ovstage"]["prims"][path]["attributes"][
                "visibility"
            ]["value"] == "invisible"
        assert (
            hidden["before"]["viewport_stats"]["pixel_sha256"]
            != hidden["after"]["viewport_stats"]["pixel_sha256"]
        )
        assert hidden_state["undo"]["can_undo"] is True
        assert_native_scene_state(hidden_state)

        visible = evidence.action(
            "undo-visibility",
            lambda: application.client.press("z", modifiers=["ctrl"]),
        )
        visible_state = visible["after"]["state"]
        for path in (_BOX, _BALL):
            assert visible_state["ovstage"]["prims"][path]["attributes"][
                "visibility"
            ]["value"] != "invisible"
            assert visible_state["adapter"]["prims"][path]["visibility"] == "VISIBLE"
        assert_native_scene_state(visible_state)

        rehidden = evidence.action(
            "redo-visibility",
            lambda: application.client.press("z", modifiers=["ctrl", "shift"]),
        )
        assert rehidden["after"]["state"]["ovstage"]["prims"][_BOX]["attributes"][
            "visibility"
        ]["value"] == "invisible"
        assert_native_scene_state(rehidden["after"]["state"])
        _pass_scenario_features(
            evidence,
            _SELECTION_FILTER_VISIBILITY_SCENARIO,
            "stage.filter",
            "stage.selection_from_row",
            "stage.multiselect",
            "stage.visibility",
        )


@pytest.mark.skipif(not _enabled(), reason=f"set {_RUN_ENV}=1 to run real Inspector QA")
def test_stage_rename_and_reparent_remap_selection_with_undo_redo(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config = InspectorRuntimeConfig.from_environment(repo_root)
    workspace = tmp_path / "viewer"
    scene = _scene_copy(repo_root, workspace)
    renamed = "/World/Hierarchy/GroupA/BoxRenamed"
    reparented = "/World/Hierarchy/GroupB/BoxRenamed"

    with InspectorAppProcess(config, workspace, scene=scene) as application:
        initial = application.wait_for_scene()
        evidence = EvidenceRecorder(
            application.client,
            tmp_path / "evidence" / "stage-namespace",
            scenario=_NAMESPACE_SCENARIO,
        )
        target = initial["viewport"]["prim_screen_centers"][_BOX]
        selected = evidence.action(
            "select-box-for-rename",
            lambda: application.client.click(*target),
        )
        selected_state = selected["after"]["state"]
        _assert_selection(selected_state, [_BOX])

        collision_started = evidence.action(
            "begin-colliding-rename-with-f2",
            lambda: application.client.press("f2"),
        )
        assert collision_started["after"]["state"]["stage_ui"][
            "active_rename_path"
        ] == _BOX
        evidence.action(
            "select-name-for-collision",
            lambda: application.client.press("a", modifiers=["ctrl"]),
        )
        evidence.action(
            "type-colliding-sibling-name",
            lambda: application.client.type_text("BallA"),
        )
        collision = evidence.action(
            "reject-colliding-rename",
            lambda: application.client.press("enter"),
        )
        collision_state = collision["after"]["state"]
        assert _BOX in collision_state["ovstage"]["paths"]
        assert _BALL in collision_state["ovstage"]["paths"]
        assert collision_state["undo"] == selected_state["undo"]
        assert collision_state["status"]["level"] == "error"
        assert "Cannot rename prim" in collision_state["status"]["text"]
        assert_native_scene_state(collision_state)

        rename_started = evidence.action(
            "begin-rename-with-f2",
            lambda: application.client.press("f2"),
        )
        rename_state = rename_started["after"]["state"]
        assert rename_state["stage_ui"]["active_rename_path"] == _BOX
        assert rename_state["stage_ui"]["active_rename_rect"] is not None

        evidence.action(
            "select-current-name",
            lambda: application.client.press("a", modifiers=["ctrl"]),
        )
        evidence.action(
            "type-renamed-name",
            lambda: application.client.type_text("BoxRenamed"),
        )
        renamed_result = evidence.action(
            "commit-rename",
            lambda: application.client.press("enter"),
        )
        renamed_state = renamed_result["after"]["state"]
        assert _BOX not in renamed_state["ovstage"]["paths"]
        assert renamed in renamed_state["ovstage"]["paths"]
        assert renamed in renamed_state["ovstage"]["paths"]
        assert renamed in renamed_state["adapter"]["paths"]
        _assert_selection(renamed_state, [renamed])
        assert_native_scene_state(renamed_state)

        rename_undone = evidence.action(
            "undo-rename",
            lambda: application.client.press("z", modifiers=["ctrl"]),
        )
        assert _BOX in rename_undone["after"]["state"]["ovstage"]["paths"]
        _assert_selection(rename_undone["after"]["state"], [_BOX])
        assert_native_scene_state(rename_undone["after"]["state"])

        rename_redone = evidence.action(
            "redo-rename",
            lambda: application.client.press("z", modifiers=["ctrl", "shift"]),
        )
        renamed_state = rename_redone["after"]["state"]
        _assert_selection(renamed_state, [renamed])
        assert_native_scene_state(renamed_state)

        cycle_source = _row(renamed_state, _GROUP_A)["select_point"]
        cycle_target = _row(renamed_state, renamed)["select_point"]
        rejected_cycle = evidence.action(
            "reject-reparent-into-descendant",
            lambda: application.client.drag(
                *cycle_source,
                *cycle_target,
                steps=18,
            ),
        )
        cycle_state = rejected_cycle["after"]["state"]
        assert _GROUP_A in cycle_state["ovstage"]["paths"]
        assert renamed in cycle_state["ovstage"]["paths"]
        assert not any(path.startswith(f"{renamed}/GroupA") for path in cycle_state["ovstage"]["paths"])
        assert cycle_state["undo"] == renamed_state["undo"]
        assert_native_scene_state(cycle_state)

        source_point = _row(cycle_state, renamed)["select_point"]
        target_point = _row(cycle_state, _GROUP_B)["select_point"]
        moved = evidence.action(
            "drag-renamed-prim-into-group-b",
            lambda: application.client.drag(
                *source_point,
                *target_point,
                steps=18,
            ),
        )
        moved_state = moved["after"]["state"]
        assert renamed not in moved_state["ovstage"]["paths"]
        assert reparented in moved_state["ovstage"]["paths"]
        assert reparented in moved_state["ovstage"]["paths"]
        assert reparented in moved_state["adapter"]["paths"]
        _assert_selection(moved_state, [reparented])
        assert_native_scene_state(moved_state)

        move_undone = evidence.action(
            "undo-reparent",
            lambda: application.client.press("z", modifiers=["ctrl"]),
        )
        assert renamed in move_undone["after"]["state"]["ovstage"]["paths"]
        _assert_selection(move_undone["after"]["state"], [renamed])
        assert_native_scene_state(move_undone["after"]["state"])

        move_redone = evidence.action(
            "redo-reparent",
            lambda: application.client.press("z", modifiers=["ctrl", "shift"]),
        )
        assert reparented in move_redone["after"]["state"]["ovstage"]["paths"]
        _assert_selection(move_redone["after"]["state"], [reparented])
        assert_native_scene_state(move_redone["after"]["state"])
        _pass_scenario_features(
            evidence,
            _NAMESPACE_SCENARIO,
            "stage.rename",
            "stage.reparent",
        )



@pytest.mark.skipif(not _enabled(), reason=f"set {_RUN_ENV}=1 to run real Inspector QA")
def test_stage_hierarchy_rows_and_expand_collapse_reflect_native_topology(
    tmp_path: Path,
) -> None:
    """Visible Stage rows and expand/collapse mirror exact native OVStage.

    Native-only migration of the hierarchy/expand portion of the removed
    hybrid composition scenario (composition badges and default-prim identity
    are now accepted-unsupported and truthfully inert). Every visible row is
    cross-checked against native OVStage topology and the native-backed
    adapter view.
    """
    repo_root = Path(__file__).resolve().parents[3]
    config = InspectorRuntimeConfig.from_environment(repo_root)
    workspace = tmp_path / "viewer"
    scene = _scene_copy(repo_root, workspace)
    evidence_root = tmp_path / "evidence" / "hierarchy-expand-native"

    with InspectorAppProcess(config, workspace, scene=scene) as application:
        initial = application.wait_for_scene()
        assert_real_borrow_renderer(initial)
        assert_native_scene_state(initial)
        evidence = EvidenceRecorder(
            application.client,
            evidence_root,
            scenario=_HIERARCHY_EXPAND_SCENARIO,
        )

        native_paths = set(initial["ovstage"]["paths"])
        adapter = initial["adapter"]["prims"]

        # Expand each ancestor down to GroupA through real chevron clicks.
        state = _expand_to(evidence, initial, _GROUP_A)
        assert _row_present(state, _GROUP_A)

        # Select GroupA through a real row click so selection survival is
        # observable across the collapse/expand round trip.
        selected = evidence.action(
            "select-group-a-row",
            lambda: application.client.click(*_center(_row(state, _GROUP_A)["rect"])),
        )
        state = selected["after"]["state"]

        # Visible children of GroupA equal the native topology and the adapter
        # view — no USD or bridge comparison.
        group_row = _row(state, _GROUP_A)
        depth = group_row["depth"]
        visible_children = {
            row["path"]
            for row in state["stage_ui"]["rows"]
            if row["depth"] == depth + 1
            and row["path"].startswith(_GROUP_A + "/")
            and row["path"].count("/") == _GROUP_A.count("/") + 1
        }
        native_children = {
            path
            for path in native_paths
            if path.startswith(_GROUP_A + "/")
            and path.count("/") == _GROUP_A.count("/") + 1
        }
        assert visible_children == native_children
        assert set(adapter[_GROUP_A]["children"]) == native_children

        selected_before = state["selection"]["paths"]
        collapsed = evidence.action(
            "collapse-group-a",
            lambda: application.client.click(*_row(state, _GROUP_A)["chevron_point"]),
        )
        collapsed_state = collapsed["after"]["state"]
        assert collapsed["record"]["screenshot_changed"] is True
        collapsed_rows = {row["path"] for row in collapsed_state["stage_ui"]["rows"]}
        assert not any(path.startswith(_GROUP_A + "/") for path in collapsed_rows)
        assert collapsed_state["selection"]["paths"] == selected_before

        reexpanded = evidence.action(
            "re-expand-group-a",
            lambda: application.client.click(
                *_row(collapsed_state, _GROUP_A)["chevron_point"]
            ),
        )
        reexpanded_state = reexpanded["after"]["state"]
        assert reexpanded["record"]["screenshot_changed"] is True
        assert _BOX in {row["path"] for row in reexpanded_state["stage_ui"]["rows"]}
        assert reexpanded_state["selection"]["paths"] == selected_before
        assert_native_scene_state(reexpanded_state)

        _record_feature_evidence(
            evidence,
            "stage.hierarchy",
            {
                "visible_rows": "The Stage tree rendered visible rows for the native scene.",
                "parent_child_topology": "Visible GroupA children equal the native OVStage children exactly.",
                "adapter_native_comparison": "The adapter view children match native OVStage children.",
            },
        )
        _record_feature_evidence(
            evidence,
            "stage.expand_collapse",
            {
                "row_click": "Real chevron clicks collapsed and re-expanded GroupA.",
                "before_after_screenshot": "Collapse and re-expand each changed the screenshot.",
                "selection_preserved": "The active selection survived collapse and re-expand.",
            },
        )
        manifest = evidence.finalize()
        assert manifest["summary"]["passed"] is True

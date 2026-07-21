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
_TARGET_PATH = "/World/Hierarchy/GroupA/BoxA"
_FILE_MENU = (122, 10)
_FILE_NEW_ITEM = (135, 35)
_CREATE_MENU = (232, 10)
_CREATE_XFORM_ITEM = (240, 145)

_PICK_DELETE_HISTORY_SCENARIO = ScenarioEvidenceContract.declare(
    "test_ovstage_stage_workflows.py::"
    "test_viewport_pick_delete_undo_redo_preserve_native_scene_state",
    {
        "stage.selection_from_viewport": (
            "viewport_click",
            "selection_path",
            "renderer_pick_path",
            "screenshots",
        ),
        "stage.delete": (
            "delete_key",
            "native_absent",
            "row_absent",
            "screenshots",
        ),
        "history.undo": (
            "ctrl_z",
            "native_restore",
            "selection_restore",
        ),
        "history.redo": (
            "ctrl_shift_z",
            "native_reapply",
        ),
        "renderer.initial_frame": (
            "real_ovrtx",
            "borrow_attach",
            "nonblack_viewport",
            "screenshot",
        ),
        "renderer.point_pick": (
            "viewport_click",
            "renderer_pick_path",
            "selection_bus",
        ),
    },
)


def _enabled() -> bool:
    return os.environ.get(_RUN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


_CREATE_XFORM_SCENARIO = ScenarioEvidenceContract.declare(
    "test_ovstage_stage_workflows.py::"
    "test_create_xform_through_visible_menu_populates_native_ovstage",
    {
        "create.xform": (
            "menu_click",
            "xform_schema",
            "ovstage_path",
        ),
    },
)


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


@pytest.mark.skipif(not _enabled(), reason=f"set {_RUN_ENV}=1 to run real Inspector QA")
def test_viewport_pick_delete_undo_redo_preserve_native_scene_state(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    source_scene = (
        repo_root
        / "ovui-data-adapters"
        / "tests"
        / "data"
        / "ovstage_static_scene.usda"
    )
    config = InspectorRuntimeConfig.from_environment(repo_root)
    workspace = tmp_path / "viewer"
    workspace.mkdir(parents=True)
    scene = workspace / "ovstage_static_scene.usda"
    shutil.copy2(source_scene, scene)
    evidence_root = tmp_path / "evidence" / "stage-delete-undo-redo"

    with InspectorAppProcess(config, workspace, scene=scene) as application:
        initial = application.wait_for_scene()
        assert_real_borrow_renderer(initial)
        assert_native_scene_state(initial)
        target = initial.get("viewport", {}).get("prim_screen_centers", {}).get(
            _TARGET_PATH
        )
        assert target is not None, initial.get("viewport")

        evidence = EvidenceRecorder(
            application.client,
            evidence_root,
            scenario=_PICK_DELETE_HISTORY_SCENARIO,
        )
        selected = evidence.action(
            "select-box-through-viewport",
            lambda: application.client.click(int(target[0]), int(target[1])),
        )
        assert selected["before"]["viewport_stats"]["max_channel_range"] >= 32
        assert selected["before"]["viewport_stats"]["nonblack_pixels"] > 0
        selected_state = selected["after"]["state"]
        assert selected_state["selection"]["paths"] == [_TARGET_PATH]
        assert selected_state["renderer"]["last_pick_path"] == _TARGET_PATH
        assert_native_scene_state(selected_state)

        deleted = evidence.action(
            "delete-selected-prim",
            lambda: application.client.press("delete"),
        )
        deleted_state = deleted["after"]["state"]
        assert _TARGET_PATH not in deleted_state["ovstage"]["paths"]
        assert _TARGET_PATH not in deleted_state["adapter"]["paths"]
        assert _TARGET_PATH not in {
            row["path"] for row in deleted_state["stage_ui"]["rows"]
        }
        assert deleted_state["selection"]["paths"] == []
        assert deleted_state["undo"]["can_undo"] is True
        assert_native_scene_state(deleted_state)

        restored = evidence.action(
            "undo-delete",
            lambda: application.client.press("z", modifiers=["ctrl"]),
        )
        restored_state = restored["after"]["state"]
        assert _TARGET_PATH in restored_state["ovstage"]["paths"]
        assert _TARGET_PATH in restored_state["adapter"]["paths"]
        assert _TARGET_PATH in {
            row["path"] for row in restored_state["stage_ui"]["rows"]
        }
        assert restored_state["selection"]["paths"] == [_TARGET_PATH]
        assert_native_scene_state(restored_state)

        redone = evidence.action(
            "redo-delete",
            lambda: application.client.press("z", modifiers=["ctrl", "shift"]),
        )
        redone_state = redone["after"]["state"]
        assert _TARGET_PATH not in redone_state["ovstage"]["paths"]
        assert _TARGET_PATH not in redone_state["adapter"]["paths"]
        assert _TARGET_PATH not in {
            row["path"] for row in redone_state["stage_ui"]["rows"]
        }
        assert_native_scene_state(redone_state)

        _record_feature_evidence(
            evidence,
            "stage.selection_from_viewport",
            {
                "viewport_click": "The visible box was clicked in the rendered viewport.",
                "selection_path": f"The shared selection became exactly {_TARGET_PATH}.",
                "renderer_pick_path": (
                    f"The BORROW renderer reported exactly {_TARGET_PATH} for the click."
                ),
                "screenshots": "Atomic before/after screenshots recorded the viewport action.",
            },
        )
        _record_feature_evidence(
            evidence,
            "stage.delete",
            {
                "delete_key": "Delete was issued as a real keyboard action.",
                "native_absent": f"{_TARGET_PATH} was absent from the committed native OVStage topology.",
                "row_absent": f"{_TARGET_PATH} was absent from the visible Stage tree.",
                "screenshots": "Atomic screenshots recorded the deletion transition.",
            },
        )
        _record_feature_evidence(
            evidence,
            "history.undo",
            {
                "ctrl_z": "Undo was issued with the real Ctrl+Z shortcut.",
                "native_restore": f"Undo restored {_TARGET_PATH} in the native OVStage topology.",
                "selection_restore": f"Undo restored selection to {_TARGET_PATH}.",
            },
        )
        _record_feature_evidence(
            evidence,
            "history.redo",
            {
                "ctrl_shift_z": "Redo was issued with the real Ctrl+Shift+Z shortcut.",
                "native_reapply": f"Redo removed {_TARGET_PATH} from the native OVStage topology again.",
            },
        )
        _record_feature_evidence(
            evidence,
            "renderer.initial_frame",
            {
                "real_ovrtx": "The renderer state identified the real OVRTX backend.",
                "borrow_attach": "The renderer was attached to OVStage in BORROW mode.",
                "nonblack_viewport": (
                    "The initial viewport contained non-black pixels and useful channel range."
                ),
                "screenshot": "The first atomic checkpoint captured the rendered frame.",
            },
        )
        _record_feature_evidence(
            evidence,
            "renderer.point_pick",
            {
                "viewport_click": "Picking was initiated by a real viewport click.",
                "renderer_pick_path": f"OVRTX returned exactly {_TARGET_PATH}.",
                "selection_bus": f"The shared selection bus received exactly {_TARGET_PATH}.",
            },
        )
        manifest = evidence.finalize()
        assert manifest["summary"]["complete"] is True


@pytest.mark.skipif(not _enabled(), reason=f"set {_RUN_ENV}=1 to run real Inspector QA")
def test_create_xform_through_visible_menu_populates_native_ovstage(
    tmp_path: Path,
) -> None:
    """A visible Create > Xform menu click populates exact native OVStage.

    Native-only migration of the create.xform portion of the removed hybrid
    File-New scenario (File New itself is now accepted-unsupported): the Xform
    is created through the real Create menu and verified against native
    OVStage type/topology and the Stage tree rows, with undo/redo.
    """
    repo_root = Path(__file__).resolve().parents[3]
    config = InspectorRuntimeConfig.from_environment(repo_root)
    workspace = tmp_path / "viewer"
    workspace.mkdir(parents=True)
    source_scene = (
        repo_root
        / "ovui-data-adapters"
        / "tests"
        / "data"
        / "ovstage_static_scene.usda"
    )
    scene = workspace / "ovstage_static_scene.usda"
    shutil.copy2(source_scene, scene)
    evidence_root = tmp_path / "evidence" / "create-xform-native"

    with InspectorAppProcess(config, workspace, scene=scene) as application:
        initial = application.wait_for_scene()
        assert initial["adapter"]["paths"]
        evidence = EvidenceRecorder(
            application.client,
            evidence_root,
            scenario=_CREATE_XFORM_SCENARIO,
        )

        menu = evidence.action(
            "open-create-menu",
            lambda: application.client.click(*_CREATE_MENU),
        )
        assert menu["record"]["screenshot_changed"] is True
        created = evidence.action(
            "choose-create-xform",
            lambda: application.client.click(*_CREATE_XFORM_ITEM),
        )
        state = created["after"]["state"]
        assert state["ovstage"]["prims"]["/World/Xform"]["type_name"] == "Xform"
        assert "/World/Xform" in state["ovstage"]["paths"]
        assert "/World/Xform" in state["adapter"]["paths"]
        assert "/World/Xform" in {
            row["path"] for row in state["stage_ui"]["rows"]
        }
        assert_native_scene_state(state)

        undone = evidence.action(
            "undo-create-xform",
            lambda: application.client.press("z", modifiers=["ctrl"]),
        )
        assert "/World/Xform" not in undone["after"]["state"]["ovstage"]["paths"]
        assert_native_scene_state(undone["after"]["state"])

        redone = evidence.action(
            "redo-create-xform",
            lambda: application.client.press("z", modifiers=["ctrl", "shift"]),
        )
        assert "/World/Xform" in redone["after"]["state"]["ovstage"]["paths"]
        assert_native_scene_state(redone["after"]["state"])

        _record_feature_evidence(
            evidence,
            "create.xform",
            {
                "menu_click": "A real mouse click opened Create and chose Xform.",
                "xform_schema": "The created prim's native OVStage type is exactly Xform.",
                "ovstage_path": "/World/Xform is present in native OVStage, the adapter, and the Stage rows.",
            },
        )
        manifest = evidence.finalize()
        assert manifest["summary"]["passed"] is True

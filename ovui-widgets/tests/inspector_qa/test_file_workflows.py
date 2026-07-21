# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Native-only OVStage File Open scenario plus file-ledger partition guard.

Opening documents is supported and proven by the visible File > Open dialog
scenario below, cross-checked against exact native OVStage state. Creating,
saving, and exporting documents are accepted limitations of the native-only
provider (no OpenUSD bridge); their former hybrid Save/Save As/export
scenarios and backing-USD dialog fixtures were removed with the bridge.
"""

from __future__ import annotations

import json
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
    assert_native_scene_state,
    assert_real_borrow_renderer,
)

_RUN_ENV = "OVUI_RUN_INSPECTOR_QA"
_FILE_MENU = (122, 10)
_FILE_OPEN_ITEM = (135, 57)

_FILE_OPEN_SCENARIO = ScenarioEvidenceContract.declare(
    "test_file_workflows.py::test_file_open_dialog_loads_scene_into_native_ovstage",
    {
        "file.open": (
            "menu_click",
            "dialog_accept",
            "screenshot",
            "native_scene_state",
        ),
    },
)


def _enabled() -> bool:
    return os.environ.get(_RUN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _point(value: Any, *, label: str) -> tuple[int, int]:
    assert isinstance(value, list) and len(value) == 2, (label, value)
    return int(value[0]), int(value[1])


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


def test_file_new_export_and_xform_contracts_partition_ledger() -> None:
    """Fail cheaply when file/create ledger assignments drift from provider truth."""

    matrix = json.loads(
        Path(__file__).with_name("feature-matrix.json").read_text(encoding="utf-8")
    )
    by_id = {feature["id"]: feature for feature in matrix["features"]}

    # The native-only provider cannot create, save, or export documents; the
    # ledger must record those as accepted limitations closed by fail-closed
    # contract evidence, never as supported Inspector-covered behavior.
    for feature_id in ("file.new", "file.save", "file.save_as", "file.export_stage"):
        feature = by_id[feature_id]
        assert feature["support_status"] == "accepted_unsupported", feature_id
        assert feature["evidence_status"] == "contract_covered", feature_id
        assert feature.get("scope_note", "").strip(), feature_id
        assert feature.get("contract_evidence"), feature_id
        assert "scenarios" not in feature, feature_id

    # Opening documents remains supported and is proven by the visible native
    # File > Open scenario in this module.
    file_open = by_id["file.open"]
    assert file_open["support_status"] == "supported"
    assert file_open["evidence_status"] == "inspector_covered"
    assert file_open["scenarios"] == [_FILE_OPEN_SCENARIO.scenario_id]

    # Native Xform creation remains supported and is proven by its own visible
    # Create-menu scenario in test_ovstage_stage_workflows.py.
    create_xform = by_id["create.xform"]
    assert create_xform["support_status"] == "supported"
    assert create_xform["evidence_status"] == "inspector_covered"


@pytest.mark.skipif(not _enabled(), reason=f"set {_RUN_ENV}=1 to run real Inspector QA")
def test_file_open_dialog_loads_scene_into_native_ovstage(tmp_path: Path) -> None:
    """A visible File > Open dialog loads a second scene into native OVStage.

    Native-only migration of the former hybrid open/save/save-as round trip:
    Save and Save As moved to the accepted-unsupported ledger entries, so this
    scenario proves the supported Open path only. The dialog target is an
    ordinary native-openable OVStage document (no pxr authoring), and the
    result is verified against exact native OVStage topology, not backing USD.
    """
    repo_root = Path(__file__).resolve().parents[3]
    config = InspectorRuntimeConfig.from_environment(repo_root)
    workspace = tmp_path / "viewer"
    home = workspace / "home"
    home.mkdir(parents=True)

    source_fixture = (
        repo_root / "ovui-data-adapters" / "tests" / "data" / "ovstage_static_scene.usda"
    )
    initial_scene = workspace / "initial.usda"
    shutil.copy2(source_fixture, initial_scene)
    # A second, independently named native document to open through the dialog.
    opened_scene = home / "dialog-open.usda"
    shutil.copy2(source_fixture, opened_scene)
    evidence_root = tmp_path / "evidence" / "file-open-native"

    with InspectorAppProcess(config, workspace, scene=initial_scene) as application:
        initial = application.wait_for_scene()
        assert_real_borrow_renderer(initial)
        assert_native_scene_state(initial)
        evidence = EvidenceRecorder(
            application.client,
            evidence_root,
            scenario=_FILE_OPEN_SCENARIO,
        )

        menu = evidence.action(
            "open-file-menu",
            lambda: application.client.click(*_FILE_MENU),
        )
        assert menu["record"]["screenshot_changed"] is True
        open_dialog_action = evidence.action(
            "choose-file-open",
            lambda: application.client.click(*_FILE_OPEN_ITEM, timeout=15.0),
        )
        open_dialog = open_dialog_action["after"]["state"]["layers_ui"][
            "open_file_dialog"
        ]
        assert open_dialog["shown"] is True
        assert open_dialog["apply_enabled"] is False
        assert Path(open_dialog["directory"].removeprefix("file://")) == home

        field_point = _point(open_dialog["field_point"], label="open filename")
        evidence.action(
            "focus-open-filename",
            lambda: application.client.click(*field_point),
        )
        typed = evidence.action(
            "type-open-filename",
            lambda: application.client.type_text(opened_scene.name),
        )
        typed_dialog = typed["after"]["state"]["layers_ui"]["open_file_dialog"]
        assert typed_dialog["filename"] == opened_scene.name
        assert typed_dialog["apply_enabled"] is True

        apply_point = _point(typed_dialog["apply_point"], label="Open button")
        opened = evidence.action(
            "accept-open-dialog",
            lambda: application.client.click(*apply_point, timeout=60.0),
        )
        assert opened["record"]["screenshot_changed"] is True
        opened_state = opened["after"]["state"]
        assert opened_state["current_file_path"] == str(opened_scene)
        assert opened_state["undo"]["undo_depth"] == 0
        assert opened_state["undo"]["redo_depth"] == 0
        assert opened_state["layers_ui"]["open_file_dialog"]["shown"] is False
        # The freshly opened native scene composes its own user topology.
        native_paths = set(opened_state["ovstage"]["paths"])
        assert "/World/Hierarchy/GroupA/BallA" in native_paths
        assert_real_borrow_renderer(opened_state)
        assert_native_scene_state(opened_state)

        _record_feature_evidence(
            evidence,
            "file.open",
            {
                "menu_click": "A real mouse click opened the File menu.",
                "dialog_accept": "The Open dialog filename was typed and the Open button clicked.",
                "screenshot": "Before/after screenshots recorded the visible scene change.",
                "native_scene_state": "The opened document composed its native OVStage topology (BallA present).",
            },
        )
        manifest = evidence.finalize()
        assert manifest["summary"]["passed"] is True

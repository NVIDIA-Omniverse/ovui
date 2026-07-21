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

import ast
import importlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from .harness import EvidenceRecorder, ScenarioEvidenceContract

_QA_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _QA_ROOT.parents[2]
_MATRIX_PATH = _QA_ROOT / "feature-matrix.json"

_SUPPORT_STATUSES = {"supported", "accepted_unsupported", "not_applicable"}
_EVIDENCE_STATUSES = {
    "inspector_covered",
    "inspector_partial",
    "contract_covered",
    "open_evidence",
}
_RELEASE_TIERS = {
    "ovui_0_1_baseline",
    "post_0_1_usd_extension",
    "ovui_0_2_ovstage_only",
}
_TOP_LEVEL_KEYS = {
    "schema_version",
    "support_status_definition",
    "evidence_status_definition",
    "release_tier_definition",
    "baseline_manifest",
    "features",
}
_FEATURE_REQUIRED_KEYS = {
    "id",
    "surface",
    "required_evidence",
    "release_tier",
    "support_status",
    "evidence_status",
}
_FEATURE_OPTIONAL_KEYS = {
    "scenarios",
    "contract_evidence",
    "scope_note",
}
_FEATURE_ID = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")

# This tuple is intentionally explicit and duplicated by the JSON manifest.
# A baseline feature can be added, removed, or renamed only by updating this
# release gate and the reviewed ledger in the same change.
_REQUIRED_OVUI_0_1_BASELINE_IDS = (
    "file.new",
    "file.open",
    "file.save",
    "file.save_as",
    "file.export_stage",
    "stage.hierarchy",
    "stage.usd_child_order",
    "stage.expand_collapse",
    "stage.filter",
    "stage.selection_from_row",
    "stage.selection_from_viewport",
    "stage.multiselect",
    "stage.delete",
    "stage.rename",
    "stage.reparent",
    "stage.visibility",
    "stage.default_prim_identity",
    "stage.composition_badges",
    "create.geometry_meshes",
    "create.geometry_shapes",
    "create.lights",
    "create.camera",
    "create.scope",
    "create.xform",
    "create.material",
    "property.scalar_edit",
    "property.vector_edit",
    "property.token_edit",
    "property.clear_reset",
    "property.multi_selection",
    "transform.translate",
    "transform.rotate",
    "transform.scale",
    "transform.snap",
    "history.undo",
    "history.redo",
    "layers.layer_stack",
    "layers.edit_target_read",
    "layers.edit_target_write",
    "layers.save_layer",
    "layers.save_layer_as",
    "layers.create_sublayer",
    "layers.insert_sublayer",
    "layers.remove_sublayer",
    "layers.reload_layer",
    "layers.mute_layer",
    "layers.lock_layer",
    "layers.move_sublayer",
    "layers.replace_sublayer",
    "layers.prim_spec_read",
    "layers.prim_spec_edit",
    "layers.layer_snapshot",
    "layers.layer_restore",
    "layers.transfer_layer_content",
    "layers.merge_down",
    "layers.flatten_sublayers",
    "renderer.initial_frame",
    "renderer.point_pick",
    "renderer.pick_miss",
    "renderer.marquee_pick",
    "renderer.selection_outline",
    "livestream.headless_full_ui",
    "livestream.windowed_viewport",
)

# Runtime evidence contracts live beside the Inspector workflows that execute
# them.  Discovering those declarations here makes the release ledger a strict
# cross-check instead of a second, hand-maintained copy that can silently drift.
_WORKFLOW_MODULE_NAMES = (
    # test_layers_workflows declares no Inspector evidence: the USD layer stack
    # is an accepted limitation of the native-only provider, closed by contract
    # evidence instead of a real-runtime scenario. test_file_workflows declares
    # only the supported File Open scenario (save/export are accepted-unsupported).
    "test_file_workflows",
    "test_ovstage_stage_workflows",
    "test_property_transform_workflows",
    "test_renderer_feature_workflows",
    "test_stage_browser_workflows",
)


def _discover_inspector_scenarios() -> tuple[ScenarioEvidenceContract, ...]:
    declarations: dict[str, ScenarioEvidenceContract] = {}
    for module_name in _WORKFLOW_MODULE_NAMES:
        module = importlib.import_module(f"{__package__}.{module_name}")
        module_declarations = [
            value
            for value in vars(module).values()
            if isinstance(value, ScenarioEvidenceContract)
        ]
        assert module_declarations, f"{module_name}: no Inspector evidence contracts"
        for declaration in module_declarations:
            previous = declarations.setdefault(declaration.scenario_id, declaration)
            assert previous is declaration, (
                f"{declaration.scenario_id}: duplicate contract objects were imported"
            )
    return tuple(declarations.values())


_INSPECTOR_SCENARIOS = _discover_inspector_scenarios()


def _load_matrix() -> dict[str, Any]:
    value = json.loads(_MATRIX_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _assert_nonempty_unique_strings(value: Any, *, label: str) -> list[str]:
    assert isinstance(value, list) and value, label
    assert all(isinstance(item, str) and item.strip() == item and item for item in value), label
    assert len(value) == len(set(value)), label
    return value


def _find_named_child(nodes: list[ast.stmt], name: str) -> ast.AST | None:
    for node in nodes:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                return node
    return None


def _assert_reference(reference: str, *, base: Path, label: str) -> ast.AST | None:
    parts = reference.split("::")
    relative_path = Path(parts[0])
    assert not relative_path.is_absolute(), f"{label}: absolute path {reference!r}"
    path = (base / relative_path).resolve()
    assert path.is_relative_to(_REPO_ROOT), f"{label}: path escapes repository"
    assert path.is_file(), f"{label}: missing {path.relative_to(_REPO_ROOT)}"

    if len(parts) == 1:
        return None
    assert path.suffix == ".py", f"{label}: node ID requires Python source"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    body = tree.body
    resolved: ast.AST | None = None
    for node_name in parts[1:]:
        assert node_name, f"{label}: empty node component"
        node = _find_named_child(body, node_name)
        assert node is not None, f"{label}: missing node {node_name!r} in {path}"
        resolved = node
        body = getattr(node, "body", [])
    return resolved


def _calls_evidence_action(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == "action"
        and isinstance(child.func.value, ast.Name)
        and child.func.value.id == "evidence"
        for child in ast.walk(node)
    )


def _assert_inspector_coverage_contracts(
    features: list[dict[str, Any]],
    declarations: tuple[ScenarioEvidenceContract, ...],
    *,
    action_scenarios: set[str],
) -> None:
    """Cross-check matrix requirements, source declarations, and real actions."""

    declaration_ids = [declaration.scenario_id for declaration in declarations]
    assert len(declaration_ids) == len(set(declaration_ids)), (
        "duplicate Inspector scenario evidence declarations"
    )
    by_scenario = {
        declaration.scenario_id: declaration for declaration in declarations
    }
    covered = {
        feature["id"]: feature
        for feature in features
        if feature["evidence_status"] == "inspector_covered"
    }
    expected_scenarios = {
        scenario
        for feature in covered.values()
        for scenario in feature.get("scenarios", [])
    }
    assert set(by_scenario) == expected_scenarios, (
        "Inspector scenario declarations do not match the covered matrix references: "
        f"missing={sorted(expected_scenarios - set(by_scenario))}, "
        f"unexpected={sorted(set(by_scenario) - expected_scenarios)}"
    )

    for declaration in declarations:
        for feature_id in declaration.feature_ids:
            assert feature_id in covered, (
                f"{declaration.scenario_id}: declared feature {feature_id!r} is not "
                "inspector_covered"
            )
            assert declaration.scenario_id in covered[feature_id]["scenarios"], (
                f"{declaration.scenario_id}: feature {feature_id!r} does not reference "
                "this scenario in the matrix"
            )

    for feature_id, feature in covered.items():
        required = set(feature["required_evidence"])
        for scenario_id in feature["scenarios"]:
            declaration = by_scenario[scenario_id]
            assert feature_id in declaration.feature_ids, (
                f"{scenario_id}: source declaration is missing feature {feature_id!r}"
            )
            missing_tokens = required - declaration.tokens_for(feature_id)
            assert not missing_tokens, (
                f"{scenario_id}: {feature_id} is missing declared evidence tokens "
                f"{sorted(missing_tokens)}"
            )
            assert scenario_id in action_scenarios, (
                f"{scenario_id}: {feature_id} has no EvidenceRecorder.action call"
            )


def test_feature_matrix_is_strict_schema_v2() -> None:
    matrix = _load_matrix()
    assert set(matrix) == _TOP_LEVEL_KEYS
    assert matrix["schema_version"] == 2
    assert set(matrix["support_status_definition"]) == _SUPPORT_STATUSES
    assert set(matrix["evidence_status_definition"]) == _EVIDENCE_STATUSES
    assert set(matrix["release_tier_definition"]) == _RELEASE_TIERS
    assert all(
        isinstance(value, str) and value.strip()
        for definitions in (
            matrix["support_status_definition"],
            matrix["evidence_status_definition"],
            matrix["release_tier_definition"],
        )
        for value in definitions.values()
    )

    features = matrix["features"]
    assert isinstance(features, list) and features
    identifiers: list[str] = []
    for feature in features:
        assert isinstance(feature, dict)
        assert _FEATURE_REQUIRED_KEYS <= set(feature)
        assert set(feature) <= _FEATURE_REQUIRED_KEYS | _FEATURE_OPTIONAL_KEYS
        assert "status" not in feature

        identifier = feature["id"]
        assert isinstance(identifier, str) and _FEATURE_ID.fullmatch(identifier)
        identifiers.append(identifier)
        assert isinstance(feature["surface"], str) and feature["surface"].strip()
        assert feature["support_status"] in _SUPPORT_STATUSES
        assert feature["evidence_status"] in _EVIDENCE_STATUSES
        assert feature["release_tier"] in _RELEASE_TIERS
        _assert_nonempty_unique_strings(
            feature["required_evidence"], label=f"{identifier}: required_evidence"
        )

        if feature["support_status"] == "accepted_unsupported":
            assert feature.get("scope_note", "").strip(), identifier
            assert feature["evidence_status"] != "open_evidence", (
                f"{identifier}: an accepted limitation must have closure evidence"
            )
        if feature["evidence_status"].startswith("inspector_"):
            _assert_nonempty_unique_strings(
                feature.get("scenarios"), label=f"{identifier}: scenarios"
            )
        if feature["evidence_status"] == "contract_covered":
            _assert_nonempty_unique_strings(
                feature.get("contract_evidence"),
                label=f"{identifier}: contract_evidence",
            )
        if feature["evidence_status"] == "open_evidence":
            assert feature.get("scope_note", "").strip(), (
                f"{identifier}: open evidence requires a scope_note"
            )

    assert len(identifiers) == len(set(identifiers))

    # These counts are computed, not maintained as a second source of truth.
    assert sum(Counter(feature["support_status"] for feature in features).values()) == len(features)
    assert sum(Counter(feature["evidence_status"] for feature in features).values()) == len(features)
    assert sum(Counter(feature["release_tier"] for feature in features).values()) == len(features)


def test_exact_ovui_0_1_baseline_manifest_has_no_omissions_or_extras() -> None:
    matrix = _load_matrix()
    manifest = matrix["baseline_manifest"]
    assert set(manifest) == {"name", "scope", "feature_ids"}
    assert manifest["name"] == "ovui_0_1_usd_stage_adapter_and_viewer"
    assert isinstance(manifest["scope"], str) and manifest["scope"].strip()
    manifest_ids = _assert_nonempty_unique_strings(
        manifest["feature_ids"], label="baseline_manifest.feature_ids"
    )
    assert tuple(manifest_ids) == _REQUIRED_OVUI_0_1_BASELINE_IDS

    ledger_ids = tuple(
        feature["id"]
        for feature in matrix["features"]
        if feature["release_tier"] == "ovui_0_1_baseline"
    )
    assert ledger_ids == _REQUIRED_OVUI_0_1_BASELINE_IDS
    # The native-only OVStage provider accepts these limitations instead of
    # emulating them through the removed OpenUSD bridge: document creation,
    # save, and export; the entire logical USD layer stack; render settings;
    # clear-to-default; authored child order; and composition/default-prim
    # identity metadata.
    assert {
        feature["id"]
        for feature in matrix["features"]
        if feature["support_status"] == "accepted_unsupported"
    } == {
        "file.export_stage",
        "file.combined_snapshot_export",
        "file.new",
        "file.save",
        "file.save_as",
        "layers.create_sublayer",
        "layers.edit_target_read",
        "layers.edit_target_write",
        "layers.flatten_sublayers",
        "layers.insert_sublayer",
        "layers.layer_restore",
        "layers.layer_snapshot",
        "layers.layer_stack",
        "layers.lock_layer",
        "layers.merge_down",
        "layers.move_sublayer",
        "layers.mute_layer",
        "layers.prim_spec_edit",
        "layers.prim_spec_read",
        "layers.reload_layer",
        "layers.remove_sublayer",
        "layers.replace_sublayer",
        "layers.save_layer",
        "layers.save_layer_as",
        "layers.transfer_layer_content",
        "property.clear_reset",
        "renderer.settings",
        "stage.composition_badges",
        "stage.default_prim_identity",
        "stage.usd_child_order",
    }


def test_all_evidence_references_resolve() -> None:
    matrix = _load_matrix()

    for feature in matrix["features"]:
        identifier = feature["id"]
        for scenario in feature.get("scenarios", []):
            _assert_reference(
                scenario,
                base=_QA_ROOT,
                label=f"{identifier}: scenario",
            )
        for reference in feature.get("contract_evidence", []):
            _assert_reference(
                reference,
                base=_REPO_ROOT,
                label=f"{identifier}: contract_evidence",
            )


def test_inspector_covered_features_have_declared_tokens_and_real_actions() -> None:
    matrix = _load_matrix()
    action_scenarios: set[str] = set()
    for declaration in _INSPECTOR_SCENARIOS:
        node = _assert_reference(
            declaration.scenario_id,
            base=_QA_ROOT,
            label=f"{declaration.scenario_id}: evidence declaration",
        )
        assert node is not None
        if _calls_evidence_action(node):
            action_scenarios.add(declaration.scenario_id)

    _assert_inspector_coverage_contracts(
        matrix["features"],
        _INSPECTOR_SCENARIOS,
        action_scenarios=action_scenarios,
    )


def _covered_feature(
    feature_id: str,
    scenario_id: str,
    *required_evidence: str,
) -> dict[str, Any]:
    return {
        "id": feature_id,
        "evidence_status": "inspector_covered",
        "required_evidence": list(required_evidence),
        "scenarios": [scenario_id],
    }


def test_inspector_contract_rejects_missing_feature_declaration() -> None:
    scenario_id = "test_demo.py::test_demo"
    features = [
        _covered_feature("demo.feature", scenario_id, "click"),
        _covered_feature("demo.other", scenario_id, "click"),
    ]
    declarations = (
        ScenarioEvidenceContract.declare(
            scenario_id,
            {"demo.other": ("click",)},
        ),
    )

    with pytest.raises(AssertionError, match="missing feature 'demo.feature'"):
        _assert_inspector_coverage_contracts(
            features,
            declarations,
            action_scenarios={scenario_id},
        )


def test_inspector_contract_rejects_missing_evidence_token() -> None:
    scenario_id = "test_demo.py::test_demo"
    feature = _covered_feature("demo.feature", scenario_id, "click", "settled")
    declarations = (
        ScenarioEvidenceContract.declare(
            scenario_id,
            {"demo.feature": ("click",)},
        ),
    )

    with pytest.raises(AssertionError, match="missing declared evidence tokens"):
        _assert_inspector_coverage_contracts(
            [feature],
            declarations,
            action_scenarios={scenario_id},
        )


def test_inspector_contract_rejects_scenario_without_evidence_action() -> None:
    scenario_id = "test_demo.py::test_demo"
    feature = _covered_feature("demo.feature", scenario_id, "click")
    declarations = (
        ScenarioEvidenceContract.declare(
            scenario_id,
            {"demo.feature": ("click",)},
        ),
    )

    with pytest.raises(AssertionError, match="no EvidenceRecorder.action call"):
        _assert_inspector_coverage_contracts(
            [feature],
            declarations,
            action_scenarios=set(),
        )


class _UnitEvidenceRecorder(EvidenceRecorder):
    def checkpoint(self, label: str) -> dict[str, Any]:
        return {
            "label": label,
            "screenshot_sha256": label,
            "state": {},
            "native_scene_verified": True,
        }


def test_runtime_manifest_records_pass_and_fail_token_results(tmp_path: Path) -> None:
    scenario = ScenarioEvidenceContract.declare(
        "test_demo.py::test_demo",
        {"demo.feature": ("click", "settled")},
    )
    recorder = _UnitEvidenceRecorder(object(), tmp_path, scenario=scenario)  # type: ignore[arg-type]
    recorder.action(
        "click-demo",
        lambda: {"success": True},
        evidence_tokens={"demo.feature": ("click",)},
    )
    with pytest.raises(AssertionError, match="Evidence check failed"):
        recorder.check(
            "demo.feature",
            "settled",
            False,
            detail="native OVStage state differed from the expected value",
        )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["scenario"]["id"] == "test_demo.py::test_demo"
    assert manifest["scenario"]["features"] == [
        {
            "id": "demo.feature",
            "required_evidence": ["click", "settled"],
        }
    ]
    assert manifest["evidence_checks"] == [
        {
            "after_action": 1,
            "detail": "Inspector action 'click-demo' completed successfully",
            "feature_id": "demo.feature",
            "passed": True,
            "token": "click",
        },
        {
            "after_action": 1,
            "detail": "native OVStage state differed from the expected value",
            "feature_id": "demo.feature",
            "passed": False,
            "token": "settled",
        },
    ]
    assert manifest["summary"]["complete"] is False
    assert manifest["summary"]["failed_evidence"] == [
        {"feature_id": "demo.feature", "token": "settled"}
    ]

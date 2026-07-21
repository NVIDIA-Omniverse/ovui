# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""State-guided Inspector workflows for OVStage-owned renderer features.

These tests deliberately discover interaction coordinates from read-only
application state.  Mutations still travel exclusively through mouse and
keyboard input, and :class:`EvidenceRecorder` captures a screenshot and scene
native-state checkpoint immediately before and after every action.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
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
_CAMERA = "/World/Cameras/MainCamera"

_RENDERER_INTERACTION_SCENARIO = ScenarioEvidenceContract.declare(
    "test_renderer_feature_workflows.py::"
    "test_camera_point_miss_and_marquee_use_real_borrow_renderer",
    {
        "renderer.pick_miss": ("empty_viewport_click", "selection_clear"),
        "renderer.marquee_pick": (
            "rectangle_query",
            "multiple_hits",
            "selection_sync",
        ),
    },
)

_WINDOWED_LIVESTREAM_SCENARIO = ScenarioEvidenceContract.declare(
    "test_renderer_feature_workflows.py::"
    "test_windowed_livestream_tees_borrowed_frame_and_shuts_down_cleanly",
    {
        "livestream.windowed_viewport": (
            "mapped_ovrtx_rgba_tee",
            "gpu_zero_copy_when_compatible",
            "cpu_fallback_when_required",
            "mapping_lifetime_and_shutdown",
        ),
    },
)

_RUNTIME_SCENARIOS = (
    _RENDERER_INTERACTION_SCENARIO,
    _WINDOWED_LIVESTREAM_SCENARIO,
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


def test_renderer_runtime_scenario_contracts_are_token_exact() -> None:
    """Fail cheaply on renderer token drift without launching the GPU app."""

    assigned_ids = {
        "renderer.pick_miss",
        "renderer.marquee_pick",
        "livestream.windowed_viewport",
    }
    matrix = json.loads(
        Path(__file__).with_name("feature-matrix.json").read_text(encoding="utf-8")
    )
    expected = {
        feature["id"]: frozenset(feature["required_evidence"])
        for feature in matrix["features"]
        if feature["id"] in assigned_ids
    }
    assert set(expected) == assigned_ids
    assigned: dict[str, str] = {}
    for contract in _RUNTIME_SCENARIOS:
        assert contract.scenario_id.startswith("test_renderer_feature_workflows.py::test_")
        for feature_id in contract.feature_ids:
            assert feature_id not in assigned, (
                f"{feature_id} assigned to both {assigned[feature_id]} "
                f"and {contract.scenario_id}"
            )
            assigned[feature_id] = contract.scenario_id
            assert contract.tokens_for(feature_id) == expected[feature_id]
    assert set(assigned) == assigned_ids


def _enabled() -> bool:
    return os.environ.get(_RUN_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _scene_copy(repo_root: Path, workspace: Path, relative: str) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    source = repo_root / relative
    target = workspace / source.name
    shutil.copy2(source, target)
    return target


def _top_menu_point(state: dict[str, Any], label: str) -> tuple[int, int]:
    item = next(
        item for item in state["menus"]["top_levels"] if item["label"] == label
    )
    point = item["point"]
    assert point is not None, item
    return int(point[0]), int(point[1])



@pytest.mark.skipif(not _enabled(), reason=f"set {_RUN_ENV}=1 to run real Inspector QA")
def test_camera_point_miss_and_marquee_use_real_borrow_renderer(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config = InspectorRuntimeConfig.from_environment(repo_root)
    workspace = tmp_path / "viewer"
    scene = _scene_copy(
        repo_root,
        workspace,
        "ovui-data-adapters/tests/data/ovstage_static_scene.usda",
    )
    evidence_root = tmp_path / "evidence" / "camera-picking"

    with InspectorAppProcess(config, workspace, scene=scene) as application:
        # This workflow aims real clicks at state-discovered prim screen
        # centers, so it opts into the centers-ready criterion explicitly.
        initial = application.wait_for_scene(require_prim_screen_centers=True)
        assert_real_borrow_renderer(initial)
        assert_native_scene_state(initial)
        assert initial["components"]["failures"] == {}

        evidence = EvidenceRecorder(
            application.client,
            evidence_root,
            scenario=_RENDERER_INTERACTION_SCENARIO,
        )
        hit_point = initial["viewport"]["prim_screen_centers"][_BOX]
        hit = evidence.action(
            "point-pick-visible-box",
            lambda: application.client.click(int(hit_point[0]), int(hit_point[1])),
        )
        hit_state = hit["after"]["state"]
        assert hit_state["renderer"]["last_pick_kind"] == "point"
        assert hit_state["renderer"]["last_pick_query_name"] == "viewport_click"
        assert hit_state["renderer"]["last_pick_paths"] == [_BOX]
        assert hit_state["renderer"]["last_pick_world_point"] is not None
        assert hit_state["selection"]["paths"] == [_BOX]

        image = hit_state["viewport"]["image_rect"]
        miss_point = (
            int(float(image["x"]) + float(image["width"]) - 8),
            int(float(image["y"]) + float(image["height"]) - 8),
        )
        miss = evidence.action(
            "point-pick-empty-background",
            lambda: application.client.click(*miss_point),
        )
        miss_state = miss["after"]["state"]
        assert miss_state["renderer"]["pick_result_count"] > hit_state["renderer"][
            "pick_result_count"
        ]
        assert miss_state["renderer"]["last_pick_kind"] == "point"
        assert miss_state["renderer"]["last_pick_paths"] == []
        assert miss_state["selection"]["paths"] == []

        marquee_start = (
            int(float(image["x"]) + 24),
            int(float(image["y"]) + 32),
        )
        marquee_end = (
            int(float(image["x"]) + float(image["width"]) - 24),
            int(float(image["y"]) + float(image["height"]) - 24),
        )
        marquee = evidence.action(
            "marquee-select-visible-scene",
            lambda: application.client.drag(
                *marquee_start,
                *marquee_end,
                steps=16,
            ),
        )
        marquee_state = marquee["after"]["state"]
        marquee_paths = marquee_state["renderer"]["last_pick_paths"]
        assert marquee_state["renderer"]["last_pick_kind"] == "rect"
        assert marquee_state["renderer"]["last_pick_query_name"].startswith(
            "viewport_rect:"
        )
        assert len(marquee_paths) >= 2, marquee_state["renderer"]
        assert marquee_state["selection"]["paths"] == marquee_paths

        outline = marquee_state["renderer"]["selection_outline"]
        # The outline membership tracks the marquee selection while the
        # BORROW data-plane witness stays zero: renderer-owned presentation
        # writes, never attribute writes into the borrowed stage.
        assert sorted(outline["applied_paths"]) == sorted(marquee_paths)
        assert marquee_state["renderer"]["selection_outline_attribute_writes"] == 0

        camera_button = marquee_state["viewport"]["camera_button"]
        assert camera_button["enabled"] is True and camera_button["point"] is not None
        opened = evidence.action(
            "open-camera-choice-menu",
            lambda: application.client.click(*camera_button["point"]),
        )
        opened_state = opened["after"]["state"]
        camera_item = next(
            item
            for item in opened_state["viewport"]["camera_menu"]["items"]
            if item["path"] == _CAMERA
        )
        assert camera_item["enabled"] is True and camera_item["point"] is not None
        selected = evidence.action(
            "select-native-camera",
            lambda: application.client.click(*camera_item["point"]),
        )
        selected_state = selected["after"]["state"]
        assert selected_state["viewport"]["active_camera_path"] == _CAMERA
        assert selected_state["renderer"]["active_camera_path"] == _CAMERA
        assert (
            opened["before"]["viewport_stats"]["pixel_sha256"]
            != selected["after"]["viewport_stats"]["pixel_sha256"]
        )
        assert_real_borrow_renderer(selected_state)
        assert_native_scene_state(selected_state)
        _record_feature_evidence(
            evidence,
            "renderer.pick_miss",
            {
                "empty_viewport_click": (
                    f"clicked empty viewport pixel {miss_point} through Inspector"
                ),
                "selection_clear": (
                    "OVRTX point query returned no paths and SelectionBus became empty"
                ),
            },
        )
        _record_feature_evidence(
            evidence,
            "renderer.marquee_pick",
            {
                "rectangle_query": (
                    f"dragged Inspector rectangle {marquee_start}->{marquee_end}; "
                    f"query={marquee_state['renderer']['last_pick_query_name']}"
                ),
                "multiple_hits": f"OVRTX returned {len(marquee_paths)} unique scene paths",
                "selection_sync": (
                    "SelectionBus paths exactly matched the OVRTX rectangle result"
                ),
            },
        )
        manifest = evidence.finalize()
        assert manifest["summary"]["complete"] is True
        assert manifest["summary"]["passed"] is True


@pytest.mark.skipif(not _enabled(), reason=f"set {_RUN_ENV}=1 to run real Inspector QA")
def test_physics_enable_reports_missing_ovphysx_without_partial_state(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config = InspectorRuntimeConfig.from_environment(repo_root)
    workspace = tmp_path / "viewer"
    scene = _scene_copy(
        repo_root,
        workspace,
        "ovui-data-adapters/tests/data/ovstage_physics_scene.usda",
    )
    evidence_root = tmp_path / "evidence" / "physics"
    with InspectorAppProcess(config, workspace, scene=scene) as application:
        initial = application.wait_for_scene()
        assert_real_borrow_renderer(initial)
        assert_native_scene_state(initial)
        assert initial["physics"]["available"] is True
        assert initial["physics"]["enabled"] is False
        assert initial["physics"]["can_toggle_enabled"] is True
        evidence = EvidenceRecorder(application.client, evidence_root)

        opened_enable = evidence.action(
            "open-physics-menu-for-enable",
            lambda: application.client.click(*_top_menu_point(initial, "Physics")),
        )
        enable_item = next(
            item
            for item in opened_enable["after"]["state"]["menus"]["built_items"]
            if item["id"] == "legacy_menu.physics.enable"
        )
        assert enable_item["enabled"] is True and enable_item["point"] is not None
        enabled = evidence.action(
            "enable-physx",
            lambda: application.client.click(*enable_item["point"]),
        )
        enabled_state = enabled["after"]["state"]
        physics = enabled_state["physics"]
        assert physics["enabled"] is False
        assert physics["playing"] is False
        assert physics["has_physics_scene"] is False
        assert physics["can_toggle_playing"] is False
        assert physics["pose_paths"] == []
        assert physics["pose_write_ordinals"] == []
        failure = physics["last_failure"]
        assert failure["operation"] == "ovphysx.enable"
        assert failure["exception_type"] == "OvstageRuntimePreflightError"
        assert "No module named 'ovphysx'" in failure["exception_text"]
        assert_real_borrow_renderer(enabled_state)
        assert_native_scene_state(enabled_state)


@pytest.mark.skipif(not _enabled(), reason=f"set {_RUN_ENV}=1 to run real Inspector QA")
def test_windowed_livestream_tees_borrowed_frame_and_shuts_down_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config = InspectorRuntimeConfig.from_environment(repo_root)
    workspace = tmp_path / "viewer-zero-copy"
    scene = _scene_copy(
        repo_root,
        workspace,
        "ovui-data-adapters/tests/data/ovstage_static_scene.usda",
    )
    evidence_root = tmp_path / "evidence" / "windowed-livestream"
    signal_port = _free_port()
    media_port = _free_port()
    monkeypatch.setenv("OVGEAR_LIVESTREAM", "1")
    monkeypatch.setenv("OVGEAR_ZERO_COPY", "1")
    monkeypatch.setenv("OVGEAR_LIVESTREAM_SIGNAL_PORT", str(signal_port))
    monkeypatch.setenv("OVGEAR_LIVESTREAM_MEDIA_PORT", str(media_port))
    monkeypatch.delenv("OMNIUI_HEADLESS", raising=False)

    application = InspectorAppProcess(config, workspace, scene=scene)
    with application:
        initial = application.wait_for_scene()
        assert_real_borrow_renderer(initial)
        assert_native_scene_state(initial)
        evidence = EvidenceRecorder(
            application.client,
            evidence_root,
            scenario=_WINDOWED_LIVESTREAM_SCENARIO,
        )
        image = initial["viewport"]["image_rect"]
        streamed = evidence.action(
            "advance-windowed-livestream-through-visible-viewport",
            lambda: application.client.move(
                int(float(image["x"]) + float(image["width"]) * 0.5),
                int(float(image["y"]) + float(image["height"]) * 0.5),
            ),
        )
        state = streamed["after"]["state"]
        tap = state["livestream"]["windowed"]
        assert tap["present"] is True
        assert tap["signal_port"] == signal_port
        assert tap["media_port"] == media_port
        assert tap["server_present"] is True
        assert tap["disabled"] is False
        assert tap["closed"] is False and tap["close_count"] == 0
        assert tap["tee_attempts"] > 0
        assert tap["frames_pushed"] + tap["frames_skipped"] == tap["tee_attempts"]
        assert tap["cuda_ring_size"] > 0
        assert state["renderer"]["livestream_zero_copy_tee_attempt_count"] > 0
        assert state["renderer"]["livestream_zero_copy_tee_success_count"] == tap[
            "frames_pushed"
        ]
        assert state["renderer"]["zero_copy"]["enabled"] is True
        assert state["renderer"]["zero_copy"]["fallback_reason"] == ""
        assert state["livestream"]["hud"]["state"] == tap["state"]
        assert str(signal_port) in state["livestream"]["hud"]["text"]
        assert_real_borrow_renderer(state)
        assert_native_scene_state(state)

    assert application.process is not None
    assert application.process.returncode == 0

    cpu_workspace = tmp_path / "viewer-cpu-fallback"
    cpu_scene = _scene_copy(
        repo_root,
        cpu_workspace,
        "ovui-data-adapters/tests/data/ovstage_static_scene.usda",
    )
    cpu_signal_port = _free_port()
    cpu_media_port = _free_port()
    monkeypatch.setenv("OVGEAR_ZERO_COPY", "0")
    monkeypatch.setenv("OVGEAR_LIVESTREAM_SIGNAL_PORT", str(cpu_signal_port))
    monkeypatch.setenv("OVGEAR_LIVESTREAM_MEDIA_PORT", str(cpu_media_port))

    cpu_application = InspectorAppProcess(config, cpu_workspace, scene=cpu_scene)
    with cpu_application:
        cpu_initial = cpu_application.wait_for_scene()
        assert_real_borrow_renderer(cpu_initial)
        assert_native_scene_state(cpu_initial)
        evidence.client = cpu_application.client
        cpu_image = cpu_initial["viewport"]["image_rect"]
        cpu_streamed = evidence.action(
            "advance-windowed-livestream-through-cpu-fallback",
            lambda: cpu_application.client.move(
                int(float(cpu_image["x"]) + float(cpu_image["width"]) * 0.5),
                int(float(cpu_image["y"]) + float(cpu_image["height"]) * 0.5),
            ),
        )
        cpu_state = cpu_streamed["after"]["state"]
        cpu_tap = cpu_state["livestream"]["windowed"]
        assert cpu_tap["present"] is True
        assert cpu_tap["signal_port"] == cpu_signal_port
        assert cpu_tap["media_port"] == cpu_media_port
        assert cpu_tap["server_present"] is True
        assert cpu_tap["disabled"] is False
        assert cpu_tap["closed"] is False and cpu_tap["close_count"] == 0
        assert cpu_tap["tee_attempts"] > 0
        assert cpu_tap["frames_pushed"] + cpu_tap["frames_skipped"] == cpu_tap[
            "tee_attempts"
        ]
        assert cpu_state["renderer"]["zero_copy"]["enabled"] is False
        assert cpu_state["renderer"]["livestream_cuda_tee_and_d2h_count"] > 0
        assert cpu_state["renderer"]["livestream_zero_copy_tee_attempt_count"] == 0
        assert cpu_streamed["after"]["viewport_stats"]["nonblack_pixels"] > 0
        assert_real_borrow_renderer(cpu_state)
        assert_native_scene_state(cpu_state)

    assert cpu_application.process is not None
    assert cpu_application.process.returncode == 0

    _record_feature_evidence(
        evidence,
        "livestream.windowed_viewport",
        {
            "mapped_ovrtx_rgba_tee": (
                f"zero-copy tap attempted {tap['tee_attempts']} mapped OVRTX RGBA frames; "
                f"CPU-mode tap attempted {cpu_tap['tee_attempts']}"
            ),
            "gpu_zero_copy_when_compatible": (
                "OVGEAR_ZERO_COPY=1 kept the mapped CUDA frame on the GPU and "
                f"attempted {state['renderer']['livestream_zero_copy_tee_attempt_count']} "
                "NVENC tees"
            ),
            "cpu_fallback_when_required": (
                "OVGEAR_ZERO_COPY=0 exercised the CUDA tee plus D2H presentation path "
                f"{cpu_state['renderer']['livestream_cuda_tee_and_d2h_count']} times"
            ),
            "mapping_lifetime_and_shutdown": (
                "both independently mapped viewport processes released mappings, "
                "closed the livestream/renderer lifecycle, and exited with status 0"
            ),
        },
    )
    manifest = evidence.finalize()
    assert manifest["summary"]["complete"] is True
    assert manifest["summary"]["passed"] is True

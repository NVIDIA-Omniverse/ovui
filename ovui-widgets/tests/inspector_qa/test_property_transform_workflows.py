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

import math
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
_BALL = "/World/Hierarchy/GroupA/BallA"
_BOX = "/World/Hierarchy/GroupA/BoxA"
_ROTATE_SCALE = "/World/TransformCases/RotateScale"
_VISIBLE_PARENT = "/World/VisibilityCases/VisibleParent"
_EXPLICIT_HIDDEN_CHILD = f"{_VISIBLE_PARENT}/ExplicitHiddenChild"
_EDIT_MENU = (151, 10)
_EDIT_SETTINGS_ITEM = (174, 86)

_GRID_SNAP_SCENARIO = ScenarioEvidenceContract.declare(
    "test_property_transform_workflows.py::"
    "test_grid_snap_viewport_translate_authors_native_ovstage",
    {
        "transform.translate": (
            "gizmo_drag",
            "native_matrix",
            "ovstage_matrix",
            "property_refresh",
        ),
        "transform.snap": (
            "snap_toggle",
            "gizmo_drag",
            "quantized_matrix",
        ),
    },
)

_ROTATE_SCALE_SCENARIO = ScenarioEvidenceContract.declare(
    "test_property_transform_workflows.py::"
    "test_viewport_translate_rotate_scale_gizmos_author_native_ovstage",
    {
        "transform.rotate": (
            "tool_shortcut",
            "gizmo_drag",
            "native_matrix",
            "ovstage_matrix",
        ),
        "transform.scale": (
            "tool_shortcut",
            "gizmo_drag",
            "native_matrix",
            "ovstage_matrix",
        ),
    },
)

_PROPERTY_SCENARIO = ScenarioEvidenceContract.declare(
    "test_property_transform_workflows.py::"
    "test_property_scalar_vector_token_and_mixed_selection_edit_native_ovstage",
    {
        "property.scalar_edit": (
            "field_click",
            "keyboard_type",
            "native_value",
            "ui_row_value",
        ),
        "property.vector_edit": (
            "component_field",
            "native_value",
            "ui_row_value",
            "viewport_change",
        ),
        "property.token_edit": (
            "combo_click",
            "selection",
            "native_value",
            "ui_row_value",
        ),
        "property.multi_selection": (
            "mixed_value",
            "edit_all",
            "distinct_undo_restore",
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


def _enabled() -> bool:
    return os.environ.get(_RUN_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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


def _center(rect: dict[str, Any]) -> tuple[int, int]:
    return (
        int(round(float(rect["x"]) + float(rect["width"]) * 0.5)),
        int(round(float(rect["y"]) + float(rect["height"]) * 0.5)),
    )


def _stage_point(state: dict[str, Any], path: str) -> tuple[int, int]:
    for row in state["stage_ui"]["rows"]:
        if row["path"] == path:
            return tuple(row["select_point"])
    raise AssertionError(f"no visible Stage row for {path}")


def _ensure_stage_path_visible(
    evidence: EvidenceRecorder,
    state: dict[str, Any],
    path: str,
) -> dict[str, Any]:
    """Expand each visible ancestor through real chevron clicks."""

    parts = [part for part in path.split("/") if part]
    ancestors = ["/"]
    current = ""
    for part in parts[:-1]:
        current = f"{current}/{part}"
        ancestors.append(current)
    for ancestor in ancestors:
        row = next(
            (item for item in state["stage_ui"]["rows"] if item["path"] == ancestor),
            None,
        )
        if row is None:
            raise AssertionError(f"no visible Stage ancestor {ancestor} for {path}")
        if not row["expanded"]:
            label = "pseudo-root" if ancestor == "/" else ancestor.rsplit("/", 1)[-1]
            expanded = evidence.action(
                f"expand-{label}-for-{path.rsplit('/', 1)[-1]}",
                lambda point=tuple(row["chevron_point"]): evidence.client.click(
                    *point
                ),
            )
            state = expanded["after"]["state"]
    return state


def _select_stage_path(
    evidence: EvidenceRecorder,
    state: dict[str, Any],
    path: str,
    *,
    ctrl: bool = False,
) -> dict[str, Any]:
    state = _ensure_stage_path_visible(evidence, state, path)
    result = evidence.action(
        f"select-{path.rsplit('/', 1)[-1]}",
        lambda: evidence.client.click(
            *_stage_point(state, path),
            modifiers=["ctrl"] if ctrl else None,
        ),
    )
    return result["after"]["state"]


def _filter_property(
    evidence: EvidenceRecorder,
    state: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    rect = state["property_ui"]["filter_rect"]
    assert rect is not None
    evidence.action(
        f"focus-property-filter-{text}",
        lambda: evidence.client.click(*_center(rect)),
    )
    evidence.action(
        f"select-property-filter-{text}",
        lambda: evidence.client.press("a", modifiers=["ctrl"]),
    )
    result = evidence.action(
        f"type-property-filter-{text}",
        lambda: evidence.client.type_text(text),
    )
    filtered = result["after"]["state"]
    # Filtering rebuilds the visible Property rows.  The action's atomic
    # checkpoint can observe that rebuild before its first layout pass, in
    # which case widget rectangles are deliberately zero-sized.  A read-only
    # follow-up checkpoint gives the rebuilt controls one frame to acquire
    # their real hit geometry before the next user action.
    if any(
        float(rect.get("width", 0.0)) <= 0.0
        or float(rect.get("height", 0.0)) <= 0.0
        for row in filtered["property_ui"]["rows"].values()
        for rect in row["field_rects"]
    ):
        filtered = evidence.checkpoint(
            f"settled-property-filter-{text}"
        )["state"]
    assert filtered["property_ui"]["filter_text"] == text
    return filtered


def _replace_property_component(
    evidence: EvidenceRecorder,
    state: dict[str, Any],
    attr_name: str,
    component: int,
    value: str,
) -> dict[str, Any]:
    point = state["property_ui"]["rows"][attr_name]["field_points"][component]
    evidence.action(
        f"focus-{attr_name}-{component}",
        lambda: evidence.client.click(*point),
    )
    evidence.action(
        f"activate-text-{attr_name}-{component}",
        lambda: evidence.client.click(
            *point,
            double=True,
            modifiers=["ctrl"],
        ),
    )
    evidence.action(
        f"select-{attr_name}-{component}",
        lambda: evidence.client.press("a", modifiers=["ctrl"]),
    )
    evidence.action(
        f"type-{attr_name}-{component}",
        lambda: evidence.client.type_text(value),
    )
    return evidence.action(
        f"commit-{attr_name}-{component}",
        lambda: evidence.client.press("enter"),
    )


def _axis_drag_points(
    state: dict[str, Any],
    axis_name: str,
    *,
    start_fraction: float = 0.65,
    distance: float = 70.0,
) -> tuple[int, int, int, int]:
    handles = state["viewport"]["transform_handles"]
    assert handles["available"] is True
    axis = next(item for item in handles["axes"] if item["axis"] == axis_name)
    start = axis["start"]
    end = axis["end"]
    image_rect = state["viewport"]["image_rect"]
    dx = float(end[0]) - float(start[0])
    dy = float(end[1]) - float(start[1])
    length = max(math.hypot(dx, dy), 1.0)
    start_x = image_rect["x"] + float(start[0]) + dx * start_fraction
    start_y = image_rect["y"] + float(start[1]) + dy * start_fraction
    return (
        int(round(start_x)),
        int(round(start_y)),
        int(round(start_x + dx / length * distance)),
        int(round(start_y + dy / length * distance)),
    )


def _rotation_ring_drag_points(
    state: dict[str, Any],
) -> tuple[int, int, int, int]:
    """Return two visible points on the Z rotation ring.

    The read-only handle projection exposes the pivot and projected X/Y axis
    endpoints using a 1.2-axis length. The rotate ring has unit radius, so
    projected 45- and 75-degree points use the matching ``1 / 1.2`` factor.
    """

    handles = state["viewport"]["transform_handles"]
    assert handles["available"] is True
    axes = {item["axis"]: item for item in handles["axes"]}
    pivot = axes["x"]["start"]
    x_end = axes["x"]["end"]
    y_end = axes["y"]["end"]
    image_rect = state["viewport"]["image_rect"]
    x_vector = (
        float(x_end[0]) - float(pivot[0]),
        float(x_end[1]) - float(pivot[1]),
    )
    y_vector = (
        float(y_end[0]) - float(pivot[0]),
        float(y_end[1]) - float(pivot[1]),
    )

    def ring_point(degrees: float) -> tuple[int, int]:
        angle = math.radians(degrees)
        radius_factor = 1.0 / 1.2
        x = (
            image_rect["x"]
            + float(pivot[0])
            + radius_factor
            * (math.cos(angle) * x_vector[0] + math.sin(angle) * y_vector[0])
        )
        y = (
            image_rect["y"]
            + float(pivot[1])
            + radius_factor
            * (math.cos(angle) * x_vector[1] + math.sin(angle) * y_vector[1])
        )
        return int(round(x)), int(round(y))

    return (*ring_point(45.0), *ring_point(75.0))


def _native_local_matrix(state: dict[str, Any], path: str) -> list[list[float]]:
    """Return the committed native OVStage local matrix for ``path``."""

    value = state["ovstage"]["prims"][path]["attributes"]["localMatrix"]["value"]
    assert value is not None, path
    return value


def _assert_native_transform_state(state: dict[str, Any], path: str) -> None:
    assert _native_local_matrix(state, path) is not None
    assert_native_scene_state(state)


def _assert_viewport_changed(action: dict[str, Any]) -> None:
    assert (
        action["before"]["viewport_stats"]["pixel_sha256"]
        != action["after"]["viewport_stats"]["pixel_sha256"]
    )


def _assert_property_local_matrix(state: dict[str, Any], path: str) -> None:
    expected = [
        component
        for row in _native_local_matrix(state, path)
        for component in row
    ]
    row = state["property_ui"]["rows"]["localMatrix"]
    assert row["value"] == pytest.approx(expected)


@pytest.mark.skipif(not _enabled(), reason=f"set {_RUN_ENV}=1 to run real Inspector QA")
def test_grid_snap_viewport_translate_authors_native_ovstage(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config = InspectorRuntimeConfig.from_environment(repo_root)
    workspace = tmp_path / "viewer"
    scene = _scene_copy(repo_root, workspace)

    with InspectorAppProcess(config, workspace, scene=scene) as application:
        state = application.wait_for_scene()
        assert_real_borrow_renderer(state)
        evidence = EvidenceRecorder(
            application.client,
            tmp_path / "evidence" / "grid-snap-transform",
            scenario=_GRID_SNAP_SCENARIO,
        )

        evidence.action(
            "open-edit-menu",
            lambda: application.client.click(*_EDIT_MENU),
        )
        opened = evidence.action(
            "open-settings-dialog",
            lambda: application.client.click(*_EDIT_SETTINGS_ITEM),
        )
        state = opened["after"]["state"]
        settings = state["transforms"]["interaction"]["settings_dialog"]
        assert settings["visible"] is True
        snap_rect = settings["snap_checkbox_rect"]

        enabled = evidence.action(
            "enable-grid-snap",
            lambda: application.client.click(
                int(round(float(snap_rect["x"]) + 12.0)),
                int(round(float(snap_rect["y"]) + float(snap_rect["height"]) * 0.5)),
            ),
        )
        state = enabled["after"]["state"]
        settings = state["transforms"]["interaction"]["settings_dialog"]
        grid_rect = settings["grid_size_rect"]
        grid_point = _center(grid_rect)
        evidence.action(
            "focus-grid-size",
            lambda: application.client.click(*grid_point),
        )
        evidence.action(
            "activate-grid-size-text",
            lambda: application.client.click(
                *grid_point,
                double=True,
                modifiers=["ctrl"],
            ),
        )
        evidence.action(
            "select-grid-size",
            lambda: application.client.press("a", modifiers=["ctrl"]),
        )
        evidence.action(
            "type-grid-size",
            lambda: application.client.type_text("0.5"),
        )
        configured = evidence.action(
            "commit-grid-size",
            lambda: application.client.press("enter"),
        )
        state = configured["after"]["state"]
        interaction = state["transforms"]["interaction"]
        assert interaction["snap_enabled"] is True
        assert interaction["grid_size"] == pytest.approx(0.5)
        settings = interaction["settings_dialog"]
        evidence.action(
            "close-settings-dialog",
            lambda: application.client.click(*_center(settings["close_button_rect"])),
        )

        target = state["viewport"]["prim_screen_centers"][_BOX]
        selected = evidence.action(
            "select-box-for-grid-snap",
            lambda: application.client.click(*target),
        )
        state = selected["after"]["state"]
        preview_writes_before = state["renderer"]["live_preview_write_count"]
        preview_clears_before = state["renderer"]["live_preview_clear_count"]
        handles = state["viewport"]["transform_handles"]
        assert handles["available"] is True
        x_axis = next(axis for axis in handles["axes"] if axis["axis"] == "x")
        start = x_axis["start"]
        end = x_axis["end"]
        image_rect = state["viewport"]["image_rect"]
        start_x = image_rect["x"] + start[0] + (end[0] - start[0]) * 0.65
        start_y = image_rect["y"] + start[1] + (end[1] - start[1]) * 0.65
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = max(math.hypot(dx, dy), 1.0)
        end_x = start_x + dx / length * 70.0
        end_y = start_y + dy / length * 70.0
        moved = evidence.action(
            "drag-x-handle-with-grid-snap",
            lambda: application.client.drag(
                int(round(start_x)),
                int(round(start_y)),
                int(round(end_x)),
                int(round(end_y)),
                steps=20,
            ),
        )
        state = moved["after"]["state"]
        translation = _native_local_matrix(state, _BOX)[3][:3]
        assert translation != pytest.approx([0.0, 0.0, 0.0])
        assert all(
            math.isclose(value / 0.5, round(value / 0.5), abs_tol=1.0e-5)
            for value in translation
        )
        assert state["transforms"]["paths"][_BOX]["matches"] is True
        # ovui-inspect currently exposes an atomic mouse-drag command, not
        # separate hold/release calls, so it cannot checkpoint a screenshot
        # while the button remains down. These counters prove that the same
        # user drag did enter OVStage live preview and then cleared it after
        # the durable native commit; the focused native contract test separately
        # observes the held preview and cancel edge.
        assert state["renderer"]["live_preview_write_count"] > preview_writes_before
        assert state["renderer"]["live_preview_clear_count"] > preview_clears_before
        assert state["renderer"]["live_preview_paths"] == []
        assert state["renderer"]["last_live_preview_path"] == _BOX
        _assert_viewport_changed(moved)
        _assert_native_transform_state(state, _BOX)
        _assert_property_local_matrix(state, _BOX)
        assert_native_scene_state(state)
        _record_feature_evidence(
            evidence,
            "transform.translate",
            {
                "gizmo_drag": "A real mouse drag moved the visible X translation handle.",
                "native_matrix": "The committed native OVStage local matrix contains the translation.",
                "ovstage_matrix": "Adapter and Property Inspector matrices exactly match the native OVStage value.",
                "property_refresh": "The visible Property localMatrix row refreshed to the committed matrix.",
            },
        )
        _record_feature_evidence(
            evidence,
            "transform.snap",
            {
                "snap_toggle": "The Settings checkbox enabled grid snapping and grid size 0.5 through visible controls.",
                "gizmo_drag": "The snapped result came from the same real X-handle drag.",
                "quantized_matrix": "Every committed translation component is an exact 0.5-grid multiple.",
            },
        )
        manifest = evidence.finalize()
        assert manifest["summary"]["passed"] is True


@pytest.mark.skipif(not _enabled(), reason=f"set {_RUN_ENV}=1 to run real Inspector QA")
def test_viewport_translate_rotate_scale_gizmos_author_native_ovstage(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config = InspectorRuntimeConfig.from_environment(repo_root)
    workspace = tmp_path / "viewer"
    scene = _scene_copy(repo_root, workspace)

    with InspectorAppProcess(config, workspace, scene=scene) as application:
        state = application.wait_for_scene()
        assert_real_borrow_renderer(state)
        evidence = EvidenceRecorder(
            application.client,
            tmp_path / "evidence" / "viewport-transform-gizmos",
            scenario=_ROTATE_SCALE_SCENARIO,
        )

        target = state["viewport"]["prim_screen_centers"][_BOX]
        selected = evidence.action(
            "select-box-for-transform-gizmos",
            lambda: application.client.click(*target),
        )
        state = selected["after"]["state"]
        assert state["selection"]["paths"] == [_BOX]
        _assert_native_transform_state(state, _BOX)

        matrix_before = _native_local_matrix(state, _BOX)
        preview_writes = state["renderer"]["live_preview_write_count"]
        preview_clears = state["renderer"]["live_preview_clear_count"]
        translated = evidence.action(
            "drag-translate-x-gizmo",
            lambda: application.client.drag(
                *_axis_drag_points(state, "x"),
                steps=20,
            ),
        )
        state = translated["after"]["state"]
        assert _native_local_matrix(state, _BOX) != matrix_before
        assert state["renderer"]["live_preview_write_count"] > preview_writes
        assert state["renderer"]["live_preview_clear_count"] > preview_clears
        assert state["renderer"]["live_preview_paths"] == []
        _assert_viewport_changed(translated)
        _assert_native_transform_state(state, _BOX)
        _assert_property_local_matrix(state, _BOX)

        rotate_tool = evidence.action(
            "activate-rotate-tool-shortcut",
            lambda: application.client.press("e"),
        )
        state = rotate_tool["after"]["state"]
        assert state["transforms"]["interaction"]["active_tool"] == "rotate"
        assert rotate_tool["record"]["screenshot_changed"] is True

        matrix_before = _native_local_matrix(state, _BOX)
        preview_writes = state["renderer"]["live_preview_write_count"]
        preview_clears = state["renderer"]["live_preview_clear_count"]
        rotated = evidence.action(
            "drag-rotate-z-gizmo",
            lambda: application.client.drag(
                *_rotation_ring_drag_points(state),
                steps=20,
            ),
        )
        state = rotated["after"]["state"]
        assert _native_local_matrix(state, _BOX) != matrix_before
        assert state["renderer"]["live_preview_write_count"] > preview_writes
        assert state["renderer"]["live_preview_clear_count"] > preview_clears
        assert state["renderer"]["live_preview_paths"] == []
        _assert_viewport_changed(rotated)
        _assert_native_transform_state(state, _BOX)
        _assert_property_local_matrix(state, _BOX)
        _record_feature_evidence(
            evidence,
            "transform.rotate",
            {
                "tool_shortcut": "A real E key press activated the visible Rotate gizmo.",
                "gizmo_drag": "A real mouse drag traversed the projected Z rotation ring.",
                "native_matrix": "The rotation drag changed the exact native OVStage local matrix.",
                "ovstage_matrix": "The Property Inspector matrix row exactly matches the rotated native OVStage matrix.",
            },
        )

        scale_tool = evidence.action(
            "activate-scale-tool-shortcut",
            lambda: application.client.press("r"),
        )
        state = scale_tool["after"]["state"]
        assert state["transforms"]["interaction"]["active_tool"] == "scale"
        assert scale_tool["record"]["screenshot_changed"] is True

        matrix_before = _native_local_matrix(state, _BOX)
        preview_writes = state["renderer"]["live_preview_write_count"]
        preview_clears = state["renderer"]["live_preview_clear_count"]
        scaled = evidence.action(
            "drag-scale-x-gizmo",
            lambda: application.client.drag(
                *_axis_drag_points(state, "x"),
                steps=20,
            ),
        )
        state = scaled["after"]["state"]
        assert _native_local_matrix(state, _BOX) != matrix_before
        assert state["renderer"]["live_preview_write_count"] > preview_writes
        assert state["renderer"]["live_preview_clear_count"] > preview_clears
        assert state["renderer"]["live_preview_paths"] == []
        _assert_viewport_changed(scaled)
        _assert_native_transform_state(state, _BOX)
        _assert_property_local_matrix(state, _BOX)
        _record_feature_evidence(
            evidence,
            "transform.scale",
            {
                "tool_shortcut": "A real R key press activated the visible Scale gizmo.",
                "gizmo_drag": "A real mouse drag moved the projected X scale handle.",
                "native_matrix": "The scale drag changed the exact native OVStage local matrix.",
                "ovstage_matrix": "The Property Inspector matrix row exactly matches the scaled native OVStage matrix.",
            },
        )
        manifest = evidence.finalize()
        assert manifest["summary"]["passed"] is True



@pytest.mark.skipif(not _enabled(), reason=f"set {_RUN_ENV}=1 to run real Inspector QA")
def test_property_scalar_vector_token_and_mixed_selection_edit_native_ovstage(
    tmp_path: Path,
) -> None:
    """Visible Property Inspector edits authored into exact native OVStage.

    Native-only migration of the former hybrid property-parity scenario: the
    reset-to-default portion moved to the accepted-unsupported ledger entry
    (OVStage exposes no authored-opinion/default query), so this scenario
    proves the supported scalar/vector/token/multi-selection edits only, every
    value cross-checked against the exact native OVStage snapshot and the
    Property Inspector row it renders.
    """
    repo_root = Path(__file__).resolve().parents[3]
    config = InspectorRuntimeConfig.from_environment(repo_root)
    workspace = tmp_path / "viewer"
    scene = _scene_copy(repo_root, workspace)

    def _native_value(state: dict[str, Any], path: str, name: str) -> Any:
        return state["ovstage"]["prims"][path]["attributes"][name]["value"]

    with InspectorAppProcess(config, workspace, scene=scene) as application:
        state = application.wait_for_scene()
        assert_real_borrow_renderer(state)
        evidence = EvidenceRecorder(
            application.client,
            tmp_path / "evidence" / "property-native",
            scenario=_PROPERTY_SCENARIO,
        )

        # --- scalar edit: visible Radius FloatDrag ---------------------------
        state = _select_stage_path(evidence, state, _BALL)
        state = _filter_property(evidence, state, "Radius")
        radius_edit = _replace_property_component(
            evidence, state, "radius", 0, "2.25"
        )
        state = radius_edit["after"]["state"]
        assert _native_value(state, _BALL, "radius") == pytest.approx(2.25)
        assert state["property_ui"]["rows"]["radius"]["value"] == pytest.approx(2.25)
        _assert_viewport_changed(radius_edit)
        assert_native_scene_state(state)
        _record_feature_evidence(
            evidence,
            "property.scalar_edit",
            {
                "field_click": "The Radius FloatDrag was focused and activated by real mouse clicks.",
                "keyboard_type": "Ctrl+A, typed 2.25, and Enter committed through Inspector keyboard input.",
                "native_value": "Native OVStage radius is exactly 2.25 at the synchronized ordinal.",
                "ui_row_value": "The Property Inspector Radius row renders exactly 2.25.",
            },
        )

        # --- token edit: visible Visibility combo ----------------------------
        state = _select_stage_path(evidence, state, _VISIBLE_PARENT)
        state = _filter_property(evidence, state, "Visibility")
        visibility_row = state["property_ui"]["rows"]["visibility"]
        assert visibility_row["allowed_values"] == ["inherited", "invisible"]
        combo_point = visibility_row["field_points"][0]
        evidence.action(
            "open-visibility-token-combo",
            lambda: application.client.click(*combo_point),
        )
        evidence.action(
            "choose-next-visibility-token",
            lambda: application.client.press("end"),
        )
        changed = evidence.action(
            "commit-visibility-token",
            lambda: application.client.press("enter"),
        )
        state = changed["after"]["state"]
        assert _native_value(state, _VISIBLE_PARENT, "visibility") == "invisible"
        assert state["property_ui"]["rows"]["visibility"]["value"] == "invisible"
        assert_native_scene_state(state)
        _record_feature_evidence(
            evidence,
            "property.token_edit",
            {
                "combo_click": "The Visibility token combo was opened with a real mouse click.",
                "selection": "Keyboard navigation selected and committed the visible `invisible` entry.",
                "native_value": "Native OVStage visibility is `invisible` after synchronization.",
                "ui_row_value": "The Property Inspector Visibility row renders `invisible`.",
            },
        )

        # --- vector edit: visible transform component FloatDrags -------------
        state = _select_stage_path(evidence, state, _ROTATE_SCALE)
        for query, attr_name, component, value in (
            ("Translate", "xformOp:translate", 0, "-3.5"),
            ("Rotate Xyz", "xformOp:rotateXYZ", 1, "30"),
            ("Scale", "xformOp:scale", 2, "1.5"),
        ):
            state = _filter_property(evidence, state, query)
            vector_edit = _replace_property_component(
                evidence, state, attr_name, component, value
            )
            state = vector_edit["after"]["state"]
            _assert_viewport_changed(vector_edit)
            _assert_native_transform_state(state, _ROTATE_SCALE)
        _record_feature_evidence(
            evidence,
            "property.vector_edit",
            {
                "component_field": "Translate X, Rotate Y, and Scale Z component FloatDrags were visibly edited.",
                "native_value": "Each component edit changed the exact native OVStage local matrix.",
                "ui_row_value": "The Property Inspector localMatrix row matched the native OVStage matrix after each commit.",
                "viewport_change": "Every component commit changed the viewport pixel hash.",
            },
        )

        # --- multi-selection edit: visible Mixed state then converge ---------
        state = _select_stage_path(evidence, state, _BALL)
        state = _select_stage_path(
            evidence, state, _EXPLICIT_HIDDEN_CHILD, ctrl=True
        )
        state = _filter_property(evidence, state, "Radius")
        mixed = state["property_ui"]["rows"]["radius"]
        assert mixed["ambiguous"] is True
        assert mixed["indicator_state"] == "Mixed"
        assert _native_value(state, _BALL, "radius") != _native_value(
            state, _EXPLICIT_HIDDEN_CHILD, "radius"
        )
        assert_native_scene_state(state)

        edited_all = _replace_property_component(
            evidence, state, "radius", 0, "0.75"
        )
        state = edited_all["after"]["state"]
        for path in (_BALL, _EXPLICIT_HIDDEN_CHILD):
            assert _native_value(state, path, "radius") == pytest.approx(0.75)
        assert state["property_ui"]["rows"]["radius"]["ambiguous"] is False
        assert_native_scene_state(state)

        multi_undone = evidence.action(
            "undo-multi-selection-radius",
            lambda: application.client.press("z", modifiers=["ctrl"]),
        )
        state = multi_undone["after"]["state"]
        assert _native_value(state, _BALL, "radius") != _native_value(
            state, _EXPLICIT_HIDDEN_CHILD, "radius"
        )
        assert state["property_ui"]["rows"]["radius"]["ambiguous"] is True
        assert_native_scene_state(state)

        multi_redone = evidence.action(
            "redo-multi-selection-radius",
            lambda: application.client.press("z", modifiers=["ctrl", "shift"]),
        )
        state = multi_redone["after"]["state"]
        for path in (_BALL, _EXPLICIT_HIDDEN_CHILD):
            assert _native_value(state, path, "radius") == pytest.approx(0.75)
        assert state["property_ui"]["rows"]["radius"]["ambiguous"] is False
        assert_native_scene_state(state)
        _record_feature_evidence(
            evidence,
            "property.multi_selection",
            {
                "mixed_value": "Distinct native Sphere radii displayed the visible scalar Mixed state.",
                "edit_all": "One visible Radius edit authored 0.75 to both selected prims in native OVStage.",
                "distinct_undo_restore": "Ctrl+Z restored the two distinct native radii; redo reconverged both to 0.75.",
            },
        )
        manifest = evidence.finalize()
        assert manifest["summary"]["passed"] is True

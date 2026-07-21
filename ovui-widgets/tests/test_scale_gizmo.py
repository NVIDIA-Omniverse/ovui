# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the Step C.4 scale gizmo.

Covers:

* Public constants (cube size, shaft length, clamp).
* Geometry emitted by :func:`build_scale_gizmo` (3 shafts + 3 cubes + 1
  uniform cube + 1 uniform hit target, colours, gesture wiring).
* :class:`PrimScaleChangedGesture` drag lifecycle — begin opens the
  ``"Scale Prims"`` undo group, changed accumulates projected length +
  writes the scale factor, ended closes the group.
* Uniform handle behaviour — projection axis defaults to the diagonal,
  ``(1, 1, 1)`` axis mask hands uniform scale to the model.
* End-to-end: scaling along each axis leaves the others unchanged and
  the translation row preserved; a single :meth:`UndoManager.undo`
  reverts a multi-frame drag.
* :class:`TransformManipulator` integration — selecting + scale tool
  populates ``scale_handles``.
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from omni.ui_scene import scene as sc

from ovui_widgets.common.testing.mock_transform import MockTransformAdapter
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.viewport.prim_transform_model import PrimTransformModel
from ovui_widgets.viewport.scale_gizmo import (
    CUBE_HALF,
    HIGHLIGHT_COLOR_UNIFORM,
    MIN_SCALE_FACTOR,
    SHAFT_INTERSECTION_THICKNESS,
    SHAFT_LENGTH,
    SHAFT_THICKNESS,
    UNIFORM_COLOR,
    UNIFORM_CUBE_HALF,
    UNIFORM_HIT_HALF,
    PrimScaleChangedGesture,
    ScaleGizmoHandles,
    build_scale_gizmo,
)
from ovui_widgets.viewport.transform_manipulator import (
    AXIS_COLOR_X,
    AXIS_COLOR_Y,
    AXIS_COLOR_Z,
    TOOL_SCALE,
    TransformManipulator,
)
from ovui_widgets.viewport.translate_gizmo import (
    HIGHLIGHT_COLOR_X,
    HIGHLIGHT_COLOR_Y,
    HIGHLIGHT_COLOR_Z,
    HighlightGesture,
)

# -- fixtures --------------------------------------------------------------


@pytest.fixture
def scene_view() -> sc.SceneView:
    return sc.SceneView()


@contextmanager
def _cm():
    yield


def _make_mock_stage() -> MagicMock:
    stage = MagicMock()
    stage.suppress_change_notifications.side_effect = lambda: _cm()
    return stage


@pytest.fixture
def wired_model() -> PrimTransformModel:
    """Model with real mock adapters, selection already populated."""
    transform = MockTransformAdapter()
    transform.set_local_transform(
        "/World/Cube",
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [2.0, 3.0, 4.0, 1.0],
        ],
    )
    stage = _make_mock_stage()
    undo = UndoManager()
    model = PrimTransformModel(transform, stage, undo)
    model.set_selection(["/World/Cube"])
    return model


@pytest.fixture
def empty_model() -> PrimTransformModel:
    return PrimTransformModel()


def _fake_sender_with_moved(x: float, y: float, z: float) -> SimpleNamespace:
    """Stand-in for a shape's drag sender with a world-space ``moved`` delta."""
    moved = SimpleNamespace(x=x, y=y, z=z)
    payload = SimpleNamespace(moved=moved)
    return SimpleNamespace(gesture_payload=payload)


# -- constants -------------------------------------------------------------


class TestConstants:
    def test_shaft_length_matches_translate(self):
        # Visual consistency with the translate gizmo — scale cube sits
        # where translate cone cap would, making tool-switches seamless.
        assert SHAFT_LENGTH == pytest.approx(1.0)

    def test_shaft_thickness_is_thin(self):
        # "Thin and elegant, not chunky" — same cap as translate.
        assert 1.0 <= SHAFT_THICKNESS <= 3.0

    def test_intersection_thickness_is_grabbable(self):
        assert SHAFT_INTERSECTION_THICKNESS >= SHAFT_THICKNESS * 3.0

    def test_cube_half_is_small(self):
        # Small + elegant: ~7% of shaft length. Never chunky.
        assert CUBE_HALF <= 0.10
        assert CUBE_HALF >= 0.04

    def test_uniform_cube_smaller_than_axis(self):
        # Uniform cube is visually distinct — slightly smaller so it
        # doesn't merge with the three axis cubes at origin.
        assert UNIFORM_CUBE_HALF < CUBE_HALF

    def test_uniform_hit_larger_than_cube(self):
        # Hit target oversized vs. visible cube so picking isn't a
        # pixel hunt.
        assert UNIFORM_HIT_HALF > UNIFORM_CUBE_HALF

    def test_min_scale_factor_is_positive(self):
        # Floor keeps geometry non-mirrored/non-degenerate during drag.
        assert 0.0 < MIN_SCALE_FACTOR <= 0.1

    def test_uniform_colors_are_neutral(self):
        # Uniform handle should read as grey/white, NOT red/green/blue
        # (otherwise it competes with the per-axis handles).
        assert UNIFORM_COLOR != AXIS_COLOR_X
        assert UNIFORM_COLOR != AXIS_COLOR_Y
        assert UNIFORM_COLOR != AXIS_COLOR_Z
        assert HIGHLIGHT_COLOR_UNIFORM != UNIFORM_COLOR


# -- geometry builder -----------------------------------------------------


class TestBuildScaleGizmo:
    def test_returns_scale_gizmo_handles(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_scale_gizmo(wired_model)
        assert isinstance(handles, ScaleGizmoHandles)

    def test_produces_three_axis_shafts(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_scale_gizmo(wired_model)
        assert len(handles.shafts) == 3

    def test_produces_three_axis_cubes(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_scale_gizmo(wired_model)
        assert len(handles.cubes) == 3

    def test_cubes_provide_color_for_every_face_vertex(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_scale_gizmo(wired_model)
        for cube in [*handles.cubes, handles.uniform_cube]:
            assert len(cube.colors) == len(cube.vertex_indices)

    def test_produces_uniform_cube_and_hit_target(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_scale_gizmo(wired_model)
        assert handles.uniform_cube is not None
        assert handles.uniform_hit is not None

    def test_produces_four_drag_gestures_total(self, scene_view, wired_model):
        # 3 axis + 1 uniform — the uniform gesture lives on
        # ``uniform_drag`` so the axis list stays exactly three.
        with scene_view.scene:
            handles = build_scale_gizmo(wired_model)
        assert len(handles.drag_gestures) == 3
        for g in handles.drag_gestures:
            assert isinstance(g, PrimScaleChangedGesture)
        assert isinstance(handles.uniform_drag, PrimScaleChangedGesture)

    def test_produces_four_hover_gestures(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_scale_gizmo(wired_model)
        assert len(handles.hover_gestures) == 3
        for h in handles.hover_gestures:
            assert isinstance(h, HighlightGesture)
        assert isinstance(handles.uniform_hover, HighlightGesture)

    def test_axis_masks_are_per_axis(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_scale_gizmo(wired_model)
        assert handles.drag_gestures[0].axis == (1.0, 0.0, 0.0)
        assert handles.drag_gestures[1].axis == (0.0, 1.0, 0.0)
        assert handles.drag_gestures[2].axis == (0.0, 0.0, 1.0)

    def test_uniform_axis_mask(self, scene_view, wired_model):
        # Uniform gesture advertises (1,1,1) so ``on_drag_scaled`` applies
        # the factor to all three axes.
        with scene_view.scene:
            handles = build_scale_gizmo(wired_model)
        assert handles.uniform_drag.axis == (1.0, 1.0, 1.0)
        assert handles.uniform_drag.is_uniform is True

    def test_gesture_for_axis_lookup(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_scale_gizmo(wired_model)
        assert handles.gesture_for_axis("x").axis == (1.0, 0.0, 0.0)
        assert handles.gesture_for_axis("Y").axis == (0.0, 1.0, 0.0)
        assert handles.gesture_for_axis("z").axis == (0.0, 0.0, 1.0)

    def test_highlight_colors_per_axis(self, scene_view, wired_model):
        # Guard against copy-paste bug where X cube flashes the Y colour.
        with scene_view.scene:
            handles = build_scale_gizmo(wired_model)
        pairs = [
            (handles.hover_gestures[0], AXIS_COLOR_X, HIGHLIGHT_COLOR_X),
            (handles.hover_gestures[1], AXIS_COLOR_Y, HIGHLIGHT_COLOR_Y),
            (handles.hover_gestures[2], AXIS_COLOR_Z, HIGHLIGHT_COLOR_Z),
        ]
        for hover, base, hl in pairs:
            assert hover._base_color == base
            assert hover._highlight_color == hl

    def test_uniform_highlight_colours(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_scale_gizmo(wired_model)
        assert handles.uniform_hover._base_color == UNIFORM_COLOR
        assert handles.uniform_hover._highlight_color == HIGHLIGHT_COLOR_UNIFORM

    def test_hover_attached_to_shaft_and_cube(self, scene_view, wired_model):
        # Both the shaft and the tip cube must flash on hover — the hover
        # list should contain both shapes after construction.
        with scene_view.scene:
            handles = build_scale_gizmo(wired_model)
        for shaft, cube, hover in zip(
            handles.shafts, handles.cubes, handles.hover_gestures
        ):
            assert shaft in hover._shapes
            assert cube in hover._shapes

    def test_uniform_hover_covers_cube(self, scene_view, wired_model):
        # The uniform cube must flash when the hit rectangle is hovered.
        with scene_view.scene:
            handles = build_scale_gizmo(wired_model)
        assert handles.uniform_cube in handles.uniform_hover._shapes


# -- PrimScaleChangedGesture construction ---------------------------------


class TestPrimScaleChangedGestureConstruction:
    def test_rejects_zero_axis(self):
        with pytest.raises(ValueError):
            PrimScaleChangedGesture(model=MagicMock(), axis=(0.0, 0.0, 0.0))

    def test_rejects_zero_projection_axis(self):
        with pytest.raises(ValueError):
            PrimScaleChangedGesture(
                model=MagicMock(),
                axis=(1.0, 0.0, 0.0),
                projection_axis=(0.0, 0.0, 0.0),
            )

    def test_normalises_projection_axis(self):
        g = PrimScaleChangedGesture(
            model=MagicMock(),
            axis=(1.0, 0.0, 0.0),
            projection_axis=(0.0, 3.0, 0.0),
        )
        assert g.projection_axis == (0.0, 1.0, 0.0)

    def test_axis_preserved_verbatim(self):
        # The axis mask is NOT normalised — (1,1,1) stays (1,1,1).
        g = PrimScaleChangedGesture(
            model=MagicMock(), axis=(1.0, 1.0, 1.0), uniform=True,
        )
        assert g.axis == (1.0, 1.0, 1.0)

    def test_uniform_defaults_to_diagonal_projection(self):
        # Drag right OR up → scale up; the default picks (1,1,0)/√2.
        g = PrimScaleChangedGesture(
            model=MagicMock(), axis=(1.0, 1.0, 1.0), uniform=True,
        )
        inv = 1.0 / math.sqrt(2.0)
        assert g.projection_axis[0] == pytest.approx(inv)
        assert g.projection_axis[1] == pytest.approx(inv)
        assert g.projection_axis[2] == pytest.approx(0.0)

    def test_constrained_projection_defaults_to_axis(self):
        g = PrimScaleChangedGesture(
            model=MagicMock(), axis=(0.0, 1.0, 0.0),
        )
        assert g.projection_axis == (0.0, 1.0, 0.0)

    def test_initial_state_inactive(self):
        g = PrimScaleChangedGesture(model=MagicMock(), axis=(1.0, 0.0, 0.0))
        assert g.is_active is False
        assert g.accumulated_length == 0.0
        assert g.current_factor == pytest.approx(1.0)


# -- PrimScaleChangedGesture lifecycle ------------------------------------


class TestPrimScaleChangedGestureLifecycle:
    def test_began_without_selection_stays_inert(self, empty_model):
        g = PrimScaleChangedGesture(model=empty_model, axis=(1.0, 0.0, 0.0))
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        assert g.is_active is False

    def test_began_with_selection_opens_scale_undo_group(self, wired_model):
        g = PrimScaleChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        assert g.is_active is True
        wired_model._stage.begin_undo_group.assert_called_once_with("Scale Prims")

    def test_began_with_broken_adapter_goes_inert(self):
        model = PrimTransformModel()
        model._selected_paths = ["/World/Cube"]  # no adapters → raises
        g = PrimScaleChangedGesture(model=model, axis=(1.0, 0.0, 0.0))
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        assert g.is_active is False

    def test_changed_accumulates_projected_delta(self, wired_model):
        g = PrimScaleChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        # Drag +0.3 along world X; projection axis is (1,0,0).
        g._on_changed(_fake_sender_with_moved(0.3, 0.0, 0.0))
        assert g.accumulated_length == pytest.approx(0.3)
        # Another +0.2: accumulated = 0.5.
        g._on_changed(_fake_sender_with_moved(0.2, 0.0, 0.0))
        assert g.accumulated_length == pytest.approx(0.5)

    def test_changed_ignores_off_axis_noise(self, wired_model):
        # Projection kills perpendicular components — a Y-axis handle
        # should NOT accumulate from world-X mouse deltas.
        g = PrimScaleChangedGesture(model=wired_model, axis=(0.0, 1.0, 0.0))
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        g._on_changed(_fake_sender_with_moved(1.0, 0.0, 0.0))
        assert g.accumulated_length == pytest.approx(0.0)

    def test_changed_produces_scale_factor(self, wired_model):
        # +0.25 along the shaft with SHAFT_LENGTH 1.0 → factor 1.25.
        g = PrimScaleChangedGesture(model=wired_model, axis=(0.0, 0.0, 1.0))
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        g._on_changed(_fake_sender_with_moved(0.0, 0.0, 0.25))
        assert g.current_factor == pytest.approx(1.25)

    def test_changed_clamps_negative_factor(self, wired_model):
        # Drag backwards past -1 * SHAFT_LENGTH should clamp, not mirror.
        g = PrimScaleChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        g._on_changed(_fake_sender_with_moved(-5.0, 0.0, 0.0))
        assert g.current_factor == pytest.approx(MIN_SCALE_FACTOR)

    def test_changed_while_inactive_is_noop(self, wired_model):
        g = PrimScaleChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_changed(_fake_sender_with_moved(0.5, 0.0, 0.0))
        assert g.accumulated_length == 0.0

    def test_changed_records_scale_preview(self, wired_model):
        # +0.5 along world X with axis=(1,0,0) → sx = 1.5, others = 1.0.
        g = PrimScaleChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        g._on_changed(_fake_sender_with_moved(0.5, 0.0, 0.0))
        assert wired_model._transform.get_local_transform("/World/Cube")[0][0] == pytest.approx(1.0)
        mat = wired_model._live_transforms["/World/Cube"]
        assert mat[0][0] == pytest.approx(1.5)
        assert mat[1][1] == pytest.approx(1.0)
        assert mat[2][2] == pytest.approx(1.0)
        # Translation row preserved — scale about prim's own origin.
        assert mat[3][0] == pytest.approx(2.0)
        assert mat[3][1] == pytest.approx(3.0)
        assert mat[3][2] == pytest.approx(4.0)

    def test_ended_calls_drag_ended(self, wired_model):
        g = PrimScaleChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        g._on_ended(_fake_sender_with_moved(0.0, 0.0, 0.0))
        wired_model._stage.end_undo_group.assert_called_once()
        assert g.is_active is False

    def test_ended_while_inactive_is_noop(self, wired_model):
        g = PrimScaleChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_ended(_fake_sender_with_moved(0.0, 0.0, 0.0))
        wired_model._stage.end_undo_group.assert_not_called()


# -- Uniform gesture behaviour --------------------------------------------


class TestUniformScaleGesture:
    def test_uniform_records_same_factor_all_axes(self, wired_model):
        # Uniform factor 1.5 should scale X, Y, Z identically and preserve
        # the translation row.
        g = PrimScaleChangedGesture(
            model=wired_model, axis=(1.0, 1.0, 1.0), uniform=True,
            projection_axis=(1.0, 0.0, 0.0),  # deterministic for the test
        )
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        g._on_changed(_fake_sender_with_moved(0.5, 0.0, 0.0))
        assert wired_model._transform.get_local_transform("/World/Cube")[0][0] == pytest.approx(1.0)
        mat = wired_model._live_transforms["/World/Cube"]
        assert mat[0][0] == pytest.approx(1.5)
        assert mat[1][1] == pytest.approx(1.5)
        assert mat[2][2] == pytest.approx(1.5)
        assert mat[3][0] == pytest.approx(2.0)
        assert mat[3][1] == pytest.approx(3.0)
        assert mat[3][2] == pytest.approx(4.0)

    def test_uniform_drag_diagonal_mouse_scales_up(self, wired_model):
        # Default projection is (1,1,0)/√2 — dragging up-right should
        # produce factor > 1 after one frame.
        g = PrimScaleChangedGesture(
            model=wired_model, axis=(1.0, 1.0, 1.0), uniform=True,
        )
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        g._on_changed(_fake_sender_with_moved(0.3, 0.3, 0.0))
        assert g.current_factor > 1.0


# -- Undo integration -----------------------------------------------------


class TestPrimScaleChangedGestureUndo:
    def test_single_undo_reverts_scale(self, wired_model):
        initial = wired_model._transform.get_local_transform("/World/Cube")
        g = PrimScaleChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        g._on_changed(_fake_sender_with_moved(0.5, 0.0, 0.0))
        g._on_ended(_fake_sender_with_moved(0.5, 0.0, 0.0))
        scaled = wired_model._transform.get_local_transform("/World/Cube")
        assert scaled[0][0] == pytest.approx(1.5)
        assert wired_model._undo.undo() is True
        reverted = wired_model._transform.get_local_transform("/World/Cube")
        for i in range(4):
            for j in range(4):
                assert reverted[i][j] == pytest.approx(initial[i][j], abs=1e-9)

    def test_single_redo_replays_scale(self, wired_model):
        g = PrimScaleChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        g._on_changed(_fake_sender_with_moved(0.5, 0.0, 0.0))
        g._on_ended(_fake_sender_with_moved(0.5, 0.0, 0.0))
        wired_model._undo.undo()
        assert wired_model._undo.redo() is True
        replayed = wired_model._transform.get_local_transform("/World/Cube")
        assert replayed[0][0] == pytest.approx(1.5)

    def test_multi_frame_drag_yields_single_undo_entry(self, wired_model):
        g = PrimScaleChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        for i in range(1, 5):
            g._on_changed(_fake_sender_with_moved(i * 0.05, 0.0, 0.0))
        g._on_ended(_fake_sender_with_moved(0.2, 0.0, 0.0))
        assert len(wired_model._undo._undo_stack) == 1

    def test_uniform_undo_reverts_all_axes(self, wired_model):
        initial = wired_model._transform.get_local_transform("/World/Cube")
        g = PrimScaleChangedGesture(
            model=wired_model, axis=(1.0, 1.0, 1.0), uniform=True,
            projection_axis=(1.0, 0.0, 0.0),
        )
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        g._on_changed(_fake_sender_with_moved(0.5, 0.0, 0.0))
        g._on_ended(_fake_sender_with_moved(0.5, 0.0, 0.0))
        wired_model._undo.undo()
        reverted = wired_model._transform.get_local_transform("/World/Cube")
        for i in range(4):
            for j in range(4):
                assert reverted[i][j] == pytest.approx(initial[i][j], abs=1e-9)


# -- Per-axis parametrisation ---------------------------------------------


class TestPerAxisIsolation:
    """Dragging one axis must NOT affect the other two."""

    @pytest.mark.parametrize(
        "axis, row_idx",
        [
            ((1.0, 0.0, 0.0), 0),
            ((0.0, 1.0, 0.0), 1),
            ((0.0, 0.0, 1.0), 2),
        ],
    )
    def test_axis_scales_only_its_row(self, wired_model, axis, row_idx):
        g = PrimScaleChangedGesture(model=wired_model, axis=axis)
        g._on_began(_fake_sender_with_moved(0.0, 0.0, 0.0))
        # Drag +1.0 along the axis → factor = 2.0.
        g._on_changed(_fake_sender_with_moved(
            axis[0] * 1.0, axis[1] * 1.0, axis[2] * 1.0,
        ))
        assert wired_model._transform.get_local_transform("/World/Cube")[row_idx][row_idx] == pytest.approx(1.0)
        mat = wired_model._live_transforms["/World/Cube"]
        assert mat[row_idx][row_idx] == pytest.approx(2.0, abs=1e-9)
        # The other two rows stay at identity (1.0 on diagonal).
        for other in (0, 1, 2):
            if other == row_idx:
                continue
            assert mat[other][other] == pytest.approx(1.0, abs=1e-9)


# -- TransformManipulator integration -------------------------------------


class TestTransformManipulatorScaleIntegration:
    def test_on_build_populates_handles_when_selected(
        self, scene_view, wired_model
    ):
        with scene_view.scene:
            manip = TransformManipulator(model=wired_model, tool=TOOL_SCALE)
            manip.on_build()
        assert manip.scale_handles is not None
        assert len(manip.scale_handles.shafts) == 3
        assert len(manip.scale_handles.cubes) == 3
        assert manip.scale_handles.uniform_cube is not None
        assert len(manip.scale_handles.drag_gestures) == 3
        assert manip.scale_handles.uniform_drag is not None

    def test_handles_stay_none_when_no_selection(self, scene_view, empty_model):
        with scene_view.scene:
            manip = TransformManipulator(model=empty_model, tool=TOOL_SCALE)
            manip.on_build()
        assert manip.scale_handles is None

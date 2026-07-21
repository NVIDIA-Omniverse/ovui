# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the Step C.3 rotate gizmo.

Covers:

* Public constants (ring radius/thickness, intersection thickness).
* :func:`rotation_matrix_row_major` — identity at zero angle, cardinal
  rotations match the row-vector convention, orthogonality.
* Geometry emitted by :func:`build_rotate_gizmo` (3 rings, colour
  assignments, gesture attachment, per-axis ring orientation).
* :class:`PrimRotateChangedGesture` drag lifecycle — begin captures the
  baseline angle, changed pipes angle deltas through the model,
  ended closes the undo group.
* End-to-end: full ring drag rotates the selected prim around the axis,
  a single :meth:`UndoManager.undo` reverts.
* :class:`TransformManipulator` integration — selecting a prim + the
  rotate tool populates ``rotate_handles``.
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
from ovui_widgets.viewport.rotate_gizmo import (
    RING_INTERSECTION_THICKNESS,
    RING_RADIUS,
    RING_THICKNESS,
    PrimRotateChangedGesture,
    RotateGizmoHandles,
    build_rotate_gizmo,
    rotation_matrix_row_major,
)
from ovui_widgets.viewport.transform_manipulator import (
    AXIS_COLOR_X,
    AXIS_COLOR_Y,
    AXIS_COLOR_Z,
    TOOL_ROTATE,
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


def _fake_arc_sender(angle: float) -> SimpleNamespace:
    """Stand-in for ``sc.Arc``'s drag sender: exposes ``gesture_payload.angle``."""
    payload = SimpleNamespace(angle=angle)
    return SimpleNamespace(gesture_payload=payload)


# -- constants -------------------------------------------------------------


class TestConstants:
    def test_ring_radius_is_unit(self):
        # Matches translate shaft length so the ring circumscribes the arrow
        # tips — the unified Maya/Blender look called out in the C.3 plan.
        assert RING_RADIUS == pytest.approx(1.0)

    def test_ring_thickness_matches_translate_thin_look(self):
        # The "thin and elegant, not chunky" design directive bounds this.
        assert 1.0 <= RING_THICKNESS <= 3.0

    def test_intersection_thickness_is_grabbable(self):
        # Wide enough to grab, tight enough not to swallow adjacent rings.
        assert RING_INTERSECTION_THICKNESS >= RING_THICKNESS * 3.0


# -- rotation_matrix_row_major --------------------------------------------


class TestRotationMatrixRowMajor:
    def test_identity_at_zero_angle(self):
        m = rotation_matrix_row_major((1.0, 0.0, 0.0), 0.0)
        for i in range(4):
            for j in range(4):
                expected = 1.0 if i == j else 0.0
                assert m[i][j] == pytest.approx(expected, abs=1e-12)

    def test_z_axis_90_takes_x_to_y(self):
        # Row-vector convention: (1, 0, 0) @ R should land at (0, 1, 0).
        m = rotation_matrix_row_major((0.0, 0.0, 1.0), math.pi / 2)
        x_new = (
            1.0 * m[0][0] + 0.0 * m[1][0] + 0.0 * m[2][0],
            1.0 * m[0][1] + 0.0 * m[1][1] + 0.0 * m[2][1],
            1.0 * m[0][2] + 0.0 * m[1][2] + 0.0 * m[2][2],
        )
        assert x_new[0] == pytest.approx(0.0, abs=1e-12)
        assert x_new[1] == pytest.approx(1.0, abs=1e-12)
        assert x_new[2] == pytest.approx(0.0, abs=1e-12)

    def test_x_axis_90_takes_y_to_z(self):
        m = rotation_matrix_row_major((1.0, 0.0, 0.0), math.pi / 2)
        y_new = (
            0.0 * m[0][0] + 1.0 * m[1][0] + 0.0 * m[2][0],
            0.0 * m[0][1] + 1.0 * m[1][1] + 0.0 * m[2][1],
            0.0 * m[0][2] + 1.0 * m[1][2] + 0.0 * m[2][2],
        )
        assert y_new[0] == pytest.approx(0.0, abs=1e-12)
        assert y_new[1] == pytest.approx(0.0, abs=1e-12)
        assert y_new[2] == pytest.approx(1.0, abs=1e-12)

    def test_y_axis_90_takes_z_to_x(self):
        m = rotation_matrix_row_major((0.0, 1.0, 0.0), math.pi / 2)
        z_new = (
            0.0 * m[0][0] + 0.0 * m[1][0] + 1.0 * m[2][0],
            0.0 * m[0][1] + 0.0 * m[1][1] + 1.0 * m[2][1],
            0.0 * m[0][2] + 0.0 * m[1][2] + 1.0 * m[2][2],
        )
        assert z_new[0] == pytest.approx(1.0, abs=1e-12)
        assert z_new[1] == pytest.approx(0.0, abs=1e-12)
        assert z_new[2] == pytest.approx(0.0, abs=1e-12)

    def test_axis_is_fixed_point(self):
        # A pure rotation leaves points on its axis unchanged.
        m = rotation_matrix_row_major((0.0, 0.0, 1.0), 1.234)
        z_pt = (
            0.0 * m[0][0] + 0.0 * m[1][0] + 1.0 * m[2][0],
            0.0 * m[0][1] + 0.0 * m[1][1] + 1.0 * m[2][1],
            0.0 * m[0][2] + 0.0 * m[1][2] + 1.0 * m[2][2],
        )
        assert z_pt[0] == pytest.approx(0.0, abs=1e-12)
        assert z_pt[1] == pytest.approx(0.0, abs=1e-12)
        assert z_pt[2] == pytest.approx(1.0, abs=1e-12)

    def test_row_orthonormal(self):
        # Rotation matrices are orthonormal — each row norm == 1.
        m = rotation_matrix_row_major((1.0, 0.0, 0.0), 0.7)
        for i in range(3):
            norm = sum(m[i][j] ** 2 for j in range(3))
            assert norm == pytest.approx(1.0, abs=1e-12)


# -- geometry builder -----------------------------------------------------


class TestBuildRotateGizmo:
    def test_returns_rotate_gizmo_handles(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_rotate_gizmo(wired_model)
        assert isinstance(handles, RotateGizmoHandles)

    def test_produces_three_rings(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_rotate_gizmo(wired_model)
        assert len(handles.rings) == 3

    def test_produces_three_drag_gestures(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_rotate_gizmo(wired_model)
        assert len(handles.drag_gestures) == 3
        for g in handles.drag_gestures:
            assert isinstance(g, PrimRotateChangedGesture)

    def test_produces_three_hover_gestures(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_rotate_gizmo(wired_model)
        assert len(handles.hover_gestures) == 3
        for h in handles.hover_gestures:
            assert isinstance(h, HighlightGesture)

    def test_axis_vectors_are_unit(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_rotate_gizmo(wired_model)
        assert handles.drag_gestures[0].axis == (1.0, 0.0, 0.0)
        assert handles.drag_gestures[1].axis == (0.0, 1.0, 0.0)
        assert handles.drag_gestures[2].axis == (0.0, 0.0, 1.0)

    def test_gesture_for_axis_lookup(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_rotate_gizmo(wired_model)
        assert handles.gesture_for_axis("x").axis == (1.0, 0.0, 0.0)
        assert handles.gesture_for_axis("Y").axis == (0.0, 1.0, 0.0)
        assert handles.gesture_for_axis("z").axis == (0.0, 0.0, 1.0)

    def test_highlight_colors_per_axis(self, scene_view, wired_model):
        # Each hover binds the matching (base, highlight) pair — a copy-paste
        # bug here would flash the wrong ring on mouseover.
        with scene_view.scene:
            handles = build_rotate_gizmo(wired_model)
        pairs = [
            (handles.hover_gestures[0], AXIS_COLOR_X, HIGHLIGHT_COLOR_X),
            (handles.hover_gestures[1], AXIS_COLOR_Y, HIGHLIGHT_COLOR_Y),
            (handles.hover_gestures[2], AXIS_COLOR_Z, HIGHLIGHT_COLOR_Z),
        ]
        for hover, base, hl in pairs:
            assert hover._base_color == base
            assert hover._highlight_color == hl

    def test_hover_attached_to_ring(self, scene_view, wired_model):
        # The hover gesture must swap the ring's colour, not something else.
        with scene_view.scene:
            handles = build_rotate_gizmo(wired_model)
        for ring, hover in zip(handles.rings, handles.hover_gestures):
            assert ring in hover._shapes


# -- PrimRotateChangedGesture construction --------------------------------


class TestPrimRotateChangedGestureConstruction:
    def test_rejects_zero_axis(self):
        with pytest.raises(ValueError):
            PrimRotateChangedGesture(model=MagicMock(), axis=(0.0, 0.0, 0.0))

    def test_normalises_axis(self):
        g = PrimRotateChangedGesture(model=MagicMock(), axis=(0.0, 3.0, 0.0))
        assert g.axis == (0.0, 1.0, 0.0)

    def test_stores_axis(self):
        g = PrimRotateChangedGesture(model=MagicMock(), axis=(0.0, 0.0, 1.0))
        assert g.axis == (0.0, 0.0, 1.0)

    def test_initial_state_inactive(self):
        g = PrimRotateChangedGesture(model=MagicMock(), axis=(1.0, 0.0, 0.0))
        assert g.is_active is False
        assert g.accumulated_angle == 0.0


# -- PrimRotateChangedGesture lifecycle -----------------------------------


class TestPrimRotateChangedGestureLifecycle:
    def test_began_without_selection_stays_inert(self, empty_model):
        g = PrimRotateChangedGesture(model=empty_model, axis=(0.0, 0.0, 1.0))
        g._on_began(_fake_arc_sender(0.0))
        assert g.is_active is False

    def test_began_with_selection_calls_drag_start(self, wired_model):
        g = PrimRotateChangedGesture(model=wired_model, axis=(0.0, 0.0, 1.0))
        g._on_began(_fake_arc_sender(0.5))
        assert g.is_active is True
        wired_model._stage.begin_undo_group.assert_called_once_with("Rotate Prims")

    def test_began_with_broken_adapter_goes_inert(self):
        model = PrimTransformModel()
        model._selected_paths = ["/World/Cube"]  # but no adapters → drag_start raises
        g = PrimRotateChangedGesture(model=model, axis=(0.0, 0.0, 1.0))
        g._on_began(_fake_arc_sender(0.0))
        assert g.is_active is False

    def test_changed_tracks_angle_delta(self, wired_model):
        g = PrimRotateChangedGesture(model=wired_model, axis=(0.0, 0.0, 1.0))
        g._on_began(_fake_arc_sender(math.pi / 4))
        g._on_changed(_fake_arc_sender(math.pi / 2))
        assert g.accumulated_angle == pytest.approx(math.pi / 4)

    def test_changed_overwrites_previous_delta(self, wired_model):
        # Unlike translate, rotate deltas are absolute-vs-start: the previous
        # frame's delta is replaced, not accumulated.
        g = PrimRotateChangedGesture(model=wired_model, axis=(0.0, 0.0, 1.0))
        g._on_began(_fake_arc_sender(0.0))
        g._on_changed(_fake_arc_sender(1.0))
        g._on_changed(_fake_arc_sender(2.0))
        assert g.accumulated_angle == pytest.approx(2.0)

    def test_changed_while_inactive_is_noop(self, wired_model):
        g = PrimRotateChangedGesture(model=wired_model, axis=(0.0, 0.0, 1.0))
        g._on_changed(_fake_arc_sender(1.0))
        assert g.accumulated_angle == 0.0

    def test_changed_records_rotation_preview(self, wired_model):
        # A 90° rotation about Z should send the initial local X axis to +Y.
        # With identity upper-3×3 in the fixture, that's m[0][0]=0, m[0][1]=1.
        g = PrimRotateChangedGesture(model=wired_model, axis=(0.0, 0.0, 1.0))
        g._on_began(_fake_arc_sender(0.0))
        g._on_changed(_fake_arc_sender(math.pi / 2))
        assert wired_model._transform.get_local_transform("/World/Cube")[0][0] == pytest.approx(1.0)
        mat = wired_model._live_transforms["/World/Cube"]
        assert mat[0][0] == pytest.approx(0.0, abs=1e-9)
        assert mat[0][1] == pytest.approx(1.0, abs=1e-9)
        assert mat[1][0] == pytest.approx(-1.0, abs=1e-9)
        assert mat[1][1] == pytest.approx(0.0, abs=1e-9)
        # Translation row preserved — the rotation is "in place".
        assert mat[3][0] == pytest.approx(2.0)
        assert mat[3][1] == pytest.approx(3.0)
        assert mat[3][2] == pytest.approx(4.0)

    def test_ended_calls_drag_ended(self, wired_model):
        g = PrimRotateChangedGesture(model=wired_model, axis=(0.0, 0.0, 1.0))
        g._on_began(_fake_arc_sender(0.0))
        g._on_ended(_fake_arc_sender(0.0))
        wired_model._stage.end_undo_group.assert_called_once()
        assert g.is_active is False

    def test_ended_while_inactive_is_noop(self, wired_model):
        g = PrimRotateChangedGesture(model=wired_model, axis=(0.0, 0.0, 1.0))
        g._on_ended(_fake_arc_sender(0.0))
        wired_model._stage.end_undo_group.assert_not_called()


# -- Undo integration -----------------------------------------------------


class TestPrimRotateChangedGestureUndo:
    def test_single_undo_reverts_rotation(self, wired_model):
        initial = wired_model._transform.get_local_transform("/World/Cube")
        g = PrimRotateChangedGesture(model=wired_model, axis=(0.0, 0.0, 1.0))
        g._on_began(_fake_arc_sender(0.0))
        g._on_changed(_fake_arc_sender(math.pi / 2))
        g._on_ended(_fake_arc_sender(math.pi / 2))
        rotated = wired_model._transform.get_local_transform("/World/Cube")
        assert rotated[0][1] == pytest.approx(1.0, abs=1e-9)
        assert wired_model._undo.undo() is True
        reverted = wired_model._transform.get_local_transform("/World/Cube")
        for i in range(4):
            for j in range(4):
                assert reverted[i][j] == pytest.approx(initial[i][j], abs=1e-9)

    def test_single_redo_replays_rotation(self, wired_model):
        g = PrimRotateChangedGesture(model=wired_model, axis=(0.0, 0.0, 1.0))
        g._on_began(_fake_arc_sender(0.0))
        g._on_changed(_fake_arc_sender(math.pi / 2))
        g._on_ended(_fake_arc_sender(math.pi / 2))
        wired_model._undo.undo()
        assert wired_model._undo.redo() is True
        replayed = wired_model._transform.get_local_transform("/World/Cube")
        assert replayed[0][1] == pytest.approx(1.0, abs=1e-9)

    def test_undo_stack_has_single_entry_for_multi_frame_drag(self, wired_model):
        g = PrimRotateChangedGesture(model=wired_model, axis=(0.0, 0.0, 1.0))
        g._on_began(_fake_arc_sender(0.0))
        for i in range(1, 5):
            g._on_changed(_fake_arc_sender(i * 0.1))
        g._on_ended(_fake_arc_sender(0.4))
        assert len(wired_model._undo._undo_stack) == 1


# -- Per-axis parametrisation ---------------------------------------------


class TestPrimRotateChangedGesturePerAxis:
    """Confirm each ring rotates around the correct world axis."""

    @pytest.mark.parametrize(
        "axis, col_before_rot",
        [
            ((1.0, 0.0, 0.0), 1),  # X-ring: (0,1,0) — the old +Y local axis — moves
            ((0.0, 1.0, 0.0), 2),  # Y-ring: (0,0,1) — the old +Z local axis — moves
            ((0.0, 0.0, 1.0), 0),  # Z-ring: (1,0,0) — the old +X local axis — moves
        ],
    )
    def test_rotation_around_axis_moves_other_axes(
        self, wired_model, axis, col_before_rot
    ):
        g = PrimRotateChangedGesture(model=wired_model, axis=axis)
        g._on_began(_fake_arc_sender(0.0))
        g._on_changed(_fake_arc_sender(math.pi / 2))
        assert wired_model._transform.get_local_transform("/World/Cube")[0][0] == pytest.approx(1.0)
        mat = wired_model._live_transforms["/World/Cube"]
        # The column corresponding to the axis-aligned local vector that
        # SHOULD move must no longer be purely along its original direction —
        # a 90° rotation around the chosen axis rotates the other two local
        # axes away from identity.
        moved = mat[col_before_rot]
        # The row's dominant component should no longer be along col_before_rot.
        assert abs(moved[col_before_rot]) < 0.01


# -- TransformManipulator integration -------------------------------------


class TestTransformManipulatorRotateIntegration:
    def test_on_build_populates_handles_when_selected(self, scene_view, wired_model):
        with scene_view.scene:
            manip = TransformManipulator(model=wired_model, tool=TOOL_ROTATE)
            manip.on_build()
        assert manip.rotate_handles is not None
        assert len(manip.rotate_handles.rings) == 3
        assert len(manip.rotate_handles.drag_gestures) == 3

    def test_handles_stay_none_when_no_selection(self, scene_view, empty_model):
        with scene_view.scene:
            manip = TransformManipulator(model=empty_model, tool=TOOL_ROTATE)
            manip.on_build()
        assert manip.rotate_handles is None

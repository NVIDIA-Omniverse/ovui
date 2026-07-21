# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the Step C.2 translate gizmo.

Covers:

* Public constants (highlight colours differ from base, shaft length).
* Math helpers (``_project_onto_axis``, ``_axis_delta_matrix``).
* Geometry emitted by :func:`build_translate_gizmo` (3 shafts, 3 caps,
  colour assignments, gesture attachment).
* :class:`PrimTranslateChangedGesture` drag lifecycle — begin starts drag on
  model, changed projects onto axis and accumulates, ended pushes undo.
* :class:`HighlightGesture` swaps shape colour on hover enter/leave.
* End-to-end: a full drag on the X arrow moves the selected prim along X
  and is undoable with a single ``UndoManager.undo`` call.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from omni.ui_scene import scene as sc

from ovui_widgets.common.testing.mock_transform import MockTransformAdapter
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.viewport.prim_transform_model import PrimTransformModel
from ovui_widgets.viewport.transform_manipulator import (
    AXIS_COLOR_X,
    AXIS_COLOR_Y,
    AXIS_COLOR_Z,
    TOOL_TRANSLATE,
    TransformManipulator,
)
from ovui_widgets.viewport.translate_gizmo import (
    CONE_TIP_LENGTH,
    CONE_TIP_RADIUS,
    CONE_TIP_SEGMENTS,
    HIGHLIGHT_COLOR_X,
    HIGHLIGHT_COLOR_Y,
    HIGHLIGHT_COLOR_Z,
    SHAFT_LENGTH,
    HighlightGesture,
    PrimTranslateChangedGesture,
    TranslateGizmoHandles,
    _axis_delta_matrix,
    _cone_positions,
    _project_onto_axis,
    build_translate_gizmo,
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
            [0.0, 0.0, 0.0, 1.0],
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


# -- math helpers ---------------------------------------------------------


class TestProjectOntoAxis:
    def test_pure_x_projects_to_x(self):
        assert _project_onto_axis(3.0, 0.0, 0.0, (1.0, 0.0, 0.0)) == (3.0, 0.0, 0.0)

    def test_off_axis_drops_to_zero(self):
        # Pure Y motion projected onto X axis → zero.
        assert _project_onto_axis(0.0, 5.0, 0.0, (1.0, 0.0, 0.0)) == (0.0, 0.0, 0.0)

    def test_mixed_projects_to_axis_component(self):
        result = _project_onto_axis(2.0, 4.0, 0.0, (1.0, 0.0, 0.0))
        assert result == (2.0, 0.0, 0.0)

    def test_projection_onto_y(self):
        result = _project_onto_axis(1.0, 7.0, 3.0, (0.0, 1.0, 0.0))
        assert result == (0.0, 7.0, 0.0)

    def test_projection_onto_z(self):
        result = _project_onto_axis(1.0, 2.0, 3.0, (0.0, 0.0, 1.0))
        assert result == (0.0, 0.0, 3.0)

    def test_negative_delta(self):
        result = _project_onto_axis(-4.0, 0.0, 0.0, (1.0, 0.0, 0.0))
        assert result == (-4.0, 0.0, 0.0)


class TestAxisDeltaMatrix:
    def test_returns_4x4(self):
        m = _axis_delta_matrix(1.0, 2.0, 3.0)
        assert len(m) == 4
        assert all(len(row) == 4 for row in m)

    def test_translation_in_last_row(self):
        m = _axis_delta_matrix(5.0, 7.0, 11.0)
        assert m[3][0] == pytest.approx(5.0)
        assert m[3][1] == pytest.approx(7.0)
        assert m[3][2] == pytest.approx(11.0)
        assert m[3][3] == pytest.approx(1.0)

    def test_identity_when_zero(self):
        m = _axis_delta_matrix(0.0, 0.0, 0.0)
        for i in range(4):
            for j in range(4):
                expected = 1.0 if i == j else 0.0
                assert m[i][j] == pytest.approx(expected)


# -- geometry builder ------------------------------------------------------


class TestBuildTranslateGizmo:
    def test_produces_three_shafts(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_translate_gizmo(wired_model)
        assert len(handles.shafts) == 3

    def test_produces_three_caps(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_translate_gizmo(wired_model)
        assert len(handles.caps) == 3
        assert all(isinstance(cap, sc.PolygonMesh) for cap in handles.caps)

    def test_caps_provide_color_for_every_face_vertex(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_translate_gizmo(wired_model)
        for cap in handles.caps:
            assert len(cap.colors) == len(cap.vertex_indices)

    def test_cone_positions_have_pointed_tips(self):
        positions = _cone_positions((1.0, 0.0, 0.0))
        assert len(positions) == CONE_TIP_SEGMENTS + 1
        assert positions[0] == pytest.approx((SHAFT_LENGTH + CONE_TIP_LENGTH, 0.0, 0.0))
        for base_vertex in positions[1:]:
            assert base_vertex[0] == pytest.approx(SHAFT_LENGTH)
            radial = (base_vertex[1] ** 2 + base_vertex[2] ** 2) ** 0.5
            assert radial == pytest.approx(CONE_TIP_RADIUS)

    def test_cone_positions_align_to_each_axis(self):
        for axis, component in [
            ((1.0, 0.0, 0.0), 0),
            ((0.0, 1.0, 0.0), 1),
            ((0.0, 0.0, 1.0), 2),
        ]:
            positions = _cone_positions(axis)
            assert positions[0][component] == pytest.approx(SHAFT_LENGTH + CONE_TIP_LENGTH)
            for base_vertex in positions[1:]:
                assert base_vertex[component] == pytest.approx(SHAFT_LENGTH)

    def test_produces_three_drag_gestures(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_translate_gizmo(wired_model)
        assert len(handles.drag_gestures) == 3
        for g in handles.drag_gestures:
            assert isinstance(g, PrimTranslateChangedGesture)

    def test_produces_three_hover_gestures(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_translate_gizmo(wired_model)
        assert len(handles.hover_gestures) == 3
        for h in handles.hover_gestures:
            assert isinstance(h, HighlightGesture)

    def test_axis_vectors_are_unit(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_translate_gizmo(wired_model)
        assert handles.drag_gestures[0].axis == (1.0, 0.0, 0.0)
        assert handles.drag_gestures[1].axis == (0.0, 1.0, 0.0)
        assert handles.drag_gestures[2].axis == (0.0, 0.0, 1.0)

    def test_gesture_for_axis_lookup(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_translate_gizmo(wired_model)
        assert handles.gesture_for_axis("x").axis == (1.0, 0.0, 0.0)
        assert handles.gesture_for_axis("Y").axis == (0.0, 1.0, 0.0)
        assert handles.gesture_for_axis("z").axis == (0.0, 0.0, 1.0)

    def test_returns_translate_gizmo_handles(self, scene_view, wired_model):
        with scene_view.scene:
            handles = build_translate_gizmo(wired_model)
        assert isinstance(handles, TranslateGizmoHandles)


# -- PrimTranslateChangedGesture ------------------------------------------


def _fake_drag_sender(move_x: float, move_y: float, move_z: float) -> SimpleNamespace:
    """Return a stand-in ``sender`` exposing ``gesture_payload.moved``."""
    moved = SimpleNamespace(x=move_x, y=move_y, z=move_z)
    payload = SimpleNamespace(moved=moved)
    return SimpleNamespace(gesture_payload=payload)


class TestPrimTranslateChangedGestureConstruction:
    def test_rejects_zero_axis(self):
        with pytest.raises(ValueError):
            PrimTranslateChangedGesture(model=MagicMock(), axis=(0.0, 0.0, 0.0))

    def test_normalises_axis(self):
        g = PrimTranslateChangedGesture(model=MagicMock(), axis=(2.0, 0.0, 0.0))
        assert g.axis == (1.0, 0.0, 0.0)

    def test_stores_axis(self):
        g = PrimTranslateChangedGesture(model=MagicMock(), axis=(0.0, 1.0, 0.0))
        assert g.axis == (0.0, 1.0, 0.0)

    def test_initial_state_inactive(self):
        g = PrimTranslateChangedGesture(model=MagicMock(), axis=(1.0, 0.0, 0.0))
        assert g.is_active is False
        assert g.accumulated_delta == (0.0, 0.0, 0.0)


class TestPrimTranslateChangedGestureLifecycle:
    def test_began_without_selection_stays_inert(self, empty_model):
        g = PrimTranslateChangedGesture(model=empty_model, axis=(1.0, 0.0, 0.0))
        g._on_began()
        assert g.is_active is False

    def test_began_with_selection_calls_drag_start(self, wired_model):
        g = PrimTranslateChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began()
        assert g.is_active is True
        wired_model._stage.begin_undo_group.assert_called_once_with("Move Prims")

    def test_began_with_broken_adapter_goes_inert(self):
        model = PrimTransformModel()
        model._selected_paths = ["/World/Cube"]  # but no adapters → drag_start raises
        g = PrimTranslateChangedGesture(model=model, axis=(1.0, 0.0, 0.0))
        g._on_began()
        assert g.is_active is False

    def test_changed_projects_onto_axis(self, wired_model):
        g = PrimTranslateChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began()
        # Mixed delta — only the X component should accumulate.
        sender = _fake_drag_sender(2.5, 4.0, 1.0)
        g._on_changed(sender)
        assert g.accumulated_delta == pytest.approx((2.5, 0.0, 0.0))

    def test_changed_accumulates_across_frames(self, wired_model):
        g = PrimTranslateChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began()
        g._on_changed(_fake_drag_sender(1.0, 0.0, 0.0))
        g._on_changed(_fake_drag_sender(2.0, 0.0, 0.0))
        g._on_changed(_fake_drag_sender(3.0, 0.0, 0.0))
        assert g.accumulated_delta == pytest.approx((6.0, 0.0, 0.0))

    def test_changed_while_inactive_is_noop(self, wired_model):
        g = PrimTranslateChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        # Never called ``_on_began`` — gesture stays inert.
        g._on_changed(_fake_drag_sender(5.0, 0.0, 0.0))
        assert g.accumulated_delta == (0.0, 0.0, 0.0)

    def test_changed_records_live_delta_without_transform_write(self, wired_model):
        g = PrimTranslateChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began()
        g._on_changed(_fake_drag_sender(3.0, 0.0, 0.0))
        mat = wired_model._transform.get_local_transform("/World/Cube")
        assert mat[3][0] == pytest.approx(0.0)
        live = wired_model._live_transforms["/World/Cube"]
        assert live[3][0] == pytest.approx(3.0)

    def test_ended_calls_drag_ended(self, wired_model):
        g = PrimTranslateChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began()
        g._on_ended()
        wired_model._stage.end_undo_group.assert_called_once()
        assert g.is_active is False

    def test_ended_while_inactive_is_noop(self, wired_model):
        g = PrimTranslateChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        # Never began — ending should not crash or call the stage.
        g._on_ended()
        wired_model._stage.end_undo_group.assert_not_called()

    def test_ended_sets_drag_ended_latch(self, wired_model):
        """Bug 13 — ``_on_ended`` latches so the pick gesture's guard
        still fires even when it runs after the gizmo's ``_on_ended``.
        """
        g = PrimTranslateChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        assert g._drag_ended_this_cycle is False
        g._on_began()
        assert g._drag_ended_this_cycle is False
        g._on_ended()
        assert g._drag_ended_this_cycle is True

    def test_began_clears_drag_ended_latch(self, wired_model):
        """A fresh drag clears the latch from the previous cycle."""
        g = PrimTranslateChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began()
        g._on_ended()
        assert g._drag_ended_this_cycle is True
        g._on_began()
        assert g._drag_ended_this_cycle is False

    def test_inactive_ended_does_not_set_latch(self, wired_model):
        """An ``_on_ended`` on a never-begun gesture shouldn't latch."""
        g = PrimTranslateChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_ended()
        assert g._drag_ended_this_cycle is False


class TestPrimTranslateChangedGestureUndo:
    def test_single_undo_reverts_drag(self, wired_model):
        # Start at the identity translation.
        initial = wired_model._transform.get_local_transform("/World/Cube")
        assert initial[3][0] == pytest.approx(0.0)
        g = PrimTranslateChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began()
        g._on_changed(_fake_drag_sender(5.0, 0.0, 0.0))
        g._on_ended()
        moved = wired_model._transform.get_local_transform("/World/Cube")
        assert moved[3][0] == pytest.approx(5.0)
        # One Ctrl+Z reverts the entire drag.
        assert wired_model._undo.undo() is True
        reverted = wired_model._transform.get_local_transform("/World/Cube")
        assert reverted[3][0] == pytest.approx(0.0)

    def test_single_redo_replays_drag(self, wired_model):
        g = PrimTranslateChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began()
        g._on_changed(_fake_drag_sender(5.0, 0.0, 0.0))
        g._on_ended()
        wired_model._undo.undo()
        assert wired_model._undo.redo() is True
        replayed = wired_model._transform.get_local_transform("/World/Cube")
        assert replayed[3][0] == pytest.approx(5.0)

    def test_undo_stack_has_single_entry(self, wired_model):
        g = PrimTranslateChangedGesture(model=wired_model, axis=(1.0, 0.0, 0.0))
        g._on_began()
        g._on_changed(_fake_drag_sender(1.0, 0.0, 0.0))
        g._on_changed(_fake_drag_sender(2.0, 0.0, 0.0))
        g._on_changed(_fake_drag_sender(3.0, 0.0, 0.0))
        g._on_ended()
        # Many changed frames but only one top-level undo entry.
        assert len(wired_model._undo._undo_stack) == 1


class TestPrimTranslateChangedGesturePerAxis:
    """Parameterised end-to-end checks for X / Y / Z."""

    @pytest.mark.parametrize(
        "axis, delta, col",
        [
            ((1.0, 0.0, 0.0), (4.0, 0.0, 0.0), 0),
            ((0.0, 1.0, 0.0), (0.0, 2.5, 0.0), 1),
            ((0.0, 0.0, 1.0), (0.0, 0.0, -1.5), 2),
        ],
    )
    def test_drag_moves_prim_on_axis(self, wired_model, axis, delta, col):
        g = PrimTranslateChangedGesture(model=wired_model, axis=axis)
        g._on_began()
        g._on_changed(_fake_drag_sender(*delta))
        g._on_ended()
        mat = wired_model._transform.get_local_transform("/World/Cube")
        assert mat[3][col] == pytest.approx(delta[col])


# -- HighlightGesture ------------------------------------------------------


class TestHighlightGesture:
    def _make_shape_proxy(self, initial_color: int = 0):
        """A minimal object that mimics ``sc.Line``'s colour assignment."""
        return SimpleNamespace(color=initial_color)

    def test_initial_state_not_hovered(self):
        shape = self._make_shape_proxy()
        h = HighlightGesture([shape], base_color=0x1111, highlight_color=0x2222)
        assert h.is_hovered is False

    def test_began_sets_highlight_color(self):
        a = self._make_shape_proxy(0x1111)
        b = self._make_shape_proxy(0x1111)
        h = HighlightGesture([a, b], base_color=0x1111, highlight_color=0x2222)
        h._on_began()
        assert h.is_hovered is True
        assert a.color == 0x2222
        assert b.color == 0x2222

    def test_ended_restores_base_color(self):
        shape = self._make_shape_proxy(0x1111)
        h = HighlightGesture([shape], base_color=0x1111, highlight_color=0x2222)
        h._on_began()
        h._on_ended()
        assert h.is_hovered is False
        assert shape.color == 0x1111

    def test_fires_state_change_callback(self):
        shape = self._make_shape_proxy()
        states = []
        h = HighlightGesture(
            [shape], base_color=0, highlight_color=1,
            on_state_change=lambda s: states.append(s),
        )
        h._on_began()
        h._on_ended()
        assert states == [True, False]

    def test_typeerror_shape_does_not_crash(self):
        """A shape whose setter raises ``TypeError`` shouldn't break hover."""
        class BadShape:
            @property
            def color(self):
                return 0

            @color.setter
            def color(self, value):
                raise TypeError("bad color value")

        h = HighlightGesture([BadShape()], base_color=0, highlight_color=1)
        h._on_began()  # no exception
        h._on_ended()  # no exception

    def test_polygon_mesh_shape_updates_vertex_colors(self):
        """Mesh-only shapes use per-vertex colors instead of a scalar color property."""
        class MeshOnlyShape:
            positions = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]

            def __init__(self):
                self.colors = [0x1111, 0x1111]

            @property
            def color(self):
                raise AttributeError("mesh has no scalar color")

            @color.setter
            def color(self, value):
                raise AttributeError("mesh has no scalar color")

        mesh = MeshOnlyShape()
        h = HighlightGesture([mesh], base_color=0x1111, highlight_color=0x2222)
        h._on_began()
        assert mesh.colors == [0x2222, 0x2222]
        h._on_ended()
        assert mesh.colors == [0x1111, 0x1111]

    def test_polygon_mesh_shape_prefers_face_vertex_color_count(self):
        """Real ``sc.PolygonMesh`` colors are consumed per face vertex."""
        class MeshOnlyShape:
            positions = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
            vertex_indices = [0, 1, 0, 1, 0, 1]

            def __init__(self):
                self.colors = [0x1111] * len(self.vertex_indices)

            @property
            def color(self):
                raise AttributeError("mesh has no scalar color")

            @color.setter
            def color(self, value):
                raise AttributeError("mesh has no scalar color")

        mesh = MeshOnlyShape()
        h = HighlightGesture([mesh], base_color=0x1111, highlight_color=0x2222)
        h._on_began()
        assert mesh.colors == [0x2222] * len(mesh.vertex_indices)
        h._on_ended()
        assert mesh.colors == [0x1111] * len(mesh.vertex_indices)

    def test_add_shape_extends_coverage(self):
        a = SimpleNamespace(color=0x1111)
        b = SimpleNamespace(color=0x1111)
        h = HighlightGesture([a], base_color=0x1111, highlight_color=0x2222)
        h.add_shape(b)
        h._on_began()
        assert a.color == 0x2222
        assert b.color == 0x2222


# -- TransformManipulator integration -------------------------------------


class TestTransformManipulatorTranslateIntegration:
    def test_on_build_populates_handles_when_selected(self, scene_view, wired_model):
        with scene_view.scene:
            manip = TransformManipulator(
                model=wired_model, tool=TOOL_TRANSLATE,
            )
            manip.on_build()
        assert manip.translate_handles is not None
        assert len(manip.translate_handles.drag_gestures) == 3

    def test_handles_empty_when_no_selection(self, scene_view, empty_model):
        with scene_view.scene:
            manip = TransformManipulator(
                model=empty_model, tool=TOOL_TRANSLATE,
            )
            manip.on_build()
        # ``on_build`` is a no-op with no selection, so handles stay None.
        assert manip.translate_handles is None

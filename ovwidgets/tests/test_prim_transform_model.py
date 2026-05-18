# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for PrimTransformModel and _apply_delta."""

import math
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from ovwidgets.common.testing.mock_transform import MockTransformAdapter
from ovwidgets.common.undo import UndoManager
from ovwidgets.viewport.prim_transform_model import (
    PrimTransformModel,
    _apply_delta,
    _apply_scale,
)

_IDENTITY = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]

_TRANSLATION = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [1.0, 2.0, 3.0, 1.0],
]


def _make_mock_stage():
    stage = MagicMock()
    stage.suppress_change_notifications.side_effect = lambda: _cm()
    return stage


@contextmanager
def _cm():
    yield


@pytest.fixture
def transform():
    adapter = MockTransformAdapter(blocked={"/Locked"})
    mat = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [5.0, 0.0, 0.0, 1.0],
    ]
    adapter.set_local_transform("/World/A", mat)
    adapter.set_local_transform("/World/B", [row[:] for row in _IDENTITY])
    return adapter


@pytest.fixture
def model(transform):
    stage = _make_mock_stage()
    undo = UndoManager()
    return PrimTransformModel(transform, stage, undo)


class TestSetSelection:
    def test_filters_untransformable(self, model):
        model.set_selection(["/World/A", "/Locked"])
        assert model._selected_paths == ["/World/A"]

    def test_keeps_transformable(self, model):
        model.set_selection(["/World/A", "/World/B"])
        assert set(model._selected_paths) == {"/World/A", "/World/B"}

    def test_empty_selection(self, model):
        model.set_selection([])
        assert model._selected_paths == []

    def test_transform_space_exposes_current_mode(self, model):
        assert model.transform_space == "world"

    def test_all_locked(self, model):
        model.set_selection(["/Locked"])
        assert model._selected_paths == []


class TestOnDragStart:
    def test_captures_initial_transforms(self, model, transform):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        assert "/World/A" in model._initial_transforms
        assert model._initial_transforms["/World/A"][3][0] == pytest.approx(5.0)

    def test_calls_begin_undo_group(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model._stage.begin_undo_group.assert_called_once_with("Move Prims")

    def test_captures_all_selected(self, model):
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()
        assert "/World/A" in model._initial_transforms
        assert "/World/B" in model._initial_transforms


class TestOnDragMoved:
    def test_applies_delta_to_initial(self, model, transform):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        delta = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [10.0, 0.0, 0.0, 1.0],
        ]
        model.on_drag_moved(delta)
        result = transform.get_local_transform("/World/A")
        assert result[3][0] == pytest.approx(15.0)

    def test_uses_suppress_notifications(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved([row[:] for row in _IDENTITY])
        model._stage.suppress_change_notifications.assert_called()

    def test_notifies_live_transform_before_drag_end(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        delta = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [10.0, 0.0, 0.0, 1.0],
        ]
        model.on_drag_moved(delta)
        model._stage.notify_transform_changed.assert_called_once_with(
            ["/World/A"],
            source="viewport-manipulator-live",
        )

    def test_repeated_move_uses_initial(self, model, transform):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        delta1 = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [1.0, 0.0, 0.0, 1.0],
        ]
        delta2 = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [2.0, 0.0, 0.0, 1.0],
        ]
        model.on_drag_moved(delta1)
        model.on_drag_moved(delta2)
        result = transform.get_local_transform("/World/A")
        assert result[3][0] == pytest.approx(7.0)


class TestOnDragEnded:
    def test_clears_initial_transforms(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        assert model._initial_transforms
        model.on_drag_ended()
        assert model._initial_transforms == {}

    def test_calls_end_undo_group(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_ended()
        model._stage.end_undo_group.assert_called_once()

    def test_notifies_final_transform_after_drag_end(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        delta = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [10.0, 0.0, 0.0, 1.0],
        ]
        model.on_drag_moved(delta)
        model._stage.notify_transform_changed.reset_mock()

        model.on_drag_ended()

        model._stage.notify_transform_changed.assert_called_once_with(
            ["/World/A"],
            source="viewport-manipulator",
        )

    def test_skips_final_notify_when_drag_does_not_change_transform(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_ended()
        model._stage.notify_transform_changed.assert_not_called()


class TestOnDragStartLabel:
    def test_default_label_is_move(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model._stage.begin_undo_group.assert_called_once_with("Move Prims")

    def test_custom_label_forwarded(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start(label="Rotate Prims")
        model._stage.begin_undo_group.assert_called_once_with("Rotate Prims")

    def test_label_is_persisted_for_ended(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start(label="Rotate Prims")
        model.on_drag_ended()
        # The UndoGroup label should match what was begun.
        undo_group = model._undo._undo_stack[-1]
        assert undo_group.label == "Rotate Prims"


class TestOnDragRotated:
    def test_rotates_upper_3x3_preserving_translation(self, model, transform):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_rotated((0.0, 0.0, 1.0), math.pi / 2)
        mat = transform.get_local_transform("/World/A")
        # 90° around Z with identity upper-3×3: +X row becomes (0, 1, 0).
        assert mat[0][0] == pytest.approx(0.0, abs=1e-9)
        assert mat[0][1] == pytest.approx(1.0, abs=1e-9)
        assert mat[1][0] == pytest.approx(-1.0, abs=1e-9)
        assert mat[1][1] == pytest.approx(0.0, abs=1e-9)
        # Translation row stays put — rotation "in place".
        assert mat[3][0] == pytest.approx(5.0)
        assert mat[3][1] == pytest.approx(0.0)
        assert mat[3][2] == pytest.approx(0.0)

    def test_uses_suppress_notifications(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_rotated((0.0, 0.0, 1.0), 0.5)
        model._stage.suppress_change_notifications.assert_called()

    def test_notifies_live_transform_before_drag_end(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_rotated((0.0, 0.0, 1.0), 0.5)
        model._stage.notify_transform_changed.assert_called_once_with(
            ["/World/A"],
            source="viewport-manipulator-live",
        )

    def test_rotation_rebases_on_initial_not_current(self, model, transform):
        # Repeated calls to ``on_drag_rotated`` during one drag always rotate
        # the *initial* transform, not the previous frame's output — otherwise
        # a multi-frame drag would compound rotations and overshoot.
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_rotated((0.0, 0.0, 1.0), math.pi / 2)
        model.on_drag_rotated((0.0, 0.0, 1.0), math.pi / 2)
        mat = transform.get_local_transform("/World/A")
        # Two calls with π/2 should match a single call with π/2 — not π.
        assert mat[0][0] == pytest.approx(0.0, abs=1e-9)
        assert mat[0][1] == pytest.approx(1.0, abs=1e-9)

    def test_zero_angle_is_noop(self, model, transform):
        model.set_selection(["/World/A"])
        initial = transform.get_local_transform("/World/A")
        model.on_drag_start()
        model.on_drag_rotated((0.0, 0.0, 1.0), 0.0)
        after = transform.get_local_transform("/World/A")
        for i in range(4):
            for j in range(4):
                assert after[i][j] == pytest.approx(initial[i][j], abs=1e-12)

    def test_multi_prim_rotation(self, model, transform):
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()
        model.on_drag_rotated((0.0, 0.0, 1.0), math.pi / 2)
        a = transform.get_local_transform("/World/A")
        b = transform.get_local_transform("/World/B")
        # Each prim rotated in place around its own origin. Translations
        # stay put (A at x=5, B at origin); upper-3×3 is the same rotation.
        assert a[3][0] == pytest.approx(5.0)
        assert b[3][0] == pytest.approx(0.0)
        for mat in (a, b):
            assert mat[0][1] == pytest.approx(1.0, abs=1e-9)
            assert mat[1][0] == pytest.approx(-1.0, abs=1e-9)


class TestOnDragScaled:
    def test_axis_scales_matching_row(self, model, transform):
        # Axis mask (1,0,0) with factor 2.0 → row 0 doubles, rows 1/2
        # untouched, translation preserved.
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_scaled((1.0, 0.0, 0.0), 2.0)
        mat = transform.get_local_transform("/World/A")
        assert mat[0][0] == pytest.approx(2.0)
        assert mat[1][1] == pytest.approx(1.0)
        assert mat[2][2] == pytest.approx(1.0)
        # Translation row stays put — scale about prim's own origin.
        assert mat[3][0] == pytest.approx(5.0)

    def test_uniform_scales_all_rows(self, model, transform):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_scaled((1.0, 1.0, 1.0), 2.0)
        mat = transform.get_local_transform("/World/A")
        assert mat[0][0] == pytest.approx(2.0)
        assert mat[1][1] == pytest.approx(2.0)
        assert mat[2][2] == pytest.approx(2.0)
        assert mat[3][0] == pytest.approx(5.0)

    def test_uses_suppress_notifications(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_scaled((1.0, 0.0, 0.0), 2.0)
        model._stage.suppress_change_notifications.assert_called()

    def test_notifies_live_transform_before_drag_end(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_scaled((1.0, 0.0, 0.0), 2.0)
        model._stage.notify_transform_changed.assert_called_once_with(
            ["/World/A"],
            source="viewport-manipulator-live",
        )

    def test_factor_rebases_on_initial_not_current(self, model, transform):
        # Repeated scale_drag calls rebase on the initial transform, not
        # compound — otherwise a multi-frame drag would overshoot.
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_scaled((1.0, 0.0, 0.0), 2.0)
        model.on_drag_scaled((1.0, 0.0, 0.0), 2.0)
        mat = transform.get_local_transform("/World/A")
        # Two calls with factor 2 should match a single call with factor 2
        # — not factor 4.
        assert mat[0][0] == pytest.approx(2.0)

    def test_factor_one_is_noop(self, model, transform):
        model.set_selection(["/World/A"])
        initial = transform.get_local_transform("/World/A")
        model.on_drag_start()
        model.on_drag_scaled((1.0, 1.0, 1.0), 1.0)
        after = transform.get_local_transform("/World/A")
        for i in range(4):
            for j in range(4):
                assert after[i][j] == pytest.approx(initial[i][j], abs=1e-12)

    def test_multi_prim_scale(self, model, transform):
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()
        model.on_drag_scaled((1.0, 1.0, 1.0), 3.0)
        a = transform.get_local_transform("/World/A")
        b = transform.get_local_transform("/World/B")
        # Each prim scaled independently around its own origin.
        assert a[0][0] == pytest.approx(3.0)
        assert a[3][0] == pytest.approx(5.0)
        assert b[0][0] == pytest.approx(3.0)
        assert b[3][0] == pytest.approx(0.0)


class TestApplyScale:
    def test_identity_factor_returns_copy(self):
        result = _apply_scale(_IDENTITY, 1.0, 1.0, 1.0)
        for i in range(4):
            for j in range(4):
                expected = 1.0 if i == j else 0.0
                assert result[i][j] == pytest.approx(expected)

    def test_x_scale_only_scales_row_0(self):
        result = _apply_scale(_IDENTITY, 3.0, 1.0, 1.0)
        assert result[0][0] == pytest.approx(3.0)
        assert result[1][1] == pytest.approx(1.0)
        assert result[2][2] == pytest.approx(1.0)

    def test_translation_row_preserved(self):
        result = _apply_scale(_TRANSLATION, 5.0, 5.0, 5.0)
        # _TRANSLATION has (1, 2, 3) in row 3 — scale must not touch it.
        assert result[3][0] == pytest.approx(1.0)
        assert result[3][1] == pytest.approx(2.0)
        assert result[3][2] == pytest.approx(3.0)
        assert result[3][3] == pytest.approx(1.0)

    def test_result_is_4x4(self):
        result = _apply_scale(_IDENTITY, 2.0, 2.0, 2.0)
        assert len(result) == 4
        assert all(len(row) == 4 for row in result)

    def test_scales_full_row_not_just_diagonal(self):
        # Off-diagonal entries in a row should scale too: a row like
        # [a, b, c, 0] under factor f becomes [fa, fb, fc, 0].
        rotated = [
            [0.0, 1.0, 0.0, 0.0],  # row 0: old local +X axis points at +Y
            [-1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        result = _apply_scale(rotated, 2.0, 1.0, 1.0)
        assert result[0][0] == pytest.approx(0.0)
        assert result[0][1] == pytest.approx(2.0)
        # Row 1 untouched.
        assert result[1][0] == pytest.approx(-1.0)


class TestApplyDelta:
    def test_identity_times_translation(self):
        result = _apply_delta(_IDENTITY, _TRANSLATION, "world")
        assert result[3][0] == pytest.approx(1.0)
        assert result[3][1] == pytest.approx(2.0)
        assert result[3][2] == pytest.approx(3.0)

    def test_translation_times_identity(self):
        result = _apply_delta(_TRANSLATION, _IDENTITY, "world")
        assert result[3][0] == pytest.approx(1.0)
        assert result[3][1] == pytest.approx(2.0)
        assert result[3][2] == pytest.approx(3.0)

    def test_identity_times_identity(self):
        result = _apply_delta(_IDENTITY, _IDENTITY, "world")
        for i in range(4):
            for j in range(4):
                expected = 1.0 if i == j else 0.0
                assert result[i][j] == pytest.approx(expected)

    def test_result_is_4x4(self):
        result = _apply_delta(_IDENTITY, _TRANSLATION, "world")
        assert len(result) == 4
        assert all(len(row) == 4 for row in result)

    def test_translation_composed(self):
        t1 = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [1.0, 0.0, 0.0, 1.0],
        ]
        t2 = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [2.0, 0.0, 0.0, 1.0],
        ]
        result = _apply_delta(t1, t2, "world")
        assert result[3][0] == pytest.approx(3.0)

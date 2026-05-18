# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the Step C.1 ``TransformManipulator`` scaffold.

Covers:

* Construction + default tool.
* Tool property validation + switching.
* ``invalidate`` is triggered when ``tool`` changes.
* ``on_build`` emits nothing when the model has no selection.
* ``on_build`` emits geometry once a selection is present.
* ``pivot_fn`` is called and the return value is used.

The real gizmo drag math, undo grouping, and highlight system land in
Steps C.2 / C.3 / C.4 — this scaffold only asserts shape and wiring.
"""

from __future__ import annotations

import pytest
from omni.ui_scene import scene as sc

from ovwidgets.viewport.prim_transform_model import PrimTransformModel
from ovwidgets.viewport.transform_manipulator import (
    AXIS_COLOR_X,
    AXIS_COLOR_Y,
    AXIS_COLOR_Z,
    GIZMO_SIZE_SCALE,
    TOOL_ROTATE,
    TOOL_SCALE,
    TOOL_TRANSLATE,
    VALID_TOOLS,
    TransformManipulator,
    _scale_matrix,
    _translation_matrix,
)

# -- fixtures --------------------------------------------------------------


@pytest.fixture
def scene_view() -> sc.SceneView:
    return sc.SceneView()


@pytest.fixture
def empty_model() -> PrimTransformModel:
    """Fresh ``PrimTransformModel`` with no adapters and no selection."""
    return PrimTransformModel()


@pytest.fixture
def selected_model() -> PrimTransformModel:
    """``PrimTransformModel`` with a single non-empty selection path."""
    model = PrimTransformModel()
    model._selected_paths = ["/World/Cube"]
    return model


@pytest.fixture
def manipulator(scene_view: sc.SceneView, empty_model: PrimTransformModel) -> TransformManipulator:
    with scene_view.scene:
        m = TransformManipulator(model=empty_model, tool=TOOL_TRANSLATE)
    return m


# -- construction ----------------------------------------------------------


class TestConstants:
    def test_gizmo_size_scale_is_refined(self):
        # Polished value: small enough to look like a refined tool, big
        # enough to pick. Compare Maya/Blender manipulator proportions.
        assert 0.04 <= GIZMO_SIZE_SCALE <= 0.06

    def test_valid_tools_has_three_names(self):
        assert VALID_TOOLS == (TOOL_TRANSLATE, TOOL_ROTATE, TOOL_SCALE)

    def test_axis_colors_differ_per_axis(self):
        # Guard against a copy-paste bug where two axes share a colour.
        assert AXIS_COLOR_X != AXIS_COLOR_Y
        assert AXIS_COLOR_Y != AXIS_COLOR_Z
        assert AXIS_COLOR_X != AXIS_COLOR_Z


class TestConstruction:
    def test_is_sc_manipulator_subclass(self):
        assert issubclass(TransformManipulator, sc.Manipulator)

    def test_creates_with_default_tool(self, scene_view, empty_model):
        with scene_view.scene:
            m = TransformManipulator(model=empty_model)
        assert m.tool == TOOL_TRANSLATE

    def test_accepts_explicit_tool(self, scene_view, empty_model):
        with scene_view.scene:
            m = TransformManipulator(model=empty_model, tool=TOOL_ROTATE)
        assert m.tool == TOOL_ROTATE

    def test_rejects_invalid_tool_at_construction(self, scene_view, empty_model):
        with scene_view.scene:
            with pytest.raises(ValueError):
                TransformManipulator(model=empty_model, tool="flargh")

    def test_stores_model_reference(self, manipulator, empty_model):
        assert manipulator.prim_model is empty_model

    def test_accepts_pivot_fn(self, scene_view, empty_model):
        pivot_fn = lambda: (1.0, 2.0, 3.0)
        with scene_view.scene:
            m = TransformManipulator(model=empty_model, pivot_fn=pivot_fn)
        assert m._pivot_fn is pivot_fn

    def test_default_pivot_fn_returns_origin(self, manipulator):
        assert manipulator._pivot_fn() == (0.0, 0.0, 0.0)


# -- tool property --------------------------------------------------------


class TestToolProperty:
    def test_switch_to_rotate(self, manipulator):
        manipulator.tool = TOOL_ROTATE
        assert manipulator.tool == TOOL_ROTATE

    def test_switch_to_scale(self, manipulator):
        manipulator.tool = TOOL_SCALE
        assert manipulator.tool == TOOL_SCALE

    def test_switch_back_to_translate(self, manipulator):
        manipulator.tool = TOOL_ROTATE
        manipulator.tool = TOOL_TRANSLATE
        assert manipulator.tool == TOOL_TRANSLATE

    def test_invalid_tool_rejected(self, manipulator):
        with pytest.raises(ValueError):
            manipulator.tool = "spin"

    def test_setting_same_tool_is_noop(self, manipulator):
        manipulator.tool = TOOL_TRANSLATE
        # No state change, no exception — just a silent noop.
        assert manipulator.tool == TOOL_TRANSLATE

    def test_tool_change_calls_invalidate(self, manipulator, monkeypatch):
        calls: list = []
        monkeypatch.setattr(manipulator, "invalidate", lambda: calls.append(1))
        manipulator.tool = TOOL_ROTATE
        assert calls == [1]

    def test_noop_tool_change_does_not_invalidate(self, manipulator, monkeypatch):
        calls: list = []
        monkeypatch.setattr(manipulator, "invalidate", lambda: calls.append(1))
        manipulator.tool = TOOL_TRANSLATE  # same as current
        assert calls == []


# -- has_selection --------------------------------------------------------


class TestHasSelection:
    def test_empty_model_has_no_selection(self, manipulator):
        assert manipulator.has_selection() is False

    def test_populated_model_has_selection(self, selected_model, scene_view):
        with scene_view.scene:
            m = TransformManipulator(model=selected_model)
        assert m.has_selection() is True

    def test_model_without_attribute_is_treated_empty(self, scene_view):
        class Bare:
            pass
        with scene_view.scene:
            m = TransformManipulator(model=Bare())
        assert m.has_selection() is False


# -- on_build behaviour ---------------------------------------------------


class TestOnBuild:
    def test_no_selection_emits_no_geometry(self, manipulator):
        # ``on_build`` must be safe to call with no selection — it's the
        # "empty invisible gizmo" path the plan requires.
        manipulator.on_build()  # no exception

    def test_with_selection_calls_pivot_fn(self, scene_view, selected_model):
        calls: list = []
        pivot_fn = lambda: (calls.append(1) or (1.0, 2.0, 3.0))
        with scene_view.scene:
            m = TransformManipulator(
                model=selected_model, pivot_fn=pivot_fn,
            )
            m.on_build()
        assert len(calls) >= 1

    def test_with_selection_builds_for_translate(self, scene_view, selected_model):
        with scene_view.scene:
            m = TransformManipulator(model=selected_model, tool=TOOL_TRANSLATE)
            m.on_build()  # no exception

    def test_with_selection_builds_for_rotate(self, scene_view, selected_model):
        with scene_view.scene:
            m = TransformManipulator(model=selected_model, tool=TOOL_ROTATE)
            m.on_build()  # no exception

    def test_with_selection_builds_for_scale(self, scene_view, selected_model):
        with scene_view.scene:
            m = TransformManipulator(model=selected_model, tool=TOOL_SCALE)
            m.on_build()  # no exception

    def test_dispatch_hits_each_builder(self, manipulator, monkeypatch):
        # Drive ``_build_tool_geometry`` directly, spying on each builder.
        calls: list = []
        monkeypatch.setattr(
            manipulator, "_build_translate_placeholder",
            lambda: calls.append("translate"),
        )
        monkeypatch.setattr(
            manipulator, "_build_rotate",
            lambda: calls.append("rotate"),
        )
        monkeypatch.setattr(
            manipulator, "_build_scale",
            lambda: calls.append("scale"),
        )
        manipulator._tool = TOOL_TRANSLATE
        manipulator._build_tool_geometry()
        manipulator._tool = TOOL_ROTATE
        manipulator._build_tool_geometry()
        manipulator._tool = TOOL_SCALE
        manipulator._build_tool_geometry()
        assert calls == ["translate", "rotate", "scale"]

    def test_on_model_updated_is_noop(self, manipulator):
        manipulator.on_model_updated(None)  # no exception


# -- helper math ----------------------------------------------------------


class TestMatrixHelpers:
    def test_scale_matrix_is_16_floats(self):
        m = _scale_matrix(2.0)
        assert len(m) == 16

    def test_scale_matrix_diagonal(self):
        m = _scale_matrix(0.15)
        assert m[0] == pytest.approx(0.15)
        assert m[5] == pytest.approx(0.15)
        assert m[10] == pytest.approx(0.15)
        assert m[15] == pytest.approx(1.0)

    def test_scale_matrix_off_diagonal_zero(self):
        m = _scale_matrix(0.15)
        # Off-diagonal entries in the upper 3×3 must be zero — any non-zero
        # value there would shear the gizmo.
        zero_indices = [1, 2, 3, 4, 6, 7, 8, 9, 11, 12, 13, 14]
        for idx in zero_indices:
            assert m[idx] == pytest.approx(0.0)

    def test_translation_matrix_stores_translation(self):
        m = _translation_matrix(5.0, 7.0, 11.0)
        # Row-major: translation lands in the last row's first three entries.
        assert m[12] == pytest.approx(5.0)
        assert m[13] == pytest.approx(7.0)
        assert m[14] == pytest.approx(11.0)


class TestPersistentGestures:
    """The manipulator must own gesture instances that survive ``invalidate``.

    A camera-distance-driven rebuild of the gizmo fires on every frame
    while a selection exists. If ``build_*_gizmo`` produced fresh
    :class:`sc.DragGesture` instances each time, a live drag would lose
    its captured shape on the next rebuild and fall through to the
    Screen-level pick gesture (user symptom: "drag only changes
    selection instead of moving the object"). The fix: the manipulator
    constructs the gestures once, passes them into the builders, and
    the builders rebind them to freshly-built shapes.
    """

    def test_translate_gesture_identity_stable_across_rebuilds(self, scene_view, selected_model):
        with scene_view.scene:
            m = TransformManipulator(model=selected_model, tool=TOOL_TRANSLATE)
            m.on_build()
            before = [id(g) for g in m._translate_drags]
            m.invalidate()
            m.on_build()
            after = [id(g) for g in m._translate_drags]
        assert before == after

    def test_rotate_gesture_identity_stable_across_rebuilds(self, scene_view, selected_model):
        with scene_view.scene:
            m = TransformManipulator(model=selected_model, tool=TOOL_ROTATE)
            m.on_build()
            before = [id(g) for g in m._rotate_drags]
            m.invalidate()
            m.on_build()
            after = [id(g) for g in m._rotate_drags]
        assert before == after

    def test_scale_gesture_identity_stable_across_rebuilds(self, scene_view, selected_model):
        with scene_view.scene:
            m = TransformManipulator(model=selected_model, tool=TOOL_SCALE)
            m.on_build()
            before = [id(g) for g in m._scale_drags]
            before_uniform = id(m._uniform_scale_drag)
            m.invalidate()
            m.on_build()
            after = [id(g) for g in m._scale_drags]
            after_uniform = id(m._uniform_scale_drag)
        assert before == after
        assert before_uniform == after_uniform

    def test_handles_reference_persistent_gestures(self, scene_view, selected_model):
        """``translate_handles.drag_gestures`` must point at the persistent set."""
        with scene_view.scene:
            m = TransformManipulator(model=selected_model, tool=TOOL_TRANSLATE)
            m.on_build()
        assert m._translate_handles is not None
        assert m._translate_handles.drag_gestures[0] is m._translate_drags[0]
        assert m._translate_handles.drag_gestures[1] is m._translate_drags[1]
        assert m._translate_handles.drag_gestures[2] is m._translate_drags[2]

    def test_size_fn_overrides_constant(self, scene_view, selected_model):
        """A user-provided ``size_fn`` replaces :data:`GIZMO_SIZE_SCALE`.

        The viewport passes in a camera-distance-driven scale so the
        gizmo appears constant-sized on screen; that can only work if the
        manipulator calls ``size_fn`` from ``on_build``.
        """
        calls = []

        def _size() -> float:
            calls.append(None)
            return 2.5

        with scene_view.scene:
            m = TransformManipulator(
                model=selected_model, tool=TOOL_TRANSLATE, size_fn=_size,
            )
            m.on_build()
        assert len(calls) >= 1

    def test_size_fn_exception_falls_back_to_constant(self, scene_view, selected_model):
        """A raising ``size_fn`` must not abort the draw — the constant kicks in."""
        def _size() -> float:
            raise RuntimeError("viewport not ready yet")

        with scene_view.scene:
            m = TransformManipulator(
                model=selected_model, tool=TOOL_TRANSLATE, size_fn=_size,
            )
            # Must not raise.
            m.on_build()
        assert m._translate_handles is not None

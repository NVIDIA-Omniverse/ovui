# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for UsdTransformAdapter (skipped when USD is unavailable)."""

import time

import pytest

from pxr import Gf, Sdf, Usd, UsdGeom


@pytest.fixture
def stage_with_sphere():
    stage = Usd.Stage.CreateInMemory()
    sphere = UsdGeom.Sphere.Define(stage, "/Sphere")
    UsdGeom.XformCommonAPI(sphere).SetTranslate((1.0, 2.0, 3.0))
    return stage


@pytest.fixture
def adapter(stage_with_sphere):
    from ovui_data_adapters.openusd import UsdTransformAdapter
    return UsdTransformAdapter(stage_with_sphere)


class TestGetLocalTransform:
    def test_returns_4x4(self, adapter):
        mat = adapter.get_local_transform("/Sphere")
        assert len(mat) == 4
        assert all(len(row) == 4 for row in mat)

    def test_translation_in_row3(self, adapter):
        mat = adapter.get_local_transform("/Sphere")
        assert abs(mat[3][0] - 1.0) < 1e-5
        assert abs(mat[3][1] - 2.0) < 1e-5
        assert abs(mat[3][2] - 3.0) < 1e-5

    def test_invalid_path_returns_identity(self, adapter):
        mat = adapter.get_local_transform("/DoesNotExist")
        assert len(mat) == 4
        assert mat[0][0] == pytest.approx(1.0)
        assert mat[0][1] == pytest.approx(0.0)

    def test_returns_plain_lists(self, adapter):
        mat = adapter.get_local_transform("/Sphere")
        assert isinstance(mat, list)
        assert isinstance(mat[0], list)
        assert isinstance(mat[0][0], float)


class TestGetWorldTransform:
    def test_returns_4x4(self, adapter):
        mat = adapter.get_world_transform("/Sphere")
        assert len(mat) == 4
        assert all(len(row) == 4 for row in mat)

    def test_returns_plain_lists(self, adapter):
        mat = adapter.get_world_transform("/Sphere")
        assert isinstance(mat, list)
        assert isinstance(mat[0], list)

    def test_root_prim_world_matches_local(self, stage_with_sphere):
        from ovui_data_adapters.openusd import UsdTransformAdapter
        adapter = UsdTransformAdapter(stage_with_sphere)
        local = adapter.get_local_transform("/Sphere")
        world = adapter.get_world_transform("/Sphere")
        assert abs(world[3][0] - local[3][0]) < 1e-5


class TestSetLocalTransform:
    def test_set_changes_prim(self, adapter, stage_with_sphere):
        new_matrix = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [10.0, 20.0, 30.0, 1.0],
        ]
        adapter.set_local_transform("/Sphere", new_matrix)
        mat = adapter.get_local_transform("/Sphere")
        assert abs(mat[3][0] - 10.0) < 1e-5
        assert abs(mat[3][1] - 20.0) < 1e-5
        assert abs(mat[3][2] - 30.0) < 1e-5

    def test_set_invalid_path_no_crash(self, adapter):
        adapter.set_local_transform("/DoesNotExist", [[1, 0, 0, 0]] * 4)


class TestAuthoredTransformHistory:
    def test_undo_redo_round_trips_authored_xform_structure(self):
        from ovui_data_adapters.openusd import UsdTransformAdapter

        from ovui_widgets.common.undo import BatchTransformCommand, UndoManager

        stage = Usd.Stage.CreateInMemory()
        prim = UsdGeom.Xform.Define(stage, "/Object")
        common = UsdGeom.XformCommonAPI(prim)
        common.SetTranslate((1.0, 2.0, 3.0))
        common.SetRotate((10.0, 20.0, 30.0))
        common.SetScale((1.0, 2.0, 3.0))
        adapter = UsdTransformAdapter(stage)
        initial = adapter.get_local_transform("/Object")
        final = [row[:] for row in initial]
        final[3][0] += 4.0
        layer = stage.GetRootLayer()
        authored_before = layer.ExportToString()

        undo = UndoManager()
        undo.push(BatchTransformCommand(adapter, "/Object", initial, final))
        authored_after = layer.ExportToString()
        assert authored_after != authored_before

        assert undo.undo() is True
        assert layer.ExportToString() == authored_before
        assert undo.redo() is True
        assert layer.ExportToString() == authored_after

    def test_undo_restores_initial_after_app_authored_preview(self):
        from ovui_data_adapters.openusd import UsdTransformAdapter

        from ovui_widgets.common.undo import BatchTransformCommand, UndoManager

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/Object")
        adapter = UsdTransformAdapter(stage)
        initial = adapter.get_local_transform("/Object")
        final = [row[:] for row in initial]
        final[3][0] = 6.0
        adapter.set_local_transform("/Object", final)

        undo = UndoManager()
        undo.push(BatchTransformCommand(adapter, "/Object", initial, final))
        assert undo.undo() is True
        assert adapter.get_local_transform("/Object") == initial
        assert undo.redo() is True
        assert adapter.get_local_transform("/Object") == final


class TestCanTransform:
    def test_valid_prim_returns_true(self, adapter):
        assert adapter.can_transform("/Sphere") is True

    def test_invalid_path_returns_false(self, adapter):
        assert adapter.can_transform("/DoesNotExist") is False


# The animated prims of the regression (scene anim_main.usda: Slider and Spinner; scene neg_huge.usda: Neg), a prim with one
# time sample (the Property Inspector shows it as animated too) and a static prim with the op order of Slider.
_ANIMATED_SCENE = """#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 0.01
    startTimeCode = 0
    endTimeCode = 48
)

def Xform "World" {
    def Cube "Slider" {
        double size = 30
        double3 xformOp:translate.timeSamples = { 0: (-150, 15, 0), 48: (150, 15, 0) }
        float xformOp:rotateY.timeSamples = { 0: 0, 48: 180 }
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateY"]
    }
    def Cube "Spinner" {
        double size = 30
        double3 xformOp:translate = (0, 15, 150)
        float xformOp:rotateY.timeSamples = { 0: 45, 48: 90 }
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateY"]
    }
    def Cube "Neg" {
        double size = 30
        double3 xformOp:translate.timeSamples = { -1000: (-200, 15, 0), -500: (-100, 15, 0) }
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }
    def Cube "Once" {
        double size = 30
        double3 xformOp:translate.timeSamples = { 10: (100, 15, 0) }
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }
    def Cube "Static" {
        double size = 30
        double3 xformOp:translate = (0, 15, -150)
        float xformOp:rotateY = 30
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateY"]
    }
}
"""

_ANIMATED_OPS = {
    "/World/Slider": "xformOp:translate, xformOp:rotateY",
    "/World/Spinner": "xformOp:rotateY",
    "/World/Neg": "xformOp:translate",
    "/World/Once": "xformOp:translate",
}

_MOVE_X_60 = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [60.0, 0.0, 0.0, 1.0]]
_TURN_Y_30 = [
    [0.8660254037844387, 0.0, -0.5, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.5, 0.0, 0.8660254037844387, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


@pytest.fixture
def animated_stage():
    stage = Usd.Stage.CreateInMemory()
    assert stage.GetRootLayer().ImportFromString(_ANIMATED_SCENE)
    return stage


def _authored_properties(layer, path):
    """Each authored property of the prim spec at ``path``: its default value and its time samples."""
    return {
        prop.name: (prop.default, {time: layer.QueryTimeSample(prop.path, time) for time in layer.ListTimeSamplesForPath(prop.path)})
        for prop in layer.GetPrimAtPath(path).properties
    }


def _reason(op_names):
    return f"The transform is animated ({op_names}). Move, Rotate and Scale would remove the animation."


def _value_clip_stage(folder, samples):
    """A stage whose /Model gets the values of its translate and rotateY ops from a value clip with ``samples`` time
    samples for each op. The stage layer itself has only the op order."""
    clip_layer = Sdf.Layer.CreateNew(str(folder / f"clip_{samples}.usda"))
    clip_stage = Usd.Stage.Open(clip_layer)
    clip_cube = UsdGeom.Cube.Define(clip_stage, "/Model")
    translate = clip_cube.AddTranslateOp().GetAttr().GetPath()
    rotate = clip_cube.AddRotateYOp().GetAttr().GetPath()
    with Sdf.ChangeBlock():
        for index in range(samples):
            clip_layer.SetTimeSample(translate, float(index), Gf.Vec3d(float(index), 15.0, 0.0))
            clip_layer.SetTimeSample(rotate, float(index), float(index % 360))
    clip_layer.Save()
    stage = Usd.Stage.CreateInMemory()
    cube = UsdGeom.Cube.Define(stage, "/Model")
    cube.AddTranslateOp()
    cube.AddRotateYOp()
    clips = Usd.ClipsAPI(cube.GetPrim())
    clips.SetClipAssetPaths([Sdf.AssetPath(clip_layer.identifier)])
    clips.SetClipPrimPath("/Model")
    clips.SetClipActive([(0.0, 0)])
    clips.SetClipTimes([(0.0, 0.0), (float(samples - 1), float(samples - 1))])
    return stage


def _time_sample_stage(samples):
    """A stage whose /Model has a translate op and a rotateY op with ``samples`` time samples each."""
    stage = Usd.Stage.CreateInMemory()
    cube = UsdGeom.Cube.Define(stage, "/Model")
    translate = cube.AddTranslateOp().GetAttr().GetPath()
    rotate = cube.AddRotateYOp().GetAttr().GetPath()
    layer = stage.GetRootLayer()
    with Sdf.ChangeBlock():
        for index in range(samples):
            layer.SetTimeSample(translate, float(index), Gf.Vec3d(float(index), 15.0, 0.0))
            layer.SetTimeSample(rotate, float(index), float(index % 360))
    return stage


def _seconds_per_policy_call(stage, path, calls=50, rounds=5):
    """The shortest time of ``rounds`` rounds, divided by ``calls``: the least disturbed measure on a busy machine."""
    from ovui_data_adapters.openusd import UsdTransformAdapter

    adapter = UsdTransformAdapter(stage)
    best = float("inf")
    for _ in range(rounds):
        start = time.perf_counter()
        for _ in range(calls):
            adapter.get_transform_edit_policy(path)
        best = min(best, time.perf_counter() - start)
    return best / calls


class TestAnimatedTransform:
    """Regression: a gizmo edit replaced animated transform ops with one static matrix (or, for a single animated
    translate, put a default value under its time samples). The adapter now refuses these edits and gives the cause."""

    @pytest.mark.parametrize("path", sorted(_ANIMATED_OPS))
    def test_edit_policy_blocks_an_animated_transform_and_names_its_animated_ops(self, animated_stage, path):
        from ovui_data_adapters.common import TransformEditMode
        from ovui_data_adapters.openusd import UsdTransformAdapter

        policy = UsdTransformAdapter(animated_stage).get_transform_edit_policy(path)

        assert policy.mode is TransformEditMode.BLOCKED
        assert policy.reason == _reason(_ANIMATED_OPS[path])

    def test_edit_policy_blocks_an_op_animated_by_a_spline(self):
        from pxr import Ts

        from ovui_data_adapters.common import TransformEditMode
        from ovui_data_adapters.openusd import UsdTransformAdapter

        stage = Usd.Stage.CreateInMemory()
        cube = UsdGeom.Cube.Define(stage, "/Cube")
        cube.AddTranslateOp().Set((0.0, 15.0, 0.0))
        spline = Ts.Spline("double")
        for time, value in ((0.0, 0.0), (48.0, 180.0)):
            knot = Ts.Knot("double")
            knot.SetTime(time)
            knot.SetValue(value)
            spline.SetKnot(knot)
        cube.AddRotateYOp(precision=UsdGeom.XformOp.PrecisionDouble).GetAttr().SetSpline(spline)

        policy = UsdTransformAdapter(stage).get_transform_edit_policy("/Cube")

        assert policy.mode is TransformEditMode.BLOCKED
        assert policy.reason == _reason("xformOp:rotateY")

    def test_edit_policy_blocks_ops_animated_by_value_clips_and_a_write_keeps_the_layers(self, tmp_path):
        from ovui_data_adapters.common import TransformEditMode
        from ovui_data_adapters.openusd import UsdTransformAdapter

        stage = _value_clip_stage(tmp_path, 3)
        adapter = UsdTransformAdapter(stage)
        authored_before = stage.GetRootLayer().ExportToString()
        clip_before = (tmp_path / "clip_3.usda").read_text()

        policy = adapter.get_transform_edit_policy("/Model")
        with pytest.raises(RuntimeError) as refused:
            adapter.set_local_transform("/Model", _MOVE_X_60)

        assert policy.mode is TransformEditMode.BLOCKED
        assert policy.reason == _reason("xformOp:translate, xformOp:rotateY")
        assert str(refused.value) == f"set_local_transform is refused for /Model: {policy.reason}"
        assert stage.GetRootLayer().ExportToString() == authored_before
        assert (tmp_path / "clip_3.usda").read_text() == clip_before

    @pytest.mark.parametrize("source", ["time samples", "value clips"])
    def test_edit_policy_costs_the_same_for_a_long_animation(self, tmp_path, source):
        """The edit policy of each selected prim is read at each selection change. A check that lists or counts the
        time samples made the selection of a prim with 20,000 samples for each op hundreds of times slower."""
        from ovui_data_adapters.common import TransformEditMode
        from ovui_data_adapters.openusd import UsdTransformAdapter

        if source == "time samples":
            short, long = _time_sample_stage(2), _time_sample_stage(20_000)
        else:
            short, long = _value_clip_stage(tmp_path, 2), _value_clip_stage(tmp_path, 20_000)
        assert UsdTransformAdapter(long).get_transform_edit_policy("/Model").mode is TransformEditMode.BLOCKED

        ratio = _seconds_per_policy_call(long, "/Model") / _seconds_per_policy_call(short, "/Model")

        assert ratio < 10.0, f"a policy call for 20,000 samples per op costs {ratio:.0f} times a call for 2 samples"

    def test_edit_policy_keeps_a_static_transform_editable(self, animated_stage):
        from ovui_data_adapters.common import TransformEditMode
        from ovui_data_adapters.openusd import UsdTransformAdapter

        policy = UsdTransformAdapter(animated_stage).get_transform_edit_policy("/World/Static")

        assert policy.mode is TransformEditMode.DIRECT

    @pytest.mark.parametrize("matrix", [_MOVE_X_60, _TURN_Y_30], ids=["move", "turn"])
    @pytest.mark.parametrize("path", sorted(_ANIMATED_OPS))
    def test_set_local_transform_refuses_an_animated_transform_and_keeps_the_layer(self, animated_stage, path, matrix):
        from ovui_data_adapters.openusd import UsdTransformAdapter

        layer = animated_stage.GetRootLayer()
        authored_before = layer.ExportToString()

        with pytest.raises(RuntimeError) as refused:
            UsdTransformAdapter(animated_stage).set_local_transform(path, matrix)

        assert str(refused.value) == f"set_local_transform is refused for {path}: {_reason(_ANIMATED_OPS[path])}"
        assert layer.ExportToString() == authored_before


class TestGizmoDragOnAnimatedTransform:
    """The viewport transform model with the OpenUSD adapter: the Move, Rotate and Scale controls are off for an animated
    prim, with the cause as their tooltip, and a drag of a mixed selection changes only the static prim and says why the
    animated prim is not changed."""

    @staticmethod
    def _model(stage):
        from contextlib import nullcontext
        from unittest.mock import MagicMock

        from ovui_data_adapters.openusd import UsdTransformAdapter

        from ovui_widgets.common.undo import UndoManager
        from ovui_widgets.viewport.prim_transform_model import PrimTransformModel

        stage_adapter = MagicMock()
        stage_adapter.suppress_change_notifications.side_effect = nullcontext
        return PrimTransformModel(UsdTransformAdapter(stage), stage_adapter, UndoManager())

    @pytest.mark.parametrize("path", sorted(_ANIMATED_OPS))
    def test_transform_controls_are_off_with_the_cause_for_an_animated_prim(self, animated_stage, path):
        model = self._model(animated_stage)

        model.set_selection([path])

        assert model.transform_controls_enabled() is False
        assert model.transform_controls_tooltip() == _reason(_ANIMATED_OPS[path])

    @pytest.mark.parametrize(
        "paths, subject",
        [
            (["/World/Slider"], "/World/Slider"),
            (["/World/Neg", "/World/Once", "/World/Spinner"], "/World/Neg and 2 more prims"),
            (["/World/Static"], None),
            (["/World/Static", "/World/Slider"], None),
        ],
        ids=["one-animated", "three-animated", "static", "mixed"],
    )
    def test_each_tool_request_shows_the_cause_one_time_when_no_gizmo_can_appear(
        self, animated_stage, monkeypatch, paths, subject
    ):
        """A Tools menu choice of the tool that is already active showed no cause, and E or R sent it two times.
        Each request (the Tools menu, also for the active tool, W, E, an Inspector tool request and a key from a host)
        shows it one time."""
        from types import SimpleNamespace
        from unittest.mock import Mock

        import ovui_widgets.app.menu_bar as menu_bar
        from ovui_widgets.app.application import Application
        from ovui_widgets.common.error_reporter import ErrorReporter
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.inspector import ViewportInspector
        from ovui_widgets.viewport.manipulator_registry import ToolRegistry
        from ovui_widgets.viewport.viewport_widget import ViewportSurface

        shown = []
        monkeypatch.setattr(ErrorReporter, "show_warning", lambda message, *args: shown.append(message))
        view = ViewportSurface.__new__(ViewportSurface)
        view._transform_model = self._model(animated_stage)
        view._transform_model.set_selection(paths)
        assert shown == []  # a plain selection shows no message
        view._transform_manipulator = SimpleNamespace(visible=True, tool="translate")
        view._transform_manipulator_visible = True
        view._refresh_toolbar_state = Mock()
        view._flight_keyboard = SimpleNamespace(rmb_held=False, handle_key_event=lambda *_args: None)
        settings = Settings()
        view._tool_registry = ToolRegistry(
            settings=settings, manipulator=view._transform_manipulator, on_tool_changed=view._on_tool_changed
        )
        app = SimpleNamespace(_viewport_window=view, settings=settings)
        # The real Tools menu of the app; only the menu widgets are replaced, so that the test can choose an item.
        items = {}
        monkeypatch.setattr(menu_bar, "ui", SimpleNamespace(MenuItem=lambda label, **kw: items.update({label: kw})))
        monkeypatch.setattr(menu_bar, "_build_hook_items", lambda *_args: None)
        menu_bar._build_tools_menu(app)
        assert items["Move"]["checked"] is True

        inspector = ViewportInspector(lambda: {"primary": view}, lambda: None)
        requests = [
            ("Tools > Move, the active tool", items["Move"]["triggered_fn"], "translate"),
            ("W, the active tool", lambda: Application._dispatch_tool_hotkey(app, ord("w"), 0), "translate"),
            ("E, a new tool", lambda: Application._dispatch_tool_hotkey(app, ord("e"), 0), "rotate"),
            ("Tools > Scale, a new tool", items["Scale"]["triggered_fn"], "scale"),
            ("Inspector tool request", lambda: inspector.tool("move"), "translate"),
            ("R from a host", lambda: view.handle_navigation_key(ord("R"), 0, True), "scale"),
        ]
        expected = [] if subject is None else [f"{subject}: {_reason(_ANIMATED_OPS[paths[0]])}"]
        for name, request, tool in requests:
            shown.clear()
            request()
            assert view._tool_registry.active_tool == tool, name
            assert shown == expected, name

    def test_drag_of_a_mixed_selection_moves_the_static_prim_and_reports_the_animated_prim(
        self, animated_stage, monkeypatch
    ):
        from ovui_widgets.common.error_reporter import ErrorReporter

        reports = []
        for name in ("log_warning", "show_warning"):
            monkeypatch.setattr(ErrorReporter, name, lambda *args, _name=name: reports.append((_name, args[-1])))
        slider_before = _authored_properties(animated_stage.GetRootLayer(), "/World/Slider")
        model = self._model(animated_stage)
        model.set_selection(["/World/Static", "/World/Slider"])
        assert model.transform_controls_enabled() is True

        model.on_drag_start()
        model.on_drag_moved(_MOVE_X_60)
        model.on_drag_ended()

        message = f"Move Prims: /World/Slider is not changed: {_reason(_ANIMATED_OPS['/World/Slider'])}"
        assert reports == [("log_warning", message), ("show_warning", message)]
        static = UsdGeom.Xformable(animated_stage.GetPrimAtPath("/World/Static"))
        assert static.GetLocalTransformation()[3][0] == pytest.approx(60.0)
        assert _authored_properties(animated_stage.GetRootLayer(), "/World/Slider") == slider_before


class TestGizmoEditKeepsTheTransformOps:
    """A gizmo edit writes the new values into the translate, rotate and scale
    operations of the prim, so the separate values stay.

    Each edit goes through the drag of ``PrimTransformModel``, as in the
    viewport, and the local matrix of the prim must be the matrix of the drag.
    """

    @staticmethod
    def _stage(text):
        stage = Usd.Stage.CreateInMemory()
        assert stage.GetRootLayer().ImportFromString("#usda 1.0\n" + text)
        return stage

    @staticmethod
    def _drag(stage, path, kind, *args):
        """One gizmo drag of the prim at ``path``; returns its undo manager."""
        import math

        from ovui_data_adapters.openusd import UsdStageAdapter, UsdTransformAdapter

        from ovui_widgets.common.undo import UndoManager
        from ovui_widgets.viewport.prim_transform_model import PrimTransformModel

        undo = UndoManager()
        model = PrimTransformModel(UsdTransformAdapter(stage), UsdStageAdapter(stage, undo_manager=undo), undo)
        model.set_selection([path])
        model.on_drag_start()
        if kind == "rotate":
            axis, degrees = args
            model.on_drag_rotated(axis, math.radians(degrees))
        elif kind == "scale":
            model.on_drag_scaled(*args)
        else:
            model.on_drag_moved(args[0])
        model.on_drag_ended()
        return undo

    @staticmethod
    def _ops(stage, path):
        return [(op.GetOpName(), op.Get()) for op in UsdGeom.Xformable(stage.GetPrimAtPath(path)).GetOrderedXformOps()]

    @staticmethod
    def _local(stage, path):
        return UsdGeom.Xformable(stage.GetPrimAtPath(path)).GetLocalTransformation()

    @staticmethod
    def _turned(matrix, axis, degrees):
        """``matrix`` turned in place about the world ``axis``, as the rotate gizmo does."""
        result = Gf.Matrix4d(matrix)
        result.SetTranslateOnly(Gf.Vec3d(0.0))
        result = result * Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(*axis), degrees))
        result.SetTranslateOnly(matrix.ExtractTranslation())
        return result

    def test_rotate_writes_the_rotate_op_and_keeps_translate_and_scale_exactly(self):
        stage = self._stage(
            'def Cube "C" {\n'
            "  float3 xformOp:translate = (2, 0.5, 0)\n"
            "  float3 xformOp:rotateXYZ = (10, 20, 30)\n"
            "  float3 xformOp:scale = (1, 1.5, 0.3)\n"
            '  uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]\n'
            "}\n"
        )
        expected = self._turned(self._local(stage, "/C"), (0.0, 1.0, 0.0), 40.0)

        self._drag(stage, "/C", "rotate", (0.0, 1.0, 0.0), 40.0)

        ops = dict(self._ops(stage, "/C"))
        assert list(ops) == ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]
        # Not changed by a rotate: the exact old values, also 0.3 of a float.
        assert ops["xformOp:translate"] == Gf.Vec3f(2.0, 0.5, 0.0)
        assert ops["xformOp:scale"] == Gf.Vec3f(1.0, 1.5, 0.3)
        assert ops["xformOp:rotateXYZ"] != Gf.Vec3f(10.0, 20.0, 30.0)
        assert Gf.IsClose(self._local(stage, "/C"), expected, 1.0e-5)

    def test_a_turn_past_y_90_keeps_the_form_of_the_old_angles(self):
        stage = self._stage(
            'def Xform "X" {\n'
            "  double3 xformOp:rotateXYZ = (0, 80, 0)\n"
            '  uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]\n'
            "}\n"
        )
        self._drag(stage, "/X", "rotate", (0.0, 1.0, 0.0), 20.0)
        assert dict(self._ops(stage, "/X"))["xformOp:rotateXYZ"] == pytest.approx((0.0, 100.0, 0.0))

    def test_move_and_scale_change_only_their_op(self):
        stage = self._stage(
            'def Xform "X" {\n'
            "  double3 xformOp:translate = (1, 2, 3)\n"
            "  float3 xformOp:rotateZYX = (10, 20, 30)\n"
            "  float3 xformOp:scale = (1, 1, 1)\n"
            '  uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateZYX", "xformOp:scale"]\n'
            "}\n"
        )
        move = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [5.0, 0.0, 0.0, 1.0]]
        self._drag(stage, "/X", "move", move)
        self._drag(stage, "/X", "scale", (1.0, 0.0, 0.0), 2.0)

        assert self._ops(stage, "/X") == [
            ("xformOp:translate", Gf.Vec3d(6.0, 2.0, 3.0)),
            ("xformOp:rotateZYX", Gf.Vec3f(10.0, 20.0, 30.0)),
            ("xformOp:scale", Gf.Vec3f(2.0, 1.0, 1.0)),
        ]

    def test_a_pivot_and_an_orient_op_stay_and_get_the_turn(self):
        stage = self._stage(
            'def Xform "P" {\n'
            "  float3 xformOp:translate = (1, 0, 0)\n"
            "  float3 xformOp:translate:pivot = (0, 1, 0)\n"
            "  quatf xformOp:orient = (1, 0, 0, 0)\n"
            "  float3 xformOp:scale = (2, 2, 2)\n"
            '  uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:translate:pivot", "xformOp:orient", '
            '"xformOp:scale", "!invert!xformOp:translate:pivot"]\n'
            "}\n"
        )
        expected = self._turned(self._local(stage, "/P"), (1.0, 0.0, 0.0), 25.0)

        self._drag(stage, "/P", "rotate", (1.0, 0.0, 0.0), 25.0)

        names = [name for name, _value in self._ops(stage, "/P")]
        assert names == [
            "xformOp:translate", "xformOp:translate:pivot", "xformOp:orient",
            "xformOp:scale", "!invert!xformOp:translate:pivot",
        ]
        assert dict(self._ops(stage, "/P"))["xformOp:translate:pivot"] == Gf.Vec3f(0.0, 1.0, 0.0)
        assert Gf.IsClose(self._local(stage, "/P"), expected, 1.0e-5)

    def test_a_missing_rotate_op_is_added_in_its_place_and_undo_removes_it(self):
        stage = self._stage(
            'def Xform "T" {\n'
            "  double3 xformOp:translate = (1, 2, 3)\n"
            "  float3 xformOp:scale = (1, 1, 1)\n"
            '  uniform token[] xformOpOrder = ["!resetXformStack!", "xformOp:translate", "xformOp:scale"]\n'
            "}\n"
        )
        layer = stage.GetRootLayer()
        before = layer.ExportToString()

        undo = self._drag(stage, "/T", "rotate", (0.0, 0.0, 1.0), 30.0)

        order = UsdGeom.Xformable(stage.GetPrimAtPath("/T")).GetXformOpOrderAttr().Get()
        assert list(order) == ["!resetXformStack!", "xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]
        assert dict(self._ops(stage, "/T"))["xformOp:rotateXYZ"] == pytest.approx((0.0, 0.0, 30.0))
        assert undo.undo() is True
        assert layer.ExportToString() == before

    def test_a_shear_falls_back_to_one_matrix_op_with_the_exact_matrix(self):
        from ovui_data_adapters.openusd import UsdTransformAdapter

        stage = self._stage(
            'def Xform "S" {\n'
            "  double3 xformOp:translate = (1, 2, 3)\n"
            '  uniform token[] xformOpOrder = ["xformOp:translate"]\n'
            "}\n"
        )
        sheared = [[1.0, 0.0, 0.0, 0.0], [0.3, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [1.0, 2.0, 3.0, 1.0]]

        UsdTransformAdapter(stage).set_local_transform("/S", sheared)

        assert [name for name, _value in self._ops(stage, "/S")] == ["xformOp:transform"]
        assert self._local(stage, "/S") == Gf.Matrix4d(*[v for row in sheared for v in row])

    @pytest.fixture
    def reports(self, monkeypatch):
        """The warnings of the drag model: (log, status bar) messages."""
        from ovui_widgets.common.error_reporter import ErrorReporter

        logged, shown = [], []
        monkeypatch.setattr(ErrorReporter, "log_warning", lambda _module, message: logged.append(message))
        monkeypatch.setattr(ErrorReporter, "show_warning", lambda message, *args, **kwargs: shown.append(message))
        return logged, shown

    def test_a_fallback_to_one_matrix_reports_the_prim_and_the_cause(self, reports):
        """The reviewer's scene of regression: a rotateX operation cannot hold
        a turn about Y, so the edit is stored as one matrix. The object gets
        the exact matrix, and the log and the status bar give the cause."""
        stage = self._stage(
            'def Cube "T" {\n'
            "  double3 xformOp:translate = (2, 0.5, 0)\n"
            "  float xformOp:rotateX = 0\n"
            "  float3 xformOp:scale = (1, 1, 1)\n"
            '  uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateX", "xformOp:scale"]\n'
            "}\n"
        )
        expected = self._turned(self._local(stage, "/T"), (0.0, 1.0, 0.0), 40.0)

        self._drag(stage, "/T", "rotate", (0.0, 1.0, 0.0), 40.0)

        assert [name for name, _value in self._ops(stage, "/T")] == ["xformOp:transform"]
        assert Gf.IsClose(self._local(stage, "/T"), expected, 1.0e-9)
        message = (
            "Move Prims: /T is stored as one matrix operation (xformOp:transform), because "
            "xformOp:rotateX turns only about X, and the edit turns about another axis"
        )
        assert reports == ([message], [message])

    def test_an_edit_that_the_operations_hold_reports_nothing(self, reports):
        stage = self._stage(
            'def Cube "C" {\n'
            "  double3 xformOp:translate = (2, 0.5, 0)\n"
            "  float3 xformOp:rotateXYZ = (0, 0, 0)\n"
            "  float3 xformOp:scale = (1, 0, 0)\n"
            '  uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]\n'
            "}\n"
        )
        # A flat object (scale 1, 0, 0) keeps its operations too: its Y and Z
        # axes have length 0, and the scale gizmo doubles X.
        self._drag(stage, "/C", "scale", (1.0, 0.0, 0.0), 2.0)

        assert self._ops(stage, "/C") == [
            ("xformOp:translate", Gf.Vec3d(2.0, 0.5, 0.0)),
            ("xformOp:rotateXYZ", Gf.Vec3f(0.0, 0.0, 0.0)),
            ("xformOp:scale", Gf.Vec3f(2.0, 0.0, 0.0)),
        ]
        assert reports == ([], [])

    def test_a_prim_with_one_matrix_operation_keeps_it_and_reports_nothing(self, reports):
        stage = self._stage(
            'def Xform "M" {\n'
            "  matrix4d xformOp:transform:pose = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))\n"
            '  uniform token[] xformOpOrder = ["!resetXformStack!", "xformOp:transform:pose"]\n'
            "}\n"
        )
        move = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [5.0, 0.0, 0.0, 1.0]]

        self._drag(stage, "/M", "move", move)

        order = UsdGeom.Xformable(stage.GetPrimAtPath("/M")).GetXformOpOrderAttr().Get()
        assert list(order) == ["!resetXformStack!", "xformOp:transform:pose"]
        assert self._local(stage, "/M").ExtractTranslation() == Gf.Vec3d(5.0, 0.0, 0.0)
        assert reports == ([], [])

    def test_a_turn_of_an_object_far_from_the_origin_is_written(self, reports):
        """A large move value must not hide the turn: the rotate drag of an
        object at X 1e10 changes its rotate operation, as near the origin."""
        stage = self._stage(
            'def Xform "Far" {\n'
            "  double3 xformOp:translate = (10000000000, 0, 0)\n"
            "  double3 xformOp:rotateXYZ = (0, 0, 0)\n"
            "  double3 xformOp:scale = (1, 1, 1)\n"
            '  uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]\n'
            "}\n"
        )

        self._drag(stage, "/Far", "rotate", (0.0, 1.0, 0.0), 64.0)

        ops = dict(self._ops(stage, "/Far"))
        assert list(ops) == ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]
        assert ops["xformOp:translate"] == Gf.Vec3d(1.0e10, 0.0, 0.0)
        assert ops["xformOp:rotateXYZ"] == pytest.approx((0.0, 64.0, 0.0))
        assert ops["xformOp:scale"] == Gf.Vec3d(1.0, 1.0, 1.0)
        assert reports == ([], [])

    def test_a_turn_that_the_operations_of_a_far_object_cannot_hold_is_kept_and_reported(self, reports):
        """Far from the origin, a turn about Y that a rotateX operation cannot
        hold still gives the exact turn, and the report names the operation
        and the cause."""
        stage = self._stage(
            'def Xform "Far" {\n'
            "  double3 xformOp:translate = (10000000000, 0, 0)\n"
            "  float xformOp:rotateX = 0\n"
            '  uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateX"]\n'
            "}\n"
        )
        expected = self._turned(self._local(stage, "/Far"), (0.0, 1.0, 0.0), 64.0)

        self._drag(stage, "/Far", "rotate", (0.0, 1.0, 0.0), 64.0)

        local = self._local(stage, "/Far")
        for row in range(3):
            assert Gf.IsClose(local.GetRow(row), expected.GetRow(row), 1.0e-9)
        assert local.ExtractTranslation() == Gf.Vec3d(1.0e10, 0.0, 0.0)
        message = (
            "Move Prims: /Far is stored as one matrix operation (xformOp:transform), because "
            "xformOp:rotateX turns only about X, and the edit turns about another axis"
        )
        assert reports == ([message], [message])

    def test_a_move_changes_only_the_first_translate_op_when_other_ops_follow_the_scale(self, reports):
        """The op stack of Robot_Arm_Export in the Factory scene: unit
        operations follow the scale. A move writes only xformOp:translate."""
        stage = self._stage(
            'def Xform "Arm" {\n'
            "  double3 xformOp:translate = (194.726026961988, -73.67554528828711, -0.21110696449771638)\n"
            "  float3 xformOp:rotateXYZ = (0, 0, 0)\n"
            "  float3 xformOp:scale = (1, 1, 1)\n"
            "  double xformOp:rotateX:unitsResolve = 0\n"
            "  double3 xformOp:scale:unitsResolve = (2, 2, 2)\n"
            '  uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale", '
            '"xformOp:rotateX:unitsResolve", "xformOp:scale:unitsResolve"]\n'
            "}\n"
        )
        before = self._ops(stage, "/Arm")
        move = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 165.5, 1.0]]

        self._drag(stage, "/Arm", "move", move)

        after = self._ops(stage, "/Arm")
        assert [name for name, _value in after] == [name for name, _value in before]
        assert after[1:] == before[1:]
        assert after[0][1] == pytest.approx((194.726026961988, -73.67554528828711, -0.21110696449771638 + 165.5))
        assert reports == ([], [])

    def test_a_small_move_of_an_object_far_along_another_axis_is_written(self, reports):
        """A large X must not hide a small move along Z: the move writes Z,
        and the other channels and operations keep their exact values."""
        stage = self._stage(
            'def Xform "Arm" {\n'
            "  double3 xformOp:translate = (10000000000, -73.67554528828711, 0)\n"
            "  float3 xformOp:rotateXYZ = (0, 0, 0)\n"
            "  float3 xformOp:scale = (1, 1, 1)\n"
            "  double xformOp:rotateX:unitsResolve = 0\n"
            "  double3 xformOp:scale:unitsResolve = (2, 2, 2)\n"
            '  uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale", '
            '"xformOp:rotateX:unitsResolve", "xformOp:scale:unitsResolve"]\n'
            "}\n"
        )
        before = self._ops(stage, "/Arm")
        move = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.302, 1.0]]

        self._drag(stage, "/Arm", "move", move)

        after = self._ops(stage, "/Arm")
        assert after[1:] == before[1:]
        assert after[0] == ("xformOp:translate", Gf.Vec3d(1.0e10, -73.67554528828711, 0.302))
        assert reports == ([], [])

    def test_a_small_move_along_the_axis_of_a_large_move_value_is_written(self, reports):
        """At X 1e10 a double keeps a change of about 0.000002: a move of +5
        along X writes X, and Y and Z keep their exact values."""
        stage = self._stage(
            'def Xform "Far" {\n'
            "  double3 xformOp:translate = (10000000000, 2, 3)\n"
            '  uniform token[] xformOpOrder = ["xformOp:translate"]\n'
            "}\n"
        )
        move = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [5.0, 0.0, 0.0, 1.0]]

        self._drag(stage, "/Far", "move", move)

        assert self._ops(stage, "/Far") == [("xformOp:translate", Gf.Vec3d(1.0e10 + 5.0, 2.0, 3.0))]
        assert reports == ([], [])

    def test_a_move_that_a_float_operation_cannot_hold_is_kept_and_reported(self, reports):
        """A float keeps steps of 1024 at 1e10, so it cannot hold a move of
        +5: the object gets the exact matrix, and the report names the
        operation and the cause."""
        stage = self._stage(
            'def Xform "Far" {\n'
            "  float3 xformOp:translate = (10000000000, 2, 3)\n"
            '  uniform token[] xformOpOrder = ["xformOp:translate"]\n'
            "}\n"
        )
        move = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [5.0, 0.0, 0.0, 1.0]]
        start = self._local(stage, "/Far").ExtractTranslation()

        self._drag(stage, "/Far", "move", move)

        assert self._local(stage, "/Far").ExtractTranslation() == start + Gf.Vec3d(5.0, 0.0, 0.0)
        message = (
            "Move Prims: /Far is stored as one matrix operation (xformOp:transform), because "
            "xformOp:translate keeps float values, which cannot hold this edit"
        )
        assert reports == ([message], [message])

    def test_a_small_turn_of_an_orient_operation_is_written(self, reports):
        """A turn of 0.002 degrees changes the orient value, as a large turn does."""
        stage = self._stage(
            'def Xform "O" {\n'
            "  quatd xformOp:orient = (1, 0, 0, 0)\n"
            '  uniform token[] xformOpOrder = ["xformOp:orient"]\n'
            "}\n"
        )
        expected = self._turned(self._local(stage, "/O"), (1.0, 0.0, 0.0), 0.002)

        self._drag(stage, "/O", "rotate", (1.0, 0.0, 0.0), 0.002)

        assert [name for name, _value in self._ops(stage, "/O")] == ["xformOp:orient"]
        assert Gf.IsClose(self._local(stage, "/O"), expected, 1.0e-9)
        assert reports == ([], [])

    def test_a_move_of_float_operations_near_the_origin_keeps_them(self, reports):
        """The gizmo math leaves rounding noise in the channels that a move
        does not change; that noise must not make a float operation refuse
        the move. Only X changes, and nothing is reported."""
        stage = self._stage(
            'def Cube "FloatCube" {\n'
            "  float3 xformOp:translate = (-1.08, 116.87, 246.19)\n"
            "  float3 xformOp:rotateXYZ = (-76, -7, 11)\n"
            "  float3 xformOp:scale = (1, 1, 1)\n"
            '  uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]\n'
            "}\n"
        )
        before = self._ops(stage, "/FloatCube")
        move = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [77.0, 0.0, 0.0, 1.0]]

        self._drag(stage, "/FloatCube", "move", move)

        after = self._ops(stage, "/FloatCube")
        assert after[1:] == before[1:]
        assert after[0] == ("xformOp:translate", Gf.Vec3f(-1.08 + 77.0, 116.87, 246.19))
        assert reports == ([], [])

    def test_a_scale_of_a_float_pivot_stack_near_the_origin_keeps_the_operations(self, reports):
        """A scale of a stack with a pivot moves the translate by a little; a
        float holds that, so the operations stay and nothing is reported."""
        stage = self._stage(
            'def Xform "PivotCube" {\n'
            "  float3 xformOp:translate = (246.19, -1.08, 116.87)\n"
            "  float3 xformOp:translate:pivot = (1.5, -2.25, 0.75)\n"
            "  float3 xformOp:rotateXYZ = (-76, -7, 11)\n"
            "  float3 xformOp:scale = (1, 1, 1)\n"
            '  uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:translate:pivot", "xformOp:rotateXYZ", '
            '"xformOp:scale", "!invert!xformOp:translate:pivot"]\n'
            "}\n"
        )
        names = [name for name, _value in self._ops(stage, "/PivotCube")]

        self._drag(stage, "/PivotCube", "scale", (1.0, 0.0, 0.0), 1.0001)

        ops = dict(self._ops(stage, "/PivotCube"))
        assert list(ops) == names
        assert ops["xformOp:scale"][0] == pytest.approx(1.0001, abs=1.0e-6)
        assert ops["xformOp:translate:pivot"] == Gf.Vec3f(1.5, -2.25, 0.75)
        assert reports == ([], [])

    def test_a_scale_drag_is_kept_when_another_scale_channel_is_large(self, reports):
        """Scale X 1e10 must not hide a scale of Z: the Z scale is written."""
        stage = self._stage(
            'def Cube "FloatScale" {\n'
            "  double3 xformOp:translate = (0, 0, 0)\n"
            "  float3 xformOp:rotateXYZ = (0, 10, 0)\n"
            "  float3 xformOp:scale = (10000000000, 2, 0.5)\n"
            '  uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]\n'
            "}\n"
        )

        self._drag(stage, "/FloatScale", "scale", (0.0, 0.0, 1.0), 1.232)

        ops = dict(self._ops(stage, "/FloatScale"))
        assert ops["xformOp:translate"] == Gf.Vec3d(0.0, 0.0, 0.0)
        assert ops["xformOp:rotateXYZ"] == Gf.Vec3f(0.0, 10.0, 0.0)
        assert ops["xformOp:scale"] == Gf.Vec3f(1.0e10, 2.0, 0.5 * 1.232)
        assert reports == ([], [])

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The transform gizmo through the real gesture dispatch.

A drag on a handle of :class:`TransformManipulator` moves the selected prim. These tests drive the real manipulator, the
real ``PrimTransformModel``, the real gizmo gestures and the real gesture dispatch with injected pointer input, and a
transform adapter whose world transform is the local one times the parents' (the arithmetic of a USD stage), so the
numbers of the pivot are rounded as they are in the application. Like ``ViewportWidget``, the test calls
``refresh_transform`` after each frame (every frame, or every second or third). They check:

* a drag gives one ``on_changed`` call for each pointer movement, none at the press and none while the pointer is held
  still, for a prim with and without parents, and for parents that turn and scale (the pivot of such a prim is rounded
  differently by two ways of computing it, and a pivot that changes in the last digit is a write that the gesture reports);
* the prim ends where the pointer took it, measured from the pixel of the press to the pixel of the release (the first
  movement is not lost);
* the gizmo keeps its size on the screen during the drag: its scale follows the distance, and the change of the scale is
  not a change that the gesture reports;
* the rotate and the scale gizmo, which never had the duplicate, still give one call for each pointer movement, and the
  prim ends rotated or scaled by what the pointer did from the press.
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from unittest.mock import MagicMock

import omni.ui as ui
import pytest
from omni.ui import _ui, standalone
from omni.ui_scene import scene as sc

from ovui_widgets.common.testing.mock_transform import MockTransformAdapter
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.viewport import rotate_gizmo, scale_gizmo, translate_gizmo
from ovui_widgets.viewport.prim_transform_model import PrimTransformModel, _invert_matrix_4x4
from ovui_widgets.viewport.transform_manipulator import (
    TOOL_ROTATE,
    TOOL_SCALE,
    TOOL_TRANSLATE,
    TransformManipulator,
)

_PROJ = [0.5, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 2e-7, 0, 0, 0, 1, 1]
_WINDOW_FLAGS = (
    ui.WINDOW_FLAGS_NO_SCROLLBAR
    | ui.WINDOW_FLAGS_NO_TITLE_BAR
    | ui.WINDOW_FLAGS_NO_RESIZE
    | ui.WINDOW_FLAGS_NO_MOVE
)
_SIZE = 2.0  # the world size of the gizmo
_STEPS = 12
_HOLD = 3
_PATH = "/World/Parent/Cube"

# The parent of the prim. Its translation has digits that no binary number holds, so that the world transform that the
# adapter gives is rounded.
_PARENT = [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [12.3456, -4.5678, 0.001, 1.0]]
_IDENTITY = [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]


def _row_major_product(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _rotation(axis, angle):
    c, s = math.cos(angle), math.sin(angle)
    m = [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]
    a, b = {"x": (1, 2), "y": (2, 0), "z": (0, 1)}[axis]
    m[a][a], m[a][b], m[b][a], m[b][b] = c, s, -s, c
    return m


def _scaling(x, y, z):
    return [[x, 0, 0, 0], [0, y, 0, 0], [0, 0, z, 0], [0, 0, 0, 1.0]]


def _translated(m, x, y, z):
    m = [row[:] for row in m]
    m[3][0], m[3][1], m[3][2] = x, y, z
    return m


# A parent that is turned about X and scaled along Y and Z: the world X axis is still the X axis of the parent, so a drag
# on the X handle is exact in the world, but every number of the world transform of the prim is rounded by the turn.
_PARENT_TURNED_X = _translated(_row_major_product(_scaling(1.0, 1.7, 0.6), _rotation("x", 0.6)), 12.3456, -4.5678, 0.001)
# A parent that is turned about all axes and scaled differently along each: the world X axis is not an axis of the parent,
# so the model must turn the world delta of the gizmo into the frame of the parent.
_PARENT_GENERAL = _translated(
    _row_major_product(_row_major_product(_scaling(1.3, 0.7, 2.1), _rotation("z", 0.7)), _rotation("y", -0.4)), -7.77, 3.21, 0.05
)


class _ParentedAdapter(MockTransformAdapter):
    """The world transform is the local one times the world transform of the parent, as ``UsdTransformAdapter`` gives it."""

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    def get_world_transform(self, path):
        local = self.get_local_transform(path)
        return [[sum(local[i][k] * self.parent[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


@contextmanager
def _no_change_notifications():
    yield


class _Drag:
    """A real manipulator in a real scene view, and a pointer that is injected into the input queue."""

    def __init__(self, parent, refresh_every, distance_size, tool=TOOL_TRANSLATE):
        self.transform = _ParentedAdapter(parent)
        # The local transform that puts the world position of the prim at about (0.31, -0.17, 0.2): the position in the
        # frame of the parent.
        inverse = _invert_matrix_4x4(parent)
        local = _row_major_product(_translated(_IDENTITY, 0.31, -0.17, 0.2), inverse)
        local[0:3] = [row[:] for row in _IDENTITY[0:3]]
        local[3][3] = 1.0
        self.transform.set_local_transform(_PATH, local)
        stage = MagicMock()
        stage.suppress_change_notifications.side_effect = lambda: _no_change_notifications()
        self.model = PrimTransformModel(self.transform, stage, UndoManager())
        self.model.set_selection([_PATH])
        self.base = self.model.get_pivot_world()
        self.refresh_every = refresh_every
        self.frame = 0
        self.scales = []
        self.window = ui.Window(
            "_test_translate_gizmo_dispatch", width=512, height=256, flags=_WINDOW_FLAGS, position_x=0, position_y=0
        )
        with self.window.frame:
            self.scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, sc.Matrix44.get_translation_matrix(-self.base[0], -self.base[1], -10)),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            with self.scene_view.scene:
                self.manipulator = TransformManipulator(
                    self.model,
                    tool=tool,
                    pivot_fn=self.model.get_pivot_world,
                    # The view of this scene looks along Z, as the viewport tells the manipulator for such a camera: the Z
                    # shaft has no length on the screen, so it is built without gestures and can never take a press.
                    view_dir_fn=lambda _pivot: (0.0, 0.0, -1.0),
                    # With a perspective camera the size that keeps the gizmo the same on the screen follows the distance
                    # to the camera, so it changes as the pivot moves.
                    size_fn=(lambda: _SIZE + 0.05 * self.model.get_pivot_world()[0] + 0.01 * self.model.get_pivot_world()[1])
                    if distance_size
                    else (lambda: _SIZE),
                )

    def tick(self, events=()):
        """The pointer events of a frame, the frame, and the viewport's update of the gizmo (as ViewportWidget does)."""
        for kind, *args in events:
            if kind == "move":
                _ui._inject_mouse_move(*self.pixel(args[0]))
            elif kind == "down":
                _ui._inject_mouse_button(0, True)
            else:
                _ui._inject_mouse_button(0, False)
        standalone._tick_one_frame()
        self.frame += 1
        if self.frame % self.refresh_every == 0:
            self.manipulator.refresh_transform()
        scale_transform = self.manipulator._scale_transform
        if scale_transform is not None:
            self.scales.append(scale_transform.transform[0])

    def pixel(self, ndc):
        view = self.scene_view
        return (
            view.screen_position_x + (ndc[0] + 1) / 2 * view.computed_width,
            view.screen_position_y + (1 - ndc[1]) / 2 * view.computed_height,
        )

    def ndc_of(self, x, y):
        """The NDC of the world point (x, y) on the plane z = 0 (the view is linear there)."""
        ray = self.scene_view.get_ray_from_ndc
        o0, _ = ray(sc.Vector2(0.0, 0.0))
        ox, _ = ray(sc.Vector2(1.0, 0.0))
        oy, _ = ray(sc.Vector2(0.0, 1.0))
        return (x - o0[0]) / (ox[0] - o0[0]), (y - o0[1]) / (oy[1] - o0[1])

    def snap(self, ndc):
        """The NDC of the whole pixel nearest to ``ndc``: the pointer position is in whole pixels."""
        view = self.scene_view
        x, y = (round(v) for v in self.pixel(ndc))
        return (
            2 * (x - view.screen_position_x) / view.computed_width - 1,
            1 - 2 * (y - view.screen_position_y) / view.computed_height,
        )

    def world_point(self, ndc):
        """Where the ray of the pointer meets the plane z = the pivot's z (the view looks along z)."""
        origin, direction = self.scene_view.get_ray_from_ndc(sc.Vector2(*ndc))
        t = (self.base[2] - origin[2]) / direction[2]
        return tuple(origin[i] + t * direction[i] for i in range(3))

    def translation(self):
        matrix = self.transform.get_world_transform(_PATH)
        return matrix[3][0], matrix[3][1], matrix[3][2]

    def destroy(self):
        self.manipulator.destroy()
        self.window.destroy()


@pytest.fixture
def counted_calls(monkeypatch):
    """Every call of ``on_changed`` of a translate, rotate or scale gesture, with its axis."""
    calls = []
    for cls in (translate_gizmo.PrimTranslateChangedGesture, rotate_gizmo.PrimRotateChangedGesture, scale_gizmo.PrimScaleChangedGesture):
        original = cls._on_changed

        def counting(gesture, sender=None, original=original):
            calls.append(tuple(getattr(gesture, "axis_mask", None) or gesture.axis))
            return original(gesture, sender)

        monkeypatch.setattr(cls, "_on_changed", counting)
    return calls


def _drag(handle, parent, refresh_every, distance_size, calls, monkeypatch, still_frames=30, tool=TOOL_TRANSLATE):
    """Press on the handle, move the pointer along it in steps with frames of a still pointer in between, hold the pointer
    still for a while, release."""
    from tests._vulkan_device import use_headless_vulkan

    use_headless_vulkan(monkeypatch)
    standalone.init("_test_translate_gizmo_dispatch", 512, 256)
    drag = _Drag(parent, refresh_every, distance_size, tool)
    try:
        for _ in range(6):
            drag.tick()
        base = drag.base
        scale = drag.manipulator._resolve_scale()
        length = translate_gizmo.SHAFT_LENGTH * scale
        if handle == "z_ring":
            # The ring of the rotate gizmo that is in the XY plane: the pointer goes around the pivot on it.
            radius = rotate_gizmo.RING_RADIUS * scale
            path = [(base[0] + radius * math.cos(0.5 + 0.1 * i), base[1] + radius * math.sin(0.5 + 0.1 * i)) for i in range(_STEPS + 1)]
        elif handle == "x_shaft":
            path = [(base[0] + length * (0.3 + 0.04 * i), base[1]) for i in range(_STEPS + 1)]
        elif handle == "y_shaft":
            path = [(base[0], base[1] + length * (0.3 + 0.04 * i)) for i in range(_STEPS + 1)]
        else:
            # The XY plane handle: its centre is (0.25, 0.25) of the gizmo (see translate_gizmo._PLANES).
            plane = next(p for p in translate_gizmo._PLANES if p[0] == "xy")
            centre = plane[3]
            path = [(base[0] + scale * centre[0] + 0.02 * i, base[1] + scale * centre[1] + 0.015 * i) for i in range(_STEPS + 1)]
        positions = [drag.snap(drag.ndc_of(*point)) for point in path]
        drag.tick([("move", positions[0])])
        drag.tick([("move", positions[0])])
        press_start = len(calls)
        drag.tick([("move", positions[0]), ("down",)])
        # The pointer is held on the press point for some frames before it moves: the press is not a change of the shape.
        for _ in range(_HOLD):
            drag.tick()
        press_calls = len(calls) - press_start
        before = len(calls)
        per_move = []
        for position in positions[1:]:
            start = len(calls)
            drag.tick([("move", position)])
            first = len(calls) - start
            for _ in range(_HOLD):
                drag.tick()
            per_move.append((first, len(calls) - start))
        total = len(calls) - before
        scales_during = list(drag.scales)
        still_start = len(calls)
        for _ in range(still_frames):
            drag.tick()
        still_calls = len(calls) - still_start
        drag.tick([("up",)])
        drag.tick()
        moved = tuple(b - a for a, b in zip(base, drag.translation()))
        local = drag.transform.get_local_transform(_PATH)
        # Where the pointer took the prim: from the pixel of the press to the pixel of the release, on the handle.
        press, release = drag.world_point(positions[0]), drag.world_point(positions[-1])
        pointer = tuple(r - p for p, r in zip(press, release))
        return dict(
            local=local, base=base, scale=scale, positions=[drag.world_point(p) for p in (positions[0], positions[-1])],
            press_calls=press_calls, total=total, per_move=per_move, still_calls=still_calls, moved=moved, pointer=pointer,
            scales_during=scales_during, scale_after=drag.scales[-1], expected_scale=drag.manipulator._resolve_scale(),
            axes=sorted(set(calls)),
        )
    finally:
        drag.destroy()
        standalone.shutdown()


@pytest.mark.parametrize("distance_size", [False, True], ids=["fixed_size", "distance_size"])
@pytest.mark.parametrize("refresh_every", [1, 2, 3])
@pytest.mark.parametrize("handle", ["x_shaft", "y_shaft", "xy_plane"])
@pytest.mark.parametrize(
    "parent", [_PARENT, _IDENTITY, _PARENT_TURNED_X, _PARENT_GENERAL], ids=["parented", "no_parent", "turned_scaled_parent", "general_parent"]
)
def test_gizmo_drag_gives_one_call_for_each_pointer_movement(parent, handle, refresh_every, distance_size, counted_calls, monkeypatch):
    result = _drag(handle, parent, refresh_every, distance_size, counted_calls, monkeypatch)
    expected_axes = {"x_shaft": [(1.0, 0.0, 0.0)], "y_shaft": [(0.0, 1.0, 0.0)], "xy_plane": [(1.0, 1.0, 0.0)]}[handle]
    assert result["axes"] == expected_axes, "the drag must be on the handle that the pointer pressed"
    assert result["press_calls"] == 0, "the press, and the frames of the pointer held on the press point, give no call"
    assert result["per_move"] == [(1, 1)] * _STEPS, f"one call in the frame of each movement, none after it: {result['per_move']}"
    assert result["total"] == _STEPS
    assert result["still_calls"] == 0, "no call while the pointer is held still"


@pytest.mark.parametrize("refresh_every", [1, 3])
@pytest.mark.parametrize("handle", ["x_shaft", "y_shaft", "xy_plane"])
@pytest.mark.parametrize("parent", [_PARENT, _IDENTITY], ids=["parented", "no_parent"])
def test_prim_ends_where_the_pointer_took_it_from_the_press(parent, handle, refresh_every, counted_calls, monkeypatch):
    result = _drag(handle, parent, refresh_every, False, counted_calls, monkeypatch)
    moved, pointer = result["moved"], result["pointer"]
    if handle == "x_shaft":
        expected = (pointer[0], 0.0, 0.0)
    elif handle == "y_shaft":
        expected = (0.0, pointer[1], 0.0)
    else:
        expected = (pointer[0], pointer[1], 0.0)
    for axis in range(3):
        assert moved[axis] == pytest.approx(expected[axis], abs=1e-9), f"axis {axis}: moved {moved}, pointer {pointer}"
    # The pointer moved a distance that is much more than the first step: the first step is in the sum.
    assert abs(sum(abs(v) for v in expected)) > 0.1


@pytest.mark.parametrize("refresh_every", [1, 3])
def test_prim_of_a_turned_scaled_parent_ends_where_the_pointer_took_it_along_x(refresh_every, counted_calls, monkeypatch):
    result = _drag("x_shaft", _PARENT_TURNED_X, refresh_every, False, counted_calls, monkeypatch)
    moved, pointer = result["moved"], result["pointer"]
    assert abs(pointer[0]) > 0.1
    assert moved[0] == pytest.approx(pointer[0], abs=1e-9)
    assert moved[1] == pytest.approx(0.0, abs=1e-9)
    assert moved[2] == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("refresh_every", [1, 3])
def test_prim_of_a_general_parent_ends_where_the_model_moves_it(refresh_every, counted_calls, monkeypatch):
    """The gizmo moves along the world axes, so the prim moves by the pointer movement along world X also under a parent
    that turns and scales; the drag must neither lose nor add a movement on the way."""
    result = _drag("x_shaft", _PARENT_GENERAL, refresh_every, False, counted_calls, monkeypatch)
    delta = result["pointer"][0]
    assert abs(delta) > 0.1
    expected = (delta, 0.0, 0.0)
    for axis in range(3):
        assert result["moved"][axis] == pytest.approx(expected[axis], abs=1e-9)


@pytest.mark.parametrize("parent", [_PARENT, _IDENTITY], ids=["parented", "no_parent"])
def test_gizmo_keeps_its_size_on_the_screen_during_the_drag(parent, counted_calls, monkeypatch):
    result = _drag("x_shaft", parent, 1, True, counted_calls, monkeypatch)
    during = result["scales_during"][-(_STEPS * (_HOLD + 1)) :]
    # The scale follows the distance in every step, and it is where it ends after the release: no jump back.
    assert len(set(during)) >= _STEPS // 2, f"the scale must change during the drag: {sorted(set(during))}"
    assert during[-1] == result["expected_scale"]
    assert result["scale_after"] == result["expected_scale"]
    # The change of the scale is not a change that the gesture reports.
    assert result["per_move"] == [(1, 1)] * _STEPS
    assert result["still_calls"] == 0



@pytest.mark.parametrize("refresh_every", [1, 3])
@pytest.mark.parametrize("parent", [_PARENT, _IDENTITY], ids=["parented", "no_parent"])
def test_rotate_gizmo_drag_gives_one_call_for_each_pointer_movement_and_turns_by_the_pointer(parent, refresh_every, counted_calls, monkeypatch):
    result = _drag("z_ring", parent, refresh_every, False, counted_calls, monkeypatch, tool=TOOL_ROTATE)
    assert result["axes"] == [(0.0, 0.0, 1.0)]
    assert result["per_move"] == [(1, 1)] * _STEPS, f"one call in the frame of each movement, none after it: {result['per_move']}"
    assert result["still_calls"] == 0
    # The prim turns by the angle that the pointer went around the pivot, from the press to the release.
    press, release = result["positions"]
    base = result["base"]
    expected = math.atan2(release[1] - base[1], release[0] - base[0]) - math.atan2(press[1] - base[1], press[0] - base[0])
    local = result["local"]
    turned = math.atan2(local[0][1], local[0][0])
    assert abs(turned) == pytest.approx(abs(expected), abs=1e-9)


@pytest.mark.parametrize("refresh_every", [1, 3])
@pytest.mark.parametrize("parent", [_PARENT, _IDENTITY], ids=["parented", "no_parent"])
def test_scale_gizmo_drag_gives_one_call_for_each_pointer_movement_and_scales_by_the_pointer(parent, refresh_every, counted_calls, monkeypatch):
    result = _drag("x_shaft", parent, refresh_every, False, counted_calls, monkeypatch, tool=TOOL_SCALE)
    assert result["axes"] == [(1.0, 0.0, 0.0)]
    assert result["per_move"] == [(1, 1)] * _STEPS, f"one call in the frame of each movement, none after it: {result['per_move']}"
    assert result["still_calls"] == 0
    # The prim is scaled along X by one plus the distance that the pointer went along the handle, in units of its length.
    press, release = result["positions"]
    expected = 1.0 + (release[0] - press[0]) / (scale_gizmo.SHAFT_LENGTH * result["scale"])
    assert result["local"][0][0] == pytest.approx(expected, abs=1e-9)

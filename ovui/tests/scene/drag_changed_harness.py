# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# A harness for the tests of DragGesture.on_changed delivery.
#
# All pointer input goes through the input queue of the standalone backend (_inject_mouse_move and
# _inject_mouse_button) and the default gesture manager, so a test runs the real dispatch: events are queued, a frame is
# drawn, the scene intersects the shape with the ray of the pointer, and the gesture decides. The expected values come
# from the ray of the SceneView and from plain math, not from the payload that is tested.
#
# A test says in each frame what it does: the pointer events to queue, and the code that changes the scene before the
# frame is drawn (``act``, ``later``), as code other than the callback does. The harness counts the calls of on_changed
# in each frame, so a test states exactly which frames have a call.

from contextlib import contextmanager
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import omni.ui as ui
from omni.ui import _ui
from omni.ui.testing import next_frame
from omni.ui_scene import scene as sc
from test_base import OmniUiTest

PROJ = [0.5, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 2e-7, 0, 0, 0, 1, 1]

# A window that cannot move: ImGui would otherwise drag the window with the pointer.
WINDOW_FLAGS = (
    ui.WINDOW_FLAGS_NO_SCROLLBAR
    | ui.WINDOW_FLAGS_NO_TITLE_BAR
    | ui.WINDOW_FLAGS_NO_RESIZE
    | ui.WINDOW_FLAGS_NO_MOVE
)

MOVE, DOWN, UP = "move", "down", "up"


def translation(x, y, z):
    return sc.Matrix44.get_translation_matrix(x, y, z)


def units(x, count=1):
    """``count`` units of the last digit of the double ``x``."""
    return count * math.ulp(x)


def payload_values(payload):
    """The values of a payload that a consumer reads, as plain Python numbers."""
    names = ("moved", "item_closest_point", "ray_closest_point", "line_closest_point")
    values = {name: tuple(getattr(payload, name)) for name in names if hasattr(payload, name)}
    for name in ("angle", "moved_angle", "distance_to_center", "moved_distance_to_center", "s", "t", "moved_s", "moved_t"):
        if hasattr(payload, name):
            values[name] = float(getattr(payload, name))
    return values


class Drag:
    """What a drag did, frame by frame."""

    def __init__(self):
        # The number of calls in each frame that had pointer movements, and in each frame that had none.
        self.moves = []
        self.holds = []
        # Every call: the values of the payload that a consumer reads.
        self.calls = []
        # Whether the points of the payload of the shape (the item and the ray) changed in each of the frames without
        # pointer input, bit for bit.
        self.hold_changes = []

    @property
    def extra(self):
        """The calls in the frames without pointer input."""
        return sum(self.holds)


class DragHarness(OmniUiTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None
        self.calls = []
        self._frame_calls = 0
        self.began = 0
        self.ended = 0
        self._frame = 0
        self._scheduled = []
        self._down = False

    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    @contextmanager
    def case(self, **parameters):
        """A failure inside a loop over cases names the case in its message."""
        try:
            yield
        except AssertionError as error:
            raise AssertionError(f"{parameters}: {error}") from None

    async def end(self):
        """Destroy the window of a scenario: the next scenario of the same test starts from a clean scene."""
        if self._down:
            await self.release()
        await self.finalize_test_no_image()
        self.calls = []
        self._scheduled = []
        self.began = self.ended = 0

    # ------------------------------------------------------------------
    # Scene
    # ------------------------------------------------------------------

    async def build(
        self,
        make_shape,
        proj=PROJ,
        base=(0.0, 0.0, 0.0),
        parents=(),
        on_changed=None,
        on_began=None,
        on_ended=None,
        check_mouse_moved=None,
        gesture=None,
    ):
        """Create the window and the scene.

        ``make_shape(gesture)`` makes the shape. ``parents`` are the matrices of the Transforms above the shape, the
        outermost first (``self.parents`` has them); ``self.transform`` is the innermost, or one at the origin if there is
        none. The camera looks at ``base``. ``gesture`` is a DragGesture to use instead of the one that the harness makes.
        """
        window = await self.create_test_window(width=512, height=256, window_flags=WINDOW_FLAGS)
        self.parents = []
        with window.frame:
            self.scene_view = sc.SceneView(
                sc.CameraModel(proj, translation(-base[0], -base[1], -10)),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            with self.scene_view.scene:

                def recording(shape):
                    self._frame_calls += 1
                    self.calls.append(payload_values(shape.gesture_payload))
                    if on_changed:
                        on_changed(shape)

                def began(shape):
                    self.began += 1
                    if on_began:
                        on_began(shape)

                def ended(shape):
                    self.ended += 1
                    if on_ended:
                        on_ended(shape)

                kwargs = {} if check_mouse_moved is None else {"check_mouse_moved": check_mouse_moved}
                self.gesture = gesture or sc.DragGesture(
                    on_began_fn=began, on_changed_fn=recording, on_ended_fn=ended, **kwargs
                )
                self._nest(list(parents) or [sc.Matrix44()], make_shape)
        self.transform = self.parents[-1]
        self.base = base
        await self.settle()

    def _nest(self, matrices, make_shape):
        transform = sc.Transform(transform=matrices[0])
        self.parents.append(transform)
        with transform:
            if len(matrices) > 1:
                self._nest(matrices[1:], make_shape)
            else:
                self.shape = make_shape(self.gesture)

    async def settle(self, frames=6):
        for _ in range(frames):
            await next_frame()
        self._frame_calls = 0

    # ------------------------------------------------------------------
    # Pointer
    # ------------------------------------------------------------------

    def pixel(self, ndc):
        view = self.scene_view
        x = view.screen_position_x + (ndc[0] + 1) / 2 * view.computed_width
        y = view.screen_position_y + (1 - ndc[1]) / 2 * view.computed_height
        return x, y

    def snap(self, ndc):
        """The NDC of the whole pixel nearest to ``ndc``: the pointer position is in whole pixels."""
        view = self.scene_view
        x, y = self.pixel(ndc)
        x, y = round(x), round(y)
        return (
            2 * (x - view.screen_position_x) / view.computed_width - 1,
            1 - 2 * (y - view.screen_position_y) / view.computed_height,
        )

    def ray(self, ndc):
        return self.scene_view.get_ray_from_ndc(sc.Vector2(*ndc))

    def ndc_of(self, x, y):
        """The NDC of the world point (x, y) on the plane z = 0 (the view is linear there)."""
        o0, _ = self.ray((0.0, 0.0))
        ox1, _ = self.ray((1.0, 0.0))
        oy1, _ = self.ray((0.0, 1.0))
        return (x - o0[0]) / (ox1[0] - o0[0]), (y - o0[1]) / (oy1[1] - o0[1])

    def points(self):
        """The points of the payload of the shape now, bit for bit: what decides whether a frame is a change."""
        payload = self.shape.gesture_payload
        return tuple(payload.item_closest_point), tuple(payload.ray_closest_point)

    def later(self, frames, function):
        """Run ``function`` before the frame that is ``frames`` after the current one is drawn: code other than the callback
        that applies what the callback read, as an application does in its own update."""
        self._scheduled.append((self._frame + frames, function))

    async def step(self, events=(), act=None):
        """Queue the events, run the scheduled code and ``act``, draw a frame. Returns the number of calls of on_changed
        in that frame."""
        self._frame += 1
        for kind, *args in events:
            if kind == MOVE:
                _ui._inject_mouse_move(*self.pixel(args[0]))
            elif kind == DOWN:
                _ui._inject_mouse_button(0, True)
                self._down = True
            elif kind == UP:
                _ui._inject_mouse_button(0, False)
                self._down = False
        due = [function for frame, function in self._scheduled if frame <= self._frame]
        self._scheduled = [(frame, function) for frame, function in self._scheduled if frame > self._frame]
        for function in due:
            function()
        if act:
            act()
        self._frame_calls = 0
        await next_frame()
        return self._frame_calls

    async def press_at(self, position):
        """Move to ``position`` and press the button there (the frames before are the pointer arriving)."""
        await self.step([(MOVE, position)])
        await self.step([(MOVE, position)])
        return await self.step([(MOVE, position), (DOWN,)])

    async def release(self):
        await self.step([(UP,)])
        await self.step()

    async def drag(self, positions, hold=1, group=1, repeat=1, acts=None, release=True):
        """Press at the first position, move through the others, release.

        ``group`` positions are queued in one frame, ``repeat`` repeats each queued move (and the press) and ``hold`` frames
        with no input follow each group. ``acts`` maps the number of the pointer frame (from 1) and the hold frame (from
        0) to code that runs before that frame, for example ``{(1, 1): edit}``; the hold frame -1 is the pointer frame.
        """
        drag = Drag()
        acts = acts or {}
        await self.press_at(positions[0])
        first = len(self.calls)
        rest = positions[1:]
        for number, i in enumerate(range(0, len(rest), group), 1):
            events = []
            for position in rest[i : i + group]:
                events += [(MOVE, position)] * repeat
            if repeat > 1:
                events += [(DOWN,)] * (repeat - 1)
            drag.moves.append(await self.step(events, acts.get((number, -1))))
            for index in range(hold):
                before = self.points()
                drag.holds.append(await self.step([], acts.get((number, index))))
                drag.hold_changes.append(self.points() != before)
        drag.calls = self.calls[first:]
        if release:
            await self.release()
        return drag

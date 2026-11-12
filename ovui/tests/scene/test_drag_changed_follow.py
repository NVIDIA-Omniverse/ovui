# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# DragGesture.on_changed delivery: one call for each pointer movement.
#
# A consumer that follows the pointer moves the shape, or a Transform above it, by the movement that a call reported. The
# next frame has the payload of the new place under a still pointer. Before the fix that frame gave a second call for the
# same movement (`moved` of zero or of rounding noise and, for an Arc, the angle that the pointer has on the moved shape).
# These tests drive real drags through the input queue and the gesture manager, and state for each frame whether it has a
# call (see drag_changed_harness.py). What must not change (a change that other code makes is called however small it is)
# is in test_drag_changed_edits.py.

import gc
import math

from drag_changed_harness import DOWN, DragHarness, MOVE, PROJ, UP, payload_values, translation
from omni.ui_scene import scene as sc

BASE = (123.456, -45.678, 78.9)
# Another place of the shape: here the second call for a Rectangle is a change of the last digit of the point of its border.
OTHER_BASE = (0.37, 0.11, 0.2)
KINDS = ("line_x", "line_diagonal", "arc", "rectangle", "points", "curve")
STEPS = 8


def make_shape(kind):
    def make(gesture):
        if kind == "line_x":
            return sc.Line([0, 0, 0], [3, 0, 0], thickness=5, intersection_thickness=10, gesture=gesture)
        if kind == "line_diagonal":
            return sc.Line([-2, -1.3, 0], [2, 1.7, 0], thickness=5, intersection_thickness=10, gesture=gesture)
        if kind == "arc":
            return sc.Arc(1.7, wireframe=True, thickness=6, gesture=gesture)
        if kind == "rectangle":
            return sc.Rectangle(3, 3, gesture=gesture)
        if kind == "curve":
            return sc.Curve([(-1.5, -0.5, 0), (1.5, 0.5, 0)], thicknesses=[6], curve_type=sc.Curve.CurveType.LINEAR, intersection_thickness=10, gesture=gesture)
        if kind == "mesh":
            return sc.PolygonMesh([(-1, -1, -0.5), (1, -1, 0.1), (0, 1, 0.2)], [(1, 1, 1, 1)] * 3, [3], [0, 1, 2], gesture=gesture)
        return sc.Points([(0.2, 0.1, 0), (1, 1, 0)], sizes=[12, 12], colors=[(1, 1, 1, 1)] * 2, gesture=gesture)

    return make


def pointer_path(kind, base, steps):
    """The world points (x, y) of the pointer: on the shape, moving along it."""
    if kind == "arc":
        return [(base[0] + 1.7 * math.cos(0.3 + 0.08 * i), base[1] + 1.7 * math.sin(0.3 + 0.08 * i)) for i in range(steps + 1)]
    if kind == "points":
        return [(base[0] + 0.2 + 0.06 * i, base[1] + 0.1 + 0.02 * i) for i in range(steps + 1)]
    if kind == "line_x":
        return [(base[0] + 0.2 + 0.1 * i, base[1]) for i in range(steps + 1)]
    if kind == "line_diagonal":
        return [(base[0] + 0.04 * i, base[1] + 0.025 * i) for i in range(steps + 1)]
    if kind == "curve":
        return [(base[0] - 1.2 + 0.1 * i, base[1] - 0.5 + (0.3 + 0.1 * i) / 3) for i in range(steps + 1)]
    return [(base[0] + 0.06 * i, base[1] + 0.02 * i) for i in range(steps + 1)]


def point_of(kind, payload):
    """The absolute point of the payload that a consumer reads to follow the pointer."""
    return tuple(payload.line_closest_point if kind.startswith("line") else payload.ray_closest_point)


class Follower:
    """A consumer that follows the pointer: it moves the Transform of the harness by the movement that calls reported.

    ``form`` is how it does it, in the callback: "add" (adds `moved` to the translation), "rebuild" (the translation at the
    start plus the sum of `moved`), "absolute" (the translation at the start plus the change of the absolute point of the
    payload); "none" (it writes nothing). It records the first call at which the number that it wrote is not the old
    translation plus `moved`.
    """

    def __init__(self, harness, kind, form):
        self.h, self.kind, self.form = harness, kind, form
        self.start = None
        self.first = None
        self.total = [0.0, 0.0, 0.0]
        self.calls = 0
        # The numbers of the calls (of pointer movements) at which the number that it wrote is not the old translation plus
        # `moved`.
        self.disagreements = []

    def began(self, shape):
        matrix = self.h.transform.transform
        self.start = (matrix[12], matrix[13], matrix[14])
        self.first = point_of(self.kind, shape.gesture_payload)

    def changed(self, shape):
        payload = shape.gesture_payload
        moved = tuple(payload.moved)
        if self.form in ("rebuild", "absolute") and max(abs(v) for v in moved) < 1e-3:
            return  # a call that carries no pointer movement: the consumer of these forms has nothing to apply
        self.calls += 1
        for axis in range(3):
            self.total[axis] += moved[axis]
        if self.form == "none":
            return
        matrix = self.h.transform.transform
        add = tuple(matrix[12 + axis] + moved[axis] for axis in range(3))
        if self.form == "add":
            written = add
        elif self.form == "rebuild":
            written = tuple(self.start[a] + self.total[a] for a in range(3))
        else:
            point = point_of(self.kind, payload)
            written = tuple(self.start[a] + (point[a] - self.first[a]) for a in range(3))
        if written != add:
            self.disagreements.append(self.calls)
        self.h.transform.transform = translation(*written)


class TestDragChangedFollow(DragHarness):
    async def follow_drag(self, kind, form, base=BASE, steps=STEPS, parents=None, group=1, repeat=1, hold=3):
        follower = Follower(self, kind, form)
        await self.build(
            make_shape(kind),
            base=base,
            parents=parents if parents is not None else [translation(*base)],
            on_changed=follower.changed,
            on_began=follower.began,
        )
        positions = [self.snap(self.ndc_of(*w)) for w in pointer_path(kind, base, steps)]
        drag = await self.drag(positions, hold=hold, group=group, repeat=repeat)
        first, last = self.ray(positions[0])[0], self.ray(positions[-1])[0]
        pointer = (last[0] - first[0], last[1] - first[1])
        final = self.transform.transform
        await self.end()
        return drag, follower, pointer, (final[12], final[13], final[14])

    # ------------------------------------------------------------------
    # The reported scenario
    # ------------------------------------------------------------------

    async def test_without_a_follow_there_is_one_call_for_each_movement(self):
        for kind in KINDS:
            with self.case(kind=kind):
                drag, *_ = await self.follow_drag(kind, "none")
                self.assertEqual(drag.moves, [1] * STEPS)
                self.assertEqual(drag.extra, 0)

    async def test_follow_in_the_callback_gives_one_call_for_each_movement(self):
        """The shape follows the pointer by the movement that the call reported: one call for each pointer movement and no
        call for the frames that only show the follow, for every shape."""
        for kind in KINDS:
            for base in (BASE, OTHER_BASE):
                with self.case(kind=kind, base=base):
                    drag, follower, pointer, final = await self.follow_drag(kind, "add", base=base)
                    self.assertEqual(drag.moves, [1] * STEPS)
                    self.assertEqual(drag.holds, [0] * (3 * STEPS), f"calls for a movement that was already reported: {drag.calls}")
                    self.assertEqual(follower.calls, STEPS)
                    if kind.startswith("line"):
                        # The closest point of a line moves along the line only.
                        direction = (1.0, 0.0) if kind == "line_x" else (0.8, 0.6)
                        along = pointer[0] * direction[0] + pointer[1] * direction[1]
                        pointer = (along * direction[0], along * direction[1])
                    for axis in range(2):
                        self.assertAlmostEqual(follower.total[axis], pointer[axis], delta=1e-9)
                        self.assertAlmostEqual(final[axis], base[axis] + pointer[axis], delta=1e-9)

    async def test_follow_from_the_start_is_called_at_each_step_where_its_number_is_not_old_plus_moved(self):
        """A consumer that writes the start plus the sum of the movements, or the start plus the change of the absolute point,
        writes another number than the old one plus the movement at some steps (the roundings differ). That number is also what
        an independent edit of one unit of the last digit writes, and the stored matrix and the payload are the same in both
        cases, so the call is delivered every time and nothing is learned from it (a later real correction must not be hidden
        by it). The steps where the two numbers agree give no call."""
        disagreements = 0
        for kind in KINDS:
            for form in ("rebuild", "absolute"):
                with self.case(kind=kind, form=form):
                    # Two parents that cancel out near one billion: the world position of the shape is BASE, but the
                    # translation that the consumer writes has a unit of the last digit of 1.2e-7, so the sum since the start
                    # and the old translation plus the movement round differently.
                    big = 1.0e9
                    parents = [translation(big, big, 0), translation(BASE[0] - big, BASE[1] - big, BASE[2])]
                    drag, follower, *_ = await self.follow_drag(kind, form, parents=parents)
                    self.assertEqual(drag.moves, [1] * STEPS)
                    expected = [0] * (3 * STEPS)
                    for step in follower.disagreements:
                        disagreements += 1
                        # The call is in the first frame after the step, if the number changed the payload at all (a shape
                        # that moves along itself may not).
                        expected[3 * (step - 1)] = int(drag.hold_changes[3 * (step - 1)])
                    self.assertEqual(drag.holds, expected, f"{drag.calls}")
        self.assertGreaterEqual(disagreements, 4, "the test needs steps where the forms differ")

    async def test_follow_shared_between_parents_gives_one_call_for_each_movement(self):
        """The callback shares the movement equally between two parents of the shape."""
        for kind in KINDS:
            with self.case(kind=kind):

                def changed(shape):
                    v = tuple(shape.gesture_payload.moved)
                    for transform in self.parents:
                        m = transform.transform
                        transform.transform = translation(*(m[12 + a] + v[a] / 2 for a in range(3)))

                await self.build(make_shape(kind), base=BASE, parents=[translation(*BASE), sc.Matrix44()], on_changed=changed)
                positions = [self.snap(self.ndc_of(*w)) for w in pointer_path(kind, BASE, STEPS)]
                drag = await self.drag(positions, hold=3)
                self.assertEqual(drag.moves, [1] * STEPS)
                self.assertEqual(drag.holds, [0] * (3 * STEPS), f"{drag.calls}")
                await self.end()

    async def test_follow_with_the_pointer_outside_of_the_shape_gives_one_call_for_each_movement(self):
        """A drag goes on when the pointer leaves the shape. The item closest point of a Rectangle is then the point of its
        border that is nearest, which moves with the shape: the follow changes the payload, and it is not called."""
        follower = Follower(self, "rectangle", "add")
        calls = []

        def changed(shape):
            calls.append(tuple(shape.gesture_payload.item_closest_point))
            follower.changed(shape)

        await self.build(
            lambda gesture: sc.Rectangle(1, 1, gesture=gesture), base=OTHER_BASE, parents=[translation(*OTHER_BASE)],
            on_changed=changed, on_began=follower.began,
        )
        # From inside the rectangle (half of its width is 0.5) to 0.5 beyond its border.
        path = [(OTHER_BASE[0] + 0.3 + 0.1 * i, OTHER_BASE[1] + 0.02 * i) for i in range(9)]
        positions = [self.snap(self.ndc_of(*w)) for w in path]
        drag = await self.drag(positions, hold=3)
        self.assertEqual(drag.moves, [1] * 8)
        self.assertEqual(drag.holds, [0] * 24, f"{drag.calls}")
        await self.end()

    async def test_follow_by_the_geometry_of_the_shape_gives_one_call_for_each_movement(self):
        """The callback moves the positions of a Points, or both ends of a Line, by `moved`: a Points of any size, also one
        with more positions than the gesture once could watch."""
        cases = [("points", count) for count in (1, 3, 257, 65535, 65536, 65537, 70000)] + [("line_x", 0), ("line_diagonal", 0)]
        for kind, count in cases:
            with self.case(kind=kind, count=count):

                def build(gesture, kind=kind, count=count):
                    if kind != "points":
                        return make_shape(kind)(gesture)
                    points = [(0.2 + 0.0001 * i, 0.1, 0) for i in range(count)]
                    return sc.Points(points, sizes=[12] * count, colors=[(1, 1, 1, 1)] * count, gesture=gesture)

                def changed(shape, kind=kind):
                    v = tuple(shape.gesture_payload.moved)
                    if kind == "points":
                        shape.positions = [tuple(p[a] + v[a] for a in range(3)) for p in shape.positions]
                    else:
                        shape.start = [shape.start[a] + v[a] for a in range(3)]
                        shape.end = [shape.end[a] + v[a] for a in range(3)]

                await self.build(build, base=BASE, parents=[translation(*BASE)], on_changed=changed)
                path_kind = "points" if kind == "points" else kind
                positions = [self.snap(self.ndc_of(*w)) for w in pointer_path(path_kind, BASE, STEPS)]
                drag = await self.drag(positions, hold=2)
                self.assertEqual(drag.moves, [1] * STEPS)
                self.assertEqual(drag.holds, [0] * (2 * STEPS), f"{drag.calls}")
                await self.end()

    async def test_follow_of_a_shape_with_many_positions_by_a_parent_gives_one_call_for_each_movement(self):
        for count in (65535, 65537, 200000):
            with self.case(count=count):
                follower = Follower(self, "points", "add")

                def build(gesture, count=count):
                    points = [(0.2 + 0.0001 * i, 0.1, 0) for i in range(count)]
                    return sc.Points(points, sizes=[12] * count, colors=[(1, 1, 1, 1)] * count, gesture=gesture)

                await self.build(build, base=BASE, parents=[translation(*BASE)], on_changed=follower.changed, on_began=follower.began)
                positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, STEPS)]
                drag = await self.drag(positions, hold=2)
                self.assertEqual(drag.moves, [1] * STEPS)
                self.assertEqual(drag.holds, [0] * (2 * STEPS), f"{drag.calls}")
                await self.end()

    async def test_writing_the_color_in_the_callback_does_not_bring_the_second_call_back(self):
        """Highlighting the shape that is dragged is a common pattern: a color is not geometry, so it is not a change that
        the gesture reports."""
        for kind in ("rectangle", "arc", "curve", "points", "line_x"):
            with self.case(kind=kind):
                follower = Follower(self, kind, "add")
                colors = []

                def changed(shape, kind=kind):
                    follower.changed(shape)
                    color = 0xFF000000 | (len(colors) + 1) * 0x010203
                    colors.append(color)
                    if kind == "curve":
                        shape.colors = [color]
                        shape.thicknesses = [4 + len(colors)]
                    elif kind == "points":
                        shape.colors = [(1, 0, 0, 1)] * 2
                        shape.sizes = [12 + len(colors)] * 2
                    else:
                        shape.color = color
                        shape.thickness = 4 + len(colors)

                await self.build(make_shape(kind), base=OTHER_BASE, parents=[translation(*OTHER_BASE)], on_changed=changed, on_began=follower.began)
                positions = [self.snap(self.ndc_of(*w)) for w in pointer_path(kind, OTHER_BASE, 6)]
                drag = await self.drag(positions, hold=3)
                self.assertEqual(drag.moves, [1] * 6)
                self.assertEqual(drag.holds, [0] * 18, f"{drag.calls}")
                self.assertEqual(len(colors), 6)
                await self.end()

    # ------------------------------------------------------------------
    # The follow that the consumer declares
    # ------------------------------------------------------------------

    async def test_declared_follow_covers_a_write_that_the_gesture_cannot_predict(self):
        """The consumer moves the shape through a parent that scales by 2 (the local translation is half of `moved`). The
        gesture cannot know that this is the follow of the movement, so without a declaration the frame after the write is
        called; inside `with gesture.following()` it is not."""
        for kind in ("points", "arc"):
            for declared in (False, True):
                with self.case(kind=kind, declared=declared):

                    def changed(shape):
                        v = tuple(shape.gesture_payload.moved)
                        m = self.transform.transform
                        write = lambda: setattr(self.transform, "transform", translation(*(m[12 + a] + v[a] / 2 for a in range(3))))
                        if declared:
                            with self.gesture.following():
                                write()
                        else:
                            write()

                    await self.build(
                        make_shape(kind), base=BASE, parents=[translation(*BASE), sc.Matrix44.get_scale_matrix(2, 2, 1)], on_changed=changed
                    )
                    # The shape is twice as large as it is built: so is the path of the pointer around the base.
                    path = pointer_path(kind, BASE, STEPS)
                    positions = [self.snap(self.ndc_of(BASE[0] + 2 * (x - BASE[0]), BASE[1] + 2 * (y - BASE[1]))) for x, y in path]
                    drag = await self.drag(positions, hold=3)
                    self.assertEqual(drag.moves, [1] * STEPS)
                    if declared:
                        self.assertEqual(drag.holds, [0] * (3 * STEPS), f"{drag.calls}")
                    else:
                        # One call in the first frame after each call, exactly where the shape changed the payload.
                        self.assertEqual(drag.holds, [int(drag.hold_changes[i]) if i % 3 == 0 else 0 for i in range(3 * STEPS)])
                        self.assertGreaterEqual(sum(drag.hold_changes[::3]), STEPS - 1, "the writes must change the payload")
                    await self.end()

    async def test_follow_applied_in_a_later_update_is_called_unless_it_is_declared(self):
        """An application that applies the movement in its own update, after the callback, writes outside of the callback:
        its frame has the data of an independent edit and is called. The application can declare the write."""
        for declared in (False, True):
            for delay in (1, 2):
                with self.case(declared=declared, delay=delay):

                    def apply(moved):
                        m = self.transform.transform
                        self.transform.transform = translation(*(m[12 + a] + moved[a] for a in range(3)))

                    def changed(shape):
                        moved = tuple(shape.gesture_payload.moved)

                        def later():
                            if declared:
                                with self.gesture.following():
                                    apply(moved)
                            else:
                                apply(moved)

                        self.later(delay, later)

                    await self.build(make_shape("points"), base=BASE, parents=[translation(*BASE)], on_changed=changed)
                    positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, STEPS)]
                    drag = await self.drag(positions, hold=4)
                    self.assertEqual(drag.moves, [1] * STEPS)
                    self.assertEqual(drag.extra, 0 if declared else STEPS, f"{drag.calls}")
                    await self.end()

    async def test_declared_write_after_the_callback_does_not_take_a_write_of_the_callback_for_the_follow(self):
        """The second callback turns the parent (not a follow of the movement) and keeps the movement for a later update, which
        applies it inside `following()`. The frame of that update carries the turn too, so it is called."""
        calls = []

        def changed(shape):
            calls.append(1)
            if len(calls) != 2:
                return
            moved = tuple(shape.gesture_payload.moved)
            self.transform.transform = sc.Matrix44.get_rotation_matrix(0, 0, 0.001, True) * self.transform.transform

            def later():
                m = self.transform.transform
                with self.gesture.following():
                    self.transform.transform = translation(*(m[12 + a] + moved[a] for a in range(3)))

            self.later(1, later)

        await self.build(make_shape("points"), base=BASE, parents=[translation(*BASE)], on_changed=changed)
        positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 4)]
        drag = await self.drag(positions, hold=3)
        self.assertEqual(drag.moves, [1] * 4)
        # The turn is seen in the frame of the next update, the first frame after the second call.
        self.assertEqual(drag.holds, [0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0], f"{drag.calls}")
        await self.end()

    async def test_callback_that_destroys_the_scene_of_its_shape_ends_the_drag(self):
        calls = []

        def changed(shape):
            calls.append(1)
            if len(calls) == 2:
                self.scene_view.scene.clear()

        await self.build(make_shape("points"), base=BASE, parents=[translation(*BASE)], on_changed=changed)
        positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 5)]
        drag = await self.drag(positions, hold=2)
        self.assertEqual(len(calls), 2)
        # As on main: the shape is gone, so the drag ends without a call for its end.
        self.assertEqual((self.began, self.ended), (1, 0))
        await self.end()

    async def test_call_for_a_later_follow_has_the_data_of_a_call_for_an_independent_edit(self):
        """What the gesture cannot tell apart is called (the decision of the owner of the issue: a lost real update is worse
        than one extra call). That is true only if nothing in the call tells the two apart: the payload of the call for a
        movement that was applied in a later update is, value for value, the payload of the call for an independent edit that
        writes the same matrix."""

        async def run(deferred):
            def changed(shape):
                moved = tuple(shape.gesture_payload.moved)
                if deferred:
                    def apply():
                        m = self.transform.transform
                        self.transform.transform = translation(*(m[12 + a] + moved[a] for a in range(3)))
                    self.later(1, apply)

            await self.build(make_shape("points"), base=BASE, parents=[translation(*BASE)], on_changed=changed)
            positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 2)]
            await self.press_at(positions[0])
            self.assertEqual(await self.step([(MOVE, positions[1])]), 1)
            if deferred:
                # The application applies the movement in its next update: that frame has the call.
                self.assertEqual(await self.step(), 1)
                written = tuple(self.transform.transform)
            else:
                written = None
            return written

        written = await run(True)
        deferred_call = self.calls[-1]
        await self.end()

        async def edit():
            await self.build(make_shape("points"), base=BASE, parents=[translation(*BASE)])
            positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 2)]
            await self.press_at(positions[0])
            self.assertEqual(await self.step([(MOVE, positions[1])]), 1)
            self.assertEqual(await self.step(act=lambda: setattr(self.transform, "transform", list(written))), 1)
            return self.calls[-1]

        edit_call = await edit()
        await self.end()
        self.assertEqual(deferred_call, edit_call)

    # ------------------------------------------------------------------
    # What the calls report
    # ------------------------------------------------------------------

    async def test_moved_of_the_calls_adds_up_to_the_movement_of_the_payload(self):
        """The frame that is not called keeps its movement for the next call: the sum of `moved` is the change of the
        absolute point since the drag began, with a follow as without."""
        for kind in ("line_diagonal", "points", "arc", "rectangle", "curve"):
            for form in ("none", "add"):
                with self.case(kind=kind, form=form):
                    follower = Follower(self, kind, form if form != "none" else "add")
                    first = []
                    last = []
                    sums = [0.0, 0.0, 0.0]
                    angle_sum = [0.0]

                    def changed(shape):
                        payload = shape.gesture_payload
                        for axis in range(3):
                            sums[axis] += payload.moved[axis]
                        if hasattr(payload, "moved_angle"):
                            angle_sum[0] += payload.moved_angle
                        last[:] = [(point_of(kind, payload), getattr(payload, "angle", None))]
                        if form != "none":
                            follower.changed(shape)

                    def began(shape):
                        payload = shape.gesture_payload
                        first.append((point_of(kind, payload), getattr(payload, "angle", None)))
                        follower.began(shape)

                    await self.build(make_shape(kind), base=BASE, parents=[translation(*BASE)], on_changed=changed, on_began=began)
                    positions = [self.snap(self.ndc_of(*w)) for w in pointer_path(kind, BASE, STEPS)]
                    drag = await self.drag(positions, hold=3)
                    self.assertEqual(drag.moves, [1] * STEPS)
                    for axis in range(3):
                        self.assertAlmostEqual(sums[axis], last[0][0][axis] - first[0][0][axis], delta=1e-9)
                    if first[0][1] is not None:
                        self.assertAlmostEqual(angle_sum[0], last[0][1] - first[0][1], delta=1e-9)
                    await self.end()

    async def test_arc_angle_stays_continuous_through_the_full_turn(self):
        """The pointer goes around the arc more than once, with and without a follow: the angle does not jump by a turn."""
        for form in ("none", "add"):
            with self.case(form=form):
                follower = Follower(self, "arc", "add")
                angles = []

                def changed(shape):
                    angles.append((float(shape.gesture_payload.angle), float(shape.gesture_payload.moved_angle)))
                    if form != "none":
                        follower.changed(shape)

                await self.build(make_shape("arc"), base=BASE, parents=[translation(*BASE)], on_changed=changed, on_began=follower.began)
                steps = 40
                path = [(BASE[0] + 1.7 * math.cos(0.3 + 0.17 * i), BASE[1] + 1.7 * math.sin(0.3 + 0.17 * i)) for i in range(steps + 1)]
                positions = [self.snap(self.ndc_of(*w)) for w in path]
                drag = await self.drag(positions, hold=2)
                self.assertEqual(drag.moves, [1] * steps)
                self.assertEqual(drag.extra, 0)
                for (angle, moved), (before, _) in zip(angles[1:], angles):
                    self.assertAlmostEqual(angle - before, moved, delta=1e-12)
                    self.assertLess(abs(moved), 0.5, "the angle jumped by a turn")
                if form == "none":
                    self.assertGreater(angles[-1][0] - angles[0][0], 2 * math.pi, "the pointer went around more than once")
                await self.end()

    async def test_repeated_and_grouped_input_gives_one_call_for_each_frame_with_a_movement(self):
        for group, repeat in ((1, 3), (2, 1), (4, 1), (2, 2)):
            with self.case(group=group, repeat=repeat):
                drag, follower, pointer, final = await self.follow_drag("points", "add", group=group, repeat=repeat, steps=8)
                self.assertEqual(drag.moves, [1] * (8 // group))
                self.assertEqual(drag.extra, 0)
                self.assertAlmostEqual(final[0], BASE[0] + pointer[0], delta=1e-9)
                self.assertEqual((self.began, self.ended), (0, 0), "the scene of the case is gone")

    async def test_begin_and_end_are_called_once_for_each_drag_with_a_follow(self):
        for form in ("none", "add"):
            with self.case(form=form):
                follower = Follower(self, "points", "add")
                lifecycle = []

                def changed(shape):
                    lifecycle.append("changed")
                    if form != "none":
                        follower.changed(shape)

                await self.build(
                    make_shape("points"), base=BASE, parents=[translation(*BASE)], on_changed=changed,
                    on_began=lambda s: (lifecycle.append("began"), follower.began(s)),
                    on_ended=lambda s: lifecycle.append("ended"),
                )
                positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 4)]
                await self.drag(positions, hold=2)
                self.assertEqual(lifecycle, ["began"] + ["changed"] * 4 + ["ended"])
                await self.end()

    async def test_a_second_drag_starts_clean(self):
        """The state of the follow of one drag does not reach the next: the second drag gives one call for each movement
        from its first step."""
        follower = Follower(self, "points", "add")
        await self.build(make_shape("points"), base=BASE, parents=[translation(*BASE)], on_changed=follower.changed, on_began=follower.began)
        for _ in range(2):
            positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", self.transform_world(), 5)]
            drag = await self.drag(positions, hold=2)
            self.assertEqual(drag.moves, [1] * 5)
            self.assertEqual(drag.holds, [0] * 10)
        await self.end()

    def transform_world(self):
        m = self.transform.transform
        return (m[12], m[13], m[14])

    # ------------------------------------------------------------------
    # The baseline of `moved` does not outlive the gesture
    # ------------------------------------------------------------------

    async def drag_one_step_and_replace_the_gesture(self, replace):
        follower = Follower(self, "points", "add")
        await self.build(make_shape("points"), base=BASE, parents=[translation(*BASE)], on_changed=follower.changed, on_began=follower.began)
        positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 3)]
        await self.press_at(positions[0])
        self.assertEqual(await self.step([(MOVE, positions[1])]), 1)
        # The next frame has only the follow of that call: it is not called, and its movement waits for the next call.
        replace()
        moved = []
        for events in ([(UP,)], [], [(MOVE, positions[2])], [], [], []):
            await self.step(events)
            moved.append(tuple(self.shape.gesture_payload.moved))
        return moved

    async def test_replacing_the_gesture_of_the_shape_does_not_keep_the_movement_of_the_follow(self):
        """After the gestures of the shape are replaced, the stationary frames report no movement, as they did before."""
        moved = await self.drag_one_step_and_replace_the_gesture(lambda: setattr(self.shape, "gestures", [sc.HoverGesture()]))
        self.assertEqual(moved[3:], [(0.0, 0.0, 0.0)] * 3)
        await self.end()

    async def test_releasing_the_pointer_does_not_keep_the_movement_of_the_follow(self):
        moved = await self.drag_one_step_and_replace_the_gesture(lambda: None)
        self.assertEqual(moved[3:], [(0.0, 0.0, 0.0)] * 3)
        await self.end()

    async def test_the_gesture_that_goes_away_does_not_keep_the_movement_of_the_follow(self):
        def destroy():
            self.shape.gestures = [sc.HoverGesture()]
            self.gesture = None
            gc.collect()

        moved = await self.drag_one_step_and_replace_the_gesture(destroy)
        self.assertEqual(moved[3:], [(0.0, 0.0, 0.0)] * 3)
        await self.end()

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# DragGesture.on_changed delivery: a change that is not the follow of the pointer is called, however small.
#
# The gesture does not call again for the frame that only shows how the shape followed a reported movement (see
# test_drag_changed_follow.py). Everything else that changes what the payload reports is called under a still pointer, as
# before: a write of one unit of the last digit of a number, a write that is made inside the callback but is not what the
# movement gives, the edit of a single position, the camera. Each test states exactly which frames have a call.

import math

from drag_changed_harness import DragHarness, MOVE, translation, units
from omni.ui_scene import scene as sc
from test_drag_changed_follow import BASE, Follower, make_shape, pointer_path

BIG = 1.0e9


def after(x, toward=math.inf):
    """The double next to ``x``: an edit of one unit of its last digit."""
    return math.nextafter(x, toward)


class TestDragChangedEdits(DragHarness):
    async def follow_then(self, edit, kind="points", parents=None, steps=4, edit_after=2, frames=3, base=BASE, check_mouse_moved=None):
        """Drag with a consumer that follows by the old translation plus `moved`. After the ``edit_after``-th movement, in
        the frame after the one that has only the follow, ``edit()`` runs. Returns the drag and the calls per frame."""
        follower = Follower(self, kind, "add")
        parents = parents if parents is not None else [translation(*base)]
        await self.build(
            make_shape(kind), base=base, parents=parents, on_changed=follower.changed, on_began=follower.began,
            check_mouse_moved=check_mouse_moved,
        )
        positions = [self.snap(self.ndc_of(*w)) for w in pointer_path(kind, base, steps)]
        drag = await self.drag(positions, hold=frames, acts={(edit_after, 1): edit})
        return drag, follower

    # ------------------------------------------------------------------
    # Writes that other code makes
    # ------------------------------------------------------------------

    async def test_write_of_one_unit_of_the_last_digit_after_a_follow_is_called(self):
        """The frame after the one that has only the follow is a frame of its own: a write of the smallest size is a call,
        at every magnitude of the number that is written."""
        for magnitude in (BIG, 1.0e6, 1.0e3, 7.0, 1.0e-3):
            with self.case(magnitude=magnitude):
                parents = [translation(magnitude, magnitude, 0), translation(BASE[0] - magnitude, BASE[1] - magnitude, BASE[2])]

                def edit():
                    m = self.transform.transform
                    self.transform.transform = translation(after(m[12]), m[13], m[14])

                drag, _ = await self.follow_then(edit, parents=parents)
                # Frames 0 and 2 of the hold after the second movement have no call, frame 1 (the edit) has one.
                expected = [0] * 12
                expected[3 * 1 + 1] = 1
                self.assertEqual(drag.holds, expected, f"{drag.calls}")
                # The calls are: the first movement, the second, the edit, the third, the fourth.
                self.assertNotEqual(drag.calls[2]["item_closest_point"], drag.calls[1]["item_closest_point"])
                await self.end()

    async def test_write_of_one_unit_without_any_follow_is_called(self):
        for magnitude in (BIG, 7.0, 1.0e-3):
            with self.case(magnitude=magnitude):
                await self.build(make_shape("points"), base=BASE, parents=[translation(magnitude, magnitude, 0), translation(BASE[0] - magnitude, BASE[1] - magnitude, BASE[2])])
                positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 2)]
                await self.press_at(positions[0])
                self.assertEqual(await self.step([(MOVE, positions[1])]), 1)
                self.assertEqual(await self.step(), 0)

                def edit():
                    m = self.transform.transform
                    self.transform.transform = translation(m[12], after(m[13]), m[14])

                self.assertEqual(await self.step(act=edit), 1)
                self.assertEqual(await self.step(), 0)
                await self.end()

    async def test_write_in_the_callback_that_is_one_unit_from_the_follow_is_called(self):
        """The callback writes the old translation plus `moved` at every step but one, where it writes the number that is one
        unit of the last digit away from it. That number is not the follow: the frame is called, once."""
        for edit_step in (1, 3):
            with self.case(edit_step=edit_step):
                parents = [translation(BIG, BIG, 0), translation(BASE[0] - BIG, BASE[1] - BIG, BASE[2])]
                calls = []
                follower = Follower(self, "points", "rebuild")

                def changed(shape):
                    calls.append(1)
                    moved = tuple(shape.gesture_payload.moved)
                    m = self.transform.transform
                    written = [m[12 + a] + moved[a] for a in range(3)]
                    if len(calls) == edit_step:
                        # One unit of the last digit, in the direction that is not the number that the other arithmetic of a
                        # follow (the start plus the sum) gives: the edit must not be mistaken for that.
                        follower.total = [follower.total[a] + moved[a] for a in range(3)]
                        other = follower.start[0] + follower.total[0]
                        written[0] = after(written[0]) if after(written[0]) != other else after(written[0], -math.inf)
                    else:
                        follower.total = [follower.total[a] + moved[a] for a in range(3)]
                    self.transform.transform = translation(*written)

                await self.build(make_shape("points"), base=BASE, parents=parents, on_changed=changed, on_began=follower.began)
                positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 4)]
                drag = await self.drag(positions, hold=3)
                self.assertEqual(drag.moves, [1] * 4)
                expected = [0] * 12
                expected[3 * (edit_step - 1)] = 1
                self.assertEqual(drag.holds, expected, f"{drag.calls}")
                await self.end()

    async def test_correction_of_the_callback_near_1e9_is_called_every_time(self):
        """The callback follows with the old translation plus `moved` and, at two steps, corrects the position to the
        accumulated one (one unit of the last digit away, near 1e9). The correction is an independent write whether the
        callback assigns the matrix twice or prepares the corrected matrix and assigns it once: the stored matrix and the
        payload are the same as for a consumer that always writes the accumulated position, so the gesture cannot tell them
        apart and calls both corrections. It learns nothing from the first, and the steps without a correction give none."""
        for prepared in (False, True):
            with self.case(prepared=prepared):
                total = [0.0, 0.0, 0.0]
                start = []
                corrections = []
                steps = []

                def began(shape):
                    start[:] = list(self.transform.transform)[12:15]

                def changed(shape):
                    moved = tuple(shape.gesture_payload.moved)
                    if abs(moved[0]) < 1e-3:
                        return  # a call that carries no pointer movement
                    steps.append(1)
                    m = self.transform.transform
                    for a in range(3):
                        total[a] += moved[a]
                    add = [m[12 + a] + moved[a] for a in range(3)]
                    summed = [start[a] + total[a] for a in range(3)]
                    corrected = add[0] != summed[0] and len(corrections) < 2
                    if corrected:
                        corrections.append(len(steps))
                    if not prepared:
                        self.transform.transform = translation(*add)
                    self.transform.transform = translation(*(summed if corrected else add))

                parents = [translation(-BIG, -BIG, 0), translation(BASE[0] + BIG, BASE[1] + BIG, BASE[2])]
                await self.build(make_shape("points"), base=BASE, parents=parents, on_began=began, on_changed=changed)
                positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 8)]
                drag = await self.drag(positions, hold=3)
                self.assertEqual(len(corrections), 2, "the scenario needs two steps where the two numbers differ")
                self.assertEqual(drag.moves, [1] * 8)
                expected = [0] * 24
                for n in corrections:
                    expected[3 * (n - 1)] = 1
                self.assertEqual(drag.holds, expected, f"{drag.calls}")
                await self.end()

    async def test_edit_of_one_parent_by_one_unit_after_a_follow_shared_by_two_parents_is_called(self):
        """The movement is shared equally by two parents. A later write of one unit of the last digit to one of them is
        called, and so is the same write inside the callback."""
        for inside in (False, True):
            with self.case(inside=inside):
                calls = []

                def changed(shape):
                    calls.append(1)
                    moved = tuple(shape.gesture_payload.moved)
                    for transform in self.parents:
                        m = transform.transform
                        transform.transform = translation(*(m[12 + a] + moved[a] / 2 for a in range(3)))
                    if inside and len(calls) == 2:
                        m = self.parents[0].transform
                        self.parents[0].transform = translation(after(m[12]), m[13], m[14])

                await self.build(
                    make_shape("points"), base=BASE, parents=[translation(BIG, BIG, 0), translation(BASE[0] - BIG, BASE[1] - BIG, BASE[2])],
                    on_changed=changed,
                )

                def edit():
                    m = self.parents[0].transform
                    self.parents[0].transform = translation(after(m[12]), m[13], m[14])

                positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 4)]
                drag = await self.drag(positions, hold=3, acts={} if inside else {(2, 1): edit})
                self.assertEqual(drag.moves, [1] * 4)
                expected = [0] * 12
                expected[3 * 1 + (0 if inside else 1)] = 1
                self.assertEqual(drag.holds, expected, f"{drag.calls}")
                await self.end()

    async def test_matrix_made_from_the_payload_and_overwritten_is_an_independent_write(self):
        """A matrix that was made from the payload and then got other numbers is the same as a new matrix with those
        numbers: both give one call."""
        for reuse in (False, True):
            with self.case(reuse=reuse):
                kept = []

                def changed(shape):
                    moved = tuple(shape.gesture_payload.moved)
                    kept.append(translation(*moved))

                await self.build(make_shape("points"), base=BASE, parents=[translation(*BASE)], on_changed=changed)
                positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 2)]
                await self.press_at(positions[0])
                self.assertEqual(await self.step([(MOVE, positions[1])]), 1)

                def write():
                    numbers = (BASE[0] + 0.011, BASE[1] - 0.013, BASE[2])
                    if reuse:
                        matrix = kept[0]
                        for axis in range(3):
                            matrix[12 + axis] = numbers[axis]
                    else:
                        matrix = translation(*numbers)
                    self.transform.transform = matrix

                self.assertEqual(await self.step(act=write), 1)
                self.assertEqual(await self.step(), 0)
                await self.end()

    # ------------------------------------------------------------------
    # Edits of the shape
    # ------------------------------------------------------------------

    async def test_edit_of_a_position_of_a_points_is_called_with_no_movement(self):
        """A position that changes under a still pointer has the new item point and `moved` of zero."""
        for after_follow in (False, True):
            with self.case(after_follow=after_follow):

                def edit():
                    positions = list(self.shape.positions)
                    positions[0] = (positions[0][0] + 0.01, positions[0][1], positions[0][2])
                    self.shape.positions = positions

                if after_follow:
                    drag, _ = await self.follow_then(edit)
                else:
                    await self.build(make_shape("points"), base=BASE, parents=[translation(*BASE)])
                    positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 4)]
                    drag = await self.drag(positions, hold=3, acts={(2, 1): edit})
                expected = [0] * 12
                expected[3 * 1 + 1] = 1
                self.assertEqual(drag.holds, expected, f"{drag.calls}")
                # The calls are: the first movement, the second, the edit, the third, the fourth.
                self.assertEqual(drag.calls[2]["moved"], (0.0, 0.0, 0.0))
                follow = drag.calls[1]["moved"][0] if after_follow else 0.0
                self.assertAlmostEqual(
                    drag.calls[2]["item_closest_point"][0], drag.calls[1]["item_closest_point"][0] + follow + 0.01, delta=1e-12
                )
                await self.end()

    async def test_tiny_edit_of_the_geometry_of_a_shape_after_a_follow_is_called(self):
        """Edits of 1e-14 of a position, an end or a radius, or a turn of 1e-9, after a follow."""
        tiny = 64 * math.ulp(1.0)
        for kind, what in (("points", "position"), ("line_diagonal", "end"), ("arc", "radius"), ("rectangle", "turn"), ("curve", "position")):
            with self.case(kind=kind, what=what):

                def edit():
                    if what == "position":
                        positions = list(self.shape.positions)
                        positions[0] = (positions[0][0] + tiny, positions[0][1], positions[0][2])
                        self.shape.positions = positions
                    elif what == "end":
                        x, y, z = self.shape.end
                        self.shape.end = (x + tiny, y, z)
                    elif what == "radius":
                        self.shape.radius = self.shape.radius + tiny
                    else:
                        self.transform.transform = sc.Matrix44.get_rotation_matrix(0, 0, 1.0e-9) * self.transform.transform

                # The shape is at the origin, so that its own numbers are of the size of the world numbers.
                drag, _ = await self.follow_then(edit, kind=kind, steps=3, edit_after=2, base=(0.0, 0.0, 0.0))
                # A Curve builds its points in the draw of the frame, so it shows its edit one frame later than the others.
                frame = 3 * 1 + (2 if kind == "curve" else 1)
                expected = [0] * 9
                expected[frame] = 1
                self.assertEqual(drag.holds, expected, f"{drag.calls}")
                await self.end()

    async def test_camera_move_under_a_still_pointer_is_called(self):
        def edit():
            self.scene_view.model.view = translation(-BASE[0] - 0.01, -BASE[1], -10)

        drag, _ = await self.follow_then(edit)
        expected = [0] * 12
        expected[3 * 1 + 1] = 1
        self.assertEqual(drag.holds, expected, f"{drag.calls}")
        await self.end()

    async def test_color_write_by_other_code_is_not_a_change_of_the_payload(self):
        """A color is not geometry: it is not a call, with a follow or without."""

        def edit():
            self.shape.colors = [(1, 0, 0, 1), (1, 0, 0, 1)]
            self.shape.sizes = [20, 20]

        drag, _ = await self.follow_then(edit)
        self.assertEqual(drag.holds, [0] * 12)
        await self.end()

    async def test_write_that_the_callback_makes_besides_the_follow_is_called(self):
        """The callback follows and also moves one position of the Points by one unit: the second write is not the
        follow, so the frame is called."""
        follower = Follower(self, "points", "add")
        calls = []

        def changed(shape):
            calls.append(1)
            follower.changed(shape)
            if len(calls) == 2:
                x, y, z = shape.positions[0]
                shape.positions = [(after(x), y, z)] + list(shape.positions[1:])

        await self.build(make_shape("points"), base=BASE, parents=[translation(*BASE)], on_changed=changed, on_began=follower.began)
        positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 4)]
        drag = await self.drag(positions, hold=3)
        expected = [0] * 12
        expected[3] = 1
        self.assertEqual(drag.holds, expected, f"{drag.calls}")
        await self.end()

    async def test_callback_that_does_not_write_does_not_hide_a_later_write(self):
        calls = []

        def changed(shape):
            calls.append(tuple(shape.gesture_payload.moved))

        await self.build(make_shape("points"), base=BASE, parents=[translation(*BASE)], on_changed=changed)

        def write():
            m = self.transform.transform
            self.transform.transform = translation(m[12] + 0.01, m[13], m[14])

        positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 4)]
        drag = await self.drag(positions, hold=3, acts={(2, 1): write})
        expected = [0] * 12
        expected[4] = 1
        self.assertEqual(drag.holds, expected, f"{drag.calls}")
        await self.end()

    async def test_snapping_consumer_is_called_where_the_snapped_place_differs_from_the_pointer(self):
        """A consumer that rounds the new translation to a grid is not following the movement exactly: each write that
        moves the shape to another place is called in the next frame, a write that leaves it in place gives no call."""
        grid = 0.25
        writes = []

        def changed(shape):
            moved = tuple(shape.gesture_payload.moved)
            m = self.transform.transform
            new = tuple(round((m[12 + a] + moved[a]) / grid) * grid for a in range(3))
            writes.append(new != (m[12], m[13], m[14]))
            self.transform.transform = translation(*new)

        await self.build(make_shape("points"), base=(0.0, 0.0, 0.0), parents=[translation(1.0, 1.0, 0.0)], on_changed=changed)
        # Steps of 0.2 (the grid takes the shape to the next line) and of 0.05 (the shape stays where it was).
        path = [(1.2, 1.1)]
        for i in range(8):
            path.append((path[-1][0] + (0.2 if i % 2 == 0 else 0.05), path[-1][1] + 0.01))
        positions = [self.snap(self.ndc_of(*w)) for w in path]
        drag = await self.drag(positions, hold=3)
        self.assertEqual(drag.moves, [1] * 8)
        self.assertTrue(any(writes) and not all(writes), "the grid must hold the shape in place for some steps")
        # A snapped write moves the shape to another place than the pointer asked: the frame after it has a call when the
        # payload changed, and no call when the write left the shape where it was.
        # (A call in a hold frame runs the callback too, which writes again: its entry in ``writes`` is skipped.)
        expected = [0] * 24
        index = 0
        for step in range(8):
            expected[3 * step] = int(writes[index] and drag.hold_changes[3 * step])
            index += 1 + drag.holds[3 * step]
        self.assertEqual(drag.holds, expected, f"{drag.calls}")
        await self.end()

    # ------------------------------------------------------------------
    # Things the gesture must not change
    # ------------------------------------------------------------------

    async def test_stationary_pointer_gives_no_call_for_any_number_of_frames(self):
        """A drag in which nothing is written, and one that follows, give no call in 60 frames of a still pointer."""
        for form in ("none", "add"):
            with self.case(form=form):
                follower = Follower(self, "points", "add")

                def changed(shape):
                    if form != "none":
                        follower.changed(shape)

                await self.build(make_shape("points"), base=BASE, parents=[translation(*BASE)], on_changed=changed, on_began=follower.began)
                positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 3)]
                drag = await self.drag(positions, hold=60)
                self.assertEqual(drag.moves, [1] * 3)
                self.assertEqual(drag.holds, [0] * 180)
                await self.end()

    async def test_check_mouse_moved_keeps_its_meaning(self):
        """With check_mouse_moved the gesture is called only when the 2D position of the pointer changed: a write under a
        still pointer is not, and the next movement is."""
        def edit():
            m = self.transform.transform
            self.transform.transform = translation(m[12] + 0.01, m[13], m[14])

        drag, _ = await self.follow_then(edit, check_mouse_moved=True)
        self.assertEqual(drag.moves, [1] * 4)
        self.assertEqual(drag.holds, [0] * 12)
        await self.end()

    async def test_press_and_release_without_a_movement_is_one_begin_and_one_end(self):
        await self.build(make_shape("points"), base=BASE, parents=[translation(*BASE)])
        positions = [self.snap(self.ndc_of(*w)) for w in pointer_path("points", BASE, 1)]
        await self.press_at(positions[0])
        await self.release()
        self.assertEqual((self.began, self.ended, len(self.calls)), (1, 1, 0))
        await self.end()

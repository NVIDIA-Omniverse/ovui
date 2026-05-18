# SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

# Standalone port: removed carb/omni.kit imports, renamed setUp->asyncSetUp.

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from gesture_manager_utils import Manager
from functools import partial
from omni.ui import color as cl
from omni.ui_scene import scene as sc
from test_base import OmniUiTest
import omni.ui as ui


class TestGestures(OmniUiTest):
    # Before running each test
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None  # use default standalone golden dir

    # After running each test
    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    async def test_gesture_select(self):
        def _on_shape_clicked(shape):
            """Called when the user clicks the point"""
            shape.color = cl.red

        window = await self.create_test_window(width=512, height=256)
        # Projection matrix
        proj = [0.5, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 2e-7, 0, 0, 0, 1, 1]
        view = sc.Matrix44.get_translation_matrix(0, 0, -10)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(proj, view),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200
            )

            with scene_view.scene:
                select = sc.ClickGesture(_on_shape_clicked)
                mouse_action_sequence = [(0, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]
                mouse_position_sequence = [(0, 0), (0, 0), (0, 0), (0, 0), (0, 0)]
                select.manager = Manager(mouse_action_sequence, mouse_position_sequence, scene_view)
                sc.Rectangle(color=cl.blue, gesture=select)

        await self.wait_n_updates(30)
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_gesture_drag(self):
        class MyDragGesture(sc.DragGesture):
            def __init__(self):
                super().__init__()
                self.began_called = False
                self.changed_called = False
                self.ended_called = False

            def can_be_prevented(self, gesture):
                return True

            def on_began(self):
                self.began_called = True

            def on_changed(self):
                self.changed_called = True

            def on_ended(self):
                self.ended_called = True

        class PriorityManager(Manager):
            """
            Manager makes the gesture high priority
            """

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)

            def can_be_prevented(self, gesture):
                return False

            def should_prevent(self, gesture, preventer):
                return gesture.state == sc.GestureState.CHANGED and (
                    preventer.state == sc.GestureState.BEGAN or preventer.state == sc.GestureState.CHANGED
                )

        window = await self.create_test_window()

        # Projection matrix
        proj = [0.5, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 2e-7, 0, 0, 0, 1, 1]
        view = sc.Matrix44.get_translation_matrix(0, 0, -10)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(proj, view),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
            )

            with scene_view.scene:
                # Click, move, release in the center
                drag = MyDragGesture()
                # Clicked, down, released
                mouse_action_sequence = [(0, 0, 0), (1, 1, 0), (0, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]
                mouse_position_sequence = [(0, 0), (0, 0), (0, 0), (0.1, 0), (0.1, 0), (0.1, 0)]
                drag.manager = Manager(mouse_action_sequence, mouse_position_sequence, scene_view)
                rectangle = sc.Rectangle(color=cl.blue, gesture=drag)

        await self.wait_n_updates(30)

        self.assertTrue(drag.began_called)
        self.assertTrue(drag.changed_called)
        self.assertTrue(drag.ended_called)

        # Click, move, release on the side
        drag = MyDragGesture()
        mouse_action_sequence = [(0, 0, 0), (1, 1, 0), (0, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]
        mouse_position_sequence = [(0, 0.9), (0, 0.9), (0, 0.9), (0.1, 0.9), (0.1, 0.9), (0.1, 0.9)]
        drag.manager = Manager(mouse_action_sequence, mouse_position_sequence, scene_view)
        rectangle.gestures = [drag]

        await self.wait_n_updates(30)

        self.assertFalse(drag.began_called)
        self.assertFalse(drag.changed_called)
        self.assertFalse(drag.ended_called)

        # Testing preventing
        drag = MyDragGesture()
        mouse_action_sequence = [(0, 0, 0), (1, 1, 0), (0, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]
        mouse_position_sequence = [(0, 0), (0, 0), (0, 0), (0.1, 0), (0.1, 0), (0.1, 0)]
        drag.manager = Manager(mouse_action_sequence, mouse_position_sequence, scene_view)
        rectangle.gestures = [
            sc.DragGesture(manager=PriorityManager(mouse_action_sequence, mouse_position_sequence, scene_view)),
            drag,
        ]

        await self.wait_n_updates(30)

        self.assertTrue(drag.began_called)
        self.assertFalse(drag.changed_called)
        self.assertTrue(drag.ended_called)

        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_gesture_callback(self):
        def move(transform: sc.Transform, shape: sc.AbstractShape):
            """Called by the gesture"""
            translate = shape.gesture_payload.moved
            # Move transform to the direction mouse moved
            current = sc.Matrix44.get_translation_matrix(*translate)
            transform.transform *= current

        window = await self.create_test_window(width=512, height=256)
        # Projection matrix
        proj = [0.5, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 2e-7, 0, 0, 0, 1, 1]
        view = sc.Matrix44.get_translation_matrix(0, 0, -10)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(proj, view),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200
            )

            mouse_action_sequence = [(0, 0, 0), (1, 1, 0), (0, 1, 0),(0, 1, 0), (0, 0, 1), (0, 0, 0)]
            mouse_position_sequence = [(0, 0), (0, 0), (0.15, 0), (0.3, 0), (0.3, 0), (0.3, 0)]
            mgr = Manager(mouse_action_sequence, mouse_position_sequence, scene_view)
            with scene_view.scene:
                transform = sc.Transform()
                with transform:
                    sc.Line(
                        [-1, 0, 0],
                        [1, 0, 0],
                        color=cl.blue,
                        thickness=5,
                        gesture=sc.DragGesture(
                            manager = mgr,
                            on_changed_fn=partial(move, transform)
                        )
                    )

        await self.wait_n_updates(30)
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_gesture_override(self):
        class Move(sc.DragGesture):
            def __init__(self, transform: sc.Transform):
                super().__init__()
                self.__transform = transform

            def on_began(self):
                self.sender.color = cl.red

            def on_changed(self):
                translate = self.sender.gesture_payload.moved
                # Move transform to the direction mouse moved
                current = sc.Matrix44.get_translation_matrix(*translate)
                self.__transform.transform *= current

            def on_ended(self):
                self.sender.color = cl.blue

        window = await self.create_test_window(width=512, height=256)
        # Projection matrix
        proj = [0.5, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 2e-7, 0, 0, 0, 1, 1]
        view = sc.Matrix44.get_translation_matrix(0, 0, -10)

        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(proj, view),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200
            )
            with scene_view.scene:
                transform=sc.Transform()
                with transform:
                    move = Move(transform)
                    mouse_action_sequence = [(0, 0, 0), (1, 1, 0), (0, 1, 0),(0, 1, 0), (0, 0, 1), (0, 0, 0)]
                    mouse_position_sequence = [(0, 0), (0, 0), (-0.25, -0.07), (-0.6, -0.15), (-0.6, -0.15), (-0.6, -0.15)]
                    move.manager = Manager(mouse_action_sequence, mouse_position_sequence, scene_view)
                    sc.Rectangle(color=cl.blue, gesture=move)

        await self.wait_n_updates(30)
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_gesture_manager(self):
        class PrimeManager(Manager):
            def __init__(self, mouse_action_sequence, mouse_position_sequence, scene_view):
                super().__init__(mouse_action_sequence, mouse_position_sequence, scene_view)

            def should_prevent(self, gesture, preventer):
                # prime gesture always wins
                if preventer.name == "prime":
                    return True

        def move(transform: sc.Transform, shape: sc.AbstractShape):
            """Called by the gesture"""
            translate = shape.gesture_payload.moved
            current = sc.Matrix44.get_translation_matrix(*translate)
            transform.transform *= current

        window = await self.create_test_window(width=512, height=256)
        # Projection matrix
        proj = [0.5, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 2e-7, 0, 0, 0, 1, 1]
        view = sc.Matrix44.get_translation_matrix(0, 0, -10)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(proj, view),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200
            )

            mouse_action_sequence = [(0, 0, 0), (1, 1, 0), (0, 1, 0),(0, 1, 0), (0, 0, 1), (0, 0, 0)]
            mouse_position_sequence = [(0, 0), (0, 0), (-0.25, -0.15), (-0.6, -0.3), (-0.6, -0.3), (-0.6, -0.3)]
            mgr = PrimeManager(mouse_action_sequence, mouse_position_sequence, scene_view)
            # create two cubes overlap with each other
            # since the red one has the name of prime, it wins the gesture of move
            with scene_view.scene:
                transform1 = sc.Transform()
                with transform1:
                    sc.Rectangle(
                        color=cl.blue,
                        gesture=sc.DragGesture(
                            manager=mgr,
                            on_changed_fn=partial(move, transform1)
                        )
                    )
                transform2 = sc.Transform()
                with transform2:
                    sc.Rectangle(
                        color=cl.red,
                        gesture=sc.DragGesture(
                            name="prime",
                            manager=mgr,
                            on_changed_fn=partial(move, transform2)
                        )
                    )

        await self.wait_n_updates(30)
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_hover_gesture(self):
        class HoverGesture(sc.HoverGesture):
            def on_began(self):
                self.sender.color = cl.red

            def on_ended(self):
                self.sender.color = cl.blue

        window = await self.create_test_window()
        # Projection matrix
        proj = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 2e-7, 0, 0, 0, 1, 1]
        view = sc.Matrix44.get_translation_matrix(0, 0, -1)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(proj, view), aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT
            )

            mouse_action_sequence = [(0, 0, 0)] * 10
            # Move mouse close (2px) to the second line and after that on the
            # first line. The second line will be blue, the first one is the
            # red.
            mouse_position_sequence = [(-0, -1)] * 2 + [(0, 0.028)] * 3 + [(0, 0)] * 5
            mgr = Manager(mouse_action_sequence, mouse_position_sequence, scene_view)
            # create two cubes overlap with each other
            # since the red one has the name of prime, it wins the gesture of move
            with scene_view.scene:
                sc.Line([-1, -1, 0], [1, 1, 0], thickness=1, gesture=HoverGesture(manager=mgr))
                sc.Line([-1, 1, 0], [1, -0.9, 0], thickness=4, gesture=HoverGesture(manager=mgr))

        await self.wait_n_updates(9)
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_intersection_thickness(self):
        class HoverGesture(sc.HoverGesture):
            def on_began(self):
                self.sender.color = cl.red

            def on_ended(self):
                self.sender.color = cl.blue

        window = await self.create_test_window()
        # Projection matrix
        proj = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 2e-7, 0, 0, 0, 1, 1]
        view = sc.Matrix44.get_translation_matrix(0, 0, -1)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(proj, view), aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT
            )

            mouse_action_sequence = [(0, 0, 0)] * 10
            # Move mouse close (about 4px) to the second line and after that on
            # the first line. The second line will be blue, the first one is the
            # red.
            mouse_position_sequence = [(-0, -1)] * 2 + [(0, 0.43)] * 3 + [(0, 0)] * 5
            mgr = Manager(mouse_action_sequence, mouse_position_sequence, scene_view)
            # create two cubes overlap with each other
            # since the red one has the name of prime, it wins the gesture of move
            with scene_view.scene:
                sc.Line([-1, -1, 0], [1, 1, 0], thickness=1, gesture=HoverGesture(manager=mgr))
                sc.Line(
                    [-1, 1, 0], [1, 0, 0], thickness=1, intersection_thickness=8, gesture=HoverGesture(manager=mgr)
                )

        await self.wait_n_updates(9)
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_hover_smallscale(self):
        # Flag that it was hovered
        hovered = [0, 0]

        class HoverGesture(sc.HoverGesture):
            def __init__(self, manager: sc.GestureManager):
                super().__init__(manager=manager)

            def on_began(self):
                if isinstance(self.sender, sc.Line):
                    hovered[0] = 1
                elif isinstance(self.sender, sc.Rectangle):
                    hovered[1] = 1
                self.sender.color = [0, 0, 1, 1]

            def on_ended(self):
                self.sender.color = [1, 1, 1, 1]

        class SmallScale(sc.Manipulator):
            def __init__(self, manager: sc.GestureManager):
                super().__init__()
                self.manager = manager

            def on_build(self):
                transform = sc.Matrix44.get_translation_matrix(-0.01, 0, 0)

                with sc.Transform(transform=transform):
                    sc.Line([0, 0.005, 0], [0, 0.01, 0], gestures=HoverGesture(manager=self.manager))
                    sc.Rectangle(0.01, 0.01, gestures=HoverGesture(manager=self.manager))

        window = await self.create_test_window()
        proj = [
            4.772131,
            0.000000,
            0.000000,
            0.000000,
            0.000000,
            7.987040,
            0.000000,
            0.000000,
            0.000000,
            0.000000,
            -1.002002,
            -1.000000,
            0.000000,
            0.000000,
            -0.200200,
            0.000000,
        ]
        view = [
            0.853374,
            -0.124604,
            0.506188,
            0.000000,
            -0.000000,
            0.971013,
            0.239026,
            0.000000,
            -0.521299,
            -0.203979,
            0.828638,
            0.000000,
            0.008796,
            -0.003659,
            -0.198528,
            1.000000,
        ]
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(proj, view), aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT
            )

            mouse_action_sequence = [(0, 0, 0)] * 10
            # Move mouse close (about 4px) to the second line and after that on
            # the first line. The second line will be blue, the first one is the
            # red.
            mouse_position_sequence = [(-0, -1)] * 2 + [(0, 0)] * 3 + [(0, 0.1)] * 5
            mgr = Manager(mouse_action_sequence, mouse_position_sequence, scene_view)

            with scene_view.scene:
                SmallScale(mgr)

        await self.wait_n_updates(9)

        self.assertTrue(hovered[0])
        self.assertTrue(hovered[1])

        await self.finalize_test_no_image()

    async def test_check_no_crash(self):
        class ClickGesture(sc.ClickGesture):
            def __init__(self, *args, **kwargs):
                # Passing `self` while using `super().__init__` is legal python, but not correct.
                # However, it shouldn't crash.
                super().__init__(self, *args, **kwargs)

        with self.assertRaises(TypeError) as cm:
            self.assertTrue(bool(ClickGesture()))
        await self.finalize_test_no_image()

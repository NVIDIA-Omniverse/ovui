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

from gesture_manager_utils import Manager
from omni.ui import color as cl
from omni.ui_scene import scene as sc
from test_base import OmniUiTest
import math


class TestArc(OmniUiTest):
    # Before running each test
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None  # use default standalone golden dir

    # After running each test
    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    async def test_angle(self):
        """Test the angle"""
        window = await self.create_test_window(block_devices=False)

        class MyDragGesture(sc.DragGesture):
            def __init__(self):
                super().__init__()

                self.began_called = False
                self.changed_called = False
                self.ended_called = False

                self.began_angle = 0.0
                self.end_angle = 0.0

            def can_be_prevented(self, gesture):
                return True

            def on_began(self):
                self.sender.begin = self.sender.gesture_payload.angle
                self.began_angle = self.sender.gesture_payload.angle
                self.began_called = True

            def on_changed(self):
                self.sender.end = self.sender.gesture_payload.angle
                self.changed_called = True

            def on_ended(self):
                self.sender.color = cl.blue
                self.end_angle = self.sender.gesture_payload.angle
                self.ended_called = True

        with window.frame:
            # Camera matrices
            projection = [1e-2, 0, 0, 0]
            projection += [0, 1e-2, 0, 0]
            projection += [0, 0, 2e-7, 0]
            projection += [0, 0, 1, 1]
            view = sc.Matrix44.get_translation_matrix(0, 0, -5)

            scene_view = sc.SceneView(sc.CameraModel(projection, view))
            with scene_view.scene:
                transform = sc.Matrix44.get_translation_matrix(0, 0, 0)
                transform *= sc.Matrix44.get_scale_matrix(0.2, 0.2, 0.2)

                with sc.Transform(transform=transform):
                    nsteps = 20

                    # Click, drag 360 deg, release
                    drag = MyDragGesture()
                    # Clicked, down, released
                    mouse_action_sequence = [(0, 0, 0), (1, 1, 0)] + [(0, 1, 0)] * (nsteps + 1) + [(0, 0, 1), (0, 0, 0)]
                    mouse_position_sequence = (
                        [(0, 1), (0, 1)]
                        + [
                            (-math.sin(i * math.pi * 2.0 / nsteps), math.cos(i * math.pi * 2.0 / nsteps))
                            for i in range(nsteps + 1)
                        ]
                        + [(0, 1), (0, 1)]
                    )
                    drag.manager = Manager(mouse_action_sequence, mouse_position_sequence, scene_view)

                    sc.Arc(500, wireframe=True, color=cl.white, gesture=drag)

        await self.wait_n_updates(nsteps + 5)

        self.assertTrue(drag.began_called)
        self.assertTrue(drag.changed_called)
        self.assertTrue(drag.ended_called)
        self.assertEqual(drag.began_angle, math.pi * 0.5)
        self.assertEqual(drag.end_angle, math.pi * 2.5)

        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_gesture_culling(self):
        """Test the gesture from a culled position on the arc"""
        window = await self.create_test_window(block_devices=False)

        class MyHoverGesture(sc.HoverGesture):
            def __init__(self):
                super().__init__()
                self.began_called: bool = False
                self.ended_called: bool = False

            def can_be_prevented(self, gesture):
                return True

            def on_began(self):
                self.sender.begin = self.sender.gesture_payload.culled
                self.culled = self.sender.gesture_payload.culled
                self.began_called = True

            def on_ended(self):
                self.sender.color = cl.blue
                self.ended_called = True

        with window.frame:
            # Camera matrices
            projection = [1e-2, 0, 0, 0]
            projection += [0, 1e-2, 0, 0]
            projection += [0, 0, 2e-7, 0]
            projection += [0, 0, 1, 1]
            view = sc.Matrix44.get_translation_matrix(0, 0, -5)
            view *= sc.Matrix44.get_rotation_matrix(0.0, 45.0, 0.0, degrees=True)

            scene_view = sc.SceneView(sc.CameraModel(projection, view))
            with scene_view.scene:
                transform = sc.Matrix44.get_translation_matrix(0, 0, 0)
                transform *= sc.Matrix44.get_scale_matrix(0.2, 0.2, 0.2)

                with sc.Transform(transform=transform):
                    n_steps = int(window.width * 0.5)
                    hover = MyHoverGesture()
                    # Move diagonally across the view to center
                    mouse_action_sequence = [(0, 0, 0)] * 3
                    mouse_position_sequence = [(0, 0), (0, 1), (0, 0)]
                    hover.manager = Manager(mouse_action_sequence, mouse_position_sequence, scene_view)

                    sc.Arc(
                        500,
                        axis=2,
                        wireframe=True,
                        intersection_thickness=10,
                        color=cl.white,
                        culling=sc.Culling.BACK,
                        gesture=hover
                    )

        await self.wait_n_updates(5)

        self.assertTrue(hover.began_called)
        self.assertTrue(hover.ended_called)
        self.assertTrue(not hover.culled)  # Hover over non culled position

        await self.finalize_test(golden_img_dir=self._golden_img_dir)

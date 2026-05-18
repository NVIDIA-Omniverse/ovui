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

from test_base import OmniUiTest
from omni.ui_scene import scene as sc


class TestCamera(OmniUiTest):
    # Before running each test
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None  # use default standalone golden dir

    # After running each test
    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    async def test_general(self):
        window = await self.create_test_window(width=512, height=256)
        # Projection matrix
        proj = [1.7, 0, 0, 0, 0, 3, 0, 0, 0, 0, -1, -1, 0, 0, -2, 0]

        # Move camera
        rotation = sc.Matrix44.get_rotation_matrix(30, 50, 0, True)
        transl = sc.Matrix44.get_translation_matrix(0, 0, -6)
        view = transl * rotation
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(proj, view),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200
            )

            with scene_view.scene:
                # Edges of cube
                sc.Line([-1, -1, -1], [1, -1, -1])
                sc.Line([-1, 1, -1], [1, 1, -1])
                sc.Line([-1, -1, 1], [1, -1, 1])
                sc.Line([-1, 1, 1], [1, 1, 1])

                sc.Line([-1, -1, -1], [-1, 1, -1])
                sc.Line([1, -1, -1], [1, 1, -1])
                sc.Line([-1, -1, 1], [-1, 1, 1])
                sc.Line([1, -1, 1], [1, 1, 1])

                sc.Line([-1, -1, -1], [-1, -1, 1])
                sc.Line([-1, 1, -1], [-1, 1, 1])
                sc.Line([1, -1, -1], [1, -1, 1])
                sc.Line([1, 1, -1], [1, 1, 1])

        await self.wait_n_updates()
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_distant_camera(self):
        window = await self.create_test_window(width=512, height=256)
        # Projection matrix
        proj = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, -1, 0, 0, 0, 0]

        # Move camera
        rotation = sc.Matrix44.get_rotation_matrix(-25, 55, 0, True)
        transl = sc.Matrix44.get_translation_matrix(-10000000000, 10000000000, -20000000000)
        view = transl * rotation
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(proj, view),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200
            )

            with scene_view.scene:
                sc.Line([-10000000000, -10000000000, -10000000000], [-2000000000, -10000000000, -10000000000])

        await self.wait_n_updates()
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_camera_model(self):
        class CameraModel(sc.AbstractManipulatorModel):
            def __init__(self):
                super().__init__()
                self._angle = 0

            def append_angle(self, delta: float):
                self._angle += delta * 100
                # Inform SceneView that view matrix is changed
                self._item_changed("view")

            def get_as_floats(self, item):
                """Called by SceneView to get projection and view matrices"""
                if item == self.get_item("projection"):
                    # Projection matrix
                    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, -1, 0, 0, -2, 0]
                if item == self.get_item("view"):
                    # Move camera
                    rotation = sc.Matrix44.get_rotation_matrix(30, self._angle, 0, True)
                    transl = sc.Matrix44.get_translation_matrix(0, 0, -8)
                    view = transl * rotation
                    return [view[i] for i in range(16)]

        def on_mouse_dragged(sender):
            # Change the model's angle according to mouse x offset
            mouse_moved = sender.gesture_payload.mouse_moved[0]
            sender.scene_view.model.append_angle(mouse_moved)

        window = await self.create_test_window(width=512, height=256)
        camera_model = CameraModel()
        # check initial projection and view matrix
        proj = camera_model.get_as_floats(camera_model.get_item("projection"))
        view = camera_model.get_as_floats(camera_model.get_item("view"))
        self.assertEqual(proj, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, -1, 0, 0, -2, 0])
        self.assertAlmostEqual(view[5], 0.866025, places=5)
        self.assertAlmostEqual(view[10], 0.866025, places=5)
        self.assertAlmostEqual(view[6], 0.5, places=5)
        self.assertAlmostEqual(view[9], -0.5, places=5)

        with window.frame:
            with sc.SceneView(camera_model, height=200).scene:
                # Camera control
                sender = sc.Screen(gesture=sc.DragGesture(on_changed_fn=on_mouse_dragged))

                # Edges of cube
                sc.Line([-1, -1, -1], [1, -1, -1])
                sc.Line([-1, 1, -1], [1, 1, -1])
                sc.Line([-1, -1, 1], [1, -1, 1])
                sc.Line([-1, 1, 1], [1, 1, 1])

                sc.Line([-1, -1, -1], [-1, 1, -1])
                sc.Line([1, -1, -1], [1, 1, -1])
                sc.Line([-1, -1, 1], [-1, 1, 1])
                sc.Line([1, -1, 1], [1, 1, 1])

                sc.Line([-1, -1, -1], [-1, -1, 1])
                sc.Line([-1, 1, -1], [-1, 1, 1])
                sc.Line([1, -1, -1], [1, -1, 1])
                sc.Line([1, 1, -1], [1, 1, 1])

        await self.wait_n_updates()
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

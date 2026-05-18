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
__all__ = ["TestScene"]

import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_base import OmniUiTest
from omni.ui_scene import scene as sc
import omni.ui as ui


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
            return [5, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, -1, 0, 0, -1, 0]
        if item == self.get_item("view"):
            # Move camera
            rotation = sc.Matrix44.get_rotation_matrix(30, self._angle, 0, True)
            transl = sc.Matrix44.get_translation_matrix(0, 0, -8)
            view = transl * rotation
            return [view[i] for i in range(16)]


class StereoModel(sc.AbstractManipulatorModel):
    def __init__(self, parent, offset):
        super().__init__()
        self._parent = parent
        self._offset = offset
        self._sub = self._parent.subscribe_item_changed_fn(lambda m, i: self.changed(m, i))

    def changed(self, model, item):
        self._item_changed("view")

    def get_as_floats(self, item):
        """Called by SceneView to get projection and view matrices"""
        if item == self.get_item("projection"):
            return self._parent.get_as_floats(self._parent.get_item("projection"))
        if item == self.get_item("view"):
            parent = self._parent.get_as_floats(self._parent.get_item("view"))
            parent = sc.Matrix44(*parent)
            transl = sc.Matrix44.get_translation_matrix(0, 0, 8)
            rotation = sc.Matrix44.get_rotation_matrix(0, self._offset, 0, True)
            transl_inv = sc.Matrix44.get_translation_matrix(0, 0, -8)
            view = transl_inv * rotation * transl * parent
            return [view[i] for i in range(16)]


class TestScene(OmniUiTest):
    # Before running each test
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None  # use default standalone golden dir

    # After running each test
    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    async def test_draw_list_buffer_count(self):
        class RotatingCube(sc.Manipulator):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self._angle = 0

            def on_build(self):
                transform = sc.Matrix44.get_rotation_matrix(
                    0, self._angle, 0, True)

                with sc.Transform(transform=transform):
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

                # Increase the angle
                self._angle += 5

            def get_angle(self):
                return self._angle

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
                rcube = RotatingCube()

        for _ in range(2):
            rcube.invalidate()
            await self.wait_n_updates(1)

        draw_list_buffer_count = scene_view.scene.draw_list_buffer_count

        for _ in range(2):
            rcube.invalidate()
            await self.wait_n_updates(1)

        # Testing that the buffer count didn't change
        self.assertEqual(scene_view.scene.draw_list_buffer_count, draw_list_buffer_count)

        await self.finalize_test_no_image()

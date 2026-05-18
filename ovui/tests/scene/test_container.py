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
from omni.ui import color as cl
import math
import weakref


class TestContainer(OmniUiTest):
    # Before running each test
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None  # use default standalone golden dir

    # After running each test
    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    async def test_transform(self):
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
                line_count = 36
                for i in range(line_count):
                    weight = i / line_count
                    angle = 2.0 * math.pi * weight

                    # translation matrix
                    move = sc.Matrix44.get_translation_matrix(
                        8 * (weight - 0.5), 0.5 * math.sin(angle), 0)

                    # rotation matrix
                    rotate = sc.Matrix44.get_rotation_matrix(0, 0, angle)

                    # the final transformation
                    transform = move * rotate

                    color = cl(weight, 1.0 - weight, 1.0)

                    # create transform and put line to it
                    with sc.Transform(transform=transform):
                        sc.Line([0, 0, 0], [0.5, 0, 0], color=color)

        await self.wait_n_updates()
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_clear(self):
        """Test manipulator inside container is destroyed on clear"""
        manipulator: sc.Manipulator | None
        scene_view: sc.SceneView
        root: sc.Transform

        window = await self.create_test_window()

        try:
            with window.frame:
                scene_view = sc.SceneView()
                with scene_view.scene:
                    root = sc.Transform()
                    with root:
                        manipulator = sc.Manipulator()

            weak_manipulator = weakref.ref(manipulator)

            await self.wait_n_updates()

            # Deleting the manipulator and calling root.clear() SHOULD release the manipulator's strong ref
            del manipulator
            root.clear()

            await self.wait_n_updates()

            self.assertIsNone(weak_manipulator())

        finally:
            await self.finalize_test_no_image()

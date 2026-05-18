# SPDX-FileCopyrightText: Copyright (c) 2023-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

# Standalone port: removed carb/omni.kit imports, renamed setUp->asyncSetUp.
__all__ = ["TestTransformBasis"]

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_base import OmniUiTest
from omni.ui_scene import scene as sc
from omni.ui import color as cl


class TestTransformBasis(OmniUiTest):
    # Before running each test
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None  # use default standalone golden dir

    # After running each test
    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    async def test_transform_basis(self):

        class ConstantTransformBasis(sc.TransformBasis):
            def __init__(self, x: float, y: float, z: float, **kwargs):
                super().__init__(**kwargs)
                self.__matrix = sc.Matrix44.get_translation_matrix(x, y, z)

            def get_matrix(self):
                return self.__matrix

        window = await self.create_test_window(width=512, height=256)
        # Projection matrix
        proj = [1.7, 0, 0, 0, 0, 3, 0, 0, 0, 0, -1, -1, 0, 0, -2, 0]

        # Move camera
        rotation = sc.Matrix44.get_rotation_matrix(30, 50, 0, True)
        transl = sc.Matrix44.get_translation_matrix(0, -1, -6)
        view = transl * rotation

        with window.frame:
            self.scene_view = sc.SceneView(
                sc.CameraModel(proj, view), aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT, height=200
            )

            positions = [0, 0, 0]
            sizes = [20]

            white = cl(1.0, 1.0, 1.0, 1.0)
            red = cl(1.0, 0.0, 0.0, 1.0)
            green = cl(0.0, 1.0, 0.0, 1.0)
            blue = cl(0.0, 0.0, 1.0, 1.0)
            yellow = cl(1.0, 1.0, 0.0, 1.0)

            with self.scene_view.scene:
                sc.Points(positions, sizes=sizes, colors=[white])

                with sc.Transform(transform=sc.Matrix44.get_translation_matrix(2, 0, 0)):
                    sc.Points(positions, sizes=sizes, colors=[red])

                    with sc.Transform(transform=sc.Matrix44.get_translation_matrix(0, 2, 0)):
                        sc.Points(positions, sizes=sizes, colors=[green])

                        # Now throw in a transform with a custom basis, overriding the parent transforms
                        with sc.Transform(basis=ConstantTransformBasis(-2, 0, 0)):
                            sc.Points(positions, sizes=sizes, colors=[blue])

                            with sc.Transform(transform=sc.Matrix44.get_translation_matrix(0, 2, 0)):
                                sc.Points(positions, sizes=sizes, colors=[yellow])

        await self.wait_n_updates()
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

        self.scene_view.scene.clear()
        self.scene_view = None

        del window

    async def test_transform_basis_python_class_deleted(self):
        self.was_deleted = False

        def do_delete():
            self.was_deleted = True

        class LoggingTransformBasis(sc.TransformBasis):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.__matrix = sc.Matrix44.get_translation_matrix(0, 0, 0)

            def __del__(self):
                do_delete()

            def get_matrix(self):
                return self.__matrix

        xform = sc.Transform(basis=LoggingTransformBasis())

        self.assertFalse(self.was_deleted, "Python child class of sc.TransformBasis was deleted too soon")

        del xform

        self.assertTrue(self.was_deleted, "Python child class of sc.TransformBasis was not deleted")
        del self.was_deleted

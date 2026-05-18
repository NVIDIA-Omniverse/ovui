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
from gesture_manager_utils import Manager
from functools import partial
from omni.ui_scene import scene as sc
from omni.ui import color as cl
import asyncio
import omni.ui as ui

DATA_PATH = Path(__file__).resolve().parent / "data"


class TestManipulator(OmniUiTest):
    # Before running each test
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None  # use default standalone golden dir

    # After running each test
    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    async def test_manipulator_update(self):
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

                rcube.invalidate()
                await self.wait_n_updates(1)
                self.assertEqual(rcube.get_angle(), 5)

                rcube.invalidate()
                await self.wait_n_updates(1)
                self.assertEqual(rcube.get_angle(), 10)

                rcube.invalidate()
                await self.wait_n_updates(1)
                self.assertEqual(rcube.get_angle(), 15)

        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_manipulator_model(self):
        class MovingRectangle(sc.Manipulator):
            """Manipulator that redraws when the model is changed"""

            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                mouse_action_sequence = [(0, 0, 0), (1, 1, 0), (0, 1, 0),(0, 1, 0), (0, 0, 1), (0, 0, 0)]
                mouse_position_sequence = [(0, 0), (0, 0), (0.15, 0), (0.3, 0), (0.3, 0), (0.3, 0)]
                mgr = Manager(mouse_action_sequence, mouse_position_sequence, scene_view)
                self._gesture = sc.DragGesture(on_changed_fn=self._move, manager=mgr)

            def on_build(self):
                position = self.model.get_as_floats(self.model.get_item("position"))
                transform = sc.Matrix44.get_translation_matrix(*position)
                with sc.Transform(transform=transform):
                    sc.Rectangle(color=cl.blue, gesture=self._gesture)

            def on_model_updated(self, item):
                self.invalidate()

            def _move(self, shape: sc.AbstractShape):
                position = shape.gesture_payload.ray_closest_point
                item = self.model.get_item("position")
                self.model.set_floats(item, position)

        class Model(sc.AbstractManipulatorModel):
            """User part. Simple value holder."""

            class PositionItem(sc.AbstractManipulatorItem):
                def __init__(self):
                    super().__init__()
                    self.value = [0, 0, 0]

            def __init__(self):
                super().__init__()
                self.position = Model.PositionItem()

            def get_item(self, identifier):
                return self.position

            def get_as_floats(self, item):
                return item.value

            def set_floats(self, item, value):
                item.value = value
                self._item_changed(item)

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
                MovingRectangle(model=Model())

        await self.wait_n_updates(30)
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_manipulator_image(self):
        """Check the image in manipulator doesn't crash when invalidation"""

        class ImageManipulator(sc.Manipulator):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.image = None

            def on_build(self):
                filename = f"{DATA_PATH}/main_ov_logo_square.png"
                self.image = sc.Image(filename)

        window = await self.create_test_window()
        with window.frame:
            scene_view = sc.SceneView(aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT, height=150)
            with scene_view.scene:
                manipulator = ImageManipulator()

        # removing this wait leads to an error of png unload wait time exceeded limit of 20000 ms!
        for _ in range(50):
            image_ready = manipulator.image and manipulator.image.image_provider.is_reference_valid
            if image_ready:
                break
            await asyncio.sleep(0.1)
            await self.wait_n_updates(1)

        # Check it doesn't crash
        manipulator.invalidate()
        await self.wait_n_updates(1)

        # Wait for Image
        for _ in range(50):
            image_ready = manipulator.image and manipulator.image.image_provider.is_reference_valid
            if image_ready:
                break
            await asyncio.sleep(0.1)
            await self.wait_n_updates(1)

        await self.finalize_test_no_image()

    async def test_manipulator_textured_mesh(self):
        """Check the TexturedMesh in manipulator doesn't crash when invalidation"""

        class TexturedMeshManipulator(sc.Manipulator):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.mesh = None

            def on_build(self):
                point_count = 4
                # Form the mesh data
                points = [[1, -1, 0], [1, 1, 0], [0, 1, 0], [-1, -1, 0]]
                vertex_indices = [0, 1, 2, 3]
                colors = [[0, 1, 0, 1], [0, 1, 0, 1], [0, 1, 0, 1], [0, 1, 0, 1]]
                uvs = [[1, 1], [1, 0], [0.5, 0], [0, 1]]
                # Draw the mesh
                filename = f"{DATA_PATH}/main_ov_logo_square.png"
                self.mesh = sc.TexturedMesh(filename, uvs, points, colors, [point_count], vertex_indices)

        window = await self.create_test_window()
        with window.frame:
            scene_view = sc.SceneView(aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT, height=150)
            with scene_view.scene:
                manipulator = TexturedMeshManipulator()

        # removing this wait leads to an error of png unload wait time exceeded limit of 20000 ms!
        for _ in range(50):
            image_ready = manipulator.mesh and manipulator.mesh.image_provider.is_reference_valid
            if image_ready:
                break
            await asyncio.sleep(0.1)
            await self.wait_n_updates(1)

        # Check it doesn't crash
        manipulator.invalidate()
        await self.wait_n_updates(1)

        # Wait for Image
        for _ in range(50):
            image_ready = manipulator.mesh and manipulator.mesh.image_provider.is_reference_valid
            if image_ready:
                break
            await asyncio.sleep(0.1)
            await self.wait_n_updates(1)

        await self.finalize_test_no_image()

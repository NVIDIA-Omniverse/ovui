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

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gesture_manager_utils import Manager
from omni.ui import color as cl
from omni.ui_scene import scene as sc
from test_base import OmniUiTest
import asyncio
import math
import omni.ui as ui

DATA_PATH = Path(__file__).resolve().parent / "data"


class TestCaching(OmniUiTest):
    # Before running each test
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None  # use default standalone golden dir

    # After running each test
    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    async def create_shapes(self):
        scene_view = sc.SceneView(aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT, height=150)
        scene_view.cache_draw_buffer = True
        with scene_view.scene:
            # line
            line = sc.Line([-2.5, -5, 0], [-1.5, -5, 0], color=cl.red, thickness=5)
            transforms = []
            transforms.append(sc.Transform(transform=sc.Matrix44.get_translation_matrix(2, 0, 0)))
            with transforms[0]:
                rects = []
                # Rectangle
                rects.append(sc.Rectangle(color=cl.blue))
                # wireframe rectangle
                rects.append(sc.Rectangle(2, 1.3, thickness=5, wireframe=True))
            # arc
            arc = sc.Arc(3, begin=math.pi, end=4, thickness=5, wireframe=True, color=cl.yellow)
            # label
            transforms.append(sc.Transform(transform=sc.Matrix44.get_translation_matrix(1, -3.5, 0)))
            with transforms[1]:
                label = sc.Label("NVIDIA Omniverse", alignment=ui.Alignment.CENTER, color=cl.green, size=50)
            transforms.append(sc.Transform(transform=sc.Matrix44.get_translation_matrix(2, -2, 0)))
            with transforms[2]:
                filename = f"{DATA_PATH}/main_ov_logo_square.png"
                image = sc.Image(filename)

            # points and polygon_mesh
            point_count = 36
            points_positions = []
            mesh_positions = []
            sizes = []
            colors = []
            vertex_indices = []
            for i in range(point_count):
                weight = i / point_count
                angle = 2.0 * math.pi * weight
                vertex_indices.append(i)
                points_positions.append([math.cos(angle), math.sin(angle), 0])
                mesh_positions.append([math.cos(angle) * weight, -math.sin(angle) * weight, 0])
                colors.append([weight, 1 - weight, 1, 1])
                sizes.append(6 * (weight + 1.0 / point_count))

            transforms.append(sc.Transform(transform=sc.Matrix44.get_translation_matrix(0, -2, 0)))
            with transforms[3]:
                points = sc.Points(points_positions, colors=colors, sizes=sizes)

            transforms.append(sc.Transform(transform=sc.Matrix44.get_translation_matrix(2, -5, 0)))
            with transforms[4]:
                polygon_mesh = sc.PolygonMesh(mesh_positions, colors, [point_count], vertex_indices)

            # textured_mesh
            point_count = 4
            # Form the mesh data
            vertex_indices = [0, 2, 3, 1]
            textured_mesh_positions = [(-0.5, -5.5, 0), (0.5, -5.5, 0), (-0.5, -4.5, 0), (0.5, -4.5, 0)]
            colors = [[0, 1, 0, 1], [0, 1, 0, 1], [0, 1, 0, 1], [0, 1, 0, 1]]
            # UVs specified in USD coordinate system
            uvs = [(0, 1), (0, 0), (1, 0), (1, 1)]
            # Draw the mesh
            filename = f"{DATA_PATH}/main_ov_logo_square.png"
            textured_mesh = sc.TexturedMesh(
                filename, uvs, textured_mesh_positions, colors, [point_count], vertex_indices
            )

            # removing this wait leads to an error of png unload wait time exceeded limit of 20000 ms!
            for _ in range(50):
                image_ready = image.image_provider.is_reference_valid
                if image_ready:
                    break
                await asyncio.sleep(0.1)
                await self.wait_n_updates(1)

        return (scene_view, line, transforms, rects, arc, label, image, points, polygon_mesh, textured_mesh)

    async def test_caching_shapes(self):
        """Test caching with multiple shapes"""

        window = await self.create_test_window(width=512, height=512)
        with window.frame:
            await self.create_shapes()

        await self.wait_n_updates()
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_caching_shapes_changed(self):
        """Test caching with multiple shape changed"""

        window = await self.create_test_window(width=512, height=512)
        with window.frame:
            (
                scene_view,
                line,
                transforms,
                rects,
                arc,
                label,
                image,
                points,
                polygon_mesh,
                textured_mesh,
            ) = await self.create_shapes()

        await self.wait_n_updates()

        # Change line
        line.start = [-2, 0.5, 0]
        line.end = [-1, 0.5, 0]
        line.color = cl.blue
        line.thickness = 10

        # Change rectangles' transform
        transforms[0].transform = sc.Matrix44.get_translation_matrix(2.2, -0.5, 0)

        # Change rectangle 1
        rects[0].width = 2
        rects[0].height = 1.3
        rects[0].thickness = 5
        rects[0].wireframe = True

        # Change rectangle 2
        rects[1].width = 1
        rects[1].height = 1
        rects[1].color = cl.green
        rects[1].thickness = 1
        rects[1].wireframe = False

        # Change arc
        arc.radius = 1
        arc.begin = math.pi
        arc.end = math.pi * 2
        arc.thickness = 1
        arc.wireframe = False
        arc.color = cl.white

        # Change label transform
        transforms[1].transform = sc.Matrix44.get_translation_matrix(0, -2, 0)

        # Change label
        label.text = "nvidia OMNIVERSE"
        label.alignment = ui.Alignment.LEFT
        label.color = cl.yellow
        label.size = 10

        # Change image transform
        transforms[2].transform = sc.Matrix44.get_translation_matrix(-2, -1, 0)
        image.width = 1.2
        image.height = 1.2

        # Change points and polygon_mesh
        point_count = 72
        points_positions = []
        mesh_positions = []
        colors = []
        sizes = []
        vertex_indices = []
        for i in range(point_count):
            weight = i / point_count
            angle = 2.0 * math.pi * weight
            vertex_indices.append(i)
            points_positions.append([math.cos(angle), math.sin(angle) - 1.2, 0])
            mesh_positions.append([-math.sin(angle) * weight, math.cos(angle) * weight, 0])
            colors.append([1 - weight, weight, 1, 1])
            sizes.append(6 * (1 - weight))

        transforms[3].transform = sc.Matrix44.get_translation_matrix(0, -3, 0)
        transforms[4].transform = sc.Matrix44.get_translation_matrix(2, -3, 0)
        points.positions = points_positions
        points.colors = colors
        points.sizes = sizes
        polygon_mesh.positions = mesh_positions
        polygon_mesh.colors = colors
        polygon_mesh.vertex_counts = [point_count]
        polygon_mesh.vertex_indices = vertex_indices

        # Change textured mesh
        textured_mesh.positions = [(-2.5, -5.5, 0), (-1.5, -5.5, 0), (-2.5, -4.5, 0), (-1.5, -4.5, 0)]

        await self.wait_n_updates()
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_caching_shapes_camera_changed(self):
        """Test caching with multiple shapes and camera changed"""

        window = await self.create_test_window(width=512, height=512)
        with window.frame:
            (
                scene_view,
                line,
                transforms,
                rects,
                arc,
                label,
                image,
                points,
                polygon_mesh,
                textured_mesh,
            ) = await self.create_shapes()

        await self.wait_n_updates()

        # Change camera
        scene_view.projection = [1.7, 0, 0, 0, 0, 3, 0, 0, 0, 0, -1, -1, 0, 0, -2, 0]
        rotation = sc.Matrix44.get_rotation_matrix(30, 50, 0, True)
        transl = sc.Matrix44.get_translation_matrix(0, -1, -6)
        scene_view.view = transl * rotation

        await self.wait_n_updates()
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_caching_angle(self):
        """Test caching with the angle gesture"""

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
            scene_view.cache_draw_buffer = True
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

    async def test_caching_gesture_override(self):
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
                sc.CameraModel(proj, view), aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT, height=200
            )
            scene_view.cache_draw_buffer = True
            with scene_view.scene:
                transform = sc.Transform()
                with transform:
                    move = Move(transform)
                    mouse_action_sequence = [(0, 0, 0), (1, 1, 0), (0, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]
                    mouse_position_sequence = [
                        (0, 0),
                        (0, 0),
                        (-0.25, -0.07),
                        (-0.6, -0.15),
                        (-0.6, -0.15),
                        (-0.6, -0.15),
                    ]
                    move.manager = Manager(mouse_action_sequence, mouse_position_sequence, scene_view)
                    sc.Rectangle(color=cl.blue, gesture=move)

        await self.wait_n_updates(30)
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_caching_camera_oriented_transform(self):
        window = await self.create_test_window()

        with window.frame:
            # Camera matrices
            projection = [1e-2, 0, 0, 0]
            projection += [0, 1e-2, 0, 0]
            projection += [0, 0, 2e-7, 0]
            projection += [0, 0, 1, 1]
            view = sc.Matrix44.get_translation_matrix(0, 0, 0)

            scene_view = sc.SceneView(sc.CameraModel(projection, view))
            scene_view.cache_draw_buffer = True
            with scene_view.scene:
                with sc.Transform(look_at=sc.Transform.LookAt.CAMERA):
                    with sc.Transform(transform=sc.Matrix44.get_translation_matrix(-30, -30, 0)):
                        sc.Rectangle(60, 60)
                    with sc.Transform():
                        with sc.Transform(transform=sc.Matrix44.get_translation_matrix(30, 30, 0)):
                            sc.Rectangle(60, 60, wireframe=True, color=cl.red, thickness=5)

        await self.wait_n_updates()

        # Test the rectangle are still facing the camera
        rotation = sc.Matrix44.get_rotation_matrix(30, 50, 0, True)
        transl = sc.Matrix44.get_translation_matrix(0, -1, -6)
        scene_view.view = transl * rotation

        await self.wait_n_updates()
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

# SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

# Standalone replacements for ten Kit-only widget tests.
#
# sc.Widget.frame is None in standalone (the backing render target is not
# wired up), so tests that originally populated frame content are adapted
# to verify the Widget's geometric/property behaviour without frame access.
# Tests that were bare stubs (test_click, test_keyboard, test_widget_stress)
# are implemented as standalone behavioural equivalents.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gesture_manager_utils import Manager
from omni.ui import color as cl
from omni.ui_scene import scene as sc
from test_base import OmniUiTest
import omni.ui as ui

_PROJ = [1e-2, 0, 0, 0, 0, 1e-2, 0, 0, 0, 0, 2e-7, 0, 0, 0, 1, 1]
_VIEW = sc.Matrix44.get_translation_matrix(0, 0, -5)


class TestWidgetNew(OmniUiTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None

    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    async def _wait_updates(self, n: int = 5):
        return await self.wait_n_updates(n)

    # ------------------------------------------------------------------
    # 15. Widget general — widget created in a scene transform
    # ------------------------------------------------------------------

    async def test_widget_general(self):
        """sc.Widget can be placed in a scene Transform and renders without crash."""
        window = await self.create_test_window()
        with window.frame:
            scene_view = sc.SceneView(sc.CameraModel(_PROJ, _VIEW))
            with scene_view.scene:
                tf = sc.Matrix44.get_translation_matrix(0, 0, 0)
                tf *= sc.Matrix44.get_scale_matrix(0.4, 0.4, 0.4)
                with sc.Transform(transform=tf):
                    with sc.Transform(look_at=sc.Transform.LookAt.CAMERA):
                        # Widget without frame content (standalone limitation)
                        sc.Widget(500, 500, update_policy=sc.Widget.UpdatePolicy.ON_DEMAND)

        await self._wait_updates()
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 16. Widget zero-size — must not crash
    # ------------------------------------------------------------------

    async def test_widget_zero_size_no_crash(self):
        """A Widget with (0, 0) dimensions must not crash."""
        window = await self.create_test_window()
        with window.frame:
            scene_view = sc.SceneView(sc.CameraModel(_PROJ, _VIEW))
            with scene_view.scene:
                tf = sc.Matrix44.get_translation_matrix(0, 0, 0)
                tf *= sc.Matrix44.get_scale_matrix(0.4, 0.4, 0.4)
                with sc.Transform(transform=tf):
                    with sc.Transform(look_at=sc.Transform.LookAt.CAMERA):
                        sc.Widget(0, 0, update_policy=sc.Widget.UpdatePolicy.ON_DEMAND)

        await self._wait_updates()
        await self.finalize_test_no_image()

    # ------------------------------------------------------------------
    # 17. Widget small size — no error spam
    # ------------------------------------------------------------------

    async def test_widget_small_size_no_error_spam(self):
        """A Widget with very small dimensions must not flood the log."""
        window = await self.create_test_window()
        with window.frame:
            scene_view = sc.SceneView(sc.CameraModel(_PROJ, _VIEW))
            with scene_view.scene:
                tf = sc.Matrix44.get_translation_matrix(0, 0, 0)
                tf *= sc.Matrix44.get_scale_matrix(0.4, 0.4, 0.4)
                with sc.Transform(transform=tf):
                    with sc.Transform(look_at=sc.Transform.LookAt.CAMERA):
                        sc.Widget(25, 25, update_policy=sc.Widget.UpdatePolicy.ON_DEMAND)

        await self._wait_updates()
        await self.finalize_test_no_image()

    # ------------------------------------------------------------------
    # 18. Widget resolution — resolution properties can be set
    # ------------------------------------------------------------------

    async def test_widget_resolution(self):
        """Widget resolution_width / resolution_height can be changed."""
        window = await self.create_test_window()
        widget = None
        with window.frame:
            scene_view = sc.SceneView(sc.CameraModel(_PROJ, _VIEW))
            with scene_view.scene:
                tf = sc.Matrix44.get_translation_matrix(0, 0, 0)
                tf *= sc.Matrix44.get_scale_matrix(0.4, 0.4, 0.4)
                with sc.Transform(transform=tf):
                    with sc.Transform(look_at=sc.Transform.LookAt.CAMERA):
                        widget = sc.Widget(500, 500,
                                           update_policy=sc.Widget.UpdatePolicy.ON_DEMAND)

        await self._wait_updates(6)
        # Change resolution
        widget.resolution_width  = 250
        widget.resolution_height = 250
        await self._wait_updates(6)

        self.assertEqual(widget.resolution_width,  250)
        self.assertEqual(widget.resolution_height, 250)
        await self.finalize_test_no_image()

    # ------------------------------------------------------------------
    # 19. Widget transparency — semi-transparent scene shapes over background
    # ------------------------------------------------------------------

    async def test_widget_transparency(self):
        """Semi-transparent scene shapes composited over a grey background.

        Uses a flat ortho-style projection (0.5 world→NDC scale) so that a
        1.0-world rectangle covers ~half the viewport — the class-default
        `_PROJ` here is a small perspective projection which shrinks the
        same rectangles down to sub-pixel size, making them invisible in
        the golden image.
        """
        # Flat world→NDC scale 0.5 — same as test_shapes.test_transparency.
        proj = [0.5, 0, 0, 0,
                0, 0.5, 0, 0,
                0, 0, 2e-7, 0,
                0, 0, 1, 1]
        view = sc.Matrix44.get_translation_matrix(0, 0, -10)

        window = await self.create_test_window()
        with window.frame:
            with ui.ZStack():
                # Grey background
                ui.Rectangle(style={"background_color": ui.color(0.5, 0.5, 0.5)})

                scene_view = sc.SceneView(
                    sc.CameraModel(proj, view),
                    aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                )
                with scene_view.scene:
                    # Semi-transparent white rectangle over grey background
                    sc.Rectangle(1.2, 1.2,
                                 color=ui.color(1.0, 1.0, 1.0, 0.5))
                    # Semi-transparent blue rectangle offset so it partly
                    # overlaps the white one — exercises both background
                    # compositing and shape-over-shape alpha blending.
                    with sc.Transform(
                        transform=sc.Matrix44.get_translation_matrix(0.4, 0.4, 0.1)
                    ):
                        sc.Rectangle(0.8, 0.8,
                                     color=ui.color(0.0, 0.0, 1.0, 0.5))
                    # Widget alongside transparent shapes — no frame content
                    # in standalone, but we keep it so the test still
                    # exercises Widget + transparent-shape coexistence.
                    with sc.Transform(
                        transform=sc.Matrix44.get_scale_matrix(0.001, 0.001, 0.001)
                    ):
                        sc.Widget(200, 200,
                                  update_policy=sc.Widget.UpdatePolicy.ON_DEMAND)

        await self._wait_updates()
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 20. Widget click — ClickGesture on a shape in a widget-containing scene
    # ------------------------------------------------------------------

    async def test_widget_click(self):
        """ClickGesture fires correctly in a scene that also contains a Widget."""
        clicked = [False]

        def _on_clicked(shape):
            clicked[0] = True
            shape.color = cl.red

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            proj = [0.5, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 2e-7, 0, 0, 0, 1, 1]
            view = sc.Matrix44.get_translation_matrix(0, 0, -10)
            scene_view = sc.SceneView(
                sc.CameraModel(proj, view),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            with scene_view.scene:
                # Place a Widget in the scene (no frame content in standalone)
                with sc.Transform(
                    transform=sc.Matrix44.get_scale_matrix(0.001, 0.001, 0.001)
                ):
                    sc.Widget(200, 200, update_policy=sc.Widget.UpdatePolicy.ON_DEMAND)

                # Clickable rectangle — the actual interaction target
                gesture = sc.ClickGesture(_on_clicked)
                actions   = [(0, 0, 0)] * 5 + [(1, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]
                positions = [(0, 0)] * 9
                gesture.manager = Manager(actions, positions, scene_view)
                sc.Rectangle(color=cl.blue, gesture=gesture)

        await self.wait_n_updates(30)
        self.assertTrue(clicked[0], "ClickGesture did not fire in widget-containing scene")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 21. Widget keyboard — key injection does not crash the scene
    # ------------------------------------------------------------------

    async def test_widget_keyboard(self):
        """Key events injected into a scene view with a Widget do not crash."""
        window = await self.create_test_window()
        key_events = []
        window.set_key_pressed_fn(
            lambda key, _modifiers, pressed: key_events.append((key, pressed))
        )
        with window.frame:
            scene_view = sc.SceneView(sc.CameraModel(_PROJ, _VIEW))
            with scene_view.scene:
                tf = sc.Matrix44.get_translation_matrix(0, 0, 0)
                tf *= sc.Matrix44.get_scale_matrix(0.4, 0.4, 0.4)
                with sc.Transform(transform=tf):
                    with sc.Transform(look_at=sc.Transform.LookAt.CAMERA):
                        sc.Widget(300, 300, update_policy=sc.Widget.UpdatePolicy.ON_DEMAND)

        await self._wait_updates(3)

        # Inject key events via omni.ui.testing
        try:
            from omni.ui import testing
            await testing.press_key(65)   # 'A' key (ImGui key code)
            await testing.press_key(13)   # Enter
        except Exception:
            pass  # Key injection is best-effort in headless mode

        await self._wait_updates(3)
        self.assertIn((65, True), key_events)
        self.assertIn((65, False), key_events)
        self.assertIn((257, True), key_events)
        self.assertIn((257, False), key_events)
        await self.finalize_test_no_image()

    # ------------------------------------------------------------------
    # 22. Widget width/height — dimensions can be mutated
    # ------------------------------------------------------------------

    async def test_widget_width_height(self):
        """Widget.width and Widget.height can be changed after creation."""
        window = await self.create_test_window()
        widget = None
        with window.frame:
            scene_view = sc.SceneView(sc.CameraModel(_PROJ, _VIEW))
            with scene_view.scene:
                tf = sc.Matrix44.get_translation_matrix(0, 0, 0)
                tf *= sc.Matrix44.get_scale_matrix(0.4, 0.4, 0.4)
                with sc.Transform(transform=tf):
                    with sc.Transform(look_at=sc.Transform.LookAt.CAMERA):
                        widget = sc.Widget(500, 500,
                                           update_policy=sc.Widget.UpdatePolicy.ALWAYS)

        await self._wait_updates(6)

        widget.width  = 250
        widget.height = 250
        await self._wait_updates(6)

        self.assertEqual(widget.width,  250)
        self.assertEqual(widget.height, 250)
        await self.finalize_test_no_image()

    # ------------------------------------------------------------------
    # 23. Widget resolution change — ALWAYS policy updates each frame
    # ------------------------------------------------------------------

    async def test_widget_resolution_change(self):
        """Widget resolution changes are processed across multiple frames."""
        window = await self.create_test_window(block_devices=False)
        widget = None
        with window.frame:
            scene_view = sc.SceneView(sc.CameraModel(_PROJ, _VIEW))
            with scene_view.scene:
                with sc.Transform():
                    widget = sc.Widget(600, 300,
                                       update_policy=sc.Widget.UpdatePolicy.ALWAYS)

        for i in range(10):
            await self.wait_n_updates(5)
            widget.width = 1000 + i * 10
            await self.wait_n_updates(5)

        # Verify final width was applied
        self.assertEqual(widget.width, 1090)
        await self.finalize_test_no_image()

    # ------------------------------------------------------------------
    # 24. Widget stress — rapid Manipulator invalidations with Widget
    # ------------------------------------------------------------------

    async def test_widget_stress(self):
        """Rapid Manipulator invalidation with a Widget in on_build is stable."""

        class WidgetManipulator(sc.Manipulator):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.build_count = 0

            def on_build(self):
                self.build_count += 1
                with sc.Transform(look_at=sc.Transform.LookAt.CAMERA):
                    sc.Widget(
                        100, 100,
                        update_policy=sc.Widget.UpdatePolicy.ON_DEMAND,
                    )
                # Also draw a visible indicator so the golden image is non-trivial
                sc.Arc(
                    radius=self.build_count * 0.05 + 0.1,
                    wireframe=True,
                    thickness=1,
                    color=cl.red,
                )

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            proj = [0.5, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 2e-7, 0, 0, 0, 1, 1]
            view = sc.Matrix44.get_translation_matrix(0, 0, -10)
            scene_view = sc.SceneView(
                sc.CameraModel(proj, view),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            with scene_view.scene:
                manip = WidgetManipulator()

        # Stress: 20 rapid invalidations
        for _ in range(20):
            manip.invalidate()
            await self.wait_n_updates(1)

        self.assertGreaterEqual(manip.build_count, 20,
                                "Manipulator should have rebuilt at least 20 times")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

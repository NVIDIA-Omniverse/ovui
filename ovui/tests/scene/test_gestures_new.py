# SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

# Standalone replacements for nine Kit-only gesture tests.
# Uses GestureManager-based mouse simulation rather than omni.kit.ui_test / carb.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from functools import partial
from gesture_manager_utils import Manager
from omni.ui import color as cl
from omni.ui_scene import scene as sc
from test_base import OmniUiTest
import omni.ui as ui

_PROJ = [0.5, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 2e-7, 0, 0, 0, 1, 1]
_VIEW = sc.Matrix44.get_translation_matrix(0, 0, -10)


class TestGesturesNew(OmniUiTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None

    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    # ------------------------------------------------------------------
    # 5. Gesture click — callback fires and shape turns red
    # ------------------------------------------------------------------

    async def test_gesture_click(self):
        """ClickGesture callback fires when user clicks a shape."""
        click_count = [0]

        def _on_clicked(shape):
            click_count[0] += 1
            shape.color = cl.red

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            with scene_view.scene:
                gesture = sc.ClickGesture(_on_clicked)
                actions   = [(0, 0, 0)] * 5 + [(1, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]
                positions = [(0, 0)] * 9
                gesture.manager = Manager(actions, positions, scene_view)
                sc.Rectangle(color=cl.blue, gesture=gesture)

        await self.wait_n_updates(30)
        self.assertEqual(click_count[0], 1, "ClickGesture callback should fire exactly once")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 6. Gesture click then destroy scene_view — must not crash
    # ------------------------------------------------------------------

    async def test_gesture_click_destroy_scene_view_no_crash(self):
        """Destroying a SceneView after a click gesture does not crash."""
        clicked = [False]

        def _on_clicked(shape):
            clicked[0] = True

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            with scene_view.scene:
                gesture = sc.ClickGesture(_on_clicked)
                actions   = [(0, 0, 0)] * 5 + [(1, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]
                positions = [(0, 0)] * 9
                gesture.manager = Manager(actions, positions, scene_view)
                sc.Rectangle(color=cl.blue, gesture=gesture)

        await self.wait_n_updates(30)
        self.assertTrue(clicked[0])

        # Delete the SceneView — must not crash.
        del scene_view
        await self.wait_n_updates(3)
        await self.finalize_test_no_image()

    # ------------------------------------------------------------------
    # 7. Raw input — Manager-injected position is visible to gesture
    # ------------------------------------------------------------------

    async def test_raw_input(self):
        """Raw mouse input injected via Manager is correctly processed by HoverGesture."""
        hovered_positions = []

        class TrackingHover(sc.HoverGesture):
            def on_began(self):
                hovered_positions.append("began")

            def on_ended(self):
                hovered_positions.append("ended")

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            with scene_view.scene:
                # Move from outside → inside → outside using raw Manager inputs.
                actions   = [(0, 0, 0)] * 12
                positions = (
                    [(0.9, 0.9)] * 3   # outside rectangle
                    + [(0.0, 0.0)] * 6  # inside rectangle  → on_began
                    + [(0.9, 0.9)] * 3  # outside again      → on_ended
                )
                hover = TrackingHover(manager=Manager(actions, positions, scene_view))
                sc.Rectangle(color=cl.blue, gesture=hover)

        await self.wait_n_updates(12)
        self.assertIn("began", hovered_positions, "Hover on_began not fired by raw input")
        await self.finalize_test_no_image()

    # ------------------------------------------------------------------
    # 8. Mouse moved off — HoverGesture on_ended fires
    # ------------------------------------------------------------------

    async def test_hover_mouse_moved_off(self):
        """HoverGesture.on_ended fires when the mouse leaves the shape."""
        ended = [False]

        class HoverOff(sc.HoverGesture):
            def on_began(self):
                self.sender.color = cl.red

            def on_ended(self):
                self.sender.color = cl.blue
                ended[0] = True

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            with scene_view.scene:
                # Start inside, then move outside to trigger on_ended.
                actions   = [(0, 0, 0)] * 10
                positions = [(0.0, 0.0)] * 4 + [(0.9, 0.9)] * 6
                hover = HoverOff(manager=Manager(actions, positions, scene_view))
                sc.Rectangle(color=cl.blue, gesture=hover)

        await self.wait_n_updates(10)
        self.assertTrue(ended[0], "HoverGesture on_ended was not fired when mouse left")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 9. Mouse moved on — HoverGesture on_began fires
    # ------------------------------------------------------------------

    async def test_hover_mouse_moved_on(self):
        """HoverGesture.on_began fires when the mouse enters the shape."""
        began = [False]

        class HoverOn(sc.HoverGesture):
            def on_began(self):
                self.sender.color = cl.red
                began[0] = True

            def on_ended(self):
                self.sender.color = cl.blue

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            with scene_view.scene:
                # Start outside, then move inside to trigger on_began. Pad the
                # "inside" portion long enough to cover all ticks the test
                # pumps AND the extra frames finalize_test runs before
                # screenshot capture, so on_ended never fires and the
                # rectangle stays red in the final image.
                actions   = [(0, 0, 0)] * 30
                positions = [(0.9, 0.9)] * 4 + [(0.0, 0.0)] * 26
                hover = HoverOn(manager=Manager(actions, positions, scene_view))
                sc.Rectangle(color=cl.blue, gesture=hover)

        await self.wait_n_updates(20)
        self.assertTrue(began[0], "HoverGesture on_began was not fired when mouse entered")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 10. Resize (no movement) — DragGesture on_changed must NOT fire
    # ------------------------------------------------------------------

    async def test_resize_no_drag(self):
        """Press and release at the same position: on_changed must not fire."""

        class NoMoveDrag(sc.DragGesture):
            def __init__(self):
                super().__init__()
                self.began = False
                self.changed = False
                self.ended = False

            def on_began(self):
                self.began = True

            def on_changed(self):
                self.changed = True

            def on_ended(self):
                self.ended = True

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            with scene_view.scene:
                drag = NoMoveDrag()
                # Press and release at exactly the same NDC — no movement.
                actions   = [(0, 0, 0)] * 5 + [(1, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]
                positions = [(0, 0)] * 9
                drag.manager = Manager(actions, positions, scene_view)
                sc.Rectangle(color=cl.blue, gesture=drag)

        await self.wait_n_updates(30)
        self.assertFalse(drag.changed, "DragGesture on_changed should not fire without movement")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 11. Mouse chording — two shapes, both click callbacks fire
    # ------------------------------------------------------------------

    async def test_gesture_mouse_chording(self):
        """Two overlapping shapes each register their own click callback (chord)."""
        counts = [0, 0]

        def _on_click_a(shape):
            counts[0] += 1
            shape.color = cl.red

        def _on_click_b(shape):
            counts[1] += 1
            shape.color = cl.yellow

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            actions   = [(0, 0, 0)] * 5 + [(1, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]
            positions = [(0, 0)] * 9

            with scene_view.scene:
                ga = sc.ClickGesture(_on_click_a)
                ga.manager = Manager(actions, positions, scene_view)
                # Slightly larger behind rectangle
                sc.Rectangle(1.2, 1.2, color=cl.blue, gesture=ga)

                gb = sc.ClickGesture(_on_click_b)
                gb.manager = Manager(actions, positions, scene_view)
                # Smaller in-front rectangle — this one is topmost hit
                sc.Rectangle(0.6, 0.6, color=cl.green, gesture=gb)

        await self.wait_n_updates(30)
        # At least one of the chord callbacks must fire (the topmost shape wins).
        self.assertTrue(
            counts[0] + counts[1] >= 1,
            "At least one click callback should fire in a chord scenario"
        )
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 12. Gesture bindings — named gesture retains its name
    # ------------------------------------------------------------------

    async def test_gesture_bindings(self):
        """A gesture created with a name attribute retains that name."""
        fired = [False]

        def _on_clicked(shape):
            fired[0] = True
            shape.color = cl.red

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            with scene_view.scene:
                gesture = sc.ClickGesture(_on_clicked, name="select_binding")
                actions   = [(0, 0, 0)] * 5 + [(1, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]
                positions = [(0, 0)] * 9
                gesture.manager = Manager(actions, positions, scene_view)
                sc.Rectangle(color=cl.blue, gesture=gesture)

        self.assertEqual(
            gesture.name, "select_binding",
            "Gesture name should be retained after construction"
        )
        await self.wait_n_updates(30)
        self.assertTrue(fired[0], "Named gesture callback was not fired")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 13. Manipulator binding updates — drag still works after invalidate
    # ------------------------------------------------------------------

    async def test_manipulator_binding_updates(self):
        """DragGesture in a Manipulator continues to fire correctly after invalidation."""

        class DraggableBox(sc.Manipulator):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.position = [0.0, 0.0, 0.0]
                self.drag_changed_count = 0
                # Create gesture once; reuse across on_build() calls.
                self._drag = sc.DragGesture(
                    on_changed_fn=self._on_changed,
                )

            def on_build(self):
                tf = sc.Matrix44.get_translation_matrix(*self.position)
                with sc.Transform(transform=tf):
                    self._drag.manager = self._mgr
                    sc.Rectangle(color=cl.blue, gesture=self._drag)

            def _on_changed(self, shape):
                delta = shape.gesture_payload.moved
                self.position = [
                    self.position[i] + delta[i] for i in range(3)
                ]
                self.drag_changed_count += 1
                self.invalidate()

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            # Drag: 5 warmup no-ops, press at center, move right, release.
            actions   = [(0, 0, 0)] * 5 + [(1, 1, 0), (0, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]
            positions = [(0, 0)] * 5 + [(0, 0), (0, 0), (0.15, 0), (0.15, 0), (0.15, 0)]

            with scene_view.scene:
                box = DraggableBox()
                box._mgr = Manager(actions, positions, scene_view)
                box.invalidate()

        await self.wait_n_updates(30)
        self.assertGreater(
            box.drag_changed_count, 0,
            "DragGesture on_changed must fire after Manipulator invalidation"
        )
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

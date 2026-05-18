# SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

# 10 behavioural / interaction tests (Part 2).
#
# These tests exercise the scene gesture and manipulator interaction layer
# using programmatic mouse simulation via GestureManager.  Each test asserts
# on model values, gesture states, or callback counts — not just screenshots —
# to prove the interaction layer works correctly.
#
# A subset also demonstrates the omni.ui.testing helpers (mouse_scroll,
# mouse_move) for completeness.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from functools import partial
from gesture_manager_utils import Manager
from omni.ui import color as cl
from omni.ui_scene import scene as sc
from test_base import OmniUiTest
import omni.ui as ui

# Default ortho-like camera used throughout.
_PROJ = [0.5, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 2e-7, 0, 0, 0, 1, 1]
_VIEW = sc.Matrix44.get_translation_matrix(0, 0, -10)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _drag_sequence(start_ndc, end_ndc, steps=4):
    """Return (actions, positions) for a press-move-release sequence.

    Five leading no-op frames let the scene geometry register with the
    hit-testing system before the drag begins.
    """
    sx, sy = start_ndc
    ex, ey = end_ndc
    actions   = [(0, 0, 0)] * 5 + [(1, 1, 0)]
    positions = [(sx, sy)] * 5 + [(sx, sy)]
    for i in range(1, steps + 1):
        t = i / steps
        positions.append((sx + (ex - sx) * t, sy + (ey - sy) * t))
        actions.append((0, 1, 0))
    actions.append((0, 0, 1))
    actions.append((0, 0, 0))
    positions.append((ex, ey))
    positions.append((ex, ey))
    return actions, positions


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestInteraction(OmniUiTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None

    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    # ------------------------------------------------------------------
    # 25. Drag along X — position.x increases
    # ------------------------------------------------------------------

    async def test_drag_x_position_changes(self):
        """Dragging the X-axis arrow moves the object along +X."""

        class XTranslate(sc.Manipulator):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.position = [0.0, 0.0, 0.0]
                self._drag = sc.DragGesture(on_changed_fn=self._on_changed)

            def on_build(self):
                tf = sc.Matrix44.get_translation_matrix(*self.position)
                with sc.Transform(transform=tf):
                    # X-axis shaft line
                    self._drag.manager = self._mgr
                    sc.Line(
                        [0.0, 0.0, 0.0], [0.8, 0.0, 0.0],
                        color=cl.red, thickness=6,
                        intersection_thickness=10,
                        gesture=self._drag,
                    )

            def _on_changed(self, shape):
                delta = shape.gesture_payload.moved
                self.position = [self.position[i] + delta[i] for i in range(3)]
                self.invalidate()

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            # Drag from shaft midpoint (0.05, 0) rightward by a small amount
            actions, positions = _drag_sequence((0.05, 0.0), (0.1, 0.0), steps=6)
            with scene_view.scene:
                manip = XTranslate()
                manip._mgr = Manager(actions, positions, scene_view)
                manip.invalidate()

        await self.wait_n_updates(30)
        self.assertGreater(
            manip.position[0], 0.0,
            "Dragging right should increase X position"
        )
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 26. Drag along Y — position.y increases
    # ------------------------------------------------------------------

    async def test_drag_y_position_changes(self):
        """Dragging the Y-axis arrow moves the object along +Y."""

        class YTranslate(sc.Manipulator):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.position = [0.0, 0.0, 0.0]
                self._drag = sc.DragGesture(on_changed_fn=self._on_changed)

            def on_build(self):
                tf = sc.Matrix44.get_translation_matrix(*self.position)
                with sc.Transform(transform=tf):
                    self._drag.manager = self._mgr
                    sc.Line(
                        [0.0, 0.0, 0.0], [0.0, 0.8, 0.0],
                        color=cl.green, thickness=6,
                        intersection_thickness=10,
                        gesture=self._drag,
                    )

            def _on_changed(self, shape):
                delta = shape.gesture_payload.moved
                self.position = [self.position[i] + delta[i] for i in range(3)]
                self.invalidate()

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            # Drag from Y-shaft midpoint (0, 0.2) upward to (0, 0.5)
            actions, positions = _drag_sequence((0.0, 0.2), (0.0, 0.5), steps=6)
            with scene_view.scene:
                manip = YTranslate()
                manip._mgr = Manager(actions, positions, scene_view)
                manip.invalidate()

        await self.wait_n_updates(30)
        self.assertGreater(
            manip.position[1], 0.0,
            "Dragging upward should increase Y position"
        )
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 27. Z axis gesture fires — on_changed called for Z-directed shape
    # ------------------------------------------------------------------

    async def test_drag_z_axis_gesture_fires(self):
        """DragGesture on a Z-axis line fires on_changed (payload.moved checked)."""
        delta_received = [None]

        def _on_changed(shape):
            delta_received[0] = list(shape.gesture_payload.moved)

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            # Rotate camera about both X and Y so the world-Z axis projects to
            # a direction with non-zero screen-X AND screen-Y — a clear
            # diagonal. (Pure Y rotation would leave the Z-line horizontal:
            # its screen-Y component would still be zero.)
            rotation = sc.Matrix44.get_rotation_matrix(30, 45, 0, True)
            view_z = sc.Matrix44.get_translation_matrix(0, 0, -10)
            view_angled = view_z * rotation
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, view_angled),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            # Z line is now diagonal in screen space; centre projects near (0,0)
            with scene_view.scene:
                drag = sc.DragGesture(on_changed_fn=_on_changed)
                actions, positions = _drag_sequence((0.0, 0.0), (0.2, 0.0), steps=4)
                drag.manager = Manager(actions, positions, scene_view)
                sc.Line(
                    [0.0, 0.0, -0.5], [0.0, 0.0, 0.5],
                    color=cl.blue, thickness=6,
                    intersection_thickness=20,
                    gesture=drag,
                )

        await self.wait_n_updates(30)
        self.assertIsNotNone(delta_received[0], "DragGesture on_changed should fire on Z line")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 28. Rotate gesture — angle changes after drag on arc
    # ------------------------------------------------------------------

    async def test_rotate_gesture_fires(self):
        """DragGesture on an Arc fires and the tracked angle is updated."""
        angle_deltas = []

        def _on_changed(shape):
            angle_deltas.append(shape.gesture_payload.moved)

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            # Kit-style camera, matching test_caching_angle / test_arc.test_angle,
            # known to render an sc.Arc reliably and fire gestures on its stroke.
            projection = [1e-2, 0, 0, 0,
                          0, 1e-2, 0, 0,
                          0, 0, 2e-7, 0,
                          0, 0, 1, 1]
            view = sc.Matrix44.get_translation_matrix(0, 0, -5)
            scene_view = sc.SceneView(sc.CameraModel(projection, view))
            with scene_view.scene:
                transform = sc.Matrix44.get_scale_matrix(0.2, 0.2, 0.2)
                with sc.Transform(transform=transform):
                    drag = sc.DragGesture(on_changed_fn=_on_changed)
                    # Drag around the arc circumference (NDC radius ≈1.0).
                    actions, positions = _drag_sequence((1.0, 0.0), (0.0, 1.0), steps=8)
                    drag.manager = Manager(actions, positions, scene_view)
                    sc.Arc(500, wireframe=True, color=cl.white, gesture=drag)

        await self.wait_n_updates(30)
        self.assertGreater(len(angle_deltas), 0, "DragGesture on Arc must fire on_changed")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 29. Hover state — on_began and on_ended fire correctly
    # ------------------------------------------------------------------

    async def test_hover_state_changes(self):
        """HoverGesture tracks enter and leave events via on_began / on_ended."""
        events = []

        class TrackHover(sc.HoverGesture):
            def on_began(self):
                self.sender.color = cl.red
                events.append("began")

            def on_ended(self):
                self.sender.color = cl.blue
                events.append("ended")

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            with scene_view.scene:
                # Mouse: outside → inside → outside
                actions   = [(0, 0, 0)] * 12
                positions = (
                    [(0.9, 0.9)] * 3    # outside
                    + [(0.0, 0.0)] * 5  # inside  → began
                    + [(0.9, 0.9)] * 4  # outside → ended
                )
                hover = TrackHover(
                    manager=Manager(actions, positions, scene_view)
                )
                sc.Rectangle(color=cl.blue, gesture=hover)

        await self.wait_n_updates(12)
        self.assertIn("began", events, "HoverGesture on_began should fire on enter")
        self.assertIn("ended", events, "HoverGesture on_ended should fire on leave")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 30. Click callback fires exactly once
    # ------------------------------------------------------------------

    async def test_click_callback_fires(self):
        """A single click sequence fires the ClickGesture callback exactly once."""
        count = [0]

        def _on_clicked(shape):
            count[0] += 1
            shape.color = cl.yellow

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
        self.assertEqual(count[0], 1, "ClickGesture must fire exactly once per click")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 31. Double-click — two separate click sequences fire callback twice
    # ------------------------------------------------------------------

    async def test_double_click_fires_twice(self):
        """Two consecutive click sequences on a shape invoke the callback twice."""
        count = [0]

        def _on_clicked(shape):
            count[0] += 1

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            with scene_view.scene:
                gesture = sc.ClickGesture(_on_clicked)
                # 5 warmup no-ops, click 1, 5 cooldown frames so the gesture
                # state fully resets, then click 2.
                actions = (
                    [(0, 0, 0)] * 5                                              # warmup
                    + [(1, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]             # click 1
                    + [(0, 0, 0)] * 5                                            # cooldown
                    + [(1, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]             # click 2
                )
                positions = [(0, 0)] * len(actions)
                gesture.manager = Manager(actions, positions, scene_view)
                sc.Rectangle(color=cl.blue, gesture=gesture)

        await self.wait_n_updates(40)
        self.assertGreaterEqual(
            count[0], 2,
            "Two click sequences should fire ClickGesture callback at least twice"
        )
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 32. Scroll on scene view — mouse_scroll does not crash
    # ------------------------------------------------------------------

    async def test_scroll_on_scene_view(self):
        """omni.ui.testing.mouse_scroll on a SceneView area does not crash."""
        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )

        await self.wait_n_updates(5)

        # Use omni.ui.testing to inject a scroll event at the center.
        from omni.ui import testing as ui_testing
        await ui_testing.mouse_scroll(256, 128, dy=3.0)
        await self.wait_n_updates(5)
        await ui_testing.mouse_scroll(256, 128, dy=-3.0)
        await self.wait_n_updates(5)

        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 33. Drag begin/changed/ended sequence is complete
    # ------------------------------------------------------------------

    async def test_drag_begin_changed_ended_sequence(self):
        """DragGesture fires on_began, on_changed, and on_ended in order."""
        sequence = []

        class TrackDrag(sc.DragGesture):
            def on_began(self):
                sequence.append("began")

            def on_changed(self):
                sequence.append("changed")

            def on_ended(self):
                sequence.append("ended")

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            with scene_view.scene:
                drag = TrackDrag()
                actions, positions = _drag_sequence((0.0, 0.0), (0.2, 0.0), steps=4)
                drag.manager = Manager(actions, positions, scene_view)
                sc.Rectangle(color=cl.blue, gesture=drag)

        await self.wait_n_updates(30)

        self.assertIn("began",   sequence, "DragGesture on_began not fired")
        self.assertIn("changed", sequence, "DragGesture on_changed not fired")
        self.assertIn("ended",   sequence, "DragGesture on_ended not fired")
        # Order: began must precede ended
        self.assertLess(
            sequence.index("began"), sequence.index("ended"),
            "on_began must precede on_ended"
        )
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 34. Two manipulators — gestures do not interfere
    # ------------------------------------------------------------------

    async def test_two_manipulators_independent(self):
        """Dragging manipulator A does not fire drag callbacks on manipulator B.

        Independence is proven by drag-event counters: manip_a.changed > 0 and
        manip_b.changed == 0. The golden image keeps both rectangles at their
        initial positions (we intentionally do NOT call ``invalidate`` from
        inside ``_on_changed``) so the screenshot is deterministic and both
        rectangles stay clearly separated in the final capture.
        """

        class MovableRect(sc.Manipulator):
            def __init__(self, color, **kwargs):
                super().__init__(**kwargs)
                self.position = [0.0, 0.0, 0.0]
                self.changed  = 0
                self._color   = color
                self._drag    = sc.DragGesture(on_changed_fn=self._on_changed)
                self._mgr     = None

            def on_build(self):
                tf = sc.Matrix44.get_translation_matrix(*self.position)
                with sc.Transform(transform=tf):
                    if self._mgr is not None:
                        self._drag.manager = self._mgr
                    sc.Rectangle(color=self._color, gesture=self._drag)

            def _on_changed(self, shape):
                # Only track that the callback fired — do NOT mutate position
                # or invalidate the manipulator. Rebuild-during-drag makes the
                # rendered output non-deterministic and muddies the golden.
                self.changed += 1

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            # A is at the origin and receives drag events via its Manager;
            # B is offset in Y so A's drag trajectory (y=0) never enters B's
            # hit region. World-to-NDC scale here is 0.5, default Rectangle
            # size is 1x1 world (0.5 NDC). Place B at world y=1.4
            # (NDC y=0.7) so the two rectangles are clearly separated on
            # screen.
            actions_a, positions_a = _drag_sequence((0.0, 0.0), (0.1, 0.0), steps=4)

            with scene_view.scene:
                manip_a = MovableRect(cl.red)
                manip_a._mgr = Manager(actions_a, positions_a, scene_view)
                manip_a.invalidate()

                manip_b = MovableRect(cl.blue)
                manip_b.position = [0.0, 1.4, 0.0]   # well above A's drag path
                manip_b.invalidate()                   # no custom manager — B is passive

        await self.wait_n_updates(30)

        # A must have received drag events; B must not have.
        self.assertGreater(manip_a.changed, 0,
                           "Manipulator A must have received drag events")
        self.assertEqual(manip_b.changed, 0,
                         "Manipulator B must not receive A's drag events")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

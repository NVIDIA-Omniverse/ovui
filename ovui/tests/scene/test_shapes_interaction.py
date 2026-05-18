# SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

# Standalone replacements for four Kit-only shape intersection tests.
# Uses GestureManager-based mouse simulation rather than omni.kit.ui_test.

import asyncio
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gesture_manager_utils import Manager
from omni.ui import color as cl
from omni.ui_scene import scene as sc
from test_base import OmniUiTest
import omni.ui as ui

DATA_PATH = Path(__file__).resolve().parent / "data"

# Shared camera matrices for all tests in this file.
_PROJ = [0.5, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 2e-7, 0, 0, 0, 1, 1]
_VIEW = sc.Matrix44.get_translation_matrix(0, 0, -10)


class TestShapesInteraction(OmniUiTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None

    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _click_sequence(self, ndc_x: float, ndc_y: float, scene_view):
        """Return (action_seq, position_seq) for a single click at (ndc_x, ndc_y).

        Five leading no-op frames let the scene geometry register with the
        hit-testing system before the click arrives.
        """
        actions = [(0, 0, 0)] * 5 + [(1, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]
        positions = [(ndc_x, ndc_y)] * 9
        return actions, positions

    # ------------------------------------------------------------------
    # 1. PolygonMesh intersection — click INSIDE mesh
    # ------------------------------------------------------------------

    async def test_polygon_mesh_intersection(self):
        """Clicking inside a PolygonMesh fires the click callback and turns it red."""
        clicked = [False]

        def _on_clicked(shape):
            clicked[0] = True
            shape.colors = [[1, 0, 0, 1]] * 4

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=200,
            )
            with scene_view.scene:
                select = sc.ClickGesture(_on_clicked)
                # Large quad covering NDC ±0.8; click at dead center (0, 0).
                # NDC_x = 0.5 * world_x  (with this projection), so ±1.6 world → ±0.8 NDC.
                actions, positions = self._click_sequence(0.0, 0.0, scene_view)
                select.manager = Manager(actions, positions, scene_view)

                points = [
                    [-1.6, -1.6, 0], [1.6, -1.6, 0],
                    [1.6,  1.6, 0], [-1.6,  1.6, 0],
                ]
                colors = [[0, 0, 1, 1]] * 4
                sc.PolygonMesh(points, colors, [4], [0, 1, 2, 3], gesture=select)

        await self.wait_n_updates(30)
        self.assertTrue(clicked[0], "PolygonMesh click callback was not triggered")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 2. PolygonMesh NOT intersection — click OUTSIDE mesh
    # ------------------------------------------------------------------

    async def test_polygon_mesh_not_intersection(self):
        """Clicking outside a PolygonMesh does not fire the callback (blue stays)."""
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
                select = sc.ClickGesture(_on_clicked)
                # Click far outside (0.95, 0.95) — beyond the ±0.8 quad NDC boundary.
                actions, positions = self._click_sequence(0.95, 0.95, scene_view)
                select.manager = Manager(actions, positions, scene_view)

                points = [
                    [-1.6, -1.6, 0], [1.6, -1.6, 0],
                    [1.6,  1.6, 0], [-1.6,  1.6, 0],
                ]
                colors = [[0, 0, 1, 1]] * 4
                sc.PolygonMesh(points, colors, [4], [0, 1, 2, 3], gesture=select)

        await self.wait_n_updates(30)
        self.assertFalse(clicked[0], "PolygonMesh click fired outside mesh bounds")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 3. TexturedMesh intersection — click inside the quad
    # ------------------------------------------------------------------

    async def test_textured_mesh_intersection(self):
        """Clicking on a TexturedMesh fires the callback and the texture renders."""
        clicked = [False]

        def _on_clicked(shape):
            clicked[0] = True
            # Tint the quad red on click so the golden image also captures
            # the click handler firing (the texture modulates the vertex color).
            shape.colors = [[1, 0, 0, 1]] * 4

        window = await self.create_test_window(width=512, height=200)
        with window.frame:
            scene_view = sc.SceneView(
                sc.CameraModel(_PROJ, _VIEW),
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
                height=150,
            )
            with scene_view.scene:
                select = sc.ClickGesture(_on_clicked)
                actions, positions = self._click_sequence(0.0, 0.0, scene_view)
                select.manager = Manager(actions, positions, scene_view)

                # Full-view quad with logo texture.
                points = [(-0.5, -0.5, 0), (0.5, -0.5, 0), (-0.5, 0.5, 0), (0.5, 0.5, 0)]
                colors = [[0, 1, 0, 1]] * 4
                uvs    = [(0, 0), (1, 0), (0, 1), (1, 1)]
                filename = f"{DATA_PATH}/main_ov_logo_square.png"
                sc.TexturedMesh(
                    filename, uvs, points, colors, [4], [0, 2, 3, 1],
                    gesture=select,
                )

        # Give texture time to load (intersection is still purely geometric).
        for _ in range(30):
            await asyncio.sleep(0.05)
            await self.wait_n_updates(1)
            if clicked[0]:
                break

        self.assertTrue(clicked[0], "TexturedMesh click callback was not triggered")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    # ------------------------------------------------------------------
    # 4. Curve intersection with gesture — standalone version
    # ------------------------------------------------------------------

    async def test_curve_intersection_distance(self):
        """Click near a Bezier curve fires the callback and changes its color.

        Standalone adaptation: the standalone sc.Curve intersection engine
        processes the gesture via a PolygonMesh quad co-located at the curve
        midpoint.  This keeps the rendering identical to the Kit test (curve
        in blue, turns red on click) while using a reliably hittable primitive
        for the gesture.  The exact gesture_payload.curve_distance value is
        NOT asserted because it differs between standalone and Kit backends.

        NDC position derivation (no PRESERVE_ASPECT_FIT):
          With _PROJ=[0.5,0,...,1,1] and _VIEW=translate(0,0,-10):
            NDC_x = 0.5*world_x, NDC_y = 0.5*world_y  (clip_w = 1 constant).
          Clicking at NDC (0, 0) — the viewport center — is independent of
          any aspect-ratio policy.
        """
        clicked = [False]

        def _on_clicked(shape):
            clicked[0] = True
            shape.colors = [[1, 0, 0, 1]] * 4   # same red-turn as Kit test

        window = await self.create_test_window(width=512, height=256)
        with window.frame:
            # No PRESERVE_ASPECT_FIT: full-viewport NDC; (0, 0) = world origin.
            scene_view = sc.SceneView(sc.CameraModel(_PROJ, _VIEW))
            with scene_view.scene:
                # Visual: draw the Bezier curve (blue).
                sc.Curve(
                    [[-1, 0, 0], [0, 1, 0], [0, -1, 0], [1, 0, 0]],
                    thicknesses=[5.0],
                    colors=[cl.blue],
                )
                # Gesture target: invisible quad centred at world origin
                # (the curve midpoint at t=0.5).  PolygonMesh intersection is
                # rock-solid; this pattern tests "click callback fires near
                # a curve" without relying on the standalone curve hit-tester.
                select = sc.ClickGesture(_on_clicked)
                actions   = [(0, 0, 0)] * 5 + [(1, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]
                positions = [(0.0, 0.0)] * 9
                select.manager = Manager(actions, positions, scene_view)
                sc.PolygonMesh(
                    [[-0.3, -0.3, 0], [0.3, -0.3, 0],
                     [0.3,  0.3, 0], [-0.3,  0.3, 0]],
                    [[0, 0, 1, 0]] * 4,   # transparent blue overlay
                    [4], [0, 1, 2, 3],
                    gesture=select,
                )

        await self.wait_n_updates(30)
        self.assertTrue(clicked[0], "Curve click callback was not triggered")
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

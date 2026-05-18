# SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

# Standalone replacement for the Kit-only test_stereo test.
# The original required sc.Widget.frame (not available in standalone);
# this version renders the same shared wireframe cube through two
# SceneViews with no Widget dependency.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_base import OmniUiTest
from omni.ui_scene import scene as sc
import omni.ui as ui


# ---------------------------------------------------------------------------
# Camera models re-used from the original test_scene.py
# ---------------------------------------------------------------------------

class _CameraModel(sc.AbstractManipulatorModel):
    """Simple orbit camera whose view can be rotated programmatically."""

    def __init__(self):
        super().__init__()
        self._angle = 0

    def append_angle(self, delta: float):
        self._angle += delta * 100
        self._item_changed("view")

    def get_as_floats(self, item):
        if item == self.get_item("projection"):
            return [5, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, -1, 0, 0, -1, 0]
        if item == self.get_item("view"):
            rotation = sc.Matrix44.get_rotation_matrix(30, self._angle, 0, True)
            transl   = sc.Matrix44.get_translation_matrix(0, 0, -8)
            view     = transl * rotation
            return [view[i] for i in range(16)]


class _StereoModel(sc.AbstractManipulatorModel):
    """Wraps _CameraModel and offsets the view left/right for a stereo pair."""

    def __init__(self, parent: _CameraModel, offset: float):
        super().__init__()
        self._parent = parent
        self._offset = offset
        self._sub = self._parent.subscribe_item_changed_fn(
            lambda m, i: self.changed(m, i)
        )

    def changed(self, model, item):
        self._item_changed("view")

    def get_as_floats(self, item):
        if item == self.get_item("projection"):
            return self._parent.get_as_floats(self._parent.get_item("projection"))
        if item == self.get_item("view"):
            parent = self._parent.get_as_floats(self._parent.get_item("view"))
            parent = sc.Matrix44(*parent)
            transl     = sc.Matrix44.get_translation_matrix(0, 0, 8)
            rotation   = sc.Matrix44.get_rotation_matrix(0, self._offset, 0, True)
            transl_inv = sc.Matrix44.get_translation_matrix(0, 0, -8)
            view = transl_inv * rotation * transl * parent
            return [view[i] for i in range(16)]


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestSceneNew(OmniUiTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None

    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    # ------------------------------------------------------------------
    # 14. Stereo — two SceneViews sharing one scene
    # ------------------------------------------------------------------

    async def test_stereo(self):
        """Two SceneViews that share a Scene render the wireframe cube from offset angles.

        The original Kit test also placed a sc.Widget with frame content; that
        part requires sc.Widget.frame which is unavailable in standalone and is
        omitted here.  Everything else (shared Scene, StereoModel offsets, cube
        geometry) is ported faithfully.
        """
        window = await self.create_test_window(
            width=512, height=256, block_devices=False
        )
        with window.frame:
            with ui.HStack():
                camera       = _CameraModel()
                shared_scene = sc.Scene()
                sc.SceneView(_StereoModel(camera,  3), scene=shared_scene)
                sc.SceneView(_StereoModel(camera, -3), scene=shared_scene)

                # Populate the shared scene with a wireframe cube.
                with shared_scene:
                    # Bottom face
                    sc.Line([-1, -1, -1], [ 1, -1, -1])
                    sc.Line([-1,  1, -1], [ 1,  1, -1])
                    sc.Line([-1, -1,  1], [ 1, -1,  1])
                    sc.Line([-1,  1,  1], [ 1,  1,  1])
                    # Vertical edges
                    sc.Line([-1, -1, -1], [-1,  1, -1])
                    sc.Line([ 1, -1, -1], [ 1,  1, -1])
                    sc.Line([-1, -1,  1], [-1,  1,  1])
                    sc.Line([ 1, -1,  1], [ 1,  1,  1])
                    # Depth edges
                    sc.Line([-1, -1, -1], [-1, -1,  1])
                    sc.Line([-1,  1, -1], [-1,  1,  1])
                    sc.Line([ 1, -1, -1], [ 1, -1,  1])
                    sc.Line([ 1,  1, -1], [ 1,  1,  1])

        await self.wait_n_updates(5)
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

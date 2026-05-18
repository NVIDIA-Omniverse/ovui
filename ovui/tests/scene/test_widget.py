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

import itertools
import unittest

from test_base import OmniUiTest
from omni.ui_scene import scene as sc
import omni.ui as ui
from omni.ui import color as cl


class TestWidget(OmniUiTest):
    # Before running each test
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None  # use default standalone golden dir

    # After running each test
    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    async def _wait_updates(self, n_updates: int = 5):
        return await self.wait_n_updates(n_updates)

    async def test_widget_color_not_leak(self):
        class Manipulator(sc.Manipulator):
            def on_build(self):
                with sc.Transform(scale_to=sc.Space.SCREEN):
                    with sc.Transform(look_at=sc.Transform.LookAt.CAMERA):
                        widget = sc.Widget(
                            100, 100, update_policy=sc.Widget.UpdatePolicy.ALWAYS
                        )
                        sc.Arc(
                            radius=20,
                            wireframe=False,
                            thickness=2,
                            tesselation=16,
                            color=cl.red,
                        )
        window = await self.create_test_window(block_devices=False)
        with window.frame:
            projection = [1e-2, 0, 0, 0]
            projection += [0, 1e-2, 0, 0]
            projection += [0, 0, -2e-7, 0]
            projection += [0, 0, 1, 1]
            view = sc.Matrix44.get_translation_matrix(0, 0, -5)
            with sc.SceneView(sc.CameraModel(projection, view)).scene:
                Manipulator()

        await self._wait_updates()
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

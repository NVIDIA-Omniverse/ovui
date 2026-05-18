# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Dedicated tests for the standalone raster-image loader.

These tests specifically verify that a PNG on disk is decoded, uploaded to the
GPU, and rendered (not just silently dropped). If the standalone
IRasterImageLoader is broken or unregistered, these tests fail.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_base import OmniUiTest
from omni.ui_scene import scene as sc

DATA_PATH = Path(__file__).resolve().parent / "data"


class TestTextureLoading(OmniUiTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._golden_img_dir = None

    async def asyncTearDown(self):
        self._golden_img_dir = None
        await super().asyncTearDown()

    async def _wait_for_ready(self, image_provider, frames: int = 50):
        """Pump frames until the provider's GPU reference becomes valid."""
        for _ in range(frames):
            if image_provider.is_reference_valid:
                return True
            await asyncio.sleep(0.05)
            await self.wait_n_updates(1)
        return False

    async def test_image_loader_populates_gpu_reference(self):
        """sc.Image should produce a valid ImGui reference after the loader runs."""
        window = await self.create_test_window(width=256, height=256)
        sc_image = None
        with window.frame:
            scene_view = sc.SceneView(aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT)
            with scene_view.scene:
                sc_image = sc.Image(str(DATA_PATH / "main_ov_logo_square.png"))

        ready = await self._wait_for_ready(sc_image.image_provider)
        self.assertTrue(
            ready,
            "sc.Image did not become reference-valid — standalone raster image "
            "loader is not delivering pixels to the GPU.",
        )
        self.assertGreater(sc_image.image_provider.width, 0)
        self.assertGreater(sc_image.image_provider.height, 0)
        await self.finalize_test(golden_img_dir=self._golden_img_dir)

    async def test_textured_mesh_loader_renders_pixels(self):
        """A TexturedMesh with a PNG source_url should render the texel data.

        The golden image captures a full-viewport textured quad. If the loader
        regresses (texture never uploaded) the captured image becomes a flat
        vertex-color rectangle and the golden comparison fails.
        """
        window = await self.create_test_window(width=256, height=256)
        with window.frame:
            scene_view = sc.SceneView(aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT)
            with scene_view.scene:
                # Same UV / winding convention as TestShapes.test_textured_mesh
                # (USD coords, legacy_flipped_v=False). White vertex colors
                # so the texture is sampled without tinting.
                points = [(-1, -1, 0), (1, -1, 0), (-1, 1, 0), (1, 1, 0)]
                uvs = [(0, 0), (0, 1), (1, 1), (1, 0)]
                colors = [[1, 1, 1, 1]] * 4
                sc.TexturedMesh(
                    str(DATA_PATH / "main_ov_logo_square.png"),
                    uvs,
                    points,
                    colors,
                    [4],
                    [0, 2, 3, 1],
                    legacy_flipped_v=False,
                )

        # Give the loader a few frames to upload the texture.
        for _ in range(20):
            await asyncio.sleep(0.05)
            await self.wait_n_updates(1)

        await self.finalize_test(golden_img_dir=self._golden_img_dir)

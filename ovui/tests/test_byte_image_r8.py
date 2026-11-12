# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""``ByteImageProvider`` with ``TextureFormat.R8_UNORM`` draws a white mask.

The R value is the alpha: 0 is transparent and 255 is opaque white. On Vulkan
the image was drawn as an opaque white square, so the mask shape was lost.
"""

from __future__ import annotations

import pathlib
import tempfile

import omni.ui as ui
from omni.ui import _ui
from test_base import OmniUiTest

_SIZE = 64


class TestByteImageR8(OmniUiTest):
    async def test_r8_value_is_alpha(self):
        # 8x8 mask: left half 0 (transparent), right half 255 (opaque white).
        provider = ui.ByteImageProvider()
        provider.set_bytes_data(([0] * 4 + [255] * 4) * 8, [8, 8], ui.TextureFormat.R8_UNORM)
        window = await self.create_test_window(_SIZE, _SIZE)
        with window.frame:
            ui.ImageWithProvider(provider, width=_SIZE, height=_SIZE)
        await self.wait_n_updates(4)

        with tempfile.TemporaryDirectory() as tmp:
            capture = pathlib.Path(tmp) / "capture.png"
            self.assertTrue(_ui._schedule_screenshot(str(capture)), "screenshot request was refused")
            for _ in range(10):
                await self.wait_n_updates(1)
                if _ui._poll_screenshot_done() and capture.exists():
                    break
            self.assertTrue(capture.exists(), "screenshot was not written")

            from PIL import Image

            with Image.open(capture) as img:
                rgb = img.convert("RGB")
                left, right = rgb.getpixel((_SIZE // 8, _SIZE // 2)), rgb.getpixel((_SIZE * 7 // 8, _SIZE // 2))
        self.assertEqual(left, (0, 0, 0), "R value 0 must be transparent")
        self.assertEqual(right, (255, 255, 255), "R value 255 must be opaque white")

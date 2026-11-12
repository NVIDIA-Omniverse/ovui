# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""3-channel float byte images get GPU data on every backend.

Most Vulkan devices cannot sample RGB16_FLOAT or RGB32_FLOAT images, so the
Vulkan backend must upload them with an alpha channel, as OpenGL does.
"""

from __future__ import annotations

import struct
import unittest

import omni.ui as ui
from test_base import OmniUiTest


class TestByteImageRgbFloat(OmniUiTest):
    async def test_rgb_float_formats_get_gpu_data(self):
        for texture_format, code in ((ui.TextureFormat.RGB16_FLOAT, "e"), (ui.TextureFormat.RGB32_FLOAT, "f")):
            provider = ui.ByteImageProvider()
            pixels = struct.pack("<3" + code, 1.0, 0.5, 0.25) * 16
            provider.set_bytes_data(list(pixels), [4, 4], texture_format)
            self.assertTrue(provider.is_reference_valid, texture_format)
        await self.finalize_test_no_image()


if __name__ == "__main__":
    unittest.main()

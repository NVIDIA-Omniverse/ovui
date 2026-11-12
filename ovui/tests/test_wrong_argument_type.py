# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A wrong argument type raises TypeError that names the function and the expected type."""

from __future__ import annotations

import unittest

import omni.ui as ui
from test_base import OmniUiTest


class TestWrongArgumentType(OmniUiTest):
    async def test_wrong_format_and_app_window_raise_type_error(self):
        provider = ui.ByteImageProvider()
        with self.assertRaisesRegex(TypeError, r"set_bytes_data\(\)[\s\S]*format: omni\.ui\._ui\.TextureFormat"):
            provider.set_bytes_data([0] * 16, [2, 2], 1)
        window = await self.create_test_window(64, 64)
        with self.assertRaisesRegex(TypeError, "move_to_app_window"):
            window.move_to_app_window(123)
        await self.finalize_test_no_image()


if __name__ == "__main__":
    unittest.main()

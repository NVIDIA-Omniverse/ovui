# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Replacing textures inside the frame that has already drawn them.

A widget callback can release the textures that the current frame has drawn
and upload replacements in the same frame, for example a button that refreshes
an image grid. The released textures stay alive until that frame is submitted,
so the replacements must still get GPU resources.
"""

from __future__ import annotations

import unittest

import omni.ui as ui
from test_base import OmniUiTest


class TestByteImageProviderReplacement(OmniUiTest):
    async def test_replacing_drawn_textures_inside_a_frame_keeps_every_replacement(self):
        count = 60

        def make_providers(seed):
            providers = []
            for index in range(count):
                provider = ui.ByteImageProvider()
                provider.set_bytes_data([seed, index * 4, 30, 255] * 16, [4, 4])
                providers.append(provider)
            return providers

        old = make_providers(200)
        new = []

        def replace():
            # Runs while the frame that has drawn ``old`` is built.
            for provider in old:
                provider.destroy()
            new.extend(make_providers(40))

        window = await self.create_test_window(256, 256)
        with window.frame:
            with ui.VStack():
                with ui.VGrid(column_width=8, row_height=8, height=0):
                    for provider in old:
                        ui.ImageWithProvider(provider, width=8, height=8)
                trigger = ui.Frame(build_fn=lambda: None)
        await self.wait_n_updates(2)
        self.assertEqual(sum(provider.is_reference_valid for provider in old), count)

        trigger.set_build_fn(replace)
        trigger.rebuild()
        await self.wait_n_updates(3)

        self.assertEqual(len(new), count)
        self.assertEqual(sum(provider.is_reference_valid for provider in new), count)
        await self.finalize_test_no_image()


if __name__ == "__main__":
    unittest.main()

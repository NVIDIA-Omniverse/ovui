# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Integration tests for the OVLS streaming backend."""

import os
import unittest

import pytest

from omni.ui import standalone
import omni.ui as ui


@pytest.mark.requires_gl
@pytest.mark.requires_glfw
class TestStreamingIntegration(unittest.TestCase):
    """Integration tests for the OVLS streaming backend."""

    def setUp(self):
        os.environ.setdefault('GLFW_PLATFORM', 'null')
        os.environ.setdefault('__NV_PRIME_RENDER_OFFLOAD', '1')
        os.environ.setdefault('__GLX_VENDOR_LIBRARY_NAME', 'nvidia')
        standalone.init_streaming(640, 480)

    def tearDown(self):
        standalone.shutdown_streaming()

    def test_full_streaming_pipeline(self):
        result = standalone.streaming_tick()
        self.assertTrue(result)
        tex = standalone.get_streaming_gl_texture()
        self.assertGreater(tex, 0)
        self.assertEqual(standalone.get_streaming_size(), (640, 480))

    def test_streaming_with_label(self):
        win = ui.Window("Test Window", width=640, height=480)
        with win.frame:
            with ui.VStack():
                ui.Label("Hello")
        # Tick several frames to ensure the label is laid out and rendered
        for _ in range(5):
            result = standalone.streaming_tick()
            self.assertTrue(result)
        tex = standalone.get_streaming_gl_texture()
        self.assertGreater(tex, 0)

    def test_streaming_multiple_ticks(self):
        for i in range(30):
            result = standalone.streaming_tick()
            self.assertTrue(result, f"streaming_tick failed on iteration {i}")

    def test_streaming_resize_and_tick(self):
        result = standalone.streaming_tick()
        self.assertTrue(result)
        self.assertEqual(standalone.get_streaming_size(), (640, 480))

        standalone.resize_streaming(1280, 720)
        result = standalone.streaming_tick()
        self.assertTrue(result)
        self.assertEqual(standalone.get_streaming_size(), (1280, 720))

    def test_streaming_cuda_buffer_stability(self):
        standalone.streaming_tick()
        ptr1 = standalone.get_streaming_cuda_ptr()
        standalone.streaming_tick()
        ptr2 = standalone.get_streaming_cuda_ptr()
        # If CUDA is available, pointer should be stable across ticks
        # If CUDA is not available, both will be 0
        self.assertEqual(ptr1, ptr2, "CUDA pointer should remain stable across ticks")

    def test_streaming_headless_no_display(self):
        # Verify we are running headless (GLFW_PLATFORM=null)
        self.assertEqual(os.environ.get('GLFW_PLATFORM'), 'null')
        # The full pipeline should work without a display
        result = standalone.streaming_tick()
        self.assertTrue(result)
        tex = standalone.get_streaming_gl_texture()
        self.assertGreater(tex, 0)
        size = standalone.get_streaming_size()
        self.assertEqual(size, (640, 480))


if __name__ == '__main__':
    unittest.main()

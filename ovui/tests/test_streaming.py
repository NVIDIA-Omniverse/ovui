# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the streaming API lifecycle."""

import os
import unittest

import pytest

from omni.ui import standalone


@pytest.mark.requires_gl
@pytest.mark.requires_glfw
class TestStreamingLifecycle(unittest.TestCase):
    """Test the streaming API lifecycle."""

    def setUp(self):
        os.environ.setdefault('GLFW_PLATFORM', 'null')
        os.environ.setdefault('__NV_PRIME_RENDER_OFFLOAD', '1')
        os.environ.setdefault('__GLX_VENDOR_LIBRARY_NAME', 'nvidia')

    def tearDown(self):
        standalone.shutdown_streaming()

    def test_init_streaming_creates_fbo(self):
        standalone.init_streaming(640, 480)
        tex = standalone.get_streaming_gl_texture()
        self.assertGreater(tex, 0, "GL texture should be > 0 after init")

    def test_init_streaming_returns_size(self):
        standalone.init_streaming(640, 480)
        size = standalone.get_streaming_size()
        self.assertEqual(size, (640, 480))

    def test_streaming_tick_renders_frame(self):
        standalone.init_streaming(640, 480)
        result = standalone.streaming_tick()
        self.assertTrue(result)

    def test_get_streaming_cuda_ptr(self):
        standalone.init_streaming(640, 480)
        ptr = standalone.get_streaming_cuda_ptr()
        self.assertIsInstance(ptr, int)

    def test_get_streaming_cuda_pitch(self):
        standalone.init_streaming(640, 480)
        pitch = standalone.get_streaming_cuda_pitch()
        self.assertIsInstance(pitch, int)
        self.assertGreaterEqual(pitch, 0)

    def test_get_streaming_gl_texture(self):
        standalone.init_streaming(640, 480)
        tex = standalone.get_streaming_gl_texture()
        self.assertIsInstance(tex, int)
        self.assertGreater(tex, 0)

    def test_resize_streaming(self):
        standalone.init_streaming(640, 480)
        self.assertEqual(standalone.get_streaming_size(), (640, 480))
        standalone.resize_streaming(800, 600)
        self.assertEqual(standalone.get_streaming_size(), (800, 600))

    def test_shutdown_streaming_cleanup(self):
        standalone.init_streaming(640, 480)
        standalone.shutdown_streaming()
        self.assertEqual(standalone.get_streaming_gl_texture(), 0)
        self.assertEqual(standalone.get_streaming_size(), (0, 0))

    def test_double_init_raises(self):
        standalone.init_streaming(640, 480)
        with self.assertRaises(RuntimeError):
            standalone.init_streaming(640, 480)

    def test_shutdown_without_init(self):
        # Should not crash or raise
        standalone.shutdown_streaming()

    def test_streaming_tick_without_init(self):
        with self.assertRaises(RuntimeError):
            standalone.streaming_tick()

    def test_get_cuda_ptr_without_init(self):
        ptr = standalone.get_streaming_cuda_ptr()
        self.assertEqual(ptr, 0)

    # ----- Edge cases (critique action items) -----

    def test_streaming_tick_after_shutdown(self):
        """streaming_tick after shutdown should raise, not crash."""
        standalone.init_streaming(640, 480)
        standalone.shutdown_streaming()
        with self.assertRaises(RuntimeError):
            standalone.streaming_tick()

    def test_resize_to_zero(self):
        """Resizing to 0x0 should fail gracefully."""
        standalone.init_streaming(640, 480)
        with self.assertRaises(RuntimeError):
            standalone.resize_streaming(0, 0)
        # Original size should be preserved
        self.assertEqual(standalone.get_streaming_size(), (640, 480))

    def test_resize_to_zero_width(self):
        """Resizing to 0 width should fail gracefully."""
        standalone.init_streaming(640, 480)
        with self.assertRaises(RuntimeError):
            standalone.resize_streaming(0, 480)
        self.assertEqual(standalone.get_streaming_size(), (640, 480))

    def test_resize_to_negative(self):
        """Resizing to negative dimensions should fail gracefully."""
        standalone.init_streaming(640, 480)
        with self.assertRaises(RuntimeError):
            standalone.resize_streaming(-1, -1)
        self.assertEqual(standalone.get_streaming_size(), (640, 480))

    def test_get_streaming_format(self):
        """get_streaming_format should return 'rgba8'."""
        self.assertEqual(standalone.get_streaming_format(), "rgba8")

    def test_is_streaming_cuda_available_before_init(self):
        """is_streaming_cuda_available should be False before init."""
        self.assertFalse(standalone.is_streaming_cuda_available())

    def test_is_streaming_cuda_available_after_init(self):
        """is_streaming_cuda_available should return a bool after init."""
        standalone.init_streaming(640, 480)
        result = standalone.is_streaming_cuda_available()
        self.assertIsInstance(result, bool)

    def test_streaming_sync_without_init(self):
        """streaming_sync should be a no-op without init, not crash."""
        standalone.streaming_sync()  # Should not raise

    def test_streaming_sync_after_init(self):
        """streaming_sync should succeed after init + tick."""
        standalone.init_streaming(640, 480)
        standalone.streaming_tick()
        standalone.streaming_sync()  # Should not raise

    def test_get_streaming_cuda_event_without_init(self):
        """get_streaming_cuda_event should return 0 without init."""
        event = standalone.get_streaming_cuda_event()
        self.assertEqual(event, 0)

    def test_get_streaming_cuda_buffer(self):
        """get_streaming_cuda_buffer should return (ptr, pitch) tuple."""
        standalone.init_streaming(640, 480)
        buf = standalone.get_streaming_cuda_buffer()
        self.assertIsInstance(buf, tuple)
        self.assertEqual(len(buf), 2)
        ptr, pitch = buf
        self.assertIsInstance(ptr, int)
        self.assertIsInstance(pitch, int)

    def test_get_streaming_cuda_buffer_without_init(self):
        """get_streaming_cuda_buffer should return (0, 0) without init."""
        self.assertEqual(standalone.get_streaming_cuda_buffer(), (0, 0))

    def test_shutdown_then_reinit(self):
        """Should be able to re-initialize after shutdown."""
        standalone.init_streaming(640, 480)
        standalone.shutdown_streaming()
        # Re-init should work
        standalone.init_streaming(800, 600)
        self.assertEqual(standalone.get_streaming_size(), (800, 600))

    def test_resize_without_init(self):
        """resize_streaming without init should raise."""
        with self.assertRaises(RuntimeError):
            standalone.resize_streaming(800, 600)

    def test_get_streaming_size_without_init(self):
        """get_streaming_size should return (0, 0) without init."""
        self.assertEqual(standalone.get_streaming_size(), (0, 0))

    def test_get_streaming_gl_texture_without_init(self):
        """get_streaming_gl_texture should return 0 without init."""
        self.assertEqual(standalone.get_streaming_gl_texture(), 0)


if __name__ == '__main__':
    unittest.main()

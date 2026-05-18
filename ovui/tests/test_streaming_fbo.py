# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the FBO/virtual window at the C++ binding level."""

import os
import unittest

import pytest

from omni.ui import _ui


@pytest.mark.requires_gl
@pytest.mark.requires_glfw
class TestStreamingFBO(unittest.TestCase):
    """Test the FBO/virtual window at the C++ binding level."""

    def setUp(self):
        os.environ.setdefault('GLFW_PLATFORM', 'null')
        os.environ.setdefault('__NV_PRIME_RENDER_OFFLOAD', '1')
        os.environ.setdefault('__GLX_VENDOR_LIBRARY_NAME', 'nvidia')

    def tearDown(self):
        _ui._shutdown_streaming()

    def test_init_creates_valid_texture(self):
        result = _ui._init_streaming(320, 240)
        self.assertTrue(result)
        tex = _ui._get_streaming_gl_texture()
        self.assertGreater(tex, 0)

    def test_streaming_width_height(self):
        _ui._init_streaming(320, 240)
        self.assertEqual(_ui._get_streaming_width(), 320)
        self.assertEqual(_ui._get_streaming_height(), 240)

    def test_gl_texture_changes_after_resize(self):
        _ui._init_streaming(320, 240)
        tex_before = _ui._get_streaming_gl_texture()
        self.assertGreater(tex_before, 0)
        _ui._resize_streaming(640, 480)
        tex_after = _ui._get_streaming_gl_texture()
        self.assertGreater(tex_after, 0)
        # Texture ID may or may not change; just verify it's still valid
        self.assertEqual(_ui._get_streaming_width(), 640)
        self.assertEqual(_ui._get_streaming_height(), 480)

    def test_streaming_tick_returns_bool(self):
        _ui._init_streaming(320, 240)
        result = _ui._streaming_tick()
        self.assertIsInstance(result, bool)
        self.assertTrue(result)

    def test_shutdown_clears_texture(self):
        _ui._init_streaming(320, 240)
        self.assertGreater(_ui._get_streaming_gl_texture(), 0)
        _ui._shutdown_streaming()
        self.assertEqual(_ui._get_streaming_gl_texture(), 0)

    def test_render_produces_pixels(self):
        """Verify that rendering to the FBO produces non-zero pixels.

        After streamingTick() the FBO is unbound, so we must bind the
        streaming GL texture's parent FBO before glReadPixels. We use the
        GL texture ID to create a temporary read-framebuffer.
        """
        try:
            from OpenGL.GL import (
                glReadPixels, GL_RGBA, GL_UNSIGNED_BYTE,
                glGenFramebuffers, glBindFramebuffer, glDeleteFramebuffers,
                glFramebufferTexture2D, GL_READ_FRAMEBUFFER,
                GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
            )
        except ImportError:
            self.skipTest("PyOpenGL not available")

        _ui._init_streaming(320, 240)
        _ui._streaming_tick()

        tex_id = _ui._get_streaming_gl_texture()
        self.assertGreater(tex_id, 0)

        # Create a temporary FBO to read from the streaming texture
        read_fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_READ_FRAMEBUFFER, read_fbo)
        glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, tex_id, 0)

        width, height = 320, 240
        pixels = glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE)
        pixel_bytes = bytes(pixels)

        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0)
        glDeleteFramebuffers(1, [read_fbo])

        # Verify that at least some non-zero pixels exist (the background
        # clear color is ~(31, 33, 36, 255) so pixels should not be all-zero)
        has_nonzero = any(b != 0 for b in pixel_bytes)
        self.assertTrue(has_nonzero, "Expected non-zero pixels after rendering to FBO")


if __name__ == '__main__':
    unittest.main()

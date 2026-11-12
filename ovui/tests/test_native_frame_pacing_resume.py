# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A resume of the native render worker renders only when the caller says so.

Under the "on_change" policy a resume renders once, because what changed during
the pause is shown. A caller that paused the worker only to give the renderer a
value that the picture does not show resumes with ``render=False``: no frame.
The status says when the worker waits with no render due (``render_idle``): the
picture on screen then has its settle frames, and the caller can store it.

The fake frame source (``libomniui_fake_frame_source``, built with ovui from
``standalone/tests/fake_frame_source.cpp``, also without the CUDA toolkit) fills
the renderer slot with host copies; the frames are counted with
``omni.ui._ui._get_native_frame_pacing_status()``. It needs no GPU, so the
headless Vulkan job runs it. Native frame pacing exists only with the
standalone Vulkan backend, so an OpenGL run (headless EGL or a windowed OpenGL
backend) skips it, as an OpenGL-only test skips under Vulkan. Otherwise a missing
fake source or native frame pacing fails the test.
"""

import ctypes
import os
import pathlib
import unittest

import omni.ui as ui
from omni.ui import _ui
from test_base import OmniUiTest
from test_native_frame_pacing_upload import (
    _CAPSULE_NAME,
    _IDENTITY,
    _LIBRARY_NAME,
    _PyCapsule_New,
    _fake_frame_source,
)


def _opengl_backend() -> bool:
    """The backend choice of tests/conftest.py: headless EGL or an OpenGL backend that was asked for."""
    if os.environ.get("OMNIUI_HEADLESS") == "1":
        return os.environ.get("OMNIUI_HEADLESS_GL") == "1"
    return os.environ.get("OMNIUI_BACKEND", "").lower() in ("opengl", "gl")


class TestNativeFramePacingResume(OmniUiTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._token = 0
        self._lib = None
        if _opengl_backend():
            self.skipTest("native frame pacing needs the standalone Vulkan backend; this run uses OpenGL")
        library = _fake_frame_source()
        self.assertTrue(
            library and pathlib.Path(library).exists(),
            f"{_LIBRARY_NAME} was not found in the ovui build folder, and OMNIUI_FAKE_FRAME_SOURCE does not name it",
        )
        self.assertTrue(hasattr(_ui, "_native_frame_pacing_start"), "this ovui build has no native frame pacing")
        self._lib = ctypes.CDLL(library)
        self._lib.omniui_fake_frame_source_hooks.restype = ctypes.c_void_p
        self._capsule = _PyCapsule_New(self._lib.omniui_fake_frame_source_hooks(), _CAPSULE_NAME, None)
        _ui._set_native_frame_pacing_hooks(self._capsule)

    async def asyncTearDown(self):
        if self._lib is not None:
            if self._token:
                _ui._native_frame_pacing_stop(self._token)
            _ui._set_present_rate(0.0)
            _ui._set_native_frame_pacing_hooks(None)
        await super().asyncTearDown()

    @staticmethod
    def _rendered():
        return _ui._get_native_frame_pacing_status()["real_render_completions"]

    async def _until_still(self):
        """Wait until the worker renders no more frames; return the count of rendered frames."""
        rendered, same = -1, 0
        for _ in range(400):
            await self.wait_n_updates(1)
            count = self._rendered()
            same = same + 1 if count == rendered else 0
            rendered = count
            if same >= 10:
                return rendered
        self.fail(f"the worker did not stop rendering: {_ui._get_native_frame_pacing_status()}")

    async def test_a_resume_without_render_renders_no_frame(self):
        window = await self.create_test_window(64, 64)
        provider = ui.ByteImageProvider()
        provider.set_bytes_data([0, 0, 0, 255] * 16, [4, 4])
        with window.frame:
            ui.ImageWithProvider(provider, width=64, height=64)
        await self.wait_n_updates(2)
        _ui._set_present_rate(60.0)
        self._token = _ui._native_frame_pacing_start(1, "", 0, 0, 0, provider, "/Render/Product", "/World/Camera", 64, 64)
        self.assertNotEqual(self._token, 0, _ui._get_native_frame_pacing_status().get("last_error"))
        self.assertTrue(_ui._native_frame_pacing_set_render_policy(self._token, "on_change", 0))
        _ui._native_frame_pacing_publish(self._token, 64, 64, _IDENTITY)
        rendered = await self._until_still()
        self.assertGreater(rendered, 0, "the worker rendered no first frame")

        # A caller that changed nothing the picture shows resumes with render=False.
        self.assertTrue(_ui._native_frame_pacing_pause_render(self._token))
        self.assertTrue(_ui._native_frame_pacing_resume_render(self._token, render=False))
        await self.wait_n_updates(20)
        self.assertEqual(self._rendered(), rendered, "a resume with render=False rendered a frame")

        # A plain resume still renders what changed during the pause.
        self.assertTrue(_ui._native_frame_pacing_pause_render(self._token))
        self.assertTrue(_ui._native_frame_pacing_resume_render(self._token))
        self.assertGreater(await self._until_still(), rendered, "a plain resume rendered no frame")

    async def _until_idle(self):
        """Wait until the status says that the worker has nothing to render; return the count of rendered frames."""
        for _ in range(400):
            await self.wait_n_updates(1)
            if _ui._get_native_frame_pacing_status().get("render_idle") is True:
                return self._rendered()
        self.fail(f"the worker never had nothing to render: {_ui._get_native_frame_pacing_status()}")

    async def test_the_status_says_when_the_worker_has_nothing_to_render(self):
        window = await self.create_test_window(64, 64)
        provider = ui.ByteImageProvider()
        provider.set_bytes_data([0, 0, 0, 255] * 16, [4, 4])
        with window.frame:
            ui.ImageWithProvider(provider, width=64, height=64)
        await self.wait_n_updates(2)
        _ui._set_present_rate(60.0)
        self._token = _ui._native_frame_pacing_start(1, "", 0, 0, 0, provider, "/Render/Product", "/World/Camera", 64, 64)
        self.assertNotEqual(self._token, 0, _ui._get_native_frame_pacing_status().get("last_error"))
        settle = 3
        self.assertTrue(_ui._native_frame_pacing_set_render_policy(self._token, "on_change", settle))
        _ui._native_frame_pacing_publish(self._token, 64, 64, _IDENTITY)
        rendered = await self._until_idle()
        self.assertGreater(rendered, settle, "the worker was idle before its settle frames")
        await self.wait_n_updates(20)
        self.assertEqual(self._rendered(), rendered, "the worker rendered frames while the status said idle")

        # A render request: the settle frames are rendered before the worker is idle again.
        _ui._native_frame_pacing_request_render(self._token)
        self.assertGreater(await self._until_idle(), rendered + settle)
        rendered = self._rendered()

        # A paused worker cannot render: it is not idle. Its resume without a render is.
        self.assertTrue(_ui._native_frame_pacing_pause_render(self._token))
        self.assertFalse(_ui._get_native_frame_pacing_status()["render_idle"])
        self.assertTrue(_ui._native_frame_pacing_resume_render(self._token, render=False))
        self.assertEqual(await self._until_idle(), rendered)


if __name__ == "__main__":
    unittest.main()

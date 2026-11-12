# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Native frame pacing must not count a refused upload as a published frame.

A fake frame source (``libomniui_fake_frame_source.so``, built from
``standalone/tests/fake_frame_source.cpp`` with the ovui build when the CUDA
toolkit is there) fills the renderer slot. The tests refuse uploads with the
failure hook of the paced provider and read the counters of
``omni.ui._ui._get_native_frame_pacing_status()``:

- one refused upload drops its frame, counts a failure, and does not count a
  published frame, and the next frame still uses the GPU path;
- three refused uploads in a row switch to the host copy.

The library is found in the ovui build folder; ``OMNIUI_FAKE_FRAME_SOURCE``
can name another one. The tests skip only on a computer without the hardware:
no NVIDIA GPU listed by the driver tools and no CUDA device. On a computer that
has an NVIDIA GPU, every other problem fails the test with its cause: a CUDA
error such as a driver that does not match, a missing library, no native frame
pacing, or an ovui that cannot import Vulkan memory into CUDA.
"""

import ctypes
import os
import pathlib
import shutil
import subprocess
import sys
import unittest

import omni.ui as ui
from omni.ui import _ui
from test_base import OmniUiTest

_PyCapsule_New = ctypes.pythonapi.PyCapsule_New
_PyCapsule_New.restype = ctypes.py_object
_PyCapsule_New.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p]
_CAPSULE_NAME = b"omni.ui.native_frame_pacing_hooks"
_IDENTITY = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
# CMake names it with the "lib" prefix on every platform.
_LIBRARY_NAME = "libomniui_fake_frame_source.dll" if sys.platform == "win32" else "libomniui_fake_frame_source.so"


def _nvidia_gpu_listed() -> bool:
    """Whether this computer shows an NVIDIA GPU to the driver tools, without asking CUDA."""
    if os.path.exists("/dev/nvidia0"):
        return True
    smi = shutil.which("nvidia-smi")
    if smi is None:
        return False
    try:
        done = subprocess.run([smi, "-L"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and "GPU" in done.stdout


def _cuda_devices() -> tuple:
    """How many CUDA devices CUDA reports, and why it reports none ("" when it answered).

    The function is looked up in the global symbols first, so that a library that
    ovui would also use in place of the CUDA runtime is used here too.
    """
    for name in ("libcudart.so.12", "libcudart.so", "cudart64_12.dll"):
        try:
            cudart = ctypes.CDLL(name)
        except OSError:
            continue
        try:
            get_count = ctypes.CDLL(None).cudaGetDeviceCount
        except (AttributeError, OSError, TypeError):
            get_count = cudart.cudaGetDeviceCount
        count = ctypes.c_int(0)
        error = get_count(ctypes.byref(count))
        if error != 0:
            cudart.cudaGetErrorName.restype = ctypes.c_char_p
            cudart.cudaGetErrorString.restype = ctypes.c_char_p
            error_name = cudart.cudaGetErrorName(error).decode()
            error_text = cudart.cudaGetErrorString(error).decode()
            return 0, f"cudaGetDeviceCount failed with CUDA error {error} ({error_name}: {error_text})"
        if count.value == 0:
            return 0, "cudaGetDeviceCount found no device"
        return count.value, ""
    return 0, "no CUDA runtime library (libcudart) could be loaded"


def _fake_frame_source() -> str:
    """Path of the fake frame source library, or "" when it was not built."""
    named = os.environ.get("OMNIUI_FAKE_FRAME_SOURCE", "")
    if named:
        return named
    build = pathlib.Path(__file__).resolve().parents[1] / "build"
    found = sorted(build.glob(f"**/{_LIBRARY_NAME}")) if build.is_dir() else []
    return str(found[0]) if found else ""


class TestNativeFramePacingUpload(OmniUiTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._token = 0
        self._lib = None
        count, cuda_problem = _cuda_devices()
        if count == 0 and not _nvidia_gpu_listed():
            self.skipTest(f"no NVIDIA GPU: the GPU publication path needs one ({cuda_problem})")
        # The hardware is there. From here every problem is a broken setup and fails with its cause.
        self.assertGreater(count, 0, f"this computer has an NVIDIA GPU, but CUDA does not work: {cuda_problem}")
        library = _fake_frame_source()
        self.assertTrue(
            library and pathlib.Path(library).exists(),
            f"{_LIBRARY_NAME} was not found in the ovui build folder (it is built only when the CUDA toolkit is "
            f"there), and OMNIUI_FAKE_FRAME_SOURCE does not name it; this computer has an NVIDIA GPU with CUDA",
        )
        self.assertTrue(hasattr(_ui, "_native_frame_pacing_start"), "this ovui build has no native frame pacing")
        self.assertTrue(
            ui.has_gpu_byte_image(),
            "ovui cannot import Vulkan memory into CUDA (omni.ui.has_gpu_byte_image() is False), although this "
            f"computer has an NVIDIA GPU and CUDA reports {count} device(s); the GPU publication path cannot run",
        )
        self._lib = ctypes.CDLL(library)
        self._lib.omniui_fake_frame_source_hooks.restype = ctypes.c_void_p
        self._lib.omniui_fake_frame_source_has_device_buffer.restype = ctypes.c_int
        self._capsule = _PyCapsule_New(self._lib.omniui_fake_frame_source_hooks(), _CAPSULE_NAME, None)
        _ui._set_native_frame_pacing_hooks(self._capsule)

    async def asyncTearDown(self):
        if self._lib is not None:
            provider = getattr(self, "_provider", None)
            if provider is not None:
                provider.inject_upload_failures(0)
            if self._token:
                _ui._native_frame_pacing_stop(self._token)
            _ui._set_present_rate(0.0)
            _ui._set_native_frame_pacing_hooks(None)
        await super().asyncTearDown()

    async def _start(self):
        window = await self.create_test_window(64, 64)
        self._provider = ui.ByteImageProvider()
        self._provider.set_bytes_data([0, 0, 0, 255] * 16, [4, 4])
        with window.frame:
            ui.ImageWithProvider(self._provider, width=64, height=64)
        await self.wait_n_updates(2)
        _ui._set_present_rate(60.0)
        self._token = _ui._native_frame_pacing_start(1, "", 0, 0, 0, self._provider, "/Render/Product", "/World/Camera", 64, 64)
        self.assertNotEqual(self._token, 0, _ui._get_native_frame_pacing_status().get("last_error"))

    @staticmethod
    def _status():
        return _ui._get_native_frame_pacing_status()

    async def _until(self, condition, what):
        for _ in range(400):
            await self.wait_n_updates(1)
            if condition(self._status()):
                return self._status()
        self.fail(f"timeout waiting for {what}: {self._status()}")

    async def _settle(self):
        """Pause the render worker so the counters stop moving."""
        self.assertTrue(_ui._native_frame_pacing_pause_render(self._token))
        await self.wait_n_updates(2)
        return self._status()

    async def _start_with_gpu_path(self):
        self.assertTrue(self._lib.omniui_fake_frame_source_has_device_buffer(), "cudaMalloc failed in the fake source")
        await self._start()
        _ui._native_frame_pacing_publish(self._token, 64, 64, _IDENTITY)
        status = await self._until(lambda s: s["gpu_resident_publications"] + s["host_fallback_publications"] >= 2,
                                   "two published frames")
        self.assertGreaterEqual(status["gpu_resident_publications"], 2, f"the GPU publication path failed: {status}")

    async def test_one_refused_upload_is_not_a_published_frame(self):
        await self._start_with_gpu_path()

        self._provider.inject_upload_failures(1)
        status = await self._until(lambda s: s["gpu_publication_failures"] >= 1, "the refusal")
        self.assertEqual(status["gpu_publication_failures"], 1)
        self.assertEqual(self._provider.inject_upload_failures(0), 0, "the hook was used by pacing")

        # One refusal drops one frame. The next frames still use the GPU path.
        gpu = status["gpu_resident_publications"]
        status = await self._until(lambda s: s["gpu_resident_publications"] >= gpu + 2, "GPU frames after it")
        self.assertEqual(status["gpu_publication_failures"], 1, "one refusal does not switch paths")
        self.assertEqual(status["host_fallback_publications"], 0)

        # Every frame that the worker rendered is counted once: as published
        # (GPU path or host copy), or as refused. A refused frame is not
        # counted as published.
        await self._settle()
        status = await self._until(
            lambda s: s["real_render_completions"]
            == s["gpu_resident_publications"] + s["host_fallback_publications"] + s["gpu_publication_failures"],
            "every rendered frame to be counted once",
        )
        self.assertEqual(status["gpu_publication_failures"], 1)

    async def test_three_refused_uploads_in_a_row_switch_to_the_host_copy(self):
        await self._start_with_gpu_path()

        self._provider.inject_upload_failures(3)
        status = await self._until(lambda s: s["gpu_publication_failures"] >= 3, "three refusals")
        self.assertEqual(status["gpu_publication_failures"], 3)
        status = await self._until(lambda s: s["host_fallback_publications"] >= 2, "frames through the host copy")
        gpu = status["gpu_resident_publications"]
        await self.wait_n_updates(10)
        status = self._status()
        self.assertEqual(status["gpu_resident_publications"], gpu, "no more GPU publications after the switch")
        self.assertEqual(status["gpu_publication_failures"], 3)


if __name__ == "__main__":
    unittest.main()

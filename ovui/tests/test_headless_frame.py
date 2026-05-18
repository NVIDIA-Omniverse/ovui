# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the high-level :mod:`omni.ui.standalone.headless_frame` wrappers.

The wrappers are thin pass-throughs over the ``_ui._headless_frame_*``
bindings, but the wrapper layer is what downstream users (ovgear) consume.
This test verifies that the wrappers are importable, present the expected
surface, and end-to-end drive a real frame export when the environment
supports it (headless Vulkan + CUDA).

When the environment is not headless / not Vulkan / has no CUDA, the
end-to-end test skips. The import / surface checks always run.
"""

from __future__ import annotations

import ctypes
import os
import unittest

import pytest

from omni.ui import standalone
from omni.ui.standalone import headless_frame


_IS_HEADLESS = os.environ.get("OMNIUI_HEADLESS", "").lower() in ("1", "true")
_BACKEND = os.environ.get("OMNIUI_BACKEND", "").lower()
_IS_VULKAN = _BACKEND in ("vulkan", "vk")


class TestHeadlessFrameSurface(unittest.TestCase):
    """The wrapper surface must exist regardless of runtime environment."""

    def test_module_exposes_expected_symbols(self):
        for name in (
            "init",
            "shutdown",
            "extent",
            "format",
            "wait_ready",
            "signal_consumed",
            "copy_to_linear",
        ):
            self.assertTrue(
                hasattr(headless_frame, name),
                f"headless_frame.{name} missing",
            )
            self.assertTrue(callable(getattr(headless_frame, name)))

    def test_extent_returns_tuple_when_uninitialised(self):
        # When the pipeline is not initialised the C++ side returns
        # (0, 0); the wrapper must surface that as a 2-tuple of ints.
        result = headless_frame.extent()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], int)
        self.assertIsInstance(result[1], int)


@unittest.skipUnless(
    _IS_HEADLESS and _IS_VULKAN,
    "headless_frame end-to-end requires OMNIUI_HEADLESS=1 OMNIUI_BACKEND=vulkan",
)
@pytest.mark.requires_cuda
class TestHeadlessFrameEndToEnd(unittest.TestCase):
    """Drive a single frame through the full pipeline.

    Runs only when the harness is started with the headless Vulkan env.
    Allocates a pitched device buffer via ctypes-cudart, copies the frame
    into it through ``copy_to_linear``, copies the result back to host,
    and asserts the frame contains non-zero variance (i.e. is actually
    rendered, not just zero-filled).
    """

    @classmethod
    def setUpClass(cls):
        cls._cudart = ctypes.CDLL("libcudart.so")

        # cudaMalloc(void**, size_t)
        cls._cudart.cudaMalloc.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_size_t,
        ]
        cls._cudart.cudaMalloc.restype = ctypes.c_int

        # cudaMallocPitch(void**, size_t*, size_t, size_t)
        cls._cudart.cudaMallocPitch.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_size_t,
            ctypes.c_size_t,
        ]
        cls._cudart.cudaMallocPitch.restype = ctypes.c_int

        # cudaFree(void*)
        cls._cudart.cudaFree.argtypes = [ctypes.c_void_p]
        cls._cudart.cudaFree.restype = ctypes.c_int

        # cudaMemcpy2D(dst, dpitch, src, spitch, width_bytes, height, kind)
        cls._cudart.cudaMemcpy2D.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_int,
        ]
        cls._cudart.cudaMemcpy2D.restype = ctypes.c_int

        # cudaDeviceSynchronize()
        cls._cudart.cudaDeviceSynchronize.argtypes = []
        cls._cudart.cudaDeviceSynchronize.restype = ctypes.c_int

        cls._CUDA_MEMCPY_DEVICE_TO_HOST = 2

    def setUp(self):
        # Ensure standalone is initialised so the headless platform exists.
        standalone.init("test_headless_frame", 256, 256, max_fps=None)

    def tearDown(self):
        try:
            headless_frame.shutdown()
        except Exception:
            pass
        # Don't shut down the standalone backend here — the run_tests
        # harness manages global lifecycle and other tests share the
        # platform. Re-init is idempotent.

    def _check(self, rc: int, where: str) -> None:
        self.assertEqual(rc, 0, f"{where} failed (cuda rc={rc})")

    def test_end_to_end_copy_produces_nonzero_variance(self):
        ok = headless_frame.init()
        self.assertTrue(ok, "headless_frame.init() refused — check env vars")

        self.assertEqual(headless_frame.format(), "rgba8")
        w, h = headless_frame.extent()
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)

        # Tick once so the offscreen image actually has rendered content
        # (without this the V->C semaphore is never signalled and the
        # frame is zero-initialised).
        standalone._tick_one_frame()

        # Allocate pitched RGBA8 destination.
        dst = ctypes.c_void_p(0)
        pitch = ctypes.c_size_t(0)
        self._check(
            self._cudart.cudaMallocPitch(
                ctypes.byref(dst),
                ctypes.byref(pitch),
                ctypes.c_size_t(w * 4),
                ctypes.c_size_t(h),
            ),
            "cudaMallocPitch",
        )
        try:
            self.assertTrue(
                headless_frame.wait_ready(timeout_ns=10_000_000_000),
                "wait_ready returned False",
            )
            self.assertTrue(
                headless_frame.copy_to_linear(
                    dst.value,
                    pitch.value,
                    cuda_stream_handle=0,
                ),
                "copy_to_linear returned False",
            )
            headless_frame.signal_consumed()

            # Pull the buffer back to host.
            host = (ctypes.c_uint8 * (w * h * 4))()
            self._check(
                self._cudart.cudaMemcpy2D(
                    ctypes.cast(host, ctypes.c_void_p),
                    ctypes.c_size_t(w * 4),
                    dst,
                    pitch,
                    ctypes.c_size_t(w * 4),
                    ctypes.c_size_t(h),
                    ctypes.c_int(self._CUDA_MEMCPY_DEVICE_TO_HOST),
                ),
                "cudaMemcpy2D D2H",
            )
            self._check(
                self._cudart.cudaDeviceSynchronize(), "cudaDeviceSynchronize"
            )

            # A rendered frame must contain at least two distinct byte
            # values somewhere — a uniform clear is fine, but if the
            # whole buffer is identical then either the export silently
            # produced zeros or the readback is broken. Use a cheap
            # variance-style check: count distinct bytes in a sample.
            sample = bytes(host[: min(len(host), 4096)])
            self.assertGreater(
                len(set(sample)),
                1,
                "exported frame appears to be uniform — likely zero-filled",
            )
        finally:
            self._cudart.cudaFree(dst)


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ``ovui_data_adapters.openusd._swap_kernel`` — issue #34 Step 1.5.

The kernel runs on the GPU; tests are skipped automatically when no
CUDA device or runtime is available. On the dev VM (driver 570.158.01,
CUDA 12.6, NVIDIA L40) both tests pass.
"""

from __future__ import annotations

import ctypes
import ctypes.util

import numpy as np
import pytest
from ovui_data_adapters.openusd import _swap_kernel

# ---------------------------------------------------------------------------
# Tiny CUDA Runtime API helper for the tests. The production tap's
# `_Cudart` class only knows D2H/D2D/malloc; tests need H2D too. We keep
# this thin wrapper test-local so the production module stays focused.
# ---------------------------------------------------------------------------

_CUDA_MEMCPY_HTOD = 1
_CUDA_MEMCPY_DTOH = 2


class _TestCuda:
    def __init__(self) -> None:
        candidates = [
            ctypes.util.find_library("cudart"),
            "libcudart.so",
            "libcudart.so.12",
            "libcudart.so.1",
        ]
        last_exc = None
        for c in candidates:
            if not c:
                continue
            try:
                self._lib = ctypes.CDLL(c)
                break
            except OSError as exc:
                last_exc = exc
        else:
            raise OSError(f"libcudart not found: {last_exc!r}")

        L = self._lib
        L.cudaMalloc.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t]
        L.cudaMalloc.restype = ctypes.c_int
        L.cudaFree.argtypes = [ctypes.c_void_p]
        L.cudaFree.restype = ctypes.c_int
        L.cudaMemcpy.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int,
        ]
        L.cudaMemcpy.restype = ctypes.c_int
        L.cudaDeviceSynchronize.argtypes = []
        L.cudaDeviceSynchronize.restype = ctypes.c_int

    def malloc(self, nbytes: int) -> int:
        ptr = ctypes.c_void_p()
        rc = self._lib.cudaMalloc(ctypes.byref(ptr), nbytes)
        if rc != 0:
            raise RuntimeError(f"cudaMalloc({nbytes}) rc={rc}")
        return int(ptr.value)

    def free(self, dev: int) -> None:
        if dev:
            self._lib.cudaFree(ctypes.c_void_p(dev))

    def h2d(self, dev: int, host: np.ndarray) -> None:
        rc = self._lib.cudaMemcpy(
            ctypes.c_void_p(dev),
            host.ctypes.data_as(ctypes.c_void_p),
            host.nbytes,
            _CUDA_MEMCPY_HTOD,
        )
        if rc != 0:
            raise RuntimeError(f"cudaMemcpy H2D rc={rc}")

    def d2h(self, host: np.ndarray, dev: int) -> None:
        rc = self._lib.cudaMemcpy(
            host.ctypes.data_as(ctypes.c_void_p),
            ctypes.c_void_p(dev),
            host.nbytes,
            _CUDA_MEMCPY_DTOH,
        )
        if rc != 0:
            raise RuntimeError(f"cudaMemcpy D2H rc={rc}")

    def sync(self) -> None:
        rc = self._lib.cudaDeviceSynchronize()
        if rc != 0:
            raise RuntimeError(f"cudaDeviceSynchronize rc={rc}")


def _has_gpu() -> bool:
    try:
        cu = _TestCuda()
        ptr = cu.malloc(16)
        cu.free(ptr)
        # Probe NVRTC + driver too — if any of these fail we should
        # skip rather than fail (the kernel can't run anyway).
        _swap_kernel.warm_up()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _has_gpu(),
    reason="CUDA runtime / NVRTC / GPU not available — _swap_kernel needs all three",
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_swap_rb_in_place_8x8_byte_for_byte():
    """Build an 8×8 RGBA fixture with deterministic per-pixel values
    (R=x*32, G=y*32, B=128, A=255), copy to device, run the kernel,
    copy back, assert that each pixel's R and B were exchanged exactly
    (no fractional miscalc, no off-by-one)."""
    W, H = 8, 8
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    for y in range(H):
        for x in range(W):
            rgba[y, x, 0] = (x * 32) & 0xFF   # R
            rgba[y, x, 1] = (y * 32) & 0xFF   # G
            rgba[y, x, 2] = 128                # B
            rgba[y, x, 3] = 255                # A

    expected = rgba.copy()
    expected[..., [0, 2]] = expected[..., [2, 0]]

    cu = _TestCuda()
    nbytes = rgba.nbytes
    dev = cu.malloc(nbytes)
    try:
        cu.h2d(dev, rgba)
        _swap_kernel.swap_rb_in_place(dev, W, H, pitch=W * 4)
        cu.sync()
        out = np.empty_like(rgba)
        cu.d2h(out, dev)
    finally:
        cu.free(dev)

    assert np.array_equal(out, expected)


def test_swap_rb_in_place_1920x1080_covers_height_tail():
    """1080 mod 16 == 8 — the bottom 8 rows live in a "tail" thread
    block. Floor-div ``height // 16 == 67`` blocks would miss them
    entirely; ceil-div ``(1080 + 15) // 16 == 68`` blocks covers them
    and the in-kernel bounds guard masks the out-of-bounds threads at
    ``y in [1080, 1087]``.

    Sanity-check by:
      * filling row 0 and row 1079 with two distinct sentinel
        patterns,
      * running the kernel,
      * asserting both rows have R/B swapped.

    If the ceil-div regressed to floor-div, row 1079 would still
    carry the original (un-swapped) sentinel and the test would fail
    loudly."""
    W, H = 1920, 1080
    rgba = np.zeros((H, W, 4), dtype=np.uint8)

    # Row 0: distinctive RGBA = (0xDE, 0xAD, 0xBE, 0xEF) on every column.
    rgba[0, :, 0] = 0xDE
    rgba[0, :, 1] = 0xAD
    rgba[0, :, 2] = 0xBE
    rgba[0, :, 3] = 0xEF

    # Row 1079 (the last in-bounds row, the one floor-div would miss).
    rgba[1079, :, 0] = 0xCA
    rgba[1079, :, 1] = 0xFE
    rgba[1079, :, 2] = 0xF0
    rgba[1079, :, 3] = 0x0D

    cu = _TestCuda()
    nbytes = rgba.nbytes
    dev = cu.malloc(nbytes)
    try:
        cu.h2d(dev, rgba)
        _swap_kernel.swap_rb_in_place(dev, W, H, pitch=W * 4)
        cu.sync()
        out = np.empty_like(rgba)
        cu.d2h(out, dev)
    finally:
        cu.free(dev)

    # Row 0: R↔B swapped.
    assert (out[0, 0, 0], out[0, 0, 1], out[0, 0, 2], out[0, 0, 3]) == (
        0xBE, 0xAD, 0xDE, 0xEF,
    )
    # Row 1079: R↔B swapped (the height-tail block actually fired).
    assert (out[1079, 0, 0], out[1079, 0, 1], out[1079, 0, 2], out[1079, 0, 3]) == (
        0xF0, 0xFE, 0xCA, 0x0D,
    )
    # And the bottom-right pixel specifically (last column AND last row).
    assert (out[1079, 1919, 0], out[1079, 1919, 1], out[1079, 1919, 2], out[1079, 1919, 3]) == (
        0xF0, 0xFE, 0xCA, 0x0D,
    )

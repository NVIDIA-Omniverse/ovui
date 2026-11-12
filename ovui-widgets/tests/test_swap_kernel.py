# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for ``ovui_data_adapters.openusd._swap_kernel`` — the regression Step 1.5.

The kernel runs on the GPU. The kernels need only the NVIDIA driver (issue
510), so the tests use only the driver too: its CUDA library (libcuda or
nvcuda.dll) gives the device memory. They run on each computer with an
NVIDIA GPU and driver, also without a CUDA toolkit, and skip only when
that library or a CUDA GPU is missing. A kernel that cannot load on a GPU
host fails the tests.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os

import numpy as np
import pytest
from ovui_data_adapters.openusd import _swap_kernel

# ---------------------------------------------------------------------------
# Tiny CUDA Driver API helper for the tests. The production tap's
# `_Cudart` class only knows D2H/D2D/malloc; tests need H2D too. We keep
# this thin wrapper test-local so the production module stays focused.
# It uses the CUDA library of the driver, like the kernel, and the primary
# context of device 0, which the kernel uses when it finds it current.
# ---------------------------------------------------------------------------


class _TestCuda:
    def __init__(self) -> None:
        if os.name == "nt":
            candidates = ["nvcuda.dll"]
        else:
            candidates = [ctypes.util.find_library("cuda"), "libcuda.so.1", "libcuda.so"]
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
            raise OSError(f"the CUDA driver library (libcuda / nvcuda.dll) is not found: {last_exc!r}")

        L = self._lib
        L.cuInit.argtypes = [ctypes.c_uint]
        L.cuInit.restype = ctypes.c_int
        L.cuDeviceGet.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
        L.cuDeviceGet.restype = ctypes.c_int
        L.cuDevicePrimaryCtxRetain.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_int]
        L.cuDevicePrimaryCtxRetain.restype = ctypes.c_int
        L.cuCtxSetCurrent.argtypes = [ctypes.c_void_p]
        L.cuCtxSetCurrent.restype = ctypes.c_int
        L.cuMemAlloc_v2.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t]
        L.cuMemAlloc_v2.restype = ctypes.c_int
        L.cuMemFree_v2.argtypes = [ctypes.c_uint64]
        L.cuMemFree_v2.restype = ctypes.c_int
        L.cuMemcpyHtoD_v2.argtypes = [ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t]
        L.cuMemcpyHtoD_v2.restype = ctypes.c_int
        L.cuMemcpyDtoH_v2.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_size_t]
        L.cuMemcpyDtoH_v2.restype = ctypes.c_int
        L.cuCtxSynchronize.argtypes = []
        L.cuCtxSynchronize.restype = ctypes.c_int

        self._check(L.cuInit(0), "cuInit")
        device = ctypes.c_int(0)
        self._check(L.cuDeviceGet(ctypes.byref(device), 0), "cuDeviceGet")
        ctx = ctypes.c_void_p(0)
        self._check(L.cuDevicePrimaryCtxRetain(ctypes.byref(ctx), device.value),
                    "cuDevicePrimaryCtxRetain")
        self._check(L.cuCtxSetCurrent(ctx), "cuCtxSetCurrent")

    @staticmethod
    def _check(rc: int, what: str) -> None:
        if rc != 0:
            raise RuntimeError(f"{what} rc={rc}")

    def malloc(self, nbytes: int) -> int:
        ptr = ctypes.c_uint64(0)
        self._check(self._lib.cuMemAlloc_v2(ctypes.byref(ptr), nbytes), f"cuMemAlloc({nbytes})")
        return int(ptr.value)

    def free(self, dev: int) -> None:
        if dev:
            self._lib.cuMemFree_v2(dev)

    def h2d(self, dev: int, host: np.ndarray) -> None:
        self._check(
            self._lib.cuMemcpyHtoD_v2(dev, host.ctypes.data_as(ctypes.c_void_p), host.nbytes),
            "cuMemcpyHtoD",
        )

    def d2h(self, host: np.ndarray, dev: int) -> None:
        self._check(
            self._lib.cuMemcpyDtoH_v2(host.ctypes.data_as(ctypes.c_void_p), dev, host.nbytes),
            "cuMemcpyDtoH",
        )

    def sync(self) -> None:
        self._check(self._lib.cuCtxSynchronize(), "cuCtxSynchronize")


def _cuda_gpu() -> tuple[bool, str]:
    """Whether the CUDA driver library and a CUDA GPU are present, and the cause if not."""
    try:
        cu = _TestCuda()
        ptr = cu.malloc(16)
        cu.free(ptr)
        return True, ""
    except Exception as exc:
        return False, str(exc)


_CUDA_GPU, _NO_CUDA_GPU_CAUSE = _cuda_gpu()

pytestmark = pytest.mark.skipif(
    not _CUDA_GPU,
    reason=f"no CUDA GPU with an NVIDIA driver (libcuda / nvcuda.dll): {_NO_CUDA_GPU_CAUSE}",
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


@pytest.mark.parametrize("width,height", [(8, 8), (1920, 1080), (1366, 767)])
def test_copy_swap_rb_writes_bgra_and_leaves_the_source(width, height):
    """The fused out-of-place kernel (the async livestream copy): BGRA in dst, src untouched."""
    rng = np.random.default_rng(3)
    rgba = rng.integers(0, 256, size=(height, width, 4), dtype=np.uint8)
    expected = rgba.copy()
    expected[..., [0, 2]] = expected[..., [2, 0]]

    cu = _TestCuda()
    src = cu.malloc(rgba.nbytes)
    dst = cu.malloc(rgba.nbytes)
    try:
        cu.h2d(src, rgba)
        _swap_kernel.copy_swap_rb(src, width * 4, dst, width * 4, width, height)
        cu.sync()
        out = np.empty_like(rgba)
        cu.d2h(out, dst)
        back = np.empty_like(rgba)
        cu.d2h(back, src)
    finally:
        cu.free(src)
        cu.free(dst)

    assert np.array_equal(out, expected)
    assert np.array_equal(back, rgba)


def test_kernels_load_and_run_without_nvrtc(monkeypatch):
    """Issue 510: the kernels must not need NVRTC. The reported failures
    came from the NVRTC found on the computer: its builtins DLL was not
    on the Windows DLL search path (``nvrtcCompileProgram rc=7``), and a
    Linux toolkit newer than the driver made PTX that the driver rejects
    (``cuModuleLoadData rc=222``). With every NVRTC library unloadable,
    a fresh load of the kernels must still give the exact R/B swap."""
    real_cdll = ctypes.CDLL

    def _cdll_without_nvrtc(name, *args, **kwargs):
        if name and "nvrtc" in str(name).lower():
            raise OSError(f"{name}: NVRTC is not usable on this computer")
        return real_cdll(name, *args, **kwargs)

    monkeypatch.setattr(_swap_kernel.ctypes, "CDLL", _cdll_without_nvrtc)
    # Load the module again in this process instead of reusing the cached one.
    monkeypatch.setattr(_swap_kernel, "_cached", {})

    width, height = 37, 5
    rng = np.random.default_rng(510)
    rgba = rng.integers(0, 256, size=(height, width, 4), dtype=np.uint8)
    expected = rgba.copy()
    expected[..., [0, 2]] = expected[..., [2, 0]]

    cu = _TestCuda()
    src = cu.malloc(rgba.nbytes)
    dst = cu.malloc(rgba.nbytes)
    try:
        _swap_kernel.warm_up()
        cu.h2d(src, rgba)
        _swap_kernel.copy_swap_rb(src, width * 4, dst, width * 4, width, height)
        _swap_kernel.swap_rb_in_place(src, width, height, pitch=width * 4)
        cu.sync()
        copied = np.empty_like(rgba)
        cu.d2h(copied, dst)
        in_place = np.empty_like(rgba)
        cu.d2h(in_place, src)
    finally:
        cu.free(src)
        cu.free(dst)

    assert np.array_equal(copied, expected)
    assert np.array_equal(in_place, expected)

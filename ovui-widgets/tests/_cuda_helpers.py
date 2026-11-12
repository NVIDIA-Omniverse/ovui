# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Test-only CUDA helpers shared across livestream tests.

The production tap's ``_Cudart`` thunk in ``_livestream_tap.py`` only
exposes D2D / D2H / malloc / free. Tests that exercise the real GPU
also need H2D and a top-level "is CUDA available?" probe; those live
here so neither the production module nor any test file has to grow
its own copy.

The filename intentionally does **not** start with ``test_`` so pytest
does not try to collect it as a test module.
"""

from __future__ import annotations

import ctypes
import ctypes.util

import numpy as np

_CUDA_MEMCPY_HTOD = 1
_CUDA_MEMCPY_DTOH = 2


class TestCuda:
    """Thin ctypes wrapper around libcudart for test scaffolding."""

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


def has_cuda_gpu() -> bool:
    """True iff a usable GPU + CUDA library (cudart) are present. Tests
    gated on this skip cleanly on CPU-only hosts. The swap kernel needs
    only the driver, so a kernel that cannot load fails such a test
    (issue 510)."""
    try:
        cu = TestCuda()
        ptr = cu.malloc(16)
        cu.free(ptr)
        return True
    except Exception:
        return False

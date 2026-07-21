# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""NVRTC-compiled in-place R/B channel-swap kernel.

Issue #34 Step 1.5. ovrtx LdrColor is RGBA8; ovstream NVENC consumes
BGRA8. Step 1.6 will wire this kernel into the livestream tap so each
streamed frame has its red and blue channels exchanged before NVENC
sees it.

Design
------

* No `cupy` / `cuda-python` runtime dependency. The module talks to
  libnvrtc and libcuda directly via `ctypes`, mirroring the
  `_Cudart` thunk used elsewhere in the provider-neutral `_livestream_tap.py`.
* Lazy compile on first use, cached at module scope. Subsequent
  launches reuse the loaded `CUmodule` / `CUfunction`.
* 16×16 thread block. Launch grid is **ceil-div**:
  ``((width + 15) // 16, (height + 15) // 16)``. Floor-div would
  drop the bottom 8 rows of a 1080p frame (1080 mod 16 == 8) and
  the right 8 columns of any width that is not a multiple of 16.
* In-kernel bounds guard ``if (x >= w || y >= h) return;`` handles
  the tail threads in the tail blocks safely.
* Pitched layout: row stride is ``pitch`` bytes, not ``width*4``.
  Critical when the caller used `cudaMallocPitch`, which is the streaming
  ring's natural layout.

Public surface
--------------

``swap_rb_in_place(dev_ptr, width, height, pitch, stream=0)`` — launch
the kernel synchronously w.r.t. the host (``cuLaunchKernel`` is async
on the device, but the host-side return is immediate; the encode
pipeline's CUDA stream synchronises the work).

``warm_up()`` — eagerly compile + module-load. Step 1.5 lets the tap
warm the cache during ``_ensure_server`` so the first streamed frame
does not eat the ~50-200 ms NVRTC JIT.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import threading
from typing import Any, Tuple

# ---------------------------------------------------------------------------
# Kernel source. Kept inline so the module has no companion .cu file and is
# trivially shippable with the Python wheel.
# ---------------------------------------------------------------------------

_KERNEL_NAME = b"swap_rb_in_place"

_KERNEL_SRC = """
extern "C" __global__
void swap_rb_in_place(unsigned char* p, int w, int h, unsigned long long pitch)
{
    int x = blockIdx.x * blockDim.x + threadIdx.x;
    int y = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= w || y >= h) return;
    unsigned char* pixel = p + (unsigned long long)y * pitch + (unsigned long long)x * 4;
    unsigned char tmp = pixel[0];
    pixel[0] = pixel[2];
    pixel[2] = tmp;
}
"""


class CudaSwapError(RuntimeError):
    """Raised on any failure from the NVRTC compile, the driver-API
    module load, or ``cuLaunchKernel``. The error message includes the
    underlying CUDA / NVRTC return code so the caller can disable the
    streaming leg with a clear log line."""


# ---------------------------------------------------------------------------
# libnvrtc binding — compile a program string and extract its PTX.
# ---------------------------------------------------------------------------

class _Nvrtc:
    def __init__(self) -> None:
        self._lib = self._load()
        L = self._lib
        L.nvrtcCreateProgram.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_char_p, ctypes.c_char_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_char_p),
        ]
        L.nvrtcCreateProgram.restype = ctypes.c_int
        L.nvrtcCompileProgram.argtypes = [
            ctypes.c_void_p, ctypes.c_int,
            ctypes.POINTER(ctypes.c_char_p),
        ]
        L.nvrtcCompileProgram.restype = ctypes.c_int
        L.nvrtcGetPTXSize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
        L.nvrtcGetPTXSize.restype = ctypes.c_int
        L.nvrtcGetPTX.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        L.nvrtcGetPTX.restype = ctypes.c_int
        L.nvrtcGetProgramLogSize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
        L.nvrtcGetProgramLogSize.restype = ctypes.c_int
        L.nvrtcGetProgramLog.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        L.nvrtcGetProgramLog.restype = ctypes.c_int
        L.nvrtcDestroyProgram.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        L.nvrtcDestroyProgram.restype = ctypes.c_int

    @staticmethod
    def _load() -> Any:
        candidates = [
            ctypes.util.find_library("nvrtc"),
            "libnvrtc.so",
            "libnvrtc.so.12",
            "libnvrtc.so.11",
            "/usr/local/cuda/lib64/libnvrtc.so",
        ]
        last_exc: Any = None
        for c in candidates:
            if not c:
                continue
            try:
                return ctypes.CDLL(c)
            except OSError as exc:
                last_exc = exc
        raise CudaSwapError(f"libnvrtc not found: {last_exc!r}")

    def compile_to_ptx(self, src: str, name: str = "swap_rb.cu") -> bytes:
        prog = ctypes.c_void_p(0)
        rc = self._lib.nvrtcCreateProgram(
            ctypes.byref(prog), src.encode("utf-8"), name.encode("utf-8"),
            0, None, None,
        )
        if rc != 0:
            raise CudaSwapError(f"nvrtcCreateProgram rc={rc}")
        try:
            opts = (ctypes.c_char_p * 0)()
            rc = self._lib.nvrtcCompileProgram(prog, 0, opts)
            if rc != 0:
                log_size = ctypes.c_size_t(0)
                self._lib.nvrtcGetProgramLogSize(prog, ctypes.byref(log_size))
                log = ctypes.create_string_buffer(log_size.value)
                self._lib.nvrtcGetProgramLog(prog, log)
                raise CudaSwapError(
                    f"nvrtcCompileProgram rc={rc}: "
                    f"{log.value.decode('utf-8', 'replace')}"
                )
            ptx_size = ctypes.c_size_t(0)
            rc = self._lib.nvrtcGetPTXSize(prog, ctypes.byref(ptx_size))
            if rc != 0:
                raise CudaSwapError(f"nvrtcGetPTXSize rc={rc}")
            ptx = ctypes.create_string_buffer(ptx_size.value)
            rc = self._lib.nvrtcGetPTX(prog, ptx)
            if rc != 0:
                raise CudaSwapError(f"nvrtcGetPTX rc={rc}")
            return ptx.raw[:ptx_size.value]
        finally:
            self._lib.nvrtcDestroyProgram(ctypes.byref(prog))


# ---------------------------------------------------------------------------
# CUDA Driver API binding — load PTX, look up the function, launch.
# ---------------------------------------------------------------------------

class _Driver:
    def __init__(self) -> None:
        self._lib = self._load()
        L = self._lib
        L.cuInit.argtypes = [ctypes.c_uint]
        L.cuInit.restype = ctypes.c_int
        L.cuDeviceGet.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
        L.cuDeviceGet.restype = ctypes.c_int
        L.cuCtxGetCurrent.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        L.cuCtxGetCurrent.restype = ctypes.c_int
        L.cuDevicePrimaryCtxRetain.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_int]
        L.cuDevicePrimaryCtxRetain.restype = ctypes.c_int
        L.cuCtxSetCurrent.argtypes = [ctypes.c_void_p]
        L.cuCtxSetCurrent.restype = ctypes.c_int
        L.cuModuleLoadData.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        L.cuModuleLoadData.restype = ctypes.c_int
        L.cuModuleGetFunction.argtypes = [
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_char_p,
        ]
        L.cuModuleGetFunction.restype = ctypes.c_int
        L.cuLaunchKernel.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
            ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
            ctypes.c_uint, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        L.cuLaunchKernel.restype = ctypes.c_int

    @staticmethod
    def _load() -> Any:
        candidates = [
            ctypes.util.find_library("cuda"),
            "libcuda.so",
            "libcuda.so.1",
        ]
        last_exc: Any = None
        for c in candidates:
            if not c:
                continue
            try:
                return ctypes.CDLL(c)
            except OSError as exc:
                last_exc = exc
        raise CudaSwapError(f"libcuda not found: {last_exc!r}")

    def init(self) -> None:
        rc = self._lib.cuInit(0)
        # CUDA_SUCCESS == 0; cuInit can be called multiple times safely.
        if rc != 0:
            raise CudaSwapError(f"cuInit rc={rc}")

    def ensure_context(self) -> None:
        """Ensure a CUDA context is current.

        cudart's runtime API installs the device-0 primary context lazily
        when the first allocation is made; we rely on that being the same
        context the driver API sees. If, however, this code runs on a
        thread that has never touched cudart, no context is current and
        ``cuLaunchKernel`` fails with CUDA_ERROR_INVALID_CONTEXT. Pull
        the device-0 primary context onto the calling thread to bridge
        that case."""
        ctx = ctypes.c_void_p(0)
        self._lib.cuCtxGetCurrent(ctypes.byref(ctx))
        if ctx.value:
            return
        device = ctypes.c_int(0)
        rc = self._lib.cuDeviceGet(ctypes.byref(device), 0)
        if rc != 0:
            raise CudaSwapError(f"cuDeviceGet rc={rc}")
        rc = self._lib.cuDevicePrimaryCtxRetain(ctypes.byref(ctx), device.value)
        if rc != 0:
            raise CudaSwapError(f"cuDevicePrimaryCtxRetain rc={rc}")
        rc = self._lib.cuCtxSetCurrent(ctx)
        if rc != 0:
            raise CudaSwapError(f"cuCtxSetCurrent rc={rc}")

    def current_context(self) -> int:
        """Return the current CUDA context handle for this thread."""
        ctx = ctypes.c_void_p(0)
        rc = self._lib.cuCtxGetCurrent(ctypes.byref(ctx))
        if rc != 0:
            raise CudaSwapError(f"cuCtxGetCurrent rc={rc}")
        if not ctx.value:
            raise CudaSwapError("no CUDA context is current")
        return int(ctx.value)

    def load_module(self, ptx: bytes) -> ctypes.c_void_p:
        module = ctypes.c_void_p(0)
        ptx_buf = ctypes.create_string_buffer(ptx)
        rc = self._lib.cuModuleLoadData(ctypes.byref(module), ptx_buf)
        if rc != 0:
            raise CudaSwapError(f"cuModuleLoadData rc={rc}")
        return module

    def get_function(self, module: ctypes.c_void_p, name: bytes) -> ctypes.c_void_p:
        func = ctypes.c_void_p(0)
        rc = self._lib.cuModuleGetFunction(ctypes.byref(func), module, name)
        if rc != 0:
            raise CudaSwapError(f"cuModuleGetFunction({name!r}) rc={rc}")
        return func

    def launch(
        self,
        func: ctypes.c_void_p,
        grid: Tuple[int, int, int],
        block: Tuple[int, int, int],
        ctypes_args: list,
        stream: int = 0,
    ) -> None:
        """Invoke ``cuLaunchKernel``.

        ``ctypes_args`` is a list of *ctypes value instances* (e.g.
        ``c_void_p(...)``, ``c_int(...)``). The function takes
        ``addressof`` for each so the driver gets the
        ``void* kernelParams[]`` shape it expects.
        """
        gx, gy, gz = grid
        bx, by, bz = block
        n = len(ctypes_args)
        pointer_array = (ctypes.c_void_p * n)()
        for i, val in enumerate(ctypes_args):
            pointer_array[i] = ctypes.addressof(val)
        rc = self._lib.cuLaunchKernel(
            func,
            ctypes.c_uint(gx), ctypes.c_uint(gy), ctypes.c_uint(gz),
            ctypes.c_uint(bx), ctypes.c_uint(by), ctypes.c_uint(bz),
            ctypes.c_uint(0),
            ctypes.c_void_p(stream),
            pointer_array,
            None,
        )
        if rc != 0:
            raise CudaSwapError(f"cuLaunchKernel rc={rc}")


# ---------------------------------------------------------------------------
# Module-scope cache. The lock guards the first-time NVRTC compile from a
# multi-threaded import race. Subsequent calls hit the cache directly with
# no locking on the hot path.
# ---------------------------------------------------------------------------

_state_lock = threading.Lock()
_cached: dict = {}


def _ensure_compiled() -> dict:
    """Return the kernel state bound to this thread's current CUDA context."""
    driver = _Driver()
    driver.init()
    driver.ensure_context()
    cache_key = ("v1", driver.current_context())
    cached = _cached.get(cache_key)
    if cached is not None:
        return cached
    with _state_lock:
        cached = _cached.get(cache_key)
        if cached is not None:
            return cached
        nvrtc = _Nvrtc()
        ptx = nvrtc.compile_to_ptx(_KERNEL_SRC)
        module = driver.load_module(ptx)
        func = driver.get_function(module, _KERNEL_NAME)
        cached = {
            "driver": driver,
            "module": module,
            "func": func,
            "ptx": ptx,
        }
        _cached[cache_key] = cached
        return cached


def warm_up() -> None:
    """Eagerly compile + load the kernel into the current CUDA context.

    Useful to avoid first-frame NVRTC JIT cost (~50-200 ms on this
    GPU) on the first push to NVENC. Safe to call repeatedly; cached
    after the first run.
    """
    _ensure_compiled()


def swap_rb_in_place(
    dev_ptr: int,
    width: int,
    height: int,
    pitch: int,
    stream: int = 0,
) -> None:
    """Swap R and B channels in place on a pitched RGBA8 device buffer.

    ``dev_ptr`` is a CUDA device pointer (int) to a row-major RGBA8
    image of dimensions ``width * height`` whose row stride is
    ``pitch`` bytes (``pitch >= width * 4``). After this call the
    buffer's R and B channels are exchanged on each pixel; the kernel
    runs in-place.

    Launch is non-blocking on the device (``cuLaunchKernel`` is
    asynchronous on ``stream``); host-side it returns immediately.
    The encode pipeline's CUDA stream is responsible for any required
    serialisation between this kernel and the next consumer
    (``ovstream.Server.stream_video``).
    """
    if width <= 0 or height <= 0:
        return
    required_pitch = width * 4
    if pitch < required_pitch:
        raise ValueError(
            f"pitch ({pitch}) must be >= width*4 ({required_pitch})"
        )

    state = _ensure_compiled()
    driver = state["driver"]
    func = state["func"]

    block = (16, 16, 1)
    grid = (((width + 15) // 16), ((height + 15) // 16), 1)

    # Kernel signature: (unsigned char*, int, int, unsigned long long).
    # The first arg is a device pointer; the kernel reads 8 bytes from
    # the kernelParams[0] slot and treats it as that pointer's value.
    p_val  = ctypes.c_uint64(int(dev_ptr))
    w_val  = ctypes.c_int(int(width))
    h_val  = ctypes.c_int(int(height))
    pi_val = ctypes.c_uint64(int(pitch))

    driver.launch(func, grid, block, [p_val, w_val, h_val, pi_val], stream=stream)

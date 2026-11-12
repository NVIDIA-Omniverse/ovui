# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""In-place R/B channel-swap kernel, loaded as PTX by the CUDA driver.

ovrtx LdrColor is RGBA8; ovstream NVENC consumes
BGRA8. Step 1.6 will wire this kernel into the livestream tap so each
streamed frame has its red and blue channels exchanged before NVENC
sees it.

Design
------

* No `cupy` / `cuda-python` runtime dependency. The module talks to
  libcuda directly via `ctypes`, mirroring the
  `_Cudart` thunk used elsewhere in the provider-neutral `_livestream_tap.py`.
* The kernels are PTX text. The CUDA driver compiles them for the GPU
  when the module loads, so no NVRTC (CUDA toolkit) library is used. An NVRTC
  found on the computer made the stream fail: on Windows its
  builtins DLL was not on the DLL search path (``nvrtcCompileProgram
  rc=7``), and on Linux a toolkit newer than the driver made PTX that the
  driver rejects (``cuModuleLoadData rc=222``).
* Lazy load on first use, cached at module scope. Subsequent
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

``warm_up()`` — eagerly module-load. The tap loads the kernels during
``_ensure_server`` so the first streamed frame does not wait for the
driver's PTX compile, and a stream that cannot swap R/B does not start.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import threading
from typing import Any, Tuple

# ---------------------------------------------------------------------------
# Kernel PTX. Kept inline so the module has no companion file and is
# trivially shippable with the Python wheel.
#
# PTX ISA 4.1 is the first version with the sm_52 target, the default
# target of the CUDA 12 NVRTC that compiled these kernels before, and the
# code uses only PTX ISA 2.0 instructions. So each driver since CUDA 6.5
# loads it and compiles it for each GPU from sm_52 on. A newer `.version`
# makes an older driver reject the module (CUDA_ERROR_UNSUPPORTED_PTX_VERSION).
# ---------------------------------------------------------------------------

_KERNEL_NAME = b"swap_rb_in_place"

_PTX = r"""
.version 4.1
.target sm_52
.address_size 64

// swap_rb_in_place(unsigned char* p, int w, int h, unsigned long long pitch)
// Thread (x, y) exchanges bytes 0 and 2 of the pixel at p + y * pitch + x * 4.
.visible .entry swap_rb_in_place(
    .param .u64 swap_rb_in_place_param_0,
    .param .u32 swap_rb_in_place_param_1,
    .param .u32 swap_rb_in_place_param_2,
    .param .u64 swap_rb_in_place_param_3
)
{
    .reg .pred %p<4>;
    .reg .b16 %rs<3>;
    .reg .b32 %r<11>;
    .reg .b64 %rd<9>;

    ld.param.u64 %rd1, [swap_rb_in_place_param_0];
    ld.param.u32 %r3, [swap_rb_in_place_param_1];
    ld.param.u32 %r4, [swap_rb_in_place_param_2];
    ld.param.u64 %rd2, [swap_rb_in_place_param_3];
    // x = blockIdx.x * blockDim.x + threadIdx.x; y likewise.
    mov.u32 %r5, %ntid.x;
    mov.u32 %r6, %ctaid.x;
    mov.u32 %r7, %tid.x;
    mad.lo.s32 %r1, %r6, %r5, %r7;
    mov.u32 %r8, %ntid.y;
    mov.u32 %r9, %ctaid.y;
    mov.u32 %r10, %tid.y;
    mad.lo.s32 %r2, %r9, %r8, %r10;
    // if (x >= w || y >= h) return;
    setp.ge.s32 %p1, %r1, %r3;
    setp.ge.s32 %p2, %r2, %r4;
    or.pred %p3, %p1, %p2;
    @%p3 bra $L__BB0_2;

    cvt.s64.s32 %rd3, %r2;
    mul.lo.s64 %rd4, %rd3, %rd2;
    mul.wide.s32 %rd5, %r1, 4;
    add.s64 %rd6, %rd4, %rd5;
    cvta.to.global.u64 %rd7, %rd1;
    add.s64 %rd8, %rd7, %rd6;
    ld.global.u8 %rs1, [%rd8];
    ld.global.u8 %rs2, [%rd8+2];
    st.global.u8 [%rd8], %rs2;
    st.global.u8 [%rd8+2], %rs1;

$L__BB0_2:
    ret;
}

// copy_swap_rb(const unsigned char* src, unsigned long long src_pitch,
// unsigned char* dst, unsigned long long dst_pitch, int w, int h)
// Thread (x, y) reads the 32-bit RGBA pixel p of src and writes
// (p & 0xFF00FF00) | ((p & 0xFF) << 16) | ((p >> 16) & 0xFF) to dst.
.visible .entry copy_swap_rb(
    .param .u64 copy_swap_rb_param_0,
    .param .u64 copy_swap_rb_param_1,
    .param .u64 copy_swap_rb_param_2,
    .param .u64 copy_swap_rb_param_3,
    .param .u32 copy_swap_rb_param_4,
    .param .u32 copy_swap_rb_param_5
)
{
    .reg .pred %p<4>;
    .reg .b32 %r<19>;
    .reg .b64 %rd<15>;

    ld.param.u64 %rd1, [copy_swap_rb_param_0];
    ld.param.u64 %rd2, [copy_swap_rb_param_1];
    ld.param.u64 %rd3, [copy_swap_rb_param_2];
    ld.param.u64 %rd4, [copy_swap_rb_param_3];
    ld.param.u32 %r3, [copy_swap_rb_param_4];
    ld.param.u32 %r4, [copy_swap_rb_param_5];
    // x = blockIdx.x * blockDim.x + threadIdx.x; y likewise.
    mov.u32 %r5, %ctaid.x;
    mov.u32 %r6, %ntid.x;
    mov.u32 %r7, %tid.x;
    mad.lo.s32 %r1, %r5, %r6, %r7;
    mov.u32 %r8, %ntid.y;
    mov.u32 %r9, %ctaid.y;
    mov.u32 %r10, %tid.y;
    mad.lo.s32 %r2, %r9, %r8, %r10;
    // if (x >= w || y >= h) return;
    setp.ge.s32 %p1, %r1, %r3;
    setp.ge.s32 %p2, %r2, %r4;
    or.pred %p3, %p1, %p2;
    @%p3 bra $L__BB1_2;

    cvta.to.global.u64 %rd5, %rd1;
    cvt.s64.s32 %rd6, %r2;
    mul.lo.s64 %rd7, %rd6, %rd2;
    mul.wide.s32 %rd8, %r1, 4;
    add.s64 %rd9, %rd7, %rd8;
    add.s64 %rd10, %rd5, %rd9;
    ld.global.u32 %r11, [%rd10];
    and.b32 %r12, %r11, -16711936;
    shl.b32 %r13, %r11, 16;
    and.b32 %r14, %r13, 16711680;
    or.b32 %r15, %r14, %r12;
    shr.u32 %r16, %r11, 16;
    and.b32 %r17, %r16, 255;
    or.b32 %r18, %r15, %r17;
    mul.lo.s64 %rd11, %rd6, %rd4;
    add.s64 %rd12, %rd11, %rd8;
    cvta.to.global.u64 %rd13, %rd3;
    add.s64 %rd14, %rd13, %rd12;
    st.global.u32 [%rd14], %r18;

$L__BB1_2:
    ret;
}
"""

_COPY_KERNEL_NAME = b"copy_swap_rb"


class CudaSwapError(RuntimeError):
    """Raised on any failure from the driver-API module load or
    ``cuLaunchKernel``. The error message includes the underlying CUDA
    return code so the caller can disable the streaming leg with a
    clear log line."""


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
        if os.name == "nt":
            # Windows x64: the CUDA driver library.
            candidates = ["nvcuda.dll"]
        else:
            # Linux x86_64 and Linux ARM64 library names.
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
# Module-scope cache. The lock guards the first-time driver setup and PTX
# module load from a multi-threaded import race. Subsequent calls hit the
# cache directly with no locking on the hot path.
# ---------------------------------------------------------------------------

_state_lock = threading.Lock()
_cached: dict = {}


_driver = None


def _shared_driver() -> _Driver:
    """One driver binding per process; cuInit runs once, not on every launch."""
    global _driver
    if _driver is None:
        with _state_lock:
            if _driver is None:
                driver = _Driver()
                driver.init()
                _driver = driver
    return _driver


def _ensure_compiled() -> dict:
    """Return the kernel state bound to this thread's current CUDA context."""
    driver = _shared_driver()
    driver.ensure_context()
    cache_key = ("v2", driver.current_context())
    cached = _cached.get(cache_key)
    if cached is not None:
        return cached
    with _state_lock:
        cached = _cached.get(cache_key)
        if cached is not None:
            return cached
        module = driver.load_module(_PTX.encode("ascii"))
        func = driver.get_function(module, _KERNEL_NAME)
        cached = {
            "driver": driver,
            "module": module,
            "func": func,
            "copy_func": driver.get_function(module, _COPY_KERNEL_NAME),
        }
        _cached[cache_key] = cached
        return cached


def warm_up() -> None:
    """Eagerly load the kernels into the current CUDA context.

    Useful to avoid the driver's first-frame PTX compile on the first
    push to NVENC, and to find a kernel that cannot load before a
    stream starts. Safe to call repeatedly; cached after the first run.
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


def copy_swap_rb(
    src_ptr: int,
    src_pitch: int,
    dst_ptr: int,
    dst_pitch: int,
    width: int,
    height: int,
    stream: int = 0,
) -> None:
    """Copy a pitched RGBA8 device image to ``dst`` as BGRA8, in one kernel on ``stream``.

    Replaces a D2D copy followed by :func:`swap_rb_in_place`: one read and one write per pixel,
    queued on the caller's stream (asynchronous on host and device).
    """
    if width <= 0 or height <= 0:
        return
    if src_pitch < width * 4 or dst_pitch < width * 4:
        raise ValueError(f"pitches ({src_pitch}, {dst_pitch}) must be >= width*4 ({width * 4})")
    state = _ensure_compiled()
    block = (32, 8, 1)
    grid = (((width + 31) // 32), ((height + 7) // 8), 1)
    args = [
        ctypes.c_uint64(int(src_ptr)), ctypes.c_uint64(int(src_pitch)),
        ctypes.c_uint64(int(dst_ptr)), ctypes.c_uint64(int(dst_pitch)),
        ctypes.c_int(int(width)), ctypes.c_int(int(height)),
    ]
    state["driver"].launch(state["copy_func"], grid, block, args, stream=stream)

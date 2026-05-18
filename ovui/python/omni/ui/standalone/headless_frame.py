# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""High-level Python wrappers for the headless frame export pipeline.

These are thin wrappers over the ``_ui._headless_frame_*`` pybind11 bindings
declared in ``bindings/StandalonePlatformBindings.cpp`` and implemented in
``standalone/src/StandaloneInit.cpp``. They expose ovui's offscreen
Vulkan render target as a CUDA pitched-linear buffer that downstream
consumers (e.g. ovgear's livestream tap) can hand to NVENC.

Required environment for the underlying pipeline:

- ``OMNIUI_HEADLESS=1`` and ``OMNIUI_BACKEND=vulkan`` set *before*
  :func:`omni.ui.standalone.init`.
- A Vulkan-capable device with CUDA-Vulkan interop support.

Typical per-frame sequence after one ovui tick has run::

    headless_frame.init()
    w, h = headless_frame.extent()
    # caller allocates a pitched RGBA8 buffer of (h x w*4) bytes
    headless_frame.wait_ready(timeout_ns=10_000_000)
    headless_frame.copy_to_linear(dst_dev_ptr, dst_pitch_bytes, cuda_stream_handle=0)
    # caller consumes the pitched buffer (encode, swap channels, etc.)
    headless_frame.signal_consumed()

The init/shutdown calls are safe to repeat. A second :func:`init`
returns ``False`` (already-initialised is not an error, but the call
is a no-op and reports ``False``); :func:`shutdown` after teardown is
a no-op.
"""

from __future__ import annotations

from .. import _ui

__all__ = [
    "init",
    "shutdown",
    "extent",
    "format",
    "wait_ready",
    "signal_consumed",
    "copy_to_linear",
    "resize",
]


def init() -> bool:
    """Initialise the headless frame export pipeline.

    Returns ``True`` on a successful first-time initialisation. Returns
    ``False`` if the C++ side refused (e.g. no platform initialised,
    ``OMNIUI_HEADLESS`` not set, or the backend is not Vulkan) *or* if
    the pipeline was already initialised by a previous call — repeated
    calls are safe but report ``False`` rather than re-initialising.
    """
    return bool(_ui._headless_frame_init())


def shutdown() -> None:
    """Tear down the headless frame export pipeline.

    Safe to call when the pipeline was never initialised.
    """
    _ui._headless_frame_shutdown()


def extent() -> tuple[int, int]:
    """Return ``(width, height)`` of the exported frame.

    Returns ``(0, 0)`` if the pipeline is not initialised.
    """
    w, h = _ui._headless_frame_extent()
    return (int(w), int(h))


def format() -> str:
    """Return the pixel format of the exported frame (e.g. ``'rgba8'``)."""
    return _ui._headless_frame_format()


def wait_ready(timeout_ns: int) -> bool:
    """Wait for the most recent Vulkan render to finish (V→C semaphore).

    ``timeout_ns`` is accepted for forward compatibility; the current
    implementation queues an asynchronous CUDA wait on the V→C semaphore
    via :func:`cudaWaitExternalSemaphoresAsync` and returns immediately.
    Subsequent CUDA work issued on the same stream observes the signalled
    state. Returns ``True`` on success.
    """
    return bool(_ui._headless_frame_wait_ready(int(timeout_ns)))


def signal_consumed() -> None:
    """Notify ovui that the consumer has finished reading the frame.

    Issues the C→V semaphore signal so the next ovui tick can reuse the
    offscreen image.
    """
    _ui._headless_frame_signal_consumed()


def copy_to_linear(
    dst_dev_ptr: int,
    dst_pitch_bytes: int,
    cuda_stream_handle: int = 0,
) -> bool:
    """Copy the offscreen frame into a caller-owned pitched-linear CUDA buffer.

    ``dst_dev_ptr`` must point to a CUDA allocation of at least
    ``height * dst_pitch_bytes`` bytes; ``dst_pitch_bytes`` must be at
    least ``width * 4`` (RGBA8). Pass ``cuda_stream_handle=0`` for the
    default stream.

    Issues ``cudaMemcpy2DFromArrayAsync`` on the supplied stream. Returns
    ``True`` on success, ``False`` if the pipeline is not initialised or
    the parameters are invalid.
    """
    return bool(
        _ui._headless_frame_copy_to_linear(
            int(dst_dev_ptr),
            int(dst_pitch_bytes),
            int(cuda_stream_handle),
        )
    )


def resize(width: int, height: int) -> bool:
    """Resize the active headless offscreen render target.

    Tears the CUDA-Vulkan interop down (the imported VkImage handle
    is keyed to the current Vulkan memory and becomes invalid the
    moment the framebuffer is recreated), updates the headless
    platform's main window size, drives one tick so
    ``VulkanBackend::beginFrame`` rebuilds the framebuffer at the new
    extent, verifies the framebuffer matches the request, and
    re-imports the new image into CUDA.

    Returns ``True`` on success. Returns ``False`` on:
    invalid dimensions, no headless platform active, framebuffer
    extent mismatch after recreation, or CUDA re-import failure. On
    failure the prior interop state is best-effort restored so the
    streaming pipeline does not hang.

    Caller must ensure no consumer (e.g. NVENC encoder) is mid-flight
    against the current frame when calling. The downstream
    ``LivestreamTap`` will rebuild its scratch ring on the next frame
    because :func:`extent` then reports the new size.
    """
    return bool(_ui._headless_frame_resize(int(width), int(height)))

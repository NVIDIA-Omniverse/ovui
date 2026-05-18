# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""
ByteImageProvider zero-copy GPU upload example.

Shows how to feed a CUDA device pointer into ``ui.ByteImageProvider`` via
``set_bytes_data_from_gpu(int(dptr), [W, H])`` — the path that hands a
``VkImage`` to ImGui without a CPU round-trip.

Run:  python examples/byte_image_gpu_demo.py
      python examples/byte_image_gpu_demo.py --screenshot

Requirements:
  * A Vulkan-capable build of ovui with CUDA support.
    Verify with ``omni.ui.has_gpu_byte_image()`` — must return True.
  * Example dependencies from this ovui directory:
    ``python -m pip install -e ".[examples]"``.
    This installs numpy and cuda-python.

Headless: for the windowed run, GLFW needs an X display. On a headless
Linux host you can either point at an Xvfb display (``DISPLAY=:99``) or
set ``OMNIUI_HEADLESS=1`` and use ``--screenshot``, which renders one
frame to a PNG and exits.
"""
from __future__ import annotations

import os
import sys

# The fromGpu CUDA → Vulkan path only exists on the Vulkan backend; ensure
# we're not silently dispatched to OpenGL. Set before importing omni.ui.
os.environ.setdefault("OMNIUI_BACKEND", "vulkan")

import numpy as np
import omni.ui as ui

_SCREENSHOT = "--screenshot" in sys.argv

# Synthetic RGBA8 gradient — small, visually distinctive, no external assets.
W, H = 256, 256
xs = np.linspace(0, 255, W, dtype=np.uint8)
ys = np.linspace(0, 255, H, dtype=np.uint8)
gx, gy = np.meshgrid(xs, ys)
gradient = np.stack(
    [gx, gy, ((gx.astype(np.uint16) + gy) // 2).astype(np.uint8), np.full_like(gx, 255)],
    axis=-1,
)
N_BYTES = gradient.nbytes  # W * H * 4

ui.init("byte_image_gpu_demo", width=640, height=420)

if not ui.has_gpu_byte_image():
    print(
        "omni.ui.has_gpu_byte_image() is False — this build does not have the "
        "CUDA-Vulkan zero-copy path wired up. Rebuild with Vulkan + CUDA, or use "
        "ByteImageProvider.set_data() for the host-upload path instead.",
        file=sys.stderr,
    )
    ui.shutdown()
    sys.exit(1)

# --- Allocate a CUDA device buffer and copy the gradient onto it.
from cuda.bindings import driver as cuda


def _cu(rc, where: str):
    err, *rest = rc if isinstance(rc, tuple) else (rc,)
    if int(err) != 0:
        raise RuntimeError(f"{where}: cuda error {int(err)}")
    return rest[0] if len(rest) == 1 else (rest or None)


_cu(cuda.cuInit(0), "cuInit")
_dev = _cu(cuda.cuDeviceGet(0), "cuDeviceGet")
try:
    _ctx = _cu(cuda.cuCtxCreate(0, _dev), "cuCtxCreate")           # cuda-python 12.x
except TypeError:
    _ctx = _cu(cuda.cuCtxCreate(None, 0, _dev), "cuCtxCreate")     # cuda-python 13.x
_dptr = _cu(cuda.cuMemAlloc(N_BYTES), "cuMemAlloc")
_cu(cuda.cuMemcpyHtoD(_dptr, gradient.tobytes(), N_BYTES), "cuMemcpyHtoD")
_cu(cuda.cuCtxSynchronize(), "cuCtxSynchronize")

# --- Hand the GPU pointer to a ByteImageProvider.
provider = ui.ByteImageProvider()
provider.set_bytes_data_from_gpu(int(_dptr), [W, H])

# --- Build a minimal UI: a window with one label + one image.
win = ui.Window(
    "ByteImageProvider — zero-copy CUDA \u2192 Vulkan",
    width=640, height=420,
    flags=ui.WINDOW_FLAGS_NO_RESIZE | ui.WINDOW_FLAGS_NO_MOVE,
    position_x=0, position_y=0,
)
with win.frame:
    with ui.VStack(spacing=8, style={"margin": 16}):
        ui.Label(
            f"{W}x{H} RGBA8 gradient uploaded from a CUDA device pointer "
            f"via ByteImageProvider.set_bytes_data_from_gpu().",
            height=24,
            style={"font_size": 14, "color": 0xFFE0E0E0},
        )
        ui.ImageWithProvider(provider, width=W, height=H)


def _free_cuda() -> None:
    cuda.cuMemFree(_dptr)
    cuda.cuCtxDestroy(_ctx)


async def _capture(path: str) -> None:
    from omni.ui import testing
    await testing.wait_frames(4)
    testing.capture_screenshot(path)
    print(f"screenshot saved: {path}")


if __name__ == "__main__":
    try:
        if _SCREENSHOT:
            ui.run(_capture("byte_image_gpu_demo.png"))
        else:
            ui.run()
    finally:
        _free_cuda()

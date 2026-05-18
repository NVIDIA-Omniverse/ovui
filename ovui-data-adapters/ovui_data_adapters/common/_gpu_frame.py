# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Zero-copy GPU ingest state + GPU frame marker.

Tier-2 of the strata#16 zero-copy path. When `OVGEAR_ZERO_COPY=1` is set
in the environment, the renderer maps the LdrColor render variable on the
CUDA device and hands the raw device pointer to ovui via
`ByteImageProvider.set_bytes_data_from_gpu`. This avoids the GPU→CPU
readback that tier-1 still performs.

The runtime probe is needed because ovui's standalone GPU backends
(OpenGLByteImageGpu, VulkanByteImageGpu) on `main` silently no-op the
fromGpu path with a `fprintf(stderr, "...: fromGpu not supported\\n")` —
i.e. set_bytes_data_from_gpu LOOKS callable from Python but doesn't update
pixels. The probe captures fd-2 around the first GPU push and falls back
permanently to tier-1 (CPU map → set_data_array) when the warning is
detected. That way, when ovui's `feat/cuda-vk-interop` branch (commit
cace704) lands on main, this code activates without an ovgear change.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class _Mode(Enum):
    DISABLED = "disabled"   # env flag not set or zero-copy not requested
    PROBING = "probing"     # env flag set; first GPU push will probe stderr
    ENABLED = "enabled"     # probe succeeded; GPU ingest works
    FALLBACK = "fallback"   # probe found standalone no-op; tier-1 forever


# Sentinel printed by ovui standalone backends when fromGpu is unsupported.
# See ovui/standalone/src/{OpenGLByteImageGpu,VulkanByteImageGpu}.cpp.
_STANDALONE_NOOP_MARKER = "fromGpu not supported"


@dataclass
class ZeroCopyState:
    """Shared state coordinating renderer and bridge zero-copy decisions."""

    mode: _Mode = _Mode.DISABLED
    fallback_reason: Optional[str] = None

    @classmethod
    def from_env(cls) -> "ZeroCopyState":
        if os.environ.get("OVGEAR_ZERO_COPY") == "1":
            return cls(mode=_Mode.PROBING)
        return cls(mode=_Mode.DISABLED)

    @property
    def gpu_pending(self) -> bool:
        """True iff renderer should map on CUDA and yield a GpuFrame."""
        return self.mode in (_Mode.PROBING, _Mode.ENABLED)

    @property
    def enabled(self) -> bool:
        return self.mode == _Mode.ENABLED

    @property
    def disabled(self) -> bool:
        return self.mode == _Mode.DISABLED

    def mark_enabled(self) -> None:
        if self.mode == _Mode.PROBING:
            self.mode = _Mode.ENABLED
            print("[ovgear/zero-copy] tier-2 enabled — set_bytes_data_from_gpu confirmed",
                  file=sys.stderr)

    def mark_fallback(self, reason: str) -> None:
        if self.mode in (_Mode.PROBING, _Mode.ENABLED):
            self.mode = _Mode.FALLBACK
            self.fallback_reason = reason
            print(f"[ovgear/zero-copy] tier-2 unavailable — falling back to tier-1: {reason}",
                  file=sys.stderr)


class GpuFrame:
    """Marker carrying a live CUDA device pointer for zero-copy ingest.

    The renderer creates a GpuFrame by entering an `rv.map(device=CUDA)`
    context and capturing `mapping.tensor.data`. The mapping must remain
    *entered* while the bridge dereferences `ptr` inside ovui's
    `set_bytes_data_from_gpu` (which performs the CUDA→Vulkan/GL interop
    copy). The bridge calls :meth:`close` after the ovui call completes
    (or if it bails out) to release the mapping.
    """

    __slots__ = ("ptr", "width", "height", "_mapping")

    def __init__(self, ptr: int, width: int, height: int, mapping: Optional[object] = None) -> None:
        self.ptr = ptr
        self.width = width
        self.height = height
        self._mapping = mapping

    def close(self) -> None:
        """Exit the underlying mapping context (releases the device pointer)."""
        m = self._mapping
        if m is None:
            return
        self._mapping = None
        try:
            m.__exit__(None, None, None)
        except Exception:
            pass

    def __del__(self) -> None:  # safety net
        try:
            self.close()
        except Exception:
            pass

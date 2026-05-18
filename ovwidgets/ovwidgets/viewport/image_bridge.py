# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ByteImageProvider bridge — decouples renderer from ovui."""

from __future__ import annotations

import os
import tempfile
from typing import Optional, Union

import numpy as np
import omni.ui as ui
from ovui_data_adapters.common import _STANDALONE_NOOP_MARKER, GpuFrame, ZeroCopyState


class ImageBridge:
    """Owns a ui.ByteImageProvider. Call update(frame) each render frame.

    `frame` may be a numpy ndarray (tier-1 / fallback path) or a
    :class:`GpuFrame` carrying a CUDA device pointer (tier-2 zero-copy).
    Dispatch is by type. The first GpuFrame triggers a runtime probe that
    captures fd-2 around `set_bytes_data_from_gpu`; if ovui's standalone
    backend prints the "fromGpu not supported" sentinel we latch the
    shared :class:`ZeroCopyState` to FALLBACK so the renderer reverts to
    tier-1 from the next frame onward.
    """

    def __init__(
        self,
        width: int,
        height: int,
        state: Optional[ZeroCopyState] = None,
    ) -> None:
        self._width = width
        self._height = height
        self._provider = ui.ByteImageProvider()
        self._state = state
        blank = np.zeros((height, width, 4), dtype=np.uint8)
        blank[:, :, 3] = 255
        self._provider.set_data_array(blank, [width, height])

    @property
    def provider(self) -> ui.ByteImageProvider:
        return self._provider

    def update(self, frame: Union[np.ndarray, GpuFrame]) -> None:
        """Push a new frame into the provider.

        Accepts either an (H, W, 4) uint8 ndarray or a :class:`GpuFrame`.
        """
        if isinstance(frame, GpuFrame):
            self._update_gpu(frame)
            return
        h, w = frame.shape[:2]
        if w != self._width or h != self._height:
            self._width = w
            self._height = h
        self._provider.set_data_array(frame, [w, h])

    def _update_gpu(self, frame: GpuFrame) -> None:
        w, h = frame.width, frame.height
        if w != self._width or h != self._height:
            self._width = w
            self._height = h
        try:
            if self._state is not None and self._state.mode.value == "probing":
                with _capture_fd2() as cap:
                    self._provider.set_bytes_data_from_gpu(frame.ptr, [w, h])
                captured = cap.read()
                if _STANDALONE_NOOP_MARKER in captured:
                    # Re-emit so users see the original warning once.
                    _write_fd2(captured)
                    self._state.mark_fallback(
                        "ovui standalone backend printed 'fromGpu not supported'"
                    )
                    return
                self._state.mark_enabled()
                return
            self._provider.set_bytes_data_from_gpu(frame.ptr, [w, h])
        finally:
            # Always release the CUDA mapping the renderer entered for us,
            # even if ovui's GPU push raised. The pointer is invalidated
            # when the mapping context exits, so this MUST run after the
            # set_bytes_data_from_gpu call returns synchronously.
            frame.close()


class _capture_fd2:
    """Context manager that captures fd 2 (C-level stderr) into a temp file.

    Python's `contextlib.redirect_stderr` only swaps `sys.stderr` and does
    not catch fprintf(stderr, ...) from native code. We dup fd 2 to a
    temp file for the duration of the block.
    """

    def __init__(self) -> None:
        self._saved_fd = -1
        self._tmp = None  # type: Optional[tempfile.SpooledTemporaryFile]

    def __enter__(self) -> "_capture_fd2":
        self._saved_fd = os.dup(2)
        self._tmp = tempfile.SpooledTemporaryFile(max_size=64 * 1024, mode="w+b")
        os.dup2(self._tmp.fileno(), 2)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            os.fsync(2)
        except OSError:
            pass
        os.dup2(self._saved_fd, 2)
        os.close(self._saved_fd)
        self._saved_fd = -1

    def read(self) -> str:
        if self._tmp is None:
            return ""
        self._tmp.seek(0)
        data = self._tmp.read()
        self._tmp.close()
        self._tmp = None
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:
            return ""


def _write_fd2(s: str) -> None:
    try:
        os.write(2, s.encode("utf-8", errors="replace"))
    except OSError:
        pass

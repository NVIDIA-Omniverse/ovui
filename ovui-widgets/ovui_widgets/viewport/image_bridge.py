# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ByteImageProvider bridge — decouples renderer from ovui."""

from __future__ import annotations

import os
import tempfile
from typing import Optional, Union

import numpy as np
import omni.ui as ui
from ovui_data_adapters.common import _STANDALONE_NOOP_MARKER, GpuFrame, ZeroCopyState



def _has_gpu_byte_image() -> bool:
    """Whether this ovui build can actually push a CUDA pointer into an image.

    Mirrors what the native upload path checks, so the probe cannot report
    success on a build that has no interop compiled in.
    """
    try:
        import omni.ui as ui

        return bool(ui.has_gpu_byte_image())
    except Exception:
        return False


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

    def clear(self) -> None:
        """Show no image: a fully transparent frame lets the background show."""
        clear = np.zeros((self._height, self._width, 4), dtype=np.uint8)
        self._provider.set_data_array(clear, [self._width, self._height])

    def update(self, frame: Union[np.ndarray, GpuFrame, None]) -> Optional[bool]:
        """Push a new frame into the provider.

        Accepts either an (H, W, 4) uint8 ndarray or a :class:`GpuFrame`.
        ``None`` means a native frame-pacing coordinator owns publication;
        the provider's stable presentation key must remain untouched.

        Returns ``False`` when ovui rejected the upload. The provider then
        still shows the previous frame, so the caller must not count this
        frame as presented. Returns ``True`` when ovui accepted the pixels
        and ``None`` when nothing was pushed, when ovui has no GPU backend
        (no renderer, which is not a refusal), or when ovui gave no answer
        (an older ovui returns ``None`` from the setters).
        """
        if frame is None:
            return None
        if isinstance(frame, GpuFrame):
            return self._update_gpu(frame)
        h, w = frame.shape[:2]
        if w != self._width or h != self._height:
            self._width = w
            self._height = h
        return _accepted(self._provider.set_data_array(frame, [w, h]))

    def _update_gpu(self, frame: GpuFrame) -> Optional[bool]:
        w, h = frame.width, frame.height
        if w != self._width or h != self._height:
            self._width = w
            self._height = h
        try:
            if self._state is not None and self._state.mode.value == "probing":
                # Capability first. Absence of a stderr marker is not proof
                # that the GPU push worked: a build without CUDA-Vulkan interop
                # silently produced no texture, which is how zero-copy came to
                # report `enabled` while the viewport stayed black. Ask the
                # backend directly, and fall back for real when it says no.
                if not _has_gpu_byte_image():
                    self._state.mark_fallback(
                        "ovui build has no CUDA-Vulkan byte-image support "
                        "(omni.ui.has_gpu_byte_image() is False)"
                    )
                    return _gpu_frame_not_taken()
                with _capture_fd2() as cap:
                    accepted = self._set_gpu_frame_data(frame, [w, h])
                captured = cap.read()
                if _STANDALONE_NOOP_MARKER in captured:
                    # Re-emit so users see the original warning once.
                    _write_fd2(captured)
                    self._state.mark_fallback(
                        "ovui standalone backend printed 'fromGpu not supported'"
                    )
                    return False
                if accepted is False:
                    # The return value is the truthful answer. The stderr
                    # marker is only a fallback for an ovui that returns None.
                    self._state.mark_fallback("ovui rejected the GPU upload")
                    return False
                self._state.mark_enabled()
                return accepted
            accepted = self._set_gpu_frame_data(frame, [w, h])
            if accepted is False and self._state is not None:
                # Safe choice: a rejected upload keeps the old frame on screen.
                # Switch to the CPU path so the next frames arrive.
                self._state.mark_fallback("ovui rejected the GPU upload")
            return accepted
        finally:
            # Always release the CUDA mapping the renderer entered for us,
            # even if ovui's GPU push raised. The pointer is invalidated
            # when the mapping context exits, so this MUST run after the
            # set_bytes_data_from_gpu call returns synchronously.
            frame.close()

    def _set_gpu_frame_data(self, frame: GpuFrame, size: list[int]) -> Optional[bool]:
        stride = getattr(frame, "stride", None)
        if stride is None:
            return _accepted(self._provider.set_bytes_data_from_gpu(frame.ptr, size))
        return _accepted(
            self._provider.set_bytes_data_from_gpu(
                frame.ptr,
                size,
                stride=int(stride),
            )
        )


def _gpu_frame_not_taken() -> Optional[bool]:
    """The answer for a GPU frame that ovui cannot take.

    ``False`` (refused) when ovui has a GPU backend. ``None`` when it has none:
    there is no renderer, and that is not a refusal. An older ovui cannot tell,
    and ``None`` was the answer there before.
    """
    has_backend = getattr(ui.ByteImageProvider, "has_upload_backend", None)
    return False if callable(has_backend) and has_backend() else None


def _accepted(result: object) -> Optional[bool]:
    """``True`` or ``False`` when ovui answered, ``None`` when it did not."""
    return result if isinstance(result, bool) else None


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

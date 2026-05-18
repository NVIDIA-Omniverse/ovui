# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""
Standalone run-loop for omni.ui outside of Kit.

Provides :func:`init`, :func:`shutdown`, :func:`run`, :func:`run_async`,
and :func:`next_frame` so that the standard ``await ui.next_frame()``
pattern works identically in standalone and Kit modes.

Frame timing
============

``await ui.next_frame()`` returns a :class:`FrameInfo` describing the tick
that just resolved the awaiter. Existing callers that ignore the return
value (``await ui.next_frame()``) keep working — only callers that bind
the result (``frame = await ui.next_frame()``) see the new metadata.

The run-loop also enforces a max-FPS cap. ``glfwSwapInterval(1)`` is
already set on real GPUs and gives a hardware vsync; on hosts where
``glfwSwapBuffers`` does not block (Mesa llvmpipe under kasmvnc / Xvnc),
the sleep cap in :func:`run` / :func:`run_async` keeps the loop from
free-running at 200+ FPS. Default cap is 60 FPS, configurable via
:func:`set_max_frame_rate` or ``ui.init(..., max_fps=...)``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Coroutine, Optional

from .. import _ui

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameInfo:
    """Metadata about a single standalone tick.

    Returned from :func:`next_frame`. Use ``frame.dt`` for tick-relative
    delta time, ``frame.time`` for the monotonic timestamp at this tick,
    and ``frame.index`` for the increasing tick index (0-based).

    Backward compatibility: callers that ``await ui.next_frame()`` without
    binding the return value keep working — the FrameInfo is simply
    discarded.
    """

    dt: float
    time: float
    index: int


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------
_initialized: bool = False
_next_frame_futures: list[asyncio.Future] = []
_frame_index: int = 0
_last_tick_time: Optional[float] = None
# Hard-cap on the standalone tick rate. ``None`` disables the cap; set via
# :func:`set_max_frame_rate` or ``ui.init(..., max_fps=...)``. Default 60.
_max_frame_rate: Optional[float] = 60.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init(
    title: str = "omni.ui",
    width: int = 1280,
    height: int = 720,
    *,
    max_fps: Optional[float] = 60.0,
) -> None:
    """Initialize the standalone GLFW/ImGui backend.

    ``max_fps`` caps the tick rate of the standalone run loop. ``None`` (or
    a non-positive value) disables the cap. Default is 60. The cap can be
    changed at any time via :func:`set_max_frame_rate`.

    Safe to call multiple times — subsequent calls are no-ops aside from
    the ``max_fps`` update.
    """
    global _initialized
    set_max_frame_rate(max_fps)
    if _initialized:
        return
    _ui._standalone_init(title, width, height)
    _initialized = True
    # Register atexit handler so that the backend is torn down before
    # Python destroys module globals.  Without this, process exit
    # destroys C++ objects (Window, ImGui context, GLFW) in arbitrary
    # order, causing segfaults.
    import atexit
    atexit.register(shutdown)


def shutdown() -> None:
    """Tear down the standalone backend."""
    global _initialized, _frame_index, _last_tick_time, _next_frame_futures
    if not _initialized:
        return
    _ui._standalone_shutdown()
    _initialized = False
    _frame_index = 0
    _last_tick_time = None
    # Drop any pending future references; callers awaiting them got cancelled
    # along with the surrounding event loop in normal shutdown paths.
    _next_frame_futures = []


def set_max_frame_rate(fps: Optional[float]) -> None:
    """Cap the standalone tick rate to ``fps`` frames per second.

    Pass ``None`` (or a non-positive value) to remove the cap. The cap is
    enforced inside :func:`run` and :func:`run_async` by sleeping after
    each tick when the next tick would arrive sooner than ``1/fps``.
    """
    global _max_frame_rate
    if fps is None:
        _max_frame_rate = None
        return
    fps = float(fps)
    _max_frame_rate = fps if fps > 0.0 else None


def get_max_frame_rate() -> Optional[float]:
    """Return the current max-FPS cap (or ``None`` if uncapped)."""
    return _max_frame_rate


def set_window_size(width: int, height: int) -> bool:
    """Resize the main OS window (and its default OpenGL framebuffer).

    Returns True if the backend reports the new framebuffer size matches the
    requested dimensions after the next event-poll, False otherwise (e.g.
    when running without a window system, or when the window manager clamps
    the size).
    """
    if not _initialized:
        return False
    return bool(_ui._standalone_set_window_size(width, height))


def get_window_size() -> tuple[int, int]:
    """Return ``(width, height)`` of the main OS window framebuffer."""
    if not _initialized:
        return (0, 0)
    return tuple(_ui._standalone_get_window_size())


def set_software_cursor(enabled: bool) -> None:
    """Toggle ImGui's software-rendered mouse cursor (``io.MouseDrawCursor``).

    Headless mode enables this by default so injected mouse positions
    appear in captured/streamed frames (there is no OS cursor to fall
    back on). The setter is idempotent — repeated calls with the same
    value leave the IO flag in the same state.

    Has no effect when no ImGui context exists yet (i.e. before
    :func:`init`).
    """
    _ui._set_software_cursor(bool(enabled))


def is_software_cursor_enabled() -> bool:
    """Return ``True`` when ImGui is currently rendering a software cursor.

    Returns ``False`` when no ImGui context exists yet.
    """
    return bool(_ui._is_software_cursor_enabled())


def _ensure_initialized() -> None:
    """Auto-initialize with defaults if the caller forgot to call init()."""
    if not _initialized:
        init()


def _tick_one_frame() -> FrameInfo:
    """Drive one frame: poll events, draw, present, resolve futures.

    Returns a :class:`FrameInfo` describing the tick that just completed.
    The first tick after :func:`init` (or :func:`shutdown` + :func:`init`)
    reports ``dt = 0.0`` because there is no previous tick to measure
    against — callers that derive FPS from ``dt`` should ignore that
    sentinel value.
    """
    global _frame_index, _last_tick_time, _next_frame_futures

    _ui._standalone_tick()

    now = time.monotonic()
    if _last_tick_time is None:
        dt = 0.0
    else:
        dt = max(0.0, now - _last_tick_time)
    _last_tick_time = now
    info = FrameInfo(dt=dt, time=now, index=_frame_index)
    _frame_index += 1

    # Resolve all next_frame() futures so awaiters can proceed.
    pending = _next_frame_futures
    _next_frame_futures = []
    for fut in pending:
        if not fut.done():
            fut.set_result(info)

    return info


def _max_fps_target_period() -> float:
    """Return ``1 / max_fps`` seconds, or ``0.0`` when the cap is disabled."""
    fps = _max_frame_rate
    if fps is None or fps <= 0.0:
        return 0.0
    return 1.0 / fps


def _max_fps_remaining_since(frame_start: float) -> float:
    """Return seconds left in the budget for the iteration that began at ``frame_start``.

    The caller must capture ``frame_start = time.monotonic()`` *before*
    invoking :func:`_tick_one_frame`, so the budget covers the tick itself
    (poll events / draw / swap) plus any post-tick asyncio pumping. This
    matters on hosts where ``glfwSwapBuffers`` blocks on hardware vsync —
    if we measured remaining only after the tick (against the post-tick
    timestamp on :class:`FrameInfo`), we'd add another ``1 / max_fps``
    sleep on top of the ~16.7 ms the swap already consumed, halving the
    effective frame rate.

    On free-running software hosts (Mesa llvmpipe under Xvnc / kasmvnc)
    the tick is fast and most of the budget remains; the run loops sleep
    that remainder so the loop doesn't free-run at 200+ FPS.

    Returns 0.0 when the cap is disabled or the iteration has already
    consumed its budget.
    """
    period = _max_fps_target_period()
    if period <= 0.0:
        return 0.0
    elapsed = max(0.0, time.monotonic() - frame_start)
    return max(0.0, period - elapsed)


def _pump_asyncio(loop: asyncio.AbstractEventLoop) -> None:
    """Run all ready callbacks in *loop* without blocking."""
    # Process all ready callbacks (resolved futures, scheduled tasks).
    loop._run_once()  # type: ignore[attr-defined]
    # _run_once may not exist on all loop implementations.  Fallback:
    # loop.run_until_complete(asyncio.sleep(0)) -- but that is heavier.


async def next_frame() -> FrameInfo:
    """Await exactly one frame, analogous to Kit's ``next_update_async``.

    Returns a :class:`FrameInfo` describing the tick that resolved the
    awaiter. Callers that don't care about the timing metadata can keep
    using the bare ``await ui.next_frame()`` form — the return value is
    simply discarded.
    """
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    _next_frame_futures.append(fut)
    return await fut


def run(coro: Optional[Coroutine] = None) -> None:
    """Enter the standalone blocking event loop.

    If *coro* is provided it is scheduled as a task.  The loop exits when
    either the GLFW window is closed or the coroutine finishes.

    This does **not** call :func:`asyncio.run`; it creates an event loop
    and pumps it manually each frame -- matching Kit's own run-loop model.

    The loop honours the max-FPS cap (see :func:`set_max_frame_rate`)
    by sleeping between ticks when the cap is set and the host's vsync
    isn't enforcing it (e.g. Mesa software OpenGL under Xvnc).
    """
    _ensure_initialized()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    task = None
    if coro is not None:
        task = loop.create_task(coro)

    try:
        while not _ui._standalone_should_close():
            # Capture frame_start BEFORE the tick so the budget covers the
            # tick itself plus the asyncio pump. See _max_fps_remaining_since
            # for why this matters on hardware-vsync hosts.
            frame_start = time.monotonic()
            _tick_one_frame()
            # Pump asyncio: run all ready callbacks.
            loop.call_soon(loop.stop)
            loop.run_forever()
            if task is not None and task.done():
                break
            cap = _max_fps_remaining_since(frame_start)
            if cap > 0.0:
                time.sleep(cap)
    finally:
        loop.close()
        asyncio.set_event_loop(None)
        shutdown()


async def run_async() -> None:
    """Cooperative entry point for embedding in an existing asyncio loop.

    Yields to the asyncio scheduler each frame so that other tasks
    (including the caller) can make progress. Honours the max-FPS cap
    via ``await asyncio.sleep`` between ticks.
    """
    _ensure_initialized()
    while not _ui._standalone_should_close():
        frame_start = time.monotonic()
        _tick_one_frame()
        cap = _max_fps_remaining_since(frame_start)
        if cap > 0.0:
            await asyncio.sleep(cap)
        else:
            await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Streaming API (FBO rendering + CUDA-GL interop for zero-copy to NVENC)
# ---------------------------------------------------------------------------

_streaming_initialized: bool = False


def init_streaming(width: int = 1920, height: int = 1080) -> None:
    """Initialize the streaming backend.

    Creates a hidden GLFW window (for the GL context), an FBO-backed virtual
    window at the given resolution, and optionally sets up CUDA-GL interop
    for zero-copy GPU access (required for NVENC encoding).

    Safe to call once; raises on failure or double-init.
    """
    global _streaming_initialized
    if _streaming_initialized:
        raise RuntimeError("streaming already initialized")
    if not _ui._init_streaming(width, height):
        raise RuntimeError(f"_init_streaming({width}, {height}) failed")
    _streaming_initialized = True

    import atexit
    atexit.register(shutdown_streaming)


def shutdown_streaming() -> None:
    """Tear down the streaming backend and release all resources."""
    global _streaming_initialized
    if not _streaming_initialized:
        return
    _ui._shutdown_streaming()
    _streaming_initialized = False


def streaming_tick() -> bool:
    """Render one frame to the streaming FBO.

    Returns False if the application should exit.
    Raises if streaming is not initialized.
    """
    if not _streaming_initialized:
        raise RuntimeError("streaming not initialized — call init_streaming() first")
    return _ui._streaming_tick()


def get_streaming_gl_texture() -> int:
    """Return the GL texture ID of the streaming framebuffer."""
    if not _streaming_initialized:
        return 0
    return _ui._get_streaming_gl_texture()


def get_streaming_size() -> tuple[int, int]:
    """Return (width, height) of the streaming framebuffer."""
    if not _streaming_initialized:
        return (0, 0)
    return (_ui._get_streaming_width(), _ui._get_streaming_height())


def get_streaming_cuda_ptr() -> int:
    """Return the CUDA device pointer to the linear RGBA8 frame buffer.

    Returns 0 if CUDA interop is unavailable.

    The pointer is stable across frames (same allocation, contents updated each
    ``streaming_tick()``). Call ``streaming_sync()`` before reading the buffer
    from another thread. The pointer is invalidated by ``resize_streaming()``
    or ``shutdown_streaming()``.
    """
    if not _streaming_initialized:
        return 0
    return _ui._get_streaming_cuda_ptr()


def get_streaming_cuda_pitch() -> int:
    """Return the pitch (bytes per row) of the linear CUDA buffer."""
    if not _streaming_initialized:
        return 0
    return _ui._get_streaming_cuda_pitch()


def get_streaming_cuda_buffer() -> tuple[int, int]:
    """Return ``(cuda_ptr, pitch)`` for the linear RGBA8 frame buffer.

    Convenience function that returns both values atomically, avoiding a
    TOCTOU window where the buffer could be resized between separate calls
    to ``get_streaming_cuda_ptr()`` and ``get_streaming_cuda_pitch()``.

    Returns ``(0, 0)`` if CUDA interop is unavailable.
    """
    if not _streaming_initialized:
        return (0, 0)
    return (_ui._get_streaming_cuda_ptr(), _ui._get_streaming_cuda_pitch())


def get_streaming_format() -> str:
    """Return the pixel format of the streaming buffer (e.g. ``'rgba8'``)."""
    return _ui._get_streaming_format()


def is_streaming_cuda_available() -> bool:
    """Return True if CUDA interop is active.

    Separate from ``init_streaming()`` return value — streaming can succeed
    without CUDA (degraded mode, GL texture only).
    """
    return _ui._is_streaming_cuda_available()


def streaming_sync() -> None:
    """Wait for the most recent frame's CUDA copy to complete.

    Call this before reading from the CUDA linear buffer on another thread.
    No-op if CUDA is not active.
    """
    _ui._streaming_sync()


def get_streaming_cuda_event() -> int:
    """Return a CUDA event (``cudaEvent_t`` as ``int``) recorded after each frame copy.

    Callers who want asynchronous synchronization can pass this to
    ``cudaStreamWaitEvent()`` instead of calling ``streaming_sync()``.
    Returns 0 if CUDA is not active.
    """
    return _ui._get_streaming_cuda_event()


def resize_streaming(width: int, height: int) -> None:
    """Resize the streaming framebuffer.

    Recreates the FBO and CUDA resources at the new resolution.

    **WARNING:** Must not be called while another thread is reading from the
    CUDA buffer. Ensure all NVENC reads have completed first.
    """
    if not _streaming_initialized:
        raise RuntimeError("streaming not initialized")
    if not _ui._resize_streaming(width, height):
        raise RuntimeError(f"resize_streaming({width}, {height}) failed")

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
import logging
import threading
import time
from dataclasses import dataclass
from typing import Coroutine, Optional

from .. import _ui

_log = logging.getLogger(__name__)

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
# Wakes an in-flight pacing wait in :func:`run` (blocking) so a live
# :func:`set_max_frame_rate` change or :func:`request_wakeup` takes effect
# immediately instead of after the old period elapses.
_wakeup_event = threading.Event()
# The asyncio counterpart for :func:`run_async`. Created lazily against the
# running loop (asyncio.Event binds to one loop); ``request_wakeup`` sets it
# via ``call_soon_threadsafe`` so cross-thread wakeups are safe too.
_async_wakeup_event: Optional[asyncio.Event] = None
_async_wakeup_loop: Optional[asyncio.AbstractEventLoop] = None
# True when the wake came from :func:`request_wakeup` (host wants the loop
# to observe state now — e.g. an exit request): the pacing wait ends early.
# A plain rate change only recomputes the remaining budget instead.
_wakeup_break: bool = False
# True while :func:`run` / :func:`run_async` is executing. Wake state is
# scoped to the active run: :func:`request_wakeup` with no active run is a
# true no-op, and both loops reset wake state on entry and exit so a
# consumed-too-late wakeup can never leak into a later iteration or a later
# init/run cycle.
_run_active: bool = False
# Guards admission to / release of the single run slot and the associated
# wake state, so simultaneous cross-thread run()/run_async() calls admit
# exactly one runner (a bare check-then-set under the GIL is not atomic
# across the statements in between).
_lifecycle_lock = threading.Lock()
# Mutually orders native backend calls: init, per-frame tick, and teardown.
# The tick re-checks ``_initialized`` inside the lock, so a runner that
# passed the loop guard before a concurrent shutdown() completed can no
# longer reach the native tick afterwards.
_native_lock = threading.Lock()
# Ident of the thread currently executing the native tick (only ever set
# while ``_native_lock`` is held). :func:`shutdown` compares against it to
# detect re-entry from a native callback dispatched by the tick itself —
# blocking on the native lock there would self-deadlock, so teardown is
# deferred until the in-flight tick returns.
_tick_thread_ident: Optional[int] = None
# Set by a re-entrant shutdown() (from a native tick callback). The tick
# performs the deferred teardown immediately after the native call returns,
# still under the native lock, so teardown never lands mid-native-work and
# no later tick can run.
_shutdown_requested_in_tick: bool = False
# Set (under _lifecycle_lock) when shutdown() targets an admitted run —
# including one that has not called _ensure_initialized yet. The run must
# terminate: it may not auto-reinitialize the backend and continue. Cleared
# atomically at admission.
_stop_requested: bool = False


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
    global _initialized, _shutdown_requested_in_tick
    set_max_frame_rate(max_fps)
    with _native_lock:
        if _initialized:
            return
        _shutdown_requested_in_tick = False
        _ui._standalone_init(title, width, height)
        _initialized = True
    # Register atexit handler so that the backend is torn down before
    # Python destroys module globals.  Without this, process exit
    # destroys C++ objects (Window, ImGui context, GLFW) in arbitrary
    # order, causing segfaults.
    import atexit
    atexit.register(shutdown)


def shutdown() -> None:
    """Tear down the standalone backend.

    Safe to call while a run loop is active: ``_initialized`` flips first
    (both loops check it before every tick and every pacing pass), then the
    in-flight pacing wait is *signalled* — never cleared or replaced, the
    waiter still holds its captured event — so a low-FPS wait releases
    promptly instead of running out its old period. The terminating runner
    resets the wake state itself on exit; shutdown only resets it directly
    when no run is active, so it cannot orphan an active waiter.

    Re-entrancy: when called from a native callback dispatched inside the
    in-flight tick (same thread), teardown is *deferred* — the tick
    finishes its native work, then tears down under the same native-lock
    hold before any further backend call. Blocking on the native lock here
    would self-deadlock.

    Targeting an admitted run: the run is marked stopped even when the
    backend is not (yet) initialized, so a runner caught between admission
    and ``_ensure_initialized`` cannot silently re-initialize and continue.
    """
    global _shutdown_requested_in_tick, _stop_requested
    if threading.get_ident() == _tick_thread_ident:
        _shutdown_requested_in_tick = True
        return
    # Stop intent is recorded BEFORE teardown takes the native lock. A
    # runner initializing for its run checks this under the native lock
    # (_ensure_initialized_for_run), so either it observes the stop and
    # skips init, or its init serializes before our teardown — teardown is
    # always the last word; a stopped run can never re-initialize after it.
    with _lifecycle_lock:
        if _run_active:
            _stop_requested = True
    # The native lock orders teardown against the per-frame tick: a runner
    # that passed its loop guard before this point blocks at the tick's
    # lock, re-checks ``_initialized`` inside it, and skips — no backend
    # tick can begin once teardown has started.
    #
    # Exception policy: ``_initialized`` flips before the native call, and
    # finalization (stop intent, wake delivery, counters) runs in the
    # finally — so a native teardown failure still leaves coherent
    # Python-side lifecycle state and promptly releases any active waiter.
    # The teardown exception then propagates to shutdown()'s caller (it is
    # the caller's operation), never silently lost.
    try:
        with _native_lock:
            if _initialized:
                _shutdown_native_locked()
    finally:
        _finalize_shutdown_state()


def _shutdown_native_locked() -> None:
    """Flip ``_initialized`` and tear down the backend (native lock held)."""
    global _initialized
    _initialized = False
    _ui._standalone_shutdown()


def _finalize_shutdown_state() -> None:
    """Post-teardown lifecycle bookkeeping (no locks held on entry).

    Always runs — even when the backend was not initialized — so a
    shutdown that targets an admitted-but-not-yet-initialized run still
    stops that run instead of being reversed by auto-reinitialization.
    """
    global _stop_requested, _frame_index, _last_tick_time
    global _next_frame_futures
    with _lifecycle_lock:
        if _run_active:
            _stop_requested = True
            _signal_pacing_wakeup()
        else:
            # A wakeup that was requested but never consumed must not leak
            # into the next init/run cycle.
            _reset_pacing_wake_state()
    _frame_index = 0
    _last_tick_time = None
    # Drop any pending future references; callers awaiting them got cancelled
    # along with the surrounding event loop in normal shutdown paths.
    _next_frame_futures = []


def set_max_frame_rate(fps: Optional[float]) -> None:
    """Cap the standalone tick rate to ``fps`` frames per second.

    Pass ``None`` (or a non-positive value) to remove the cap. The cap is
    enforced inside :func:`run` and :func:`run_async` by sleeping after
    each tick when the next tick would arrive sooner than ``1/fps``. A
    change made while a pacing wait is in flight wakes that wait, which
    recomputes the remaining budget against the new rate — in both
    directions — rather than finishing out the old period.
    """
    global _max_frame_rate
    if fps is None:
        _max_frame_rate = None
    else:
        fps = float(fps)
        _max_frame_rate = fps if fps > 0.0 else None
    _signal_pacing_wakeup()


def request_wakeup() -> None:
    """Wake any in-flight pacing wait in :func:`run` / :func:`run_async`
    and end it early.

    Used by hosts to keep exit requests (or any state change the loop
    should observe) from being stranded behind a low-FPS pacing sleep.
    Safe to call from any thread. A true no-op when no run loop is active:
    the wakeup is dropped, not queued, so it cannot make a later iteration
    or a later run start uncapped.
    """
    global _wakeup_break
    with _lifecycle_lock:
        if not _run_active:
            return
        _wakeup_break = True
    _signal_pacing_wakeup()


def _reset_pacing_wake_state() -> None:
    """Drop all pending wake state (run entry/exit and shutdown)."""
    global _wakeup_break, _async_wakeup_event, _async_wakeup_loop
    _wakeup_break = False
    _wakeup_event.clear()
    _async_wakeup_event = None
    _async_wakeup_loop = None


def _signal_pacing_wakeup() -> None:
    """Wake a pending pacing wait so it re-evaluates its budget."""
    _wakeup_event.set()
    ev, loop = _async_wakeup_event, _async_wakeup_loop
    if ev is not None and loop is not None and not loop.is_closed():
        try:
            loop.call_soon_threadsafe(ev.set)
        except RuntimeError:
            pass  # loop shut down between the check and the call


def _consume_wakeup_break() -> bool:
    """Return True (once) when the last wakeup asked to end the wait."""
    global _wakeup_break
    with _lifecycle_lock:
        if _wakeup_break:
            _wakeup_break = False
            return True
        return False


def _acquire_run_slot() -> None:
    """Atomically admit exactly one runner, or raise without side effects.

    The check and the set happen under ``_lifecycle_lock``, so genuinely
    simultaneous cross-thread ``run()``/``run_async()`` calls admit exactly
    one; the loser raises before any shared wake/lifecycle state has been
    touched and therefore cannot disturb the winner.
    """
    global _run_active, _stop_requested
    with _lifecycle_lock:
        if _run_active:
            raise RuntimeError(
                "a standalone run loop is already active; only one "
                "run()/run_async() may execute at a time"
            )
        _run_active = True
        # Any stop intent belonged to a previous run; this admission starts
        # clean. (A shutdown that lands after this point sets it again and
        # targets THIS run.)
        _stop_requested = False


def _release_run_slot() -> None:
    """Release pump ownership and reset wake state (owner's exit path).

    Must be the owner's LAST lifecycle action: everything that can affect
    shared native/lifecycle state (event-loop close, shutdown) happens
    before this, so a successor admitted afterwards can never be affected
    by the predecessor's cleanup.
    """
    global _run_active, _stop_requested
    with _lifecycle_lock:
        _run_active = False
        _stop_requested = False
        _reset_pacing_wake_state()


def _get_async_wakeup_event() -> asyncio.Event:
    """Return the wakeup event bound to the currently running loop."""
    global _async_wakeup_event, _async_wakeup_loop
    loop = asyncio.get_running_loop()
    if _async_wakeup_event is None or _async_wakeup_loop is not loop:
        _async_wakeup_event = asyncio.Event()
        _async_wakeup_loop = loop
    return _async_wakeup_event


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


def _ensure_initialized_for_run() -> bool:
    """Auto-initialize for a freshly admitted run, unless it was stopped.

    Returns False (without initializing) when :func:`shutdown` has already
    targeted this run. The stop check and the native init are performed
    under the native lock, ordered against shutdown()'s teardown: either
    the stop intent — which shutdown records *before* it takes the native
    lock — is observed here and init is skipped, or this init serializes
    ahead of the pending teardown and the teardown wins afterwards. A
    stopped run can never silently re-initialize a torn-down backend.
    """
    global _initialized, _shutdown_requested_in_tick
    initialized_now = False
    with _native_lock:
        if _stop_requested:
            return False
        if not _initialized:
            # Mirrors init()'s auto-init defaults (title/size/60 FPS cap).
            set_max_frame_rate(60.0)
            _shutdown_requested_in_tick = False
            _ui._standalone_init("omni.ui", 1280, 720)
            _initialized = True
            initialized_now = True
    if initialized_now:
        import atexit
        atexit.register(shutdown)
    return True


def _tick_one_frame() -> FrameInfo:
    """Drive one frame: poll events, draw, present, resolve futures.

    Returns a :class:`FrameInfo` describing the tick that just completed.
    The first tick after :func:`init` (or :func:`shutdown` + :func:`init`)
    reports ``dt = 0.0`` because there is no previous tick to measure
    against — callers that derive FPS from ``dt`` should ignore that
    sentinel value.

    Returns ``None`` without touching the backend when teardown has
    already started — the ``_initialized`` re-check happens inside the
    native lock, closing the guard-to-tick race with :func:`shutdown`.
    """
    global _frame_index, _last_tick_time, _next_frame_futures
    global _tick_thread_ident, _shutdown_requested_in_tick

    deferred_teardown = False
    try:
        with _native_lock:
            if not _initialized:
                # Teardown started (or completed) after this runner passed
                # its loop guard: the backend must not be ticked again. The
                # loop observes ``_initialized`` on its next guard and
                # exits.
                return None
            _tick_thread_ident = threading.get_ident()
            try:
                _ui._standalone_tick()
            finally:
                # Deferred-shutdown processing lives in the tick's finally:
                # a callback-requested shutdown stays authoritative even
                # when the native tick exits exceptionally. The teardown
                # runs after the native work unwound, still under the
                # native lock. A teardown failure here is logged rather
                # than raised — raising from a finally would mask the
                # tick's own (more relevant) in-flight exception, and the
                # requester's shutdown() call has already returned, so no
                # caller frame exists to receive it.
                _tick_thread_ident = None
                if _shutdown_requested_in_tick:
                    _shutdown_requested_in_tick = False
                    deferred_teardown = True
                    try:
                        _shutdown_native_locked()
                    except Exception:
                        _log.exception(
                            "native teardown failed during deferred "
                            "(callback-requested) shutdown; Python-side "
                            "lifecycle state is finalized regardless"
                        )
    finally:
        # Finalization (stop intent, wake delivery, counters) happens on
        # both the normal and the exceptional exit path, before the tick
        # exception can propagate to the runner and release ownership.
        if deferred_teardown:
            _finalize_shutdown_state()
    if deferred_teardown:
        return None

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

    Only one standalone run loop (``run`` or ``run_async``) may be active
    at a time; an overlapping invocation raises :class:`RuntimeError`
    without disturbing the active loop. :func:`shutdown` during an active
    run releases any in-flight pacing wait promptly and the loop exits.
    """
    _acquire_run_slot()  # atomic; raises without side effects when taken
    loop = None
    try:
        if not _ensure_initialized_for_run():
            # shutdown() targeted this admitted run before it initialized:
            # do not auto-reinitialize the backend and continue.
            return
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        task = None
        if coro is not None:
            task = loop.create_task(coro)

        _reset_pacing_wake_state()
        while _initialized and not _stop_requested and not _ui._standalone_should_close():
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
            # Interruptible per-iteration pacing: a rate-change wake
            # recomputes the remaining budget against the CURRENT rate —
            # never against a stored schedule, so no later iteration runs
            # shorter than the configured period to catch up. A
            # request_wakeup ends the wait so exit state is observed. The
            # break flag is checked BEFORE waiting (and the event is only
            # cleared after a wake), so a wakeup that landed during the
            # tick/pump phase is honored instead of being swallowed.
            # ``_initialized`` is checked first: an active shutdown() flips
            # it and signals, releasing this wait promptly.
            while _initialized and not _stop_requested and not _ui._standalone_should_close():
                if _consume_wakeup_break():
                    break
                cap = _max_fps_remaining_since(frame_start)
                if cap <= 0.0:
                    break
                if not _wakeup_event.wait(cap):
                    break  # budget elapsed
                _wakeup_event.clear()
    finally:
        # Only the admitted owner reaches this frame: a rejected call raised
        # inside _acquire_run_slot and cannot release the winner's slot.
        # Ownership is retained through EVERY cleanup action that can touch
        # shared native/lifecycle state (loop close, shutdown); the slot is
        # released last, so a successor admitted afterwards can never have
        # its backend torn down by this predecessor.
        try:
            if loop is not None:
                loop.close()
                asyncio.set_event_loop(None)
            shutdown()
        finally:
            _release_run_slot()


async def run_async() -> None:
    """Cooperative entry point for embedding in an existing asyncio loop.

    Yields to the asyncio scheduler each frame so that other tasks
    (including the caller) can make progress. Honours the max-FPS cap
    via an interruptible wait between ticks.

    Only one standalone run loop (``run`` or ``run_async``) may be active
    at a time; an overlapping invocation raises :class:`RuntimeError`
    without disturbing the active loop. :func:`shutdown` during an active
    run releases any in-flight pacing wait promptly and the loop exits.
    """
    _acquire_run_slot()  # atomic; raises without side effects when taken
    try:
        if not _ensure_initialized_for_run():
            # shutdown() targeted this admitted run before it initialized:
            # do not auto-reinitialize the backend and continue.
            return
        _reset_pacing_wake_state()
        await _run_async_loop()
    finally:
        # Only the admitted owner reaches this frame: a rejected call raised
        # inside _acquire_run_slot and cannot release the winner's slot.
        # run_async owns no event loop and performs no teardown; releasing
        # the slot (which atomically resets wake state) is its final —
        # and only — shared-state cleanup.
        _release_run_slot()


async def _run_async_loop() -> None:
    while _initialized and not _stop_requested and not _ui._standalone_should_close():
        frame_start = time.monotonic()
        _tick_one_frame()
        # Same interruptible per-iteration pacing as :func:`run`: rate
        # changes recompute the remaining budget (both directions, no
        # catch-up); request_wakeup ends the wait early, and is honored
        # even when it landed before the wait started. ``_initialized``
        # first: an active shutdown() flips it and signals this wait.
        event = _get_async_wakeup_event()
        paced = False
        while _initialized and not _stop_requested and not _ui._standalone_should_close():
            if _consume_wakeup_break():
                break
            cap = _max_fps_remaining_since(frame_start)
            if cap <= 0.0:
                break
            paced = True
            try:
                await asyncio.wait_for(event.wait(), timeout=cap)
            except asyncio.TimeoutError:
                break  # budget elapsed
            event.clear()
        if not paced:
            await asyncio.sleep(0)  # uncapped: still yield to other tasks


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

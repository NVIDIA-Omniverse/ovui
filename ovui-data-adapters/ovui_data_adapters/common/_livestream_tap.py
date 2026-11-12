# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Provider-neutral ovstream tap for OVRTX or composed ovui frames.

Activated by ``OVGEAR_LIVESTREAM=1``. When inactive (the default),
``maybe_create()`` returns ``None`` before importing ovstream or
touching CUDA.

Design (strata#17):
* ovrtx maps ``LdrColor`` to CUDA via ``rv.map(device=Device.CUDA)``.
* The CUDA pointer is D2D-copied into one of N persistent scratch
  buffers (a small ring, see "Buffer lifetime" below); the scratch
  pointer is then handed to ``ovstream.Server.stream_video`` as a
  ``VideoFrame``. The GPU buffer is consumed by NVENC. No host bounce.
* On the livestream-only path, the same CUDA buffer is then D2H-copied
  into a host numpy array so the existing OvGear viewport UI consumer
  keeps working. ovrtx forbids a second ``map()`` per frame
  (``RuntimeError`` on the second call), so the one CUDA map must
  serve both consumers.
* On the composed (``OVGEAR_ZERO_COPY=1`` AND ``OVGEAR_LIVESTREAM=1``)
  path, the adapter calls :meth:`tee_to_ovstream` only and returns a
  ``GpuFrame`` from the still-mapped tensor — no D2H, the GPU UI
  ingest reads the same CUDA pointer.
* Format note: OVRTX LdrColor is RGBA8 and ovstream expects BGRA8. The
  provider-neutral CUDA swap kernel exchanges R/B in the scratch buffer
  before NVENC consumes it; the fix can be disabled for diagnostics.

Buffer lifetime
---------------
ovstream's ``stream_video`` returns BEFORE NVENC has finished reading the
buffer (kit-livestream ``sdk/src/rtsp/server.cpp`` wraps the CUDA
pointer in a ``GstBuffer`` and pushes it to an asynchronous encoder
pipeline; ``sdk/src/webrtc/server.cpp`` likewise hands the pointer to
``nvstPushStreamData`` and returns immediately). Reusing a single
buffer across frames is the documented upstream pattern (see
``sdk/examples/python/ovrtx_stream.py:288-291``), but predicated on
the encoder thread picking up fast.

To structurally protect against frame N+1's D2D stomping NVENC's
read of frame N, we use a ring of scratch buffers. The default is
eight slots, configurable through ``OVGEAR_LIVESTREAM_BUFFER_RING``.
The larger default is a defensive margin: current validation has not
deterministically reproduced the historical browser speckle, but the
async SDK handoff means WebRTC/NVENC backpressure can leave previous
zero-copy CUDA surfaces in flight after ``stream_video`` returns. On
resize and shutdown we issue ``cudaDeviceSynchronize`` before freeing
the ring so the encoder thread has a chance to drain (``Server.stop()``
is meant to drain on its own; the explicit synchronize is defensive).

The D2D itself uses ``cudaMemcpy`` on the default stream, which is
synchronous w.r.t. the host — i.e. when ``cudart.d2d()`` returns,
the scratch is filled and visible to NVENC.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
import threading
import time
from typing import Any, Optional, Tuple

import numpy as np
from ovui_data_adapters.common import _swap_kernel

# Connection-state strings exposed by ``LivestreamTap.status()`` and
# consumed by the viewport overlay widget (Step 1.7). Stable strings
# so the widget can render them verbatim without a separate enum import.
_STATE_OFF       = "OFF"        # tap exists but has no server up yet
_STATE_LISTENING = "LISTENING"  # server up, zero clients connected
_STATE_STREAMING = "STREAMING"  # at least one client attached
_STATE_ERROR     = "ERROR"      # permanent failure; tap disabled


_ENABLED_ENV_VAR = "OVGEAR_LIVESTREAM"
_PROTOCOL_ENV_VAR = "OVGEAR_LIVESTREAM_PROTOCOL"
_SIGNAL_PORT_ENV_VAR = "OVGEAR_LIVESTREAM_SIGNAL_PORT"
_MEDIA_PORT_ENV_VAR = "OVGEAR_LIVESTREAM_MEDIA_PORT"
_LEGACY_PORT_ENV_VAR = "OVGEAR_LIVESTREAM_PORT"
_PUBLIC_IP_ENV_VAR = "OVGEAR_LIVESTREAM_PUBLIC_IP"
_FORMAT_FIX_ENV_VAR = "OVGEAR_LIVESTREAM_FORMAT_FIX"
_BUFFER_RING_ENV_VAR = "OVGEAR_LIVESTREAM_BUFFER_RING"

# WebRTC is the Kit-standard protocol for browser-driven streaming and the
# only one that carries the back-channel input + custom-message envelope
# tier-3 needs. RTSP and Native are still supported via the env var, but
# the demo target (web-viewer-sample) speaks WebRTC.
_DEFAULT_PROTOCOL = "webrtc"

# Kit App Template's `web-viewer-sample` connects to signaling port
# 49100 by default (`stream.config.json:19`). Media port 47999 is the
# ovstream SDK's WebRTC default when ``stream_port`` is left at zero
# (`ovstream/_types.py:153`). We pin both as ovgear's defaults so a
# fresh checkout is browser-compatible without any env-var tuning.
_DEFAULT_SIGNAL_PORT = 49100
_DEFAULT_MEDIA_PORT = 47999

# StreamSDK accepts zero-copy CUDA pointers and may keep reading them
# after ``stream_video`` returns. Each RGBA8 ring costs
# width*height*4*depth bytes: depth 8 is ~63 MiB per active 1080p ring
# or ~253 MiB per active 4K ring, and both normal + pitched-linear rings
# can be live. The depth-64 cap is for diagnosis/stress only (~506 MiB
# per 1080p ring, ~2.0 GiB per 4K ring). Default 8 is a defensive
# cushion for several 30 fps encoder/WebRTC frame intervals; the env var
# keeps that tradeoff adjustable on tighter GPUs.
_MIN_RING_LEN = 2
_DEFAULT_RING_LEN = 12  # the async publisher keeps up to 8 in flight plus the slot being re-sent
_MAX_RING_LEN = 64


def _validate_rgba8_mapping_tensor(
    mapping_tensor: Any,
    width: int,
    height: int,
) -> tuple[int, ...]:
    """Validate an OVRTX ``LdrColor`` CUDA mapping and return its shape.

    OVRTX has exposed RGBA8 image tensors in two ABI-compatible DLPack
    layouts across runtime cohorts:

    * legacy: ``shape == (H, W)`` with ``dtype.lanes == 4``;
    * current: ``shape == (H, W, 4)`` with ``dtype.lanes == 1``.

    Lightweight test doubles historically omit ``dtype``. Keep accepting
    those when their shape is one of the supported forms, while validating
    lane width and scalar bit width whenever the runtime supplies them.
    """
    try:
        shape = tuple(int(value) for value in mapping_tensor.shape)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("OVRTX LdrColor mapping has no valid shape") from exc

    dtype = getattr(mapping_tensor, "dtype", None)
    lanes = getattr(dtype, "lanes", None)
    bits = getattr(dtype, "bits", None)
    if lanes is not None:
        lanes = int(lanes)
    if bits is not None:
        bits = int(bits)

    legacy_shape = (int(height), int(width))
    current_shape = (int(height), int(width), 4)
    if shape == legacy_shape:
        if lanes not in (None, 4):
            raise ValueError(
                "Legacy OVRTX LdrColor mapping must use four dtype lanes; "
                f"got shape={shape}, lanes={lanes}"
            )
    elif shape == current_shape:
        if lanes not in (None, 1):
            raise ValueError(
                "Channel-last OVRTX LdrColor mapping must use scalar dtype lanes; "
                f"got shape={shape}, lanes={lanes}"
            )
    else:
        raise ValueError(
            "Unexpected OVRTX LdrColor shape "
            f"{shape} for {int(width)}x{int(height)}; expected "
            f"{legacy_shape} with four dtype lanes or {current_shape}"
        )

    if bits not in (None, 8):
        raise ValueError(
            f"OVRTX LdrColor mapping must use 8-bit channels; got bits={bits}"
        )
    return shape


def _tensor_cuda_device(mapping_tensor: Any) -> Optional[int]:
    """Return the CUDA device ordinal of a DLPack tensor, when it reports one."""
    try:
        device_type, device_id = mapping_tensor.__dlpack_device__()
    except Exception:
        return None
    return int(device_id) if int(device_type) == 2 else None  # kDLCUDA


def _encoder_width(width: int) -> int:
    """NVENC encodes an 8-pixel-aligned width; the rightmost columns are dropped.

    The source row pitch is unchanged, so a frame of any width can be streamed.
    """
    return width - width % 8 if width >= 8 else width


def _enabled() -> bool:
    return os.environ.get(_ENABLED_ENV_VAR, "").strip().lower() in ("1", "true", "yes")


def _format_fix_enabled() -> bool:
    """Resolve ``OVGEAR_LIVESTREAM_FORMAT_FIX``. Default ON.

    The Step-1.5 R/B swap kernel runs by default — without it the
    streamed frame has its red and blue channels exchanged (a known
    cosmetic gap with the historical RTSP path). Flipping the env to
    ``0`` / ``false`` / ``no`` / ``off`` / empty string keeps the
    legacy R/B-swapped output, useful for diagnostic comparisons.
    """
    raw = os.environ.get(_FORMAT_FIX_ENV_VAR)
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _async_enabled() -> bool:
    """Stream through the asynchronous pipeline (``tee_async``). ``OVUI_STREAM_ASYNC=0`` restores
    the synchronous tee (host waits for the frame, D2D + in-place swap + stream sync)."""
    return os.environ.get("OVUI_STREAM_ASYNC", "1").strip().lower() not in ("0", "false", "no")


def _timestamps_enabled() -> bool:
    """Pass capture timestamps with each frame (``OVUI_STREAM_TIMESTAMPS=1``, experimental)."""
    return os.environ.get("OVUI_STREAM_TIMESTAMPS", "0").strip().lower() in ("1", "true", "yes")


def _repeat_enabled() -> bool:
    """Re-send the last frame on a publish tick with no new frame (``OVUI_STREAM_REPEAT=0`` disables)."""
    return os.environ.get("OVUI_STREAM_REPEAT", "1").strip().lower() not in ("0", "false", "no")


class _Publisher:
    """Submit frames to ovstream from one thread, paced by when they were rendered.

    The ovstream reference pipeline (``examples/python/app_stream`` in ovstream 0.5): the producer
    queues a copy into a scratch slot on its own CUDA stream and records an event; this thread
    submits the frame once its copy has completed (events are polled, never awaited one at a time:
    on a saturated GPU a copy completes only after the next render).

    Frames are sent in order at ``produced + slot offset + latency budget``: a frame-generation
    step's frames are spaced one period apart, and the budget follows the 98th percentile of copy
    completion (one to four periods), so send spacing follows the render cadence. A free-running
    send clock beat against the render clock and sent every other frame several milliseconds late
    (120 Hz: send interval p95 12.4 ms for 8.33). The last frame is re-sent only when nothing was
    sent for 2.5 periods (``OVUI_STREAM_REPEAT=0`` disables). Slots in flight or being re-sent are
    never handed back to the producer.
    """

    # Frames whose copy may still be running. On a saturated GPU a copy completes only after the next
    # render, and frame generation posts two frames per render: at 120 Hz four was too few, and the
    # oldest frame was evicted before its copy finished, so almost none were ever sent.
    MAX_IN_FLIGHT = 8

    def __init__(self, tap: "LivestreamTap", fps: int) -> None:
        self._tap = tap
        self._period = 1.0 / max(1, int(fps))
        self._repeat = _repeat_enabled()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        # (slot, event, width, height, seq, t_produced, offset), oldest first
        self._in_flight: list = []
        self._last: Optional[tuple] = None
        self._ready_at: Optional[float] = None
        self._copy_latency: list = []
        self.budget = self._period
        self._stop = False
        self.new_frames = 0
        self.repeated_frames = 0
        self.dropped_frames = 0
        self.submit_seconds = 0.0
        self.wait_seconds = 0.0
        self.call_seconds = 0.0
        # The render thread runs long stretches of Python; keep the GIL hand-off short so the send
        # lands on time (the default switch interval is 5 ms).
        self._switch_interval = sys.getswitchinterval()
        try:
            sys.setswitchinterval(float(os.environ.get("OVUI_STREAM_SWITCH_INTERVAL", "0.0005")))
        except ValueError:
            pass
        self._thread = threading.Thread(target=self._run, name="ovui-stream-publisher", daemon=True)
        self._thread.start()

    def busy_slots(self) -> set:
        with self._lock:
            busy = {frame[0] for frame in self._in_flight}
            if self._last is not None:
                busy.add(self._last[0])
            return busy

    def post(self, slot: int, event: int, width: int, height: int, seq: int = 0,
             produced: float = 0.0, offset: float = 0.0) -> None:
        dropped = 0
        with self._lock:
            self._in_flight.append((slot, event, width, height, seq, produced, offset))
            while len(self._in_flight) > self.MAX_IN_FLIGHT:
                self._in_flight.pop(0)
                dropped += 1
            self.dropped_frames += dropped
        trace = getattr(self._tap, "_trace", None)
        if dropped and trace is not None:
            trace.dropped(dropped)
        self._wake.set()

    def stop(self) -> None:
        self._stop = True
        self._wake.set()
        self._thread.join(timeout=2.0)
        sys.setswitchinterval(self._switch_interval)

    def _next(self) -> Optional[tuple]:
        """The oldest frame whose copy completed; frames more than two periods overdue are skipped."""
        query = self._tap._cudart.event_query
        with self._lock:
            if not self._in_flight or not query(self._in_flight[0][1]):
                return None
            done = 1
            while done < len(self._in_flight) and query(self._in_flight[done][1]):
                done += 1
            now = time.perf_counter()
            skip = 0
            # Catch up after a stall: keep at most the two newest of the completed, overdue frames.
            while skip < done - 2 and self._due(self._in_flight[skip + 1]) < now - 2 * self._period:
                skip += 1
            frame = self._in_flight[skip]
            del self._in_flight[: skip + 1]
            self.dropped_frames += skip
        self._ready_at = now
        trace = getattr(self._tap, "_trace", None)
        if skip and trace is not None:
            trace.dropped(skip)
        return frame

    def _due(self, frame: tuple) -> float:
        return frame[5] + frame[6] + self.budget

    def _learn(self, frame: tuple) -> None:
        """Track copy completion latency; the budget is its 98th percentile, 1-4 periods."""
        self._copy_latency.append(self._ready_at - frame[5] - frame[6])
        if len(self._copy_latency) >= 30:
            ordered = sorted(self._copy_latency[-120:])
            # 98th percentile: a frame whose copy finishes after its due time is sent late and the
            # next one early, and two frames closer than a display refresh show as one (a skip).
            p98 = ordered[int(0.98 * (len(ordered) - 1))]
            self.budget = min(4 * self._period, max(self._period, p98 + 0.001))
            del self._copy_latency[:-120]

    def _run(self) -> None:
        last_sent: Optional[float] = None
        while not self._stop:
            trace = getattr(self._tap, "_trace", None)
            if trace is not None:
                trace.tick()
            frame = self._next()
            now = time.perf_counter()
            fresh = frame is not None
            if frame is None:
                if not (self._repeat and self._last is not None and last_sent is not None
                        and now - last_sent >= 2.5 * self._period):
                    self._wake.wait(0.0005)
                    self._wake.clear()
                    continue
                frame = self._last
            else:
                self._learn(frame)
                due = self._due(frame)
                if last_sent is not None:
                    # Never closer than 0.9 periods: at 60 fps a 12.5 ms gap (the former 0.75 floor)
                    # put two frames in one 16.7 ms display refresh, and the browser skipped one.
                    due = max(due, last_sent + 0.9 * self._period)
                delay = due - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
            if self._stop:
                break
            started = time.perf_counter()
            ok = self._tap._publish(frame, fresh)
            finished = time.perf_counter()
            last_sent = started
            if ok:
                if fresh:
                    self.new_frames += 1
                else:
                    self.repeated_frames += 1
                if trace is not None:
                    trace.sent(frame[4], fresh, frame[5], self._ready_at if fresh else None, finished,
                               finished - started, len(self._in_flight))
            self.submit_seconds += finished - started
            with self._lock:
                self._last = frame


def _resolve_buffer_ring_len() -> int:
    """Resolve the CUDA scratch ring depth used for livestream frames."""
    raw = os.environ.get(_BUFFER_RING_ENV_VAR)
    if raw is None:
        return _DEFAULT_RING_LEN
    try:
        value = int(raw)
    except ValueError:
        print(
            f"[ovgear/livestream] {_BUFFER_RING_ENV_VAR}={raw!r} is not "
            f"an integer; using default {_DEFAULT_RING_LEN}.",
            file=sys.stderr,
        )
        return _DEFAULT_RING_LEN
    if value < _MIN_RING_LEN:
        print(
            f"[ovgear/livestream] {_BUFFER_RING_ENV_VAR}={value} is below "
            f"the minimum safe value {_MIN_RING_LEN}; using {_MIN_RING_LEN}.",
            file=sys.stderr,
        )
        return _MIN_RING_LEN
    if value > _MAX_RING_LEN:
        print(
            f"[ovgear/livestream] {_BUFFER_RING_ENV_VAR}={value} exceeds "
            f"the maximum {_MAX_RING_LEN}; using {_MAX_RING_LEN}.",
            file=sys.stderr,
        )
        return _MAX_RING_LEN
    return value


def _resolve_ports() -> Tuple[int, int]:
    """Resolve ``(signal_port, media_port)`` from env vars with deprecation.

    The new Step-1.2 API uses two distinct env vars matching ovstream's
    ``ServerConfig`` shape:

    - ``OVGEAR_LIVESTREAM_SIGNAL_PORT`` → ``webrtc_signal_port``
      (default 49100, Kit-standard).
    - ``OVGEAR_LIVESTREAM_MEDIA_PORT`` → ``stream_port`` (default 47999,
      ovstream SDK's WebRTC default).

    The legacy single-port var ``OVGEAR_LIVESTREAM_PORT`` is honoured
    for back-compat: if it is set we use it as a fallback for the
    signaling port (the user-facing port for browser-driven flows) and
    emit a one-shot stderr deprecation warning telling the user which
    new var to set explicitly. A non-integer legacy value is ignored
    with its own warning. The new vars, if also set, override the
    legacy fallback so a partial migration still works.

    Non-integer values for the new vars trigger a warning and fall back
    to the documented default — same "never crash the renderer"
    philosophy as the protocol resolver.
    """
    signal_port = _DEFAULT_SIGNAL_PORT
    media_port  = _DEFAULT_MEDIA_PORT

    legacy = os.environ.get(_LEGACY_PORT_ENV_VAR)
    if legacy is not None:
        print(
            f"[ovgear/livestream] {_LEGACY_PORT_ENV_VAR}={legacy!r} is "
            f"deprecated; using it as a fallback for {_SIGNAL_PORT_ENV_VAR}. "
            f"Set {_SIGNAL_PORT_ENV_VAR} (Kit-standard signaling port, "
            f"default {_DEFAULT_SIGNAL_PORT}) and/or {_MEDIA_PORT_ENV_VAR} "
            f"(default {_DEFAULT_MEDIA_PORT}) explicitly instead.",
            file=sys.stderr,
        )
        try:
            signal_port = int(legacy)
        except ValueError:
            print(
                f"[ovgear/livestream] {_LEGACY_PORT_ENV_VAR}={legacy!r} "
                f"is not an integer; ignoring.",
                file=sys.stderr,
            )

    signal_raw = os.environ.get(_SIGNAL_PORT_ENV_VAR)
    if signal_raw is not None:
        try:
            signal_port = int(signal_raw)
        except ValueError:
            print(
                f"[ovgear/livestream] {_SIGNAL_PORT_ENV_VAR}={signal_raw!r} "
                f"is not an integer; using default {_DEFAULT_SIGNAL_PORT}.",
                file=sys.stderr,
            )

    media_raw = os.environ.get(_MEDIA_PORT_ENV_VAR)
    if media_raw is not None:
        try:
            media_port = int(media_raw)
        except ValueError:
            print(
                f"[ovgear/livestream] {_MEDIA_PORT_ENV_VAR}={media_raw!r} "
                f"is not an integer; using default {_DEFAULT_MEDIA_PORT}.",
                file=sys.stderr,
            )

    return signal_port, media_port


def _resolve_server_type(ovstream: Any, raw: str) -> Any:
    """Map an ``OVGEAR_LIVESTREAM_PROTOCOL`` value to ``ovstream.ServerType``.

    The lookup is case-insensitive and accepts the same three names the
    SDK exposes via its ``ServerType`` IntEnum:

    - ``"webrtc"`` → ``ovstream.ServerType.WEBRTC`` (default; matches
      what `web-viewer-sample` speaks).
    - ``"native"`` → ``ovstream.ServerType.NATIVE``.
    - ``"rtsp"`` → ``ovstream.ServerType.RTSP`` (legacy; cannot carry
      the tier-3 input back-channel).

    Unknown values fall back to the default with a one-shot stderr
    warning. The tap's overall philosophy is "never crash the
    renderer"; an invalid env var should not black the viewport.
    """
    name = raw.strip().lower()
    if name == "webrtc":
        return ovstream.ServerType.WEBRTC
    if name == "native":
        return ovstream.ServerType.NATIVE
    if name == "rtsp":
        return ovstream.ServerType.RTSP
    print(
        f"[ovgear/livestream] unknown {_PROTOCOL_ENV_VAR}={raw!r}; "
        f"falling back to {_DEFAULT_PROTOCOL!r}",
        file=sys.stderr,
    )
    return ovstream.ServerType.WEBRTC


def _runtime_pip_hint() -> str:
    return (
        "ovstream not importable. Install the ovstream SDK:\n"
        "  pip install <path-to-kit-livestream>/sdk/python\n"
        f"and run with {_ENABLED_ENV_VAR}=1."
    )


class _Cudart:
    """ctypes thunk around libcudart's memcpy — no torch/cupy dep."""

    D2H = 2
    D2D = 3

    def __init__(self) -> None:
        self._lib = self._load_libcudart()
        self._lib.cudaMemcpy.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int,
        ]
        self._lib.cudaMemcpy.restype = ctypes.c_int
        self._lib.cudaMalloc.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t]
        self._lib.cudaMalloc.restype = ctypes.c_int
        # cudaMallocPitch(devPtr, pitch, widthInBytes, height) — used by
        # the Step-2.5 linear scratch ring. The driver picks a pitch
        # >= widthInBytes that aligns each row for the encoder; the
        # caller treats subsequent rows as `base + y * pitch` instead
        # of `base + y * widthInBytes`.
        self._lib.cudaMallocPitch.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_size_t,
            ctypes.c_size_t,
        ]
        self._lib.cudaMallocPitch.restype = ctypes.c_int
        self._lib.cudaFree.argtypes = [ctypes.c_void_p]
        self._lib.cudaFree.restype = ctypes.c_int
        self._lib.cudaDeviceSynchronize.argtypes = []
        self._lib.cudaDeviceSynchronize.restype = ctypes.c_int
        # cudaStreamSynchronize is per-stream; cheaper than
        # cudaDeviceSynchronize when we only need the kernel's own
        # stream to drain (Step 1.6 fix — see ``stream_synchronize``).
        self._lib.cudaStreamSynchronize.argtypes = [ctypes.c_void_p]
        self._lib.cudaStreamSynchronize.restype = ctypes.c_int
        self._lib.cudaSetDevice.argtypes = [ctypes.c_int]
        self._lib.cudaSetDevice.restype = ctypes.c_int
        self._lib.cudaMemcpyPeer.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t,
        ]
        self._lib.cudaMemcpyPeer.restype = ctypes.c_int
        # Asynchronous stream/event pipeline (``LivestreamTap.tee_async``).
        self._lib.cudaStreamCreateWithFlags.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint]
        self._lib.cudaStreamCreateWithFlags.restype = ctypes.c_int
        self._lib.cudaStreamDestroy.argtypes = [ctypes.c_void_p]
        self._lib.cudaStreamDestroy.restype = ctypes.c_int
        self._lib.cudaEventCreateWithFlags.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint]
        self._lib.cudaEventCreateWithFlags.restype = ctypes.c_int
        self._lib.cudaEventDestroy.argtypes = [ctypes.c_void_p]
        self._lib.cudaEventDestroy.restype = ctypes.c_int
        self._lib.cudaEventRecord.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._lib.cudaEventRecord.restype = ctypes.c_int
        self._lib.cudaEventSynchronize.argtypes = [ctypes.c_void_p]
        self._lib.cudaEventSynchronize.restype = ctypes.c_int
        self._lib.cudaEventQuery.argtypes = [ctypes.c_void_p]
        self._lib.cudaEventQuery.restype = ctypes.c_int

    STREAM_NON_BLOCKING = 1
    EVENT_DISABLE_TIMING = 2

    def create_stream(self) -> int:
        stream = ctypes.c_void_p(0)
        rc = self._lib.cudaStreamCreateWithFlags(ctypes.byref(stream), self.STREAM_NON_BLOCKING)
        if rc != 0:
            raise RuntimeError(f"cudaStreamCreateWithFlags failed rc={rc}")
        return int(stream.value or 0)

    def destroy_stream(self, stream: int) -> None:
        if stream:
            self._lib.cudaStreamDestroy(ctypes.c_void_p(stream))

    def create_event(self) -> int:
        event = ctypes.c_void_p(0)
        rc = self._lib.cudaEventCreateWithFlags(ctypes.byref(event), self.EVENT_DISABLE_TIMING)
        if rc != 0:
            raise RuntimeError(f"cudaEventCreateWithFlags failed rc={rc}")
        return int(event.value or 0)

    def destroy_event(self, event: int) -> None:
        if event:
            self._lib.cudaEventDestroy(ctypes.c_void_p(event))

    def record_event(self, event: int, stream: int) -> None:
        rc = self._lib.cudaEventRecord(ctypes.c_void_p(event), ctypes.c_void_p(stream))
        if rc != 0:
            raise RuntimeError(f"cudaEventRecord failed rc={rc}")

    def event_query(self, event: int) -> bool:
        """True when the event has completed (cudaSuccess); False while pending (cudaErrorNotReady)."""
        return self._lib.cudaEventQuery(ctypes.c_void_p(event)) == 0

    def event_synchronize(self, event: int) -> None:
        rc = self._lib.cudaEventSynchronize(ctypes.c_void_p(event))
        if rc != 0:
            raise RuntimeError(f"cudaEventSynchronize failed rc={rc}")

    @staticmethod
    def _load_libcudart() -> Any:
        last_exc: Optional[OSError] = None
        if os.name == "nt":
            # Windows x64: the CUDA runtime DLL that omni.ui ships.
            candidates = ["cudart64_12.dll", "cudart64_11.dll"]
        else:
            # Linux x86_64 and Linux ARM64 library names.
            candidates = [
                ctypes.util.find_library("cudart"),
                "libcudart.so",
                "libcudart.so.12",
                "libcudart.so.1",
            ]
        for candidate in candidates:
            if not candidate:
                continue
            try:
                return ctypes.CDLL(candidate)
            except OSError as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        raise OSError("libcudart not found")

    def d2h(
        self, host: np.ndarray, device_ptr: int, nbytes: int, device: Optional[int] = None,
    ) -> None:
        """Copy to host; ``device`` names the GPU holding ``device_ptr``."""
        current = self.current_device() if device is not None else None
        if current is not None and device != current:
            # The renderer may place a RenderProduct on another GPU; its
            # memory is only addressable from that device.
            if self._lib.cudaSetDevice(int(device)) != 0:
                raise RuntimeError(f"cudaSetDevice({device}) failed")
        try:
            rc = self._lib.cudaMemcpy(
                host.ctypes.data_as(ctypes.c_void_p),
                ctypes.c_void_p(device_ptr),
                nbytes,
                self.D2H,
            )
        finally:
            if current is not None and device != current:
                self._lib.cudaSetDevice(current)
        if rc != 0:
            raise RuntimeError(f"cudaMemcpy D2H failed rc={rc}")

    def current_context(self) -> int:
        """Return the producer's CUDA context for ovstream own-context input."""
        if self._lib.cudaFree(ctypes.c_void_p()) != 0:
            raise RuntimeError("Could not initialize the producer CUDA context")
        driver = ctypes.CDLL("nvcuda.dll" if os.name == "nt" else "libcuda.so.1")
        driver.cuCtxGetCurrent.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        driver.cuCtxGetCurrent.restype = ctypes.c_int
        context = ctypes.c_void_p()
        if driver.cuCtxGetCurrent(ctypes.byref(context)) != 0 or not context.value:
            raise RuntimeError("No current producer CUDA context")
        return int(context.value)

    def current_device(self) -> int:
        self._lib.cudaGetDevice.argtypes = [ctypes.POINTER(ctypes.c_int)]
        self._lib.cudaGetDevice.restype = ctypes.c_int
        device = ctypes.c_int()
        if self._lib.cudaGetDevice(ctypes.byref(device)) != 0:
            raise RuntimeError("Could not resolve the producer CUDA device")
        return device.value

    def d2d(
        self, dst_ptr: int, src_ptr: int, nbytes: int, src_device: Optional[int] = None,
    ) -> None:
        """Copy into ``dst_ptr`` on the current device from ``src_device``."""
        if src_device is not None:
            current = self.current_device()
            if src_device != current:
                rc = self._lib.cudaMemcpyPeer(
                    ctypes.c_void_p(dst_ptr), current,
                    ctypes.c_void_p(src_ptr), int(src_device), nbytes,
                )
                if rc != 0:
                    raise RuntimeError(
                        f"cudaMemcpyPeer from device {src_device} failed rc={rc}"
                    )
                return
        rc = self._lib.cudaMemcpy(
            ctypes.c_void_p(dst_ptr),
            ctypes.c_void_p(src_ptr),
            nbytes,
            self.D2D,
        )
        if rc != 0:
            raise RuntimeError(f"cudaMemcpy D2D failed rc={rc}")

    def malloc(self, nbytes: int) -> int:
        ptr = ctypes.c_void_p()
        rc = self._lib.cudaMalloc(ctypes.byref(ptr), nbytes)
        if rc != 0:
            raise RuntimeError(f"cudaMalloc({nbytes}) failed rc={rc}")
        return int(ptr.value)

    def malloc_pitch(self, width_bytes: int, height: int) -> Tuple[int, int]:
        """Allocate a pitched 2D buffer; returns ``(dev_ptr, pitch_bytes)``.

        ``pitch_bytes`` is the actual row stride chosen by the driver,
        always ``>= width_bytes``. Callers must address row ``y`` at
        ``dev_ptr + y * pitch_bytes`` (not ``y * width_bytes``).
        """
        ptr = ctypes.c_void_p()
        pitch = ctypes.c_size_t()
        rc = self._lib.cudaMallocPitch(
            ctypes.byref(ptr),
            ctypes.byref(pitch),
            ctypes.c_size_t(width_bytes),
            ctypes.c_size_t(height),
        )
        if rc != 0:
            raise RuntimeError(
                f"cudaMallocPitch(width_bytes={width_bytes}, height={height}) "
                f"failed rc={rc}"
            )
        return int(ptr.value), int(pitch.value)

    def free(self, device_ptr: int) -> None:
        if device_ptr:
            rc = self._lib.cudaFree(ctypes.c_void_p(device_ptr))
            if rc != 0:
                print(f"[ovgear/livestream] cudaFree failed rc={rc}", file=sys.stderr)

    def stream_synchronize(self, stream: int = 0) -> None:
        """Block the host until ``stream`` drains.

        Used to fence the Step-1.5 R/B swap kernel before
        ``Server.stream_video`` reads the scratch buffer (Step 1.6
        fix). The kernel was launched on the default stream
        (``stream=0``); the runtime API and the driver API share the
        device-0 primary context, so a runtime-side
        ``cudaStreamSynchronize(0)`` correctly waits on the
        driver-side ``cuLaunchKernel``'s queued work.
        """
        rc = self._lib.cudaStreamSynchronize(ctypes.c_void_p(stream))
        if rc != 0:
            raise RuntimeError(f"cudaStreamSynchronize stream={stream} failed rc={rc}")

    def device_synchronize(self) -> None:
        rc = self._lib.cudaDeviceSynchronize()
        if rc != 0:
            # Don't raise: this is a best-effort drain hook. A failure
            # here means CUDA is unhealthy; freeing the scratch can't
            # make things worse.
            print(f"[ovgear/livestream] cudaDeviceSynchronize failed rc={rc}", file=sys.stderr)


class LivestreamTap:
    """Lazy ovstream.Server tap. Resilient — if anything fails, the tap
    disables itself and the renderer keeps running on the CPU path."""

    @classmethod
    def maybe_create(cls) -> Optional["LivestreamTap"]:
        if not _enabled():
            return None
        try:
            import ovstream  # noqa: F401
        except ImportError as exc:
            print(f"[ovgear/livestream] disabled — {exc}", file=sys.stderr)
            print(f"[ovgear/livestream] {_runtime_pip_hint()}", file=sys.stderr)
            return None
        try:
            tap = cls()
            return tap
        except Exception as exc:
            print(f"[ovgear/livestream] disabled — init failed: {exc}", file=sys.stderr)
            return None

    def __init__(
        self,
        *,
        cuda_context: Optional[int] = None,
        config: Optional[dict] = None,
        manage_sdk: bool = True,
        trace_directory: Optional[Any] = None,
    ) -> None:
        import ovstream
        self._ovstream = ovstream
        # An owner that keeps the process-level SDK alive across streams
        # passes manage_sdk=False; this tap then neither initializes nor
        # shuts it down.
        self._manage_sdk = manage_sdk
        self._cudart = _Cudart()
        self._cuda_context = cuda_context

        # Explicit application controls are isolated from environment defaults.
        if config is None:
            signal_port, media_port = _resolve_ports()
            fps = int(os.environ.get("OVGEAR_LIVESTREAM_FPS", "30"))
            protocol_raw = os.environ.get(_PROTOCOL_ENV_VAR, _DEFAULT_PROTOCOL)
            public_ip = os.environ.get(_PUBLIC_IP_ENV_VAR) or None
        else:
            protocol_raw = config["protocol"]
            signal_port = config["signal_port"]
            media_port = config["media_port"]
            fps = config["fps"]
            public_ip = config.get("public_ip")
        self._signal_port = signal_port
        self._media_port = media_port
        self._fps = fps
        self._protocol = protocol_raw
        self._server_type = _resolve_server_type(ovstream, protocol_raw)
        self._public_ip = public_ip
        self._ring_len = _resolve_buffer_ring_len()
        # Step 1.6: gate the R/B swap kernel. Default ON.
        self._format_fix = _format_fix_enabled()

        # Connection-status atom (Step 1.4). The SDK fires the
        # ``on_connection`` callback on a worker thread; ovgear's main
        # loop reads ``status()`` once per frame for the overlay widget
        # (Step 1.7). The lock guards the trio so a concurrent connect
        # never tears the read.
        self._status_lock = threading.Lock()
        self._status_state: str = _STATE_OFF
        self._status_n_clients: int = 0
        self._status_last_error: Optional[str] = None

        # Initialize ovstream once. Re-init on second call raises in the
        # C lib; tolerate that for hot-reload scenarios.
        if manage_sdk:
            try:
                ovstream.initialize(log_fn=self._log)
            except Exception:
                pass

        self._server: Any = None
        self._size: Tuple[int, int] = (0, 0)
        # Tier 3 input bridge. When set via
        # :meth:`set_input_bridge`, ``_ensure_server`` registers the
        # ``on_input`` / ``on_unicode`` / ``on_connection`` callbacks
        # on the ovstream :class:`Server` so remote keyboard/mouse
        # events feed the bridge before ``server.start(cfg)`` is
        # called (a connect that fires between ``start`` and a later
        # callback assignment lands on a null pointer on the C side
        # and is silently dropped — same lesson as Step 1.4).
        self._input_bridge: Any = None
        # Tier 3 custom-message dispatcher.
        # Set via :meth:`set_message_dispatcher`. When attached,
        # ``_ensure_server`` registers the dispatcher's ``on_message``
        # on the ovstream :class:`Server` before ``Server.start(cfg)``
        # — same ordering invariant as the input callbacks.
        self._message_dispatcher: Any = None
        # Ring of CUDA scratch device pointers; rotates per-frame.
        # Empty until the first successful ``_ensure_server``.
        self._scratch_ring: list = []
        self._scratch_size: Tuple[int, int] = (0, 0)
        self._scratch_index: int = -1
        # Step 2.5: separate ring of *pitched* device buffers used by the
        # headless composite hook. ovui's ``copyHeadlessFrameToLinear``
        # writes into one of these slots, the swap kernel runs in place,
        # and ``tee_linear_to_ovstream`` publishes it to NVENC. Lazy:
        # only allocated on the first ``acquire_linear_scratch`` call
        # so the windowed path doesn't pay the cost.
        self._linear_ring: list = []
        self._linear_size: Tuple[int, int] = (0, 0)
        self._linear_pitch: int = 0
        self._linear_index: int = -1
        # Set to True if a non-recoverable error occurs (e.g., a
        # non-OvstreamError raised from stream_video). The livestream
        # leg is then bypassed for the rest of the session; the UI
        # path keeps running.
        self._disabled = False
        # Asynchronous pipeline (``tee_async``): a CUDA stream owned by the tap, one event per
        # scratch slot, and the publish thread. Created with the server. Its copy always swaps R/B:
        # with the format fix off (a diagnostic), frames take the synchronous tee, which honors it.
        self._async = _async_enabled() and self._format_fix
        self._cuda_stream: int = 0
        self._slot_events: list = []
        self._publisher: Optional[_Publisher] = None
        # Stream performance trace (``_stream_trace``): created with the server, kept across resizes.
        self._trace_directory = trace_directory
        self._trace: Any = None
        self._seq = 0

        self._first_push_logged = False
        self._d2d_error_logged = False
        self._stream_error_logged = False
        self._frames_pushed = 0
        self._frames_skipped = 0
        self._tee_attempts = 0
        self._closed = False
        self._close_count = 0
        self._t0 = time.monotonic()
        self._last_report_t = self._t0

    @staticmethod
    def _log(
        level: Any,
        channel: bytes | str,
        msg: bytes | str,
        _timestamp: float | None = None,
    ) -> None:
        # ovstream callback: level is a LogLevel enum, channel/msg are bytes.
        try:
            channel_text = (
                channel.decode("utf-8", errors="replace")
                if isinstance(channel, bytes)
                else str(channel)
            )
            message_text = (
                msg.decode("utf-8", errors="replace")
                if isinstance(msg, bytes)
                else str(msg)
            )
            print(
                f"[ovstream/{level.name}/{channel_text}] {message_text}",
                file=sys.stderr,
            )
        except Exception:
            pass

    # ── Connection-status atom (Step 1.4) ──

    def _on_connection_changed(self, connected: bool) -> None:
        """SDK ``on_connection`` callback. Runs on a worker thread.

        ``connected=True`` is fired for every client join; ``False`` for
        every leave. The atom tracks the current attached-client count
        so the overlay widget (Step 1.7) can render
        ``Streaming N clients`` exactly. Lock-guarded because the
        callback thread and the main loop both touch the trio.

        Once the atom is in the ERROR state (Tier-1 fix; see
        ``_set_error_status``), connection events do **not** transition
        out of it — the tap is permanently disabled and the overlay
        must keep showing the failure to the user even if the SDK
        keeps emitting connect/disconnect events.

        Step 3.6: when a Tier 3 input bridge is registered, every
        connection event is also forwarded to the bridge. The bridge
        ignores ``connected=True`` and uses ``connected=False`` to
        synthesise release events for any modifier key the remote
        client was holding when the link dropped (Step 3.5
        side-aware cleanup). The status-atom logic above and the
        bridge cleanup are independent — running both unconditionally
        means the cleanup still fires even after the tap latches into
        ERROR.
        """
        bridge = self._input_bridge
        if bridge is not None:
            try:
                bridge.on_connection(bool(connected))
            except Exception as exc:
                # Worker-thread safety: never let a bridge bug tear
                # down the ovstream callback path.
                print(
                    f"[ovgear/livestream] input bridge on_connection "
                    f"raised: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )

        with self._status_lock:
            if self._status_state == _STATE_ERROR:
                # Track the count for diagnostics but don't downgrade
                # the visible state.
                if connected:
                    self._status_n_clients += 1
                else:
                    self._status_n_clients = max(0, self._status_n_clients - 1)
                return
            if connected:
                self._status_n_clients += 1
                self._status_state = _STATE_STREAMING
            else:
                self._status_n_clients = max(0, self._status_n_clients - 1)
                if self._status_n_clients == 0 and self._server is not None:
                    self._status_state = _STATE_LISTENING
                # If a client drops while others remain, state stays
                # STREAMING — no transition.
            clients = self._status_n_clients
        trace = self._trace
        if trace is not None:
            trace.connection(bool(connected), clients)

    # ── Tier 3 input callbacks (Step 3.6) ──

    def set_input_bridge(self, bridge: Any) -> None:
        """Register the :class:`RemoteInputBridge` for remote control.

        Call this **before** the first ``ensure_server`` so the
        callbacks are wired up at server creation; ``None`` detaches
        the bridge so callbacks become no-ops.
        """
        self._input_bridge = bridge

    def _dispatch_input_event(self, event: Any) -> None:
        """ovstream ``Server.on_input`` callback — runs on a worker thread.

        Unpacks the union-style :class:`ovstream.InputEvent` and
        forwards each variant to the matching :class:`RemoteInputBridge`
        method. Keyboard and mouse events are handled (Step 3.6 scope);
        gamepad events are dropped silently — the bridge has no
        gamepad path yet, and feeding a gamepad event into the
        keyboard or mouse handler would corrupt state.
        """
        bridge = self._input_bridge
        if bridge is None:
            return
        ovstream = self._ovstream
        if ovstream is None:
            return
        try:
            event_type = event.type
            if event_type == ovstream.InputEventType.KEYBOARD:
                kb = event.keyboard
                if kb is not None:
                    bridge.on_keyboard_event(kb)
            elif event_type == ovstream.InputEventType.MOUSE:
                ms = event.mouse
                if ms is not None:
                    bridge.on_mouse_event(ms)
            # GAMEPAD: silent drop (Step 3.6 scope is keyboard+mouse).
        except Exception as exc:
            print(
                f"[ovgear/livestream] input bridge dispatch raised: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    def set_message_dispatcher(self, dispatcher: Any) -> None:
        """Register the Step 3.7 custom-message dispatcher.

        ``dispatcher.on_message(text)`` is wired to
        :class:`ovstream.Server.on_message` at the next
        ``_ensure_server`` so messages arriving from the WebRTC client
        (Kit-style flat ``{event_type, payload}`` JSON) drive
        application actions and reply through ``Server.send_message``.
        Pass ``None`` to detach.
        """
        self._message_dispatcher = dispatcher

    def _dispatch_unicode(self, text: str) -> None:
        """ovstream ``Server.on_unicode`` callback — text/IME input.

        Forwards to the bridge so the drain (Step 3.3) emits
        ``_ui._inject_text_input(text)`` on the next frame.
        """
        bridge = self._input_bridge
        if bridge is None:
            return
        try:
            bridge.on_unicode(text)
        except Exception as exc:
            print(
                f"[ovgear/livestream] input bridge on_unicode raised: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    def _set_error_status(self, last_error: str) -> None:
        """Latch the status atom into ERROR with a user-facing message.

        Called from every permanent-disable path in the tap (the
        non-OvstreamError catch in ``tee_to_ovstream``, the
        belt-and-suspenders catch in ``tee_and_d2h``, and the
        swap/stream sync failure in Step 1.6). The Step-1.7 status
        overlay reads ``last_error`` via ``status()`` and surfaces it
        as ``Error: <last_error>`` so the failure is visible to the
        user instead of the misleading ``Listening`` carry-over.
        Sticky: once ERROR, the connection callback does not move the
        atom back to LISTENING/STREAMING.
        """
        with self._status_lock:
            self._status_state = _STATE_ERROR
            self._status_last_error = str(last_error)

    def status(self) -> Tuple[str, int, Optional[str]]:
        """Snapshot the connection-status atom.

        Returns ``(state, n_clients, last_error)``. ``state`` is one of
        ``"OFF" / "LISTENING" / "STREAMING" / "ERROR"`` (the constants
        ``_STATE_*`` above). The Step 1.7 overlay widget calls this
        once per frame.
        """
        with self._status_lock:
            return (self._status_state, self._status_n_clients, self._status_last_error)

    # ── Static accessors for the Step-1.7 status overlay ──

    @property
    def extent(self) -> Tuple[int, int]:
        """Dimensions of the encoded stream, including renderer-driven resizes.

        The width is the aligned width actually encoded (``_encoder_width``),
        which can be up to seven columns narrower than the source.
        """
        width, height = self._size
        return (_encoder_width(width), height)

    @property
    def submitted_frames(self) -> int:
        """Frames accepted by the sender; this is not receiver decode proof."""
        return self._frames_pushed

    @property
    def protocol(self) -> str:
        """The configured protocol name (`"webrtc"` / `"native"` /
        `"rtsp"`). Resolved at construction; immutable for the
        lifetime of the tap."""
        return self._protocol

    @property
    def signal_port(self) -> int:
        """The WebRTC/native signaling port in use. Default 49100."""
        return self._signal_port

    @property
    def media_port(self) -> int:
        """The streaming media port. Default 47999 (WebRTC) or the
        legacy 8554 for RTSP back-compat."""
        return self._media_port

    @property
    def public_ip(self) -> Optional[str]:
        """The pinned WebRTC public IP, or ``None`` to use ICE."""
        return self._public_ip

    # ── Internal lifecycle ──

    def _teardown_server_and_scratch(self) -> None:
        """Stop the server (drains the encoder pipeline), then sync and
        free the D2D scratch ring. Idempotent. Called on resize and
        close.

        **Does not** touch ``_linear_ring`` — the linear (pitched) ring
        is owned by the headless Step-2.5/2.6 path which calls
        :meth:`acquire_linear_scratch` *before*
        :meth:`tee_linear_to_ovstream`. Freeing the linear ring here
        would invalidate the device pointer the caller is about to
        stream (Codex: server bring-up frees the buffer that's about
        to be streamed). The linear ring has its own teardown in
        :meth:`_teardown_linear_ring`, called on linear-ring resize
        and from :meth:`close`.
        """
        if self._publisher is not None:
            # stream_video must not overlap Server.stop/close.
            self._publisher.stop()
            self._publisher = None
        if self._server is not None:
            try:
                self._server.stop()
            except Exception:
                pass
            try:
                self._server.close()
            except Exception:
                pass
            self._server = None
            self._size = (0, 0)
            # Status atom: any clients that were attached are now gone.
            with self._status_lock:
                self._status_state = _STATE_OFF
                self._status_n_clients = 0
        if self._scratch_ring:
            # Defensive drain: server.stop() is meant to wait for the
            # encoder to flush, but a synchronize before free is cheap
            # insurance against any remaining in-flight reads.
            try:
                self._cudart.device_synchronize()
            except Exception:
                pass
            for ptr in self._scratch_ring:
                try:
                    self._cudart.free(ptr)
                except Exception:
                    pass
            self._scratch_ring = []
            self._scratch_size = (0, 0)
            self._scratch_index = -1
        for event in self._slot_events:
            try:
                self._cudart.destroy_event(event)
            except Exception:
                pass
        self._slot_events = []

    def _teardown_linear_ring(self) -> None:
        """Drain and free the linear (pitched) scratch ring. Idempotent.

        Called from :meth:`_ensure_linear_ring` on resize and from
        :meth:`close` on shutdown — **not** from
        :meth:`_teardown_server_and_scratch`, so a server bring-up
        triggered by :meth:`tee_linear_to_ovstream` cannot invalidate a
        device pointer the caller just got from
        :meth:`acquire_linear_scratch`.
        """
        if not self._linear_ring:
            return
        try:
            self._cudart.device_synchronize()
        except Exception:
            pass
        for ptr in self._linear_ring:
            try:
                self._cudart.free(ptr)
            except Exception:
                pass
        self._linear_ring = []
        self._linear_size = (0, 0)
        self._linear_pitch = 0
        self._linear_index = -1

    def start(self, width: int, height: int) -> None:
        """Start explicitly, propagating failures to a control-plane caller."""
        if self._closed:
            raise RuntimeError("Cannot restart a closed LivestreamTap; create a new tap")
        self._ensure_server(width, height)

    def _ensure_server(self, width: int, height: int) -> None:
        """Bring the server + scratch ring up at ``(width, height)``.

        Either fully transitions to the new (server, ring) tuple, or
        leaves the tap in a clean torn-down state and re-raises. The
        caller must be prepared for either outcome — partial success
        is not visible from the outside, so a transient ``cudaMalloc``
        failure cannot wedge the tap (Codex blocker 2).
        """
        if (
            self._server is not None
            and self._size == (width, height)
            and self._scratch_ring
            and self._scratch_size == (width, height)
        ):
            return
        # Tear down whatever we currently hold, then build fresh.
        self._teardown_server_and_scratch()

        nbytes = width * height * 4
        new_ring: list = []
        new_server: Any = None
        try:
            for _ in range(self._ring_len):
                new_ring.append(self._cudart.malloc(nbytes))
            if self._format_fix:
                # After the allocation, which makes the CUDA context current: the kernel loads into it.
                self._load_swap_kernel()
            ovstream = self._ovstream
            new_server = ovstream.Server(self._server_type)
            cfg = ovstream.ServerConfig(
                width=_encoder_width(width),
                height=height,
                target_fps=self._fps,
                stream_port=self._media_port,
                webrtc_signal_port=self._signal_port,
                webrtc_public_ip=self._public_ip,
                **({"cuda_context": self._cuda_context, "cuda_device": self._cudart.current_device()}
                   if self._cuda_context is not None else {}),
            )
            # Step 1.4: register the connection callback BEFORE start().
            # The SDK guards its callback table with a mutex, so setting
            # after start() is technically safe — but any client connect
            # that fires between start() and the setter call lands on a
            # null pointer on the C side and is silently dropped. Setting
            # first prevents missed first-connect events.
            new_server.on_connection = self._on_connection_changed
            # Step 3.6: register Tier 3 input callbacks BEFORE start()
            # for the same reason — an input event arriving in the
            # window between ``start`` and the assignment would land on
            # a null callback pointer on the C side. The bridge knows
            # how to clamp coordinates; tell it the current extent
            # before any event can fire.
            if self._input_bridge is not None:
                try:
                    self._input_bridge.set_extents(_encoder_width(width), height)
                except Exception as exc:
                    print(
                        f"[ovgear/livestream] input bridge set_extents "
                        f"raised: {type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
                new_server.on_input = self._dispatch_input_event
                new_server.on_unicode = self._dispatch_unicode
            # Step 3.7: register the custom-message dispatcher BEFORE
            # start() for the same reason — a message arriving in the
            # window between start and a deferred assignment would
            # land on a null callback pointer on the C side.
            if self._message_dispatcher is not None:
                new_server.on_message = self._message_dispatcher.on_message
            if hasattr(type(new_server), "on_qos"):  # ovstream >= 0.5
                new_server.on_qos = self._on_qos
            new_server.start(cfg)
        except Exception:
            # Clean up partial state before propagating. Critically,
            # never publish (self._server, self._size) as ready unless
            # the ring is also ready: that's the precondition Codex
            # called out at blocker 2.
            for ptr in new_ring:
                try:
                    self._cudart.free(ptr)
                except Exception:
                    pass
            if new_server is not None:
                try:
                    new_server.stop()
                except Exception:
                    pass
                try:
                    new_server.close()
                except Exception:
                    pass
            raise
        # All steps succeeded — commit atomically.
        self._scratch_ring = new_ring
        self._scratch_size = (width, height)
        self._scratch_index = -1
        self._server = new_server
        self._size = (width, height)
        if self._trace is None:
            from ovui_data_adapters.common._stream_trace import StreamTrace

            self._trace = StreamTrace(self._fps, self._trace_directory)
        self._trace.write({"event": "server", "width": width, "height": height, "fps": self._fps,
                           "async": self._async, "protocol": self._protocol})
        if self._async:
            try:
                if not self._cuda_stream:
                    self._cuda_stream = self._cudart.create_stream()
                self._slot_events = [self._cudart.create_event() for _ in new_ring]
            except Exception as exc:
                self._async = False
                print(f"[ovgear/livestream] async pipeline unavailable ({exc}); using the synchronous tee",
                      file=sys.stderr)
        # Status atom transitions OFF → LISTENING. The on_connection
        # callback will move it to STREAMING the moment the first client
        # connects (Step 1.4).
        with self._status_lock:
            self._status_state = _STATE_LISTENING
            self._status_n_clients = 0
            self._status_last_error = None
        print(
            f"[ovgear/livestream] scratch ring allocated: {self._ring_len} buffers × "
            f"{nbytes} bytes ({width}x{height}x4)",
            file=sys.stderr,
        )
        print(
            f"[ovgear/livestream] {self._protocol} server up "
            f"(signal={self._signal_port} media={self._media_port}) "
            f"({width}x{height} @ {self._fps}fps target)",
            file=sys.stderr,
        )

    def _load_swap_kernel(self) -> None:
        """Load the R/B swap kernel; raise and latch ERROR when it cannot load.

        Every streamed frame needs the swap: without it the client shows
        red and blue exchanged. So a stream without it does not start,
        and the tap stays disabled.
        """
        try:
            _swap_kernel.warm_up()
        except Exception as exc:
            message = (
                f"R/B color correction is not available ({type(exc).__name__}: {exc}); "
                f"the stream does not start, because clients would show red and blue "
                f"exchanged. Make sure that the NVIDIA driver and its CUDA library "
                f"(libcuda or nvcuda.dll) operate"
            )
            self._disabled = True
            self._set_error_status(message)
            print(f"[ovgear/livestream] {message}", file=sys.stderr)
            raise RuntimeError(message) from exc

    def _disable_after_swap_failure(self, exc: Exception) -> None:
        """Disable the livestream leg after an R/B swap kernel failure.

        The frame is not sent: without the swap the client shows red and
        blue exchanged.
        """
        self._frames_skipped += 1
        self._disabled = True
        self._set_error_status(f"R/B swap kernel failed: {type(exc).__name__}: {exc}")
        if not self._stream_error_logged:
            print(
                f"[ovgear/livestream] R/B swap kernel failed "
                f"({type(exc).__name__}: {exc}); livestream leg disabled, "
                f"so that clients do not get red and blue exchanged",
                file=sys.stderr,
            )
            self._stream_error_logged = True
        self._maybe_report()

    # ── Public surface ──

    def tee_to_ovstream(
        self,
        mapping_tensor: Any,
        width: int,
        height: int,
    ) -> bool:
        """Push the CUDA frame to ovstream NVENC. No D2H.

        Used by the composed ``OVGEAR_ZERO_COPY=1`` + ``OVGEAR_LIVESTREAM=1``
        path: the adapter keeps the CUDA mapping alive and returns a
        ``GpuFrame`` for the GPU UI ingest, while we tee the same
        device pointer to the NVENC pipeline.

        Returns ``True`` if the frame was pushed to ovstream, ``False`` if
        it was skipped (no client, transient failure, server bring-up
        failed, or the tap is permanently disabled). Never raises —
        livestream failures are isolated from the renderer (Codex
        blocker 3).
        """
        self._tee_attempts += 1
        if self._disabled:
            self._frames_skipped += 1
            return False

        ptr = int(mapping_tensor.data)
        # Caller/layout bugs are not livestream-leg failures — surface them.
        # Accept both OVRTX's legacy vector-lane image layout and its current
        # channel-last scalar-lane layout.
        shape = _validate_rgba8_mapping_tensor(mapping_tensor, width, height)

        # NVENC requires even frame height.  When the UI layout produces
        # an odd height (e.g. 411), drop the last row rather than letting
        # the SDK silently adjust the negotiated resolution to height-1
        # and then reject every submitted frame for dimension mismatch.
        # The width is aligned the same way (``_encoder_width``).
        if height & 1:
            height -= 1

        pitch_bytes = width * 4
        nbytes = pitch_bytes * height

        if not self._first_push_logged:
            self._first_push_logged = True
            print(
                f"[ovgear/livestream] first push: cuda_ptr=0x{ptr:016x} "
                f"shape={shape} rgba8 pitch={pitch_bytes}B (zero-copy GPU→NVENC)",
                file=sys.stderr,
            )

        try:
            self._ensure_server(width, height)
        except Exception as exc:
            print(f"[ovgear/livestream] server bring-up failed: {exc}", file=sys.stderr)
            self._frames_skipped += 1
            self._maybe_report()
            return False

        # Skip the D2D entirely if no client is attached (nit 1).
        # ovstream RTSP rejects pre-connect pushes with OvstreamError
        # anyway, and the D2D is not free.
        try:
            connected = self._server.is_client_connected
        except Exception:
            connected = False
        if not connected:
            self._frames_skipped += 1
            self._maybe_report()
            return False

        # Advance ring before D2D so frame N's read by NVENC has at
        # one full scratch-ring cycle to drain before a later frame
        # writes the same buffer.
        self._scratch_index = (self._scratch_index + 1) % len(self._scratch_ring)
        scratch = self._scratch_ring[self._scratch_index]

        try:
            self._cudart.d2d(
                scratch, ptr, nbytes, src_device=_tensor_cuda_device(mapping_tensor),
            )
        except RuntimeError as exc:
            self._frames_skipped += 1
            self._set_error_status(f"D2D copy failed: {exc}")
            if not self._d2d_error_logged:
                print(f"[ovgear/livestream] D2D copy failed: {exc}", file=sys.stderr)
                self._d2d_error_logged = True
            self._maybe_report()
            return False

        # Step 1.6: in-place R/B swap on the scratch buffer between D2D
        # and stream_video. ovrtx LdrColor is RGBA8 but ovstream NVENC
        # expects BGRA8; without this the streamed frame's red and
        # blue are exchanged. The kernel runs in-place on the scratch
        # ring slot we just filled. A swap failure disables this leg
        # for the rest of the session and sends no frame.
        swap_ran = False
        if self._format_fix:
            try:
                _swap_kernel.swap_rb_in_place(
                    scratch, width, height, pitch_bytes,
                )
                swap_ran = True
            except Exception as exc:
                self._disable_after_swap_failure(exc)
                return False

        # Step 1.6 fix: block the host until the swap kernel actually
        # writes the scratch buffer. ``_swap_kernel.swap_rb_in_place``
        # uses ``cuLaunchKernel`` which is asynchronous on the device;
        # without the sync, ``Server.stream_video`` may hand NVENC a
        # buffer whose R/B swap hasn't finished, producing tearing or
        # the legacy R/B-swapped output it was meant to fix. Skip the
        # sync if the kernel didn't run (format fix off) — there is
        # nothing to wait for and ``cudaStreamSynchronize`` would
        # unnecessarily drain other CUDA work the renderer may have queued.
        if swap_ran:
            try:
                self._cudart.stream_synchronize(0)
            except RuntimeError as exc:
                # Sync failure is most likely the same illegal-address
                # or context-lost condition that would have surfaced
                # later anyway — fall through to the disable path so
                # the next frame skips the leg.
                self._frames_skipped += 1
                self._disabled = True
                self._set_error_status(
                    f"swap-stream sync failed: {type(exc).__name__}: {exc}"
                )
                if not self._stream_error_logged:
                    print(
                        f"[ovgear/livestream] swap-stream sync failed "
                        f"({type(exc).__name__}: {exc}); livestream leg "
                        f"disabled, viewport continues unaffected",
                        file=sys.stderr,
                    )
                    self._stream_error_logged = True
                self._maybe_report()
                return False

        try:
            frame = self._ovstream.VideoFrame(
                buffer=int(scratch),
                width=_encoder_width(int(width)),
                height=int(height),
                pitch_bytes=int(pitch_bytes),
            )
            self._server.stream_video(frame)
            self._frames_pushed += 1
            self._maybe_report()
            return True
        except self._ovstream.OvstreamError:
            # OvstreamError means an ovstream-internal hiccup (e.g.,
            # transient encoder hiccup, client churn). Skip this frame,
            # keep the tap live for the next.
            self._frames_skipped += 1
            self._maybe_report()
            return False
        except Exception as exc:
            # Anything else from VideoFrame()/stream_video() is treated
            # as non-recoverable for the livestream leg. The viewport
            # must not go black (Codex blocker 3): permanently disable
            # the tap and keep returning False so future frames go
            # straight through the no-op fast-path.
            self._frames_skipped += 1
            self._disabled = True
            self._set_error_status(
                f"stream_video failed: {type(exc).__name__}: {exc}"
            )
            if not self._stream_error_logged:
                print(
                    f"[ovgear/livestream] stream_video failed with non-OvstreamError "
                    f"({type(exc).__name__}: {exc}); livestream leg disabled, "
                    f"viewport continues unaffected",
                    file=sys.stderr,
                )
                self._stream_error_logged = True
            self._maybe_report()
            return False

    # ── Step 2.5: linear (pitched) scratch ring for the headless path ──

    def _ensure_linear_ring(self, width: int, height: int) -> None:
        """Bring the pitched scratch ring up at ``(width, height)``.

        Allocates ``self._ring_len`` pitched buffers via ``cudaMallocPitch``
        on first call and on resize. The driver picks a row pitch
        ``>= width*4`` and ``self._linear_pitch`` records it for the
        consumer. Either fully transitions to the new ring or leaves
        the tap in a clean state and re-raises (mirrors the failure
        atomicity of ``_ensure_server`` — Codex blocker 2).
        """
        if self._linear_ring and self._linear_size == (width, height):
            return
        # Resize — drain any in-flight encoder reads on the old ring
        # before freeing. (No-op on first init when the ring is empty.)
        self._teardown_linear_ring()

        new_ring: list = []
        new_pitch = 0
        try:
            for _ in range(self._ring_len):
                ptr, pitch = self._cudart.malloc_pitch(width * 4, height)
                new_ring.append(ptr)
                # cudaMallocPitch returns the same pitch for the same
                # (width_bytes, height) on a given device, so latching
                # the last value is fine. Track it explicitly so an
                # unexpected divergence would surface in tests.
                new_pitch = pitch
        except Exception:
            for ptr in new_ring:
                try:
                    self._cudart.free(ptr)
                except Exception:
                    pass
            raise

        self._linear_ring = new_ring
        self._linear_size = (width, height)
        self._linear_pitch = new_pitch
        self._linear_index = -1
        print(
            f"[ovgear/livestream] linear scratch ring allocated: "
            f"{self._ring_len} buffers × {width}x{height}x4 (pitch={new_pitch}B)",
            file=sys.stderr,
        )

    def acquire_linear_scratch(self, width: int, height: int) -> Tuple[int, int]:
        """Advance the pitched ring index and return ``(dev_ptr, pitch_bytes)``.

        Used by the Step-2.6 headless main-loop hook: ovui copies the
        offscreen Vulkan frame into the returned slot, the R/B swap
        kernel runs in place, and ``tee_linear_to_ovstream`` publishes
        the slot to NVENC. The ring rotates per-frame so frame N+1's
        ``copy_to_linear`` cannot stomp NVENC's still-in-flight read of
        frame N.
        """
        self._ensure_linear_ring(width, height)
        self._linear_index = (self._linear_index + 1) % len(self._linear_ring)
        return self._linear_ring[self._linear_index], self._linear_pitch

    def tee_linear_to_ovstream(
        self,
        dev_ptr: int,
        width: int,
        height: int,
        pitch_bytes: int,
    ) -> bool:
        """Publish a caller-owned pitched device buffer to ovstream NVENC.

        Used by the Step-2.6 headless composite hook. Unlike
        :meth:`tee_to_ovstream`, no D2D happens here — the caller
        already owns the device pointer (typically a slot returned by
        :meth:`acquire_linear_scratch`). Per-frame ordering inside this
        method:

        1. Bring the server up if needed (size-aware; never frees the
           linear ring as a side-effect — see
           :meth:`_teardown_server_and_scratch` docstring).
        2. Skip if no client is attached.
        3. R/B swap in place via ``_swap_kernel.swap_rb_in_place`` —
           gated by ``OVGEAR_LIVESTREAM_FORMAT_FIX`` (default on).
           ovrtx/ovui produce RGBA8 buffers but ovstream NVENC expects
           BGRA8; without this kernel the streamed frame's red and
           blue channels are exchanged.
        4. ``cudaStreamSynchronize(0)`` so NVENC reads the post-swap
           bytes, mirroring the Step-1.6 windowed-path fix
           (``cuLaunchKernel`` is async on the device — without the
           sync ``stream_video`` would race the kernel).
        5. Build ``VideoFrame(buffer, width, height, pitch_bytes)``
           and call ``server.stream_video``.

        Failure isolation matches the windowed path:

        - permanent disable (``_disabled = True``) on a non-OvstreamError
          from ``stream_video`` or on a sync failure;
        - frame-skip on ``OvstreamError`` (transient encoder hiccup);
        - permanent disable on a swap-kernel failure, with no frame
          sent (the client would show red and blue exchanged);
        - frame-skip if no client is attached.

        Returns ``True`` on a successful push, ``False`` on skip /
        disabled / error. Never raises.
        """
        if self._disabled:
            self._frames_skipped += 1
            return False

        try:
            self._ensure_server(width, height)
        except Exception as exc:
            print(
                f"[ovgear/livestream] server bring-up failed: {exc}",
                file=sys.stderr,
            )
            self._frames_skipped += 1
            self._maybe_report()
            return False

        try:
            connected = self._server.is_client_connected
        except Exception:
            connected = False
        if not connected:
            self._frames_skipped += 1
            self._maybe_report()
            return False

        # R/B swap in place on the caller-owned linear buffer. Same
        # gating + disable policy as ``tee_to_ovstream``.
        swap_ran = False
        if self._format_fix:
            try:
                _swap_kernel.swap_rb_in_place(
                    int(dev_ptr), int(width), int(height), int(pitch_bytes),
                )
                swap_ran = True
            except Exception as exc:
                self._disable_after_swap_failure(exc)
                return False

        # Block the host until the swap kernel actually writes the
        # buffer — Step 1.6 fix replicated for the linear path. If the
        # kernel didn't run (format fix off) skip the sync; there's
        # nothing to wait for and ``cudaStreamSynchronize`` would
        # unnecessarily drain unrelated CUDA work.
        if swap_ran:
            try:
                self._cudart.stream_synchronize(0)
            except RuntimeError as exc:
                self._frames_skipped += 1
                self._disabled = True
                self._set_error_status(
                    f"swap-stream sync failed: {type(exc).__name__}: {exc}"
                )
                if not self._stream_error_logged:
                    print(
                        f"[ovgear/livestream] swap-stream sync failed "
                        f"({type(exc).__name__}: {exc}); livestream leg "
                        f"disabled, viewport continues unaffected",
                        file=sys.stderr,
                    )
                    self._stream_error_logged = True
                self._maybe_report()
                return False

        try:
            frame = self._ovstream.VideoFrame(
                buffer=int(dev_ptr),
                width=_encoder_width(int(width)),
                height=int(height),
                pitch_bytes=int(pitch_bytes),
            )
            self._server.stream_video(frame)
            self._frames_pushed += 1
            self._maybe_report()
            return True
        except self._ovstream.OvstreamError:
            # Transient encoder hiccup or client churn — skip this frame,
            # keep the tap live for the next.
            self._frames_skipped += 1
            self._maybe_report()
            return False
        except Exception as exc:
            self._frames_skipped += 1
            self._disabled = True
            self._set_error_status(
                f"stream_video failed: {type(exc).__name__}: {exc}"
            )
            if not self._stream_error_logged:
                print(
                    f"[ovgear/livestream] stream_video (linear) failed with "
                    f"non-OvstreamError ({type(exc).__name__}: {exc}); "
                    f"livestream leg disabled, viewport continues unaffected",
                    file=sys.stderr,
                )
                self._stream_error_logged = True
            self._maybe_report()
            return False

    @property
    def perf(self) -> Optional[dict]:
        """Stream performance: the last per-second summary, totals, QoS and the trace log path."""
        return self._trace.snapshot() if self._trace is not None else None

    def _on_qos(self, status: Any) -> None:
        if self._trace is not None:
            self._trace.on_qos(status)

    @property
    def async_enabled(self) -> bool:
        """Whether frames go through :meth:`tee_async` (the caller maps on :attr:`cuda_stream`)."""
        return self._async and not self._disabled and not self._closed

    @property
    def cuda_stream(self) -> int:
        """The tap's CUDA stream; map the renderer output with ``sync_stream`` set to it."""
        if not self._cuda_stream:
            self._cuda_stream = self._cudart.create_stream()
        return self._cuda_stream

    @property
    def repeated_frames(self) -> int:
        """Ticks on which the publisher re-sent the last frame (no new frame was ready)."""
        return self._publisher.repeated_frames if self._publisher else 0

    def tee_async(self, mapping_tensor: Any, width: int, height: int, index: int = 0,
                  frames: int = 1) -> Optional[int]:
        """Queue this frame for the stream without waiting for it on the host.

        The caller mapped the render output with ``sync_stream=self.cuda_stream``, so the copy below
        runs after the render completes. It swizzles RGBA to BGRA into a scratch slot in one kernel
        and records the slot's event; the publish thread sends it. Returns the event, which the
        caller passes to ``mapping.unmap(event=...)`` so the renderer keeps its buffer until the copy
        has read it, or ``None`` when nothing was queued (no client, failure): unmap normally then.
        """
        self._tee_attempts += 1
        if not self.async_enabled:
            return None
        shape = _validate_rgba8_mapping_tensor(mapping_tensor, width, height)
        if height & 1:
            height -= 1
        try:
            self._ensure_server(width, height)
        except Exception as exc:
            print(f"[ovgear/livestream] server bring-up failed: {exc}", file=sys.stderr)
            self._frames_skipped += 1
            return None
        try:
            connected = self._server.is_client_connected
        except Exception:
            connected = False
        if not connected:
            self._frames_skipped += 1
            self._maybe_report()
            return None
        if self._publisher is None:
            # Started with the first frame for a client, not with the server: a tap that never
            # streams (or is never closed) must not keep a thread running.
            self._publisher = _Publisher(self, self._fps)
        busy = self._publisher.busy_slots()
        for _ in range(len(self._scratch_ring)):
            self._scratch_index = (self._scratch_index + 1) % len(self._scratch_ring)
            if self._scratch_index not in busy:
                break
        else:
            self._frames_skipped += 1
            return None
        slot = self._scratch_index
        pitch = width * 4
        try:
            _swap_kernel.copy_swap_rb(
                int(mapping_tensor.data), pitch, self._scratch_ring[slot], pitch,
                width, height, stream=self._cuda_stream,
            )
            event = self._slot_events[slot]
            self._cudart.record_event(event, self._cuda_stream)
        except Exception as exc:
            self._async = False
            self._frames_skipped += 1
            self._set_error_status(f"async copy failed: {type(exc).__name__}: {exc}")
            print(f"[ovgear/livestream] async copy failed ({exc}); using the synchronous tee",
                  file=sys.stderr)
            return None
        if not self._first_push_logged:
            self._first_push_logged = True
            print(f"[ovgear/livestream] first async push: shape={shape} rgba8 pitch={pitch}B "
                  f"(copy+swizzle on the tap stream, event-synchronized submit)", file=sys.stderr)
        self._seq += 1
        produced = time.perf_counter()
        if self._trace is not None:
            self._trace.produced(self._seq, produced, index, frames)
        # Frame generation: the step's frames are presented one stream period apart, in order.
        self._publisher.post(slot, event, width, height, self._seq, produced, index / max(1, self._fps))
        self._maybe_report()
        return event

    def _publish(self, frame: Tuple[int, int, int, int], fresh: bool) -> bool:
        """Publish thread: submit one queued slot. Never raises."""
        slot, event, width, height, _seq, produced, _offset = frame
        server = self._server
        if server is None or slot >= len(self._scratch_ring):
            return False
        try:
            # Wait for the copy here (ctypes releases the GIL), then submit a ready buffer: the
            # submit's own staging copy is then not queued behind this frame's render.
            started = time.perf_counter()
            self._cudart.event_synchronize(event)
            waited = time.perf_counter()
            stamps = {}
            if _timestamps_enabled() and self._trace is not None:
                # Capture start (frame produced) and end (copy complete), wall-clock ns.
                stamps = {"start_timestamp_ns": int(self._trace.wall(produced) * 1e9),
                          "ended_timestamp_ns": time.time_ns()}
            video = self._ovstream.VideoFrame(
                buffer=int(self._scratch_ring[slot]),
                width=_encoder_width(int(width)),
                height=int(height),
                pitch_bytes=int(width) * 4,
                **stamps,
            )
            server.stream_video(video)
            publisher = self._publisher
            if publisher is not None:
                publisher.wait_seconds += waited - started
                publisher.call_seconds += time.perf_counter() - waited
            if fresh:
                self._frames_pushed += 1
            return True
        except self._ovstream.OvstreamError:
            self._frames_skipped += 1
            return False
        except Exception as exc:
            self._frames_skipped += 1
            self._set_error_status(f"stream_video failed: {type(exc).__name__}: {exc}")
            if not self._stream_error_logged:
                print(f"[ovgear/livestream] async stream_video failed ({type(exc).__name__}: {exc})",
                      file=sys.stderr)
                self._stream_error_logged = True
            return False

    def tee_and_d2h(
        self,
        mapping_tensor: Any,
        width: int,
        height: int,
        host_buf: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """Tee the CUDA frame to ovstream (best effort) AND D2H-copy for
        the UI consumer. Returns a host numpy ``(H, W, 4)`` uint8 array.

        Used by the livestream-only path (``OVGEAR_LIVESTREAM=1`` with
        ``OVGEAR_ZERO_COPY`` unset). The ovstream leg is allowed to fail
        without affecting the UI leg — this method always returns a
        host buffer (Codex blocker 3); a transient failure on the
        ovstream side never propagates to the adapter.
        """
        # ovstream leg — fully exception-safe, never raises out.
        try:
            self.tee_to_ovstream(mapping_tensor, width, height)
        except ValueError:
            raise  # caller bug, surface it
        except Exception as exc:
            # Belt-and-suspenders: tee_to_ovstream is supposed to be
            # exception-safe but if anything escapes, isolate it.
            self._disabled = True
            self._set_error_status(
                f"tee_to_ovstream escaped: {type(exc).__name__}: {exc}"
            )
            if not self._stream_error_logged:
                print(
                    f"[ovgear/livestream] tee_to_ovstream escaped exception "
                    f"({type(exc).__name__}: {exc}); livestream disabled",
                    file=sys.stderr,
                )
                self._stream_error_logged = True

        # UI leg — D2H always runs so the viewport keeps rendering.
        ptr = int(mapping_tensor.data)
        nbytes = width * height * 4
        if host_buf is None or host_buf.shape != (height, width, 4) or host_buf.dtype != np.uint8:
            host_buf = np.empty((height, width, 4), dtype=np.uint8)
        try:
            self._cudart.d2h(
                host_buf, ptr, nbytes, device=_tensor_cuda_device(mapping_tensor),
            )
        except RuntimeError as exc:
            # CUDA-level failure on the UI leg is a real renderer
            # problem; black the frame rather than leaking the
            # exception (the adapter would just turn it black anyway).
            print(f"[ovgear/livestream] D2H failed: {exc}", file=sys.stderr)
            self._set_error_status(f"D2H readback failed: {exc}")
            host_buf.fill(0)

        return host_buf

    def _maybe_report(self) -> None:
        now = time.monotonic()
        if now - self._last_report_t >= 5.0:
            wall = now - self._t0
            pps = self._frames_pushed / max(wall, 1e-6)
            print(
                f"[ovgear/livestream] {self._frames_pushed} frames pushed "
                f"({pps:.1f} fps) skipped={self._frames_skipped} "
                f"disabled={self._disabled}",
                file=sys.stderr,
            )
            self._last_report_t = now

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_count += 1
        self._teardown_server_and_scratch()
        self._teardown_linear_ring()
        if self._trace is not None:
            self._trace.close()
        if self._cuda_stream:
            try:
                self._cudart.destroy_stream(self._cuda_stream)
            except Exception:
                pass
            self._cuda_stream = 0
        if self._manage_sdk:
            try:
                self._ovstream.shutdown()
            except Exception:
                pass

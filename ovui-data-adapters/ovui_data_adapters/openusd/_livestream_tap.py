# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovstream livestream tap — opt-in tee from ovrtx LdrColor to ovstream RTSP.

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
* Format note: ovrtx LdrColor is RGBA8, ovstream expects BGRA8. We
  feed the RGBA buffer as-is and the resulting RTSP stream has R/B
  swapped — a known cosmetic gap. A GPU swap (e.g., a Warp kernel) is
  a follow-up.

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

from ovui_data_adapters.openusd import _swap_kernel

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
_DEFAULT_RING_LEN = 8
_MAX_RING_LEN = 64


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

    @staticmethod
    def _load_libcudart() -> Any:
        last_exc: Optional[OSError] = None
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

    def d2h(self, host: np.ndarray, device_ptr: int, nbytes: int) -> None:
        rc = self._lib.cudaMemcpy(
            host.ctypes.data_as(ctypes.c_void_p),
            ctypes.c_void_p(device_ptr),
            nbytes,
            self.D2H,
        )
        if rc != 0:
            raise RuntimeError(f"cudaMemcpy D2H failed rc={rc}")

    def d2d(self, dst_ptr: int, src_ptr: int, nbytes: int) -> None:
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

    def __init__(self) -> None:
        import ovstream
        self._ovstream = ovstream
        self._cudart = _Cudart()

        signal_port, media_port = _resolve_ports()
        fps = int(os.environ.get("OVGEAR_LIVESTREAM_FPS", "30"))
        protocol_raw = os.environ.get(_PROTOCOL_ENV_VAR, _DEFAULT_PROTOCOL)
        # `webrtc_public_ip` is an Optional[str] on ServerConfig; pass
        # the env value through verbatim, or None if unset. Setting this
        # disables ICE on the SDK side and pins the announced IP — the
        # right knob for non-localhost demos behind a fixed router.
        public_ip = os.environ.get(_PUBLIC_IP_ENV_VAR) or None
        self._signal_port = signal_port
        self._media_port = media_port
        self._fps = fps
        self._protocol = protocol_raw
        self._server_type = _resolve_server_type(ovstream, protocol_raw)
        self._public_ip = public_ip
        self._ring_len = _resolve_buffer_ring_len()
        # Step 1.6: gate the R/B swap kernel. Default ON.
        self._format_fix = _format_fix_enabled()
        # Set to True if a CudaSwapError surfaces from the kernel; the
        # rest of the session falls back to no-swap so the stream
        # keeps flowing (cosmetically wrong is better than dark).
        self._swap_disabled = False
        self._swap_error_logged = False

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
        try:
            ovstream.initialize(log_fn=self._log)
        except Exception:
            pass

        self._server: Any = None
        self._size: Tuple[int, int] = (0, 0)
        # Tier 3 input bridge (issue #34, Step 3.6). When set via
        # :meth:`set_input_bridge`, ``_ensure_server`` registers the
        # ``on_input`` / ``on_unicode`` / ``on_connection`` callbacks
        # on the ovstream :class:`Server` so remote keyboard/mouse
        # events feed the bridge before ``server.start(cfg)`` is
        # called (a connect that fires between ``start`` and a later
        # callback assignment lands on a null pointer on the C side
        # and is silently dropped — same lesson as Step 1.4).
        self._input_bridge: Any = None
        # Tier 3 custom-message dispatcher (issue #34, Step 3.7).
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

        self._first_push_logged = False
        self._d2d_error_logged = False
        self._stream_error_logged = False
        self._frames_pushed = 0
        self._frames_skipped = 0
        self._t0 = time.monotonic()
        self._last_report_t = self._t0

    @staticmethod
    def _log(level: Any, channel: bytes, msg: bytes) -> None:
        # ovstream callback: level is a LogLevel enum, channel/msg are bytes.
        try:
            print(f"[ovstream/{level.name}/{channel}] {msg}", file=sys.stderr)
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
        if self._server is not None:
            try:
                self._server.stop()
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
            ovstream = self._ovstream
            new_server = ovstream.Server(self._server_type)
            cfg = ovstream.ServerConfig(
                width=width,
                height=height,
                target_fps=self._fps,
                stream_port=self._media_port,
                webrtc_signal_port=self._signal_port,
                webrtc_public_ip=self._public_ip,
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
                    self._input_bridge.set_extents(width, height)
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
        # Status atom transitions OFF → LISTENING. The on_connection
        # callback will move it to STREAMING the moment the first client
        # connects (Step 1.4).
        with self._status_lock:
            self._status_state = _STATE_LISTENING
            self._status_n_clients = 0
            self._status_last_error = None
        # Step 1.5/1.6: warm the NVRTC compile NOW so the first streamed
        # frame doesn't pay the ~50-200 ms JIT cost. A warm-up failure
        # disables only the format fix, not the whole tap — a cosmetic
        # R/B-swapped stream is better than no stream.
        if self._format_fix and not self._swap_disabled:
            try:
                _swap_kernel.warm_up()
            except Exception as exc:
                self._swap_disabled = True
                if not self._swap_error_logged:
                    print(
                        f"[ovgear/livestream] R/B swap kernel warm-up "
                        f"failed ({type(exc).__name__}: {exc}); falling "
                        f"back to legacy R/B-swapped stream",
                        file=sys.stderr,
                    )
                    self._swap_error_logged = True
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
        if self._disabled:
            self._frames_skipped += 1
            return False

        ptr = int(mapping_tensor.data)
        shape = tuple(mapping_tensor.shape)
        if shape != (height, width):
            # Caller bug, not a livestream-leg error — surface it.
            raise ValueError(f"Unexpected ovrtx shape {shape} for {width}x{height}")

        # NVENC requires even frame height.  When the UI layout produces
        # an odd height (e.g. 411), drop the last row rather than letting
        # the SDK silently adjust the negotiated resolution to height-1
        # and then reject every submitted frame for dimension mismatch.
        if height & 1:
            height -= 1

        pitch_bytes = width * 4
        nbytes = pitch_bytes * height

        if not self._first_push_logged:
            self._first_push_logged = True
            print(
                f"[ovgear/livestream] first push: cuda_ptr=0x{ptr:016x} "
                f"shape={shape}+uint8x4 pitch={pitch_bytes}B (zero-copy GPU→NVENC)",
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
            self._cudart.d2d(scratch, ptr, nbytes)
        except RuntimeError as exc:
            self._frames_skipped += 1
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
        # for the rest of the session and falls back to the legacy
        # R/B-swapped stream — cosmetic regression beats dark stream.
        swap_ran = False
        if self._format_fix and not self._swap_disabled:
            try:
                _swap_kernel.swap_rb_in_place(
                    scratch, width, height, pitch_bytes,
                )
                swap_ran = True
            except Exception as exc:
                self._swap_disabled = True
                if not self._swap_error_logged:
                    print(
                        f"[ovgear/livestream] R/B swap kernel failed "
                        f"({type(exc).__name__}: {exc}); falling back "
                        f"to legacy R/B-swapped stream",
                        file=sys.stderr,
                    )
                    self._swap_error_logged = True

        # Step 1.6 fix: block the host until the swap kernel actually
        # writes the scratch buffer. ``_swap_kernel.swap_rb_in_place``
        # uses ``cuLaunchKernel`` which is asynchronous on the device;
        # without the sync, ``Server.stream_video`` may hand NVENC a
        # buffer whose R/B swap hasn't finished, producing tearing or
        # the legacy R/B-swapped output it was meant to fix. Skip the
        # sync if the kernel didn't run (format fix off, or kernel
        # error already logged) — there is nothing to wait for and
        # ``cudaStreamSynchronize`` would unnecessarily drain other
        # CUDA work the renderer may have queued.
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
                width=int(width),
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
        - swap-kernel failure disables only the format fix (legacy
          R/B-swapped stream is better than dark stream);
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
        if self._format_fix and not self._swap_disabled:
            try:
                _swap_kernel.swap_rb_in_place(
                    int(dev_ptr), int(width), int(height), int(pitch_bytes),
                )
                swap_ran = True
            except Exception as exc:
                self._swap_disabled = True
                if not self._swap_error_logged:
                    print(
                        f"[ovgear/livestream] R/B swap kernel failed "
                        f"({type(exc).__name__}: {exc}); falling back "
                        f"to legacy R/B-swapped stream",
                        file=sys.stderr,
                    )
                    self._swap_error_logged = True

        # Block the host until the swap kernel actually writes the
        # buffer — Step 1.6 fix replicated for the linear path. If the
        # kernel didn't run (format fix off / swap disabled) skip the
        # sync; there's nothing to wait for and ``cudaStreamSynchronize``
        # would unnecessarily drain unrelated CUDA work.
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
                width=int(width),
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
            self._cudart.d2h(host_buf, ptr, nbytes)
        except RuntimeError as exc:
            # CUDA-level failure on the UI leg is a real renderer
            # problem; black the frame rather than leaking the
            # exception (the adapter would just turn it black anyway).
            print(f"[ovgear/livestream] D2H failed: {exc}", file=sys.stderr)
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
        self._teardown_server_and_scratch()
        self._teardown_linear_ring()
        try:
            self._ovstream.shutdown()
        except Exception:
            pass

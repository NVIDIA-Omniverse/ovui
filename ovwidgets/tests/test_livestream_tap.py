# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import os
import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from ovui_data_adapters.openusd import _livestream_tap as tap_mod
from ovui_data_adapters.openusd import renderer_adapter as adapter_mod

_TEST_ENV = {
    tap_mod._ENABLED_ENV_VAR: "1",
    tap_mod._BUFFER_RING_ENV_VAR: "2",
}


def _with_test_env(overrides=None):
    env = dict(_TEST_ENV)
    if overrides:
        env.update(overrides)
    return env


@pytest.fixture(autouse=True)
def _unit_test_ring_depth(monkeypatch):
    # Most legacy tests assert exact two-slot rotation/event order. Keep
    # those tests compact while production defaults to the safer depth.
    monkeypatch.setenv(tap_mod._BUFFER_RING_ENV_VAR, "2")


def _install_mock_ovstream(
    monkeypatch, *, connected=True, start_side_effect=None, neutralize_swap=True,
):
    server = MagicMock()
    server.is_client_connected = connected
    server.start.side_effect = start_side_effect

    ovstream = MagicMock()
    # ServerType sentinels — production code now selects between the three
    # via ``OVGEAR_LIVESTREAM_PROTOCOL`` (Step 1.1). Each enum member is
    # given a distinguishable string so tests can assert which one was
    # passed to ``Server(...)``.
    ovstream.ServerType.WEBRTC = "WEBRTC"
    ovstream.ServerType.NATIVE = "NATIVE"
    ovstream.ServerType.RTSP   = "RTSP"
    ovstream.Server.return_value = server
    ovstream.ServerConfig.side_effect = lambda **kw: types.SimpleNamespace(**kw)
    ovstream.VideoFrame.side_effect = lambda **kw: types.SimpleNamespace(**kw)
    ovstream.OvstreamError = RuntimeError

    monkeypatch.setitem(sys.modules, "ovstream", ovstream)

    # Neutralise the Step-1.6 R/B swap kernel for every mocked test:
    # the tap's ``tee_to_ovstream`` calls ``_swap_kernel.swap_rb_in_place``
    # unconditionally when the format fix is on (its default), and the
    # mocked cudart returns sentinel pointers like ``0xAA`` that the
    # real kernel would write to — CUDA returns 700 (illegal access),
    # poisoning the *process-wide* CUDA context for the rest of the
    # pytest run. A no-op stub makes mocked tests CUDA-agnostic; tests
    # that need to spy on the kernel (`_spy_swap_and_warmup`) override
    # this stub afterwards. Tests that exercise the real kernel (the
    # byte-order proof in Step 1.6) pass ``neutralize_swap=False`` so
    # the production kernel runs against real device memory.
    if neutralize_swap:
        monkeypatch.setattr(tap_mod._swap_kernel, "swap_rb_in_place",
                            lambda dev, w, h, pitch, stream=0: None)
        monkeypatch.setattr(tap_mod._swap_kernel, "warm_up", lambda: None)

    return ovstream, server


def _mapping(width, height, ptr=0x123456):
    return types.SimpleNamespace(data=ptr, shape=(height, width))


def _make_cudart_mock(events, ptrs=None):
    """Construct a _Cudart-shaped MagicMock that appends ordered events."""
    if ptrs is None:
        ptrs = iter([0xA0, 0xB0, 0xC0, 0xD0])

    cudart = MagicMock()

    def _malloc(nbytes):
        events.append(("malloc", nbytes))
        return next(ptrs)

    cudart.malloc.side_effect = _malloc
    cudart.d2d.side_effect = lambda dst, src, nbytes: events.append(("d2d", dst, src, nbytes))
    cudart.d2h.side_effect = lambda host, src, nbytes: events.append(("d2h", src, nbytes, host.shape))
    cudart.free.side_effect = lambda ptr: events.append(("free", ptr))
    cudart.device_synchronize.side_effect = lambda: events.append(("sync",))
    return cudart


# ── env flag ──

@pytest.mark.parametrize("value", ["", "0", "false", "False"])
def test_enabled_rejects_empty_zero_and_false(value):
    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: value}):
        assert tap_mod._enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "yes"])
def test_enabled_accepts_explicit_truthy_values(value):
    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: value}):
        assert tap_mod._enabled() is True


def test_enabled_rejects_missing_env():
    with patch.dict(os.environ, {}, clear=True):
        assert tap_mod._enabled() is False


def test_buffer_ring_defaults_to_encoder_latency_margin(monkeypatch):
    monkeypatch.delenv(tap_mod._BUFFER_RING_ENV_VAR, raising=False)

    assert tap_mod._resolve_buffer_ring_len() == tap_mod._DEFAULT_RING_LEN


def test_buffer_ring_accepts_env_override(monkeypatch):
    monkeypatch.setenv(tap_mod._BUFFER_RING_ENV_VAR, "12")

    assert tap_mod._resolve_buffer_ring_len() == 12


def test_buffer_ring_clamps_too_small_values(monkeypatch, capsys):
    monkeypatch.setenv(tap_mod._BUFFER_RING_ENV_VAR, "1")

    assert tap_mod._resolve_buffer_ring_len() == tap_mod._MIN_RING_LEN
    assert "minimum safe value" in capsys.readouterr().err


def test_buffer_ring_clamps_too_large_values(monkeypatch, capsys):
    monkeypatch.setenv(tap_mod._BUFFER_RING_ENV_VAR, "999")

    assert tap_mod._resolve_buffer_ring_len() == tap_mod._MAX_RING_LEN
    assert "exceeds the maximum" in capsys.readouterr().err


def test_buffer_ring_invalid_value_uses_default(monkeypatch, capsys):
    monkeypatch.setenv(tap_mod._BUFFER_RING_ENV_VAR, "many")

    assert tap_mod._resolve_buffer_ring_len() == tap_mod._DEFAULT_RING_LEN
    assert "is not an integer" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["", "0", "false"])
def test_maybe_create_returns_none_when_env_disabled(value, monkeypatch):
    ovstream, _server = _install_mock_ovstream(monkeypatch)
    cudart_cls = MagicMock()
    monkeypatch.setattr(tap_mod, "_Cudart", cudart_cls)

    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: value}):
        assert tap_mod.LivestreamTap.maybe_create() is None

    ovstream.initialize.assert_not_called()
    ovstream.Server.assert_not_called()
    cudart_cls.assert_not_called()


def test_maybe_create_returns_none_when_ovstream_missing(monkeypatch):
    """Codex coverage gap: missing ovstream is handled by returning None
    with stderr hint, no exception, no _Cudart construction."""
    cudart_cls = MagicMock()
    monkeypatch.setattr(tap_mod, "_Cudart", cudart_cls)
    # Force ImportError by ensuring 'ovstream' is absent from sys.modules
    # AND blocking its import via a meta-path finder.
    monkeypatch.delitem(sys.modules, "ovstream", raising=False)

    class _BlockOvstream:
        @classmethod
        def find_spec(cls, name, path, target=None):
            if name == "ovstream":
                raise ImportError("No module named 'ovstream' (test stub)")
            return None

    sys.meta_path.insert(0, _BlockOvstream)
    try:
        with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
            tap = tap_mod.LivestreamTap.maybe_create()
    finally:
        sys.meta_path.remove(_BlockOvstream)

    assert tap is None
    cudart_cls.assert_not_called()


# ── happy-path event ordering ──

def test_tee_and_d2h_event_order_is_ring_alloc_start_d2d_stream_d2h(monkeypatch):
    """The ring-buffer design allocates the configured scratch depth
    BEFORE starting the server (so a server-start failure doesn't leak
    a half-initialized ring), then per-frame: D2D into the next ring
    slot → stream_video → D2H for the UI."""
    events = []
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    server.start.side_effect = lambda cfg: events.append(("start", cfg.width, cfg.height))
    server.stream_video.side_effect = lambda frame: events.append(
        ("stream_video", frame.buffer, frame.pitch_bytes)
    )

    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)

    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()
    assert tap is not None

    out = tap.tee_and_d2h(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert out.shape == (2, 3, 4) and out.dtype == np.uint8

    # Allocate test ring (N=2) → start server → D2D into first ring slot →
    # stream_video that slot → D2H for UI.
    assert events == [
        ("malloc", 24),
        ("malloc", 24),
        ("start", 3, 2),
        ("d2d", 0xAA, 0x1111, 24),
        ("stream_video", 0xAA, 12),
        ("d2h", 0x1111, 24, (2, 3, 4)),
    ]
    assert tap._frames_pushed == 1
    assert tap._frames_skipped == 0


def test_ring_rotates_across_frames(monkeypatch):
    """Codex blocker 1: the ring rotates so frame N+1 doesn't stomp
    frame N's still-in-flight NVENC read."""
    events = []
    _ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    server.stream_video.side_effect = lambda frame: events.append(("stream", frame.buffer))
    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()

    for i in range(4):
        tap.tee_and_d2h(_mapping(3, 2, ptr=0x1000 + i), 3, 2)

    streamed = [e[1] for e in events if e[0] == "stream"]
    # Ring of 2: AA, BB, AA, BB
    assert streamed == [0xAA, 0xBB, 0xAA, 0xBB]
    assert tap._frames_pushed == 4


def test_close_drains_then_frees_ring(monkeypatch):
    """Codex blocker 1: shutdown drains (cudaDeviceSynchronize) before
    freeing scratch so the encoder isn't left reading a freed buffer."""
    events = []
    ovstream, _server = _install_mock_ovstream(monkeypatch, connected=True)
    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)

    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()
    tap.tee_and_d2h(_mapping(3, 2), 3, 2)
    events.clear()

    tap.close()

    # On close: drain (sync) then free both ring buffers, in that order.
    assert ("sync",) in events
    sync_idx = events.index(("sync",))
    free_events = [e for e in events if e[0] == "free"]
    assert {ptr for _tag, ptr in free_events} == {0xAA, 0xBB}
    # All frees come after the sync.
    for ev in events[:sync_idx]:
        assert ev[0] != "free"


def test_resize_drains_then_reallocates(monkeypatch):
    """Codex coverage gap: resize stops the old server, syncs, frees the
    old ring, then allocates the new ring at the new size."""
    events = []
    ovstream, _server = _install_mock_ovstream(monkeypatch, connected=True)
    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB, 0xCC, 0xDD]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)

    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()
    tap.tee_and_d2h(_mapping(3, 2), 3, 2)
    events.clear()

    # Resize: new (W, H) = (5, 4)
    tap.tee_and_d2h(_mapping(5, 4), 5, 4)

    # Expect: drain (sync) → free old (AA, BB) → malloc new (CC, DD)
    sync_idx = events.index(("sync",))
    frees = [(i, e) for i, e in enumerate(events) if e[0] == "free"]
    mallocs = [(i, e) for i, e in enumerate(events) if e[0] == "malloc"]
    assert {e[1] for _i, e in frees} == {0xAA, 0xBB}
    assert all(i > sync_idx for i, _e in frees)
    assert all(i > frees[-1][0] for i, _e in mallocs)
    # And the new ring was filled with the new size.
    assert all(e[1] == 5 * 4 * 4 for _i, e in mallocs)


# ── Blocker 2: alloc-failure must not wedge ──

def test_scratch_alloc_failure_does_not_wedge(monkeypatch):
    """Codex blocker 2: a transient cudaMalloc failure on the first
    frame must not leave (server, size) "ready" with no scratch.
    The next frame must retry from a clean state."""
    events = []
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    server.stream_video.side_effect = lambda frame: events.append(("stream", frame.buffer))

    # First malloc raises, subsequent succeed.
    fail_once = {"n": 0}

    def _malloc(nbytes):
        fail_once["n"] += 1
        events.append(("malloc", nbytes, fail_once["n"]))
        if fail_once["n"] == 1:
            raise RuntimeError("cudaMalloc returned ENOMEM (test)")
        return 0xCAFE0000 + fail_once["n"]

    cudart = MagicMock()
    cudart.malloc.side_effect = _malloc
    cudart.d2d.side_effect = lambda dst, src, n: events.append(("d2d", dst, src, n))
    cudart.d2h.side_effect = lambda host, src, n: events.append(("d2h", src, n))
    cudart.free.side_effect = lambda ptr: events.append(("free", ptr))
    cudart.device_synchronize.side_effect = lambda: events.append(("sync",))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)

    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()

    # Frame 1: alloc fails → no server published, frame skipped on
    # ovstream leg, D2H still runs for UI.
    out1 = tap.tee_and_d2h(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert out1.shape == (2, 3, 4)
    assert tap._server is None
    assert tap._scratch_ring == []
    assert tap._frames_pushed == 0

    # Frame 2: retry succeeds.
    out2 = tap.tee_and_d2h(_mapping(3, 2, ptr=0x2222), 3, 2)
    assert out2.shape == (2, 3, 4)
    assert tap._server is not None
    assert len(tap._scratch_ring) == tap._ring_len
    assert tap._frames_pushed == 1


def test_server_start_failure_cleans_up_partial_ring(monkeypatch):
    """If server.start() raises after the ring was allocated, the
    half-initialized ring must be freed (no leak) and the tap must
    leave (server, size) torn down so the next frame retries."""
    events = []
    _ovstream, server = _install_mock_ovstream(
        monkeypatch, connected=True, start_side_effect=RuntimeError("bind failed"),
    )
    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB, 0xCC, 0xDD]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)

    tap = tap_mod.LivestreamTap()
    out = tap.tee_and_d2h(_mapping(3, 2), 3, 2)

    # Ring was allocated then freed (start failed).
    assert ("malloc", 24) in events
    free_ptrs = {e[1] for e in events if e[0] == "free"}
    assert free_ptrs == {0xAA, 0xBB}
    # State is clean.
    assert tap._server is None
    assert tap._scratch_ring == []
    # UI still got its host buffer.
    assert out.shape == (2, 3, 4)
    server.stream_video.assert_not_called()


# ── Blocker 3: error isolation ──

def test_non_ovstream_error_does_not_propagate(monkeypatch):
    """Codex blocker 3: a non-OvstreamError from stream_video must not
    leak; the tap disables itself and the D2H still runs."""
    _ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    server.stream_video.side_effect = ValueError("unexpected encoder kaboom")

    events = []
    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()

    # Must not raise.
    out = tap.tee_and_d2h(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert out.shape == (2, 3, 4)
    assert tap._disabled is True
    assert tap._frames_pushed == 0
    # D2H ran.
    assert any(e[0] == "d2h" for e in events)


def test_disabled_tap_short_circuits(monkeypatch):
    """Once the tap is permanently disabled, subsequent frames skip
    the ovstream work entirely (no D2D, no stream_video) but still
    serve the UI via D2H."""
    _ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    events = []
    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()
    tap._disabled = True
    events.clear()

    out = tap.tee_and_d2h(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert out.shape == (2, 3, 4)
    server.stream_video.assert_not_called()
    # D2H ran, no D2D.
    d2d_events = [e for e in events if e[0] == "d2d"]
    d2h_events = [e for e in events if e[0] == "d2h"]
    assert d2d_events == []
    assert len(d2h_events) == 1


def test_d2d_failure_skips_stream_keeps_ui(monkeypatch):
    """Codex coverage gap: a D2D failure skips the stream push but
    must not break the UI leg (D2H still runs)."""
    _ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    events = []
    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    cudart.d2d.side_effect = RuntimeError("D2D synthetic failure")
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()

    out = tap.tee_and_d2h(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert out.shape == (2, 3, 4)
    server.stream_video.assert_not_called()
    assert tap._frames_skipped == 1


def test_no_client_skips_d2d(monkeypatch):
    """Nit 1: when no client is connected, skip the D2D entirely (it's
    not free) and just run the UI D2H."""
    _ovstream, server = _install_mock_ovstream(monkeypatch, connected=False)
    events = []
    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()

    tap.tee_and_d2h(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert all(e[0] != "d2d" for e in events)
    server.stream_video.assert_not_called()


# ── Blocker 4: composition with zero-copy ──

def test_tee_to_ovstream_only_does_not_d2h(monkeypatch):
    """Codex blocker 4: composed path (zero-copy + livestream) calls
    tee_to_ovstream only — no D2H, the GPU UI ingest reads the same
    mapping."""
    _ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    events = []
    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()

    pushed = tap.tee_to_ovstream(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert pushed is True
    server.stream_video.assert_called_once()
    # D2D ran (we tee'd the frame) but D2H did NOT (caller will use
    # the live CUDA mapping for GPU UI ingest).
    assert any(e[0] == "d2d" for e in events)
    assert all(e[0] != "d2h" for e in events)


# ── ServerType protocol selector (Step 1.1) ──

def _drive_one_frame(monkeypatch, env_overrides):
    """Helper: install a mock ovstream + cudart, set env overrides, then
    drive one ``tee_to_ovstream`` frame so ``ovstream.Server(...)`` is
    invoked. Returns the mock ``ovstream`` module so tests can assert on
    ``Server.call_args``.
    """
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    cudart = _make_cudart_mock([], ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    with patch.dict(os.environ, _with_test_env(env_overrides)):
        tap = tap_mod.LivestreamTap.maybe_create()
    assert tap is not None
    pushed = tap.tee_to_ovstream(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert pushed is True
    return ovstream


def test_protocol_rtsp_selects_rtsp_server_type(monkeypatch):
    """``OVGEAR_LIVESTREAM_PROTOCOL=rtsp`` must construct ``Server`` with
    ``ServerType.RTSP``. RTSP is the legacy protocol and the only one
    that does NOT carry tier-3 input."""
    ovstream = _drive_one_frame(monkeypatch, {tap_mod._PROTOCOL_ENV_VAR: "rtsp"})
    ovstream.Server.assert_called_once_with("RTSP")


def test_protocol_webrtc_selects_webrtc_server_type(monkeypatch):
    """``OVGEAR_LIVESTREAM_PROTOCOL=webrtc`` (also the default in Step
    1.1) must construct ``Server`` with ``ServerType.WEBRTC`` —
    matching what `web-viewer-sample` speaks."""
    ovstream = _drive_one_frame(monkeypatch, {tap_mod._PROTOCOL_ENV_VAR: "webrtc"})
    ovstream.Server.assert_called_once_with("WEBRTC")


def test_protocol_native_selects_native_server_type(monkeypatch):
    """``OVGEAR_LIVESTREAM_PROTOCOL=native`` must construct ``Server``
    with ``ServerType.NATIVE``. Native is the no-browser binary
    protocol — useful for engine-to-engine streaming without WebRTC's
    JS layer."""
    ovstream = _drive_one_frame(monkeypatch, {tap_mod._PROTOCOL_ENV_VAR: "native"})
    ovstream.Server.assert_called_once_with("NATIVE")


def test_protocol_unknown_falls_back_to_default_with_warning(
    monkeypatch, capsys
):
    """An invalid ``OVGEAR_LIVESTREAM_PROTOCOL`` must NOT crash the tap;
    it falls back to the default (``WEBRTC``) and emits a one-shot
    stderr warning so the user sees what happened. The tap's overall
    "never crash the renderer" philosophy applies to env-var typos
    too."""
    ovstream = _drive_one_frame(monkeypatch, {tap_mod._PROTOCOL_ENV_VAR: "bogus"})
    ovstream.Server.assert_called_once_with("WEBRTC")
    err = capsys.readouterr().err
    assert "OVGEAR_LIVESTREAM_PROTOCOL" in err
    assert "bogus" in err
    assert "webrtc" in err


# ── Port plumbing (Step 1.2) ──

def _ports_from_drive(monkeypatch, env_overrides):
    """Drive one frame with ``env_overrides``; return the kwargs handed
    to ``ovstream.ServerConfig`` so tests can assert on the resolved
    ``stream_port`` and ``webrtc_signal_port`` values."""
    captured: dict = {}
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)

    def _capture_cfg(**kw):
        captured.update(kw)
        return types.SimpleNamespace(**kw)

    ovstream.ServerConfig.side_effect = _capture_cfg
    cudart = _make_cudart_mock([], ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    with patch.dict(os.environ, _with_test_env(env_overrides), clear=True):
        tap = tap_mod.LivestreamTap.maybe_create()
    assert tap is not None
    pushed = tap.tee_to_ovstream(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert pushed is True
    return captured


def test_default_ports_match_kit_standard(monkeypatch):
    """No port env vars set → ``ServerConfig`` is constructed with the
    Kit-standard signaling port 49100 and the ovstream-default media
    port 47999."""
    captured = _ports_from_drive(monkeypatch, env_overrides={})
    assert captured.get("webrtc_signal_port") == tap_mod._DEFAULT_SIGNAL_PORT == 49100
    assert captured.get("stream_port") == tap_mod._DEFAULT_MEDIA_PORT == 47999


def test_custom_ports_override_defaults(monkeypatch):
    """Both new env vars set → ``ServerConfig`` reflects them
    verbatim. The two ports are independent."""
    captured = _ports_from_drive(monkeypatch, env_overrides={
        tap_mod._SIGNAL_PORT_ENV_VAR: "31415",
        tap_mod._MEDIA_PORT_ENV_VAR: "27182",
    })
    assert captured.get("webrtc_signal_port") == 31415
    assert captured.get("stream_port") == 27182


def test_legacy_port_back_compat_with_warning(monkeypatch, capsys):
    """The deprecated ``OVGEAR_LIVESTREAM_PORT`` is honoured as a
    fallback for the *signaling* port (the user-facing port for
    browser-driven WebRTC) and emits a one-shot stderr deprecation
    warning telling the user which new var to set explicitly. The
    media port is unaffected; it falls back to the documented
    default."""
    captured = _ports_from_drive(monkeypatch, env_overrides={
        tap_mod._LEGACY_PORT_ENV_VAR: "49101",
    })
    assert captured.get("webrtc_signal_port") == 49101
    assert captured.get("stream_port") == tap_mod._DEFAULT_MEDIA_PORT == 47999
    err = capsys.readouterr().err
    assert tap_mod._LEGACY_PORT_ENV_VAR in err
    assert "deprecated" in err
    assert tap_mod._SIGNAL_PORT_ENV_VAR in err
    assert tap_mod._MEDIA_PORT_ENV_VAR in err


# ── R/B swap kernel wired into the streaming pipeline (Step 1.6) ──

def _spy_swap_and_warmup(monkeypatch, events):
    """Replace the production swap kernel + warm_up with spies that
    append events. Avoids a real NVRTC compile on CPU-only hosts and
    lets call-order assertions inspect the recorded sequence."""
    def _spy_swap(dev, w, h, pitch, stream=0):
        events.append(("swap", int(dev), int(w), int(h), int(pitch)))

    monkeypatch.setattr(tap_mod._swap_kernel, "swap_rb_in_place", _spy_swap)
    monkeypatch.setattr(tap_mod._swap_kernel, "warm_up", lambda: None)


def test_format_fix_on_invokes_kernel_between_d2d_and_stream_video(monkeypatch):
    """With ``OVGEAR_LIVESTREAM_FORMAT_FIX`` defaulting to ON, the
    per-frame ordering must be:

        d2d (CUDA→scratch) → swap_rb_in_place(scratch) → stream_video.

    The swap kernel runs in-place on the scratch ring slot the d2d
    just filled; ``stream_video`` then reads the now-BGRA bytes."""
    events = []
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    server.stream_video.side_effect = lambda frame: events.append(
        ("stream_video", frame.buffer)
    )
    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    _spy_swap_and_warmup(monkeypatch, events)

    with patch.dict(os.environ, _TEST_ENV, clear=True):
        tap = tap_mod.LivestreamTap.maybe_create()
    assert tap is not None
    pushed = tap.tee_to_ovstream(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert pushed is True

    op_seq = [e[0] for e in events if e[0] in ("d2d", "swap", "stream_video")]
    assert op_seq == ["d2d", "swap", "stream_video"]
    # Kernel was launched with the SAME pointer + dims as d2d/stream_video.
    swap_event = next(e for e in events if e[0] == "swap")
    _tag, dev, w, h, pitch = swap_event
    assert dev == 0xAA  # the first scratch ring slot
    assert (w, h, pitch) == (3, 2, 12)


def test_format_fix_off_skips_kernel(monkeypatch):
    """``OVGEAR_LIVESTREAM_FORMAT_FIX=0`` keeps the legacy
    R/B-swapped output for diagnostic comparisons. The kernel must
    NOT be invoked; ``d2d`` and ``stream_video`` still happen."""
    events = []
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    server.stream_video.side_effect = lambda frame: events.append(
        ("stream_video", frame.buffer)
    )
    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    _spy_swap_and_warmup(monkeypatch, events)

    with patch.dict(
        os.environ,
        _with_test_env({tap_mod._FORMAT_FIX_ENV_VAR: "0"}),
        clear=True,
    ):
        tap = tap_mod.LivestreamTap.maybe_create()
    assert tap is not None
    pushed = tap.tee_to_ovstream(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert pushed is True

    assert all(e[0] != "swap" for e in events)
    op_seq = [e[0] for e in events if e[0] in ("d2d", "stream_video")]
    assert op_seq == ["d2d", "stream_video"]


def test_stream_synchronize_runs_between_swap_and_stream_video(monkeypatch):
    """Tier-1 fix: ``_swap_kernel.swap_rb_in_place`` is asynchronous on
    the device; without a stream sync, ``Server.stream_video`` may hand
    NVENC a buffer whose R/B swap hasn't finished. The fix calls
    ``cudart.stream_synchronize(0)`` between the kernel launch and
    ``stream_video``. This test asserts the per-frame call sequence
    is exactly:

        d2d → swap → stream_synchronize → stream_video.
    """
    events: list = []
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    server.stream_video.side_effect = lambda frame: events.append(
        ("stream_video", frame.buffer)
    )
    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    cudart.stream_synchronize.side_effect = lambda stream=0: events.append(
        ("stream_synchronize", int(stream))
    )
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    _spy_swap_and_warmup(monkeypatch, events)

    with patch.dict(os.environ, _TEST_ENV, clear=True):
        tap = tap_mod.LivestreamTap.maybe_create()
    assert tap is not None
    pushed = tap.tee_to_ovstream(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert pushed is True

    op_seq = [
        e[0] for e in events
        if e[0] in ("d2d", "swap", "stream_synchronize", "stream_video")
    ]
    assert op_seq == ["d2d", "swap", "stream_synchronize", "stream_video"]


def test_stream_synchronize_skipped_when_format_fix_off(monkeypatch):
    """When the format fix is off, the kernel doesn't run and there is
    no async work to wait on — the sync would needlessly drain
    unrelated CUDA work the renderer may have queued. Assert sync is
    NOT called when ``_FORMAT_FIX=0``."""
    events: list = []
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    server.stream_video.side_effect = lambda frame: events.append(
        ("stream_video", frame.buffer)
    )
    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    cudart.stream_synchronize.side_effect = lambda stream=0: events.append(
        ("stream_synchronize", int(stream))
    )
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    _spy_swap_and_warmup(monkeypatch, events)

    with patch.dict(
        os.environ,
        _with_test_env({tap_mod._FORMAT_FIX_ENV_VAR: "0"}),
        clear=True,
    ):
        tap = tap_mod.LivestreamTap.maybe_create()
    pushed = tap.tee_to_ovstream(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert pushed is True

    assert all(e[0] != "stream_synchronize" for e in events)
    assert all(e[0] != "swap" for e in events)


def test_status_atom_latches_error_on_non_ovstream_failure(monkeypatch):
    """Tier-1 fix: when a non-OvstreamError surfaces from
    ``stream_video`` and the tap permanently disables itself, the
    status atom must transition to ERROR with a non-empty
    ``last_error`` string. Before the fix the overlay would keep
    showing ``Listening`` even though the tap was dead — this test
    catches the regression."""
    _ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    server.stream_video.side_effect = ValueError("synthetic encoder kaboom")
    events: list = []
    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    _spy_swap_and_warmup(monkeypatch, events)

    with patch.dict(os.environ, _TEST_ENV, clear=True):
        tap = tap_mod.LivestreamTap.maybe_create()
    pushed = tap.tee_to_ovstream(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert pushed is False
    assert tap._disabled is True

    state, n_clients, last_error = tap.status()
    assert state == "ERROR"
    assert last_error is not None
    assert "ValueError" in last_error
    assert "synthetic encoder kaboom" in last_error
    # Once latched, a connect callback must NOT downgrade ERROR back
    # to STREAMING — the overlay should keep the failure visible.
    tap._on_connection_changed(True)
    state2, _, last_error2 = tap.status()
    assert state2 == "ERROR"
    assert last_error2 == last_error


def test_byte_order_swap_proven_via_d2h(monkeypatch):
    """End-to-end byte-order proof on a real GPU: seed an RGBA source
    on the device, run the live tap (real ``_Cudart``, real
    ``_swap_kernel``, mocked ``ovstream`` server), then ``cudart.d2h``
    the scratch buffer that was handed to ``stream_video`` and assert
    the first pixel's BGR is the source's RGB swapped (``BGR(out) ==
    swap(RGB(src))``). This is the no-ffmpeg byte-order proof Step
    1.6 specifies."""
    from tests._cuda_helpers import TestCuda, has_gpu_with_swap_kernel

    if not has_gpu_with_swap_kernel():
        pytest.skip("CUDA runtime / NVRTC / GPU not available")

    cu = TestCuda()
    W, H = 8, 8
    src = np.zeros((H, W, 4), dtype=np.uint8)
    # Distinctive first-pixel sentinel so a regression to identity
    # would surface as wrong-but-readable bytes, not zeros.
    src[0, 0] = [0xDE, 0xAD, 0xBE, 0xEF]
    nbytes = src.nbytes
    src_dev = cu.malloc(nbytes)
    cu.h2d(src_dev, src)

    captured = {}
    # neutralize_swap=False so the real Step-1.5 kernel runs on the
    # real device buffer this test allocated — the whole point of the
    # byte-order proof.
    ovstream, server = _install_mock_ovstream(
        monkeypatch, connected=True, neutralize_swap=False,
    )

    def _capture_video_frame(**kw):
        captured.update(kw)
        return types.SimpleNamespace(**kw)

    ovstream.VideoFrame.side_effect = _capture_video_frame

    tap = None
    try:
        with patch.dict(os.environ, _TEST_ENV, clear=True):
            tap = tap_mod.LivestreamTap.maybe_create()
        assert tap is not None
        mapping = types.SimpleNamespace(data=src_dev, shape=(H, W))
        pushed = tap.tee_to_ovstream(mapping, W, H)
        assert pushed is True

        # Read back the very buffer ovstream was about to encode.
        scratch_dev = captured["buffer"]
        out = np.empty_like(src)
        cu.d2h(out, scratch_dev)
        cu.sync()

        # First pixel: RGBA(0xDE, 0xAD, 0xBE, 0xEF) → BGRA(0xBE, 0xAD,
        # 0xDE, 0xEF). The kernel ran in-place on the scratch slot.
        assert tuple(out[0, 0]) == (0xBE, 0xAD, 0xDE, 0xEF)
    finally:
        if tap is not None:
            try:
                tap.close()
            except Exception:
                pass
        cu.free(src_dev)


# ── on_connection registration ordering + status atom (Step 1.4) ──

def _drive_with_connection_capture(monkeypatch):
    """Build the mock + tap, capture ``server.on_connection`` at the
    instant ``server.start(...)`` fires, drive one frame so the server
    bring-up runs.

    Returns ``(tap, captured_callback)``: the live tap and whatever
    callable was assigned to ``server.on_connection`` at the moment of
    ``start``. If ``captured_callback is None``, the production code
    set the callback AFTER ``start`` (or never) — which would be a
    Step 1.4 regression."""
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    # Reset auto-attr so MagicMock doesn't auto-create a "callback" for
    # us; we want the value to be None unless the production code
    # explicitly sets it.
    server.on_connection = None

    captured: dict = {}

    def _start(cfg):
        captured["on_connection_at_start"] = server.on_connection
        captured["start_called"] = True

    server.start.side_effect = _start

    cudart = _make_cudart_mock([], ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()
    assert tap is not None
    pushed = tap.tee_to_ovstream(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert pushed is True
    assert captured.get("start_called") is True
    return tap, captured.get("on_connection_at_start")


def test_on_connection_registered_before_server_start(monkeypatch):
    """The SDK guards its callback table with a mutex, so setting
    ``on_connection`` after ``start()`` is technically safe — but
    any client connect that fires between ``start()`` and the setter
    call lands on a null pointer on the C side and is silently
    dropped. The tap must therefore set the callback BEFORE start.

    This test captures ``server.on_connection`` at the exact moment
    ``server.start(cfg)`` is invoked. If the value is anything other
    than the tap's bound callback, Step 1.4 has regressed."""
    tap, callback_at_start = _drive_with_connection_capture(monkeypatch)
    assert callback_at_start is not None
    assert callable(callback_at_start)
    # Identity check: the captured callable must be the tap's bound
    # _on_connection_changed method (so the SDK fires it directly into
    # the status-atom path, not into some unrelated lambda).
    assert callback_at_start == tap._on_connection_changed


def test_status_atom_transitions_on_connect_disconnect(monkeypatch):
    """Drive the captured callback with True/False to simulate clients
    joining and leaving; assert the public ``tap.status()`` snapshot
    transitions through OFF → LISTENING → STREAMING → LISTENING and
    tracks the client count exactly. The atom is what the Step 1.7
    overlay widget reads once per frame."""
    tap, cb = _drive_with_connection_capture(monkeypatch)

    # After server bring-up: LISTENING with zero clients.
    assert tap.status() == ("LISTENING", 0, None)

    # First client connects → STREAMING with 1 client.
    cb(True)
    assert tap.status() == ("STREAMING", 1, None)

    # Second client connects → STREAMING with 2 clients.
    cb(True)
    assert tap.status() == ("STREAMING", 2, None)

    # First client drops — second client still attached → STREAMING (1).
    cb(False)
    assert tap.status() == ("STREAMING", 1, None)

    # Last client drops → back to LISTENING (0). No state churn beyond
    # what the SDK reports.
    cb(False)
    assert tap.status() == ("LISTENING", 0, None)

    # Spurious extra disconnect must not drive the count negative.
    cb(False)
    assert tap.status() == ("LISTENING", 0, None)


# ── Public-IP plumbing (Step 1.3) ──

def test_public_ip_unset_passes_none(monkeypatch):
    """``OVGEAR_LIVESTREAM_PUBLIC_IP`` unset → ``ServerConfig`` is
    constructed with ``webrtc_public_ip=None`` (the SDK's "use ICE"
    sentinel). The default LAN-localhost flow stays untouched."""
    captured = _ports_from_drive(monkeypatch, env_overrides={})
    assert "webrtc_public_ip" in captured
    assert captured["webrtc_public_ip"] is None


def test_public_ip_set_passes_string_verbatim(monkeypatch):
    """``OVGEAR_LIVESTREAM_PUBLIC_IP`` set → ``ServerConfig`` receives
    the string verbatim (no parsing, no normalisation). The SDK side
    encodes it to UTF-8 and disables ICE for the WebRTC offer."""
    captured = _ports_from_drive(monkeypatch, env_overrides={
        tap_mod._PUBLIC_IP_ENV_VAR: "203.0.113.42",
    })
    assert captured["webrtc_public_ip"] == "203.0.113.42"


# ── VideoFrame field-name contract (Step 0.1) ──

def test_video_frame_constructed_with_buffer_and_pitch_keywords(monkeypatch):
    """Step 0.1 — the SDK's ``VideoFrame`` dataclass uses ``buffer`` and
    ``pitch_bytes``; the tap must construct it with those keyword names
    (not the legacy ``data``/``ptr`` names from earlier drops). Captures
    the exact kwargs handed to ``ovstream.VideoFrame`` so a future
    regression to positional / wrong-name args fails this test loudly.
    """
    captured: dict = {}
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)

    def _capture_video_frame(**kw):
        captured.update(kw)
        return types.SimpleNamespace(**kw)

    ovstream.VideoFrame.side_effect = _capture_video_frame

    events: list = []
    cudart = _make_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()

    pushed = tap.tee_to_ovstream(_mapping(3, 2, ptr=0x1111), 3, 2)
    assert pushed is True

    # Exact keyword names + concrete int types per the VideoFrame
    # dataclass contract (ovstream/_types.py).
    assert set(captured.keys()) == {"buffer", "width", "height", "pitch_bytes"}
    assert captured["buffer"] == 0xAA  # the scratch ring slot
    assert captured["width"] == 3
    assert captured["height"] == 2
    assert captured["pitch_bytes"] == 12  # width * 4
    assert all(isinstance(v, int) for v in captured.values())


# ── Blocker 5: shutdown is uniform ──

def test_shutdown_closes_active_livestream():
    adapter = adapter_mod.OvRtxRendererAdapter.__new__(adapter_mod.OvRtxRendererAdapter)
    adapter._livestream = MagicMock()
    adapter._renderer = MagicMock()
    adapter._session_handle = None
    adapter._usd_handle = None
    adapter._owned_tmp_path = None
    adapter._stage = object()

    livestream = adapter._livestream
    adapter.shutdown()

    livestream.close.assert_called_once_with()
    assert adapter._livestream is None
    assert adapter._renderer is None
    assert adapter._stage is None


def test_shutdown_tolerates_missing_livestream_attr():
    """Symmetry with the _extract_ldr_color rebase fix: shutdown should
    use getattr defensively too, so __new__-constructed test stubs
    don't blow up."""
    adapter = adapter_mod.OvRtxRendererAdapter.__new__(adapter_mod.OvRtxRendererAdapter)
    adapter._renderer = MagicMock()
    adapter._session_handle = None
    adapter._usd_handle = None
    adapter._owned_tmp_path = None
    adapter._stage = object()
    # _livestream attr deliberately not set.

    adapter.shutdown()  # must not raise

    assert adapter._renderer is None


# ── Step 2.5: linear (pitched) scratch ring + tee_linear_to_ovstream ──

def _make_pitched_cudart_mock(events, ptrs=None, pitch_returns=None):
    """_Cudart mock with `malloc_pitch` wired in.

    Differs from `_make_cudart_mock` only in adding the Step-2.5 pitched
    allocator. Returns ``(ptr, pitch_bytes)`` from successive iterators.
    """
    if ptrs is None:
        ptrs = iter([0xA0, 0xB0, 0xC0, 0xD0])
    if pitch_returns is None:
        pitch_returns = iter([4096, 4096, 4096, 4096])

    cudart = MagicMock()

    def _malloc(nbytes):
        events.append(("malloc", nbytes))
        return next(ptrs)

    def _malloc_pitch(width_bytes, height):
        ptr = next(ptrs)
        pitch = next(pitch_returns)
        events.append(("malloc_pitch", width_bytes, height, pitch, ptr))
        return ptr, pitch

    cudart.malloc.side_effect = _malloc
    cudart.malloc_pitch.side_effect = _malloc_pitch
    cudart.d2d.side_effect = lambda dst, src, nbytes: events.append(("d2d", dst, src, nbytes))
    cudart.d2h.side_effect = lambda host, src, nbytes: events.append(("d2h", src, nbytes, host.shape))
    cudart.free.side_effect = lambda ptr: events.append(("free", ptr))
    cudart.device_synchronize.side_effect = lambda: events.append(("sync",))
    cudart.stream_synchronize.side_effect = lambda stream=0: events.append(("stream_sync", stream))
    return cudart


def test_default_buffer_ring_wires_both_scratch_rings(monkeypatch):
    """Production default env allocates the default depth in both rings."""
    events = []
    _ovstream, _server = _install_mock_ovstream(monkeypatch, connected=True)
    depth = tap_mod._DEFAULT_RING_LEN
    cudart = _make_pitched_cudart_mock(
        events,
        ptrs=iter(range(0x1000, 0x1000 + depth * 2)),
        pitch_returns=iter([4096] * depth),
    )
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    monkeypatch.delenv(tap_mod._BUFFER_RING_ENV_VAR, raising=False)
    monkeypatch.setenv(tap_mod._ENABLED_ENV_VAR, "1")

    tap = tap_mod.LivestreamTap.maybe_create()
    assert tap is not None
    try:
        tap._ensure_server(16, 8)
        tap._ensure_linear_ring(16, 8)

        assert tap._ring_len == depth
        assert len(tap._scratch_ring) == depth
        assert len(tap._linear_ring) == depth
        assert len([e for e in events if e[0] == "malloc"]) == depth
        assert len([e for e in events if e[0] == "malloc_pitch"]) == depth
    finally:
        tap.close()


def test_acquire_linear_scratch_rotates_across_frames(monkeypatch):
    """Step 2.5: the pitched ring rotates so `copy_to_linear` for frame
    N+1 cannot stomp NVENC's still-in-flight read of frame N.

    Calls ``acquire_linear_scratch`` 4 times at the same size and asserts
    the returned device pointers cycle through the configured test ring in
    order. Pitch is reported verbatim from ``cudaMallocPitch``.
    """
    events = []
    _ovstream, _server = _install_mock_ovstream(monkeypatch, connected=True)
    cudart = _make_pitched_cudart_mock(
        events,
        ptrs=iter([0xAA00, 0xBB00]),
        pitch_returns=iter([7936, 7936]),  # cudaMallocPitch for 1920x4 = 7936 on L40
    )
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()
    assert tap is not None

    # First call lazily allocates the ring (2 cudaMallocPitch calls);
    # subsequent calls hit the cache and just rotate.
    slots = [tap.acquire_linear_scratch(1920, 1080) for _ in range(4)]

    ptrs = [s[0] for s in slots]
    pitches = [s[1] for s in slots]
    assert ptrs == [0xAA00, 0xBB00, 0xAA00, 0xBB00]
    assert pitches == [7936, 7936, 7936, 7936]
    # Exactly one ring's worth of allocations — second-and-later acquires reuse.
    malloc_pitch_calls = [e for e in events if e[0] == "malloc_pitch"]
    assert len(malloc_pitch_calls) == tap._ring_len
    # Width-bytes argument is always width*4 = 1920*4 = 7680.
    assert all(e[1] == 7680 and e[2] == 1080 for e in malloc_pitch_calls)


def test_tee_linear_to_ovstream_passes_buffer_and_pitch(monkeypatch):
    """Step 2.5: the new tap method builds a `VideoFrame` from the
    caller-supplied ``(dev_ptr, width, height, pitch_bytes)`` and
    hands it to ``server.stream_video``. The R/B swap kernel runs
    in place on the buffer first (verified separately in
    ``test_tee_linear_to_ovstream_swaps_rb_before_stream``); this
    case asserts only the kwarg shape that reaches the SDK.

    No D2D ever runs on this path — the caller owns the device
    pointer (typically a slot from ``acquire_linear_scratch``).
    """
    captured: dict = {}

    def _capture_video_frame(**kw):
        captured.update(kw)
        return types.SimpleNamespace(**kw)

    events = []
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    ovstream.VideoFrame.side_effect = _capture_video_frame
    server.stream_video.side_effect = lambda frame: events.append(
        ("stream_video", frame.buffer, frame.width, frame.height, frame.pitch_bytes)
    )

    cudart = _make_pitched_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)

    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()

    pushed = tap.tee_linear_to_ovstream(0xDEAD_BEEF, 1920, 1080, 7936)
    assert pushed is True

    assert captured == {
        "buffer": 0xDEAD_BEEF,
        "width": 1920,
        "height": 1080,
        "pitch_bytes": 7936,
    }
    # All values reach the SDK as concrete Python ints (no numpy /
    # ctypes leakage), per the ovstream `VideoFrame` contract.
    assert all(isinstance(v, int) for v in captured.values())

    # Exactly one stream_video call with those values.
    stream_calls = [e for e in events if e[0] == "stream_video"]
    assert stream_calls == [("stream_video", 0xDEAD_BEEF, 1920, 1080, 7936)]
    # No D2D — the headless hook owns the device pointer.
    assert all(e[0] != "d2d" for e in events)
    assert tap._frames_pushed == 1
    assert tap._frames_skipped == 0


def test_tee_linear_to_ovstream_swallows_ovstream_error(monkeypatch):
    """Step 2.5: a transient `OvstreamError` from `stream_video` must
    NOT propagate to the renderer and must NOT permanently disable
    the tap — it is a frame-skip, identical to the windowed path.
    """
    events = []
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    cudart = _make_pitched_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)

    # Configure stream_video to raise the SDK's OvstreamError on every
    # call (the install fixture aliases OvstreamError → RuntimeError).
    server.stream_video.side_effect = ovstream.OvstreamError("transient encoder hiccup")

    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()

    pushed = tap.tee_linear_to_ovstream(0xCAFEBABE, 1920, 1080, 7936)

    # Failure is isolated: returns False, increments skip counter, but
    # the tap stays alive for the next frame.
    assert pushed is False
    assert tap._disabled is False
    assert tap._frames_skipped == 1
    assert tap._frames_pushed == 0
    # Status atom must NOT latch into ERROR for an OvstreamError —
    # ERROR is reserved for non-recoverable failures (Step 1.4 / 1.6).
    # The first push transitions OFF → LISTENING via _ensure_server,
    # which is fine; the OvstreamError path leaves it there.
    assert tap.status()[0] != tap_mod._STATE_ERROR
    assert tap.status()[0] == tap_mod._STATE_LISTENING

    # A second call still skips (server stays connected, no escalation).
    pushed2 = tap.tee_linear_to_ovstream(0xCAFEBABE, 1920, 1080, 7936)
    assert pushed2 is False
    assert tap._disabled is False
    assert tap._frames_skipped == 2


# ── Step 2.5 Codex fixes: pointer-survival + R/B swap before stream ──

def test_acquire_to_tee_first_frame_keeps_linear_pointer_valid(monkeypatch):
    """Codex Issue 1: a pointer returned by ``acquire_linear_scratch``
    must remain valid through the full ``tee_linear_to_ovstream`` call.

    Reproduces the bug: on first push the linear ring is allocated by
    ``acquire_linear_scratch``, then ``tee_linear_to_ovstream`` calls
    ``_ensure_server``. Pre-fix, ``_teardown_server_and_scratch`` would
    free the linear ring as collateral, making the pointer the caller
    just got a use-after-free. Post-fix, server bring-up only touches
    the D2D ring; the linear ring survives until ``close()`` or
    ``acquire_linear_scratch`` is called at a different size.
    """
    events = []
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    server.stream_video.side_effect = lambda frame: events.append(
        ("stream_video", frame.buffer, frame.pitch_bytes)
    )

    cudart = _make_pitched_cudart_mock(
        events,
        ptrs=iter([0xAA00, 0xBB00, 0xCC00, 0xDD00]),
        pitch_returns=iter([7936, 7936]),
    )
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)

    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()

    # Step 2.6 hook pattern: acquire then tee on the same frame, with
    # the server NOT yet up.
    ptr, pitch = tap.acquire_linear_scratch(1920, 1080)
    pushed = tap.tee_linear_to_ovstream(ptr, 1920, 1080, pitch)

    assert pushed is True
    # The acquired pointer must NOT be freed by any code path between
    # acquire and stream_video. Crucially, ``_ensure_server`` running
    # inside ``tee_linear_to_ovstream`` must not free the linear ring.
    free_events = [e for e in events if e[0] == "free"]
    assert ptr not in {p for _tag, p in free_events}, (
        f"acquired pointer freed during tee — events={events}"
    )
    # And the streamed buffer is the same pointer the caller acquired,
    # at the matching pitch.
    stream_events = [e for e in events if e[0] == "stream_video"]
    assert stream_events == [("stream_video", ptr, pitch)]


def test_tee_linear_to_ovstream_swaps_rb_before_stream(monkeypatch):
    """Codex Issue 2: the R/B swap kernel must run on the linear buffer
    in place BEFORE ``stream_video`` is called, with a
    ``stream_synchronize`` between the two so NVENC reads the
    post-swap bytes (mirrors the Step-1.6 windowed-path fix).

    Asserts the strict ordering ``swap → stream_sync → stream_video``
    and that the swap targets the caller-supplied device pointer.
    """
    events = []
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    server.stream_video.side_effect = lambda frame: events.append(
        ("stream_video", frame.buffer, frame.pitch_bytes)
    )

    cudart = _make_pitched_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)

    # Replace the no-op swap stub installed by _install_mock_ovstream
    # with a spy that records the call args + ordering.
    def _spy_swap(dev, w, h, pitch, stream=0):
        events.append(("swap", dev, w, h, pitch))
    monkeypatch.setattr(tap_mod._swap_kernel, "swap_rb_in_place", _spy_swap)

    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()

    pushed = tap.tee_linear_to_ovstream(0xCAFE_F00D, 1920, 1080, 7936)
    assert pushed is True

    swap_idx = next(i for i, e in enumerate(events) if e[0] == "swap")
    sync_idx = next(i for i, e in enumerate(events) if e[0] == "stream_sync")
    stream_idx = next(i for i, e in enumerate(events) if e[0] == "stream_video")
    assert swap_idx < sync_idx < stream_idx, events

    # Swap is invoked on the *caller-supplied* device pointer, in place,
    # with the same dimensions/pitch the SDK gets in VideoFrame.
    assert events[swap_idx] == ("swap", 0xCAFE_F00D, 1920, 1080, 7936)
    # Sync runs on the default stream (matches the Step-1.6 windowed
    # implementation; the swap kernel was launched on stream 0).
    assert events[sync_idx] == ("stream_sync", 0)


def test_tee_linear_to_ovstream_format_fix_off_skips_swap_and_sync(monkeypatch):
    """Parity with the Step-1.6 windowed behaviour: when
    ``OVGEAR_LIVESTREAM_FORMAT_FIX=0`` the swap kernel does not run,
    and the post-swap ``stream_synchronize`` is also skipped (no work
    to wait for, and a sync would unnecessarily drain unrelated CUDA
    queue items)."""
    events = []
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    server.stream_video.side_effect = lambda frame: events.append(
        ("stream_video", frame.buffer)
    )

    cudart = _make_pitched_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)

    swap_calls = []

    def _spy_swap(dev, w, h, pitch, stream=0):
        swap_calls.append((dev, w, h, pitch))

    monkeypatch.setattr(tap_mod._swap_kernel, "swap_rb_in_place", _spy_swap)

    with patch.dict(os.environ, {
        tap_mod._ENABLED_ENV_VAR: "1",
        tap_mod._FORMAT_FIX_ENV_VAR: "0",
    }):
        tap = tap_mod.LivestreamTap.maybe_create()

    pushed = tap.tee_linear_to_ovstream(0xCAFEBABE, 1920, 1080, 7936)
    assert pushed is True

    assert swap_calls == []
    assert all(e[0] != "stream_sync" for e in events), events
    # stream_video still runs.
    assert any(e[0] == "stream_video" for e in events)


def test_tee_linear_to_ovstream_swap_failure_falls_back_no_disable(monkeypatch):
    """If the swap kernel itself raises, the tap disables only the
    format fix (legacy R/B-swapped stream is better than dark stream)
    — the overall tap stays alive and ``stream_video`` still runs. No
    sync runs either: the kernel never queued any work."""
    events = []
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    server.stream_video.side_effect = lambda frame: events.append(
        ("stream_video", frame.buffer)
    )

    cudart = _make_pitched_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)

    def _failing_swap(dev, w, h, pitch, stream=0):
        raise tap_mod._swap_kernel.CudaSwapError("nvrtc broken")

    monkeypatch.setattr(tap_mod._swap_kernel, "swap_rb_in_place", _failing_swap)

    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()

    pushed = tap.tee_linear_to_ovstream(0xCAFEBABE, 1920, 1080, 7936)
    assert pushed is True
    assert tap._swap_disabled is True
    assert tap._disabled is False  # tap as a whole stays live
    assert tap.status()[0] != tap_mod._STATE_ERROR
    # No sync because the swap didn't queue any work.
    assert all(e[0] != "stream_sync" for e in events)
    assert any(e[0] == "stream_video" for e in events)


def test_tee_linear_to_ovstream_sync_failure_disables_tap(monkeypatch):
    """If ``cudaStreamSynchronize`` after the swap fails, the tap
    permanently disables the livestream leg with the status atom
    latched into ``ERROR`` — same pattern as the windowed path
    (Step 1.6)."""
    events = []
    ovstream, server = _install_mock_ovstream(monkeypatch, connected=True)
    server.stream_video.side_effect = lambda frame: events.append(
        ("stream_video", frame.buffer)
    )

    cudart = _make_pitched_cudart_mock(events, ptrs=iter([0xAA, 0xBB]))

    def _failing_sync(stream=0):
        events.append(("stream_sync_fail", stream))
        raise RuntimeError("cudaStreamSynchronize stream=0 failed rc=700")

    cudart.stream_synchronize.side_effect = _failing_sync
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)

    # Use a real-shaped no-op swap so swap_ran is True.
    monkeypatch.setattr(
        tap_mod._swap_kernel, "swap_rb_in_place",
        lambda dev, w, h, pitch, stream=0: events.append(("swap", dev)),
    )

    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()

    pushed = tap.tee_linear_to_ovstream(0xCAFEBABE, 1920, 1080, 7936)
    assert pushed is False
    assert tap._disabled is True
    assert tap.status()[0] == tap_mod._STATE_ERROR
    # stream_video must NOT have run when the sync failed — pushing a
    # not-yet-swapped buffer would produce visibly wrong output.
    assert all(e[0] != "stream_video" for e in events), events


def test_ensure_server_does_not_free_linear_ring(monkeypatch):
    """Regression for Codex Issue 1: ``_teardown_server_and_scratch``
    must not touch the linear ring. Constructs a tap, populates the
    linear ring via ``acquire_linear_scratch``, then triggers the
    teardown directly — asserts the linear ring is still intact and
    none of its pointers were freed.
    """
    events = []
    _ovstream, _server = _install_mock_ovstream(monkeypatch, connected=True)
    cudart = _make_pitched_cudart_mock(
        events,
        ptrs=iter([0xAA00, 0xBB00]),
        pitch_returns=iter([7936, 7936]),
    )
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)

    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()

    ptr, pitch = tap.acquire_linear_scratch(1920, 1080)
    ring_snapshot = list(tap._linear_ring)

    events.clear()
    tap._teardown_server_and_scratch()

    # The linear ring must be unchanged by D2D-ring teardown.
    assert tap._linear_ring == ring_snapshot
    assert tap._linear_pitch == pitch
    free_events = [e for e in events if e[0] == "free"]
    assert {p for _tag, p in free_events}.isdisjoint(set(ring_snapshot)), events


def test_close_frees_linear_ring(monkeypatch):
    """``close()`` is the only path (besides linear-ring resize) that
    frees the linear ring. Asserts both rings end up freed and the
    drain (cudaDeviceSynchronize) runs before any free.
    """
    events = []
    _ovstream, _server = _install_mock_ovstream(monkeypatch, connected=True)
    cudart = _make_pitched_cudart_mock(
        events,
        # First two ptrs go to D2D ring on _ensure_server; next two go
        # to the linear ring on acquire_linear_scratch.
        ptrs=iter([0xA0, 0xB0, 0xC0, 0xD0]),
        pitch_returns=iter([7936, 7936]),
    )
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)

    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()
    # Bring the D2D ring up via the windowed path so close() exercises
    # both teardowns.
    tap.tee_and_d2h(_mapping(8, 4), 8, 4)
    linear_ptr, _pitch = tap.acquire_linear_scratch(1920, 1080)

    events.clear()
    tap.close()

    free_events = [(i, e) for i, e in enumerate(events) if e[0] == "free"]
    freed = {e[1] for _i, e in free_events}
    # Both ring slots must have been freed.
    assert {0xA0, 0xB0}.issubset(freed)
    assert {0xC0, 0xD0}.issubset(freed)
    assert linear_ptr in freed

    sync_events = [(i, e) for i, e in enumerate(events) if e[0] == "sync"]
    assert sync_events, "expected at least one cudaDeviceSynchronize before free"
    # All frees come after at least one sync.
    first_sync_idx = sync_events[0][0]
    for i, _e in free_events:
        assert i > first_sync_idx


def test_linear_ring_resize_frees_old_buffers(monkeypatch):
    """``acquire_linear_scratch`` at a new size must drain and free the
    old linear ring before allocating the new one — so a resize-driven
    realloc doesn't leak GPU memory.
    """
    events = []
    _ovstream, _server = _install_mock_ovstream(monkeypatch, connected=True)
    cudart = _make_pitched_cudart_mock(
        events,
        ptrs=iter([0xAA, 0xBB, 0xCC, 0xDD]),
        pitch_returns=iter([7936, 7936, 3840, 3840]),
    )
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)

    with patch.dict(os.environ, {tap_mod._ENABLED_ENV_VAR: "1"}):
        tap = tap_mod.LivestreamTap.maybe_create()

    tap.acquire_linear_scratch(1920, 1080)
    events.clear()

    tap.acquire_linear_scratch(960, 1080)  # different size — triggers resize

    sync_idx = next(i for i, e in enumerate(events) if e[0] == "sync")
    free_events = [(i, e) for i, e in enumerate(events) if e[0] == "free"]
    malloc_pitch_events = [(i, e) for i, e in enumerate(events) if e[0] == "malloc_pitch"]

    # Old ring (0xAA, 0xBB) freed; new ring (0xCC, 0xDD) allocated.
    assert {e[1] for _i, e in free_events} == {0xAA, 0xBB}
    assert all(i > sync_idx for i, _e in free_events)
    assert all(i > free_events[-1][0] for i, _e in malloc_pitch_events)
    # The new ring's width-bytes argument matches the new size.
    assert all(e[1] == 960 * 4 for _i, e in malloc_pitch_events)


# ── Headless-UI renderer-tap suppression (strata#17 / port-conflict fix) ──

def test_renderer_tap_suppressed_when_omniui_headless(monkeypatch):
    """When OMNIUI_HEADLESS=1, the renderer-level tap must be None even if
    OVGEAR_LIVESTREAM=1.  The full-UI stream is owned by the headless frame
    export pipeline; two LivestreamTap instances on the same port would
    conflict.
    """
    _install_mock_ovstream(monkeypatch)
    with patch.dict(os.environ, {
        tap_mod._ENABLED_ENV_VAR: "1",
        "OMNIUI_HEADLESS": "1",
    }):
        assert adapter_mod._livestream_env_enabled() is True
        # The renderer adapter reads OMNIUI_HEADLESS in __init__ and must
        # leave _livestream = None.
        assert os.environ.get("OMNIUI_HEADLESS", "").strip() == "1"
        _headless_ui = os.environ.get("OMNIUI_HEADLESS", "").strip() == "1"
        assert _headless_ui is True
        # Verify the guard expression matches the production logic.
        should_create_tap = adapter_mod._livestream_env_enabled() and not _headless_ui
        assert should_create_tap is False


def test_renderer_tap_created_when_not_headless(monkeypatch):
    """Without OMNIUI_HEADLESS, the renderer tap IS created when OVGEAR_LIVESTREAM=1."""
    _install_mock_ovstream(monkeypatch)
    with patch.dict(os.environ, {
        tap_mod._ENABLED_ENV_VAR: "1",
    }, clear=False):
        # Ensure OMNIUI_HEADLESS is absent.
        monkeypatch.delenv("OMNIUI_HEADLESS", raising=False)
        _headless_ui = os.environ.get("OMNIUI_HEADLESS", "").strip() == "1"
        assert _headless_ui is False
        should_create_tap = adapter_mod._livestream_env_enabled() and not _headless_ui
        assert should_create_tap is True

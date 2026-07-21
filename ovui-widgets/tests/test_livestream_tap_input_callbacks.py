# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tier 3 server-callback registration tests (issue #34, Step 3.6).

The :class:`ovui_data_adapters.openusd._livestream_tap.LivestreamTap` is the only
place ovui_widgets.app creates an :class:`ovstream.Server`. Step 3.6 wires the
remote input path: when a :class:`RemoteInputBridge` is attached via
``set_input_bridge``, the tap registers ``Server.on_input``,
``Server.on_unicode`` and ``Server.on_connection`` **before**
``Server.start(cfg)`` so events that fire during the start window
don't land on null callback pointers (same lesson as Step 1.4 for the
connection callback alone).

These tests share the mocked-ovstream + mocked-cudart scaffolding from
``test_livestream_tap.py`` and exercise the new dispatch surface
without standing up the C runtime.
"""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock, patch

from ovstream import (
    InputEvent,
    InputEventType,
    KeyboardEvent,
    KeyState,
    MouseButton,
    MouseEvent,
    MouseEventType,
)
from ovui_data_adapters.openusd import _livestream_tap as tap_mod

from ovui_widgets.app._input_bridge import RemoteInputBridge

_TEST_ENV = {
    tap_mod._ENABLED_ENV_VAR: "1",
    tap_mod._BUFFER_RING_ENV_VAR: "2",
}

# Constants mirrored from ``ovui_widgets.app._input_bridge`` / Step 3.1 — kept
# local so the tests describe their expectations without re-importing
# the production tables.
_NVST_KEY_LSHIFT = 0x0302
_NVST_KEY_RSHIFT = 0x0303
_NVST_MF_SHIFT = 0x0001


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _install_mock_ovstream(monkeypatch):
    """Install a minimal mock ``ovstream`` module.

    The mock surfaces only what Step 3.6 needs: ``ServerType`` enum
    values, the ``Server`` constructor, ``ServerConfig`` /
    ``VideoFrame`` factories, and the ``InputEventType`` /
    ``MouseEventType`` / ``KeyState`` enums (re-exported from the real
    package so dispatch comparisons work).
    """
    import ovstream as _real_ovstream

    server = MagicMock()
    server.is_client_connected = False

    ovstream = MagicMock()
    ovstream.ServerType.WEBRTC = "WEBRTC"
    ovstream.ServerType.NATIVE = "NATIVE"
    ovstream.ServerType.RTSP = "RTSP"
    ovstream.Server.return_value = server
    ovstream.ServerConfig.side_effect = lambda **kw: types.SimpleNamespace(**kw)
    ovstream.VideoFrame.side_effect = lambda **kw: types.SimpleNamespace(**kw)
    ovstream.OvstreamError = RuntimeError
    # Reuse the real enum types so dispatch comparisons (`event.type ==
    # ovstream.InputEventType.KEYBOARD`) succeed against MouseEvent /
    # KeyboardEvent built from the real package.
    ovstream.InputEventType = _real_ovstream.InputEventType
    ovstream.MouseEventType = _real_ovstream.MouseEventType
    ovstream.KeyState = _real_ovstream.KeyState

    monkeypatch.setitem(sys.modules, "ovstream", ovstream)

    # Neutralise the R/B swap kernel (mirrors test_livestream_tap.py).
    monkeypatch.setattr(
        tap_mod._swap_kernel, "swap_rb_in_place",
        lambda dev, w, h, pitch, stream=0: None,
    )
    monkeypatch.setattr(tap_mod._swap_kernel, "warm_up", lambda: None)
    return ovstream, server


def _make_cudart_mock():
    cudart = MagicMock()
    ptrs = iter([0xAA, 0xBB, 0xCC, 0xDD])
    cudart.malloc.side_effect = lambda nbytes: next(ptrs)
    cudart.d2d.side_effect = lambda *a, **k: None
    cudart.d2h.side_effect = lambda *a, **k: None
    cudart.free.side_effect = lambda *a, **k: None
    cudart.device_synchronize.side_effect = lambda: None
    return cudart


def _make_tap(monkeypatch):
    """Build a real LivestreamTap against the mocked ovstream + cudart."""
    ovstream, server = _install_mock_ovstream(monkeypatch)
    cudart = _make_cudart_mock()
    monkeypatch.setattr(tap_mod, "_Cudart", lambda: cudart)
    with patch.dict(os.environ, _TEST_ENV):
        tap = tap_mod.LivestreamTap.maybe_create()
    assert tap is not None
    return tap, ovstream, server


def _input_keyboard(key_code: int, down: bool, mods: int = 0):
    # Use the top-level imports (bound to the *real* ovstream module
    # at test-module load time). A re-`import ovstream as _ov` here
    # would resolve to the mock once `_install_mock_ovstream` has
    # replaced ``sys.modules['ovstream']``, returning a MagicMock for
    # `InputEvent` whose `.type` does not compare equal to the real
    # `InputEventType.KEYBOARD` — silently breaking the dispatcher.
    return InputEvent(
        type=InputEventType.KEYBOARD,
        keyboard=KeyboardEvent(
            key_code=key_code,
            scan_code=0,
            modifiers=mods,
            key_state=KeyState.DOWN if down else KeyState.UP,
        ),
    )


def _input_mouse_move(x: int, y: int):
    return InputEvent(
        type=InputEventType.MOUSE,
        mouse=MouseEvent(
            type=MouseEventType.MOVE,
            modifiers=0,
            x=x,
            y=y,
            data=0,
            data2=0,
            button_state=KeyState.UP,
        ),
    )


def _input_mouse_button(button: int, down: bool):
    return InputEvent(
        type=InputEventType.MOUSE,
        mouse=MouseEvent(
            type=MouseEventType.BUTTON,
            modifiers=0,
            x=10,
            y=20,
            data=button,
            data2=0,
            button_state=KeyState.DOWN if down else KeyState.UP,
        ),
    )


def _input_mouse_wheel(dx: int, dy: int):
    return InputEvent(
        type=InputEventType.MOUSE,
        mouse=MouseEvent(
            type=MouseEventType.WHEEL,
            modifiers=0,
            x=0,
            y=0,
            data=dx,
            data2=dy,
            button_state=KeyState.UP,
        ),
    )


def _input_gamepad():
    return InputEvent(
        type=InputEventType.GAMEPAD,
        gamepad=None,
    )


# --------------------------------------------------------------------------
# Registration order — the critical Step 3.6 invariant
# --------------------------------------------------------------------------


def test_callbacks_are_assigned_before_server_start(monkeypatch):
    """Acceptance for Step 3.6: when an input bridge is attached,
    ``on_input``, ``on_unicode`` and ``on_connection`` must be set on
    the ovstream Server **before** ``Server.start(cfg)`` is called.

    The Server's ``start.side_effect`` snapshots the three attributes
    at start-time. If any registration is deferred until after start,
    the corresponding snapshot is ``None`` and this test fails before
    the ensure-server call returns.
    """
    tap, _ovstream, server = _make_tap(monkeypatch)
    bridge = RemoteInputBridge(width=1, height=1)
    tap.set_input_bridge(bridge)

    snapshot: dict = {}

    def _start(cfg):
        snapshot["on_connection"] = server.on_connection
        snapshot["on_input"] = server.on_input
        snapshot["on_unicode"] = server.on_unicode

    server.start.side_effect = _start

    tap._ensure_server(1920, 1080)

    # Bound methods are recreated on every attribute access, so use
    # equality rather than identity here — Python compares
    # ``method.__func__`` and ``method.__self__``.
    assert snapshot["on_connection"] == tap._on_connection_changed
    assert snapshot["on_input"] == tap._dispatch_input_event
    assert snapshot["on_unicode"] == tap._dispatch_unicode


def test_message_dispatcher_on_message_assigned_before_server_start(monkeypatch):
    """Step 3.7: when a message dispatcher is attached, the tap
    registers ``on_message`` on the ovstream Server **before**
    ``Server.start(cfg)``. Same race as Step 1.4 / 3.6 — a custom
    message arriving in the start window must not land on a null
    callback pointer.
    """
    tap, _ovstream, server = _make_tap(monkeypatch)
    dispatcher = MagicMock()
    tap.set_message_dispatcher(dispatcher)

    snapshot: dict = {}

    def _start(cfg):
        snapshot["on_message"] = server.on_message
        snapshot["on_connection"] = server.on_connection

    server.start.side_effect = _start

    tap._ensure_server(1920, 1080)

    assert snapshot["on_message"] is dispatcher.on_message
    # Step 3.6 contract preserved — connection callback still wired.
    assert snapshot["on_connection"] == tap._on_connection_changed


def test_message_dispatcher_not_registered_when_unset(monkeypatch):
    """Backward compatibility: with no dispatcher attached the tap
    must not assign ``on_message`` at all so a Tier 1 windowed mode
    keeps the SDK default."""
    tap, _ovstream, server = _make_tap(monkeypatch)
    snapshot: dict = {}

    def _start(cfg):
        snapshot["on_message"] = server.on_message

    server.start.side_effect = _start

    tap._ensure_server(1280, 720)

    # MagicMock returns a fresh child mock for any unset attribute, so
    # the snapshot is *some* MagicMock — but it cannot equal a real
    # bound method on a dispatcher we never created.
    assert not isinstance(snapshot["on_message"], type(_make_tap))
    # Nothing was attached to the tap, so the only safe positive check
    # is that `tap._message_dispatcher` is still None.
    assert tap._message_dispatcher is None


def test_message_dispatcher_can_be_attached_alongside_input_bridge(monkeypatch):
    """The dispatcher and the input bridge are independent surfaces;
    attaching both must result in all four callbacks firing on
    server.start."""
    tap, _ovstream, server = _make_tap(monkeypatch)
    bridge = RemoteInputBridge(width=1, height=1)
    tap.set_input_bridge(bridge)
    dispatcher = MagicMock()
    tap.set_message_dispatcher(dispatcher)

    snapshot: dict = {}

    def _start(cfg):
        snapshot["on_connection"] = server.on_connection
        snapshot["on_input"] = server.on_input
        snapshot["on_unicode"] = server.on_unicode
        snapshot["on_message"] = server.on_message

    server.start.side_effect = _start

    tap._ensure_server(640, 480)

    assert snapshot["on_connection"] == tap._on_connection_changed
    assert snapshot["on_input"] == tap._dispatch_input_event
    assert snapshot["on_unicode"] == tap._dispatch_unicode
    assert snapshot["on_message"] is dispatcher.on_message


def test_callbacks_are_not_registered_when_no_bridge_attached(monkeypatch):
    """Backward compatibility: in windowed Tier 1/Tier 2 mode (no
    bridge attached) only ``on_connection`` is wired — the input and
    unicode hooks remain unset so the tap behaves exactly as it did
    before Step 3.6."""
    tap, _ovstream, server = _make_tap(monkeypatch)
    snapshot: dict = {}

    def _start(cfg):
        snapshot["on_connection"] = server.on_connection
        snapshot["on_input"] = server.on_input
        snapshot["on_unicode"] = server.on_unicode

    server.start.side_effect = _start

    tap._ensure_server(800, 600)

    assert snapshot["on_connection"] == tap._on_connection_changed
    # MagicMock attributes return new MagicMocks on first access, so
    # the only safe check is "the assignment never happened" — the
    # snapshot value is therefore not equal to the tap's bound dispatch
    # methods.
    assert snapshot["on_input"] != tap._dispatch_input_event
    assert snapshot["on_unicode"] != tap._dispatch_unicode


def test_ensure_server_calls_bridge_set_extents(monkeypatch):
    """The bridge's clamp window must be configured to the streamed
    resolution before any input event can fire."""
    tap, _ovstream, _server = _make_tap(monkeypatch)
    bridge = RemoteInputBridge(width=1, height=1)
    tap.set_input_bridge(bridge)

    tap._ensure_server(1280, 720)

    # Push an out-of-range coord through the bridge and confirm it
    # clamps to the new extent rather than the construction default.
    bridge.on_mouse_event(MouseEvent(
        type=MouseEventType.MOVE, modifiers=0,
        x=2000, y=2000, data=0, data2=0, button_state=KeyState.UP,
    ))
    xy, _events = bridge.drain()
    assert xy == (1279, 719)


# --------------------------------------------------------------------------
# Dispatch — one-of-each-event coverage
# --------------------------------------------------------------------------


def test_dispatch_input_event_routes_keyboard_to_bridge(monkeypatch):
    tap, _ovstream, _server = _make_tap(monkeypatch)
    bridge = RemoteInputBridge(width=1920, height=1080)
    tap.set_input_bridge(bridge)

    tap._dispatch_input_event(_input_keyboard(_NVST_KEY_LSHIFT, down=True, mods=_NVST_MF_SHIFT))

    _xy, events = bridge.drain()
    assert len(events) == 1 and isinstance(events[0], KeyboardEvent)
    assert events[0].key_code == _NVST_KEY_LSHIFT
    assert bridge._held_modifier_keys == [_NVST_KEY_LSHIFT]


def test_dispatch_input_event_routes_mouse_move_to_bridge(monkeypatch):
    tap, _ovstream, _server = _make_tap(monkeypatch)
    bridge = RemoteInputBridge(width=1920, height=1080)
    tap.set_input_bridge(bridge)

    tap._dispatch_input_event(_input_mouse_move(640, 480))

    xy, _events = bridge.drain()
    assert xy == (640, 480)


def test_dispatch_input_event_routes_mouse_button_to_bridge(monkeypatch):
    tap, _ovstream, _server = _make_tap(monkeypatch)
    bridge = RemoteInputBridge(width=1920, height=1080)
    tap.set_input_bridge(bridge)

    tap._dispatch_input_event(
        _input_mouse_button(button=int(MouseButton.RIGHT), down=True),
    )

    _xy, events = bridge.drain()
    assert len(events) == 1
    btn = events[0]
    assert isinstance(btn, MouseEvent) and btn.type == MouseEventType.BUTTON
    assert btn.data == int(MouseButton.RIGHT)
    assert btn.button_state == KeyState.DOWN


def test_dispatch_input_event_routes_mouse_wheel_to_bridge(monkeypatch):
    tap, _ovstream, _server = _make_tap(monkeypatch)
    bridge = RemoteInputBridge(width=1920, height=1080)
    tap.set_input_bridge(bridge)

    tap._dispatch_input_event(_input_mouse_wheel(0, 3))
    tap._dispatch_input_event(_input_mouse_wheel(0, 4))  # accumulates

    _xy, events = bridge.drain()
    assert len(events) == 1
    wheel = events[0]
    assert wheel.type == MouseEventType.WHEEL and wheel.data2 == 7


def test_dispatch_input_event_silently_drops_gamepad(monkeypatch):
    """Step 3.6 scope is keyboard + mouse. Gamepad events must not
    raise and must not feed the bridge — the bridge has no gamepad
    path and forwarding into the keyboard/mouse handler would corrupt
    state."""
    tap, _ovstream, _server = _make_tap(monkeypatch)
    bridge = RemoteInputBridge(width=1920, height=1080)
    tap.set_input_bridge(bridge)

    tap._dispatch_input_event(_input_gamepad())

    _xy, events = bridge.drain()
    assert events == []


def test_dispatch_input_event_with_no_bridge_is_silent(monkeypatch):
    """Without a bridge attached the dispatch is a pure no-op — it
    must not raise even when handed a real-looking event."""
    tap, _ovstream, _server = _make_tap(monkeypatch)
    # No set_input_bridge.
    tap._dispatch_input_event(_input_mouse_move(0, 0))  # must not raise


def test_dispatch_unicode_routes_text_to_bridge(monkeypatch):
    tap, _ovstream, _server = _make_tap(monkeypatch)
    bridge = RemoteInputBridge(width=1920, height=1080)
    tap.set_input_bridge(bridge)

    tap._dispatch_unicode("hello")
    tap._dispatch_unicode("世界")

    _xy, events = bridge.drain()
    assert events == ["hello", "世界"]


def test_dispatch_unicode_with_no_bridge_is_silent(monkeypatch):
    tap, _ovstream, _server = _make_tap(monkeypatch)
    tap._dispatch_unicode("ignored")  # must not raise


def test_dispatch_handlers_swallow_bridge_exceptions(monkeypatch, capsys):
    """The SDK worker thread must not unwind through the dispatch
    helpers. A bridge that raises is logged and swallowed."""
    tap, _ovstream, _server = _make_tap(monkeypatch)

    bad_bridge = MagicMock()
    bad_bridge.on_mouse_event.side_effect = RuntimeError("boom-mouse")
    bad_bridge.on_keyboard_event.side_effect = RuntimeError("boom-key")
    bad_bridge.on_unicode.side_effect = RuntimeError("boom-text")
    tap.set_input_bridge(bad_bridge)

    tap._dispatch_input_event(_input_mouse_move(1, 1))     # must not raise
    tap._dispatch_input_event(_input_keyboard(0x0041, True))  # must not raise
    tap._dispatch_unicode("x")                              # must not raise
    err = capsys.readouterr().err
    assert "boom-mouse" in err
    assert "boom-key" in err
    assert "boom-text" in err


# --------------------------------------------------------------------------
# on_connection composition: status overlay + bridge cleanup
# --------------------------------------------------------------------------


def test_on_connection_disconnect_triggers_bridge_modifier_cleanup(monkeypatch):
    """Plan acceptance for Step 3.6: ``on_connection(False)`` triggers
    the side-aware modifier cleanup from Step 3.5. We feed a held
    modifier through the public dispatch path (so this test
    exercises the wiring end-to-end), simulate disconnect, and
    confirm a synthetic UP for that exact key code lands on the
    bridge's deque.
    """
    tap, _ovstream, _server = _make_tap(monkeypatch)
    bridge = RemoteInputBridge(width=1920, height=1080)
    tap.set_input_bridge(bridge)

    # RSHIFT down via the production input dispatcher.
    tap._dispatch_input_event(_input_keyboard(_NVST_KEY_RSHIFT, down=True, mods=_NVST_MF_SHIFT))
    assert bridge._held_modifier_keys == [_NVST_KEY_RSHIFT]

    # Disconnect via the production connection callback.
    tap._on_connection_changed(connected=False)

    _xy, events = bridge.drain()
    keyboard_events = [e for e in events if isinstance(e, KeyboardEvent)]
    assert [(e.key_code, e.key_state) for e in keyboard_events] == [
        (_NVST_KEY_RSHIFT, KeyState.DOWN),
        (_NVST_KEY_RSHIFT, KeyState.UP),
    ]
    assert bridge._held_modifier_keys == []


def test_on_connection_connect_does_not_emit_cleanup(monkeypatch):
    """``on_connection(True)`` must not synthesise releases — the
    bridge stays primed with whatever the SDK reported."""
    tap, _ovstream, _server = _make_tap(monkeypatch)
    bridge = RemoteInputBridge(width=1920, height=1080)
    tap.set_input_bridge(bridge)

    tap._dispatch_input_event(_input_keyboard(_NVST_KEY_LSHIFT, down=True, mods=_NVST_MF_SHIFT))
    bridge.drain()  # discard the press; isolate the on_connection effect

    tap._on_connection_changed(connected=True)
    _xy, events = bridge.drain()
    assert events == []
    assert bridge._held_modifier_keys == [_NVST_KEY_LSHIFT]


def test_on_connection_status_overlay_still_updates_with_bridge(monkeypatch):
    """Backward compatibility: the existing Tier 1 status-atom logic
    (the streaming/listening overlay state) keeps working when a
    bridge is attached. The two effects of ``_on_connection_changed``
    — bridge cleanup and status atom update — are independent and
    both must run."""
    tap, _ovstream, _server = _make_tap(monkeypatch)
    bridge = RemoteInputBridge(width=1920, height=1080)
    tap.set_input_bridge(bridge)

    # Need a server published so the LISTENING transition can fire.
    tap._ensure_server(1280, 720)

    tap._on_connection_changed(connected=True)
    state, n_clients, _err = tap.status()
    assert state == tap_mod._STATE_STREAMING
    assert n_clients == 1

    tap._on_connection_changed(connected=False)
    state, n_clients, _err = tap.status()
    assert state == tap_mod._STATE_LISTENING
    assert n_clients == 0


def test_on_connection_disconnect_runs_bridge_cleanup_even_in_error_state(monkeypatch):
    """If the tap has latched into ERROR (e.g. NVENC failure), the
    overlay stays sticky on ERROR but **bridge cleanup must still
    run** — a stuck modifier on disconnect is a UI bug regardless
    of the streaming health."""
    tap, _ovstream, _server = _make_tap(monkeypatch)
    bridge = RemoteInputBridge(width=1920, height=1080)
    tap.set_input_bridge(bridge)
    tap._dispatch_input_event(_input_keyboard(_NVST_KEY_LSHIFT, down=True, mods=_NVST_MF_SHIFT))
    bridge.drain()  # discard the press

    tap._set_error_status("simulated failure")
    tap._on_connection_changed(connected=False)

    _xy, events = bridge.drain()
    keyboard_events = [e for e in events if isinstance(e, KeyboardEvent)]
    assert keyboard_events == [
        KeyboardEvent(
            key_code=_NVST_KEY_LSHIFT, scan_code=0,
            modifiers=0, key_state=KeyState.UP,
        )
    ]


def test_on_connection_swallows_bridge_exceptions(monkeypatch, capsys):
    """A bridge that raises in ``on_connection`` must not unwind into
    the SDK worker thread."""
    tap, _ovstream, _server = _make_tap(monkeypatch)
    bad_bridge = MagicMock()
    bad_bridge.on_connection.side_effect = RuntimeError("boom-conn")
    tap.set_input_bridge(bad_bridge)

    tap._on_connection_changed(connected=False)  # must not raise
    err = capsys.readouterr().err
    assert "boom-conn" in err

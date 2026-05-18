# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ovwidgets.app._input_bridge.RemoteInputBridge (issue #34, Step 3.2).

Skeleton-level coverage: clamp + one-time WARN, MOVE coalescing,
discrete-event append, wheel-delta accumulation, basic concurrent
access. Drain-side dispatch and modifier release are exercised in the
follow-on steps.
"""

from __future__ import annotations

import logging
import threading

import pytest
from ovstream import KeyboardEvent, KeyState, MouseEvent, MouseEventType

from ovwidgets.app._input_bridge import RemoteInputBridge

_W = 1920
_H = 1080


def _move(x: int, y: int, mods: int = 0) -> MouseEvent:
    return MouseEvent(
        type=MouseEventType.MOVE,
        modifiers=mods,
        x=x,
        y=y,
        data=0,
        data2=0,
        button_state=KeyState.UP,
    )


def _button(x: int, y: int, button: int, down: bool, mods: int = 0) -> MouseEvent:
    return MouseEvent(
        type=MouseEventType.BUTTON,
        modifiers=mods,
        x=x,
        y=y,
        data=button,
        data2=0,
        button_state=KeyState.DOWN if down else KeyState.UP,
    )


def _wheel(dx: int, dy: int, mods: int = 0, x: int = 100, y: int = 100) -> MouseEvent:
    return MouseEvent(
        type=MouseEventType.WHEEL,
        modifiers=mods,
        x=x,
        y=y,
        data=dx,
        data2=dy,
        button_state=KeyState.UP,
    )


def _key(key_code: int, down: bool, mods: int = 0) -> KeyboardEvent:
    return KeyboardEvent(
        key_code=key_code,
        scan_code=0,
        modifiers=mods,
        key_state=KeyState.DOWN if down else KeyState.UP,
    )


# --------------------------------------------------------------------------
# Construction / extents
# --------------------------------------------------------------------------

def test_rejects_non_positive_extents() -> None:
    with pytest.raises(ValueError):
        RemoteInputBridge(width=0, height=1080)
    with pytest.raises(ValueError):
        RemoteInputBridge(width=1920, height=-1)


def test_set_extents_updates_clamp_window() -> None:
    b = RemoteInputBridge(width=100, height=100)
    b.set_extents(_W, _H)
    b.on_mouse_event(_move(1500, 800))
    xy, _events = b.drain()
    # Without the resize, this would clamp to (99, 99); with it the coord stays.
    assert xy == (1500, 800)


def test_set_extents_ignores_non_positive() -> None:
    b = RemoteInputBridge(width=_W, height=_H)
    b.set_extents(0, _H)
    b.set_extents(_W, -10)
    b.on_mouse_event(_move(_W, _H))
    xy, _events = b.drain()
    # Original 1920x1080 still in effect.
    assert xy == (_W - 1, _H - 1)


# --------------------------------------------------------------------------
# Clamp + one-time WARN — primary acceptance criterion for Step 3.2
# --------------------------------------------------------------------------

def test_clamp_and_one_time_warn(caplog: pytest.LogCaptureFixture) -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    caplog.set_level(logging.WARNING, logger="ovwidgets.app.input_bridge")

    # x = width — SDK's inclusive upper bound; valid traffic that must clamp.
    bridge.on_mouse_event(_move(_W, 500))
    xy, _ = bridge.drain()
    assert xy == (_W - 1, 500)

    # x = width-1 — already in-range; no additional WARN.
    bridge.on_mouse_event(_move(_W - 1, 500))
    xy, _ = bridge.drain()
    assert xy == (_W - 1, 500)

    # x = -3 — out-of-range below; clamps but does not WARN again.
    bridge.on_mouse_event(_move(-3, 200))
    xy, _ = bridge.drain()
    assert xy == (0, 200)

    # y similarly out-of-range — silent.
    bridge.on_mouse_event(_move(0, _H + 100))
    xy, _ = bridge.drain()
    assert xy == (0, _H - 1)

    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1, f"expected exactly one WARN, got {len(warns)}: {warns}"
    assert "out of range" in warns[0].getMessage()
    # The WARN reports the actual oversized coords, not the clamped ones.
    assert "(1920,500)" in warns[0].getMessage()


def test_clamp_does_not_raise_on_extreme_coords() -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    # Anything from huge negatives to huge positives must clamp cleanly.
    for x, y in [(-10**9, -10**9), (10**9, 10**9), (0, 0), (_W - 1, _H - 1)]:
        bridge.on_mouse_event(_move(x, y))
    xy, _ = bridge.drain()
    assert 0 <= xy[0] <= _W - 1
    assert 0 <= xy[1] <= _H - 1


# --------------------------------------------------------------------------
# MOVE coalescing
# --------------------------------------------------------------------------

def test_move_coalesces_to_latest_position() -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    for x in range(0, 1000, 50):
        bridge.on_mouse_event(_move(x, 200))
    xy, events = bridge.drain()
    assert xy == (950, 200)
    assert events == [], "MOVE events must not appear in the discrete deque"


def test_drain_clears_events_and_persists_position() -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_mouse_event(_move(400, 300))
    bridge.on_mouse_event(_button(400, 300, button=1, down=True))
    xy_a, evts_a = bridge.drain()
    assert xy_a == (400, 300)
    assert len(evts_a) == 1

    # Second drain: position is sticky; deque is empty until new events arrive.
    xy_b, evts_b = bridge.drain()
    assert xy_b == (400, 300)
    assert evts_b == []


# --------------------------------------------------------------------------
# Append: BUTTON, WHEEL, KeyboardEvent, unicode
# --------------------------------------------------------------------------

def test_button_events_append_in_order() -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_mouse_event(_button(10, 10, button=1, down=True))
    bridge.on_mouse_event(_button(10, 10, button=1, down=False))
    bridge.on_mouse_event(_button(20, 30, button=2, down=True))
    _xy, events = bridge.drain()
    assert len(events) == 3
    assert all(isinstance(e, MouseEvent) and e.type == MouseEventType.BUTTON for e in events)
    assert [e.data for e in events] == [1, 1, 2]
    assert [e.button_state for e in events] == [KeyState.DOWN, KeyState.UP, KeyState.DOWN]


def test_keyboard_events_append() -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_keyboard_event(_key(0x0041, down=True))
    bridge.on_keyboard_event(_key(0x0041, down=False))
    _xy, events = bridge.drain()
    assert len(events) == 2
    assert all(isinstance(e, KeyboardEvent) for e in events)
    assert [e.key_state for e in events] == [KeyState.DOWN, KeyState.UP]


def test_unicode_appends_strings() -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_unicode("hello")
    bridge.on_unicode("")  # ignored
    bridge.on_unicode("世界")
    _xy, events = bridge.drain()
    assert events == ["hello", "世界"]


# --------------------------------------------------------------------------
# Wheel-delta accumulation
# --------------------------------------------------------------------------

def test_consecutive_wheel_events_accumulate() -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_mouse_event(_wheel(0, 1))
    bridge.on_mouse_event(_wheel(0, 2))
    bridge.on_mouse_event(_wheel(0, 4))
    _xy, events = bridge.drain()
    assert len(events) == 1
    only = events[0]
    assert isinstance(only, MouseEvent) and only.type == MouseEventType.WHEEL
    assert only.data == 0
    assert only.data2 == 7  # 1 + 2 + 4


def test_wheel_with_different_modifiers_does_not_accumulate() -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_mouse_event(_wheel(0, 1, mods=0x0001))   # Shift held
    bridge.on_mouse_event(_wheel(0, 1, mods=0x0000))   # Shift released
    bridge.on_mouse_event(_wheel(0, 2, mods=0x0000))   # accumulates with prior
    _xy, events = bridge.drain()
    assert len(events) == 2
    assert events[0].modifiers == 0x0001 and events[0].data2 == 1
    assert events[1].modifiers == 0x0000 and events[1].data2 == 3


def test_wheel_does_not_coalesce_across_a_button_event() -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_mouse_event(_wheel(0, 1))
    bridge.on_mouse_event(_button(50, 50, button=1, down=True))
    bridge.on_mouse_event(_wheel(0, 1))
    _xy, events = bridge.drain()
    assert len(events) == 3
    assert events[0].type == MouseEventType.WHEEL
    assert events[1].type == MouseEventType.BUTTON
    assert events[2].type == MouseEventType.WHEEL


# --------------------------------------------------------------------------
# Modifier tracking + on_connection cleanup (Step 3.5)
# --------------------------------------------------------------------------
#
# Side-aware tracking: the bridge records the actual NVST key code of
# every modifier-key DOWN it sees, and clears the entry on the matching
# UP. On disconnect, every held key code becomes a synthetic UP event.
# The aggregate ``KeyboardEvent.modifiers`` mask is *not* consulted for
# cleanup — the runtime ovstream WebRTC handler at
# ``kit-livestream/sdk/src/webrtc/input_handler.cpp:205–224`` collapses
# RSHIFT/RCONTROL/RALT into the *generic* Shift/Control/Alt bits and
# reuses bits 0x0010/0x0020 for CapsLock/NumLock, so the mask cannot
# distinguish left vs right (Codex Step 3.5 NOT-GOOD finding).

_NVST_MF_SHIFT = 0x0001            # generic Shift bit (left OR right)
_NVST_MF_CONTROL = 0x0002          # generic Ctrl bit (left OR right)
_NVST_MF_ALT = 0x0004              # generic Alt bit (left OR right)
_NVST_MF_SUPER = 0x0008            # generic Meta/Super bit (left OR right)
_NVST_MF_CAPS_LOCK = 0x0010        # NOT a right-shift bit on this branch
_NVST_MF_NUM_LOCK = 0x0020         # NOT a right-ctrl bit on this branch

_NVST_KEY_LSHIFT = 0x0302
_NVST_KEY_RSHIFT = 0x0303
_NVST_KEY_LCONTROL = 0x0305
_NVST_KEY_RCONTROL = 0x0306
_NVST_KEY_LALT = 0x0308
_NVST_KEY_RALT = 0x0309
_NVST_KEY_LMETA = 0x0311
_NVST_KEY_RMETA = 0x0312
_NVST_KEY_CAPS_LOCK = 0x0501
_NVST_KEY_NUM_LOCK = 0x0502


def test_on_keyboard_event_tracks_held_modifier_keys_by_key_code() -> None:
    """Each modifier-key DOWN appends the actual NVST key code to the
    held list; the matching UP removes it. The aggregate ``modifiers``
    mask is not consulted because it is not side-aware on this
    branch's WebRTC path."""
    bridge = RemoteInputBridge(width=_W, height=_H)

    # RSHIFT down with the generic Shift mask — the runtime path
    # collapses both LSHIFT and RSHIFT into ``kModShift = 0x0001``.
    bridge.on_keyboard_event(_key(_NVST_KEY_RSHIFT, down=True, mods=_NVST_MF_SHIFT))
    assert bridge._held_modifier_keys == [_NVST_KEY_RSHIFT]

    # Layer LCONTROL on top with both bits set; the held list keeps
    # press order.
    bridge.on_keyboard_event(_key(_NVST_KEY_LCONTROL, down=True,
                                  mods=_NVST_MF_SHIFT | _NVST_MF_CONTROL))
    assert bridge._held_modifier_keys == [_NVST_KEY_RSHIFT, _NVST_KEY_LCONTROL]

    # RSHIFT up clears its specific entry; LCONTROL stays.
    bridge.on_keyboard_event(_key(_NVST_KEY_RSHIFT, down=False, mods=_NVST_MF_CONTROL))
    assert bridge._held_modifier_keys == [_NVST_KEY_LCONTROL]

    # LCONTROL up clears the rest.
    bridge.on_keyboard_event(_key(_NVST_KEY_LCONTROL, down=False, mods=0))
    assert bridge._held_modifier_keys == []


def test_on_keyboard_event_ignores_non_modifier_key_codes() -> None:
    """A regular alphanumeric key never enters the held-modifier
    list, even when the SDK reports modifier bits in
    ``KeyboardEvent.modifiers`` (e.g. CapsLock latched, or Shift
    held by another physical key)."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_keyboard_event(_key(0x0041, down=True,
                                  mods=_NVST_MF_SHIFT | _NVST_MF_CAPS_LOCK))
    assert bridge._held_modifier_keys == []


def test_on_keyboard_event_ignores_lock_keys() -> None:
    """CapsLock and NumLock are toggle keys, not held modifiers.
    They never enter the held list, and disconnect cleanup does
    not synthesise a release for them."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_keyboard_event(_key(_NVST_KEY_CAPS_LOCK, down=True,
                                  mods=_NVST_MF_CAPS_LOCK))
    bridge.on_keyboard_event(_key(_NVST_KEY_NUM_LOCK, down=True,
                                  mods=_NVST_MF_CAPS_LOCK | _NVST_MF_NUM_LOCK))
    assert bridge._held_modifier_keys == []


def test_on_keyboard_event_duplicate_down_does_not_double_track() -> None:
    """A repeat DOWN for the same key (e.g. OS auto-repeat) does not
    add a duplicate entry — disconnect would otherwise emit two
    releases for one held key."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_keyboard_event(_key(_NVST_KEY_LSHIFT, down=True, mods=_NVST_MF_SHIFT))
    bridge.on_keyboard_event(_key(_NVST_KEY_LSHIFT, down=True, mods=_NVST_MF_SHIFT))
    assert bridge._held_modifier_keys == [_NVST_KEY_LSHIFT]


def test_on_keyboard_event_stray_up_is_silent() -> None:
    """An UP event for a modifier key that was never recorded as DOWN
    is a no-op — the worker thread must not raise."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_keyboard_event(_key(_NVST_KEY_RALT, down=False, mods=0))  # must not raise
    assert bridge._held_modifier_keys == []


def test_on_connection_false_emits_release_for_held_lshift() -> None:
    """LSHIFT down + disconnect: synthesised release uses LSHIFT —
    the same side the client pressed."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_keyboard_event(_key(_NVST_KEY_LSHIFT, down=True, mods=_NVST_MF_SHIFT))
    bridge.on_connection(connected=False)

    _xy, events = bridge.drain()
    keyboard_events = [e for e in events if isinstance(e, KeyboardEvent)]
    assert len(keyboard_events) == 2
    assert keyboard_events[0].key_code == _NVST_KEY_LSHIFT
    assert keyboard_events[0].key_state == KeyState.DOWN
    assert keyboard_events[1].key_code == _NVST_KEY_LSHIFT
    assert keyboard_events[1].key_state == KeyState.UP
    assert bridge._held_modifier_keys == []


def test_on_connection_false_emits_release_for_held_rshift_codex_repro() -> None:
    """Codex Step 3.5 NOT-GOOD reproduction: RSHIFT down with the
    generic Shift mask (the only Shift bit the runtime path emits),
    then disconnect, must synthesise an RSHIFT release — not LSHIFT.

    Pre-fix, the bridge consulted the aggregate mask and emitted
    LSHIFT for bit 0x0001, leaving RSHIFT stuck."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_keyboard_event(_key(_NVST_KEY_RSHIFT, down=True, mods=_NVST_MF_SHIFT))
    bridge.on_connection(connected=False)

    _xy, events = bridge.drain()
    keyboard_events = [e for e in events if isinstance(e, KeyboardEvent)]
    assert [(e.key_code, e.key_state) for e in keyboard_events] == [
        (_NVST_KEY_RSHIFT, KeyState.DOWN),
        (_NVST_KEY_RSHIFT, KeyState.UP),
    ]


def test_on_connection_false_no_held_modifiers_is_noop() -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_connection(connected=False)
    _xy, events = bridge.drain()
    assert events == []
    assert bridge._held_modifier_keys == []


def test_on_connection_false_lock_bits_in_mask_do_not_synthesize_release() -> None:
    """If only CapsLock/NumLock bits are set in the most recent
    ``modifiers`` mask (no actual modifier-key DOWN was observed),
    disconnect must not synthesise any modifier release."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    # A regular A-key press carrying CapsLock+NumLock latched bits.
    bridge.on_keyboard_event(_key(0x0041, down=True,
                                  mods=_NVST_MF_CAPS_LOCK | _NVST_MF_NUM_LOCK))
    bridge.on_connection(connected=False)

    _xy, events = bridge.drain()
    synthesised = [
        e for e in events
        if isinstance(e, KeyboardEvent) and e.key_state == KeyState.UP
    ]
    assert synthesised == []


def test_on_connection_false_emits_releases_in_press_order() -> None:
    """Multi-modifier disconnect cleanup emits releases in the order
    the keys were pressed (not aggregate bit order). Each release
    targets the exact key code that was held."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    # Press order: LCONTROL, RSHIFT, LALT, RMETA — mixed left/right.
    bridge.on_keyboard_event(_key(_NVST_KEY_LCONTROL, down=True, mods=_NVST_MF_CONTROL))
    bridge.on_keyboard_event(_key(_NVST_KEY_RSHIFT, down=True,
                                  mods=_NVST_MF_CONTROL | _NVST_MF_SHIFT))
    bridge.on_keyboard_event(_key(_NVST_KEY_LALT, down=True,
                                  mods=_NVST_MF_CONTROL | _NVST_MF_SHIFT | _NVST_MF_ALT))
    bridge.on_keyboard_event(_key(_NVST_KEY_RMETA, down=True,
                                  mods=(_NVST_MF_CONTROL | _NVST_MF_SHIFT
                                        | _NVST_MF_ALT | _NVST_MF_SUPER)))

    bridge.on_connection(connected=False)
    _xy, events = bridge.drain()

    synthesised = [
        e for e in events
        if isinstance(e, KeyboardEvent) and e.key_state == KeyState.UP
    ]
    assert [e.key_code for e in synthesised] == [
        _NVST_KEY_LCONTROL,
        _NVST_KEY_RSHIFT,
        _NVST_KEY_LALT,
        _NVST_KEY_RMETA,
    ]


def test_on_connection_false_is_idempotent() -> None:
    """A second disconnect after the first must not re-emit releases —
    the held list is cleared by the first call."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_keyboard_event(_key(_NVST_KEY_LSHIFT, down=True, mods=_NVST_MF_SHIFT))
    bridge.on_connection(connected=False)
    bridge.drain()  # discard the first cleanup batch

    # Second disconnect with no fresh keyboard activity should not
    # synthesise additional releases.
    bridge.on_connection(connected=False)
    _xy, events = bridge.drain()
    assert events == []


def test_on_connection_true_is_noop() -> None:
    """Connecting (or re-connecting) does not touch the held list.
    The disconnect handler is the only path that emits releases."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_keyboard_event(_key(_NVST_KEY_LSHIFT, down=True, mods=_NVST_MF_SHIFT))
    assert bridge._held_modifier_keys == [_NVST_KEY_LSHIFT]

    bridge.on_connection(connected=True)
    assert bridge._held_modifier_keys == [_NVST_KEY_LSHIFT]
    _xy, events = bridge.drain()
    # Drain returns the original Shift-down event but no synthesised releases.
    assert all(
        e.key_state == KeyState.DOWN for e in events if isinstance(e, KeyboardEvent)
    )


# --------------------------------------------------------------------------
# Thread-safety smoke test
# --------------------------------------------------------------------------

def test_concurrent_writers_do_not_corrupt_state() -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    n_threads = 8
    n_per_thread = 500

    def producer(start_x: int) -> None:
        for i in range(n_per_thread):
            bridge.on_mouse_event(_move(start_x + i, 100 + i))
            bridge.on_mouse_event(_button(0, 0, button=1, down=True))
            bridge.on_mouse_event(_wheel(0, 1))
            bridge.on_keyboard_event(_key(0x0041, down=True))
            bridge.on_unicode("a")

    threads = [
        threading.Thread(target=producer, args=(t * 100,))
        for t in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    xy, events = bridge.drain()
    # Atomic position is whichever MOVE happened to land last — just
    # assert it stayed inside the clamp window and is a tuple of ints.
    assert isinstance(xy, tuple) and len(xy) == 2
    assert 0 <= xy[0] <= _W - 1
    assert 0 <= xy[1] <= _H - 1

    # Total discrete events: per producer, n_per_thread of each of
    # {button, key, unicode} plus a coalesced number of wheel events
    # (anywhere from 1 to n_per_thread per producer depending on
    # interleaving). Lower-bound sanity-check: at least the
    # non-coalescing kinds are all present.
    button_count = sum(
        1
        for e in events
        if isinstance(e, MouseEvent) and e.type == MouseEventType.BUTTON
    )
    key_count = sum(1 for e in events if isinstance(e, KeyboardEvent))
    unicode_count = sum(1 for e in events if isinstance(e, str))
    assert button_count == n_threads * n_per_thread
    assert key_count == n_threads * n_per_thread
    assert unicode_count == n_threads * n_per_thread

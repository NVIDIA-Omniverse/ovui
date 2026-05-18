# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tier 3 livestream input bridge — SDK callback ↔ ovgear main loop.

The ovstream SDK delivers input events on a worker thread; ovgear's
ImGui IO must be written on the main loop thread before
``ui.next_frame()``. ``RemoteInputBridge`` is the lock-protected
hand-off:

* ``MouseEventType.MOVE`` events coalesce into a single atomic
  ``(x, y)`` — only the most recent cursor position survives until
  the next drain.
* Button presses, wheel ticks, keyboard events and unicode text
  strings append to a deque.
* Consecutive wheel events with the same modifier mask accumulate
  their deltas, so a fast scroll spinning out 30 ticks in one frame
  collapses to a single injected scroll.

Coordinates arrive in streamed-frame pixel space — no scaling. The SDK
clamps inclusively to its announced extents
(``input_handler.cpp:119–120``), so ``x == width`` is reachable. The
bridge accepts that range and clamps it to the ovui-indexable range
``[0, width-1] × [0, height-1]``. The first out-of-range coord raises
a one-time WARN; subsequent out-of-range traffic is silent so a
mis-sized client cannot flood the log.

This module is the **skeleton** (issue #34, Step 3.2). The pre-tick
drain loop (Step 3.3), mouse-button enum mapping (Step 3.4), modifier
disconnect cleanup (Step 3.5), and ``Server`` callback wiring (Step
3.6) layer on top of this state object.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Deque, List, Tuple, Union

from ovstream import KeyboardEvent, KeyState, MouseEvent, MouseEventType

_LOG = logging.getLogger("ovwidgets.app.input_bridge")

# NVST key codes that count as "modifier keys" for disconnect cleanup
# (KeyDefs.h:138–155). Caps Lock and Num Lock are deliberately omitted:
# they are toggle keys, not held modifiers, so synthesising a release
# on disconnect would falsely tell ovui the user just released CapsLock
# even when they are still toggling it.
#
# Tracking the actual key codes (not an aggregate ``modifiers`` bitmask)
# is the source-of-truth fix for the Codex Step 3.5 NOT-GOOD finding:
# the runtime ovstream WebRTC handler at
# ``kit-livestream/sdk/src/webrtc/input_handler.cpp:205–224`` collapses
# RSHIFT / RCONTROL / RALT into the *generic* ``kModShift / kModControl
# / kModAlt`` bits and reuses bits ``0x0010`` and ``0x0020`` for
# CapsLock / NumLock. The aggregate ``modifiers`` mask therefore tells
# us *something* is held but not which side; only the per-event
# ``key_code`` is side-aware.
_MODIFIER_NVST_KEY_CODES = frozenset({
    0x0301,  # NVST_KEY_SHIFT
    0x0302,  # NVST_KEY_LSHIFT
    0x0303,  # NVST_KEY_RSHIFT
    0x0304,  # NVST_KEY_CONTROL
    0x0305,  # NVST_KEY_LCONTROL
    0x0306,  # NVST_KEY_RCONTROL
    0x0307,  # NVST_KEY_ALT
    0x0308,  # NVST_KEY_LALT
    0x0309,  # NVST_KEY_RALT
    0x0310,  # NVST_KEY_META
    0x0311,  # NVST_KEY_LMETA
    0x0312,  # NVST_KEY_RMETA
})

# Discrete events the bridge accepts in its deque. KeyboardEvent and
# MouseEvent are stored verbatim; unicode-text callbacks land as plain
# ``str`` so the drain can dispatch with ``isinstance``.
BridgeEvent = Union[KeyboardEvent, MouseEvent, str]


class RemoteInputBridge:
    """Lock-protected SDK→main-loop event buffer."""

    def __init__(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError(
                f"extents must be positive, got width={width} height={height}"
            )
        self._lock = threading.Lock()
        self._width: int = int(width)
        self._height: int = int(height)
        self._mouse_xy: Tuple[int, int] = (0, 0)
        self._events: Deque[BridgeEvent] = deque()
        # Press-ordered list of NVST modifier key codes that the SDK
        # delivered DOWN events for and has not yet delivered matching
        # UP events for. The disconnect-cleanup path reads this so the
        # synthesised releases use the **same** key code (and therefore
        # the same ImGui side) the client originally pressed.
        self._held_modifier_keys: List[int] = []
        # Cached aggregate ``modifiers`` mask from the last keyboard
        # event. Kept for diagnostics only — Codex's Step 3.5 review
        # established that this mask is not side-aware on the runtime
        # ovstream WebRTC path, so cleanup reads the held-keys list
        # above instead.
        self._last_modifier_mask: int = 0
        self._out_of_range_warned: bool = False

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_extents(self, width: int, height: int) -> None:
        """Update the clamp window (e.g. on resolution change)."""
        if width <= 0 or height <= 0:
            return
        with self._lock:
            self._width = int(width)
            self._height = int(height)

    # ------------------------------------------------------------------
    # SDK-side callbacks (run on the ovstream worker thread)
    # ------------------------------------------------------------------

    def on_mouse_event(self, event: MouseEvent) -> None:
        if event.type == MouseEventType.MOVE:
            x, y = self._clamp(event.x, event.y)
            with self._lock:
                self._mouse_xy = (x, y)
            return

        if event.type == MouseEventType.WHEEL:
            with self._lock:
                tail = self._events[-1] if self._events else None
                if (
                    isinstance(tail, MouseEvent)
                    and tail.type == MouseEventType.WHEEL
                    and tail.modifiers == event.modifiers
                ):
                    tail.data += event.data
                    tail.data2 += event.data2
                    return
                self._events.append(event)
            return

        # MouseEventType.BUTTON
        with self._lock:
            self._events.append(event)

    def on_keyboard_event(self, event: KeyboardEvent) -> None:
        # Steady-state: the SDK delivers each modifier press/release as
        # an ordinary KeyboardEvent (``InputHandler.cpp:230–249``), so
        # the bridge appends it verbatim. The held-keys list and the
        # diagnostic mask are tracked **only** to support disconnect
        # cleanup — no diff-and-emit synthesis in the steady-state
        # path (Codex finding 10b).
        key_code = int(event.key_code)
        with self._lock:
            self._events.append(event)
            self._last_modifier_mask = int(event.modifiers)
            if key_code in _MODIFIER_NVST_KEY_CODES:
                if event.key_state == KeyState.DOWN:
                    if key_code not in self._held_modifier_keys:
                        self._held_modifier_keys.append(key_code)
                else:
                    # KeyState.UP — drop the key from the held list if
                    # present. ``list.remove`` raises ValueError if the
                    # item is missing; guard so a stray UP without a
                    # matching DOWN does not crash the worker thread.
                    try:
                        self._held_modifier_keys.remove(key_code)
                    except ValueError:
                        pass

    def on_unicode(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._events.append(text)

    def on_connection(self, connected: bool) -> None:
        """Handle a connection state change from the ovstream ``Server``.

        On disconnect, every modifier the SDK delivered a DOWN event
        for (and has not yet delivered a matching UP event for) is
        converted into a synthetic ``KeyState.UP``
        :class:`KeyboardEvent` and appended to the deque. The drain
        dispatches those releases through the same
        :func:`_input_drain.drain_bridge_into_ui` path as ordinary
        keyboard events, so ovui sees a release for every modifier the
        remote client was holding when the link dropped — preventing a
        sticky Shift / Ctrl / Alt / Super state.

        The synthesised release uses the **same NVST key code** the
        client pressed, so right-side modifiers release right-side
        ImGui keys (Codex Step 3.5 NOT-GOOD fix). Aggregate
        ``modifiers`` mask bits are not consulted because the runtime
        ovstream WebRTC path collapses RSHIFT/RCONTROL/RALT into the
        generic Shift/Control/Alt bits and reuses bits 0x0010/0x0020
        for CapsLock/NumLock.

        Idempotent: clearing the held list at the end means a second
        ``on_connection(False)`` finds it empty and is a no-op.
        """
        if connected:
            return
        with self._lock:
            for nvst_key in self._held_modifier_keys:
                self._events.append(
                    KeyboardEvent(
                        key_code=nvst_key,
                        scan_code=0,
                        modifiers=0,
                        key_state=KeyState.UP,
                    )
                )
            self._held_modifier_keys.clear()
            self._last_modifier_mask = 0

    # ------------------------------------------------------------------
    # Main-loop side
    # ------------------------------------------------------------------

    def drain(self) -> Tuple[Tuple[int, int], List[BridgeEvent]]:
        """Snapshot the current cursor + queued events, clearing the deque."""
        with self._lock:
            xy = self._mouse_xy
            events = list(self._events)
            self._events.clear()
        return xy, events

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _clamp(self, x: int, y: int) -> Tuple[int, int]:
        with self._lock:
            w = self._width
            h = self._height
        out_of_range = x < 0 or y < 0 or x > (w - 1) or y > (h - 1)
        clamped_x = min(max(int(x), 0), w - 1)
        clamped_y = min(max(int(y), 0), h - 1)
        if out_of_range:
            with self._lock:
                fire_warn = not self._out_of_range_warned
                self._out_of_range_warned = True
            if fire_warn:
                _LOG.warning(
                    "coord out of range (%d,%d) for extents %dx%d; "
                    "clamping to (%d,%d). Subsequent out-of-range events will be silent.",
                    x, y, w, h, clamped_x, clamped_y,
                )
        return clamped_x, clamped_y

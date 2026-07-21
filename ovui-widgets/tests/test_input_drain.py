# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ovui_widgets.app._input_drain.drain_bridge_into_ui (issue #34, Step 3.3).

Two layers:
* The pure helper is exercised against a real :class:`RemoteInputBridge`
  with a MagicMock ``ui_native`` recording every ``_inject_*`` call.
* :meth:`Application._drain_remote_input` and the main loop wiring are
  exercised through the ``headless_app`` fixture — including a static
  check that the loop body calls drain **before** ``await
  ui.next_frame()``.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, call

import pytest
from ovstream import KeyboardEvent, KeyState, MouseButton, MouseEvent, MouseEventType

from ovui_widgets.app._input_bridge import RemoteInputBridge
from ovui_widgets.app._input_drain import drain_bridge_into_ui

_W = 1920
_H = 1080


# --------------------------------------------------------------------------
# Test helpers
# --------------------------------------------------------------------------


def _move(x: int, y: int) -> MouseEvent:
    return MouseEvent(
        type=MouseEventType.MOVE,
        modifiers=0,
        x=x,
        y=y,
        data=0,
        data2=0,
        button_state=KeyState.UP,
    )


def _button(x: int, y: int, button: int, down: bool) -> MouseEvent:
    return MouseEvent(
        type=MouseEventType.BUTTON,
        modifiers=0,
        x=x,
        y=y,
        data=button,
        data2=0,
        button_state=KeyState.DOWN if down else KeyState.UP,
    )


def _wheel(
    dx: int,
    dy: int,
    mods: int = 0,
    *,
    scroll_x: float = 0.0,
    scroll_y: float = 0.0,
) -> MouseEvent:
    return MouseEvent(
        type=MouseEventType.WHEEL,
        modifiers=mods,
        x=0,
        y=0,
        data=dx,
        data2=dy,
        button_state=KeyState.UP,
        scroll_x=scroll_x,
        scroll_y=scroll_y,
    )


def _key(key_code: int, down: bool, mods: int = 0) -> KeyboardEvent:
    return KeyboardEvent(
        key_code=key_code,
        scan_code=0,
        modifiers=mods,
        key_state=KeyState.DOWN if down else KeyState.UP,
    )


# --------------------------------------------------------------------------
# Pure-helper coverage
# --------------------------------------------------------------------------


def test_drain_60_frames_each_with_one_move_and_one_click() -> None:
    """Acceptance scenario from Step 3.3 of the plan.

    60 frames each producing 1 mouse-move + 1 LMB click.
    Assertions:
    1. Per frame, the inject order is move -> button (cursor first so the
       button fires at the up-to-date hover target).
    2. ``mouse_button`` arg is ``ImGuiMouseButton_Left == 0`` for the
       NVST ``MouseButton.LEFT (1)`` input — the table-driven mapping
       in :mod:`ovui_widgets.app._input_drain` puts LEFT on slot 0.
    3. Total counts: 60 moves, 60 buttons, no other inject calls.
    """
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    for frame in range(60):
        bridge.on_mouse_event(_move(100 + frame, 200))
        bridge.on_mouse_event(_button(
            100 + frame, 200, button=int(MouseButton.LEFT), down=True,
        ))
        drain_bridge_into_ui(bridge, ui_native)

    method_calls = ui_native.method_calls
    assert len(method_calls) == 60 * 2

    moves = [c for c in method_calls if c[0] == "_inject_mouse_move"]
    buttons = [c for c in method_calls if c[0] == "_inject_mouse_button"]
    assert len(moves) == 60
    assert len(buttons) == 60

    # Per-frame ordering: move before button at indexes 2*i, 2*i+1.
    for frame in range(60):
        move_call = method_calls[2 * frame]
        button_call = method_calls[2 * frame + 1]
        assert move_call[0] == "_inject_mouse_move"
        assert move_call.args == (100 + frame, 200)
        assert button_call[0] == "_inject_mouse_button"
        assert button_call.args == (0, True)  # ImGui index 0 == LEFT


def test_drain_only_emits_move_when_no_events() -> None:
    """An idle frame drains exactly one ``_inject_mouse_move`` and nothing else."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    drain_bridge_into_ui(bridge, ui_native)

    assert ui_native.method_calls == [call._inject_mouse_move(0, 0)]


def test_drain_dispatches_wheel_with_accumulated_delta() -> None:
    """Three wheel ticks coalesced by the bridge collapse to one
    ``_inject_mouse_scroll`` with the summed delta."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_mouse_event(_wheel(0, 1))
    bridge.on_mouse_event(_wheel(0, 2))
    bridge.on_mouse_event(_wheel(0, 4))
    drain_bridge_into_ui(bridge, ui_native)

    scroll_calls = [c for c in ui_native.method_calls if c[0] == "_inject_mouse_scroll"]
    assert scroll_calls == [call._inject_mouse_scroll(0, 7)]


def test_drain_dispatches_modern_wheel_fields_without_truncation() -> None:
    """Modern ovstream wheel packets use float scroll_x/y fields."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_mouse_event(_wheel(0, 0, scroll_x=0.25, scroll_y=0.5))
    bridge.on_mouse_event(_wheel(0, 0, scroll_x=0.25, scroll_y=1.25))
    drain_bridge_into_ui(bridge, ui_native)

    scroll_calls = [c for c in ui_native.method_calls if c[0] == "_inject_mouse_scroll"]
    assert scroll_calls == [call._inject_mouse_scroll(0.5, 1.75)]


def test_drain_dispatches_keyboard_via_keymap() -> None:
    """Key code 0x41 (NVST 'A') maps through ``nvst_to_imgui_key`` to
    ImGui int 546 (``ImGuiKey_A``)."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_keyboard_event(_key(0x0041, down=True))
    bridge.on_keyboard_event(_key(0x0041, down=False))
    drain_bridge_into_ui(bridge, ui_native)

    key_calls = [c for c in ui_native.method_calls if c[0] == "_inject_key_event"]
    assert key_calls == [
        call._inject_key_event(546, True),
        call._inject_key_event(546, False),
    ]


# --------------------------------------------------------------------------
# Step 3.5 — modifier handling: verbatim steady state + disconnect cleanup
# --------------------------------------------------------------------------

# Mirror of ovui_widgets.app._input_bridge constants. Duplicated so the test
# describes its expectations independently of the production table.
_NVST_MF_SHIFT = 0x0001
_NVST_MF_ALT = 0x0004
_NVST_MF_CAPS_LOCK = 0x0010   # CapsLock — NOT right-shift on the runtime path
_NVST_MF_NUM_LOCK = 0x0020    # NumLock  — NOT right-ctrl on the runtime path
_NVST_KEY_LSHIFT_CODE = 0x0302
_NVST_KEY_RSHIFT_CODE = 0x0303
_NVST_KEY_RCONTROL_CODE = 0x0306
_NVST_KEY_RALT_CODE = 0x0309
_IMGUI_KEY_LEFT_SHIFT = 528
_IMGUI_KEY_LEFT_CTRL = 527
_IMGUI_KEY_RIGHT_SHIFT = 532
_IMGUI_KEY_RIGHT_CTRL = 531
_IMGUI_KEY_RIGHT_ALT = 533
_IMGUI_KEY_A = 546
_IMGUI_KEY_RESERVED_MOD_CTRL = 663
_IMGUI_KEY_RESERVED_MOD_SHIFT = 664
_IMGUI_KEY_RESERVED_MOD_ALT = 665
_IMGUI_KEY_RESERVED_MOD_SUPER = 666


def test_drain_modifier_steady_state_no_double_injection() -> None:
    """Plan acceptance for Step 3.5: feed (Shift down, A down, A up,
    Shift up) and assert the injected sequence is exactly four
    keyboard calls, in order, with no synthesised duplicates from
    modifier-mask diffing.
    """
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    # The SDK reports the post-event modifier mask: Shift down comes
    # with Shift bit set; A down/up while Shift held still carry the
    # bit; Shift up flips the mask back to 0.
    bridge.on_keyboard_event(_key(_NVST_KEY_LSHIFT_CODE, down=True, mods=_NVST_MF_SHIFT))
    bridge.on_keyboard_event(_key(0x0041, down=True, mods=_NVST_MF_SHIFT))
    bridge.on_keyboard_event(_key(0x0041, down=False, mods=_NVST_MF_SHIFT))
    bridge.on_keyboard_event(_key(_NVST_KEY_LSHIFT_CODE, down=False, mods=0))

    drain_bridge_into_ui(bridge, ui_native)

    key_calls = [c for c in ui_native.method_calls if c[0] == "_inject_key_event"]
    assert key_calls == [
        call._inject_key_event(_IMGUI_KEY_LEFT_SHIFT, True),   # Shift down
        call._inject_key_event(_IMGUI_KEY_A, True),            # A down
        call._inject_key_event(_IMGUI_KEY_A, False),           # A up
        call._inject_key_event(_IMGUI_KEY_LEFT_SHIFT, False),  # Shift up
    ]


def test_drain_disconnect_with_shift_held_emits_release() -> None:
    """Plan acceptance for Step 3.5: feed (Shift down, disconnect)
    and assert the injected sequence is exactly
    [ShiftLeft press, ShiftLeft release]. The release is synthesised
    by the bridge's on_connection(False) cleanup so ovui doesn't sit
    on a sticky Shift after the remote client drops."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_keyboard_event(_key(_NVST_KEY_LSHIFT_CODE, down=True, mods=_NVST_MF_SHIFT))
    bridge.on_connection(connected=False)

    drain_bridge_into_ui(bridge, ui_native)

    key_calls = [c for c in ui_native.method_calls if c[0] == "_inject_key_event"]
    assert key_calls == [
        call._inject_key_event(_IMGUI_KEY_LEFT_SHIFT, True),
        call._inject_key_event(_IMGUI_KEY_LEFT_SHIFT, False),
    ]


def test_drain_disconnect_with_rshift_held_emits_rshift_release_codex_repro() -> None:
    """Codex Step 3.5 NOT-GOOD reproduction. The runtime ovstream
    WebRTC handler delivers RSHIFT down with the *generic* Shift bit
    (``modifiers=0x0001``); the pre-fix bridge consulted the aggregate
    mask and emitted an LSHIFT release, leaving RSHIFT stuck. The
    side-aware fix tracks the actual ``key_code`` and synthesises an
    RSHIFT release.

    Expected drain output: ``[(532, True), (532, False)]`` — the same
    side the client pressed."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_keyboard_event(_key(_NVST_KEY_RSHIFT_CODE, down=True, mods=_NVST_MF_SHIFT))
    bridge.on_connection(connected=False)

    drain_bridge_into_ui(bridge, ui_native)

    key_calls = [
        (c.args[0], c.args[1])
        for c in ui_native.method_calls
        if c[0] == "_inject_key_event"
    ]
    assert key_calls == [
        (_IMGUI_KEY_RIGHT_SHIFT, True),
        (_IMGUI_KEY_RIGHT_SHIFT, False),
    ]


def test_drain_disconnect_with_rcontrol_and_ralt_uses_right_side() -> None:
    """RCONTROL and RALT also collapse to generic CONTROL/ALT bits in
    the WebRTC path; the fix must release the right-side ImGui keys
    based on the actual key_code, not the aggregate mask."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_keyboard_event(_key(_NVST_KEY_RCONTROL_CODE, down=True, mods=0x0002))
    bridge.on_keyboard_event(_key(_NVST_KEY_RALT_CODE, down=True, mods=0x0002 | 0x0004))
    bridge.on_connection(connected=False)

    drain_bridge_into_ui(bridge, ui_native)
    releases = [
        c.args[0]
        for c in ui_native.method_calls
        if c[0] == "_inject_key_event" and c.args[1] is False
    ]
    assert releases == [_IMGUI_KEY_RIGHT_CTRL, _IMGUI_KEY_RIGHT_ALT]


def test_drain_disconnect_after_caps_lock_bit_emits_no_release() -> None:
    """Codex regression guard: the runtime path uses bit ``0x0010`` for
    CapsLock (not right-shift). A KeyboardEvent that sets the CapsLock
    bit but does *not* press a modifier key must leave the held list
    empty, so disconnect synthesises no modifier releases. Only the
    real A-key press/release should reach the dispatcher."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_keyboard_event(_key(0x0041, down=True, mods=_NVST_MF_CAPS_LOCK))
    bridge.on_keyboard_event(_key(0x0041, down=False,
                                  mods=_NVST_MF_CAPS_LOCK | _NVST_MF_NUM_LOCK))
    bridge.on_connection(connected=False)

    drain_bridge_into_ui(bridge, ui_native)

    # ImGui modifier keys live in [527, 535) — LeftCtrl..Menu. Filter
    # the inject calls to that range so the A-key (546) press/release
    # is excluded, isolating any *modifier* release that would have
    # been synthesised by a buggy aggregate-mask cleanup.
    modifier_releases = [
        c
        for c in ui_native.method_calls
        if c[0] == "_inject_key_event"
        and 527 <= c.args[0] < 535
        and c.args[1] is False
    ]
    assert modifier_releases == []


def test_drain_disconnect_with_no_modifiers_held_emits_nothing() -> None:
    """Disconnect with mask zero is a no-op — no synthesised events
    enter the dispatch path."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_connection(connected=False)
    drain_bridge_into_ui(bridge, ui_native)

    assert not any(
        c[0] == "_inject_key_event" for c in ui_native.method_calls
    )


def test_drain_repeated_disconnect_does_not_re_emit_releases() -> None:
    """Idempotent cleanup: a second disconnect after the first must
    not produce another release for the modifier already cleaned up."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_keyboard_event(_key(_NVST_KEY_LSHIFT_CODE, down=True, mods=_NVST_MF_SHIFT))
    bridge.on_connection(connected=False)
    drain_bridge_into_ui(bridge, ui_native)
    ui_native.reset_mock()

    bridge.on_connection(connected=False)
    drain_bridge_into_ui(bridge, ui_native)

    # Second drain should only carry the unconditional mouse-move
    # injection — no keyboard releases.
    key_calls = [c for c in ui_native.method_calls if c[0] == "_inject_key_event"]
    assert key_calls == []


def test_drain_mouse_event_modifiers_submit_imgui_modifier_state() -> None:
    """Browser Alt+drag may carry Alt only on mouse packets."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_mouse_event(_button(10, 10, button=int(MouseButton.LEFT), down=True))
    bridge.on_mouse_event(MouseEvent(
        type=MouseEventType.BUTTON,
        modifiers=_NVST_MF_ALT,
        x=10,
        y=10,
        data=int(MouseButton.LEFT),
        data2=0,
        button_state=KeyState.DOWN,
    ))
    drain_bridge_into_ui(bridge, ui_native)

    assert ui_native.method_calls[-5:] == [
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_CTRL, False),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_SHIFT, False),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_ALT, True),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_SUPER, False),
        call._inject_mouse_button(0, True),
    ]


def test_drain_coalesced_move_modifiers_submit_before_mouse_move() -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_mouse_event(MouseEvent(
        type=MouseEventType.MOVE,
        modifiers=_NVST_MF_ALT,
        x=20,
        y=30,
        data=0,
        data2=0,
        button_state=KeyState.UP,
    ))
    drain_bridge_into_ui(bridge, ui_native)

    assert ui_native.method_calls == [
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_CTRL, False),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_SHIFT, False),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_ALT, True),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_SUPER, False),
        call._inject_mouse_move(20, 30),
    ]


def test_drain_plain_move_clears_previous_mouse_modifier_state() -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_mouse_event(MouseEvent(
        type=MouseEventType.MOVE,
        modifiers=_NVST_MF_ALT,
        x=20,
        y=30,
        data=0,
        data2=0,
        button_state=KeyState.UP,
    ))
    drain_bridge_into_ui(bridge, ui_native)
    assert ui_native.method_calls[:4] == [
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_CTRL, False),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_SHIFT, False),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_ALT, True),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_SUPER, False),
    ]

    ui_native.reset_mock()
    bridge.on_mouse_event(MouseEvent(
        type=MouseEventType.MOVE,
        modifiers=0,
        x=25,
        y=35,
        data=0,
        data2=0,
        button_state=KeyState.UP,
    ))
    drain_bridge_into_ui(bridge, ui_native)

    assert ui_native.method_calls == [
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_CTRL, False),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_SHIFT, False),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_ALT, False),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_SUPER, False),
        call._inject_mouse_move(25, 35),
    ]


def test_drain_mouse_button_release_clears_synthesized_modifier_state() -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_mouse_event(MouseEvent(
        type=MouseEventType.BUTTON,
        modifiers=_NVST_MF_ALT,
        x=10,
        y=10,
        data=int(MouseButton.LEFT),
        data2=0,
        button_state=KeyState.UP,
    ))
    drain_bridge_into_ui(bridge, ui_native)

    assert ui_native.method_calls[-9:] == [
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_CTRL, False),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_SHIFT, False),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_ALT, True),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_SUPER, False),
        call._inject_mouse_button(0, False),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_CTRL, False),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_SHIFT, False),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_ALT, False),
        call._inject_key_event(_IMGUI_KEY_RESERVED_MOD_SUPER, False),
    ]


def test_drain_skips_keys_without_imgui_equivalent() -> None:
    """NVST_KEY_YEN (0x5F) maps to ``ImGuiKey_None`` and must not be
    injected (would corrupt ImGui's key-state cache with 0 == None)."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_keyboard_event(_key(0x005F, down=True))
    drain_bridge_into_ui(bridge, ui_native)

    assert not any(
        c[0] == "_inject_key_event" for c in ui_native.method_calls
    )


def test_drain_dispatches_unicode_strings() -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_unicode("hello")
    bridge.on_unicode("世界")
    drain_bridge_into_ui(bridge, ui_native)

    text_calls = [c for c in ui_native.method_calls if c[0] == "_inject_text_input"]
    assert text_calls == [
        call._inject_text_input("hello"),
        call._inject_text_input("世界"),
    ]


def test_drain_drops_mousebutton_none() -> None:
    """``MouseButton.NONE`` (data=0) maps to ``imgui_button = -1`` and
    is silently dropped — the alternative is feeding -1 into ImGui's
    button array, which the validator at ``StandaloneInit.cpp:323``
    rejects."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_mouse_event(_button(10, 10, button=int(MouseButton.NONE), down=True))
    drain_bridge_into_ui(bridge, ui_native)

    assert not any(
        c[0] == "_inject_mouse_button" for c in ui_native.method_calls
    )


def test_drain_drops_out_of_range_buttons() -> None:
    """Defensive: a hypothetical ``button == 6`` from a future SDK
    revision yields ``imgui_button == 5`` which is out of ImGui's
    [0, 5) range and must be dropped."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_mouse_event(_button(10, 10, button=6, down=True))
    drain_bridge_into_ui(bridge, ui_native)

    assert not any(
        c[0] == "_inject_mouse_button" for c in ui_native.method_calls
    )


def test_drain_maps_every_mouse_button_to_imgui_index() -> None:
    """ovstream's MouseButton enum and ImGui's ImGuiMouseButton enum
    disagree on the order of MIDDLE and RIGHT — see imgui.h:2042–2047
    (Left=0, Right=1, Middle=2) vs ovstream's
    NONE=0/LEFT=1/MIDDLE=2/RIGHT=3/EXTRA1=4/EXTRA2=5. ovui's
    ``injectMouseButton`` (StandaloneInit.cpp:330–336) passes the int
    straight to ``io.AddMouseButtonEvent`` so the int we emit IS the
    ImGui index.

    Required mapping (Codex Step 3.3 review correction):
        LEFT (1)  -> 0
        RIGHT (3) -> 1   (ImGui Right is index 1, not 2)
        MIDDLE(2) -> 2   (ImGui Middle is index 2, not 1)
        EXTRA1(4) -> 3
        EXTRA2(5) -> 4
    """
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    expected = [
        (MouseButton.LEFT, 0),
        (MouseButton.RIGHT, 1),
        (MouseButton.MIDDLE, 2),
        (MouseButton.EXTRA1, 3),
        (MouseButton.EXTRA2, 4),
    ]
    for nvst_button, _imgui in expected:
        bridge.on_mouse_event(_button(0, 0, button=int(nvst_button), down=True))
    drain_bridge_into_ui(bridge, ui_native)

    button_calls = [c for c in ui_native.method_calls if c[0] == "_inject_mouse_button"]
    assert [c.args[0] for c in button_calls] == [imgui for _b, imgui in expected]


# --------------------------------------------------------------------------
# Step 3.4 — fixture-driven mouse-button mapping coverage.
#
# The plan acceptance for Step 3.4 reads:
#   "Fixture-driven test: feed each MouseButton enum value + Up/Down
#    state pair; capture the resulting _ui._inject_mouse_button call
#    args; assert the table holds exactly: LEFT(1)→ImGui 0, MIDDLE(2)→1,
#    RIGHT(3)→2, EXTRA1(4)→3, EXTRA2(5)→4, NONE(0)→no call."
#
# Codex's Step 3.3 review proved the plan's MIDDLE/RIGHT cells are
# stale — ovui's `injectMouseButton` passes the int straight to
# `io.AddMouseButtonEvent` and ImGui defines Right=1, Middle=2. The
# corrected table (now centralized in `_input_drain._NVST_TO_IMGUI_BUTTON`)
# is the source of truth used here.
# --------------------------------------------------------------------------

# (nvst_enum, expected_imgui_index, button_id_for_pytest_node)
_BUTTON_TABLE = [
    (MouseButton.LEFT, 0, "LEFT"),
    (MouseButton.RIGHT, 1, "RIGHT"),
    (MouseButton.MIDDLE, 2, "MIDDLE"),
    (MouseButton.EXTRA1, 3, "EXTRA1"),
    (MouseButton.EXTRA2, 4, "EXTRA2"),
]


@pytest.mark.parametrize(
    ("nvst_button", "expected_imgui"),
    [(b, i) for b, i, _name in _BUTTON_TABLE],
    ids=[f"{name}->ImGui{i}" for _b, i, name in _BUTTON_TABLE],
)
@pytest.mark.parametrize("pressed", [True, False], ids=["DOWN", "UP"])
def test_drain_button_pressed_state_pair(
    nvst_button: MouseButton, expected_imgui: int, pressed: bool,
) -> None:
    """Fixture-driven coverage of (button enum × Up/Down) — 5×2 = 10
    cases. Captures the actual ``_inject_mouse_button`` call and asserts
    both arguments: the ImGui index AND the pressed/released boolean.

    A regression in either dimension fails this test with a node id
    that names the offending button and state.
    """
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_mouse_event(_button(0, 0, button=int(nvst_button), down=pressed))
    drain_bridge_into_ui(bridge, ui_native)

    button_calls = [c for c in ui_native.method_calls if c[0] == "_inject_mouse_button"]
    assert button_calls == [call._inject_mouse_button(expected_imgui, pressed)]


@pytest.mark.parametrize("pressed", [True, False], ids=["DOWN", "UP"])
def test_drain_drops_mousebutton_none_in_either_state(pressed: bool) -> None:
    """``MouseButton.NONE`` is not a real button press; both an Up and a
    Down event with data=0 must drop. Pairs with the pressed-state
    coverage above to give a complete (button × state) matrix."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_mouse_event(_button(0, 0, button=int(MouseButton.NONE), down=pressed))
    drain_bridge_into_ui(bridge, ui_native)

    assert not any(
        c[0] == "_inject_mouse_button" for c in ui_native.method_calls
    )


def test_drain_does_not_swap_right_and_middle_buttons() -> None:
    """Regression guard for the Codex Step 3.3 NOT-GOOD finding: a
    naive ``imgui_button = data - 1`` shortcut sends MouseButton.RIGHT
    to ImGui index 2 (== Middle) and MouseButton.MIDDLE to index 1
    (== Right). This test fails loudly if that regresses."""
    bridge = RemoteInputBridge(width=_W, height=_H)
    ui_native = MagicMock()

    bridge.on_mouse_event(_button(0, 0, button=int(MouseButton.RIGHT), down=True))
    bridge.on_mouse_event(_button(0, 0, button=int(MouseButton.MIDDLE), down=True))
    drain_bridge_into_ui(bridge, ui_native)

    button_calls = [c for c in ui_native.method_calls if c[0] == "_inject_mouse_button"]
    assert [c.args[0] for c in button_calls] == [1, 2], (
        "RIGHT must inject as ImGui index 1 and MIDDLE as ImGui index 2; "
        "the previous subtract-one mapping had them swapped."
    )


# --------------------------------------------------------------------------
# Application wiring + main-loop ordering
# --------------------------------------------------------------------------


def test_application_drain_is_noop_when_no_bridge_set(headless_app) -> None:
    headless_app._ui_native = MagicMock()
    headless_app._drain_remote_input()
    headless_app._ui_native.assert_not_called()


def test_application_drain_is_noop_before_ui_native_cached(headless_app) -> None:
    """Until ``run_async`` runs, ``_ui_native`` is None. Drain must
    short-circuit rather than crash; otherwise a bridge registered too
    early (e.g. by a unit test) would explode."""
    headless_app._remote_input_bridge = RemoteInputBridge(width=_W, height=_H)
    assert headless_app._ui_native is None
    headless_app._drain_remote_input()  # must not raise


def test_application_drain_dispatches_to_cached_ui_native(headless_app) -> None:
    bridge = RemoteInputBridge(width=_W, height=_H)
    bridge.on_mouse_event(_move(50, 60))
    bridge.on_mouse_event(_button(50, 60, button=int(MouseButton.LEFT), down=True))

    ui_native = MagicMock()
    headless_app._ui_native = ui_native
    headless_app.set_remote_input_bridge(bridge)

    headless_app._drain_remote_input()

    assert ui_native.method_calls == [
        call._inject_mouse_move(50, 60),
        call._inject_mouse_button(0, True),
    ]


def test_application_set_remote_input_bridge_can_clear() -> None:
    from ovui_widgets.app.application import Application
    from ovui_widgets.common.selection import SelectionBus

    Application._instance = None
    SelectionBus._instance = None
    try:
        app = Application()
        bridge = RemoteInputBridge(width=_W, height=_H)
        app.set_remote_input_bridge(bridge)
        assert app._remote_input_bridge is bridge
        app.set_remote_input_bridge(None)
        assert app._remote_input_bridge is None
    finally:
        app.shutdown()
        Application._instance = None
        SelectionBus._instance = None


def test_run_async_drains_before_next_frame_in_main_loop() -> None:
    """Static-source check: the main loop body must call
    ``self._drain_remote_input()`` *before* ``await ui.next_frame()``.

    Mocking through ``run_async`` would require booting ovui, so the
    cheapest enforcement is a textual ordering assertion against the
    method source — guaranteeing the critical-path requirement from
    the plan ("drain before await ui.next_frame()") survives any
    refactor.
    """
    import re

    from ovui_widgets.app.application import Application

    src = inspect.getsource(Application.run_async)
    m = re.search(r"while self\._running", src)
    assert m, "Application.run_async has no while self._running loop"
    body = src[m.start():]
    drain_at = body.find("self._drain_remote_input()")
    next_frame_at = body.find("await ui.next_frame()")
    assert drain_at != -1, "Application.run_async loop body never calls _drain_remote_input"
    assert next_frame_at != -1, "Application.run_async loop body never awaits ui.next_frame"
    assert drain_at < next_frame_at, (
        "_drain_remote_input must precede ui.next_frame inside the "
        "while-loop so injected events land in the same tick's "
        "applyInjectedInput pass"
    )

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""NVST key code → ImGui key translation for the Tier 3 input bridge.

The Tier 3 livestream input bridge (issue #34) receives keyboard events
from the ovstream SDK as ``ovstream.KeyboardEvent`` instances whose
``key_code`` field carries an ``NvstKeyCode_t`` value (see
``kit-livestream/.../nvst/common/KeyDefs.h``). Those events are
forwarded into the running ImGui context via ``_ui._inject_key_event``,
which expects ``ImGuiKey`` integers. ``nvst_to_imgui_key`` is the
table-driven translation between the two enums.

The full table — and the rationale for each NVST code that drops to
``ImGuiKey_None`` — is documented in ``ovwidgets.app._input_keymap``;
this module is the executable mirror of that table.

Modifier diff-and-emit synthesis is intentionally not implemented here
(Codex review, finding 10b). Modifier presses arrive verbatim from the
SDK; the bridge only consults ``KeyboardEvent.modifiers`` to release
keys still held when the client disconnects.
"""

from __future__ import annotations

# ImGuiKey integers, mirroring imgui.h's ImGuiKey enum (named keys start
# at ImGuiKey_NamedKey_BEGIN = 512, sequentially assigned in declaration
# order). Held as plain ints so this module has no dependency on omni.ui
# being importable — it must be safe to load in pure-Python test
# environments where the native UI bindings are absent.
_IMGUI_KEY_NONE = 0

_IMGUI_KEY_TAB = 512
_IMGUI_KEY_LEFT_ARROW = 513
_IMGUI_KEY_RIGHT_ARROW = 514
_IMGUI_KEY_UP_ARROW = 515
_IMGUI_KEY_DOWN_ARROW = 516
_IMGUI_KEY_PAGE_UP = 517
_IMGUI_KEY_PAGE_DOWN = 518
_IMGUI_KEY_HOME = 519
_IMGUI_KEY_END = 520
_IMGUI_KEY_INSERT = 521
_IMGUI_KEY_DELETE = 522
_IMGUI_KEY_BACKSPACE = 523
_IMGUI_KEY_SPACE = 524
_IMGUI_KEY_ENTER = 525
_IMGUI_KEY_ESCAPE = 526
_IMGUI_KEY_LEFT_CTRL = 527
_IMGUI_KEY_LEFT_SHIFT = 528
_IMGUI_KEY_LEFT_ALT = 529
_IMGUI_KEY_LEFT_SUPER = 530
_IMGUI_KEY_RIGHT_CTRL = 531
_IMGUI_KEY_RIGHT_SHIFT = 532
_IMGUI_KEY_RIGHT_ALT = 533
_IMGUI_KEY_RIGHT_SUPER = 534
_IMGUI_KEY_MENU = 535
_IMGUI_KEY_0 = 536
_IMGUI_KEY_A = 546
_IMGUI_KEY_F1 = 572
_IMGUI_KEY_APOSTROPHE = 596
_IMGUI_KEY_COMMA = 597
_IMGUI_KEY_MINUS = 598
_IMGUI_KEY_PERIOD = 599
_IMGUI_KEY_SLASH = 600
_IMGUI_KEY_SEMICOLON = 601
_IMGUI_KEY_EQUAL = 602
_IMGUI_KEY_LEFT_BRACKET = 603
_IMGUI_KEY_BACKSLASH = 604
_IMGUI_KEY_RIGHT_BRACKET = 605
_IMGUI_KEY_GRAVE_ACCENT = 606
_IMGUI_KEY_CAPS_LOCK = 607
_IMGUI_KEY_SCROLL_LOCK = 608
_IMGUI_KEY_NUM_LOCK = 609
_IMGUI_KEY_PRINT_SCREEN = 610
_IMGUI_KEY_PAUSE = 611
_IMGUI_KEY_KEYPAD_0 = 612
_IMGUI_KEY_KEYPAD_DECIMAL = 622
_IMGUI_KEY_KEYPAD_DIVIDE = 623
_IMGUI_KEY_KEYPAD_MULTIPLY = 624
_IMGUI_KEY_KEYPAD_SUBTRACT = 625
_IMGUI_KEY_KEYPAD_ADD = 626
_IMGUI_KEY_KEYPAD_ENTER = 627
_IMGUI_KEY_KEYPAD_EQUAL = 628
_IMGUI_KEY_OEM102 = 631


def _build_table() -> dict[int, int]:
    table: dict[int, int] = {
        # OEM-mapped ASCII punctuation
        0x0027: _IMGUI_KEY_APOSTROPHE,
        0x002C: _IMGUI_KEY_COMMA,
        0x002D: _IMGUI_KEY_MINUS,
        0x002E: _IMGUI_KEY_PERIOD,
        0x002F: _IMGUI_KEY_SLASH,
        0x003B: _IMGUI_KEY_SEMICOLON,
        0x003D: _IMGUI_KEY_EQUAL,
        0x005B: _IMGUI_KEY_LEFT_BRACKET,
        0x005C: _IMGUI_KEY_BACKSLASH,
        0x005D: _IMGUI_KEY_RIGHT_BRACKET,
        0x005E: _IMGUI_KEY_OEM102,
        # NVST "extended ASCII" codes that Kit's InputHandler.cpp:249–251
        # binds to real ImGui keys: AGRAVE → GraveAccent (the `~`/backtick
        # row above Tab on US layouts), MULTIPLY → KeypadMultiply, and
        # DIVISION → KeypadDivide. The NVST enum reuses Latin-1 code
        # points for these because no plain-ASCII slot was available, but
        # the SDK still delivers them on every numpad press.
        0x00C0: _IMGUI_KEY_GRAVE_ACCENT,
        0x00D7: _IMGUI_KEY_KEYPAD_MULTIPLY,
        0x00F7: _IMGUI_KEY_KEYPAD_DIVIDE,
        # Space
        0x0020: _IMGUI_KEY_SPACE,
        # Misc / editing
        0x0100: _IMGUI_KEY_ESCAPE,
        0x0101: _IMGUI_KEY_TAB,
        0x0102: _IMGUI_KEY_TAB,         # BACKTAB collapses to Tab; ImGui has no separate code
        0x0103: _IMGUI_KEY_BACKSPACE,
        0x0104: _IMGUI_KEY_ENTER,       # RETURN
        0x0105: _IMGUI_KEY_ENTER,       # ENTER
        0x0106: _IMGUI_KEY_INSERT,
        0x0107: _IMGUI_KEY_DELETE,
        0x0108: _IMGUI_KEY_PAUSE,
        0x0109: _IMGUI_KEY_PRINT_SCREEN,
        # Cursor / navigation
        0x0200: _IMGUI_KEY_HOME,
        0x0201: _IMGUI_KEY_END,
        0x0202: _IMGUI_KEY_LEFT_ARROW,
        0x0203: _IMGUI_KEY_UP_ARROW,
        0x0204: _IMGUI_KEY_RIGHT_ARROW,
        0x0205: _IMGUI_KEY_DOWN_ARROW,
        0x0206: _IMGUI_KEY_PAGE_UP,
        0x0207: _IMGUI_KEY_PAGE_DOWN,
        # Modifiers — generic codes collapse to the left-side ImGui key
        0x0301: _IMGUI_KEY_LEFT_SHIFT,   # SHIFT
        0x0302: _IMGUI_KEY_LEFT_SHIFT,   # LSHIFT
        0x0303: _IMGUI_KEY_RIGHT_SHIFT,  # RSHIFT
        0x0304: _IMGUI_KEY_LEFT_CTRL,    # CONTROL
        0x0305: _IMGUI_KEY_LEFT_CTRL,    # LCONTROL
        0x0306: _IMGUI_KEY_RIGHT_CTRL,   # RCONTROL
        0x0307: _IMGUI_KEY_LEFT_ALT,     # ALT
        0x0308: _IMGUI_KEY_LEFT_ALT,     # LALT
        0x0309: _IMGUI_KEY_RIGHT_ALT,    # RALT
        0x0310: _IMGUI_KEY_LEFT_SUPER,   # META
        0x0311: _IMGUI_KEY_LEFT_SUPER,   # LMETA
        0x0312: _IMGUI_KEY_RIGHT_SUPER,  # RMETA
        # Lock keys
        0x0501: _IMGUI_KEY_CAPS_LOCK,
        0x0502: _IMGUI_KEY_NUM_LOCK,
        0x0503: _IMGUI_KEY_SCROLL_LOCK,
        # Numpad arithmetic
        0x060A: _IMGUI_KEY_KEYPAD_ADD,
        0x060B: _IMGUI_KEY_KEYPAD_SUBTRACT,
        0x060C: _IMGUI_KEY_KEYPAD_DECIMAL,
        # Numpad navigation aliases (NumLock off)
        0x060D: _IMGUI_KEY_INSERT,        # KP_INSERT
        0x060E: _IMGUI_KEY_END,           # KP_END
        0x060F: _IMGUI_KEY_DOWN_ARROW,    # KP_DOWN
        0x0610: _IMGUI_KEY_PAGE_DOWN,     # KP_PAGE_DOWN
        0x0611: _IMGUI_KEY_LEFT_ARROW,    # KP_LEFT
        # 0x0612 KP_CLEAR — no ImGui equivalent, dropped via .get()
        0x0613: _IMGUI_KEY_RIGHT_ARROW,   # KP_RIGHT
        0x0614: _IMGUI_KEY_HOME,          # KP_HOME
        0x0615: _IMGUI_KEY_UP_ARROW,      # KP_UP
        0x0616: _IMGUI_KEY_PAGE_UP,       # KP_PAGE_UP
        0x0617: _IMGUI_KEY_DELETE,        # KP_DELETE
    }

    # ASCII digits 0–9 → ImGuiKey_0..9 (sequential)
    for i in range(10):
        table[0x0030 + i] = _IMGUI_KEY_0 + i
    # ASCII letters A–Z → ImGuiKey_A..Z (sequential)
    for i in range(26):
        table[0x0041 + i] = _IMGUI_KEY_A + i
    # F1–F24 (NVST 0x0400–0x0417) → ImGuiKey_F1..F24 (572–595, sequential)
    for i in range(24):
        table[0x0400 + i] = _IMGUI_KEY_F1 + i
    # Numpad digits KP_0..9 (NVST 0x0600–0x0609) → ImGuiKey_Keypad0..9 (612–621)
    for i in range(10):
        table[0x0600 + i] = _IMGUI_KEY_KEYPAD_0 + i

    return table


_NVST_TO_IMGUI: dict[int, int] = _build_table()


def nvst_to_imgui_key(key_code: int) -> int:
    """Translate an NVST/ovstream ``KeyboardEvent.key_code`` to an ImGui key int.

    Args:
        key_code: An ``NvstKeyCode_t`` value as delivered in
            :class:`ovstream.KeyboardEvent`. Out-of-range integers are
            tolerated.

    Returns:
        The matching ``ImGuiKey`` integer suitable for
        ``omni.ui._ui._inject_key_event``. Returns ``0``
        (``ImGuiKey_None``) for codes with no ImGui equivalent — Asian
        IME toggles, extended ASCII, the broadcast sentinel
        ``NVST_KEY_ALL``, etc. Callers should drop events that resolve
        to ``0`` rather than inject them.
    """
    return _NVST_TO_IMGUI.get(key_code, _IMGUI_KEY_NONE)

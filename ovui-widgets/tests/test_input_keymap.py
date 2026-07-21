# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Table-driven tests for ovui_widgets.app._input_keymap.nvst_to_imgui_key.

Every row in ovui_widgets.app._input_keymap is asserted here. If the design
table changes, this file changes in lockstep.
"""

from __future__ import annotations

import pytest

from ovui_widgets.app._input_keymap import nvst_to_imgui_key

# --------------------------------------------------------------------------
# Mapped rows — (NVST code, NVST symbolic name, expected ImGui key int)
# --------------------------------------------------------------------------

# Punctuation / OEM-mapped ASCII
_PUNCTUATION = [
    (0x0027, "NVST_KEY_APOSTROPHE", 596),
    (0x002C, "NVST_KEY_COMMA", 597),
    (0x002D, "NVST_KEY_MINUS", 598),
    (0x002E, "NVST_KEY_PERIOD", 599),
    (0x002F, "NVST_KEY_SLASH", 600),
    (0x003B, "NVST_KEY_SEMICOLON", 601),
    (0x003D, "NVST_KEY_EQUAL", 602),
    (0x005B, "NVST_KEY_BRACKETLEFT", 603),
    (0x005C, "NVST_KEY_BACKSLASH", 604),
    (0x005D, "NVST_KEY_BRACKETRIGHT", 605),
    (0x005E, "NVST_KEY_NONUS_BACKSLASH", 631),
    # Extended-ASCII codes that Kit's InputHandler.cpp:249–251 binds to
    # real ImGui keys (Codex Step 3.1 review correction):
    (0x00C0, "NVST_KEY_AGRAVE", 606),       # ImGuiKey_GraveAccent
    (0x00D7, "NVST_KEY_MULTIPLY", 624),     # ImGuiKey_KeypadMultiply
    (0x00F7, "NVST_KEY_DIVISION", 623),     # ImGuiKey_KeypadDivide
]

# Space + ASCII digits + ASCII letters
_PRINTABLE = (
    [(0x0020, "NVST_KEY_SPACE", 524)]
    + [(0x0030 + i, f"NVST_KEY_{i}", 536 + i) for i in range(10)]
    + [(0x0041 + i, f"NVST_KEY_{chr(0x41 + i)}", 546 + i) for i in range(26)]
)

# Misc / editing keys
_MISC = [
    (0x0100, "NVST_KEY_ESCAPE", 526),
    (0x0101, "NVST_KEY_TAB", 512),
    (0x0102, "NVST_KEY_BACKTAB", 512),
    (0x0103, "NVST_KEY_BACKSPACE", 523),
    (0x0104, "NVST_KEY_RETURN", 525),
    (0x0105, "NVST_KEY_ENTER", 525),
    (0x0106, "NVST_KEY_INSERT", 521),
    (0x0107, "NVST_KEY_DELETE", 522),
    (0x0108, "NVST_KEY_PAUSE", 611),
    (0x0109, "NVST_KEY_PRINT", 610),
]

# Cursor / navigation
_CURSOR = [
    (0x0200, "NVST_KEY_HOME", 519),
    (0x0201, "NVST_KEY_END", 520),
    (0x0202, "NVST_KEY_LEFT", 513),
    (0x0203, "NVST_KEY_UP", 515),
    (0x0204, "NVST_KEY_RIGHT", 514),
    (0x0205, "NVST_KEY_DOWN", 516),
    (0x0206, "NVST_KEY_PAGE_UP", 517),
    (0x0207, "NVST_KEY_PAGE_DOWN", 518),
]

# Modifier keys (generic + L*/R* variants)
_MODIFIERS = [
    (0x0301, "NVST_KEY_SHIFT", 528),
    (0x0302, "NVST_KEY_LSHIFT", 528),
    (0x0303, "NVST_KEY_RSHIFT", 532),
    (0x0304, "NVST_KEY_CONTROL", 527),
    (0x0305, "NVST_KEY_LCONTROL", 527),
    (0x0306, "NVST_KEY_RCONTROL", 531),
    (0x0307, "NVST_KEY_ALT", 529),
    (0x0308, "NVST_KEY_LALT", 529),
    (0x0309, "NVST_KEY_RALT", 533),
    (0x0310, "NVST_KEY_META", 530),
    (0x0311, "NVST_KEY_LMETA", 530),
    (0x0312, "NVST_KEY_RMETA", 534),
]

# Function keys F1–F24
_FUNCTION = [
    (0x0400 + i, f"NVST_KEY_F{i + 1}", 572 + i) for i in range(24)
]

# Lock keys
_LOCKS = [
    (0x0501, "NVST_KEY_CAPS_LOCK", 607),
    (0x0502, "NVST_KEY_NUM_LOCK", 609),
    (0x0503, "NVST_KEY_SCROLL_LOCK", 608),
]

# Numpad — digits + arithmetic
_NUMPAD_NUMERIC = (
    [(0x0600 + i, f"NVST_KEY_KP_{i}", 612 + i) for i in range(10)]
    + [
        (0x060A, "NVST_KEY_ADD", 626),
        (0x060B, "NVST_KEY_SUBTRACT", 625),
        (0x060C, "NVST_KEY_DECIMAL", 622),
    ]
)

# Numpad — NumLock-off navigation aliases
_NUMPAD_NAV = [
    (0x060D, "NVST_KEY_KP_INSERT", 521),
    (0x060E, "NVST_KEY_KP_END", 520),
    (0x060F, "NVST_KEY_KP_DOWN", 516),
    (0x0610, "NVST_KEY_KP_PAGE_DOWN", 518),
    (0x0611, "NVST_KEY_KP_LEFT", 513),
    (0x0613, "NVST_KEY_KP_RIGHT", 514),
    (0x0614, "NVST_KEY_KP_HOME", 519),
    (0x0615, "NVST_KEY_KP_UP", 515),
    (0x0616, "NVST_KEY_KP_PAGE_UP", 517),
    (0x0617, "NVST_KEY_KP_DELETE", 522),
]

_ALL_MAPPED = (
    _PUNCTUATION
    + _PRINTABLE
    + _MISC
    + _CURSOR
    + _MODIFIERS
    + _FUNCTION
    + _LOCKS
    + _NUMPAD_NUMERIC
    + _NUMPAD_NAV
)


@pytest.mark.parametrize(
    ("nvst_code", "expected_imgui"),
    [(code, imgui) for code, _name, imgui in _ALL_MAPPED],
    ids=[name for _code, name, _imgui in _ALL_MAPPED],
)
def test_nvst_to_imgui_mapped_rows(nvst_code: int, expected_imgui: int) -> None:
    assert nvst_to_imgui_key(nvst_code) == expected_imgui


# --------------------------------------------------------------------------
# Codes that drop to ImGuiKey_None (0)
# --------------------------------------------------------------------------

_DROPPED = [
    (0x0000, "NVST_KEY_NONE"),
    (0x005F, "NVST_KEY_YEN"),
    (0x0060, "NVST_KEY_HANGUL"),
    (0x0061, "NVST_KEY_HANJA"),
    (0x0062, "NVST_KEY_RO"),
    (0x010A, "NVST_KEY_CLEAR"),
    (0x01F0, "NVST_KEY_HIRAGANA_KATAKANA"),
    (0x01F1, "NVST_KEY_HENKAN_ZENKOUHO"),
    (0x01F2, "NVST_KEY_MUHENKAN"),
    (0x0612, "NVST_KEY_KP_CLEAR"),
    (0xFFFF, "NVST_KEY_ALL"),
    # Out-of-range / never-emitted values to confirm the function does not raise.
    (0x0028, "unmapped_in_ASCII_punct_gap"),
    (0x00FF, "unmapped_extended_ASCII"),
    (0x0618, "NVST_KEY_MAX_sentinel"),
    (-1, "negative_value"),
]


@pytest.mark.parametrize(
    ("nvst_code",),
    [(code,) for code, _name in _DROPPED],
    ids=[name for _code, name in _DROPPED],
)
def test_nvst_to_imgui_dropped(nvst_code: int) -> None:
    assert nvst_to_imgui_key(nvst_code) == 0


# --------------------------------------------------------------------------
# Coverage sanity: every NVST code in the SDK enum is accounted for as
# either mapped or explicitly dropped. Catches the case where someone
# adds a code to KeyDefs.h and forgets to extend the table.
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Codex Step 3.1 review correction — direct assertions that fail on the
# pre-fix behavior (where these three NVST codes returned 0). Kept as a
# standalone test so a regression in the table immediately surfaces with
# a clear failure message instead of being hidden behind a parametrized
# row name.
# --------------------------------------------------------------------------

def test_grave_accent_and_keypad_operators_are_mapped_not_dropped() -> None:
    # NVST_KEY_AGRAVE → ImGuiKey_GraveAccent (Kit InputHandler.cpp:249,
    # imgui.h ImGuiKey_GraveAccent).
    assert nvst_to_imgui_key(0x00C0) == 606
    # NVST_KEY_MULTIPLY → ImGuiKey_KeypadMultiply (Kit
    # InputHandler.cpp:250, imgui.h ImGuiKey_KeypadMultiply).
    assert nvst_to_imgui_key(0x00D7) == 624
    # NVST_KEY_DIVISION → ImGuiKey_KeypadDivide (Kit
    # InputHandler.cpp:251, imgui.h ImGuiKey_KeypadDivide).
    assert nvst_to_imgui_key(0x00F7) == 623


def test_every_sdk_code_is_classified() -> None:
    mapped_codes = {code for code, _name, _imgui in _ALL_MAPPED}
    dropped_codes = {code for code, _name in _DROPPED}
    classified = mapped_codes | dropped_codes

    # Full enumeration of NvstKeyCode_t from KeyDefs.h.
    sdk_codes = (
        # OEM-mapped ASCII
        {
            0x0027, 0x002C, 0x002D, 0x002E, 0x002F, 0x003B, 0x003D,
            0x005B, 0x005C, 0x005D, 0x005E, 0x005F, 0x0060, 0x0061, 0x0062,
        }
        # ASCII digits, letters, space
        | {0x0020}
        | set(range(0x0030, 0x003A))
        | set(range(0x0041, 0x005B))
        # Extended ASCII
        | {0x00C0, 0x00D7, 0x00F7}
        # Misc
        | set(range(0x0100, 0x010B))
        # Japanese 106 toggles
        | {0x01F0, 0x01F1, 0x01F2}
        # Cursor
        | set(range(0x0200, 0x0208))
        # Modifiers
        | set(range(0x0301, 0x030A))
        | set(range(0x0310, 0x0313))
        # F1–F24
        | set(range(0x0400, 0x0418))
        # Lock keys
        | set(range(0x0501, 0x0504))
        # Numpad
        | set(range(0x0600, 0x0618))
        # Sentinels
        | {0x0000, 0xFFFF}
    )
    missing = sdk_codes - classified
    assert not missing, f"NVST codes not covered by mapping or drop list: {sorted(missing)}"

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Normalize native and injected keys without importing an application."""

# ImGui named-key codes. Real GLFW window input reports printable letters and
# non-printable shortcuts as ASCII/GLFW values, while the ovui Inspector and
# remote input bridge inject ImGuiKey values. Normalize both sources before
# application shortcut dispatch so Delete, F2, arrows and letter chords follow
# the same shipped UI path.
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
_IMGUI_KEY_0 = 536
_IMGUI_KEY_A = 546
_IMGUI_KEY_Z = _IMGUI_KEY_A + 25
_IMGUI_KEY_F1 = 572
_IMGUI_TO_GLFW_KEY = {
    _IMGUI_KEY_TAB: 258,
    _IMGUI_KEY_LEFT_ARROW: 263,
    _IMGUI_KEY_RIGHT_ARROW: 262,
    _IMGUI_KEY_UP_ARROW: 265,
    _IMGUI_KEY_DOWN_ARROW: 264,
    _IMGUI_KEY_PAGE_UP: 266,
    _IMGUI_KEY_PAGE_DOWN: 267,
    _IMGUI_KEY_HOME: 268,
    _IMGUI_KEY_END: 269,
    _IMGUI_KEY_INSERT: 260,
    _IMGUI_KEY_DELETE: 261,
    _IMGUI_KEY_BACKSPACE: 259,
    _IMGUI_KEY_SPACE: ord(" "),
    _IMGUI_KEY_ENTER: 257,
    _IMGUI_KEY_ESCAPE: 256,
}


def normalize_printable_key(key: int) -> int:
    mapped = _IMGUI_TO_GLFW_KEY.get(key)
    if mapped is not None:
        return mapped
    if _IMGUI_KEY_0 <= key < _IMGUI_KEY_0 + 10:
        return ord("0") + (key - _IMGUI_KEY_0)
    if _IMGUI_KEY_A <= key <= _IMGUI_KEY_Z:
        return ord("A") + (key - _IMGUI_KEY_A)
    if _IMGUI_KEY_F1 <= key < _IMGUI_KEY_F1 + 24:
        return 290 + (key - _IMGUI_KEY_F1)
    return key


def is_text_input_active() -> bool:
    """Return ``True`` while an ovui text input owns the keyboard.

    True while a ``StringField`` is edited, or while a ``FloatDrag`` /
    ``IntDrag`` is in keyboard-edit mode. Application shortcuts use it so that
    a key the field edits (Backspace, Delete) does not also run a global
    action. Returns ``False`` when the ovui build has no standalone backend or
    predates ``omni.ui.standalone.is_text_input_active``.
    """
    try:
        from omni.ui import standalone
    except Exception:
        return False
    query = getattr(standalone, "is_text_input_active", None)
    if query is None:
        return False
    try:
        return bool(query())
    except Exception:
        return False

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tier 3 input bridge → ovui native input dispatcher.

The :class:`ovwidgets.app._input_bridge.RemoteInputBridge` accumulates events
on the ovstream worker thread; this module is the main-loop side that
translates them into ``omni.ui._ui._inject_*`` calls.

Critical ordering: the dispatcher must run **before**
``await ui.next_frame()`` so the injected events land in *that* tick's
ImGui IO. ovui's ``HeadlessVulkanPlatform.cpp`` runs
``applyInjectedInput()`` at line 485, immediately before
``ImGui::NewFrame()`` at line 487; an event injected after the
``next_frame`` await would not be seen until the *next* tick.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ovstream import KeyboardEvent, KeyState, MouseEvent, MouseEventType

from ovwidgets.app._input_bridge import RemoteInputBridge
from ovwidgets.app._input_keymap import nvst_to_imgui_key

# ovstream's ``MouseButton`` enum and ImGui's ``ImGuiMouseButton_`` enum
# disagree on the order of the middle and right buttons:
#
#   ovstream (NONE=0, LEFT=1, MIDDLE=2, RIGHT=3, EXTRA1=4, EXTRA2=5)
#   ImGui    (Left=0, Right=1, Middle=2, …)                 — imgui.h:2042–2047
#
# ovui's ``injectMouseButton(int button, bool pressed)`` passes the int
# straight to ``io.AddMouseButtonEvent`` (StandaloneInit.cpp:330–336),
# so the integer fed in IS the ImGui button index. Use an explicit
# table — a subtract-one shortcut would silently swap MIDDLE and RIGHT.
_NVST_TO_IMGUI_BUTTON: dict[int, int] = {
    1: 0,   # MouseButton.LEFT   → ImGuiMouseButton_Left   (0)
    3: 1,   # MouseButton.RIGHT  → ImGuiMouseButton_Right  (1)
    2: 2,   # MouseButton.MIDDLE → ImGuiMouseButton_Middle (2)
    4: 3,   # MouseButton.EXTRA1 → 3
    5: 4,   # MouseButton.EXTRA2 → 4
}


def _nvst_printable_char(key_code: int, modifiers: int) -> str:
    """Return the printable character for *key_code* under *modifiers*, or ''.

    The NVST SDK delivers keyboard events as physical key codes only; ImGui's
    InputText widgets additionally require ``io.AddInputCharactersUTF8`` to
    insert a glyph into the edit buffer.  This function synthesises that
    character for the printable ASCII subset of the NVST code space:

        0x20        → space
        0x30–0x39   → digits 0–9 (identical to ASCII code points)
        0x41–0x5A   → letter keys A–Z (NVST always uses uppercase VK codes)

    Shift state is bit 0 of *modifiers* (``kModShift``, KeyDefs.h).
    CapsLock state is bit 4 (``kModCapsLock``).  Letters are uppercase when
    Shift XOR CapsLock is set, matching standard keyboard behaviour.

    Control (bit 1, ``kModControl``) and Alt (bit 2, ``kModAlt``) suppress
    character synthesis — Ctrl+key and Alt+key combos are accelerators, not
    text input.
    """
    if modifiers & 0x0006:  # kModControl | kModAlt
        return ''
    if key_code == 0x0020:
        return ' '
    if 0x0030 <= key_code <= 0x0039:
        return chr(key_code)
    if 0x0041 <= key_code <= 0x005A:
        shift = bool(modifiers & 0x0001)
        caps  = bool(modifiers & 0x0010)
        return chr(key_code) if (shift ^ caps) else chr(key_code + 32)
    return ''


def drain_bridge_into_ui(
    bridge: RemoteInputBridge,
    ui_native: Any,
    *,
    on_left_click: Optional[Callable[[int, int], None]] = None,
    on_char: Optional[Callable[[str], None]] = None,
) -> None:
    """Drain *bridge* and inject every event into *ui_native*.

    *ui_native* is the ``omni.ui._ui`` C-binding submodule (or any
    object exposing the same ``_inject_*`` surface — a mock works for
    tests).

    Mouse-position injection is unconditional: the latest cursor
    coordinates always go in first so subsequent button/wheel events
    fire at the up-to-date hover target. Discrete events are dispatched
    in the order they were enqueued.

    The function never raises on bridge contents — unmappable keys
    (``ImGuiKey_None``), the ``MouseButton.NONE`` button, and out-of-
    range button indices are silently dropped rather than fed into the
    ImGui IO.

    *on_left_click*, if provided, is called with the current ``(x, y)``
    stream coordinates whenever a left-button DOWN event is drained.  The
    application uses this to synthesise widget focus for widgets (such as
    the Stage Browser filter bar) whose ``set_mouse_pressed_fn`` callbacks
    do not fire from ImGui IO injection alone.  The callback runs before
    ``ui.next_frame()``, so any programmatic focus changes it makes land
    in the same tick.

    *on_char*, if provided, is called with each printable ASCII character
    synthesised from a key-down event (via :func:`_nvst_printable_char`).
    The application uses this to route typed characters to widget models
    (e.g. the Stage Browser filter) that require direct model updates
    because ``io.AddInputCharactersUTF8`` alone is insufficient when the
    target widget hasn't captured ImGui keyboard focus.
    """
    (mouse_x, mouse_y), events = bridge.drain()
    ui_native._inject_mouse_move(int(mouse_x), int(mouse_y))

    for event in events:
        if isinstance(event, MouseEvent):
            if event.type == MouseEventType.BUTTON:
                imgui_button = _NVST_TO_IMGUI_BUTTON.get(int(event.data))
                # ``MouseButton.NONE`` (0) and any future SDK addition
                # outside the table drop silently — feeding an
                # unrecognised index into ovui would corrupt
                # ``MouseDown[]`` (the inject helper takes the int
                # verbatim and indexes a fixed-size array).
                if imgui_button is not None:
                    ui_native._inject_mouse_button(
                        imgui_button,
                        event.button_state == KeyState.DOWN,
                    )
                    if (imgui_button == 0
                            and event.button_state == KeyState.DOWN
                            and on_left_click is not None):
                        on_left_click(int(mouse_x), int(mouse_y))
                continue
            if event.type == MouseEventType.WHEEL:
                ui_native._inject_mouse_scroll(int(event.data), int(event.data2))
                continue
            # MouseEventType.MOVE never reaches the deque (it coalesces
            # into the atomic position read above). Defensive: skip
            # silently rather than raise if the bridge ever changes.
            continue

        if isinstance(event, KeyboardEvent):
            imgui_key = nvst_to_imgui_key(int(event.key_code))
            if imgui_key != 0:
                ui_native._inject_key_event(
                    imgui_key,
                    event.key_state == KeyState.DOWN,
                )
            if event.key_state == KeyState.DOWN:
                ch = _nvst_printable_char(int(event.key_code), int(event.modifiers))
                if ch:
                    ui_native._inject_text_input(ch)
                    if on_char is not None:
                        on_char(ch)
            continue

        if isinstance(event, str):
            ui_native._inject_text_input(event)
            continue

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""``omni.ui.standalone.is_text_input_active()`` while a number field is edited.

an application shortcut handler (``Window.set_key_pressed_fn``)
receives Backspace and Delete even while a ``FloatDrag`` or ``IntDrag`` is in
keyboard-edit mode and edits its text. The USD Viewer ran its prim-delete
shortcut on those keys. The handler must be able to tell that a text input
owns the key: ``is_text_input_active()`` must be ``True`` inside the key
callback for the keys the field edits, and ``False`` when no field is edited.

The fields are put in keyboard-edit mode with an injected double-click and
edited with injected keys, the same input path as a user.
"""

from __future__ import annotations

import asyncio

import omni.ui as ui
from omni.ui import _ui
from omni.ui import standalone
from test_base import OmniUiTest

# ImGuiKey values, as injected by the ovui inspector.
_KEY_HOME = 519
_KEY_END = 520
_KEY_DELETE = 522
_KEY_BACKSPACE = 523
_KEY_ENTER = 525
# Native (GLFW) codes the key callback receives.
_NATIVE_DELETE = 261
_NATIVE_BACKSPACE = 259


class TestTextInputActive(OmniUiTest):
    async def _press(self, key: int) -> None:
        _ui._inject_key_event(key, True)
        await self.wait_n_updates(1)
        _ui._inject_key_event(key, False)
        await self.wait_n_updates(1)

    async def _double_click(self, widget) -> None:
        # Let ImGui's double-click time (0.30 s) pass since the last click, so
        # this pair is not counted as a third and fourth click.
        await asyncio.sleep(0.5)
        x = widget.screen_position_x + widget.computed_width / 2
        y = widget.screen_position_y + widget.computed_height / 2
        _ui._inject_mouse_move(float(x), float(y))
        await self.wait_n_updates(1)
        for _ in range(2):
            _ui._inject_mouse_button(0, True)
            await self.next_frame()
            _ui._inject_mouse_button(0, False)
            await self.next_frame()
        await self.wait_n_updates(2)

    async def _edit(self, window, seen, widget, move_key, edit_key, native_key, presses, text):
        await self._double_click(widget)
        self.assertTrue(standalone.is_text_input_active(), "field did not enter keyboard-edit mode")
        await self._press(move_key)
        seen.clear()
        for _ in range(presses):
            await self._press(edit_key)
        # The window's key callback saw the key, and at that moment the
        # field owned the keyboard.
        edit_events = [active for key, active in seen if key == native_key]
        self.assertTrue(edit_events, f"key callback did not receive key {native_key}: {seen}")
        self.assertTrue(all(edit_events), f"is_text_input_active() was False in the key callback: {seen}")
        _ui._inject_text_input(text)
        await self.wait_n_updates(1)
        await self._press(_KEY_ENTER)
        await self.wait_n_updates(2)
        self.assertFalse(standalone.is_text_input_active(), "text input still active after Enter")

    async def test_number_field_edit_owns_delete_and_backspace(self):
        window = await self.create_test_window(256, 128)
        float_model = ui.SimpleFloatModel(2.0)
        int_model = ui.SimpleIntModel(42)
        with window.frame:
            with ui.VStack(height=0, spacing=8):
                float_drag = ui.FloatDrag(float_model, height=24)
                int_drag = ui.IntDrag(int_model, height=24)
        seen = []

        def on_key(key, modifiers, pressed):
            if pressed:
                seen.append((int(key), standalone.is_text_input_active()))

        window.set_key_pressed_fn(on_key)
        await self.wait_n_updates(3)
        self.assertFalse(standalone.is_text_input_active())

        await self._edit(window, seen, float_drag, _KEY_END, _KEY_BACKSPACE, _NATIVE_BACKSPACE, 4, "5")
        self.assertEqual(float_model.as_float, 5.0)
        await self._edit(window, seen, float_drag, _KEY_HOME, _KEY_DELETE, _NATIVE_DELETE, 4, "7")
        self.assertEqual(float_model.as_float, 7.0)
        await self._edit(window, seen, int_drag, _KEY_END, _KEY_BACKSPACE, _NATIVE_BACKSPACE, 3, "8")
        self.assertEqual(int_model.as_int, 8)
        await self._edit(window, seen, int_drag, _KEY_HOME, _KEY_DELETE, _NATIVE_DELETE, 2, "9")
        self.assertEqual(int_model.as_int, 9)

        # No field is edited: the same keys reach the callback with
        # is_text_input_active() False, so an application shortcut still runs.
        seen.clear()
        await self._press(_KEY_DELETE)
        await self._press(_KEY_BACKSPACE)
        self.assertEqual(seen, [(_NATIVE_DELETE, False), (_NATIVE_BACKSPACE, False)])

        await self.finalize_test_no_image()

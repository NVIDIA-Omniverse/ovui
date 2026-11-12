# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""``omni.ui.standalone.end_text_input()`` ends a field edit as a commit.

Regression: the USD Viewer saved on Ctrl+S while a Property Inspector number
field was still in keyboard-edit mode. The field had written the typed value
as a preview, and a later Escape put the old value back. The application must
be able to end the edit from its key callback, as a click outside the field
does, before it saves: the field keeps the typed value, calls its end-edit
callback once as a commit (not as a cancel) in the same frame, and a later
Escape no longer goes to the field.

A mouse drag of a number field is not typing mode, also when the same field
was edited as text before (ImGui keeps the ID of that text edit, and the drag
makes the same ID active). Ctrl+S during the drag must not end it: the call
returns False, and the drag still follows the mouse.

The field is put in keyboard-edit mode with an injected double-click and
edited with injected text and keys, the same input path as a user.
"""

from __future__ import annotations

import asyncio

import omni.ui as ui
from omni.ui import _ui
from omni.ui import standalone
from test_base import OmniUiTest

# ImGuiKey values, as injected by the ovui inspector.
_KEY_ENTER = 525
_KEY_ESCAPE = 526
_KEY_LEFT_CTRL = 527
_KEY_S = 546 + 18
# The native (GLFW) code that the key callback receives for S.
_NATIVE_S = ord("S")


class TestEndTextInput(OmniUiTest):
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

    async def _check_held_drag_after_a_text_edit(self, window, drag, model, typed: str, read) -> None:
        """Type into a drag field, press Enter, then drag it with the mouse and press Ctrl+S.

        ImGui keeps the ID of the last text edit after the edit ends, and a
        mouse drag of the same field makes the same ID active. That drag is
        not typing mode: the call must return False and the drag must go on.
        """
        results = []

        def on_key(key, modifiers, pressed):
            # As the USD Viewer does for Ctrl+S in the Property Inspector.
            if pressed and int(key) == _NATIVE_S:
                results.append(standalone.end_text_input())

        window.set_key_pressed_fn(on_key)
        await self.wait_n_updates(3)

        await self._double_click(drag)
        self.assertTrue(standalone.is_text_input_active(), "the field did not enter keyboard-edit mode")
        _ui._inject_text_input(typed)
        await self.wait_n_updates(2)
        await self._press(_KEY_ENTER)
        await self.wait_n_updates(2)
        self.assertFalse(standalone.is_text_input_active(), "Enter did not end the text edit")
        typed_value = read(model)
        self.assertEqual(typed_value, float(typed))

        # Hold the left button on the same field and drag right. Wait first,
        # so that this press is not counted as a click of a double-click.
        await asyncio.sleep(0.5)
        x = float(drag.screen_position_x + drag.computed_width / 2)
        y = float(drag.screen_position_y + drag.computed_height / 2)
        _ui._inject_mouse_move(x, y)
        await self.wait_n_updates(1)
        _ui._inject_mouse_button(0, True)
        try:
            await self.wait_n_updates(2)
            _ui._inject_mouse_move(x + 20.0, y)
            await self.wait_n_updates(2)
            before_save = read(model)
            self.assertGreater(before_save, typed_value, "the mouse drag did not change the value")
            self.assertFalse(standalone.is_text_input_active())

            # Ctrl+S while the button is held: there is no text input to end.
            _ui._inject_key_event(_KEY_LEFT_CTRL, True)
            await self.wait_n_updates(1)
            _ui._inject_key_event(_KEY_S, True)
            await self.wait_n_updates(1)
            _ui._inject_key_event(_KEY_S, False)
            await self.wait_n_updates(1)
            _ui._inject_key_event(_KEY_LEFT_CTRL, False)
            await self.wait_n_updates(1)
            self.assertEqual(results, [False])

            # The drag still follows the mouse.
            _ui._inject_mouse_move(x + 40.0, y)
            await self.wait_n_updates(2)
            self.assertGreater(read(model), before_save, "the drag stopped after Ctrl+S")
        finally:
            # A failed check must not leave the button held for the next test.
            _ui._inject_mouse_button(0, False)
            await self.wait_n_updates(2)

    async def test_end_text_input_in_a_key_callback_commits_the_field_edit(self):
        window = await self.create_test_window(256, 128)
        model = ui.SimpleFloatModel(-80.0)
        with window.frame:
            with ui.VStack(height=0):
                drag = ui.FloatDrag(model, height=24)
        events = []
        model.add_end_edit_fn(lambda m: events.append(("end", m.as_float, m.is_edit_cancelled())))

        def on_key(key, modifiers, pressed):
            # As the USD Viewer does for Ctrl+S in the Property Inspector.
            if pressed and int(key) == _NATIVE_S:
                events.append(("key", standalone.end_text_input()))

        window.set_key_pressed_fn(on_key)
        await self.wait_n_updates(3)

        # No text input: nothing to end.
        self.assertFalse(standalone.end_text_input())

        await self._double_click(drag)
        self.assertTrue(standalone.is_text_input_active(), "the field did not enter keyboard-edit mode")
        # The first click of the double-click is a short mouse edit with its
        # own end-edit; only the keyboard edit is checked below.
        events.clear()
        _ui._inject_text_input("55")
        await self.wait_n_updates(2)
        # The field writes the typed value while it edits.
        self.assertEqual(model.as_float, 55.0)
        self.assertEqual(events, [])

        _ui._inject_key_event(_KEY_LEFT_CTRL, True)
        await self.wait_n_updates(1)
        _ui._inject_key_event(_KEY_S, True)
        await self.wait_n_updates(1)
        # The key callback ended the edit, and the field ran its end-edit
        # callback in the same frame: a commit of the typed value.
        self.assertEqual(events, [("key", True), ("end", 55.0, False)])
        _ui._inject_key_event(_KEY_S, False)
        await self.wait_n_updates(1)
        _ui._inject_key_event(_KEY_LEFT_CTRL, False)
        await self.wait_n_updates(2)
        self.assertFalse(standalone.is_text_input_active(), "the field still edits")

        # A later Escape does not go to the field: the value stays, and there
        # is no second end-edit.
        await self._press(_KEY_ESCAPE)
        await self.wait_n_updates(2)
        self.assertEqual(model.as_float, 55.0)
        self.assertEqual(events, [("key", True), ("end", 55.0, False)])
        self.assertFalse(standalone.end_text_input())

        await self.finalize_test_no_image()

    async def test_end_text_input_does_not_stop_a_held_float_drag(self):
        window = await self.create_test_window(256, 128)
        model = ui.SimpleFloatModel(40.0)
        with window.frame:
            with ui.VStack(height=0):
                drag = ui.FloatDrag(model, height=24)
        await self._check_held_drag_after_a_text_edit(window, drag, model, "-80", lambda m: m.as_float)
        await self.finalize_test_no_image()

    async def test_end_text_input_does_not_stop_a_held_int_drag(self):
        window = await self.create_test_window(256, 128)
        model = ui.SimpleIntModel(0)
        with window.frame:
            with ui.VStack(height=0):
                drag = ui.IntDrag(model, height=24)
        await self._check_held_drag_after_a_text_edit(window, drag, model, "7", lambda m: m.as_int)
        await self.finalize_test_no_image()

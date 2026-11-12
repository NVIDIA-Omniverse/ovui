# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A TreeView column that the user narrows can be widened back.

The tree is in a ScrollingFrame with a horizontal scroll bar, so it measures
its last column. Expanding a row measures it again. The width that the last
column fills must not become its minimum width, or the first column cannot get
its width back. A wrapped Label must not be wider than its column because of
spaces at the end of its text, for the same reason. The drags and the click are
injected, the same input path as a user.
"""

from __future__ import annotations

import omni.ui as ui
from omni.ui import _ui
from test_base import OmniUiTest


class _Item(ui.AbstractItem):
    def __init__(self, text, children=()):
        super().__init__()
        self.model = ui.SimpleStringModel(text)
        self.children = list(children)


class _Model(ui.AbstractItemModel):
    def __init__(self):
        super().__init__()
        self._items = [_Item("Row 0", [_Item("Child")]), _Item("Row 1"), _Item("Row 2")]

    def get_item_children(self, item=None):
        return self._items if item is None else item.children

    def get_item_value_model_count(self, item=None):
        return 2

    def get_item_value_model(self, item=None, column_id=0):
        return item.model if item else None


class TestTreeViewColumnResize(OmniUiTest):
    async def _drag(self, x, y, dx):
        _ui._inject_mouse_move(float(x), float(y))
        await self.wait_n_updates(2)
        _ui._inject_mouse_button(0, True)
        await self.wait_n_updates(2)
        step = 2 if dx > 0 else -2
        for _ in range(abs(dx) // 2):
            x += step
            _ui._inject_mouse_move(float(x), float(y))
            await self.next_frame()
        _ui._inject_mouse_button(0, False)
        await self.wait_n_updates(2)

    async def _click(self, x, y):
        _ui._inject_mouse_move(float(x), float(y))
        await self.wait_n_updates(2)
        _ui._inject_mouse_button(0, True)
        await self.next_frame()
        _ui._inject_mouse_button(0, False)
        await self.wait_n_updates(3)

    async def test_narrowed_column_can_be_widened_back(self):
        window = await self.create_test_window(400, 200)
        model = _Model()
        with window.frame:
            with ui.ScrollingFrame(horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED):
                tree = ui.TreeView(
                    model,
                    root_visible=False,
                    header_visible=False,
                    keep_alive=True,
                    columns_resizable=True,
                    column_widths=[ui.Pixel(140), ui.Fraction(1)],
                )
        await self.wait_n_updates(5)

        divider_x = int(tree.screen_position_x) + 140
        row_y = int(tree.screen_position_y) + 30
        await self._drag(divider_x, row_y, -50)
        self.assertAlmostEqual(tree.column_widths[0].value, 90, delta=1)

        # Expand "Row 0". The tree measures its last column again.
        await self._click(int(tree.screen_position_x) + 8, int(tree.screen_position_y) + 8)

        await self._drag(divider_x - 50, row_y, 50)
        self.assertAlmostEqual(tree.column_widths[0].value, 140, delta=1)

        await self.finalize_test_no_image()

    async def test_wrapped_label_end_spaces_add_no_width(self):
        window = await self.create_test_window(400, 100)
        with window.frame:
            with ui.VStack():
                probe = ui.Label("Short row text", width=0, height=0)
                with ui.HStack(height=0):
                    label = ui.Label("Short row text ", word_wrap=True, width=0)
        await self.wait_n_updates(3)

        # The text fits on one line. The space at the end does not wrap, so it adds no width.
        label.width = ui.Pixel(probe.computed_width)
        await self.wait_n_updates(3)
        self.assertEqual(label.computed_width, probe.computed_width)

        await self.finalize_test_no_image()

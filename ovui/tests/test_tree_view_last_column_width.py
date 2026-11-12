# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A TreeView cell that becomes wider in place widens the last column.

The tree is in a ScrollingFrame with a horizontal scroll bar, so it measures
its last column. A row is built, and only then the text of its value model
grows. The item model is not notified, which is what an application does when
it drives a cell through its value model alone. The last column must still grow
to fit the new text, so the user can scroll right and read it.
"""

from __future__ import annotations

import omni.ui as ui
from test_base import OmniUiTest

LONG = "xxxxxxxxxx_a_text_that_is_much_wider_than_the_column_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"


class _Item(ui.AbstractItem):
    def __init__(self, text, children=()):
        super().__init__()
        self.model = ui.SimpleStringModel(text)
        self.children = list(children)


class _Model(ui.AbstractItemModel):
    def __init__(self):
        super().__init__()
        self.groups = [_Item("G%d" % g, [_Item("G%d R%d" % (g, i)) for i in range(30)]) for g in range(6)]

    def get_item_children(self, item=None):
        return self.groups if item is None else item.children

    def get_item_value_model_count(self, item=None):
        return 2

    def get_item_value_model(self, item=None, column_id=0):
        return item.model if item else None


class TestTreeViewLastColumnWidth(OmniUiTest):
    async def test_widened_cell_widens_the_last_column(self):
        window = await self.create_test_window(300, 300)
        model = _Model()
        with window.frame:
            with ui.ScrollingFrame(horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED) as frame:
                tree = ui.TreeView(model, root_visible=False, header_visible=False)
        await self.wait_n_updates(4)
        for group in model.groups:
            tree.set_expanded(group, True, False)
        await self.wait_n_updates(6)
        # Every row fits, so there is nothing to scroll right.
        self.assertEqual(frame.scroll_x_max, 0.0)

        # A row that is already built gets a much longer text, with no item change.
        model.groups[0].children[2].model.as_string = LONG
        await self.wait_n_updates(6)

        # Scrolling down builds new rows and measures the last column again.
        for _ in range(10):
            frame.scroll_y += 150
            await self.wait_n_updates(3)

        # The column grew to fit the long text, so it can be scrolled to.
        self.assertGreater(frame.scroll_x_max, 0.0)

        await self.finalize_test_no_image()

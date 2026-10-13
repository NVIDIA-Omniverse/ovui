# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Menu lifecycle regression tests."""

from test_base import OmniUiTest

import omni.ui as ui
from omni.ui import testing


def _center(widget: ui.Widget) -> tuple[float, float]:
    return (
        widget.screen_position_x + widget.computed_width * 0.5,
        widget.screen_position_y + widget.computed_height * 0.5,
    )


class TestMenu(OmniUiTest):
    async def test_closing_parent_clears_shown_descendants(self):
        """Selecting a nested leaf closes every menu in the popup stack."""
        flags = (
            ui.WINDOW_FLAGS_NO_SCROLLBAR
            | ui.WINDOW_FLAGS_NO_TITLE_BAR
            | ui.WINDOW_FLAGS_NO_RESIZE
            | ui.WINDOW_FLAGS_MENU_BAR
        )
        window = await self.create_test_window(width=400, height=240, window_flags=flags)
        root_shown = []
        child_shown = []
        grandchild_shown = []
        leaf_triggered = []

        with window.frame:
            with ui.MenuBar():
                with ui.Menu("View") as root_menu:
                    with ui.Menu("Viewport") as child_menu:
                        with ui.Menu("Overlay") as grandchild_menu:
                            leaf = ui.MenuItem("Axes", triggered_fn=lambda: leaf_triggered.append(True))

        root_menu.set_shown_changed_fn(root_shown.append)
        child_menu.set_shown_changed_fn(child_shown.append)
        grandchild_menu.set_shown_changed_fn(grandchild_shown.append)
        await self.wait_n_updates(2)

        await testing.mouse_click(*_center(root_menu))
        self.assertTrue(root_menu.shown)
        self.assertEqual(root_shown, [True])

        await testing.mouse_move(*_center(child_menu))
        await self.wait_n_updates(3)
        self.assertTrue(child_menu.shown)
        self.assertEqual(child_shown, [True])

        await testing.mouse_move(*_center(grandchild_menu))
        await self.wait_n_updates(3)
        self.assertTrue(grandchild_menu.shown)
        self.assertEqual(grandchild_shown, [True])

        await testing.mouse_click(*_center(leaf))
        await self.wait_n_updates(2)

        self.assertEqual(leaf_triggered, [True])
        self.assertFalse(root_menu.shown)
        self.assertFalse(child_menu.shown)
        self.assertFalse(grandchild_menu.shown)
        self.assertEqual(root_shown, [True, False])
        self.assertEqual(child_shown, [True, False])
        self.assertEqual(grandchild_shown, [True, False])
        await self.finalize_test_no_image()

    async def test_torn_parent_does_not_toggle_shown_child_each_frame(self):
        """The menu-bar copy must not clear a child drawn in a tear-off."""
        flags = (
            ui.WINDOW_FLAGS_NO_SCROLLBAR
            | ui.WINDOW_FLAGS_NO_TITLE_BAR
            | ui.WINDOW_FLAGS_NO_RESIZE
            | ui.WINDOW_FLAGS_MENU_BAR
        )
        window = await self.create_test_window(width=600, height=400, window_flags=flags)
        child_shown = []

        with window.frame:
            with ui.MenuBar():
                with ui.Menu("View", tearable=True) as root_menu:
                    with ui.Menu("Viewport") as child_menu:
                        ui.MenuItem("Axes")

        child_menu.set_shown_changed_fn(child_shown.append)
        await self.wait_n_updates(3)
        root_menu.tear_at(100.0, 100.0)
        await self.wait_n_updates(4)

        await testing.mouse_move(*_center(child_menu))
        await self.wait_n_updates(4)
        self.assertTrue(child_menu.shown)
        self.assertEqual(child_shown, [True])

        await self.wait_n_updates(6)
        self.assertTrue(child_menu.shown)
        self.assertEqual(child_shown, [True])
        root_menu.hide()
        self.assertFalse(child_menu.shown)
        self.assertEqual(child_shown, [True, False])
        await self.finalize_test_no_image()

    async def test_hiding_ancestor_preserves_torn_descendant_popup_state(self):
        """A live tear-off owns its open submenu state independently."""
        flags = (
            ui.WINDOW_FLAGS_NO_SCROLLBAR
            | ui.WINDOW_FLAGS_NO_TITLE_BAR
            | ui.WINDOW_FLAGS_NO_RESIZE
            | ui.WINDOW_FLAGS_MENU_BAR
        )
        window = await self.create_test_window(width=700, height=450, window_flags=flags)
        popup_shown = []

        with window.frame:
            with ui.MenuBar():
                with ui.Menu("View", tearable=True) as root_menu:
                    with ui.Menu("Viewport", tearable=True) as torn_menu:
                        with ui.Menu("Overlay") as popup_menu:
                            ui.MenuItem("Axes")

        popup_menu.set_shown_changed_fn(popup_shown.append)
        await self.wait_n_updates(3)
        root_menu.tear_at(60.0, 60.0)
        await self.wait_n_updates(4)
        torn_menu.tear_at(300.0, 100.0)
        await self.wait_n_updates(4)

        await testing.mouse_move(*_center(popup_menu))
        await self.wait_n_updates(4)
        self.assertTrue(torn_menu.teared)
        self.assertTrue(popup_menu.shown)
        self.assertEqual(popup_shown, [True])

        root_menu.hide()
        await self.wait_n_updates(4)

        self.assertTrue(torn_menu.teared)
        self.assertTrue(popup_menu.shown)
        self.assertEqual(popup_shown, [True])

        root_menu.destroy()
        self.assertFalse(popup_menu.shown)
        self.assertEqual(popup_shown, [True, False])
        await self.finalize_test_no_image()

    async def test_closing_torn_parent_clears_shown_descendants(self):
        """Double-clicking a tear-off title closes every shown descendant."""
        flags = (
            ui.WINDOW_FLAGS_NO_SCROLLBAR
            | ui.WINDOW_FLAGS_NO_TITLE_BAR
            | ui.WINDOW_FLAGS_NO_RESIZE
            | ui.WINDOW_FLAGS_MENU_BAR
        )
        window = await self.create_test_window(width=600, height=400, window_flags=flags)
        child_shown = []

        with window.frame:
            with ui.MenuBar():
                with ui.Menu("View", tearable=True) as root_menu:
                    with ui.Menu("Viewport") as child_menu:
                        ui.MenuItem("Axes")

        child_menu.set_shown_changed_fn(child_shown.append)
        await self.wait_n_updates(3)
        root_menu.tear_at(100.0, 100.0)
        await self.wait_n_updates(4)

        await testing.mouse_move(*_center(child_menu))
        await self.wait_n_updates(4)
        self.assertTrue(child_menu.shown)
        self.assertEqual(child_shown, [True])

        title = ui.Inspector.get_children(root_menu)[0]
        await testing.mouse_double_click(*_center(title))
        await self.wait_n_updates(3)

        self.assertFalse(child_menu.shown)
        self.assertEqual(child_shown, [True, False])
        await self.finalize_test_no_image()

    async def test_destroy_clears_shown_descendants(self):
        """Destroying a menu balances shown state before children disappear."""
        flags = (
            ui.WINDOW_FLAGS_NO_SCROLLBAR
            | ui.WINDOW_FLAGS_NO_TITLE_BAR
            | ui.WINDOW_FLAGS_NO_RESIZE
            | ui.WINDOW_FLAGS_MENU_BAR
        )
        window = await self.create_test_window(width=400, height=240, window_flags=flags)
        child_shown = []

        with window.frame:
            with ui.MenuBar():
                with ui.Menu("View", tearable=True) as root_menu:
                    with ui.Menu("Viewport") as child_menu:
                        ui.MenuItem("Axes")

        child_menu.set_shown_changed_fn(child_shown.append)
        await self.wait_n_updates(3)
        root_menu.tear_at(80.0, 80.0)
        await self.wait_n_updates(4)
        await testing.mouse_move(*_center(child_menu))
        await self.wait_n_updates(4)
        self.assertTrue(child_menu.shown)
        self.assertEqual(child_shown, [True])

        root_menu.destroy()
        self.assertFalse(child_menu.shown)
        self.assertEqual(child_shown, [True, False])
        await self.finalize_test_no_image()

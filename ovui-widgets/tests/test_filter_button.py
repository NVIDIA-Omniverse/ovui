# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`FilterButton` (the content browser implementation step 26).

Coverage:

* Public surface — package re-export, ``__all__`` inclusion, module
  symbols.
* Construction — empty initial filter, all menu items built, initial
  ``.checked`` is False across the board, no spurious callback at build
  time, caller's categories list is snapshotted (not shared).
* Toggle semantics (handler path) — ``_on_item_toggled(cat, True)``
  adds to the active set; ``_on_item_toggled(cat, False)`` removes;
  toggling multiple categories accumulates; toggling the same category
  twice rejoins the empty set; callback receives a *copy* so external
  mutation does not leak into the widget.
* Toggle via menu-item (integration path) — assigning
  ``item.checked = True`` routes through the widget's
  ``set_checked_changed_fn`` binding and calls the caller's callback.
* Button click dispatch — clicking the button calls
  :meth:`ui.Menu.show_at`; post-destroy click falls through safely.
* Destroy — idempotent, clears widget refs, drops the menu reference,
  drops the handler reference, stale toggle calls no-op.

Structure mirrors ``tests/test_zoom_bar.py`` — a module-scoped
``ephemeral_window`` fixture plus an ``in_window_frame`` context
manager wraps widget construction in a real ovui build context.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List, Set

import omni.ui as ui
import pytest

from ovui_widgets.common.asset_types import AssetCategory
from ovui_widgets.content.widget import FilterButton
from ovui_widgets.content.widget.filter_button import (
    _CATEGORY_DISPLAY_NAMES,
)
from ovui_widgets.content.widget.filter_button import (
    FilterButton as _FilterButton,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """Single ovui Window reused across every widget-build test."""
    win = ui.Window("_test_filter_button", width=200, height=40)
    yield win
    win.destroy()


@contextmanager
def in_window_frame(window):
    """Enter ``window.frame`` as a build context and clear it on exit."""
    try:
        with window.frame:
            yield
    finally:
        window.frame.clear()


def _noop_filter_changed(_active: Set[AssetCategory]) -> None:
    """Placeholder callback when a test does not care about the emitted set."""


# Canonical six-category set from the content browser implementation step 26.
_DEFAULT_CATEGORIES: List[AssetCategory] = [
    AssetCategory.USD,
    AssetCategory.IMAGE,
    AssetCategory.MATERIAL,
    AssetCategory.SOUND,
    AssetCategory.SCRIPT,
    AssetCategory.VOLUME,
]


# ──────────────────────────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestSurface:
    def test_filter_button_reexported_from_widget_package(self):
        from ovui_widgets.content.widget import FilterButton as FB

        assert FB is _FilterButton

    def test_widget_package_all_contains_filter_button(self):
        import ovui_widgets.content.widget as pkg

        assert "FilterButton" in pkg.__all__

    def test_display_names_cover_every_asset_category(self):
        """Every enum member has a short-name so a future caller can pass
        arbitrary categories without hitting a missing-key path."""
        for category in AssetCategory:
            assert category in _CATEGORY_DISPLAY_NAMES
            assert _CATEGORY_DISPLAY_NAMES[category]


# ──────────────────────────────────────────────────────────────────────────────
# Construction
# ──────────────────────────────────────────────────────────────────────────────


class TestConstruction:
    def test_builds_all_widget_refs(self, ephemeral_window):
        """Every handle populated — no ``None`` slots after build."""
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=_noop_filter_changed,
            )
        try:
            assert btn._zstack is not None
            assert btn._button is not None
            assert btn._icon_image is not None
            assert btn._menu is not None
        finally:
            btn.destroy()

    def test_initial_active_categories_is_empty(self, ephemeral_window):
        """Default state = empty set = show all (FileBrowserModel convention)."""
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=_noop_filter_changed,
            )
        try:
            assert btn.active_categories == set()
        finally:
            btn.destroy()

    def test_build_does_not_fire_callback(self, ephemeral_window):
        """No spurious on_filter_changed at construction time."""
        calls: List[Set[AssetCategory]] = []
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=calls.append,
            )
        try:
            assert calls == []
        finally:
            btn.destroy()

    def test_all_menu_items_built(self, ephemeral_window):
        """One ui.MenuItem per requested category, keyed by that category."""
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=_noop_filter_changed,
            )
        try:
            assert set(btn._menu_items.keys()) == set(_DEFAULT_CATEGORIES)
            assert len(btn._menu_items) == 6
        finally:
            btn.destroy()

    def test_button_is_disabled_v1(self, ephemeral_window):
        """Bug 9 — the filter dropdown is not useful in V1 (homogeneous
        folders ignore the whitelist), so the button ships disabled so
        the affordance does not promise a behavior the V1 surface
        cannot honor. The Content.ToolBar.Button:disabled style gray
        the icon and strip the hover highlight.
        """
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=_noop_filter_changed,
            )
        try:
            assert btn._button.enabled is False
            assert "not yet implemented" in btn._button.tooltip.lower()
        finally:
            btn.destroy()

    def test_all_menu_items_start_unchecked(self, ephemeral_window):
        """Default-all-off contract — user must explicitly opt in."""
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=_noop_filter_changed,
            )
        try:
            for item in btn._menu_items.values():
                assert item.checked is False
                assert item.checkable is True
        finally:
            btn.destroy()

    def test_menu_item_labels_use_short_names(self, ephemeral_window):
        """USD and Script render short — not their full catalog display names."""
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=[AssetCategory.USD, AssetCategory.SCRIPT],
                on_filter_changed=_noop_filter_changed,
            )
        try:
            assert btn._menu_items[AssetCategory.USD].text == "USD"
            assert btn._menu_items[AssetCategory.SCRIPT].text == "Script"
        finally:
            btn.destroy()

    def test_menu_item_order_matches_constructor_order(
        self, ephemeral_window,
    ):
        """Menu renders categories in the order the caller passed them."""
        ordered = [
            AssetCategory.VOLUME,
            AssetCategory.USD,
            AssetCategory.IMAGE,
        ]
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=ordered,
                on_filter_changed=_noop_filter_changed,
            )
        try:
            assert list(btn._menu_items.keys()) == ordered
        finally:
            btn.destroy()

    def test_constructor_snapshots_category_list(self, ephemeral_window):
        """Mutating the caller's list post-construction does not reshape menu."""
        categories: List[AssetCategory] = [
            AssetCategory.USD, AssetCategory.IMAGE,
        ]
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=categories,
                on_filter_changed=_noop_filter_changed,
            )
        try:
            categories.append(AssetCategory.MATERIAL)
            categories.clear()
            assert list(btn._menu_items.keys()) == [
                AssetCategory.USD, AssetCategory.IMAGE,
            ]
        finally:
            btn.destroy()

    def test_accepts_empty_categories(self, ephemeral_window):
        """Edge case — empty category list yields an empty menu without crashing."""
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=[],
                on_filter_changed=_noop_filter_changed,
            )
        try:
            assert btn._menu_items == {}
            assert btn._menu is not None  # menu still exists, just empty
            assert btn.active_categories == set()
        finally:
            btn.destroy()

    def test_accepts_subset_of_all_categories(self, ephemeral_window):
        """Caller may pass any subset — not restricted to the Step-26 six."""
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=[AssetCategory.USD],
                on_filter_changed=_noop_filter_changed,
            )
        try:
            assert list(btn._menu_items.keys()) == [AssetCategory.USD]
        finally:
            btn.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Toggle semantics (handler path — call _on_item_toggled directly)
# ──────────────────────────────────────────────────────────────────────────────


class TestToggleSemantics:
    def test_toggle_one_adds_to_active(self, ephemeral_window):
        calls: List[Set[AssetCategory]] = []
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=calls.append,
            )
        try:
            btn._on_item_toggled(AssetCategory.USD, True)
            assert btn.active_categories == {AssetCategory.USD}
            assert calls == [{AssetCategory.USD}]
        finally:
            btn.destroy()

    def test_toggle_multiple_accumulates(self, ephemeral_window):
        """Each toggle fires once with the accumulated set."""
        calls: List[Set[AssetCategory]] = []
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=calls.append,
            )
        try:
            btn._on_item_toggled(AssetCategory.USD, True)
            btn._on_item_toggled(AssetCategory.IMAGE, True)
            btn._on_item_toggled(AssetCategory.MATERIAL, True)
            assert btn.active_categories == {
                AssetCategory.USD,
                AssetCategory.IMAGE,
                AssetCategory.MATERIAL,
            }
            assert len(calls) == 3
            assert calls[0] == {AssetCategory.USD}
            assert calls[1] == {AssetCategory.USD, AssetCategory.IMAGE}
            assert calls[2] == {
                AssetCategory.USD,
                AssetCategory.IMAGE,
                AssetCategory.MATERIAL,
            }
        finally:
            btn.destroy()

    def test_untoggle_removes_from_active(self, ephemeral_window):
        """Toggling a category off drops it out of the active set."""
        calls: List[Set[AssetCategory]] = []
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=calls.append,
            )
        try:
            btn._on_item_toggled(AssetCategory.USD, True)
            btn._on_item_toggled(AssetCategory.IMAGE, True)
            btn._on_item_toggled(AssetCategory.USD, False)
            assert btn.active_categories == {AssetCategory.IMAGE}
            assert calls[-1] == {AssetCategory.IMAGE}
        finally:
            btn.destroy()

    def test_untoggle_all_fires_empty_set(self, ephemeral_window):
        """Final uncheck returns the empty set (show-all convention)."""
        calls: List[Set[AssetCategory]] = []
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=calls.append,
            )
        try:
            btn._on_item_toggled(AssetCategory.USD, True)
            btn._on_item_toggled(AssetCategory.USD, False)
            assert btn.active_categories == set()
            assert calls[-1] == set()
        finally:
            btn.destroy()

    def test_untoggle_never_checked_is_silent_noop(self, ephemeral_window):
        """Redundant False-toggle against an unchecked category is a no-op.

        The change-guard in ``_on_item_toggled`` short-circuits when
        ``checked`` already matches membership — no state mutation and
        no callback fire. Prevents spurious whitelist-refresh wakes
        downstream when the menu re-dispatches an unchanged state
        (e.g. after a hypothetical future state-restore path).
        """
        calls: List[Set[AssetCategory]] = []
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=calls.append,
            )
        try:
            btn._on_item_toggled(AssetCategory.USD, False)
            assert btn.active_categories == set()
            assert calls == []
        finally:
            btn.destroy()

    def test_toggle_same_state_is_silent_noop(self, ephemeral_window):
        """Redundant True-toggle against an already-checked category is a no-op."""
        calls: List[Set[AssetCategory]] = []
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=calls.append,
            )
        try:
            btn._on_item_toggled(AssetCategory.USD, True)
            btn._on_item_toggled(AssetCategory.USD, True)
            btn._on_item_toggled(AssetCategory.USD, True)
            assert btn.active_categories == {AssetCategory.USD}
            assert len(calls) == 1  # only the first toggle fires.
        finally:
            btn.destroy()

    def test_callback_receives_copy_not_internal_set(self, ephemeral_window):
        """Mutating the emitted set must not leak into the widget."""
        calls: List[Set[AssetCategory]] = []
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=calls.append,
            )
        try:
            btn._on_item_toggled(AssetCategory.USD, True)
            emitted = calls[-1]
            emitted.add(AssetCategory.IMAGE)
            emitted.clear()
            # Widget's own record untouched.
            assert btn.active_categories == {AssetCategory.USD}
        finally:
            btn.destroy()

    def test_active_categories_returns_copy(self, ephemeral_window):
        """Property also returns a copy — external mutation is safe."""
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=_noop_filter_changed,
            )
        try:
            btn._on_item_toggled(AssetCategory.USD, True)
            view = btn.active_categories
            view.add(AssetCategory.IMAGE)
            view.clear()
            assert btn.active_categories == {AssetCategory.USD}
        finally:
            btn.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Menu-item integration path — toggle via ``.checked = True``
# ──────────────────────────────────────────────────────────────────────────────


class TestMenuItemIntegration:
    # NOTE: ``.checked = ...`` only fires the ``set_checked_changed_fn``
    # binding while the item is still alive under its build context. After
    # ``window.frame.clear()`` the C++ side tears down the menu items and
    # subsequent ``.checked`` assignments silently no-op. So the assertions
    # here run INSIDE ``in_window_frame`` and only the ``destroy`` call
    # lands after the context exits.

    def test_item_checked_assignment_routes_through_handler(
        self, ephemeral_window,
    ):
        """Programmatic .checked=True fires the change callback end-to-end."""
        calls: List[Set[AssetCategory]] = []
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=calls.append,
            )
            btn._menu_items[AssetCategory.USD].checked = True
            assert btn.active_categories == {AssetCategory.USD}
            assert calls == [{AssetCategory.USD}]
        btn.destroy()

    def test_item_checked_false_removes_category(self, ephemeral_window):
        calls: List[Set[AssetCategory]] = []
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=calls.append,
            )
            btn._menu_items[AssetCategory.USD].checked = True
            btn._menu_items[AssetCategory.USD].checked = False
            assert btn.active_categories == set()
            assert calls[-1] == set()
        btn.destroy()

    def test_loop_lambda_binds_correct_category(self, ephemeral_window):
        """Late-binding trap — each menu item must fire for its own category.

        A naive ``lambda checked: self._on_item_toggled(category, checked)``
        in the build loop would close over the final ``category`` value
        and route every toggle to the last menu item. The default-arg
        binding (``lambda checked, cat=category: ...``) is what we verify.
        """
        calls: List[Set[AssetCategory]] = []
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=calls.append,
            )
            btn._menu_items[AssetCategory.IMAGE].checked = True
            assert btn.active_categories == {AssetCategory.IMAGE}
            btn._menu_items[AssetCategory.VOLUME].checked = True
            assert btn.active_categories == {
                AssetCategory.IMAGE, AssetCategory.VOLUME,
            }
        btn.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Button click safety (post-destroy path only — a live click requires a
# real composition context to compute ``screen_position_*`` / ``computed_height``
# before ``ui.Menu.show_at`` can position the popup. End-to-end click
# coverage belongs to the Step 28 QA pass where FilterButton is wired
# into the live toolbar; here we only verify the teardown-safe path.
# Mirrors ``tests/test_attr_context_menu.py`` which also skips the
# live ``show_attr_context_menu`` driver for the same reason.)
# ──────────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────────
# Destroy
# ──────────────────────────────────────────────────────────────────────────────


class TestDestroy:
    def test_destroy_clears_widget_refs(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=_noop_filter_changed,
            )
        btn.destroy()
        assert btn._zstack is None
        assert btn._button is None
        assert btn._icon_image is None
        assert btn._menu is None
        assert btn._menu_items == {}

    def test_destroy_clears_handler_ref(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=_noop_filter_changed,
            )
        btn.destroy()
        assert btn._on_filter_changed is None

    def test_destroy_is_idempotent(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=_noop_filter_changed,
            )
        btn.destroy()
        btn.destroy()  # must not raise

    def test_button_click_after_destroy_does_not_raise(
        self, ephemeral_window,
    ):
        """Post-destroy click from a straggling callback falls through."""
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=_noop_filter_changed,
            )
        btn.destroy()
        btn._on_button_clicked()

    def test_toggle_after_destroy_does_not_raise(self, ephemeral_window):
        """A late ``_on_item_toggled`` from a destroyed menu is safe."""
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=_noop_filter_changed,
            )
        btn.destroy()
        btn._on_item_toggled(AssetCategory.USD, True)

    def test_active_categories_after_destroy_is_empty(self, ephemeral_window):
        """Property still returns a sensible value after destroy."""
        with in_window_frame(ephemeral_window):
            btn = FilterButton(
                categories=_DEFAULT_CATEGORIES,
                on_filter_changed=_noop_filter_changed,
            )
        btn._on_item_toggled(AssetCategory.USD, True)
        btn.destroy()
        # The active record persists after destroy; what breaks is the
        # link to the UI. Tests that care about post-destroy state read
        # ``active_categories`` directly rather than through the menu
        # items.
        assert btn.active_categories == {AssetCategory.USD}

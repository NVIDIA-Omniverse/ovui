# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 53 — Options dropdown button.

Covers the LAYERS-PLAN Step 53 deliverables:

  * :class:`OptionsButton` is constructable with either a
    :class:`LayerSettings` or a :class:`DefaultLayerSettings` — the
    widget does not discriminate between the two.
  * The ordered list of menu labels matches
    LAYERS-PLAN Step 53's exact enumeration: Show Layer Contents,
    Show Session Layer, Show Missing References, Show Merge/Flatten
    Warnings, Show File Extensions in Name, Info Notifications.
  * Every :data:`MENU_ITEMS` property name resolves to a real
    :class:`LayerSettings` attribute — an invariant that prevents a
    typo in the menu list from shipping a silently-broken checkbox.
  * Toggle through :meth:`OptionsButton.toggle` flips the backing
    :class:`LayerSettings` setter and the change round-trips through
    the :class:`ovwidgets.common.settings.Settings` store (persistence).
  * Toggle on a :class:`LayerSettings`-backed button fires the
    per-key subscriber, so a bound :class:`LayerModel` rebuilds its
    tree when a tree-shape key flips — the end-to-end integration
    the step is meant to land.
  * :meth:`show_at` builds a :class:`ui.Menu` with one
    :class:`ui.MenuItem` per entry, each ``checkable=True`` and with
    ``checked`` mirroring the current setting value; triggering a
    menu item fires the corresponding toggle.
  * :meth:`show_at` can be called twice in a row — the second call
    destroys the previous menu before building the new one so the
    popup lifetime stays one-at-a-time.
  * :meth:`destroy` drops the pinned menu handle and is idempotent.
  * The non-left click path (right / middle button) does not open
    the dropdown — the button is a strict left-click affordance.
  * :class:`LayerWindow` constructs an :class:`OptionsButton` bound
    to its resolved settings wrapper, and :meth:`LayerWindow.destroy`
    cleans the button up along with the rest of the toolbar.
"""

from __future__ import annotations

import types
from typing import Any, List
from unittest.mock import MagicMock

import pytest

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.settings import Settings
from ovwidgets.layers import (
    OPTIONS_MENU_ITEMS,
    DefaultLayerSettings,
    LayerModel,
    LayerSettings,
    LayerWindow,
    OptionsButton,
)
from ovwidgets.layers.options_button import MENU_ITEMS

# ─── Fakes for headless ui.Menu capture ──────────────────────────────────────


class _FakeMenu:
    """Stand-in for :class:`ui.Menu` that records construction + items.

    Mirrors the pattern used by :mod:`tests.test_menu_bar` so tests
    can introspect the dropdown without spinning a real paint loop.
    Every :class:`_FakeMenu` the fake ``ui`` module produces is
    pushed onto a shared ``instances`` list on the module, which
    tests use to assert on the last-built dropdown.
    """

    _active_stack: List["_FakeMenu"] = []

    def __init__(self, label: str, *_a: Any, **_kw: Any) -> None:
        self.label = label
        self.items: List["_FakeMenuItem"] = []
        self.shown_at: Any = None
        self.destroyed: bool = False

    def __enter__(self) -> "_FakeMenu":
        _FakeMenu._active_stack.append(self)
        return self

    def __exit__(self, *_a: Any) -> None:
        _FakeMenu._active_stack.pop()

    def show_at(self, x: float, y: float) -> None:
        self.shown_at = (x, y)

    def destroy(self) -> None:
        self.destroyed = True


class _FakeMenuItem:
    def __init__(
        self,
        label: str,
        triggered_fn: Any = None,
        checkable: bool = False,
        checked: bool = False,
        **_kwargs: Any,
    ) -> None:
        self.label = label
        self.triggered_fn = triggered_fn
        self.checkable = checkable
        self.checked = checked
        if _FakeMenu._active_stack:
            _FakeMenu._active_stack[-1].items.append(self)


@pytest.fixture
def fake_ui_module() -> Any:
    """Patch :mod:`ovwidgets.layers.options_button`'s ``ui`` to a fake recorder.

    Yields the fake module so tests can inspect the last
    :class:`_FakeMenu` via ``fake.menus[-1]``.
    """
    import ovwidgets.layers.options_button as mod

    fake = types.ModuleType("omni.ui")
    fake.Menu = _FakeMenu
    fake.MenuItem = _FakeMenuItem
    fake.menus = []  # type: ignore[attr-defined]

    # Track every Menu built during the test so we can assert on them
    # even after the OptionsButton rebinds ``self._menu``.
    class _TrackingMenu(_FakeMenu):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, **kw)
            fake.menus.append(self)  # type: ignore[attr-defined]

    fake.Menu = _TrackingMenu

    original = mod.ui
    mod.ui = fake
    try:
        yield fake
    finally:
        mod.ui = original


# ─── MENU_ITEMS contract ─────────────────────────────────────────────────────


class TestMenuItems:
    def test_module_re_export_matches_internal_constant(self) -> None:
        assert OPTIONS_MENU_ITEMS is MENU_ITEMS

    def test_has_six_entries_matching_plan(self) -> None:
        """LAYERS-PLAN Step 53 lists six checkbox toggles."""
        assert len(MENU_ITEMS) == 6

    def test_labels_in_expected_order(self) -> None:
        labels = [label for _prop, label in MENU_ITEMS]
        assert labels == [
            "Show Layer Contents",
            "Show Session Layer",
            "Show Missing References",
            "Show Merge/Flatten Warnings",
            "Show File Extensions in Name",
            "Info Notifications",
        ]

    def test_every_prop_name_exists_on_layer_settings(self) -> None:
        """A typo in the menu list would ship a silently-broken checkbox."""
        ls = LayerSettings(Settings())
        for prop_name, _label in MENU_ITEMS:
            assert hasattr(ls, prop_name), (
                f"MENU_ITEMS references unknown LayerSettings attribute "
                f"{prop_name!r}"
            )

    def test_every_prop_name_exists_on_default_settings(self) -> None:
        ds = DefaultLayerSettings()
        for prop_name, _label in MENU_ITEMS:
            assert hasattr(ds, prop_name)


# ─── OptionsButton construction + surface ────────────────────────────────────


class TestOptionsButtonConstruction:
    def test_accepts_layer_settings(self) -> None:
        ls = LayerSettings(Settings())
        b = OptionsButton(ls)
        assert b.settings is ls

    def test_accepts_default_layer_settings(self) -> None:
        ds = DefaultLayerSettings()
        b = OptionsButton(ds)
        assert b.settings is ds

    def test_menu_is_none_before_first_open(self) -> None:
        b = OptionsButton(DefaultLayerSettings())
        assert b.menu is None

    def test_menu_item_labels_returns_ordered_labels(self) -> None:
        b = OptionsButton(DefaultLayerSettings())
        assert b.menu_item_labels() == [
            "Show Layer Contents",
            "Show Session Layer",
            "Show Missing References",
            "Show Merge/Flatten Warnings",
            "Show File Extensions in Name",
            "Info Notifications",
        ]


# ─── Toggle write path ───────────────────────────────────────────────────────


class TestToggleWritePath:
    def test_toggle_flips_layer_settings_value(self) -> None:
        s = Settings()
        ls = LayerSettings(s)
        b = OptionsButton(ls)
        assert ls.show_session_layer is True
        b.toggle("show_session_layer")
        assert ls.show_session_layer is False
        # And it persists through the backing Settings store.
        assert s.get("layers.show_session_layer") is False
        b.toggle("show_session_layer")
        assert ls.show_session_layer is True
        assert s.get("layers.show_session_layer") is True

    def test_toggle_flips_default_layer_settings_value(self) -> None:
        ds = DefaultLayerSettings()
        b = OptionsButton(ds)
        assert ds.show_layer_contents is True
        b.toggle("show_layer_contents")
        assert ds.show_layer_contents is False

    def test_toggle_fires_layer_settings_subscriber(self) -> None:
        """A toggle must notify every subscriber of the key."""
        s = Settings()
        ls = LayerSettings(s)
        b = OptionsButton(ls)
        calls: list = []
        sub = s.subscribe(
            "layers.show_session_layer", lambda k, v: calls.append((k, v))
        )
        try:
            b.toggle("show_session_layer")
            assert calls == [("layers.show_session_layer", False)]
            b.toggle("show_session_layer")
            assert calls == [
                ("layers.show_session_layer", False),
                ("layers.show_session_layer", True),
            ]
        finally:
            sub.cancel()


# ─── End-to-end: toggle → model rebuild ──────────────────────────────────────


class TestModelRebuildOnToggle:
    def test_tree_shape_toggle_reshapes_layer_model(self) -> None:
        """Toggling ``show_session_layer`` via the button reshapes the tree.

        This is the key behaviour Step 53 delivers: the checkbox writes
        through to ``LayerSettings``, the ``Settings`` subscribers fire,
        :meth:`LayerModel._on_settings_changed` walks the tree, and
        :meth:`get_item_children` returns a different set on the next
        paint — all without a manual rebuild call.
        """
        s = Settings()
        ls = LayerSettings(s)
        adapter = MockLayerStackAdapter(include_session=True)
        model = LayerModel(adapter, settings=ls)
        button = OptionsButton(ls)
        try:
            # Default: session layer visible. Root is the single child
            # of the implicit ``None`` root.
            children_before = model.get_item_children(None)
            assert len(children_before) == 2  # root + session
            # Fire the toggle via the public surface.
            button.toggle("show_session_layer")
            children_after = model.get_item_children(None)
            assert len(children_after) == 1  # session hidden
        finally:
            button.destroy()
            model.destroy()


# ─── Menu build + item wiring ────────────────────────────────────────────────


class TestMenuBuild:
    def test_show_at_builds_menu_with_expected_items(
        self, fake_ui_module: Any
    ) -> None:
        b = OptionsButton(DefaultLayerSettings())
        b.show_at(40.0, 50.0)
        assert b.menu is not None
        assert len(b.menu.items) == 6
        labels = [item.label for item in b.menu.items]
        assert labels == [
            "Show Layer Contents",
            "Show Session Layer",
            "Show Missing References",
            "Show Merge/Flatten Warnings",
            "Show File Extensions in Name",
            "Info Notifications",
        ]

    def test_every_item_is_checkable(self, fake_ui_module: Any) -> None:
        b = OptionsButton(DefaultLayerSettings())
        b.show_at(0.0, 0.0)
        for item in b.menu.items:
            assert item.checkable is True

    def test_checked_reflects_current_settings_state(
        self, fake_ui_module: Any
    ) -> None:
        ds = DefaultLayerSettings(
            show_session_layer=False,
            show_layer_contents=True,
        )
        b = OptionsButton(ds)
        b.show_at(0.0, 0.0)
        by_label = {it.label: it for it in b.menu.items}
        assert by_label["Show Session Layer"].checked is False
        assert by_label["Show Layer Contents"].checked is True

    def test_menu_show_at_coordinates_forwarded(
        self, fake_ui_module: Any
    ) -> None:
        b = OptionsButton(DefaultLayerSettings())
        b.show_at(123.0, 456.0)
        assert b.menu.shown_at == (123.0, 456.0)

    def test_menu_triggered_fn_toggles_corresponding_setting(
        self, fake_ui_module: Any
    ) -> None:
        ds = DefaultLayerSettings()
        b = OptionsButton(ds)
        b.show_at(0.0, 0.0)
        before = ds.show_layer_contents
        by_label = {it.label: it for it in b.menu.items}
        by_label["Show Layer Contents"].triggered_fn()
        assert ds.show_layer_contents is (not before)

    def test_menu_triggered_fn_pin_prop_name_per_iteration(
        self, fake_ui_module: Any
    ) -> None:
        """The default-argument capture must pin each entry's prop name.

        Without ``lambda n=prop_name: ...`` every MenuItem would fire
        with the last loop iteration's property — the classic
        closure-over-loop-variable bug. This test asserts each
        triggered_fn flips its *own* setting, not the last one.
        """
        ds = DefaultLayerSettings()
        b = OptionsButton(ds)
        b.show_at(0.0, 0.0)
        for item in b.menu.items:
            # Capture initial values for every tracked attribute.
            pass
        before = {
            prop_name: getattr(ds, prop_name)
            for prop_name, _label in MENU_ITEMS
        }
        # Trigger every item in turn; each must flip only its own flag.
        for item, (prop_name, _label) in zip(b.menu.items, MENU_ITEMS):
            item.triggered_fn()
            assert getattr(ds, prop_name) is (not before[prop_name])

    def test_second_show_at_destroys_previous_menu(
        self, fake_ui_module: Any
    ) -> None:
        """The previous popup must be destroyed before a new one opens."""
        b = OptionsButton(DefaultLayerSettings())
        b.show_at(0.0, 0.0)
        first = b.menu
        b.show_at(10.0, 10.0)
        assert first is not None
        assert first.destroyed is True
        assert b.menu is not first
        assert b.menu.shown_at == (10.0, 10.0)


# ─── Click handling ──────────────────────────────────────────────────────────


class TestClickHandling:
    def test_left_click_opens_menu(self, fake_ui_module: Any) -> None:
        b = OptionsButton(DefaultLayerSettings())
        b._on_mouse_pressed(0.0, 0.0, 0, 0)  # button 0 = left
        assert b.menu is not None

    def test_right_click_is_ignored(self, fake_ui_module: Any) -> None:
        b = OptionsButton(DefaultLayerSettings())
        b._on_mouse_pressed(0.0, 0.0, 1, 0)  # button 1 = right
        assert b.menu is None

    def test_middle_click_is_ignored(self, fake_ui_module: Any) -> None:
        b = OptionsButton(DefaultLayerSettings())
        b._on_mouse_pressed(0.0, 0.0, 2, 0)  # button 2 = middle
        assert b.menu is None


# ─── Destroy ────────────────────────────────────────────────────────────────


class TestDestroy:
    def test_destroy_drops_pinned_menu(self, fake_ui_module: Any) -> None:
        b = OptionsButton(DefaultLayerSettings())
        b.show_at(0.0, 0.0)
        built = b.menu
        assert built is not None
        b.destroy()
        assert b.menu is None
        assert built.destroyed is True

    def test_destroy_is_idempotent(self, fake_ui_module: Any) -> None:
        b = OptionsButton(DefaultLayerSettings())
        b.show_at(0.0, 0.0)
        b.destroy()
        # Second call must not raise.
        b.destroy()
        assert b.menu is None

    def test_destroy_without_open_menu(self) -> None:
        b = OptionsButton(DefaultLayerSettings())
        # Never opened — destroy should just no-op.
        b.destroy()
        assert b.menu is None


# ─── Window integration ─────────────────────────────────────────────────────


class TestLayerWindowIntegration:
    def test_window_constructs_options_button_with_settings(self) -> None:
        class FakeApp:
            def __init__(self) -> None:
                self.settings = Settings()
                self.undo_manager = MagicMock()

        app = FakeApp()
        adapter = MockLayerStackAdapter()
        w = LayerWindow(services=app, adapter=adapter)
        try:
            assert w._options_button is not None
            # The button shares the window's settings identity so a
            # toggle goes through the same wrapper LayerModel reads.
            assert w._options_button.settings is w.settings
        finally:
            w.destroy()

    def test_window_destroy_releases_options_button(
        self, fake_ui_module: Any
    ) -> None:
        w = LayerWindow(
            services=MagicMock(),
            adapter=MockLayerStackAdapter(),
            settings=DefaultLayerSettings(),
        )
        button = w._options_button
        assert button is not None
        # Open the menu so destroy has something to tear down.
        button.show_at(0.0, 0.0)
        built_menu = button.menu
        assert built_menu is not None
        w.destroy()
        assert w._options_button is None
        assert built_menu.destroyed is True

    def test_window_toggle_via_button_reshapes_model(self) -> None:
        """End-to-end: real window, real settings, toggle reshapes tree."""
        class FakeApp:
            def __init__(self) -> None:
                self.settings = Settings()
                self.undo_manager = MagicMock()

        app = FakeApp()
        adapter = MockLayerStackAdapter(include_session=True)
        w = LayerWindow(services=app, adapter=adapter)
        try:
            # Build once so the model exists.
            w._build_ui()
            model = w._model
            assert model is not None
            button = w._options_button
            assert button is not None
            assert len(model.get_item_children(None)) == 2
            button.toggle("show_session_layer")
            assert len(model.get_item_children(None)) == 1
        finally:
            w.destroy()

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for menu_bar and __main__ modules — OvGear Step 9."""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class TestMenuBarImport:
    def test_module_imports(self):
        import ovui_widgets.app
        import ovui_widgets.app.menu_bar  # noqa: F401

    def test_build_menu_bar_is_callable(self):
        from ovui_widgets.app.menu_bar import build_menu_bar
        assert callable(build_menu_bar)

    def test_build_edit_menu_is_callable(self):
        from ovui_widgets.app.menu_bar import _build_edit_menu
        assert callable(_build_edit_menu)

    def test_build_file_menu_is_callable(self):
        from ovui_widgets.app.menu_bar import _build_file_menu
        assert callable(_build_file_menu)

    def test_build_tools_menu_is_callable(self):
        from ovui_widgets.app.menu_bar import _build_tools_menu
        assert callable(_build_tools_menu)

    def test_build_view_menu_is_callable(self):
        from ovui_widgets.app.menu_bar import _build_view_menu
        assert callable(_build_view_menu)

    def test_frame_selected_is_callable(self):
        from ovui_widgets.app.menu_bar import _frame_selected
        assert callable(_frame_selected)

    def test_product_identity_helpers_are_callable(self):
        from ovui_widgets.app.menu_bar import _build_product_identity, _get_logo_provider
        assert callable(_build_product_identity)
        assert callable(_get_logo_provider)

    def test_on_exit_is_callable(self):
        from ovui_widgets.app.menu_bar import _on_exit
        assert callable(_on_exit)


def test_file_new_routes_to_public_application_new_stage(monkeypatch) -> None:
    import ovui_widgets.app.menu_bar as mb

    items: list[tuple[str, dict]] = []

    class _Menu:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    fake_ui = SimpleNamespace(
        MenuItem=lambda label, **kwargs: items.append((label, kwargs)),
        Separator=lambda: None,
    )
    new_stage = MagicMock(return_value=True)
    app = SimpleNamespace(
        new_stage=new_stage,
        _can_create_empty_startup_stage=lambda: True,
    )
    monkeypatch.setattr(mb, "ui", fake_ui)
    monkeypatch.setattr(mb, "create_flat_menu", lambda *_args, **_kwargs: _Menu())
    monkeypatch.setattr(mb, "_can_save_stage", lambda _app: False)
    monkeypatch.setattr(mb, "_app_menu_registry", lambda _app: object())
    monkeypatch.setattr(mb, "_build_hook_items", lambda *_args: None)

    mb._build_file_menu(app)
    new_item = next(kwargs for label, kwargs in items if label == "New")
    assert new_item["enabled"] is True
    new_item["triggered_fn"]()
    new_stage.assert_called_once_with()


class TestEditMenuInvalidation:
    class _UndoManager:
        def __init__(self):
            self._callback = None

        def subscribe_change(self, callback):
            self._callback = callback
            return TestEditMenuInvalidation._Subscription()

    class _Subscription:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    class _Menu:
        def __init__(self):
            self.invalidations = 0

        def invalidate(self):
            self.invalidations += 1

    def test_edit_menu_invalidates_when_undo_stack_changes(self):
        import ovui_widgets.app.menu_bar as mb

        undo_manager = self._UndoManager()
        edit_menu = self._Menu()
        app = SimpleNamespace(undo_manager=undo_manager)

        mb._wire_edit_menu_invalidation(app, edit_menu)

        assert app._edit_menu is edit_menu
        undo_manager._callback()
        assert edit_menu.invalidations == 1

    def test_rewiring_edit_menu_cancels_previous_subscription(self):
        import ovui_widgets.app.menu_bar as mb

        app = SimpleNamespace(undo_manager=self._UndoManager())
        first_menu = self._Menu()
        second_menu = self._Menu()

        mb._wire_edit_menu_invalidation(app, first_menu)
        first_subscription = app._edit_menu_undo_subscription
        mb._wire_edit_menu_invalidation(app, second_menu)

        assert first_subscription.cancelled is True
        assert app._edit_menu is second_menu


class TestLayerMenuInvalidation:
    class _Menu:
        def __init__(self):
            self.shown_changed_fn = None
            self.invalidations = 0

        def set_shown_changed_fn(self, callback):
            self.shown_changed_fn = callback

        def invalidate(self):
            self.invalidations += 1

    def test_layer_menu_invalidates_when_visibility_changes(self):
        import ovui_widgets.app.menu_bar as mb

        app = SimpleNamespace()
        layer_menu = self._Menu()

        mb._wire_layer_menu_invalidation(app, layer_menu)

        assert app._layer_menu is layer_menu
        assert callable(layer_menu.shown_changed_fn)
        layer_menu.shown_changed_fn(True)
        layer_menu.shown_changed_fn(False)
        assert layer_menu.invalidations == 2


class TestContributedMenuInvalidation:
    class _Menu:
        def __init__(self):
            self.shown_changed_fn = None
            self.invalidations = 0

        def set_shown_changed_fn(self, callback):
            self.shown_changed_fn = callback

        def invalidate(self):
            self.invalidations += 1

    def test_contributed_menu_invalidates_when_visibility_changes(self):
        import ovui_widgets.app.menu_bar as mb

        mb._CONTRIBUTED_MENUS.clear()
        menu = self._Menu()
        try:
            mb._wire_contributed_menu_invalidation(("Physics",), menu)

            assert callable(menu.shown_changed_fn)
            menu.shown_changed_fn(True)
            menu.shown_changed_fn(False)

            assert menu.invalidations == 2
        finally:
            mb._CONTRIBUTED_MENUS.clear()

    def test_contributed_action_invalidates_registered_menus(self):
        import ovui_widgets.app.menu_bar as mb

        mb._CONTRIBUTED_MENUS.clear()
        menu = self._Menu()
        calls = []
        contribution = mb.MenuContribution(
            menu_path=("Physics",),
            stable_id="physics.test",
            label="Test",
            action=lambda: calls.append("action"),
        )
        try:
            mb._wire_contributed_menu_invalidation(("Physics",), menu)

            mb._run_contribution_action(contribution)

            assert calls == ["action"]
            assert menu.invalidations == 1
        finally:
            mb._CONTRIBUTED_MENUS.clear()


class TestGlobalMenuContributionShim:
    def test_register_menu_item_forwards_into_app_menu_registry(self):
        import ovui_widgets.app.menu_bar as mb
        from ovui_widgets.app.menu_hooks import AppMenuRegistry

        calls = []
        app = SimpleNamespace()
        app.menus = AppMenuRegistry(app)
        handle = mb.register_menu_item(
            mb.MenuContribution(
                menu_path=("Physics", "Simulation"),
                stable_id="physics.forwarded",
                label=lambda: "Forwarded Physics",
                order=12,
                action=lambda: calls.append("triggered"),
                enabled=lambda: True,
                hotkey_text="Ctrl+P",
            )
        )
        try:
            mb._ensure_global_menu_provider(app)
            entries = app.menus.iter_contributions(("Physics", "Simulation"))

            assert len(entries) == 1
            entry = entries[0]
            assert entry.id == "legacy_menu.physics.forwarded"
            assert entry.label == "Forwarded Physics"
            assert entry.parent_path == ("Physics", "Simulation")
            assert entry.order == 12
            assert entry.enabled is True
            assert entry.hotkey_text == "Ctrl+P"
            assert entry.widget_name == "legacy_menu_physics_forwarded"

            assert callable(entry.callback)
            entry.callback(app)
            assert calls == ["triggered"]
        finally:
            handle.cancel()
            app.menus.clear()


class TestMenuBarProductIdentity:
    class _FakeContext:
        def __init__(self, events, kind, label=None, kwargs=None):
            self._events = events
            self._kind = kind
            self._label = label
            self._kwargs = kwargs or {}

        def __enter__(self):
            self._events.append((f"{self._kind}:enter", self._label, self._kwargs))
            return self

        def __exit__(self, exc_type, exc, tb):
            self._events.append((f"{self._kind}:exit", self._label, {}))
            return False

    class _FakeUi:
        def __init__(self):
            self.events = []

        def Spacer(self, **kwargs):
            self.events.append(("Spacer", None, kwargs))

        def ImageWithProvider(self, provider, **kwargs):
            self.events.append(("ImageWithProvider", provider, kwargs))

        def VStack(self, **kwargs):
            self.events.append(("VStack", None, kwargs))
            return TestMenuBarProductIdentity._FakeContext(
                self.events, "VStack", None, kwargs
            )

        def Label(self, text, **kwargs):
            self.events.append(("Label", text, kwargs))

        def Rectangle(self, **kwargs):
            self.events.append(("Rectangle", None, kwargs))

        def Menu(self, label, **kwargs):
            self.events.append(("Menu", label, kwargs))
            return TestMenuBarProductIdentity._FakeContext(
                self.events, "Menu", label, kwargs
            )

        def MenuItem(self, label, **kwargs):
            self.events.append(("MenuItem", label, kwargs))

        def Separator(self, **kwargs):
            self.events.append(("Separator", None, kwargs))

    def test_product_identity_precedes_existing_top_level_menus(self):
        import ovui_widgets.app.menu_bar as mb

        fake_ui = self._FakeUi()
        sentinel_provider = object()
        original_ui = mb.ui
        original_get_logo_provider = mb._get_logo_provider
        try:
            mb.ui = fake_ui
            mb._get_logo_provider = lambda: sentinel_provider
            mb.build_menu_bar(MagicMock())
        finally:
            mb.ui = original_ui
            mb._get_logo_provider = original_get_logo_provider

        event_names = [event[0] for event in fake_ui.events[:12]]
        assert event_names == [
            "Spacer",
            "VStack",
            "VStack:enter",
            "Spacer",
            "ImageWithProvider",
            "Spacer",
            "VStack:exit",
            "Spacer",
            "Label",
            "Spacer",
            "Rectangle",
            "Spacer",
        ]
        assert fake_ui.events[1][2]["height"] == mb.MENU_BAR_HEIGHT
        assert fake_ui.events[3][2]["height"] == mb._LOGO_TOP_PADDING
        assert fake_ui.events[4][1] is sentinel_provider
        assert fake_ui.events[5][2]["height"] == mb._LOGO_BOTTOM_PADDING
        assert mb._LOGO_TOP_PADDING == mb._LOGO_BOTTOM_PADDING
        assert fake_ui.events[8][1] == mb.PRODUCT_LABEL

        top_level_menus = [
            label
            for kind, label, _ in fake_ui.events
            if kind == "Menu" and label in mb.TOP_LEVEL_MENU_LABELS
        ]
        assert top_level_menus == list(mb.TOP_LEVEL_MENU_LABELS)

    def test_builds_inside_real_ui_menu_bar_context(self):
        """Smoke-test the actual ``ui.MenuBar`` path used by Application."""
        import omni.ui as ui

        from ovui_widgets.app.menu_bar import build_menu_bar

        app = MagicMock()
        win = ui.Window(
            "_test_step11_menu_bar",
            width=500,
            height=80,
            flags=(
                ui.WINDOW_FLAGS_NO_TITLE_BAR
                | ui.WINDOW_FLAGS_NO_RESIZE
                | ui.WINDOW_FLAGS_NO_MOVE
                | ui.WINDOW_FLAGS_NO_SCROLLBAR
                | ui.WINDOW_FLAGS_MENU_BAR
                | ui.WINDOW_FLAGS_NO_DOCKING
                | ui.WINDOW_FLAGS_NO_BACKGROUND
            ),
        )
        try:
            with win.frame:
                with ui.MenuBar():
                    build_menu_bar(app)
        finally:
            win.destroy()


class TestFrameSelectedMenu:
    def test_no_selection_is_noop(self):
        """``_frame_selected`` tolerates an empty selection without raising."""
        from ovui_widgets.app.menu_bar import _frame_selected
        app = MagicMock()
        app.selection_bus.get_snapshot.return_value = None
        app._viewport_window = None
        _frame_selected(app)  # must not raise
        app._viewport_window = MagicMock()
        app._viewport_window.frame_paths.assert_not_called()

    def test_empty_items_list_is_noop(self):
        from ovui_widgets.app.menu_bar import _frame_selected
        app = MagicMock()
        snap = MagicMock()
        snap.items = []
        app.selection_bus.get_snapshot.return_value = snap
        _frame_selected(app)
        app._viewport_window.frame_paths.assert_not_called()

    def test_forwards_paths_to_viewport(self):
        from ovui_widgets.app.menu_bar import _frame_selected
        app = MagicMock()
        snap = MagicMock()
        snap.items = [MagicMock(path="/World/Sphere"), MagicMock(path="/World/Cube")]
        app.selection_bus.get_snapshot.return_value = snap
        _frame_selected(app)
        app._viewport_window.frame_paths.assert_called_once_with(
            ["/World/Sphere", "/World/Cube"]
        )


class TestOnExit:
    """Issue #35 Step 6 (Codex Round 1 F8): ``_on_exit`` no longer
    calls ``ui.shutdown()`` directly — it now flips
    ``Application._running`` via :meth:`Application.request_exit` so
    ``run_async``'s ``finally:`` clause drives :meth:`shutdown` against
    a live ovui standalone backend. The test below pins that contract.
    """

    def test_on_exit_calls_request_exit(self) -> None:
        """``_on_exit`` must drive the ``request_exit`` path: it sets
        ``Application._running`` to ``False`` so ``run_async``'s loop
        exits at the next frame boundary.
        """
        from ovui_widgets.app.application import Application
        from ovui_widgets.common.selection import SelectionBus
        Application._instance = None
        SelectionBus._instance = None
        app = Application()
        try:
            from ovui_widgets.app.menu_bar import _on_exit
            app._running = True
            _on_exit()
            assert app._running is False, (
                "issue #35 Step 6: _on_exit must flip _running to False "
                "via Application.request_exit() — found _running still True"
            )
        finally:
            app.shutdown()
            Application._instance = None
            SelectionBus._instance = None

    def test_on_exit_does_not_call_ui_shutdown(self) -> None:
        """Defence-in-depth: ``_on_exit`` MUST NOT call
        ``ui.shutdown()``. The original Step-1-era implementation did,
        which broke ovui's run loop before
        :meth:`Application.shutdown` could fire — that was the issue
        #35 root cause.
        """
        import types

        from ovui_widgets.app.application import Application
        from ovui_widgets.common.selection import SelectionBus

        Application._instance = None
        SelectionBus._instance = None
        app = Application()
        ui_shutdown_calls: list[bool] = []
        try:
            import ovui_widgets.app.menu_bar as mb

            # Replace mb.ui with a fake module exposing a shutdown
            # spy. If the new _on_exit body still references mb.ui in
            # any way that ends up calling shutdown, the spy fires.
            fake_ui = types.ModuleType("omni.ui")
            fake_ui.shutdown = lambda: ui_shutdown_calls.append(True)
            original_ui = mb.ui
            try:
                mb.ui = fake_ui  # type: ignore[assignment]
                app._running = True
                mb._on_exit()
            finally:
                mb.ui = original_ui  # type: ignore[assignment]

            assert ui_shutdown_calls == [], (
                "_on_exit must NOT call ui.shutdown() (issue #35 Step 6); "
                f"got {len(ui_shutdown_calls)} call(s)"
            )
            assert app._running is False, (
                "_on_exit must still flip _running to False via request_exit"
            )
        finally:
            app.shutdown()
            Application._instance = None
            SelectionBus._instance = None

    def test_on_exit_no_application_instance_is_silent(self) -> None:
        """If ``Application.instance()`` raises (no Application yet),
        ``_on_exit`` must NOT propagate — the menu may still fire
        once during a stale callback after shutdown.
        """
        from ovui_widgets.app.application import Application
        from ovui_widgets.common.selection import SelectionBus

        Application._instance = None
        SelectionBus._instance = None
        try:
            from ovui_widgets.app.menu_bar import _on_exit
            # Application.instance() raises RuntimeError when _instance
            # is None — _on_exit must catch this silently.
            _on_exit()  # MUST NOT raise
        finally:
            Application._instance = None
            SelectionBus._instance = None


class TestWindowMenuLayers:
    """Verify the 'Window > Layers' entry toggles ``app._layer_window`` visibility."""

    def _collect_window_menu_items(self, app):
        """Invoke build_menu_bar with a fake ui and return captured Window-menu items.

        The fake records any ``MenuItem`` constructed while inside a ``Menu``
        whose label is ``"Window"``, keyed by label. The Layers entry is
        stored as a dict so we can inspect both ``checked`` and
        ``triggered_fn``.
        """
        import types

        import ovui_widgets.app.menu_bar as mb

        items = {}
        active_menu = [None]

        class FakeMenu:
            def __init__(self, label, *a, **kw):
                self.label = label
            def __enter__(self):
                active_menu[0] = self.label
                return self
            def __exit__(self, *a):
                active_menu[0] = None

        class FakeMenuItem:
            def __init__(self, label, triggered_fn=None, checkable=False,
                         checked=False, **kwargs):
                if active_menu[0] == "Window":
                    items[label] = {
                        "triggered_fn": triggered_fn,
                        "checkable": checkable,
                        "checked": checked,
                    }

        class FakeSeparator:
            def __init__(self, *a, **kw):
                pass

        fake_ui = types.ModuleType("omni.ui")
        fake_ui.Menu = FakeMenu
        fake_ui.MenuItem = FakeMenuItem
        fake_ui.Separator = FakeSeparator
        fake_ui.Spacer = lambda *a, **kw: None

        original_ui = mb.ui
        original_identity = mb._build_product_identity
        try:
            mb.ui = fake_ui
            mb._build_product_identity = lambda: None
            mb.build_menu_bar(app)
        finally:
            mb.ui = original_ui
            mb._build_product_identity = original_identity
        return items

    def test_layers_menu_item_exists(self):
        """``Window > Layers`` must be present after build_menu_bar."""
        fake_app = MagicMock()
        fake_app._layer_window = MagicMock(visible=True)
        items = self._collect_window_menu_items(fake_app)
        assert "Layers" in items, f"Layers entry missing from Window menu ({sorted(items)})"

    def test_layers_menu_item_is_checkable(self):
        fake_app = MagicMock()
        fake_app._layer_window = MagicMock(visible=True)
        items = self._collect_window_menu_items(fake_app)
        assert items["Layers"]["checkable"] is True

    def test_layers_menu_item_checked_reflects_window_visibility(self):
        """``checked`` mirrors ``app._layer_window.visible`` at build time."""
        for visible in (True, False):
            fake_app = MagicMock()
            fake_app._layer_window = MagicMock(visible=visible)
            items = self._collect_window_menu_items(fake_app)
            assert items["Layers"]["checked"] is visible

    def test_layers_menu_item_checked_false_when_window_none(self):
        """Defensive: missing ``_layer_window`` must not raise at build time."""
        fake_app = MagicMock()
        fake_app._layer_window = None
        items = self._collect_window_menu_items(fake_app)
        assert items["Layers"]["checked"] is False

    def test_layers_menu_item_toggle_flips_visibility(self):
        """Firing ``triggered_fn`` toggles ``_layer_window.visible``."""
        fake_app = MagicMock()

        class FakeWindow:
            def __init__(self):
                self.visible = False
        fake_app._layer_window = FakeWindow()

        items = self._collect_window_menu_items(fake_app)
        cb = items["Layers"]["triggered_fn"]
        assert cb is not None

        cb()
        assert fake_app._layer_window.visible is True
        cb()
        assert fake_app._layer_window.visible is False

    def test_layers_menu_item_toggle_noop_when_window_none(self):
        """Guarded by ``_toggle_window`` — no AttributeError when window is None."""
        fake_app = MagicMock()
        fake_app._layer_window = None
        items = self._collect_window_menu_items(fake_app)
        cb = items["Layers"]["triggered_fn"]
        cb()  # must not raise


class TestMainModuleImport:
    def test_main_module_imports(self):
        import ovui_widgets.app.__main__  # noqa: F401

    def test_main_function_is_callable(self):
        from ovui_widgets.app.__main__ import main
        assert callable(main)


class TestWindowMenuIncludesContentBrowser:
    """Step 11: Window menu must expose a Content Browser toggle entry."""

    def test_build_menu_bar_creates_content_browser_item(self):
        """``build_menu_bar`` must call ``ui.MenuItem`` with the
        ``"Content Browser"`` label so users can toggle the panel.

        Exercised via a patched ``omni.ui`` module that records every
        ``MenuItem`` construction the builder performs. This does not
        need a live ovui context — the contract under test is purely the
        label we emit.
        """
        import types
        from unittest.mock import MagicMock

        import ovui_widgets.app.menu_bar as mb

        recorded_labels = []

        class _FakeMenuItem:
            def __init__(self, label, *a, **kw):
                recorded_labels.append(label)

        class _FakeContext:
            def __init__(self, *a, **kw):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        fake_ui = types.SimpleNamespace(
            Menu=_FakeContext,
            MenuBar=_FakeContext,
            MenuItem=_FakeMenuItem,
            Separator=lambda *a, **kw: None,
            # Stubs for the product-identity strip added by the main-branch
            # design overhaul — the strip renders before any Menu item and
            # uses these widgets. Tests care only about MenuItem labels,
            # so these are silent no-ops.
            Spacer=lambda *a, **kw: None,
            VStack=_FakeContext,
            HStack=_FakeContext,
            ImageWithProvider=lambda *a, **kw: None,
            Label=lambda *a, **kw: None,
            Rectangle=lambda *a, **kw: None,
        )
        original = mb.ui
        original_logo = mb._get_logo_provider
        try:
            mb.ui = fake_ui
            mb._get_logo_provider = lambda: object()
            app = MagicMock()
            mb.build_menu_bar(app)
        finally:
            mb.ui = original
            mb._get_logo_provider = original_logo

        assert "Content Browser" in recorded_labels

    def test_content_browser_entry_follows_viewport(self):
        """The Content Browser entry should sit under Stage / Property / Viewport
        in that order, so the Window menu reads top-to-bottom in dock-order."""
        import types
        from unittest.mock import MagicMock

        import ovui_widgets.app.menu_bar as mb

        labels: list[str] = []

        class _FakeMenuItem:
            def __init__(self, label, *a, **kw):
                labels.append(label)

        class _FakeContext:
            def __init__(self, *a, **kw):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        fake_ui = types.SimpleNamespace(
            Menu=_FakeContext,
            MenuBar=_FakeContext,
            MenuItem=_FakeMenuItem,
            Separator=lambda *a, **kw: None,
            Spacer=lambda *a, **kw: None,
            VStack=_FakeContext,
            HStack=_FakeContext,
            ImageWithProvider=lambda *a, **kw: None,
            Label=lambda *a, **kw: None,
            Rectangle=lambda *a, **kw: None,
        )
        original = mb.ui
        original_logo = mb._get_logo_provider
        try:
            mb.ui = fake_ui
            mb._get_logo_provider = lambda: object()
            mb.build_menu_bar(MagicMock())
        finally:
            mb.ui = original
            mb._get_logo_provider = original_logo

        # Locate index of each window-menu label; Viewport must precede Content Browser.
        vp_idx = labels.index("Viewport")
        cb_idx = labels.index("Content Browser")
        assert cb_idx == vp_idx + 1

    def test_content_browser_toggle_calls_toggle_window(self):
        """Clicking the Content Browser menu entry must flip the content
        window's visibility via ``_toggle_window``."""
        from unittest.mock import MagicMock

        import ovui_widgets.app.menu_bar as mb

        app = MagicMock()
        mw = MagicMock()
        mw.visible = True
        app._content_window = mw

        mb._toggle_window(app._content_window)
        assert mw.visible is False
        mb._toggle_window(app._content_window)
        assert mw.visible is True


class TestOnOpenClicked:
    """Step 54 — File > Open triggers :class:`FileImporterHelper`, not stdin.

    The pre-Step-54 handler shelled out to ``sys.stdin.readline`` for a
    path; Step 54 replaces that with the Step-53 importer helper so the
    user sees a GUI file picker. These tests patch the helper singleton
    to assert the dispatch shape without spinning up a live ovui window.
    """

    def _patch_importer(self, monkeypatch):
        """Swap :class:`FileImporterHelper.instance` with a recording stub.

        Returns the recorded call list — each entry is the kwargs dict
        passed to ``stub.show()``. The stub's :meth:`show` captures every
        call so the test can assert both that the helper was reached
        *and* what configuration the menu handler forwarded.
        """
        calls: list = []

        class _Stub:
            def show(self, **kwargs):
                calls.append(kwargs)

        stub = _Stub()

        def _fake_instance():
            return stub

        from ovui_widgets.content import file_importer as fi_mod

        monkeypatch.setattr(
            fi_mod.FileImporterHelper, "instance", classmethod(
                lambda cls: stub,
            ),
        )
        return calls

    def test_open_clicked_calls_file_importer_helper(self, monkeypatch):
        from ovui_widgets.app.menu_bar import _on_open_clicked

        calls = self._patch_importer(monkeypatch)
        app = MagicMock()
        _on_open_clicked(app)
        assert len(calls) == 1

    def test_open_clicked_does_not_read_stdin(self, monkeypatch):
        """No stdin read — the old path would hang on an interactive run."""
        import sys

        from ovui_widgets.app.menu_bar import _on_open_clicked

        self._patch_importer(monkeypatch)
        app = MagicMock()

        original_readline = sys.stdin.readline
        readline_called = []

        def _tripwire():
            readline_called.append(True)
            return ""

        sys.stdin.readline = _tripwire
        try:
            _on_open_clicked(app)
        finally:
            sys.stdin.readline = original_readline
        assert readline_called == []

    def test_open_clicked_passes_usd_extensions(self, monkeypatch):
        from ovui_widgets.app.menu_bar import _on_open_clicked

        calls = self._patch_importer(monkeypatch)
        _on_open_clicked(MagicMock())
        kwargs = calls[0]
        # USD Files first, All files second — architecture §22.1 default.
        ext_types = kwargs["file_extension_types"]
        assert ext_types[0] == (
            "*.usd, *.usda, *.usdc, *.usdz", "USD Files",
        )
        assert ("*.*", "All files") in ext_types

    def test_open_clicked_enables_validation(self, monkeypatch):
        from ovui_widgets.app.menu_bar import _on_open_clicked

        calls = self._patch_importer(monkeypatch)
        _on_open_clicked(MagicMock())
        assert calls[0]["should_validate"] is True

    def test_open_clicked_uses_open_title_and_button_label(
        self, monkeypatch,
    ):
        from ovui_widgets.app.menu_bar import _on_open_clicked

        calls = self._patch_importer(monkeypatch)
        _on_open_clicked(MagicMock())
        assert calls[0]["title"] == "Open USD File"
        assert calls[0]["import_button_label"] == "Open"

    def test_import_handler_routes_selection_to_open_file(
        self, monkeypatch,
    ):
        """Selections (non-empty) win over filename — mirrors Kit's contract."""
        from ovui_widgets.app.menu_bar import _on_open_clicked

        calls = self._patch_importer(monkeypatch)
        app = MagicMock()
        _on_open_clicked(app)
        handler = calls[0]["import_handler"]
        handler(
            "demo.usda",
            "/home/user/Projects",
            ["/home/user/Projects/demo.usda"],
        )
        app.open_file.assert_called_once_with(
            "/home/user/Projects/demo.usda",
        )

    @pytest.mark.parametrize(
        ("platform", "selection", "expected"),
        [
            (
                "linux",
                "file:///home/user/Projects/demo.usda",
                "/home/user/Projects/demo.usda",
            ),
            (
                "win32",
                "file:///C:/Users/user/Projects/demo.usda",
                "C:/Users/user/Projects/demo.usda",
            ),
        ],
    )
    def test_import_handler_strips_file_scheme_from_selection(
        self, monkeypatch, platform, selection, expected,
    ):
        """LocalFSBackend selections are file:// URLs; OpenUSD needs a path."""
        import ovui_widgets.app.menu_bar as menu_bar

        monkeypatch.setattr(menu_bar.sys, "platform", platform)
        calls = self._patch_importer(monkeypatch)
        app = MagicMock()
        menu_bar._on_open_clicked(app)
        handler = calls[0]["import_handler"]

        handler("demo.usda", "", [selection])
        app.open_file.assert_called_once_with(expected)

    def test_import_handler_joins_dirname_and_filename(
        self, monkeypatch,
    ):
        """Empty selections → fall back to filename + dirname join."""
        from ovui_widgets.app.menu_bar import _on_open_clicked

        calls = self._patch_importer(monkeypatch)
        app = MagicMock()
        _on_open_clicked(app)
        handler = calls[0]["import_handler"]
        handler("demo.usda", "/home/user/Projects", [])
        app.open_file.assert_called_once_with(
            "/home/user/Projects/demo.usda",
        )

    @pytest.mark.parametrize(
        ("platform", "dirname", "expected"),
        [
            (
                "linux",
                "file:///home/user/Projects",
                "/home/user/Projects/demo.usda",
            ),
            (
                "win32",
                "file:///C:/Users/user/Projects",
                "C:/Users/user/Projects/demo.usda",
            ),
        ],
    )
    def test_import_handler_strips_file_scheme_after_join(
        self, monkeypatch, platform, dirname, expected,
    ):
        """Typed filename fallback also normalizes local file:// dirs."""
        import ovui_widgets.app.menu_bar as menu_bar

        monkeypatch.setattr(menu_bar.sys, "platform", platform)
        calls = self._patch_importer(monkeypatch)
        app = MagicMock()
        menu_bar._on_open_clicked(app)
        handler = calls[0]["import_handler"]

        handler("demo.usda", dirname, [])
        app.open_file.assert_called_once_with(expected)

    def test_import_handler_noops_on_empty_payload(self, monkeypatch):
        from ovui_widgets.app.menu_bar import _on_open_clicked

        calls = self._patch_importer(monkeypatch)
        app = MagicMock()
        _on_open_clicked(app)
        handler = calls[0]["import_handler"]
        handler("", "/home/user/Projects", [])
        app.open_file.assert_not_called()

    def test_import_handler_strips_trailing_slash_on_dirname(
        self, monkeypatch,
    ):
        """A trailing slash on dirname must not double-up on the join."""
        from ovui_widgets.app.menu_bar import _on_open_clicked

        calls = self._patch_importer(monkeypatch)
        app = MagicMock()
        _on_open_clicked(app)
        handler = calls[0]["import_handler"]
        handler("demo.usda", "/home/user/Projects/", [])
        app.open_file.assert_called_once_with(
            "/home/user/Projects/demo.usda",
        )


class TestOnSaveAsClicked:
    """Step 55 — File > Save As triggers :class:`FileExporterHelper`.

    Mirrors :class:`TestOnOpenClicked` but with the four-arg
    ``export_handler`` surface. The tests patch the helper's
    :meth:`instance` to a recording stub so the dispatch shape is
    verifiable without spinning up a live ovui window.
    """

    def _patch_exporter(self, monkeypatch):
        """Swap :class:`FileExporterHelper.instance` with a recording stub."""
        calls: list = []

        class _Stub:
            def show(self, **kwargs):
                calls.append(kwargs)

        stub = _Stub()

        from ovui_widgets.content import file_exporter as fe_mod

        monkeypatch.setattr(
            fe_mod.FileExporterHelper, "instance", classmethod(
                lambda cls: stub,
            ),
        )
        return calls

    def _non_exporting_app(self):
        from ovui_data_adapters.common import (
            AdapterCapabilities,
            AdapterCapability,
            StageCapabilities,
        )

        capabilities = AdapterCapabilities(
            stage=StageCapabilities(
                export_stage=AdapterCapability.unsupported(
                    "test adapter cannot export"
                )
            )
        )

        class _Session:
            def get_capabilities(self):
                return capabilities

            def can_export_stage(self):
                raise AssertionError("Save As must read explicit capabilities")

        return SimpleNamespace(
            _stage_adapter=object(),
            get_adapter_session=lambda: _Session(),
            save_stage_to=MagicMock(),
        )

    def test_save_as_clicked_calls_file_exporter_helper(self, monkeypatch):
        from ovui_widgets.app.menu_bar import _on_save_as_clicked

        calls = self._patch_exporter(monkeypatch)
        _on_save_as_clicked(MagicMock())
        assert len(calls) == 1

    def test_save_as_clicked_uses_save_title_and_button_label(
        self, monkeypatch,
    ):
        from ovui_widgets.app.menu_bar import _on_save_as_clicked

        calls = self._patch_exporter(monkeypatch)
        _on_save_as_clicked(MagicMock())
        assert calls[0]["title"] == "Save Stage As"
        assert calls[0]["export_button_label"] == "Save"

    def test_save_as_clicked_passes_usd_save_extensions(self, monkeypatch):
        """Architecture §22.4 — USD Binary/Ascii, USD Ascii, USD Crate."""
        from ovui_widgets.app.menu_bar import _on_save_as_clicked

        calls = self._patch_exporter(monkeypatch)
        _on_save_as_clicked(MagicMock())
        ext_types = calls[0]["file_extension_types"]
        assert ext_types == [
            ("*.usd", "USD Binary or Ascii"),
            ("*.usda", "USD Ascii"),
            ("*.usdc", "USD Crate"),
        ]

    def test_save_as_clicked_enables_validation(self, monkeypatch):
        from ovui_widgets.app.menu_bar import _on_save_as_clicked

        calls = self._patch_exporter(monkeypatch)
        _on_save_as_clicked(MagicMock())
        assert calls[0]["should_validate"] is True

    def test_export_handler_composes_filename_and_extension(
        self, monkeypatch, tmp_path,
    ):
        """Composed path joins dirname + filename + extension."""
        from ovui_widgets.app.menu_bar import _on_save_as_clicked

        calls = self._patch_exporter(monkeypatch)
        app = MagicMock()
        _on_save_as_clicked(app)
        handler = calls[0]["export_handler"]
        # Save into tmp_path so the exists() check deterministically misses.
        dirname = str(tmp_path)
        handler("newfile", dirname, ".usd", [])
        expected = os.path.join(dirname, "newfile.usd")
        app.save_stage_to.assert_called_once_with(expected)

    def test_export_handler_respects_typed_extension(
        self, monkeypatch, tmp_path,
    ):
        """Filename already ending in the combo ext isn't doubled up."""
        from ovui_widgets.app.menu_bar import _on_save_as_clicked

        calls = self._patch_exporter(monkeypatch)
        app = MagicMock()
        _on_save_as_clicked(app)
        handler = calls[0]["export_handler"]
        dirname = str(tmp_path)
        # User typed ``stage.usd`` with the ``.usd`` combo selected.
        handler("stage.usd", dirname, ".usd", [])
        expected = os.path.join(dirname, "stage.usd")
        app.save_stage_to.assert_called_once_with(expected)

    def test_export_handler_noops_on_empty_filename(
        self, monkeypatch, tmp_path,
    ):
        from ovui_widgets.app.menu_bar import _on_save_as_clicked

        calls = self._patch_exporter(monkeypatch)
        app = MagicMock()
        _on_save_as_clicked(app)
        handler = calls[0]["export_handler"]
        handler("", str(tmp_path), ".usd", [])
        app.save_stage_to.assert_not_called()

    def test_export_handler_strips_trailing_slash_on_dirname(
        self, monkeypatch, tmp_path,
    ):
        """A trailing slash on dirname must not double-up on the join."""
        from ovui_widgets.app.menu_bar import _on_save_as_clicked

        calls = self._patch_exporter(monkeypatch)
        app = MagicMock()
        _on_save_as_clicked(app)
        handler = calls[0]["export_handler"]
        # tmp_path is a PosixPath; appending "/" simulates a URL with
        # trailing slash post-navigate.
        dirname_trailing = str(tmp_path) + "/"
        handler("newfile", dirname_trailing, ".usd", [])
        expected = os.path.join(str(tmp_path), "newfile.usd")
        app.save_stage_to.assert_called_once_with(expected)

    @pytest.mark.parametrize(
        ("platform", "dirname", "expected"),
        [
            (
                "linux",
                "file:///home/user",
                os.path.join("/home/user", "Stage.usda"),
            ),
            (
                "win32",
                "file:///C:/Users/user",
                os.path.join("C:/Users/user", "Stage.usda"),
            ),
        ],
    )
    def test_export_handler_strips_file_scheme_before_save(
        self, monkeypatch, platform, dirname, expected,
    ):
        """LocalFSBackend save dirs are file:// URLs; USD export needs paths."""
        import ovui_widgets.app.menu_bar as menu_bar

        monkeypatch.setattr(menu_bar.sys, "platform", platform)
        calls = self._patch_exporter(monkeypatch)
        app = MagicMock()
        menu_bar._on_save_as_clicked(app)
        handler = calls[0]["export_handler"]

        handler("Stage", dirname, ".usda", [])

        app.save_stage_to.assert_called_once_with(expected)

    def test_export_handler_shows_overwrite_dialog_when_file_exists(
        self, monkeypatch, tmp_path,
    ):
        """Existing file → ConfirmOverwriteDialog, save deferred to Yes."""
        from ovui_widgets.app.menu_bar import _on_save_as_clicked

        calls = self._patch_exporter(monkeypatch)

        # Pre-create the target so os.path.exists returns True.
        existing = tmp_path / "existing.usd"
        existing.write_text("")

        # Stub ConfirmOverwriteDialog so we can observe the show call
        # without entering ovui.
        spawned: list = []

        class _FakeDialog:
            def __init__(self, url, *, on_yes=None, **kwargs):
                spawned.append((url, on_yes))

            def show(self):
                pass

        from ovui_widgets.content.widget import confirm_overwrite_dialog
        monkeypatch.setattr(
            confirm_overwrite_dialog,
            "ConfirmOverwriteDialog",
            _FakeDialog,
        )

        app = MagicMock()
        _on_save_as_clicked(app)
        handler = calls[0]["export_handler"]
        handler("existing", str(tmp_path), ".usd", [])

        # The save is NOT called directly — it's deferred to the on_yes
        # callback of the confirm dialog.
        app.save_stage_to.assert_not_called()
        assert len(spawned) == 1
        url, on_yes = spawned[0]
        assert url.endswith("existing.usd")

        # Simulate clicking Yes — the deferred save fires now.
        on_yes()
        app.save_stage_to.assert_called_once_with(url)

    def test_export_handler_saves_directly_when_file_absent(
        self, monkeypatch, tmp_path,
    ):
        """Non-existing target bypasses the confirm dialog entirely."""
        from ovui_widgets.app.menu_bar import _on_save_as_clicked

        calls = self._patch_exporter(monkeypatch)
        spawned: list = []

        class _FakeDialog:
            def __init__(self, url, *, on_yes=None, **kwargs):
                spawned.append(url)

            def show(self):
                pass

        from ovui_widgets.content.widget import confirm_overwrite_dialog
        monkeypatch.setattr(
            confirm_overwrite_dialog,
            "ConfirmOverwriteDialog",
            _FakeDialog,
        )

        app = MagicMock()
        _on_save_as_clicked(app)
        handler = calls[0]["export_handler"]
        handler("brand-new", str(tmp_path), ".usd", [])
        expected = os.path.join(str(tmp_path), "brand-new.usd")
        app.save_stage_to.assert_called_once_with(expected)
        assert spawned == []

    def test_save_as_unavailable_without_export_capability(
        self, monkeypatch,
    ):
        from ovui_widgets.app.menu_bar import _on_save_as_clicked

        calls = self._patch_exporter(monkeypatch)
        app = self._non_exporting_app()

        _on_save_as_clicked(app)

        assert calls == []
        app.save_stage_to.assert_not_called()


class TestOnSaveClicked:
    """Step 55 — File > Save with / without a known current path."""

    def _patch_exporter(self, monkeypatch):
        """Same stub shape as :class:`TestOnSaveAsClicked`."""
        calls: list = []

        class _Stub:
            def show(self, **kwargs):
                calls.append(kwargs)

        stub = _Stub()
        from ovui_widgets.content import file_exporter as fe_mod
        monkeypatch.setattr(
            fe_mod.FileExporterHelper, "instance", classmethod(
                lambda cls: stub,
            ),
        )
        return calls

    def _app_with_export_capability(self, *, current_file_path=None):
        from ovui_data_adapters.common import (
            AdapterCapabilities,
            AdapterCapability,
            StageCapabilities,
        )

        capabilities = AdapterCapabilities(
            stage=StageCapabilities(
                export_stage=AdapterCapability.supported()
            )
        )

        class _Session:
            def get_capabilities(self):
                return capabilities

            def can_export_stage(self):
                raise AssertionError("Save must read explicit capabilities")

        app = SimpleNamespace(
            _stage_adapter=object(),
            get_adapter_session=lambda: _Session(),
            save_stage_to=MagicMock(),
        )
        if current_file_path is not None:
            app._current_file_path = current_file_path
        return app

    def _app_without_export_capability(self, *, current_file_path):
        from ovui_data_adapters.common import (
            AdapterCapabilities,
            AdapterCapability,
            StageCapabilities,
        )

        capabilities = AdapterCapabilities(
            stage=StageCapabilities(
                export_stage=AdapterCapability.unsupported(
                    "test adapter cannot export"
                )
            )
        )

        class _Session:
            def get_capabilities(self):
                return capabilities

            def can_export_stage(self):
                raise AssertionError("Save must read explicit capabilities")

        return SimpleNamespace(
            _stage_adapter=object(),
            _current_file_path=current_file_path,
            get_adapter_session=lambda: _Session(),
            save_stage_to=MagicMock(),
        )

    def test_save_with_current_path_saves_directly(self):
        """A known current file path → save_stage_to, no dialog."""
        from ovui_widgets.app.menu_bar import _on_save_clicked

        app = MagicMock()
        app._current_file_path = "/home/user/Projects/demo.usd"
        _on_save_clicked(app)
        app.save_stage_to.assert_called_once_with(
            "/home/user/Projects/demo.usd",
        )

    def test_save_without_current_path_routes_to_save_as(
        self, monkeypatch,
    ):
        """No current path → Save As dialog (helper.show fires)."""
        from ovui_widgets.app.menu_bar import _on_save_clicked

        calls = self._patch_exporter(monkeypatch)
        app = MagicMock()
        app._current_file_path = None
        _on_save_clicked(app)
        # Save As path reached.
        assert len(calls) == 1
        app.save_stage_to.assert_not_called()

    def test_save_with_missing_attribute_routes_to_save_as(
        self, monkeypatch,
    ):
        """App lacking ``_current_file_path`` attr → Save As (defensive)."""
        from ovui_widgets.app.menu_bar import _on_save_clicked

        calls = self._patch_exporter(monkeypatch)

        # Omit only the current-path attribute. The stage/export capability
        # guard still passes, so Save falls through to Save As.
        app = self._app_with_export_capability()
        _on_save_clicked(app)
        assert len(calls) == 1
        app.save_stage_to.assert_not_called()

    def test_save_with_empty_path_routes_to_save_as(self, monkeypatch):
        """Empty-string path is falsy → Save As."""
        from ovui_widgets.app.menu_bar import _on_save_clicked

        calls = self._patch_exporter(monkeypatch)
        app = MagicMock()
        app._current_file_path = ""
        _on_save_clicked(app)
        assert len(calls) == 1
        app.save_stage_to.assert_not_called()

    def test_save_unavailable_without_export_capability(
        self, monkeypatch,
    ):
        from ovui_widgets.app.menu_bar import _on_save_clicked

        calls = self._patch_exporter(monkeypatch)
        app = self._app_without_export_capability(
            current_file_path="/home/user/Projects/demo.usd"
        )

        _on_save_clicked(app)

        assert calls == []
        app.save_stage_to.assert_not_called()


class TestFileMenuDoesNotSubstituteLayerCopyForStageExport:
    """File Save preserves stage-export semantics when Layers is installed."""

    @staticmethod
    def _app():
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from ovui_data_adapters.common import (
            AdapterCapabilities,
            AdapterCapability,
            LayerStackCapabilities,
            StageCapabilities,
        )

        layer_adapter = SimpleNamespace(
            get_capabilities=lambda: LayerStackCapabilities(
                save_layer=AdapterCapability.supported(),
                save_layer_as=AdapterCapability.supported(),
            )
        )
        capabilities = AdapterCapabilities(
            stage=StageCapabilities(export_stage=AdapterCapability.supported())
        )
        return SimpleNamespace(
            _stage_adapter=object(),
            _layer_adapter=layer_adapter,
            _current_file_path="/tmp/source.usda",
            get_adapter_session=lambda: SimpleNamespace(
                get_capabilities=lambda: capabilities
            ),
            save_stage_to=MagicMock(),
            save_stage=MagicMock(),
            save_stage_as=MagicMock(),
        )

    def test_stage_export_capability_enables_file_save(self):
        from ovui_widgets.app.menu_bar import _can_save_stage

        assert _can_save_stage(self._app()) is True

    def test_file_save_routes_to_composed_stage_export(self):
        from ovui_widgets.app.menu_bar import _on_save_clicked

        app = self._app()
        _on_save_clicked(app)
        app.save_stage_to.assert_called_once_with("/tmp/source.usda")
        app.save_stage.assert_not_called()

    def test_layer_capabilities_alone_do_not_enable_file_stage_export(self):
        from ovui_data_adapters.common import (
            AdapterCapabilities,
            StageCapabilities,
        )

        from ovui_widgets.app.menu_bar import _can_save_stage

        app = self._app()
        app.get_adapter_session = lambda: SimpleNamespace(
            get_capabilities=lambda: AdapterCapabilities(stage=StageCapabilities())
        )

        assert _can_save_stage(app) is False

    def test_file_save_as_uses_stage_export_dialog_not_layer_save_as(
        self, monkeypatch
    ):
        from ovui_widgets.app.menu_bar import _on_save_as_clicked

        calls = []

        class _Stub:
            def show(self, **kwargs):
                calls.append(kwargs)

        from ovui_widgets.content import file_exporter as fe_mod

        monkeypatch.setattr(
            fe_mod.FileExporterHelper,
            "instance",
            classmethod(lambda cls: _Stub()),
        )

        app = self._app()
        _on_save_as_clicked(app)
        assert len(calls) == 1
        app.save_stage_as.assert_not_called()


class TestFileMenuIncludesSaveItems:
    """Step 55 — File menu renders Save and Save As... entries."""

    def _file_menu_probe(self, app):
        """Build the menu bar, then expose the live File-menu builder."""
        import types

        import ovui_widgets.app.menu_bar as mb

        active_menu: list[str] = []
        file_items: list[dict] = []
        file_builders: list = []
        file_menus: list = []

        class _FakeMenu:
            def __init__(self, label, *a, on_build_fn=None, **kw):
                self.label = label
                self.on_build_fn = on_build_fn
                self.shown_changed_fn = None
                self.invalidations = 0
                if label == "File":
                    file_builders.append(on_build_fn)
                    file_menus.append(self)

            def set_shown_changed_fn(self, fn):
                self.shown_changed_fn = fn

            def invalidate(self):
                self.invalidations += 1

            def __enter__(self):
                active_menu.append(self.label)
                return self

            def __exit__(self, *a):
                active_menu.pop()
                return False

        class _FakeMenuItem:
            def __init__(self, label, *a, **kw):
                if active_menu and active_menu[-1] == "File":
                    file_items.append({"label": label, **kw})

        fake_ui = types.SimpleNamespace(
            Menu=_FakeMenu,
            MenuBar=_FakeMenu,
            MenuItem=_FakeMenuItem,
            Separator=lambda *a, **kw: None,
            Spacer=lambda *a, **kw: None,
            VStack=_FakeMenu,
            HStack=_FakeMenu,
            ImageWithProvider=lambda *a, **kw: None,
            Label=lambda *a, **kw: None,
            Rectangle=lambda *a, **kw: None,
        )
        original = mb.ui
        original_logo = mb._get_logo_provider
        original_identity = mb._build_product_identity
        try:
            mb.ui = fake_ui
            mb._get_logo_provider = lambda: object()
            mb._build_product_identity = lambda: None
            mb.build_menu_bar(app)
        finally:
            mb.ui = original
            mb._get_logo_provider = original_logo
            mb._build_product_identity = original_identity
        assert len(file_builders) == 1
        assert callable(file_builders[0])
        assert len(file_menus) == 1

        def open_file_menu():
            file_items.clear()
            active_menu.append("File")
            original_ui_for_open = mb.ui
            try:
                mb.ui = fake_ui
                file_builders[0]()
            finally:
                mb.ui = original_ui_for_open
                active_menu.pop()
            return list(file_items)

        open_file_menu.file_menu = file_menus[0]

        return open_file_menu

    def _app_with_stage_export_capability(
        self,
        *,
        stage_loaded: bool,
        export_supported: bool,
    ):
        from ovui_data_adapters.common import (
            AdapterCapabilities,
            AdapterCapability,
            StageCapabilities,
        )

        export_capability = (
            AdapterCapability.supported()
            if export_supported
            else AdapterCapability.unsupported("test adapter cannot export")
        )
        capabilities = AdapterCapabilities(
            stage=StageCapabilities(export_stage=export_capability)
        )

        class _Session:
            def get_capabilities(self):
                return capabilities

            def can_export_stage(self):
                raise AssertionError("File menu must read explicit capabilities")

        return SimpleNamespace(
            _stage_adapter=(object() if stage_loaded else None),
            _stage_window=MagicMock(visible=True),
            _property_window=MagicMock(visible=True),
            _viewport_window=MagicMock(visible=True),
            _content_window=MagicMock(visible=True),
            _layer_window=MagicMock(visible=True),
            undo_manager=MagicMock(),
            get_adapter_session=lambda: _Session(),
        )

    def _app_with_session(self, *, stage_loaded: bool, session):
        return SimpleNamespace(
            _stage_adapter=(object() if stage_loaded else None),
            _stage_window=MagicMock(visible=True),
            _property_window=MagicMock(visible=True),
            _viewport_window=MagicMock(visible=True),
            _content_window=MagicMock(visible=True),
            _layer_window=MagicMock(visible=True),
            undo_manager=MagicMock(),
            get_adapter_session=lambda: session,
        )

    def _app_with_public_session(self, *, stage_loaded: bool, session):
        stage_adapter = object() if stage_loaded else None
        return SimpleNamespace(
            stage_adapter=stage_adapter,
            get_stage_adapter=lambda: stage_adapter,
            _stage_window=MagicMock(visible=True),
            _property_window=MagicMock(visible=True),
            _viewport_window=MagicMock(visible=True),
            _content_window=MagicMock(visible=True),
            _layer_window=MagicMock(visible=True),
            undo_manager=MagicMock(),
            get_adapter_session=lambda: session,
        )

    def _item(self, items, label):
        for item in items:
            if item["label"] == label:
                return item
        raise AssertionError(f"missing File menu item {label!r}")

    def test_save_item_exists(self):
        app = self._app_with_stage_export_capability(
            stage_loaded=True,
            export_supported=True,
        )
        labels = [item["label"] for item in self._file_menu_probe(app)()]
        assert "Save" in labels

    def test_save_as_item_exists(self):
        app = self._app_with_stage_export_capability(
            stage_loaded=True,
            export_supported=True,
        )
        labels = [item["label"] for item in self._file_menu_probe(app)()]
        assert "Save As..." in labels

    def test_save_precedes_save_as(self):
        """Save must appear before Save As..."""
        app = self._app_with_stage_export_capability(
            stage_loaded=True,
            export_supported=True,
        )
        labels = [item["label"] for item in self._file_menu_probe(app)()]
        save_idx = labels.index("Save")
        save_as_idx = labels.index("Save As...")
        assert save_idx < save_as_idx

    def test_file_menu_invalidates_when_visibility_changes(self):
        app = self._app_with_stage_export_capability(
            stage_loaded=True,
            export_supported=True,
        )
        open_file_menu = self._file_menu_probe(app)
        file_menu = open_file_menu.file_menu

        assert callable(file_menu.shown_changed_fn)
        file_menu.shown_changed_fn(True)
        file_menu.shown_changed_fn(False)

        assert file_menu.invalidations == 2

    def test_save_items_enabled_with_loaded_export_capable_stage(self):
        app = self._app_with_stage_export_capability(
            stage_loaded=True,
            export_supported=True,
        )

        items = self._file_menu_probe(app)()

        assert self._item(items, "Save")["enabled"] is True
        assert self._item(items, "Save As...")["enabled"] is True

    def test_save_items_enabled_with_loaded_openusd_session(self):
        from ovui_data_adapters.openusd.provider import OpenUSDProviderSession

        app = self._app_with_session(
            stage_loaded=True,
            session=OpenUSDProviderSession(),
        )

        items = self._file_menu_probe(app)()

        assert self._item(items, "Save")["enabled"] is True
        assert self._item(items, "Save As...")["enabled"] is True

    def test_save_items_enabled_with_public_backend_stage_accessor(self):
        from ovui_data_adapters.openusd.provider import OpenUSDProviderSession

        app = self._app_with_public_session(
            stage_loaded=True,
            session=OpenUSDProviderSession(),
        )

        assert not hasattr(app, "_stage_adapter")
        items = self._file_menu_probe(app)()

        assert self._item(items, "Save")["enabled"] is True
        assert self._item(items, "Save As...")["enabled"] is True

    def test_save_items_disabled_without_loaded_stage(self):
        app = self._app_with_stage_export_capability(
            stage_loaded=False,
            export_supported=True,
        )

        items = self._file_menu_probe(app)()

        assert self._item(items, "Save")["enabled"] is False
        assert self._item(items, "Save As...")["enabled"] is False

    def test_save_items_disabled_without_loaded_stage_for_openusd_session(self):
        from ovui_data_adapters.openusd.provider import OpenUSDProviderSession

        app = self._app_with_session(
            stage_loaded=False,
            session=OpenUSDProviderSession(),
        )

        items = self._file_menu_probe(app)()

        assert self._item(items, "Save")["enabled"] is False
        assert self._item(items, "Save As...")["enabled"] is False

    def test_save_items_disabled_with_loaded_non_exporting_adapter(self):
        app = self._app_with_stage_export_capability(
            stage_loaded=True,
            export_supported=False,
        )

        items = self._file_menu_probe(app)()

        assert self._item(items, "Save")["enabled"] is False
        assert self._item(items, "Save As...")["enabled"] is False

    def test_save_items_disabled_with_loaded_native_ovstage_session(self):
        from ovui_data_adapters.ovstage.provider import OvstageProviderSession

        # The native OVStage session cannot export durably (no OpenUSD
        # bridge), so the save items must stay disabled instead of offering
        # an action the provider would refuse.
        app = self._app_with_session(
            stage_loaded=True,
            session=OvstageProviderSession(runtime=object()),
        )

        items = self._file_menu_probe(app)()

        assert self._item(items, "Save")["enabled"] is False
        assert self._item(items, "Save As...")["enabled"] is False

    def test_save_items_are_recomputed_when_file_menu_reopens(self):
        app = self._app_with_stage_export_capability(
            stage_loaded=False,
            export_supported=True,
        )
        open_file_menu = self._file_menu_probe(app)

        first_items = open_file_menu()
        app._stage_adapter = object()
        second_items = open_file_menu()

        assert self._item(first_items, "Save")["enabled"] is False
        assert self._item(first_items, "Save As...")["enabled"] is False
        assert self._item(second_items, "Save")["enabled"] is True
        assert self._item(second_items, "Save As...")["enabled"] is True


class TestFileMenuContributions:
    """File-rooted contributions mount under the built-in File menu."""

    def _menu_probe(self):
        import types

        import ovui_widgets.app.menu_bar as mb

        active_menu: list[str] = []
        menu_builders: dict[tuple[str, ...], object] = {}
        menu_items: list[dict] = []
        top_level_labels: list[str] = []

        class _FakeMenu:
            def __init__(self, label, *a, on_build_fn=None, **kw):
                self.label = label
                self.on_build_fn = on_build_fn
                self.shown_changed_fn = None
                self.invalidations = 0
                self.path = tuple([*active_menu, label])
                if not active_menu:
                    top_level_labels.append(label)
                if on_build_fn is not None:
                    menu_builders[self.path] = on_build_fn

            def set_shown_changed_fn(self, fn):
                self.shown_changed_fn = fn

            def invalidate(self):
                self.invalidations += 1

            def __enter__(self):
                active_menu.append(self.label)
                return self

            def __exit__(self, *a):
                active_menu.pop()
                return False

        class _FakeMenuItem:
            def __init__(self, label, *a, **kw):
                menu_items.append({"path": tuple(active_menu), "label": label, **kw})

        fake_ui = types.SimpleNamespace(
            Menu=_FakeMenu,
            MenuBar=_FakeMenu,
            MenuItem=_FakeMenuItem,
            Separator=lambda *a, **kw: None,
            Spacer=lambda *a, **kw: None,
            VStack=_FakeMenu,
            HStack=_FakeMenu,
            ImageWithProvider=lambda *a, **kw: None,
            Label=lambda *a, **kw: None,
            Rectangle=lambda *a, **kw: None,
        )
        original = mb.ui
        original_logo = mb._get_logo_provider
        original_identity = mb._build_product_identity
        try:
            mb.ui = fake_ui
            mb._get_logo_provider = lambda: object()
            mb._build_product_identity = lambda: None
            mb.build_menu_bar(MagicMock())
        finally:
            mb.ui = original
            mb._get_logo_provider = original_logo
            mb._build_product_identity = original_identity

        def open_menu(path: tuple[str, ...]) -> None:
            builder = menu_builders[path]
            active_menu[:] = list(path)
            original_ui_for_open = mb.ui
            try:
                mb.ui = fake_ui
                builder()
            finally:
                mb.ui = original_ui_for_open
                active_menu.clear()

        return SimpleNamespace(
            menu_builders=menu_builders,
            menu_items=menu_items,
            open_menu=open_menu,
            top_level_labels=top_level_labels,
        )

    def test_file_import_contribution_builds_inside_existing_file_menu(self):
        from ovui_widgets.app.menu_bar import MenuContribution, register_menu_item

        handle = register_menu_item(
            MenuContribution(
                menu_path=("File", "Import"),
                stable_id="test.file.import.urdf",
                label="URDF...",
                order=20,
            )
        )
        try:
            probe = self._menu_probe()

            assert probe.top_level_labels.count("File") == 1
            probe.open_menu(("File",))
            assert ("File", "Import") in probe.menu_builders

            probe.open_menu(("File", "Import"))

            matching = [
                item
                for item in probe.menu_items
                if item["path"] == ("File", "Import")
                and item["label"] == "URDF..."
            ]
            assert len(matching) == 1
            assert matching[0]["enabled"] is True
            assert callable(matching[0]["triggered_fn"])
        finally:
            handle.cancel()

    def test_file_contribution_does_not_create_duplicate_top_level_menu(self):
        from ovui_widgets.app.menu_bar import MenuContribution, register_menu_item

        file_handle = register_menu_item(
            MenuContribution(
                menu_path=("File", "Import"),
                stable_id="test.file.import.no_duplicate",
                label="URDF...",
            )
        )
        physics_handle = register_menu_item(
            MenuContribution(
                menu_path=("Physics", "Simulation"),
                stable_id="test.physics.top_level.still_renders",
                label="Enable PhysX",
            )
        )
        try:
            probe = self._menu_probe()

            assert probe.top_level_labels.count("File") == 1
            assert "Physics" in probe.top_level_labels
        finally:
            file_handle.cancel()
            physics_handle.cancel()


class TestStatusBarCallLater:
    """Tests for the call_later_fn wiring added to StatusBar in Step 9."""

    def _make_bar_with_call_later(self):
        """Create a StatusBar with a mock call_later_fn."""
        import omni.ui as ui

        from ovui_widgets.app.status_bar import StatusBar
        scheduled = []

        def fake_call_later(delay_secs, callback):
            handle = MagicMock()
            handle.cancel = MagicMock()
            scheduled.append((delay_secs, callback, handle))
            return handle

        frame = ui.Frame()
        bar = StatusBar(frame, call_later_fn=fake_call_later)
        return bar, scheduled

    def test_show_message_schedules_clear(self):
        bar, scheduled = self._make_bar_with_call_later()
        bar.show_message("hello", duration_ms=2000)
        assert len(scheduled) == 1
        delay, callback, _ = scheduled[0]
        assert abs(delay - 2.0) < 1e-9

    def test_show_message_clear_callback_clears_label(self):
        bar, scheduled = self._make_bar_with_call_later()
        bar.show_message("hello", duration_ms=1000)
        _, clear_fn, _ = scheduled[0]
        clear_fn()  # fire the scheduled clear
        assert bar._label.text == ""

    def test_second_show_message_cancels_first_task(self):
        bar, scheduled = self._make_bar_with_call_later()
        bar.show_message("first", duration_ms=5000)
        _, _, handle1 = scheduled[0]
        bar.show_message("second", duration_ms=5000)
        handle1.cancel.assert_called_once()

    def test_no_call_later_fn_doesnt_raise(self):
        import omni.ui as ui

        from ovui_widgets.app.status_bar import StatusBar
        frame = ui.Frame()
        bar = StatusBar(frame, call_later_fn=None)
        bar.show_message("msg", duration_ms=1000)  # must not raise

    def test_clear_resets_clear_task(self):
        bar, scheduled = self._make_bar_with_call_later()
        bar.show_message("hello", duration_ms=1000)
        assert bar._clear_task is not None
        bar.clear()
        assert bar._clear_task is None

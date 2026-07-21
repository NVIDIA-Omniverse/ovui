# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`FileContextMenu` (the content browser implementation step 31).

Coverage:

* Public surface — package re-export, ``__all__`` inclusion, module
  symbols.
* Target classification — ``None`` → EMPTY, folder item → FOLDER,
  file item → FILE.
* Built-in spec composition — file / folder / empty specs contain
  the exact menu labels the content browser implementation step 31 prescribes.
* Plug-in :meth:`register_item` — appends to every context by
  default, ``show_fn`` predicate filters the entry on/off per show
  call, duplicates are allowed.
* :meth:`show` driver — builds a :class:`ui.Menu` at the requested
  coordinates; idempotent post-destroy (returns ``None``).
* :meth:`destroy` — idempotent, clears plug-ins, drops widget ref.

Pure-helper tests run without an ovui build context (the spec-level
composition is a function of the :class:`FileItem` alone). The
:meth:`show` tests use the same module-scoped ``ephemeral_window``
fixture the rest of the content-browser suite uses so the
:class:`ui.Menu` build happens inside a live ovui root.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List, Optional, Tuple

import omni.ui as ui
import pytest

from ovui_widgets.content.widget import FileContextMenu, FileItem
from ovui_widgets.content.widget.context_menu import (
    TARGET_EMPTY,
    TARGET_FILE,
    TARGET_FOLDER,
    _MenuItemSpec,
)
from ovui_widgets.content.widget.context_menu import (
    FileContextMenu as _FileContextMenu,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


class _FakeWidget:
    """Stand-in for :class:`FileBrowserWidget` that records drill + refresh.

    The context menu's Open (folder) path calls
    ``widget._drill_into_folder(item)``; the empty-space Refresh path
    calls ``widget._detail_model.refresh_all()``. A lightweight fake
    keeps the tests headless and lets us assert which action fired.
    """

    class _FakeModel:
        def __init__(self) -> None:
            self.refresh_all_count = 0

        def refresh_all(self) -> None:
            self.refresh_all_count += 1

    def __init__(self) -> None:
        self._detail_model = _FakeWidget._FakeModel()
        self.drill_calls: List[FileItem] = []

    def _drill_into_folder(self, folder: FileItem) -> None:
        self.drill_calls.append(folder)


@pytest.fixture
def fake_widget() -> _FakeWidget:
    return _FakeWidget()


@pytest.fixture
def menu(fake_widget: _FakeWidget) -> FileContextMenu:
    m = FileContextMenu(fake_widget)
    yield m
    m.destroy()


def _file_item(
    url: str = "mock://a.usd", name: str = "a.usd", is_folder: bool = False,
) -> FileItem:
    return FileItem(url=url, name=name, is_folder=is_folder)


def _folder_item(
    url: str = "mock://folder", name: str = "folder",
) -> FileItem:
    return FileItem(url=url, name=name, is_folder=True)


@pytest.fixture(scope="module")
def ephemeral_window():
    """Single ovui Window reused across every :meth:`show` test."""
    win = ui.Window("_test_context_menu", width=200, height=200)
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


# ──────────────────────────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────────────────────────


class TestSurface:
    def test_reexported_from_widget_package(self):
        assert FileContextMenu is _FileContextMenu

    def test_widget_package_all_contains_file_context_menu(self):
        import ovui_widgets.content.widget as pkg

        assert "FileContextMenu" in pkg.__all__

    def test_target_constants_are_strings(self):
        assert TARGET_FILE == "file"
        assert TARGET_FOLDER == "folder"
        assert TARGET_EMPTY == "empty"

    def test_menu_item_spec_has_expected_fields(self):
        spec = _MenuItemSpec(
            name="X", icon=None, click_fn=lambda it: None, show_fn=None,
        )
        assert spec.name == "X"
        assert spec.icon is None
        assert callable(spec.click_fn)
        assert spec.show_fn is None


# ──────────────────────────────────────────────────────────────────────────────
# Target classification
# ──────────────────────────────────────────────────────────────────────────────


class TestTargetFor:
    def test_none_is_empty(self):
        assert FileContextMenu._target_for(None) == TARGET_EMPTY

    def test_folder_item_is_folder(self):
        assert (
            FileContextMenu._target_for(_folder_item()) == TARGET_FOLDER
        )

    def test_file_item_is_file(self):
        assert FileContextMenu._target_for(_file_item()) == TARGET_FILE


# ──────────────────────────────────────────────────────────────────────────────
# Built-in spec composition
# ──────────────────────────────────────────────────────────────────────────────


class TestBuiltinSpecs:
    """The entry labels prescribed by the content browser implementation step 31."""

    def test_file_menu_labels(self, menu):
        # Step 37 adds ``Duplicate`` next to the Copy family entries.
        names = [s.name for s in menu._file_specs()]
        assert names == [
            "Open", "Copy URL", "Cut", "Copy", "Duplicate",
            "Rename", "Delete",
        ]

    def test_folder_menu_labels(self, menu):
        # Step 37 adds ``Open in Native File Browser`` (predicate-gated),
        # ``Copy URL``, and ``Duplicate``. ``_folder_specs()`` returns the
        # raw list before the ``show_fn`` filter runs — the native-
        # browser entry is always present here; ``_specs_for`` applies
        # the predicate.
        names = [s.name for s in menu._folder_specs()]
        assert names == [
            "Open", "Open in Native File Browser", "Copy URL",
            "Create Folder", "Cut", "Copy", "Paste", "Duplicate",
            "Add Bookmark", "Rename", "Delete",
        ]

    def test_empty_menu_labels(self, menu):
        names = [s.name for s in menu._empty_specs()]
        assert names == ["Create Folder", "Paste", "Refresh"]


class TestSpecsFor:
    """``_specs_for`` composes built-ins + filtered plug-ins per target."""

    def test_file_target_uses_file_specs(self, menu):
        item = _file_item()
        names = [s.name for s in menu._specs_for(TARGET_FILE, item)]
        # Step 37 inserts ``Duplicate`` between ``Copy`` and ``Rename``.
        assert names[:7] == [
            "Open", "Copy URL", "Cut", "Copy", "Duplicate",
            "Rename", "Delete",
        ]

    def test_folder_target_uses_folder_specs(self, menu):
        item = _folder_item()
        names = [s.name for s in menu._specs_for(TARGET_FOLDER, item)]
        assert "Add Bookmark" in names
        assert "Paste" in names

    def test_empty_target_uses_empty_specs(self, menu):
        names = [s.name for s in menu._specs_for(TARGET_EMPTY, None)]
        assert names == ["Create Folder", "Paste", "Refresh"]


# ──────────────────────────────────────────────────────────────────────────────
# Plug-in registration
# ──────────────────────────────────────────────────────────────────────────────


class TestRegisterItem:
    def test_registered_item_appears_on_file_menu(self, menu):
        menu.register_item(
            "My Action", None, lambda item: None,
        )
        item = _file_item()
        names = [s.name for s in menu._specs_for(TARGET_FILE, item)]
        assert "My Action" in names

    def test_registered_item_appears_on_folder_menu(self, menu):
        menu.register_item("My Action", None, lambda item: None)
        names = [
            s.name for s in menu._specs_for(TARGET_FOLDER, _folder_item())
        ]
        assert "My Action" in names

    def test_registered_item_appears_on_empty_menu(self, menu):
        menu.register_item("My Action", None, lambda item: None)
        names = [s.name for s in menu._specs_for(TARGET_EMPTY, None)]
        assert "My Action" in names

    def test_registered_item_appends_after_builtins(self, menu):
        menu.register_item("My Action", None, lambda item: None)
        specs = menu._specs_for(TARGET_FILE, _file_item())
        assert specs[-1].name == "My Action"

    def test_show_fn_false_hides_entry(self, menu):
        menu.register_item(
            "Hidden", None,
            lambda item: None,
            show_fn=lambda item: False,
        )
        specs = menu._specs_for(TARGET_FILE, _file_item())
        assert "Hidden" not in [s.name for s in specs]

    def test_show_fn_true_keeps_entry(self, menu):
        menu.register_item(
            "Shown", None,
            lambda item: None,
            show_fn=lambda item: True,
        )
        specs = menu._specs_for(TARGET_FILE, _file_item())
        assert "Shown" in [s.name for s in specs]

    def test_show_fn_receives_item(self, menu):
        received: List[Optional[FileItem]] = []

        def predicate(item: Optional[FileItem]) -> bool:
            received.append(item)
            return True

        menu.register_item(
            "Inspected", None, lambda item: None, show_fn=predicate,
        )
        target = _file_item()
        menu._specs_for(TARGET_FILE, target)
        assert received == [target]

    def test_show_fn_receives_none_on_empty(self, menu):
        received: List[Optional[FileItem]] = []

        def predicate(item: Optional[FileItem]) -> bool:
            received.append(item)
            return True

        menu.register_item(
            "EmptyCheck", None, lambda item: None, show_fn=predicate,
        )
        menu._specs_for(TARGET_EMPTY, None)
        assert received == [None]

    def test_duplicate_name_allowed(self, menu):
        menu.register_item("Dup", None, lambda item: None)
        menu.register_item("Dup", None, lambda item: None)
        names = [
            s.name for s in menu._specs_for(TARGET_FILE, _file_item())
        ]
        assert names.count("Dup") == 2

    def test_registration_order_preserved(self, menu):
        menu.register_item("First", None, lambda item: None)
        menu.register_item("Second", None, lambda item: None)
        menu.register_item("Third", None, lambda item: None)
        names = [
            s.name for s in menu._specs_for(TARGET_FILE, _file_item())
        ]
        # Every plug-in item lands after the built-ins, in registration
        # order.
        plugin_tail = names[-3:]
        assert plugin_tail == ["First", "Second", "Third"]


# ──────────────────────────────────────────────────────────────────────────────
# Stub actions (click handlers)
# ──────────────────────────────────────────────────────────────────────────────


class TestStubActions:
    def test_open_folder_drills_into_widget(self, fake_widget):
        menu = FileContextMenu(fake_widget)
        folder = _folder_item("mock://folder", "folder")
        # Find the Open spec from folder specs and invoke it.
        open_spec = next(
            s for s in menu._folder_specs() if s.name == "Open"
        )
        open_spec.click_fn(folder)
        assert fake_widget.drill_calls == [folder]
        menu.destroy()

    def test_open_file_is_stub_only(self, fake_widget):
        menu = FileContextMenu(fake_widget)
        f = _file_item()
        open_spec = next(
            s for s in menu._file_specs() if s.name == "Open"
        )
        # File Open is a stub — no widget action recorded.
        open_spec.click_fn(f)
        assert fake_widget.drill_calls == []
        menu.destroy()

    def test_refresh_calls_detail_model(self, fake_widget):
        menu = FileContextMenu(fake_widget)
        refresh_spec = next(
            s for s in menu._empty_specs() if s.name == "Refresh"
        )
        refresh_spec.click_fn(None)
        assert fake_widget._detail_model.refresh_all_count == 1
        menu.destroy()

    def test_stub_action_does_not_raise_without_widget(self, fake_widget):
        """A stub click from a torn-down menu logs and returns silently."""
        menu = FileContextMenu(fake_widget)
        menu.destroy()
        # The click_fn closures still hold references to the menu /
        # widget even after destroy — but the stubs are staticmethods
        # and do not dereference anything on the widget, so they
        # simply log-and-return.
        FileContextMenu._stub("Copy", _file_item())
        # No assertion — the absence of a raise is the assertion.


# ──────────────────────────────────────────────────────────────────────────────
# :meth:`show` integration — live ovui menu build
# ──────────────────────────────────────────────────────────────────────────────


class TestShow:
    """End-to-end :meth:`show` tests.

    :meth:`ui.Menu.show_at` segfaults the standalone ovui test harness
    (no window compositor to anchor the popup against) — same rationale
    as ``test_filter_button.py`` and ``test_attr_context_menu.py`` skipping
    their live ``show_at`` coverage. We stub the show_at call here so the
    menu-build path (menu creation, item enumeration) is still covered
    while the popup positioning is skipped.
    """

    def test_show_returns_menu_for_file(
        self, fake_widget, ephemeral_window, monkeypatch,
    ):
        monkeypatch.setattr(
            ui.Menu, "show_at",
            lambda self, *a, **kw: None,
        )
        menu = FileContextMenu(fake_widget)
        with in_window_frame(ephemeral_window):
            result = menu.show(10.0, 20.0, _file_item())
        assert result is not None
        assert isinstance(result, ui.Menu)
        menu.destroy()

    def test_show_returns_menu_for_folder(
        self, fake_widget, ephemeral_window, monkeypatch,
    ):
        monkeypatch.setattr(
            ui.Menu, "show_at", lambda self, *a, **kw: None,
        )
        menu = FileContextMenu(fake_widget)
        with in_window_frame(ephemeral_window):
            result = menu.show(10.0, 20.0, _folder_item())
        assert result is not None
        menu.destroy()

    def test_show_returns_menu_for_empty(
        self, fake_widget, ephemeral_window, monkeypatch,
    ):
        monkeypatch.setattr(
            ui.Menu, "show_at", lambda self, *a, **kw: None,
        )
        menu = FileContextMenu(fake_widget)
        with in_window_frame(ephemeral_window):
            result = menu.show(10.0, 20.0, None)
        assert result is not None
        menu.destroy()

    def test_show_after_destroy_returns_none(self, fake_widget):
        menu = FileContextMenu(fake_widget)
        menu.destroy()
        # No in_window_frame — show short-circuits before any ovui call.
        assert menu.show(0.0, 0.0, None) is None

    def test_show_replaces_menu_attribute(
        self, fake_widget, ephemeral_window, monkeypatch,
    ):
        monkeypatch.setattr(
            ui.Menu, "show_at", lambda self, *a, **kw: None,
        )
        menu = FileContextMenu(fake_widget)
        with in_window_frame(ephemeral_window):
            m1 = menu.show(10.0, 20.0, _file_item())
            m2 = menu.show(30.0, 40.0, _folder_item())
        assert menu._menu is m2
        assert m1 is not m2
        menu.destroy()

    def test_show_forwards_coordinates(
        self, fake_widget, ephemeral_window, monkeypatch,
    ):
        """The (x, y) args land on :meth:`ui.Menu.show_at` verbatim."""
        captured: List[Tuple[float, float]] = []

        def _fake_show_at(self, x, y, *a, **kw):
            captured.append((float(x), float(y)))

        monkeypatch.setattr(ui.Menu, "show_at", _fake_show_at)
        menu = FileContextMenu(fake_widget)
        with in_window_frame(ephemeral_window):
            menu.show(123.0, 456.0, _file_item())
        assert captured == [(123.0, 456.0)]
        menu.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# :meth:`destroy` semantics
# ──────────────────────────────────────────────────────────────────────────────


class TestDestroy:
    def test_destroy_idempotent(self, fake_widget):
        menu = FileContextMenu(fake_widget)
        menu.destroy()
        menu.destroy()  # No raise.

    def test_destroy_clears_plugins(self, fake_widget):
        menu = FileContextMenu(fake_widget)
        menu.register_item("X", None, lambda it: None)
        assert len(menu._plugin_items) == 1
        menu.destroy()
        assert menu._plugin_items == []

    def test_destroy_drops_widget_ref(self, fake_widget):
        menu = FileContextMenu(fake_widget)
        menu.destroy()
        assert menu._widget is None

    def test_destroy_does_not_crash_with_live_menu(
        self, fake_widget, ephemeral_window, monkeypatch,
    ):
        monkeypatch.setattr(
            ui.Menu, "show_at", lambda self, *a, **kw: None,
        )
        menu = FileContextMenu(fake_widget)
        with in_window_frame(ephemeral_window):
            menu.show(10.0, 20.0, _file_item())
        menu.destroy()  # No raise even with a live menu attached.


# ──────────────────────────────────────────────────────────────────────────────
# Widget integration — delegate & grid right-click wiring
# ──────────────────────────────────────────────────────────────────────────────


class TestWidgetIntegration:
    """The widget wires the context menu into both panes + empty space."""

    def test_widget_builds_context_menu(self):
        from ovui_widgets.app.testing.mock_backend import MockBackend
        from ovui_widgets.content.widget import FileBrowserWidget

        backend = MockBackend()
        win = ui.Window("_test_ctx_integration", width=400, height=300)
        try:
            with win.frame:
                widget = FileBrowserWidget(backend, "mock://Home")
            assert widget._context_menu is not None
            assert isinstance(widget._context_menu, FileContextMenu)
            widget.destroy()
        finally:
            win.destroy()

    def test_widget_destroy_tears_down_context_menu(self):
        from ovui_widgets.app.testing.mock_backend import MockBackend
        from ovui_widgets.content.widget import FileBrowserWidget

        backend = MockBackend()
        win = ui.Window("_test_ctx_destroy", width=400, height=300)
        try:
            with win.frame:
                widget = FileBrowserWidget(backend, "mock://Home")
            widget.destroy()
            assert widget._context_menu is None
        finally:
            win.destroy()

    def test_on_row_right_click_routes_through_menu(self):
        from ovui_widgets.app.testing.mock_backend import MockBackend
        from ovui_widgets.content.widget import FileBrowserWidget

        backend = MockBackend()
        win = ui.Window("_test_ctx_row_right", width=400, height=300)
        try:
            with win.frame:
                widget = FileBrowserWidget(backend, "mock://Home")
            item = _folder_item()
            # Replace the menu with a recording double so we assert on
            # the coordinates forwarded without also exercising the live
            # ui.Menu build.
            calls: List[Tuple[float, float, Optional[FileItem]]] = []

            class _RecordingMenu:
                def show(
                    self,
                    x: float,
                    y: float,
                    it: Optional[FileItem],
                ) -> None:
                    calls.append((x, y, it))

                def destroy(self) -> None:
                    pass

            widget._context_menu = _RecordingMenu()  # type: ignore[assignment]
            widget._on_row_right_click(123.0, 456.0, item)
            assert calls == [(123.0, 456.0, item)]
            widget.destroy()
        finally:
            win.destroy()

    def test_on_grid_right_click_routes_through_menu(self):
        from ovui_widgets.app.testing.mock_backend import MockBackend
        from ovui_widgets.content.widget import FileBrowserWidget

        backend = MockBackend()
        win = ui.Window("_test_ctx_grid_right", width=400, height=300)
        try:
            with win.frame:
                widget = FileBrowserWidget(backend, "mock://Home")
            item = _file_item()
            calls: List[Tuple[float, float, Optional[FileItem]]] = []

            class _RecordingMenu:
                def show(
                    self,
                    x: float,
                    y: float,
                    it: Optional[FileItem],
                ) -> None:
                    calls.append((x, y, it))

                def destroy(self) -> None:
                    pass

            widget._context_menu = _RecordingMenu()  # type: ignore[assignment]
            widget._on_grid_right_click(item, 99.0, 88.0)
            assert calls == [(99.0, 88.0, item)]
            widget.destroy()
        finally:
            win.destroy()

    def test_on_grid_empty_right_click_passes_none(self):
        from ovui_widgets.app.testing.mock_backend import MockBackend
        from ovui_widgets.content.widget import FileBrowserWidget

        backend = MockBackend()
        win = ui.Window("_test_ctx_empty", width=400, height=300)
        try:
            with win.frame:
                widget = FileBrowserWidget(backend, "mock://Home")
            calls: List[Tuple[float, float, Optional[FileItem]]] = []

            class _RecordingMenu:
                def show(
                    self,
                    x: float,
                    y: float,
                    it: Optional[FileItem],
                ) -> None:
                    calls.append((x, y, it))

                def destroy(self) -> None:
                    pass

            widget._context_menu = _RecordingMenu()  # type: ignore[assignment]
            widget._on_grid_empty_right_click(10.0, 20.0)
            assert calls == [(10.0, 20.0, None)]
            widget.destroy()
        finally:
            win.destroy()

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`ContentBrowserWindow` — the content browser implementation step 10.

The window is the dockable :class:`ManagedWindow` shell that hosts the
embeddable :class:`FileBrowserWidget`. It owns docking / title / module
styles / lifecycle; the widget owns tree model, delegate, navigation,
and backend swap. These tests verify the public surface — auto-wrap,
late-binding of the widget until :meth:`_build_ui` fires, style
plumbing, navigate-to delegation, and destroy teardown — without
standing up a full :class:`Application`.
"""

from __future__ import annotations

import os

import omni.ui as ui
import pytest

from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.common.managed_window import ManagedWindow
from ovwidgets.content import ContentBrowserWindow
from ovwidgets.content.backends.backend_adapter import BackendAdapter
from ovwidgets.content.backends.local_fs_backend import LocalFSBackend
from ovwidgets.content.style import CONTENT_STYLES
from ovwidgets.content.widget.file_browser_widget import FileBrowserWidget

# ──────────────────────────────────────────────────────────────────────────────
# Window-capability probe (mirrors test_stage_window.py)
# ──────────────────────────────────────────────────────────────────────────────


def _can_create_window() -> bool:
    try:
        w = ui.Window("__probe__", width=10, height=10)
        w.destroy()
        return True
    except Exception:
        return False


_WINDOW_AVAILABLE = _can_create_window()
_skip_no_window = pytest.mark.skipif(
    not _WINDOW_AVAILABLE, reason="ui.Window creation not available without ui.init()"
)


# ──────────────────────────────────────────────────────────────────────────────
# Surface
# ──────────────────────────────────────────────────────────────────────────────


class TestSurface:
    def test_import_from_window_subpackage(self):
        from ovwidgets.content.window import ContentBrowserWindow as CW

        assert CW is ContentBrowserWindow

    def test_import_from_package(self):
        from ovwidgets.content import ContentBrowserWindow as CW

        assert CW is ContentBrowserWindow

    def test_package_all_contains_window(self):
        import ovwidgets.content as pkg

        assert "ContentBrowserWindow" in pkg.__all__

    def test_window_subpackage_all_contains_window(self):
        import ovwidgets.content.window as pkg

        assert "ContentBrowserWindow" in pkg.__all__

    def test_is_managed_window_subclass(self):
        assert issubclass(ContentBrowserWindow, ManagedWindow)

    def test_is_not_a_file_browser_widget(self):
        assert not issubclass(ContentBrowserWindow, FileBrowserWidget)


# ──────────────────────────────────────────────────────────────────────────────
# Construction — lifecycle properties
# ──────────────────────────────────────────────────────────────────────────────


@_skip_no_window
class TestConstruction:
    def test_constructible_with_mock_backend(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        assert isinstance(w, ContentBrowserWindow)
        w.destroy()

    def test_constructible_with_default_backend(self):
        w = ContentBrowserWindow()
        assert isinstance(w._backend, LocalFSBackend)
        w.destroy()

    def test_default_backend_is_local_fs(self):
        w = ContentBrowserWindow()
        assert isinstance(w._backend, BackendAdapter)
        assert isinstance(w._backend, LocalFSBackend)
        w.destroy()

    def test_title_is_content(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        assert w.title == "Content"
        w.destroy()

    def test_window_is_created(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        assert w.window is not None
        w.destroy()

    def test_widget_not_built_before_frame(self):
        # _build_ui is registered with frame.set_build_fn; it does not
        # fire until the first rendered frame. The widget must therefore
        # be None immediately after construction.
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        assert w._widget is None
        w.destroy()

    def test_build_ui_creates_file_browser_widget(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        with w._window.frame:
            w._build_ui()
        assert isinstance(w._widget, FileBrowserWidget)
        w.destroy()

    def test_build_ui_forwards_backend_to_widget(self):
        backend = MockBackend()
        w = ContentBrowserWindow(backend=backend, start_url="mock://Home")
        with w._window.frame:
            w._build_ui()
        assert w._widget._backend is backend
        w.destroy()

    def test_build_ui_forwards_start_url_to_widget_model(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home/Projects")
        with w._window.frame:
            w._build_ui()
        assert w._widget.get_model().root_url == "mock://Home/Projects"
        w.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Auto-wrap — None / BackendAdapter / str
# ──────────────────────────────────────────────────────────────────────────────


@_skip_no_window
class TestBackendAutoWrap:
    def test_none_backend_becomes_local_fs(self):
        w = ContentBrowserWindow()
        assert isinstance(w._backend, LocalFSBackend)
        w.destroy()

    def test_backend_adapter_instance_used_verbatim(self):
        backend = MockBackend()
        w = ContentBrowserWindow(backend=backend, start_url="mock://Home")
        assert w._backend is backend
        w.destroy()

    def test_str_backend_wraps_in_local_fs(self):
        w = ContentBrowserWindow(backend="/tmp")
        assert isinstance(w._backend, LocalFSBackend)
        w.destroy()

    def test_str_backend_becomes_start_url_when_none(self):
        # String backend is a convenience for "open the content browser
        # at this path with the default LocalFSBackend". The string
        # flows through to the widget as the root URL.
        w = ContentBrowserWindow(backend="/tmp")
        assert w._start_url == "/tmp"
        w.destroy()

    def test_str_backend_does_not_overwrite_explicit_start_url(self):
        # Explicit start_url wins — the string backend is purely
        # shorthand for "use LocalFSBackend", without hijacking the
        # caller's explicit URL choice.
        w = ContentBrowserWindow(backend="/tmp", start_url="/home")
        assert w._start_url == "/home"
        w.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Default start URL — user's home
# ──────────────────────────────────────────────────────────────────────────────


@_skip_no_window
class TestDefaultStartUrl:
    def test_default_start_url_is_home(self):
        # ``os.path.expanduser("~")`` resolves to the current user's
        # home directory; LocalFSBackend.normalize_url returns a
        # normalised ``file://`` URL when the input carries the
        # scheme. Test that the resolved URL contains the home path.
        home = os.path.expanduser("~")
        w = ContentBrowserWindow()
        assert home in w._start_url
        w.destroy()

    def test_default_start_url_starts_with_file_scheme(self):
        w = ContentBrowserWindow()
        assert w._start_url.startswith("file://")
        w.destroy()

    def test_explicit_start_url_overrides_default(self):
        w = ContentBrowserWindow(
            backend=MockBackend(), start_url="mock://Home",
        )
        assert w._start_url == "mock://Home"
        w.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Module styles
# ──────────────────────────────────────────────────────────────────────────────


@_skip_no_window
class TestModuleStyles:
    def test_get_module_styles_returns_content_styles(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        assert w._get_module_styles() is CONTENT_STYLES
        w.destroy()

    def test_module_styles_is_a_dict(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        assert isinstance(w._get_module_styles(), dict)
        w.destroy()

    def test_module_styles_non_empty(self):
        # Step 8 populated CONTENT_STYLES with row / header / sort-arrow
        # tokens. The window surfaces whatever the style module defines;
        # an empty dict would signal a regression in that wiring.
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        assert len(w._get_module_styles()) > 0
        w.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# navigate_to — delegates to widget
# ──────────────────────────────────────────────────────────────────────────────


@_skip_no_window
class TestNavigateTo:
    def test_navigate_to_before_build_is_noop(self):
        # Widget hasn't been built yet (frame hasn't fired); the call
        # must not raise and must not mutate any widget state.
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        assert w._widget is None
        w.navigate_to("mock://Home/Projects")  # must not raise
        assert w._widget is None
        w.destroy()

    def test_navigate_to_delegates_to_widget_model(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        with w._window.frame:
            w._build_ui()
        w.navigate_to("mock://Home/Projects")
        assert w._widget.get_model().root_url == "mock://Home/Projects"
        w.destroy()

    def test_navigate_to_after_destroy_is_noop(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        with w._window.frame:
            w._build_ui()
        w.destroy()
        # After destroy, _widget is None — navigate_to should swallow
        # the call rather than attribute-error on the None reference.
        w.navigate_to("mock://Home/Projects")  # must not raise


# ──────────────────────────────────────────────────────────────────────────────
# go_back / go_forward — Step 20 keyboard-shortcut passthrough
# ──────────────────────────────────────────────────────────────────────────────


@_skip_no_window
class TestGoBackForward:
    def test_go_back_delegates_to_widget(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        with w._window.frame:
            w._build_ui()
        w.navigate_to("mock://Home/Documents")
        w.go_back()
        assert w._widget.get_detail_model().root_url == "mock://Home"
        w.destroy()

    def test_go_forward_delegates_to_widget(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        with w._window.frame:
            w._build_ui()
        w.navigate_to("mock://Home/Documents")
        w.go_back()
        w.go_forward()
        assert (
            w._widget.get_detail_model().root_url == "mock://Home/Documents"
        )
        w.destroy()

    def test_go_back_before_build_is_noop(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        assert w._widget is None
        w.go_back()  # must not raise
        w.destroy()

    def test_go_forward_before_build_is_noop(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        w.go_forward()  # must not raise
        w.destroy()

    def test_go_back_after_destroy_is_noop(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        with w._window.frame:
            w._build_ui()
        w.destroy()
        w.go_back()  # must not raise

    def test_go_forward_after_destroy_is_noop(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        with w._window.frame:
            w._build_ui()
        w.destroy()
        w.go_forward()  # must not raise


# ──────────────────────────────────────────────────────────────────────────────
# Destroy — widget + window teardown
# ──────────────────────────────────────────────────────────────────────────────


@_skip_no_window
class TestDestroy:
    def test_destroy_clears_widget_reference(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        with w._window.frame:
            w._build_ui()
        assert w._widget is not None
        w.destroy()
        assert w._widget is None

    def test_destroy_clears_window_reference(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        with w._window.frame:
            w._build_ui()
        w.destroy()
        assert w._window is None

    def test_destroy_detaches_widget_model(self):
        # FileBrowserWidget.destroy clears its model; confirm the
        # cascade fires so the widget isn't left holding a model
        # reference after the window has released it.
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        with w._window.frame:
            w._build_ui()
        widget = w._widget
        w.destroy()
        assert widget.get_model() is None

    def test_destroy_before_build_is_safe(self):
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        assert w._widget is None
        w.destroy()  # must not raise with _widget still None
        assert w._window is None

    def test_destroy_is_idempotent(self):
        # Second destroy is a no-op — every interior field is already
        # None from the first call. Mirrors StageWindow's contract
        # (tests/test_stage_window.py::test_destroy_is_idempotent).
        w = ContentBrowserWindow(backend=MockBackend(), start_url="mock://Home")
        with w._window.frame:
            w._build_ui()
        w.destroy()
        w.destroy()  # must not raise

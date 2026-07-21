# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`FileBrowserWidget` (the content browser implementation step 9 + Step 13).

Step 9 built the widget as a single-pane tree; Step 13 split it into
two panes (folder tree on the left, file detail on the right,
separated by a draggable splitter). These tests verify the public
surface — construction, tree/model wiring, navigation, backend swap,
destroy — without depending on a running :class:`Application`.

The legacy ``_model`` / ``_tree_view`` / ``_delegate`` attributes
remain callable as backward-compat properties that resolve to the
detail-pane equivalents (so QA scripts written against the
single-pane widget keep working); new assertions use the
``_tree_model`` / ``_detail_model`` names explicitly where they
express intent better.
"""

from __future__ import annotations

from contextlib import contextmanager

import omni.ui as ui
import pytest

from ovui_widgets.app.testing.mock_backend import MockBackend
from ovui_widgets.common.asset_types import AssetCategory
from ovui_widgets.common.managed_window import ManagedWindow
from ovui_widgets.content.backends.backend_adapter import BackendResult
from ovui_widgets.content.widget import FileBrowserWidget
from ovui_widgets.content.widget.file_browser_delegate import (
    FileBrowserDelegate,
)
from ovui_widgets.content.widget.file_browser_model import FileBrowserModel
from ovui_widgets.content.widget.file_grid_view import (
    _CELL_HORIZONTAL_GUTTER,
    _CELL_VERTICAL_GUTTER,
    _DEFAULT_CARD_SIZE,
    _LABEL_BAND_HEIGHT,
    FileGridView,
)
from ovui_widgets.content.widget.zoom_bar import ZoomBar

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """Single ovui Window reused across every widget-build test.

    Constructing a ``ui.Window`` per test measurably slows the module
    down (docking registration, frame allocation); sharing one and
    clearing its frame between tests gives the same isolation at a
    fraction of the cost. Mirrors the pattern in
    ``tests/test_file_browser_delegate.py``.
    """
    win = ui.Window(
        "_test_file_browser_widget", width=400, height=300,
    )
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
# Surface
# ──────────────────────────────────────────────────────────────────────────────


class TestSurface:
    def test_not_a_managed_window(self):
        # Widgets are embeddable; ownership of the window belongs to
        # the window layer (Step 10), not the widget.
        assert not issubclass(FileBrowserWidget, ManagedWindow)

    def test_reexported_from_widget_package(self):
        from ovui_widgets.content.widget import FileBrowserWidget as FBW

        assert FBW is FileBrowserWidget

    def test_widget_package_all_contains_widget(self):
        import ovui_widgets.content.widget as pkg

        assert "FileBrowserWidget" in pkg.__all__


# ──────────────────────────────────────────────────────────────────────────────
# Construction
# ──────────────────────────────────────────────────────────────────────────────


class TestConstruction:
    def test_instantiates_with_mock_backend(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert isinstance(widget, FileBrowserWidget)
        widget.destroy()

    def test_build_creates_detail_tree_view(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._detail_tree_view is not None
        widget.destroy()

    def test_build_creates_tree_tree_view(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._tree_tree_view is not None
        widget.destroy()

    def test_build_creates_detail_scrolling_frame(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._detail_scrolling_frame is not None
        widget.destroy()

    def test_build_creates_tree_scrolling_frame(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._tree_scrolling_frame is not None
        widget.destroy()

    def test_build_creates_detail_model(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert isinstance(widget._detail_model, FileBrowserModel)
        widget.destroy()

    def test_build_creates_navigation_model(self, ephemeral_window):
        # Step 42: left pane is driven by a NavigationModel (collections),
        # not a folder-only FileBrowserModel.
        from ovui_widgets.content.widget import NavigationModel

        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert isinstance(widget._navigation_model, NavigationModel)
        widget.destroy()

    def test_build_creates_detail_delegate(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert isinstance(widget._detail_delegate, FileBrowserDelegate)
        widget.destroy()

    def test_build_creates_navigation_delegate(self, ephemeral_window):
        # Step 42: left pane uses NavigationDelegate instead of
        # TreeFolderDelegate.
        from ovui_widgets.content.widget import NavigationDelegate

        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert isinstance(widget._navigation_delegate, NavigationDelegate)
        widget.destroy()

    def test_detail_delegate_is_bound_to_detail_model(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._detail_delegate._model is widget._detail_model
        widget.destroy()

    def test_embeds_inside_plain_vstack(self, ephemeral_window):
        # StageWidget pattern: the widget should happily build into any
        # live ovui context, not only into a Window frame. Wrapping in
        # a window frame here keeps ovui's global build state clean
        # between tests — the VStack belongs to the window's frame
        # scope, which is cleared on exit.
        with in_window_frame(ephemeral_window):
            with ui.VStack():
                widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._detail_tree_view is not None
        widget.destroy()

    def test_detail_model_is_not_folder_only(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._detail_model._folder_only is False
        widget.destroy()

    def test_root_url_is_normalized_via_backend(self, ephemeral_window):
        # MockBackend.normalize_url strips stray "/" components — the
        # widget should therefore carry the normalised form on the
        # detail model. The navigation model has no root URL in Step 42.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home/")
        assert widget._detail_model.root_url == "mock://Home"
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# TreeView / model binding
# ──────────────────────────────────────────────────────────────────────────────


class TestTreeViewBinding:
    def test_detail_tree_view_model_is_detail_model(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._detail_tree_view.model is widget._detail_model
        widget.destroy()

    def test_tree_tree_view_model_is_navigation_model(self, ephemeral_window):
        # Step 42: the left-pane TreeView's model is the navigation
        # model (collections + their FileItem children), not the Step 13
        # folder-tree FileBrowserModel.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._tree_tree_view.model is widget._navigation_model
        widget.destroy()

    def test_detail_tree_view_root_visible(self, ephemeral_window):
        # root_visible=True is load-bearing on the detail pane:
        # without it an empty folder renders as blank whitespace.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._detail_tree_view.root_visible is True
        widget.destroy()

    def test_detail_tree_view_header_visible(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._detail_tree_view.header_visible is True
        widget.destroy()

    def test_tree_tree_view_header_not_visible(self, ephemeral_window):
        # Tree pane is a compact folder drill-down — the three-column
        # header would waste vertical space and read as a false
        # columnar table.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._tree_tree_view.header_visible is False
        widget.destroy()

    def test_model_yields_mock_children_for_home(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        children = widget.get_model().get_item_children(None)
        names = {c.name for c in children}
        # MockBackend's default tree places these directly under Home;
        # hidden entries are filtered by the model's default show_hidden=False.
        assert "Documents" in names
        assert "Textures" in names
        assert "Scripts" in names
        assert ".hidden_folder" not in names
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Backward-compat aliases
# ──────────────────────────────────────────────────────────────────────────────


class TestLegacyAliases:
    """The legacy single-pane attributes must still work for QA scripts."""

    def test_underscore_model_returns_detail_model(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._model is widget._detail_model
        widget.destroy()

    def test_underscore_tree_view_returns_detail_tree_view(
        self, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._tree_view is widget._detail_tree_view
        widget.destroy()

    def test_underscore_delegate_returns_detail_delegate(
        self, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._delegate is widget._detail_delegate
        widget.destroy()

    def test_underscore_scrolling_frame_returns_detail_scrolling_frame(
        self, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._scrolling_frame is widget._detail_scrolling_frame
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# navigate_to
# ──────────────────────────────────────────────────────────────────────────────


class TestNavigateTo:
    def test_navigate_to_changes_detail_model_root_url(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.navigate_to("mock://Home/Documents")
        assert widget.get_detail_model().root_url == "mock://Home/Documents"
        widget.destroy()

    def test_navigate_to_does_not_affect_navigation_model(
        self, ephemeral_window,
    ):
        # Step 42: navigate_to re-roots the detail pane only; the
        # navigation model is a fixed list of collections and has no
        # "root URL" concept.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        nav_before = widget._navigation_model
        widget.navigate_to("mock://Home/Documents")
        assert widget._navigation_model is nav_before
        widget.destroy()

    def test_navigate_to_yields_new_folders_children(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.navigate_to("mock://Home/Documents")
        names = {
            c.name for c in widget.get_detail_model().get_item_children(None)
        }
        assert names == {"Projects"}
        widget.destroy()

    def test_navigate_to_same_url_is_noop(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        before_detail_root = widget.get_detail_model().root
        widget.navigate_to("mock://Home")
        assert widget.get_detail_model().root is before_detail_root
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# get_model / get_tree_model / get_detail_model
# ──────────────────────────────────────────────────────────────────────────────


class TestGetModel:
    def test_get_model_returns_detail_model(self, ephemeral_window):
        # Legacy single-pane accessor — resolves to the detail pane,
        # which is what ContentBrowserWindow (Step 10) addresses.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget.get_model() is widget._detail_model
        widget.destroy()

    def test_get_model_returns_filebrowsermodel(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert isinstance(widget.get_model(), FileBrowserModel)
        widget.destroy()

    def test_get_tree_model_returns_the_navigation_model(
        self, ephemeral_window,
    ):
        # Step 42: ``get_tree_model`` returns the nav model now.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget.get_tree_model() is widget._navigation_model
        widget.destroy()

    def test_get_detail_model_returns_the_detail_model(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget.get_detail_model() is widget._detail_model
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# set_backend
# ──────────────────────────────────────────────────────────────────────────────


class TestSetBackend:
    def test_set_backend_stores_new_backend(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        new_backend = MockBackend()
        widget.set_backend(new_backend)
        assert widget._backend is new_backend
        widget.destroy()

    def test_set_backend_replaces_detail_model(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        old_model = widget._detail_model
        widget.set_backend(MockBackend())
        assert widget._detail_model is not old_model
        assert isinstance(widget._detail_model, FileBrowserModel)
        widget.destroy()

    def test_set_backend_replaces_navigation_model(self, ephemeral_window):
        # Step 42: the navigation model is rebuilt on backend swap so
        # its collections (drives, bookmarks, recent) enumerate against
        # the new backend.
        from ovui_widgets.content.widget import NavigationModel

        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        old_model = widget._navigation_model
        widget.set_backend(MockBackend())
        assert widget._navigation_model is not old_model
        assert isinstance(widget._navigation_model, NavigationModel)
        widget.destroy()

    def test_set_backend_rebinds_detail_delegate(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.set_backend(MockBackend())
        assert widget._detail_delegate._model is widget._detail_model
        widget.destroy()

    def test_set_backend_updates_detail_tree_view_model(
        self, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.set_backend(MockBackend())
        assert widget._detail_tree_view.model is widget._detail_model
        widget.destroy()

    def test_set_backend_updates_tree_tree_view_model(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.set_backend(MockBackend())
        assert widget._tree_tree_view.model is widget._navigation_model
        widget.destroy()

    def test_set_backend_preserves_detail_root_url(self, ephemeral_window):
        # Step 42: only the detail model carries a root URL — the
        # navigation model has no root, so no preservation check there.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home/Documents")
        widget.set_backend(MockBackend())
        assert widget._detail_model.root_url == "mock://Home/Documents"
        widget.destroy()

    def test_set_backend_preserves_detail_folder_only_flag(
        self, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.set_backend(MockBackend())
        assert widget._detail_model._folder_only is False
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# destroy
# ──────────────────────────────────────────────────────────────────────────────


class TestDestroy:
    def test_destroy_does_not_crash(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()  # must not raise

    def test_destroy_clears_detail_tree_view_reference(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._detail_tree_view is None

    def test_destroy_clears_tree_tree_view_reference(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._tree_tree_view is None

    def test_destroy_clears_detail_model_reference(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._detail_model is None

    def test_destroy_clears_navigation_model_reference(
        self, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._navigation_model is None

    def test_destroy_clears_splitter_reference(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._splitter is None

    def test_destroy_detaches_detail_delegate_before_drop(
        self, ephemeral_window,
    ):
        # A dangling delegate→model reference would keep the model
        # alive past destroy. Confirming the detach happens before the
        # delegate is dropped catches regressions where a rearrangement
        # of destroy() leaves the binding in place.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        delegate = widget._detail_delegate  # hold a local so we can inspect
        widget.destroy()
        assert delegate._model is None

    def test_destroy_clears_navigation_delegate_reference(
        self, ephemeral_window,
    ):
        # Step 42: the left pane's delegate is now NavigationDelegate.
        # NavigationDelegate has no model binding — it reads ``model``
        # from the build-widget call — so the destroy contract is just
        # that the widget's reference drops to ``None``.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._navigation_delegate is None

    def test_double_destroy_does_not_crash(self, ephemeral_window):
        # The ``is not None`` guards in ``destroy`` make the second
        # call safe — without them, the second set_model(None) on a
        # ``None`` delegate would NPE. Pin the idempotency here so a
        # future refactor can't regress it.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        widget.destroy()  # must not raise
        assert widget._detail_model is None

    def test_get_model_returns_none_after_destroy(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget.get_model() is None

    def test_get_tree_model_returns_none_after_destroy(
        self, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget.get_tree_model() is None

    def test_get_detail_model_returns_none_after_destroy(
        self, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget.get_detail_model() is None

    def test_set_backend_after_destroy_is_noop(self, ephemeral_window):
        # Calling set_backend on a destroyed widget must not resurrect
        # it or raise — Step 11's Application shutdown may call it
        # during theme/layout teardown in any order.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        widget.set_backend(MockBackend())  # must not raise
        assert widget.get_model() is None


# ──────────────────────────────────────────────────────────────────────────────
# _path_autocomplete (Step 18)
# ──────────────────────────────────────────────────────────────────────────────


class TestPathAutocomplete:
    """Step 18 — the PathField autocomplete provider on FileBrowserWidget.

    The handler shape is ``(prefix, callback) → None`` where ``callback``
    receives a flat list of folder names with trailing ``/``. Files are
    filtered out (the path bar navigates directories). Any backend
    error cascades to a callback invocation with ``[]`` — the dropdown
    simply stays empty.
    """

    def test_handler_fires_callback_with_folder_names(
        self, ephemeral_window,
    ):
        captured: list = []
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._path_autocomplete("mock://Home", captured.append)
        assert len(captured) == 1
        names = captured[0]
        # MockBackend default tree under Home has Documents, Textures,
        # Scripts, .hidden_folder — all folders, all present (no hidden
        # filter in the autocomplete provider).
        assert "Documents/" in names
        assert "Textures/" in names
        assert "Scripts/" in names
        assert ".hidden_folder/" in names
        widget.destroy()

    def test_handler_appends_trailing_slash(self, ephemeral_window):
        """Every returned name carries the trailing separator (§15.6)."""
        captured: list = []
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._path_autocomplete("mock://Home", captured.append)
        for name in captured[0]:
            assert name.endswith("/"), name
        widget.destroy()

    def test_handler_filters_out_files(self, ephemeral_window):
        """``Projects`` contains only files — callback gets ``[]``."""
        captured: list = []
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._path_autocomplete(
            "mock://Home/Documents/Projects", captured.append,
        )
        assert captured == [[]]
        widget.destroy()

    def test_handler_mixed_folders_and_files_returns_folders_only(
        self, ephemeral_window,
    ):
        """Textures has two files — no folders — so dropdown is empty."""
        captured: list = []
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._path_autocomplete(
            "mock://Home/Textures", captured.append,
        )
        assert captured == [[]]
        widget.destroy()

    def test_handler_on_missing_path_returns_empty_list(
        self, ephemeral_window,
    ):
        """Not-found error from backend → callback fires with ``[]``."""
        captured: list = []
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._path_autocomplete(
            "mock://DoesNotExist", captured.append,
        )
        assert captured == [[]]
        widget.destroy()

    def test_handler_on_injected_error_returns_empty_list(
        self, ephemeral_window,
    ):
        """Any non-OK backend result degrades to an empty dropdown."""
        captured: list = []
        backend = MockBackend()
        backend._errors["mock://Home"] = BackendResult.ERROR_ACCESS_DENIED
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(backend, "mock://Shared")
        widget._path_autocomplete("mock://Home", captured.append)
        assert captured == [[]]
        widget.destroy()

    def test_handler_empty_folder_returns_empty_list(self, ephemeral_window):
        """``mock://Shared`` is an empty folder — callback gets ``[]``."""
        captured: list = []
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._path_autocomplete("mock://Shared", captured.append)
        assert captured == [[]]
        widget.destroy()

    def test_handler_after_destroy_fires_empty_callback(
        self, ephemeral_window,
    ):
        """Post-destroy: ``_backend`` may be None; the callback still fires."""
        captured: list = []
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        # Simulate a teardown that nulled the backend.
        widget._backend = None
        widget._path_autocomplete("mock://Home", captured.append)
        assert captured == [[]]
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# BrowserBar wiring (Step 20)
# ──────────────────────────────────────────────────────────────────────────────


class TestBrowserBarWiring:
    """Step 20 — :class:`BrowserBar` is created, wired, and seeded."""

    def test_browser_bar_is_created_on_build(self, ephemeral_window):
        from ovui_widgets.content.widget import BrowserBar

        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert isinstance(widget._browser_bar, BrowserBar)
        widget.destroy()

    def test_browser_bar_is_seeded_with_initial_root(self, ephemeral_window):
        """Constructor path must propagate to the browser bar so the
        first rendered frame shows the initial folder in the breadcrumbs
        and the visited history has a "back target"."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._browser_bar._history.size() == 1
        assert widget._browser_bar._path_field.path == "mock://Home"
        widget.destroy()

    def test_navigate_to_updates_browser_bar_path(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.navigate_to("mock://Home/Documents")
        assert widget._browser_bar._path_field.path == "mock://Home/Documents"
        # Seed + navigate_to = two entries in history.
        assert widget._browser_bar._history.size() == 2
        widget.destroy()

    def test_nav_child_selection_updates_browser_bar_path(
        self, ephemeral_window,
    ):
        """Step 42 nav-pane child click pushes the URL into the bar."""
        from ovui_widgets.content.widget.file_item import FileItem

        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        # Simulate a FileItem child selection (as Step 43/44/46 will
        # surface). A synthesised item is enough to drive the
        # NavigationModel.activate_item path.
        documents = FileItem(
            url="mock://Home/Documents",
            name="Documents",
            is_folder=True,
        )
        widget._on_tree_selection([documents])
        assert (
            widget._browser_bar._path_field.path
            == "mock://Home/Documents"
        )
        widget.destroy()

    def test_drill_updates_browser_bar_path(self, ephemeral_window):
        """Step 14 detail-pane double-click drill now also pushes to the bar."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        detail_children = widget._detail_model.get_item_children(None)
        documents = next(c for c in detail_children if c.name == "Documents")
        widget._drill_into_folder(documents)
        assert (
            widget._browser_bar._path_field.path
            == "mock://Home/Documents"
        )
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# _on_apply_path (Step 20)
# ──────────────────────────────────────────────────────────────────────────────


class TestOnApplyPath:
    """Step 20 — :meth:`_on_apply_path` normalises, stats, and navigates."""

    def test_apply_path_renavigates_detail_model(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_apply_path("mock://Home/Documents")
        assert widget._detail_model.root_url == "mock://Home/Documents"
        widget.destroy()

    def test_apply_path_normalises_via_backend(self, ephemeral_window):
        """Trailing slash collapses through :meth:`BackendAdapter.normalize_url`."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_apply_path("mock://Home/Documents/")
        assert widget._detail_model.root_url == "mock://Home/Documents"
        widget.destroy()

    def test_apply_path_does_not_touch_nav_selection(self, ephemeral_window):
        # Step 42: apply-path re-roots the detail pane only. The nav
        # pane renders collections (not the detail folder hierarchy),
        # so the applied URL has no corresponding tree row to select.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        nav_selection_before = list(widget._tree_tree_view.selection)
        widget._on_apply_path("mock://Home/Documents")
        assert list(widget._tree_tree_view.selection) == nav_selection_before
        widget.destroy()

    def test_apply_path_records_in_browser_bar_history(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_apply_path("mock://Home/Documents")
        # Initial seed + apply = 2 distinct entries.
        assert widget._browser_bar._history.size() == 2
        widget.destroy()

    def test_apply_path_updates_browser_bar_field(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_apply_path("mock://Home/Documents")
        assert (
            widget._browser_bar._path_field.path
            == "mock://Home/Documents"
        )
        widget.destroy()

    def test_apply_path_missing_url_does_not_navigate(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        before = widget._detail_model.root_url
        widget._on_apply_path("mock://DoesNotExist")
        # Navigation is suppressed — panes stay where they were.
        assert widget._detail_model.root_url == before
        widget.destroy()

    def test_apply_path_missing_url_does_not_crash(self, ephemeral_window):
        """The error path must be silent (stderr-only) and never raise."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_apply_path("mock://Nowhere")  # must not raise
        widget.destroy()

    def test_apply_path_on_file_url_does_not_navigate(self, ephemeral_window):
        """A stat on a file returns OK but IS_FOLDER flag is clear —
        must be treated as error."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(), "mock://Home/Documents/Projects",
            )
        before = widget._detail_model.root_url
        widget._on_apply_path(
            "mock://Home/Documents/Projects/readme.md",
        )
        assert widget._detail_model.root_url == before
        widget.destroy()

    def test_apply_path_empty_string_is_noop(self, ephemeral_window):
        """An empty URL short-circuits before the stat."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        before = widget._detail_model.root_url
        widget._on_apply_path("")
        assert widget._detail_model.root_url == before
        widget.destroy()

    def test_apply_path_shows_error_notification(
        self, ephemeral_window, monkeypatch,
    ):
        """Invalid path must raise an :class:`ErrorReporter` status
        warning with the "Folder not found" message verbatim."""
        from ovui_widgets.common import error_reporter as er

        captured: list = []

        def _fake_show_warning(message, *args, **kwargs):
            captured.append(message)

        monkeypatch.setattr(
            er.ErrorReporter, "show_warning", _fake_show_warning,
        )
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_apply_path("mock://DoesNotExist")
        assert captured == ["Folder not found"]
        widget.destroy()

    def test_apply_path_after_destroy_is_noop(self, ephemeral_window):
        """After destroy the backend is ``None`` and the call falls through."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        # Must not raise even though _detail_model / _backend are still
        # the torn-down refs.
        widget._on_apply_path("mock://Home")  # must not raise


# ──────────────────────────────────────────────────────────────────────────────
# go_back / go_forward (Step 20)
# ──────────────────────────────────────────────────────────────────────────────


class TestGoBackForward:
    """Public :meth:`go_back` / :meth:`go_forward` walk the visited history."""

    def test_go_back_rewinds_to_previous_folder(self, ephemeral_window):
        """After seed=Home + navigate=Documents, go_back returns to Home."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_apply_path("mock://Home/Documents")
        assert widget._detail_model.root_url == "mock://Home/Documents"
        widget.go_back()
        assert widget._detail_model.root_url == "mock://Home"
        widget.destroy()

    def test_go_forward_replays_navigation(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_apply_path("mock://Home/Documents")
        widget.go_back()  # back to Home
        widget.go_forward()  # forward to Documents
        assert widget._detail_model.root_url == "mock://Home/Documents"
        widget.destroy()

    def test_go_back_updates_browser_bar_field(self, ephemeral_window):
        """The breadcrumb row must track the back navigation."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_apply_path("mock://Home/Documents")
        widget.go_back()
        assert widget._browser_bar._path_field.path == "mock://Home"
        widget.destroy()

    def test_go_back_does_not_pollute_history(self, ephemeral_window):
        """The back navigation's own re-apply must not re-insert the URL."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_apply_path("mock://Home/Documents")
        size_before_back = widget._browser_bar._history.size()
        widget.go_back()
        assert widget._browser_bar._history.size() == size_before_back
        widget.destroy()

    def test_go_back_at_start_is_noop(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        before = widget._detail_model.root_url
        widget.go_back()  # history has only the seed entry
        assert widget._detail_model.root_url == before
        widget.destroy()

    def test_go_forward_at_newest_is_noop(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        before = widget._detail_model.root_url
        widget.go_forward()  # cursor already at newest
        assert widget._detail_model.root_url == before
        widget.destroy()

    def test_go_back_after_destroy_is_noop(self, ephemeral_window):
        """Destroyed widget must swallow the Alt+Left / Alt+Right dispatch."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        widget.go_back()  # must not raise
        widget.go_forward()  # must not raise


# ──────────────────────────────────────────────────────────────────────────────
# destroy (Step 20 additions)
# ──────────────────────────────────────────────────────────────────────────────


class TestDestroyBrowserBar:
    def test_destroy_clears_browser_bar_reference(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._browser_bar is None

    def test_destroy_releases_inner_path_field(self, ephemeral_window):
        """The :class:`BrowserBar`'s own destroy must have fired."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        bar = widget._browser_bar
        widget.destroy()
        # BrowserBar.destroy nulls its _path_field ref.
        assert bar._path_field is None

    def test_double_destroy_does_not_crash(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        widget.destroy()  # idempotent
        assert widget._browser_bar is None


# ──────────────────────────────────────────────────────────────────────────────
# Grid view + zoom bar wiring (Step 24)
# ──────────────────────────────────────────────────────────────────────────────


class TestGridAndZoomBarWiring:
    """Step 24 — detail pane carries a grid view sibling + a zoom bar."""

    def test_grid_view_is_created_on_build(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert isinstance(widget._detail_grid_view, FileGridView)
        widget.destroy()

    def test_grid_frame_is_created_on_build(self, ephemeral_window):
        """Grid view lives inside a wrapping Frame so the widget can
        toggle visibility without touching :class:`FileGridView`'s
        internal ScrollingFrame."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._detail_grid_frame is not None
        widget.destroy()

    def test_zoom_bar_is_created_on_build(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert isinstance(widget._zoom_bar, ZoomBar)
        widget.destroy()

    def test_grid_view_is_bound_to_detail_model(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._detail_grid_view._model is widget._detail_model
        widget.destroy()

    def test_default_view_is_grid(self, ephemeral_window):
        """Architecture §25.4: default scale 1.0 ≥ 0.75 → grid view."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._is_grid_view is True
        # Grid frame visible, tree scrolling frame hidden.
        assert widget._detail_grid_frame.visible is True
        assert widget._detail_scrolling_frame.visible is False
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Zoom bar toggle (Step 24)
# ──────────────────────────────────────────────────────────────────────────────


class TestZoomBarToggle:
    """Step 24 — ``_on_zoom_bar_toggle_grid`` flips tree vs grid visibility."""

    def test_toggle_to_list_hides_grid_frame(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_zoom_bar_toggle_grid(False)
        assert widget._detail_grid_frame.visible is False
        widget.destroy()

    def test_toggle_to_list_shows_tree_scrolling_frame(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_zoom_bar_toggle_grid(False)
        assert widget._detail_scrolling_frame.visible is True
        widget.destroy()

    def test_toggle_to_list_flips_is_grid_view_flag(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_zoom_bar_toggle_grid(False)
        assert widget._is_grid_view is False
        widget.destroy()

    def test_toggle_back_to_grid_shows_grid_frame(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_zoom_bar_toggle_grid(False)
        widget._on_zoom_bar_toggle_grid(True)
        assert widget._detail_grid_frame.visible is True
        assert widget._detail_scrolling_frame.visible is False
        assert widget._is_grid_view is True
        widget.destroy()

    def test_toggle_after_destroy_is_noop(self, ephemeral_window):
        """Post-destroy refs are ``None``; the toggle must not raise."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        widget._on_zoom_bar_toggle_grid(False)  # must not raise
        widget._on_zoom_bar_toggle_grid(True)  # must not raise


# ──────────────────────────────────────────────────────────────────────────────
# Zoom bar scale (Step 24)
# ──────────────────────────────────────────────────────────────────────────────


class TestZoomBarScale:
    """Step 24 — ``_on_zoom_bar_scale`` drives :meth:`FileGridView.set_scale`."""

    def test_scale_updates_grid_view_scale(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_zoom_bar_scale(1.5)
        assert widget._detail_grid_view._scale == 1.5
        widget.destroy()

    def test_scale_updates_grid_column_width(self, ephemeral_window):
        """Column width equals scaled reference card edge plus gutter."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_zoom_bar_scale(1.5)
        expected = int(_DEFAULT_CARD_SIZE * 1.5) + _CELL_HORIZONTAL_GUTTER
        assert int(widget._detail_grid_view._vgrid.column_width) == expected
        widget.destroy()

    def test_scale_updates_grid_row_height(self, ephemeral_window):
        """Row height includes scaled edge, label band, and vertical gutter."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_zoom_bar_scale(1.5)
        expected = (
            int(_DEFAULT_CARD_SIZE * 1.5)
            + _LABEL_BAND_HEIGHT
            + _CELL_VERTICAL_GUTTER
        )
        assert int(widget._detail_grid_view._vgrid.row_height) == expected
        widget.destroy()

    def test_scale_half_size(self, ephemeral_window):
        """Slider index 0 → scale 0.5 plus reference grid gutter."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_zoom_bar_scale(0.5)
        expected = int(_DEFAULT_CARD_SIZE * 0.5) + _CELL_HORIZONTAL_GUTTER
        assert int(widget._detail_grid_view._vgrid.column_width) == expected
        widget.destroy()

    def test_scale_after_destroy_is_noop(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        widget._on_zoom_bar_scale(1.5)  # must not raise


# ──────────────────────────────────────────────────────────────────────────────
# Selection preservation across toggle (Step 24)
# ──────────────────────────────────────────────────────────────────────────────


class TestSelectionPreservation:
    """Step 24 — toggling grid ↔ list preserves the active view's selection."""

    def test_grid_selection_preserved_on_toggle_to_list(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        children = widget._detail_model.get_item_children(None)
        # Pick a stable child by name so the test survives any
        # resort-stability change in the mock backend.
        documents = next(c for c in children if c.name == "Documents")
        widget._detail_grid_view.set_selection([documents])
        widget._on_zoom_bar_toggle_grid(False)
        urls = [item.url for item in widget._detail_tree_view.selection]
        assert documents.url in urls
        widget.destroy()

    def test_list_selection_preserved_on_toggle_to_grid(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        # Start from list view and seed selection there.
        widget._on_zoom_bar_toggle_grid(False)
        children = widget._detail_model.get_item_children(None)
        textures = next(c for c in children if c.name == "Textures")
        widget._detail_tree_view.selection = [textures]
        widget._on_zoom_bar_toggle_grid(True)
        urls = [item.url for item in widget._detail_grid_view.get_selection()]
        assert textures.url in urls
        widget.destroy()

    def test_empty_selection_preserved_across_toggle(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_zoom_bar_toggle_grid(False)
        assert list(widget._detail_tree_view.selection) == []
        widget._on_zoom_bar_toggle_grid(True)
        assert widget._detail_grid_view.get_selection() == []
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Grid double-click drills into folders (Step 24)
# ──────────────────────────────────────────────────────────────────────────────


class TestGridDoubleClick:
    """Grid cards share :meth:`_drill_into_folder` semantics with tree rows."""

    def test_grid_double_click_on_folder_reroots_detail(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        children = widget._detail_model.get_item_children(None)
        documents = next(c for c in children if c.name == "Documents")
        widget._on_grid_double_click(documents)
        assert widget._detail_model.root_url == "mock://Home/Documents"
        widget.destroy()

    def test_grid_double_click_on_file_does_not_reroot(self, ephemeral_window):
        """File double-click dispatches open — does not re-root the detail pane."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(), "mock://Home/Documents/Projects",
            )
        before = widget._detail_model.root_url
        children = widget._detail_model.get_item_children(None)
        leaf = next(iter(children))
        widget._on_grid_double_click(leaf)
        assert widget._detail_model.root_url == before
        widget.destroy()

    def test_double_click_usd_file_calls_open_file_fn(
        self, ephemeral_window,
    ):
        """USD card double-click routes through the explicit
        ``open_file_fn`` callback (Step 11.4 contract). Replaces the
        pre-Step-11.4 ``Application.instance().open_file`` lookup."""
        from ovui_widgets.content.widget.file_item import FileItem

        calls: list[str] = []

        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(),
                "mock://Home",
                open_file_fn=calls.append,
            )

        usd_item = FileItem(
            url="file:///tmp/scene.usda", name="scene.usda", is_folder=False,
        )
        widget._dispatch_file_open(usd_item)
        # ``file://`` URLs are stripped to a native filesystem path so
        # ``pxr.Usd.Stage.Open`` accepts them.
        assert calls == ["/tmp/scene.usda"]
        widget.destroy()

    def test_double_click_non_usd_file_does_not_open(self, ephemeral_window):
        """Non-USD card double-click skips the ``open_file_fn`` callback.

        Step 11.4 contract: only USD-extension paths reach the
        callback; everything else early-returns so a stray .png /
        .txt double-click does not load a stage. The wiring is
        verified by passing an ``open_file_fn`` and asserting it is
        never called.
        """
        from ovui_widgets.content.widget.file_item import FileItem

        calls: list[str] = []

        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(),
                "mock://Home",
                open_file_fn=calls.append,
            )

        png_item = FileItem(
            url="file:///tmp/concrete.png", name="concrete.png", is_folder=False,
        )
        widget._dispatch_file_open(png_item)
        assert calls == []
        widget.destroy()

    def test_dispatch_file_open_without_callback_is_noop(self, ephemeral_window):
        """Step 11.4: without an ``open_file_fn`` callback, the
        dispatch silently no-ops. Replaces the pre-Step-11.4 contract
        of "no live Application singleton -> RuntimeError caught and
        swallowed". The callback is the explicit seam now."""
        from ovui_widgets.content.widget.file_item import FileItem

        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(),
                "mock://Home",
                open_file_fn=None,
            )
        usd_item = FileItem(
            url="file:///tmp/scene.usda",
            name="scene.usda",
            is_folder=False,
        )
        # Must not raise.
        widget._dispatch_file_open(usd_item)
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Empty-state overlay with grid view (Step 24)
# ──────────────────────────────────────────────────────────────────────────────


class TestEmptyStateWithGrid:
    """Step 24 — overlay's ``_hide`` restores the view matching ``_is_grid_view``."""

    def test_overlay_show_hides_both_views(self, ephemeral_window):
        """Access-denied overlay hides grid + tree so cards/header do
        not bleed through the error label."""
        backend = MockBackend()
        backend._errors["mock://Shared"] = BackendResult.ERROR_ACCESS_DENIED
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(backend, "mock://Shared")
        assert widget._empty_state_container.visible is True
        assert widget._detail_scrolling_frame.visible is False
        assert widget._detail_grid_frame.visible is False
        widget.destroy()

    def test_overlay_hide_restores_grid_when_is_grid_view(
        self, ephemeral_window,
    ):
        """``_is_grid_view=True`` + overlay hidden → grid visible, tree hidden."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        # Home has children → overlay hidden by default, grid shown.
        assert widget._empty_state_container.visible is False
        assert widget._detail_grid_frame.visible is True
        assert widget._detail_scrolling_frame.visible is False
        widget.destroy()

    def test_overlay_hide_restores_tree_when_list_view(self, ephemeral_window):
        """After toggling to list, overlay-hide must restore the tree,
        not the grid."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_zoom_bar_toggle_grid(False)
        # Force a re-evaluation of the overlay state.
        widget._update_empty_state()
        assert widget._detail_scrolling_frame.visible is True
        assert widget._detail_grid_frame.visible is False
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# set_backend re-bind (Step 24)
# ──────────────────────────────────────────────────────────────────────────────


class TestSetBackendGrid:
    """Step 24 — swapping backends rebinds the grid view to the new model."""

    def test_set_backend_rebinds_grid_view_model(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.set_backend(MockBackend())
        assert widget._detail_grid_view._model is widget._detail_model
        widget.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# destroy (Step 24 additions)
# ──────────────────────────────────────────────────────────────────────────────


class TestDestroyGridAndZoomBar:
    def test_destroy_clears_zoom_bar_reference(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._zoom_bar is None

    def test_destroy_clears_grid_view_reference(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._detail_grid_view is None

    def test_destroy_clears_grid_frame_reference(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._detail_grid_frame is None

    def test_destroy_releases_inner_zoom_bar(self, ephemeral_window):
        """The :class:`ZoomBar`'s own destroy must have fired."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        bar = widget._zoom_bar
        widget.destroy()
        # ZoomBar.destroy nulls its _slider ref.
        assert bar._slider is None

    def test_destroy_releases_inner_grid_view(self, ephemeral_window):
        """The :class:`FileGridView`'s own destroy must have fired."""
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        grid = widget._detail_grid_view
        widget.destroy()
        # FileGridView.destroy nulls its _vgrid ref and clears cards.
        assert grid._vgrid is None
        assert grid._cards == {}

    def test_double_destroy_does_not_crash_with_grid(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        widget.destroy()  # idempotent
        assert widget._zoom_bar is None
        assert widget._detail_grid_view is None


# ──────────────────────────────────────────────────────────────────────────────
# Step 28 — SearchField + FilterButton toolbar wiring
# ──────────────────────────────────────────────────────────────────────────────


class TestSearchAndFilterWiring:
    """Step 28 — toolbar filter widgets exist and route to the detail model.

    The widget-level tests assert routing: a call to the handler
    propagates to :meth:`FileBrowserModel.set_text_filter` /
    :meth:`FileBrowserModel.set_asset_type_whitelist`. Filter semantics
    (substring match, empty-set / None == allow all, folders always
    pass) live in ``tests/test_file_browser_model.py``; repeating them
    here would cheat the same code twice.
    """

    def test_search_field_is_created_on_build(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._search_field is not None
        widget.destroy()

    def test_filter_button_is_created_on_build(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._filter_button is not None
        widget.destroy()

    def test_search_field_initial_text_is_empty(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._search_field.text == ""
        widget.destroy()

    def test_filter_button_initial_active_set_is_empty(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        assert widget._filter_button.active_categories == set()
        widget.destroy()

    def test_on_search_changed_filters_detail_view(self, ephemeral_window):
        # Root at Projects so the detail pane shows the three leaves:
        # ``demo.usda``, ``demo.usdc``, ``readme.md``. Typing "demo" must
        # narrow to the two demo files.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(), "mock://Home/Documents/Projects",
            )
        widget._on_search_changed("demo")
        names = {
            c.name for c in widget._detail_model.get_item_children(None)
        }
        assert names == {"demo.usda", "demo.usdc"}
        widget.destroy()

    def test_on_search_changed_is_case_insensitive(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(), "mock://Home/Documents/Projects",
            )
        widget._on_search_changed("DEMO")
        names = {
            c.name for c in widget._detail_model.get_item_children(None)
        }
        assert "demo.usda" in names
        assert "demo.usdc" in names
        assert "readme.md" not in names
        widget.destroy()

    def test_on_search_changed_empty_restores_all(self, ephemeral_window):
        # Clear search after a narrow — all three leaves must come back.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(), "mock://Home/Documents/Projects",
            )
        widget._on_search_changed("demo")
        widget._on_search_changed("")
        names = {
            c.name for c in widget._detail_model.get_item_children(None)
        }
        assert names == {"demo.usda", "demo.usdc", "readme.md"}
        widget.destroy()

    def test_on_filter_changed_filters_detail_view(self, ephemeral_window):
        # Projects/ has demo.usda, demo.usdc, readme.md. Whitelist USD
        # only — readme.md (TEXT) must disappear, the two USD files stay.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(), "mock://Home/Documents/Projects",
            )
        widget._on_filter_changed({AssetCategory.USD})
        names = {
            c.name for c in widget._detail_model.get_item_children(None)
        }
        assert names == {"demo.usda", "demo.usdc"}
        widget.destroy()

    def test_on_filter_changed_empty_set_restores_all(self, ephemeral_window):
        # FilterButton fires ``on_filter_changed(set())`` when the user
        # unchecks every item. The handler must treat that as "no
        # filter" rather than "hide everything" (the explicit contract
        # in :meth:`FileBrowserModel.set_asset_type_whitelist`).
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(), "mock://Home/Documents/Projects",
            )
        widget._on_filter_changed({AssetCategory.USD})
        widget._on_filter_changed(set())
        names = {
            c.name for c in widget._detail_model.get_item_children(None)
        }
        assert names == {"demo.usda", "demo.usdc", "readme.md"}
        widget.destroy()

    def test_search_and_filter_compose_as_and(self, ephemeral_window):
        # Projects/ has demo.usda, demo.usdc, readme.md. "demo" + USD
        # filter → both demo files pass both tests. "demo" + IMAGE
        # filter → nothing matches because no demo-named image exists.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(
                MockBackend(), "mock://Home/Documents/Projects",
            )
        widget._on_search_changed("demo")
        widget._on_filter_changed({AssetCategory.USD})
        names = {
            c.name for c in widget._detail_model.get_item_children(None)
        }
        assert names == {"demo.usda", "demo.usdc"}

        widget._on_filter_changed({AssetCategory.IMAGE})
        names = {
            c.name for c in widget._detail_model.get_item_children(None)
        }
        assert names == set()
        widget.destroy()

    def test_filter_does_not_hide_folders(self, ephemeral_window):
        # Home/ has only sub-folders. An IMAGE whitelist must still
        # show every folder because folders always pass the whitelist.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_filter_changed({AssetCategory.IMAGE})
        names = {
            c.name for c in widget._detail_model.get_item_children(None)
        }
        assert "Documents" in names
        assert "Scripts" in names
        assert "Textures" in names
        widget.destroy()

    def test_search_does_not_filter_nav_pane(self, ephemeral_window):
        # The nav pane is a fixed collection list in Step 42 — the
        # search text filter targets the detail model only, so the
        # collection roots (Bookmarks / My Computer / Recent) stay
        # present regardless of what the user types.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget._on_search_changed("nothing_will_match")
        identifiers = {
            c.identifier for c in widget._navigation_model.collections
        }
        assert identifiers == {"bookmarks", "my-computer", "recent"}
        widget.destroy()

    def test_on_search_changed_after_destroy_is_noop(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        # Must not raise — the detail model ref is None and the
        # handler falls through silently.
        widget._on_search_changed("anything")

    def test_on_filter_changed_after_destroy_is_noop(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        widget._on_filter_changed({AssetCategory.USD})


class TestDestroySearchAndFilter:
    def test_destroy_clears_search_field_reference(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._search_field is None

    def test_destroy_clears_filter_button_reference(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._filter_button is None

    def test_destroy_releases_inner_search_field(self, ephemeral_window):
        # :meth:`SearchField.destroy` nulls its internal field ref, so
        # reading ``text`` after the widget destroy returns the empty-
        # string fallback rather than raising.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        sf = widget._search_field
        widget.destroy()
        assert sf.text == ""

    def test_destroy_releases_inner_filter_button(self, ephemeral_window):
        # :meth:`FilterButton.destroy` nulls its menu + button refs;
        # ``active_categories`` still returns a sensible empty set.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        fb = widget._filter_button
        widget.destroy()
        assert fb.active_categories == set()

    def test_double_destroy_does_not_crash_with_search_and_filter(
        self, ephemeral_window,
    ):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        widget.destroy()
        assert widget._search_field is None
        assert widget._filter_button is None

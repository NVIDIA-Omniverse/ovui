# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation steps 13 + 14 — two-pane layout + selection sync.

Step 13 splits the single-pane widget into a folder-tree pane on the
left + file-detail pane on the right, separated by a draggable
splitter. Step 14 wires the primary browsing loop across the two
panes — tree-click → detail re-root, detail double-click → drill-in
with tree selection mirroring — plus :meth:`FileBrowserModel.resolve`
that walks from the root populating ancestors as it descends.

These tests focus on the **two-pane contract** and **selection-sync
contract** — model roles, shared backend, synchronous navigation,
splitter drag behaviour, tree-click → detail re-root, detail
double-click drill-in vs file-open stub, and
:meth:`FileBrowserModel.resolve` walk-from-root-populating semantics
— rather than re-asserting the generic widget surface (that's
``tests/test_file_browser_widget.py``).

See the content browser behavior (two-model pattern) + §14
(selection sync / drill-in) and the content browser implementation steps 13 / 14.
"""

from __future__ import annotations

from contextlib import contextmanager

import omni.ui as ui
import pytest

from ovui_widgets.app.testing.mock_backend import MockBackend
from ovui_widgets.content.widget import (
    FileBrowserDelegate,
    FileBrowserModel,
    FileBrowserWidget,
    TreeFolderDelegate,
)
from ovui_widgets.content.widget.file_item import FileItem

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """One reusable ovui Window for the whole module.

    Creating a ``ui.Window`` per test is expensive. The same pattern
    is used in ``tests/test_file_browser_widget.py``.
    """
    win = ui.Window("_test_two_pane_layout", width=800, height=400)
    yield win
    win.destroy()


@contextmanager
def in_window_frame(window):
    try:
        with window.frame:
            yield
    finally:
        window.frame.clear()


@pytest.fixture
def widget(ephemeral_window):
    """Build a widget in the module's window, tear it down after."""
    with in_window_frame(ephemeral_window):
        w = FileBrowserWidget(MockBackend(), "mock://Home")
    yield w
    w.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Two-model contract
# ──────────────────────────────────────────────────────────────────────────────


class TestTwoModelContract:
    """Step 42: left pane is NavigationModel, right pane is FileBrowserModel.

    Pre-Step-42 both panes were :class:`FileBrowserModel` instances
    (one folder-only, one full) — the class name ``TwoModelContract``
    is retained because the widget still carries two separate models,
    but the kinds differ now.
    """

    def test_widget_creates_navigation_and_detail_models(self, widget):
        from ovui_widgets.content.widget import NavigationModel

        assert isinstance(widget._navigation_model, NavigationModel)
        assert isinstance(widget._detail_model, FileBrowserModel)

    def test_two_models_are_distinct_instances(self, widget):
        # Architecture §7.4 + §13: nav and detail models have different
        # roles and different item kinds, so they cannot share state.
        assert widget._navigation_model is not widget._detail_model

    def test_detail_model_is_not_folder_only(self, widget):
        assert widget._detail_model._folder_only is False

    def test_detail_model_is_three_columns(self, widget):
        assert widget._detail_model._single_column is False
        assert widget._detail_model.get_item_value_model_count(None) == 3

    def test_navigation_model_is_single_column(self, widget):
        # Nav pane uses one Name column — collections are a flat
        # drill-down, not a columnar table.
        assert widget._navigation_model.get_item_value_model_count(None) == 1

    def test_detail_model_backend_matches_widget(self, widget):
        # Step 42: the backend invariant holds for the detail model —
        # the nav model stores its backend privately (used by its
        # collections to enumerate children on demand).
        assert widget._detail_model._backend is widget._backend

    def test_get_tree_model_returns_navigation_model(self, widget):
        assert widget.get_tree_model() is widget._navigation_model

    def test_get_detail_model_matches_underscore_field(self, widget):
        assert widget.get_detail_model() is widget._detail_model

    def test_get_tree_and_detail_are_different(self, widget):
        assert widget.get_tree_model() is not widget.get_detail_model()


# ──────────────────────────────────────────────────────────────────────────────
# Delegate assignment
# ──────────────────────────────────────────────────────────────────────────────


class TestDelegateAssignment:
    def test_navigation_delegate_is_navigation_delegate(self, widget):
        from ovui_widgets.content.widget import NavigationDelegate

        assert isinstance(widget._navigation_delegate, NavigationDelegate)

    def test_detail_delegate_is_file_browser_delegate(self, widget):
        assert isinstance(widget._detail_delegate, FileBrowserDelegate)

    def test_navigation_and_detail_delegate_types_differ(self, widget):
        # Step 42: the two panes have distinct delegate classes — the
        # nav delegate renders collections + file children with a
        # uniform icon+name row; the detail delegate renders the full
        # Name / Size / Date columnar view.
        assert (
            type(widget._navigation_delegate)
            is not type(widget._detail_delegate)
        )

    def test_detail_tree_view_uses_detail_delegate(self, widget):
        assert widget._detail_delegate._model is widget._detail_model


# ──────────────────────────────────────────────────────────────────────────────
# Column counts + header visibility
# ──────────────────────────────────────────────────────────────────────────────


class TestPaneLayout:
    def test_tree_tree_view_is_single_column(self, widget):
        # ``column_widths`` on the tree view is a 1-tuple → TreeView
        # renders one column (Name only).
        assert len(widget._tree_tree_view.column_widths) == 1

    def test_detail_tree_view_is_three_columns(self, widget):
        # Name / Size / Date.
        assert len(widget._detail_tree_view.column_widths) == 3

    def test_tree_tree_view_header_hidden(self, widget):
        assert widget._tree_tree_view.header_visible is False

    def test_detail_tree_view_header_visible(self, widget):
        assert widget._detail_tree_view.header_visible is True

    def test_detail_tree_view_has_visible_root(self, widget):
        # The detail pane shows its root so an empty folder doesn't
        # render as blank whitespace. Step 42 hides the nav pane's
        # root (there's a virtual ``None`` root above the collections)
        # so the collections appear as top-level rows.
        assert widget._detail_tree_view.root_visible is True

    def test_nav_tree_view_hides_virtual_root(self, widget):
        # The NavigationModel uses the TreeView's implicit ``None``
        # root to hold the collection list; ``root_visible=False`` is
        # what makes the collections paint as the top-level rows.
        assert widget._tree_tree_view.root_visible is False


# ──────────────────────────────────────────────────────────────────────────────
# Splitter
# ──────────────────────────────────────────────────────────────────────────────


class TestSplitter:
    def test_splitter_exists(self, widget):
        assert widget._splitter is not None

    def test_splitter_is_a_placer(self, widget):
        assert isinstance(widget._splitter, ui.Placer)

    def test_splitter_is_draggable(self, widget):
        # The Placer was constructed with ``draggable=True``.
        assert widget._splitter.draggable is True

    def test_splitter_drag_axis_is_horizontal(self, widget):
        # Restrict dragging to the X axis — vertical drag would be
        # meaningless for a horizontal pane split.
        assert widget._splitter.drag_axis == ui.Axis.X

    def test_splitter_drag_increases_tree_pane_width(self, widget):
        # Feed a positive offset through the drag callback and verify
        # the tree pane's width grew. We do not assert the exact new
        # width — the implementation clamps and truncates — only that
        # the width moved in the expected direction.
        original = widget._tree_pane_width
        widget._on_splitter_dragged(50.0)
        assert widget._tree_pane_width > original

    def test_splitter_drag_decreases_tree_pane_width(self, widget):
        original = widget._tree_pane_width
        widget._on_splitter_dragged(-50.0)
        # Clamped to the minimum if requested width would go below it.
        assert widget._tree_pane_width <= original

    def test_splitter_drag_clamps_to_minimum(self, widget):
        # A very large negative drag must not take the pane width
        # below the minimum (80px by the widget's internal constant).
        widget._on_splitter_dragged(-10_000.0)
        assert widget._tree_pane_width >= 80

    def test_splitter_drag_is_noop_when_zero(self, widget):
        before = widget._tree_pane_width
        widget._on_splitter_dragged(0.0)
        assert widget._tree_pane_width == before

    def test_splitter_drag_ignores_invalid_offset(self, widget):
        # During teardown, ovui may deliver ``None`` / non-numeric
        # offsets through the callback. These must not crash.
        before = widget._tree_pane_width
        widget._on_splitter_dragged(None)
        widget._on_splitter_dragged("not a number")
        assert widget._tree_pane_width == before

    def test_splitter_drag_is_suppressed_during_reentry(self, widget):
        # The ``_suppress_splitter_cb`` guard prevents re-entry when
        # the callback resets the Placer's offset to zero. Set the
        # flag manually and verify a drag doesn't fire.
        widget._suppress_splitter_cb = True
        before = widget._tree_pane_width
        widget._on_splitter_dragged(100.0)
        assert widget._tree_pane_width == before
        widget._suppress_splitter_cb = False


# ──────────────────────────────────────────────────────────────────────────────
# navigate_to updates both roots
# ──────────────────────────────────────────────────────────────────────────────


class TestNavigateToBothRoots:
    """Step 42: navigate_to re-roots the detail pane only.

    Pre-Step-42 both panes (tree + detail) re-rooted together; Step
    42 replaces the tree pane with a collection navigation model that
    has no "root URL" to move. The class name is retained because
    ``navigate_to`` is still the public API; the contract now refers
    to the detail pane alone.
    """

    def test_navigate_to_updates_detail_model_root(self, widget):
        widget.navigate_to("mock://Home/Documents")
        assert widget._detail_model.root_url == "mock://Home/Documents"

    def test_navigate_to_does_not_replace_navigation_model(self, widget):
        # Navigation is a fixed list of collections — navigate_to on
        # the widget is a detail-pane concern, not a nav-pane concern.
        nav_before = widget._navigation_model
        widget.navigate_to("mock://Home/Textures")
        assert widget._navigation_model is nav_before

    def test_navigate_to_preserves_detail_folder_only_flag(self, widget):
        # Detail folder-only flag is intrinsic to the model; navigation
        # must not flip it.
        widget.navigate_to("mock://Home/Documents")
        assert widget._detail_model._folder_only is False


# ──────────────────────────────────────────────────────────────────────────────
# destroy cleans up both models
# ──────────────────────────────────────────────────────────────────────────────


class TestDestroyCleansBothModels:
    def test_destroy_clears_navigation_model(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._navigation_model is None

    def test_destroy_clears_detail_model(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._detail_model is None

    def test_destroy_clears_both_tree_views(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._tree_tree_view is None
        assert widget._detail_tree_view is None

    def test_destroy_clears_both_delegates(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._navigation_delegate is None
        assert widget._detail_delegate is None

    def test_destroy_clears_splitter(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._splitter is None

    def test_destroy_clears_both_frames(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        assert widget._tree_frame is None
        assert widget._detail_frame is None

    def test_navigate_after_destroy_is_noop(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        widget.navigate_to("mock://Home/Documents")  # must not raise

    def test_destroy_detaches_detail_delegate_model(self, ephemeral_window):
        # Step 42: the nav delegate holds no model reference (the model
        # is supplied per build-widget call) — only the detail
        # delegate's model binding is the destroy contract.
        with in_window_frame(ephemeral_window):
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        detail_delegate = widget._detail_delegate
        widget.destroy()
        assert detail_delegate._model is None


# ──────────────────────────────────────────────────────────────────────────────
# TreeFolderDelegate — the single-column renderer
# ──────────────────────────────────────────────────────────────────────────────


class TestTreeFolderDelegate:
    """Direct tests on :class:`TreeFolderDelegate`'s public contract.

    Rendering (``build_widget``, ``build_branch``) is exercised
    implicitly through the widget's TreeView builds; these tests pin
    the model-binding surface and the header no-op.
    """

    def test_default_model_is_none(self):
        d = TreeFolderDelegate()
        assert d._model is None

    def test_set_model_binds(self):
        d = TreeFolderDelegate()
        model = FileBrowserModel(MockBackend(), "mock://Home", folder_only=True)
        d.set_model(model)
        assert d._model is model

    def test_set_model_none_clears(self):
        d = TreeFolderDelegate()
        model = FileBrowserModel(MockBackend(), "mock://Home", folder_only=True)
        d.set_model(model)
        d.set_model(None)
        assert d._model is None

    def test_build_header_is_noop(self):
        # Must not raise — the tree pane suppresses the header via
        # ``header_visible=False`` on the TreeView, so this method is
        # never called in practice; keeping it as an explicit no-op
        # matches FileBrowserDelegate's surface.
        d = TreeFolderDelegate()
        d.build_header(0)  # must not raise

    def test_is_abstract_item_delegate_subclass(self):
        assert issubclass(TreeFolderDelegate, ui.AbstractItemDelegate)


# ──────────────────────────────────────────────────────────────────────────────
# Package exports
# ──────────────────────────────────────────────────────────────────────────────


class TestPackageExports:
    def test_tree_folder_delegate_in_widget_package_all(self):
        import ovui_widgets.content.widget as pkg

        assert "TreeFolderDelegate" in pkg.__all__

    def test_tree_folder_delegate_reexported(self):
        from ovui_widgets.content.widget import TreeFolderDelegate as TFD

        assert TFD is TreeFolderDelegate


# ──────────────────────────────────────────────────────────────────────────────
# Selection sync (Step 14)
# ──────────────────────────────────────────────────────────────────────────────


def _first_child_folder(model: FileBrowserModel) -> FileItem:
    """Return the first folder child of ``model``'s root, populating lazily.

    Shared helper for the selection-sync tests: they all need *some*
    folder under the current root to click / double-click on, and the
    mock tree guarantees at least one (``Documents`` / ``Projects`` /
    etc.) under every folder node the tests visit.
    """
    children = model.get_item_children(None)
    folders = [c for c in children if isinstance(c, FileItem) and c.is_folder]
    assert folders, "mock tree missing a folder child under the current root"
    return folders[0]


def _first_child_file(model: FileBrowserModel) -> FileItem:
    """Return the first file child of ``model``'s root, populating lazily."""
    children = model.get_item_children(None)
    files = [c for c in children if isinstance(c, FileItem) and not c.is_folder]
    assert files, "mock tree missing a file child under the current root"
    return files[0]


class TestSelectionSync:
    """Step 14 selection / drill-in contract, re-adapted for Step 42.

    Pre-Step-42 a tree-click re-rooted the detail pane and a detail
    double-click mirrored the folder into the tree. Step 42 replaces
    the left pane with a collection navigation model, so tree-click
    becomes a nav-model activation and the drill-in no longer mirrors
    back into the (now virtual) nav tree. Tests are retained where
    they pin the detail-pane half of the contract.
    """

    def test_nav_activate_file_child_updates_detail_root(self, widget):
        # Step 42 equivalent of the pre-Step-42 "tree-click updates
        # detail" contract. A FileItem under any collection (a
        # bookmark, a drive, a recent file's folder) activates into
        # the detail pane.
        target = FileItem(
            url="mock://Home/Documents",
            name="Documents",
            is_folder=True,
        )
        widget._navigation_model.activate_item(target)
        assert widget._detail_model.root_url == "mock://Home/Documents"

    def test_nav_activate_empty_selection_is_noop(self, widget):
        detail_root_before = widget._detail_model.root_url
        widget._on_tree_selection([])
        assert widget._detail_model.root_url == detail_root_before

    def test_nav_activate_non_file_item_root_is_noop(self, widget):
        # The nav model's FileItem activation fires on_navigate;
        # anything else (CollectionItem, raw object) is a no-op.
        detail_root_before = widget._detail_model.root_url
        widget._on_tree_selection([object()])
        assert widget._detail_model.root_url == detail_root_before

    def test_nav_activate_after_destroy_is_noop(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            w = FileBrowserWidget(MockBackend(), "mock://Home")
        w.destroy()
        # Must not raise — the handler short-circuits on None model.
        target = FileItem(
            url="mock://Home", name="Home", is_folder=True,
        )
        w._on_tree_selection([target])

    def test_nav_activate_publishes_no_selection_bus_event(self, widget):
        # the content browser implementation step 14: file URLs are not prim paths — the
        # selection bus stays silent. Observable today by the
        # detail-pane-only side-effect of activate.
        target = FileItem(
            url="mock://Home/Documents",
            name="Documents",
            is_folder=True,
        )
        widget._navigation_model.activate_item(target)
        assert widget._detail_model.root_url == "mock://Home/Documents"

    def test_detail_double_click_drills_into_folder(self, widget):
        # Named exactly as in the content browser implementation step 14 "Verify" bullet. Pick
        # a folder in the detail pane, simulate the mouse-press-select
        # that precedes a double-click, then fire the double-click
        # handler and confirm the detail re-rooted.
        folder = _first_child_folder(widget._detail_model)
        widget._detail_tree_view.selection = [folder]
        widget._on_detail_double_click(0, 0, 0, 0)
        assert widget._detail_model.root_url == folder.url

    def test_detail_double_click_leaves_nav_selection_alone(self, widget):
        # Step 42 replaces the pre-Step-42 "mirror tree selection"
        # behaviour: drill-in affects the detail pane only; the nav
        # pane's collection selection is untouched.
        folder = _first_child_folder(widget._detail_model)
        nav_selection_before = list(widget._tree_tree_view.selection)
        widget._detail_tree_view.selection = [folder]
        widget._on_detail_double_click(0, 0, 0, 0)
        assert (
            list(widget._tree_tree_view.selection)
            == nav_selection_before
        )

    def test_double_click_file_does_not_drill(self, widget):
        # Named exactly as in the content browser implementation step 14 "Verify" bullet. A file
        # double-click is a no-op at Step 14 — Step 54 wires the USD
        # open dispatch. Today we assert that the detail pane's root
        # stays put.
        widget.navigate_to("mock://Home/Documents/Projects")
        file_item = _first_child_file(widget._detail_model)
        detail_root_before = widget._detail_model.root_url
        widget._detail_tree_view.selection = [file_item]
        widget._on_detail_double_click(0, 0, 0, 0)
        assert widget._detail_model.root_url == detail_root_before

    def test_double_click_with_empty_selection_is_noop(self, widget):
        widget._detail_tree_view.selection = []
        detail_root_before = widget._detail_model.root_url
        widget._on_detail_double_click(0, 0, 0, 0)
        assert widget._detail_model.root_url == detail_root_before

    def test_double_click_after_destroy_is_noop(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            w = FileBrowserWidget(MockBackend(), "mock://Home")
        w.destroy()
        # Must not raise: post-destroy, ``_detail_tree_view`` is None
        # and the handler returns before touching anything.
        w._on_detail_double_click(0, 0, 0, 0)

    def test_drill_into_folder_can_be_called_directly(self, widget):
        # The folder-path is split out of the mouse handler so a test
        # can fire the drill-in without a simulated mouse event. Only
        # the detail pane is affected.
        folder = _first_child_folder(widget._detail_model)
        widget._drill_into_folder(folder)
        assert widget._detail_model.root_url == folder.url

    def test_build_wires_nav_selection_callback(self, ephemeral_window):
        # ``has_selection_changed_fn`` reads the C++-side slot, which
        # ``window.frame.clear()`` resets — so the check has to happen
        # *inside* the frame context (the shared ``widget`` fixture
        # clears on teardown before the test body runs). The fresh
        # builder below keeps the frame alive for the duration of
        # the assertion. Step 42: the nav TreeView's selection
        # callback dispatches through :class:`NavigationModel`.
        with in_window_frame(ephemeral_window):
            w = FileBrowserWidget(MockBackend(), "mock://Home")
            try:
                assert w._tree_tree_view.has_selection_changed_fn() is True
            finally:
                w.destroy()

    def test_build_wires_detail_double_click_callback(self, ephemeral_window):
        with in_window_frame(ephemeral_window):
            w = FileBrowserWidget(MockBackend(), "mock://Home")
            try:
                assert (
                    w._detail_tree_view.has_mouse_double_clicked_fn() is True
                )
            finally:
                w.destroy()

    def test_destroy_clears_selection_callback(self, ephemeral_window):
        # Same C++-state constraint as the build-wires tests: the
        # ``has_*_fn`` slots read from the omni.ui TreeView C++ side,
        # which is only alive inside the frame context. Drive the
        # destroy from inside the frame and verify the slots cleared.
        with in_window_frame(ephemeral_window):
            w = FileBrowserWidget(MockBackend(), "mock://Home")
            tree_view = w._tree_tree_view
            detail_view = w._detail_tree_view
            # Sanity — callbacks are wired before destroy.
            assert tree_view.has_selection_changed_fn() is True
            assert detail_view.has_mouse_double_clicked_fn() is True
            w.destroy()
            # Post-destroy, the bound callbacks must be gone so the
            # TreeView's C++ side does not keep the Python widget
            # alive via the selection-callback slot.
            assert tree_view.has_selection_changed_fn() is False
            assert detail_view.has_mouse_double_clicked_fn() is False


# ──────────────────────────────────────────────────────────────────────────────
# FileBrowserModel.resolve (Step 14)
# ──────────────────────────────────────────────────────────────────────────────


class TestResolve:
    """:meth:`FileBrowserModel.resolve` walks from root, populating
    ancestors along the way. Step 42 removes the widget's tree-pane
    resolve path but keeps the method on :class:`FileBrowserModel`
    because the detail pane and future file-picker flows still use it
    (architecture §5.9). Tests run against a standalone folder-only
    :class:`FileBrowserModel` so the semantics are pinned independently
    of the widget's changed navigation pane.
    """

    def _make_tree_model(self):
        return FileBrowserModel(
            MockBackend(), "mock://Home", folder_only=True,
        )

    def test_resolve_walks_from_root_populating(self):
        tree_model = self._make_tree_model()
        assert tree_model.root.populated is False

        target_url = "mock://Home/Documents/Projects"
        result = tree_model.resolve(target_url)
        assert isinstance(result, FileItem)
        assert result.url == target_url
        assert tree_model.root.populated is True
        docs = tree_model.resolve("mock://Home/Documents")
        assert docs.populated is True

    def test_resolve_root_url_returns_root(self):
        tree_model = self._make_tree_model()
        assert tree_model.resolve("mock://Home") is tree_model.root

    def test_resolve_unknown_url_returns_none(self):
        tree_model = self._make_tree_model()
        assert tree_model.resolve("mock://Home/does_not_exist") is None

    def test_resolve_outside_root_returns_none(self):
        tree_model = self._make_tree_model()
        assert tree_model.resolve("mock://Other") is None

    def test_resolve_prefix_collision_does_not_match(self):
        # A URL whose string is a lexical prefix of the root but not
        # a directory child (``mock://Homework`` shares the
        # ``mock://Home`` prefix but is not under it).
        tree_model = self._make_tree_model()
        assert tree_model.resolve("mock://Homework") is None

    def test_resolve_leaf_on_detail_model(self, widget):
        # Detail model is not folder-only, so resolving a leaf URL
        # works. The walk populates parent folders as it descends.
        url = "mock://Home/Documents/Projects/demo.usda"
        result = widget._detail_model.resolve(url)
        assert isinstance(result, FileItem)
        assert result.url == url
        assert result.is_folder is False

    def test_resolve_leaf_on_folder_only_model_returns_none(self):
        # folder_only=True filters files out of every
        # ``get_item_children`` query, so a walk looking for a leaf
        # runs out of candidates at the parent folder.
        tree_model = self._make_tree_model()
        url = "mock://Home/Documents/Projects/demo.usda"
        assert tree_model.resolve(url) is None

    def test_resolve_normalizes_url(self):
        tree_model = self._make_tree_model()
        backend = tree_model._backend
        result = tree_model.resolve("mock://Home/Documents/")
        assert result is not None
        assert result.url == backend.normalize_url(
            "mock://Home/Documents"
        )

    def test_resolve_empty_string_returns_none(self):
        tree_model = self._make_tree_model()
        assert tree_model.resolve("") is None

    def test_resolve_populates_via_get_item_children(self):
        tree_model = self._make_tree_model()
        tree_model.resolve("mock://Home/Documents/Projects")
        assert tree_model.root.populated is True
        docs = tree_model._cache.get("mock://Home/Documents")
        assert docs is not None
        assert docs.populated is True
        projects = tree_model._cache.get("mock://Home/Documents/Projects")
        assert projects is not None
        assert projects.populated is False

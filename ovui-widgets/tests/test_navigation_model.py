# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 42 — NavigationModel + CollectionItem.

See the content browser behavior and the content browser implementation step 42. The
navigation pane is driven by :class:`NavigationModel`, which holds a
fixed list of :class:`CollectionItem` roots (Bookmarks, My Computer,
Recent) and dispatches tree queries through them. Clicking a
collection root is a no-op; clicking a :class:`FileItem` child fires
the model's ``on_navigate`` callback so the hosting widget can
re-root the detail pane.

These tests focus on the **nav-model contract** — collection roots,
child enumeration, activation dispatch, navigation callback — rather
than the widget integration (that lives in
``tests/test_two_pane_layout.py`` and ``tests/test_file_browser_widget.py``).
"""

from __future__ import annotations

from typing import List

import omni.ui as ui
import pytest

from ovui_widgets.app.testing.mock_backend import MockBackend
from ovui_widgets.content.widget import (
    BookmarksCollection,
    CollectionItem,
    MyComputerCollection,
    NavigationDelegate,
    NavigationModel,
    RecentFilesCollection,
)
from ovui_widgets.content.widget.file_item import FileItem

# ──────────────────────────────────────────────────────────────────────────────
# Test helper — a collection whose children are explicit
# ──────────────────────────────────────────────────────────────────────────────


class _StubCollection(CollectionItem):
    """CollectionItem that returns a fixed list of FileItem children.

    The real collections (Bookmarks / My Computer / Recent) are stubs in
    Step 42 so they all return ``[]``. Several tests want to assert
    activation on an actual :class:`FileItem` child; this helper gives
    them a collection with deterministic children without needing the
    Step 43 / 44 / 46 implementations.
    """

    def __init__(self, children: List[FileItem]) -> None:
        super().__init__(
            identifier="stub",
            title="Stub Collection",
            icon_key="content_home",
        )
        self._children = list(children)

    def get_children(self, backend) -> List[FileItem]:
        return list(self._children)


# ──────────────────────────────────────────────────────────────────────────────
# CollectionItem surface
# ──────────────────────────────────────────────────────────────────────────────


class TestCollectionItemSurface:
    def test_is_abstract_item_subclass(self):
        assert issubclass(CollectionItem, ui.AbstractItem)

    def test_constructor_sets_identifier(self):
        stub = _StubCollection([])
        assert stub.identifier == "stub"

    def test_constructor_sets_title(self):
        stub = _StubCollection([])
        assert stub.title == "Stub Collection"

    def test_constructor_sets_icon_key(self):
        stub = _StubCollection([])
        assert stub.icon_key == "content_home"

    def test_name_aliases_title(self):
        # NavigationDelegate treats collection roots and FileItem
        # children uniformly via a ``.name`` read — the alias keeps the
        # single-path render contract intact.
        stub = _StubCollection([])
        assert stub.name == stub.title

    def test_is_folder_is_true(self):
        # Collections are always expandable; the TreeView branch-arrow
        # path reads this to draw the chevron.
        stub = _StubCollection([])
        assert stub.is_folder is True

    def test_get_name_model_returns_simple_string_model(self):
        stub = _StubCollection([])
        model = stub.get_name_model()
        assert isinstance(model, ui.SimpleStringModel)
        assert model.as_string == "Stub Collection"

    def test_get_name_model_is_cached(self):
        # Lazy value-model allocation — subsequent reads return the
        # same instance so the delegate's label stays bound to one model.
        stub = _StubCollection([])
        first = stub.get_name_model()
        second = stub.get_name_model()
        assert first is second

    def test_base_get_children_returns_empty_list(self):
        # Default implementation so a subclass whose ``get_children``
        # has not been fleshed out yet still returns a sane value.
        base = CollectionItem("id", "Title", "content_home")
        assert base.get_children(MockBackend()) == []


# ──────────────────────────────────────────────────────────────────────────────
# Default collection list
# ──────────────────────────────────────────────────────────────────────────────


class TestDefaultCollections:
    def test_default_constructor_has_three_collections(self):
        model = NavigationModel(MockBackend())
        assert len(model.collections) == 3

    def test_default_collection_order_is_bookmarks_computer_recent(self):
        # Order matches the content browser behavior's intended
        # default: Bookmarks at the top (user-curated shortcuts),
        # My Computer in the middle (drives), Recent at the bottom
        # (time-sorted history).
        model = NavigationModel(MockBackend())
        identifiers = [c.identifier for c in model.collections]
        assert identifiers == ["bookmarks", "my-computer", "recent"]

    def test_bookmarks_collection_title(self):
        model = NavigationModel(MockBackend())
        bookmarks = model.find_collection("bookmarks")
        assert bookmarks is not None
        assert bookmarks.title == "Bookmarks"

    def test_my_computer_collection_title(self):
        model = NavigationModel(MockBackend())
        computer = model.find_collection("my-computer")
        assert computer is not None
        assert computer.title == "My Computer"

    def test_recent_collection_title(self):
        model = NavigationModel(MockBackend())
        recent = model.find_collection("recent")
        assert recent is not None
        assert recent.title == "Recent"

    def test_collections_are_correct_types(self):
        model = NavigationModel(MockBackend())
        assert isinstance(
            model.find_collection("bookmarks"), BookmarksCollection,
        )
        assert isinstance(
            model.find_collection("my-computer"), MyComputerCollection,
        )
        assert isinstance(
            model.find_collection("recent"), RecentFilesCollection,
        )

    def test_default_collections_have_icon_keys(self):
        # Every default collection needs an icon so the nav pane's
        # delegate has something to render. The exact key is a style
        # decision and may rebrand later — the non-empty invariant is
        # what matters for the render path.
        model = NavigationModel(MockBackend())
        for collection in model.collections:
            assert collection.icon_key
            assert isinstance(collection.icon_key, str)

    def test_find_collection_returns_none_for_unknown(self):
        model = NavigationModel(MockBackend())
        assert model.find_collection("does-not-exist") is None

    def test_collections_returns_fresh_list(self):
        # The property returns a copy — mutating the returned list
        # must not change the model's internal state.
        model = NavigationModel(MockBackend())
        copy = model.collections
        copy.clear()
        assert len(model.collections) == 3

    def test_custom_collections_override_defaults(self):
        # Callers can pass their own collection list (e.g. tests /
        # file-picker dialogs that want a different surface).
        custom = _StubCollection([])
        model = NavigationModel(MockBackend(), collections=[custom])
        assert model.collections == [custom]


# ──────────────────────────────────────────────────────────────────────────────
# Tree-model surface
# ──────────────────────────────────────────────────────────────────────────────


class TestAbstractItemModelSurface:
    def test_is_abstract_item_model_subclass(self):
        assert issubclass(NavigationModel, ui.AbstractItemModel)

    def test_get_item_children_none_returns_collections(self):
        model = NavigationModel(MockBackend())
        children = model.get_item_children(None)
        assert children == model.collections

    def test_get_item_children_none_returns_fresh_list(self):
        # Mutating the returned list cannot mutate the collection order.
        model = NavigationModel(MockBackend())
        children = model.get_item_children(None)
        children.clear()
        assert len(model.get_item_children(None)) == 3

    def test_get_item_children_of_collection_dispatches_to_get_children(self):
        child = FileItem(
            url="mock://Home/Documents",
            name="Documents",
            is_folder=True,
        )
        stub = _StubCollection([child])
        model = NavigationModel(MockBackend(), collections=[stub])
        children = model.get_item_children(stub)
        assert children == [child]

    def test_get_item_children_of_stub_collection_returns_empty(self):
        # Bookmarks and Recent are still stubs (Steps 44 / 46 flesh
        # them out). My Computer shipped in Step 43 and enumerates
        # real mount points / user folders, so it's excluded from
        # this assertion — its children live under test_my_computer.py.
        model = NavigationModel(MockBackend())
        for collection in model.collections:
            if collection.identifier == "my-computer":
                continue
            assert model.get_item_children(collection) == []

    def test_get_item_children_of_file_item_folder_populates_on_demand(self):
        # Bug 1 fix: collections hand back FileItem instances with
        # ``_populated=False`` and empty ``_children``. The nav model
        # must populate on demand so subfolders appear when the user
        # expands a collection child at any depth.
        folder = FileItem(
            url="mock://Home",
            name="Home",
            is_folder=True,
        )
        model = NavigationModel(MockBackend())
        children = model.get_item_children(folder)
        # MockBackend's Home/ contains Documents, Textures, Scripts,
        # .hidden_folder — all folders, no files.
        assert {c.name for c in children} == {
            "Documents", "Textures", "Scripts", ".hidden_folder",
        }
        assert folder.populated is True

    def test_get_item_children_of_file_leaf_returns_empty(self):
        leaf = FileItem(
            url="mock://Home/readme.md",
            name="readme.md",
            is_folder=False,
        )
        model = NavigationModel(MockBackend())
        assert model.get_item_children(leaf) == []

    def test_get_item_children_filters_files_out(self):
        # Bug 1 — the nav pane is folder-only. Populating
        # mock://Home/Documents/Projects yields demo.usda, demo.usdc,
        # readme.md (all files) — the nav model must return ``[]`` so
        # the nav pane never shows files.
        projects = FileItem(
            url="mock://Home/Documents/Projects",
            name="Projects",
            is_folder=True,
        )
        model = NavigationModel(MockBackend())
        assert model.get_item_children(projects) == []
        # Populate did run — verifies the filter, not a "populate never
        # fired" false-pass.
        assert projects.populated is True

    def test_get_item_children_mixed_returns_only_folders(self):
        # Documents holds one folder child (Projects); no files. The
        # filter keeps Projects and nothing else regardless of what
        # populate pulls in.
        documents = FileItem(
            url="mock://Home/Documents",
            name="Documents",
            is_folder=True,
        )
        model = NavigationModel(MockBackend())
        children = model.get_item_children(documents)
        assert [c.name for c in children] == ["Projects"]
        assert all(c.is_folder for c in children)

    def test_get_item_children_works_three_levels_deep(self):
        # Bug 1 — the original code only let level-1 folders expand.
        # Here we drive the fix three levels: Home → Documents →
        # Projects (a leaf folder with only file children).
        home = FileItem(url="mock://Home", name="Home", is_folder=True)
        model = NavigationModel(MockBackend())

        level2 = model.get_item_children(home)
        documents = next(c for c in level2 if c.name == "Documents")

        level3 = model.get_item_children(documents)
        projects = next(c for c in level3 if c.name == "Projects")

        level4 = model.get_item_children(projects)
        # Projects has only files — nav pane drops them all.
        assert level4 == []
        assert projects.populated is True

    def test_get_item_children_populate_is_idempotent(self):
        # TreeView calls ``get_item_children`` repeatedly across frames;
        # the populate short-circuit inside :class:`FileItem` means the
        # backend is hit exactly once, not on every repaint.
        home = FileItem(url="mock://Home", name="Home", is_folder=True)
        backend = MockBackend()

        call_count = {"list_dir": 0}
        original = backend.list_dir

        def _counting_list_dir(url: str):
            call_count["list_dir"] += 1
            return original(url)

        backend.list_dir = _counting_list_dir  # type: ignore[method-assign]

        model = NavigationModel(backend)
        first = model.get_item_children(home)
        second = model.get_item_children(home)
        assert first == second
        # Home was populated once; the second call must not re-enter
        # ``list_dir``.
        assert call_count["list_dir"] == 1

    def test_can_item_have_children_collection_is_true(self):
        model = NavigationModel(MockBackend())
        for collection in model.collections:
            assert model.can_item_have_children(collection) is True

    def test_can_item_have_children_folder_file_item_is_true(self):
        folder = FileItem(
            url="mock://Home", name="Home", is_folder=True,
        )
        model = NavigationModel(MockBackend())
        assert model.can_item_have_children(folder) is True

    def test_can_item_have_children_leaf_file_item_is_false(self):
        leaf = FileItem(
            url="mock://Home/readme.md", name="readme.md", is_folder=False,
        )
        model = NavigationModel(MockBackend())
        assert model.can_item_have_children(leaf) is False

    def test_get_item_value_model_count_is_one(self):
        # Single Name column per the content browser behavior
        model = NavigationModel(MockBackend())
        assert model.get_item_value_model_count(None) == 1

    def test_get_item_value_model_for_collection(self):
        model = NavigationModel(MockBackend())
        bookmarks = model.find_collection("bookmarks")
        assert bookmarks is not None
        value_model = model.get_item_value_model(bookmarks, 0)
        assert value_model is not None
        assert value_model.as_string == "Bookmarks"

    def test_get_item_value_model_for_file_item(self):
        leaf = FileItem(
            url="mock://Home/readme.md", name="readme.md", is_folder=False,
        )
        model = NavigationModel(MockBackend())
        value_model = model.get_item_value_model(leaf, 0)
        assert value_model is not None
        assert value_model.as_string == "readme.md"

    def test_get_item_value_model_unknown_column_is_none(self):
        # Nav pane is single-column; column_id >= 1 must not crash.
        model = NavigationModel(MockBackend())
        bookmarks = model.find_collection("bookmarks")
        assert model.get_item_value_model(bookmarks, 1) is None
        assert model.get_item_value_model(bookmarks, 99) is None


# ──────────────────────────────────────────────────────────────────────────────
# Activation / navigation callback
# ──────────────────────────────────────────────────────────────────────────────


class TestActivation:
    def test_activate_item_none_is_noop(self):
        model = NavigationModel(MockBackend())
        navigated: List[str] = []
        model.set_on_navigate(navigated.append)
        model.activate_item(None)
        assert navigated == []

    def test_activate_collection_root_is_noop(self):
        # Clicking a collection root (Bookmarks / My Computer / Recent)
        # expands the row but does NOT navigate the detail pane.
        model = NavigationModel(MockBackend())
        navigated: List[str] = []
        model.set_on_navigate(navigated.append)
        for collection in model.collections:
            model.activate_item(collection)
        assert navigated == []

    def test_activate_file_item_child_fires_callback(self):
        folder = FileItem(
            url="mock://Home/Documents",
            name="Documents",
            is_folder=True,
        )
        stub = _StubCollection([folder])
        model = NavigationModel(MockBackend(), collections=[stub])
        navigated: List[str] = []
        model.set_on_navigate(navigated.append)
        model.activate_item(folder)
        assert navigated == ["mock://Home/Documents"]

    def test_activate_file_item_leaf_also_fires_callback(self):
        # Step 46's Recent collection has file children — clicking one
        # should also navigate so the detail pane opens on the file's
        # URL (Step 54 will turn this into an actual file-open).
        leaf = FileItem(
            url="mock://Home/Documents/Projects/demo.usda",
            name="demo.usda",
            is_folder=False,
        )
        stub = _StubCollection([leaf])
        model = NavigationModel(MockBackend(), collections=[stub])
        navigated: List[str] = []
        model.set_on_navigate(navigated.append)
        model.activate_item(leaf)
        assert navigated == ["mock://Home/Documents/Projects/demo.usda"]

    def test_activate_without_callback_set_is_noop(self):
        # ``set_on_navigate`` was never called — activate must not
        # crash on the missing callback slot.
        folder = FileItem(
            url="mock://Home", name="Home", is_folder=True,
        )
        stub = _StubCollection([folder])
        model = NavigationModel(MockBackend(), collections=[stub])
        model.activate_item(folder)  # no raise

    def test_set_on_navigate_none_clears_callback(self):
        folder = FileItem(
            url="mock://Home", name="Home", is_folder=True,
        )
        stub = _StubCollection([folder])
        model = NavigationModel(MockBackend(), collections=[stub])
        navigated: List[str] = []
        model.set_on_navigate(navigated.append)
        model.set_on_navigate(None)
        model.activate_item(folder)
        assert navigated == []

    def test_set_on_navigate_replaces_previous_callback(self):
        folder = FileItem(
            url="mock://Home", name="Home", is_folder=True,
        )
        stub = _StubCollection([folder])
        model = NavigationModel(MockBackend(), collections=[stub])
        first: List[str] = []
        second: List[str] = []
        model.set_on_navigate(first.append)
        model.set_on_navigate(second.append)
        model.activate_item(folder)
        assert first == []
        assert second == ["mock://Home"]


# ──────────────────────────────────────────────────────────────────────────────
# NavigationDelegate surface
# ──────────────────────────────────────────────────────────────────────────────


class TestNavigationDelegateSurface:
    def test_is_abstract_item_delegate_subclass(self):
        assert issubclass(NavigationDelegate, ui.AbstractItemDelegate)

    def test_instantiates(self):
        # The delegate is stateless — no constructor args and no
        # references into the hosting widget.
        delegate = NavigationDelegate()
        assert delegate is not None

    def test_build_header_is_no_op(self):
        # The nav TreeView hides its header; the delegate's header
        # builder exists only for API parity.
        delegate = NavigationDelegate()
        # Calling does not raise.
        delegate.build_header(0)


# ──────────────────────────────────────────────────────────────────────────────
# Widget integration
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ephemeral_window():
    """Single reusable ovui Window for the integration tests."""
    win = ui.Window("_test_navigation_model", width=400, height=300)
    yield win
    win.destroy()


class TestWidgetIntegration:
    def test_widget_uses_navigation_model_for_left_pane(self, ephemeral_window):
        from ovui_widgets.content.widget import FileBrowserWidget

        with ephemeral_window.frame:
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        try:
            assert isinstance(widget._navigation_model, NavigationModel)
        finally:
            widget.destroy()
            ephemeral_window.frame.clear()

    def test_widget_uses_navigation_delegate_for_left_pane(
        self, ephemeral_window,
    ):
        from ovui_widgets.content.widget import FileBrowserWidget

        with ephemeral_window.frame:
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        try:
            assert isinstance(
                widget._navigation_delegate, NavigationDelegate,
            )
        finally:
            widget.destroy()
            ephemeral_window.frame.clear()

    def test_widget_nav_model_has_three_collections(self, ephemeral_window):
        from ovui_widgets.content.widget import FileBrowserWidget

        with ephemeral_window.frame:
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        try:
            assert len(widget._navigation_model.collections) == 3
        finally:
            widget.destroy()
            ephemeral_window.frame.clear()

    def test_widget_tree_tree_view_model_is_navigation_model(
        self, ephemeral_window,
    ):
        from ovui_widgets.content.widget import FileBrowserWidget

        with ephemeral_window.frame:
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        try:
            assert widget._tree_tree_view.model is widget._navigation_model
        finally:
            widget.destroy()
            ephemeral_window.frame.clear()

    def test_nav_activation_reroots_detail(self, ephemeral_window):
        # End-to-end: a FileItem activation through the nav model's
        # callback path re-roots the widget's detail model.
        from ovui_widgets.content.widget import FileBrowserWidget

        with ephemeral_window.frame:
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        try:
            target = FileItem(
                url="mock://Home/Documents",
                name="Documents",
                is_folder=True,
            )
            widget._navigation_model.activate_item(target)
            assert (
                widget._detail_model.root_url == "mock://Home/Documents"
            )
        finally:
            widget.destroy()
            ephemeral_window.frame.clear()

    def test_nav_collection_root_click_does_not_reroot_detail(
        self, ephemeral_window,
    ):
        from ovui_widgets.content.widget import FileBrowserWidget

        with ephemeral_window.frame:
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        try:
            before = widget._detail_model.root_url
            for collection in widget._navigation_model.collections:
                widget._navigation_model.activate_item(collection)
            assert widget._detail_model.root_url == before
        finally:
            widget.destroy()
            ephemeral_window.frame.clear()

    def test_destroy_clears_navigation_model(self, ephemeral_window):
        from ovui_widgets.content.widget import FileBrowserWidget

        with ephemeral_window.frame:
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        ephemeral_window.frame.clear()
        assert widget._navigation_model is None

    def test_destroy_clears_navigation_delegate(self, ephemeral_window):
        from ovui_widgets.content.widget import FileBrowserWidget

        with ephemeral_window.frame:
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        widget.destroy()
        ephemeral_window.frame.clear()
        assert widget._navigation_delegate is None

    def test_get_navigation_model_matches_underscore_field(
        self, ephemeral_window,
    ):
        from ovui_widgets.content.widget import FileBrowserWidget

        with ephemeral_window.frame:
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        try:
            assert (
                widget.get_navigation_model() is widget._navigation_model
            )
        finally:
            widget.destroy()
            ephemeral_window.frame.clear()

    def test_get_tree_model_returns_navigation_model(self, ephemeral_window):
        # Backward-compat: ``get_tree_model`` was an existing public
        # accessor; Step 42 keeps the name but returns the new model
        # type. Tests written against the accessor still pass; those
        # written against the return *type* need a Step 42 update.
        from ovui_widgets.content.widget import FileBrowserWidget

        with ephemeral_window.frame:
            widget = FileBrowserWidget(MockBackend(), "mock://Home")
        try:
            assert widget.get_tree_model() is widget._navigation_model
            assert isinstance(widget.get_tree_model(), NavigationModel)
        finally:
            widget.destroy()
            ephemeral_window.frame.clear()

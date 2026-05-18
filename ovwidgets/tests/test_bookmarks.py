# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 44 + 45 — BookmarksManager, BookmarksCollection,
Add / Remove Bookmark actions, and the toolbar star.

See the content browser behavior (bookmark collection) and §25.2
(bookmark star button). Step 44 shipped the manager (persistent
``name → url`` mapping via :class:`ovwidgets.common.settings.Settings`) and the
collection (one :class:`FileItem` child per bookmark, subscribes to the
manager). Step 45 wires the UX:

* Context menu "Add Bookmark" on folder items opens a
  :class:`SimpleInputDialog` for the display name and calls
  :meth:`BookmarksManager.add`.
* Context menu "Remove Bookmark" on nav-pane bookmark child rows
  calls :meth:`BookmarksManager.remove`.
* Toolbar star button flips icon between hollow and filled based on
  whether the current URL is bookmarked; click opens
  Add / Remove flows.

These tests exercise the manager's public API (add / remove / rename
/ list / subscribe_changed / persistence roundtrip), the collection's
rendering contract, the change notification wiring, and the Step 45
Add / Remove actions + toolbar star.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import omni.ui as ui
import pytest

from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.common.settings import Settings, Subscription
from ovwidgets.content.bookmarks import (
    SETTINGS_KEY,
    BookmarksManager,
)
from ovwidgets.content.widget.bookmark_button import BookmarkButton
from ovwidgets.content.widget.collections.bookmarks import (
    BookmarksCollection,
)
from ovwidgets.content.widget.context_menu import (
    TARGET_BOOKMARK,
    FileContextMenu,
)
from ovwidgets.content.widget.file_item import FileItem

# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def settings() -> Settings:
    """Return a fresh :class:`Settings` with no persisted bookmarks."""
    return Settings()


@pytest.fixture
def manager(settings: Settings) -> BookmarksManager:
    """Manager backed by an empty Settings instance."""
    return BookmarksManager(settings)


@pytest.fixture
def populated_manager(settings: Settings) -> BookmarksManager:
    """Manager pre-loaded with three bookmarks — kept deterministic so
    tests can assert on insertion order.
    """
    m = BookmarksManager(settings)
    m.add("Home", "mock://Home")
    m.add("Documents", "mock://Home/Documents")
    m.add("Shared", "mock://Shared")
    return m


# ──────────────────────────────────────────────────────────────────────────────
# BookmarksManager — identity + defaults
# ──────────────────────────────────────────────────────────────────────────────


class TestBookmarksManagerDefaults:
    def test_settings_key_is_canonical(self):
        # The architecture's single persistence key. A future migration
        # (e.g. ``ui.content.bookmarks.v2``) would update this constant.
        assert SETTINGS_KEY == "ui.content.bookmarks"

    def test_empty_manager_lists_empty(self, manager: BookmarksManager):
        assert manager.list() == {}

    def test_empty_manager_does_not_persist_default_to_settings(
        self, settings: Settings, manager: BookmarksManager,
    ):
        # Construction must not write an empty dict back to Settings —
        # that would spuriously fire subscribers and produce
        # unnecessary save-to-disk churn.
        assert settings.get(SETTINGS_KEY, None) is None


# ──────────────────────────────────────────────────────────────────────────────
# BookmarksManager — add
# ──────────────────────────────────────────────────────────────────────────────


class TestBookmarksManagerAdd:
    def test_add_single_entry(self, manager: BookmarksManager):
        manager.add("Home", "mock://Home")
        assert manager.list() == {"Home": "mock://Home"}

    def test_add_multiple_preserves_insertion_order(
        self, manager: BookmarksManager,
    ):
        manager.add("Alpha", "mock://A")
        manager.add("Beta", "mock://B")
        manager.add("Gamma", "mock://C")
        # Dict (Python 3.7+) preserves insertion order.
        assert list(manager.list().keys()) == ["Alpha", "Beta", "Gamma"]

    def test_add_overwrites_url_for_existing_name(
        self, manager: BookmarksManager,
    ):
        manager.add("Home", "mock://OldHome")
        manager.add("Home", "mock://NewHome")
        assert manager.list() == {"Home": "mock://NewHome"}

    def test_add_is_idempotent_on_identical_pair(
        self, manager: BookmarksManager,
    ):
        # Same (name, url) twice — the second call is a no-op.
        manager.add("Home", "mock://Home")
        manager.add("Home", "mock://Home")
        assert manager.list() == {"Home": "mock://Home"}

    def test_add_persists_to_settings(
        self, settings: Settings, manager: BookmarksManager,
    ):
        manager.add("Home", "mock://Home")
        assert settings.get(SETTINGS_KEY) == {"Home": "mock://Home"}


# ──────────────────────────────────────────────────────────────────────────────
# BookmarksManager — remove
# ──────────────────────────────────────────────────────────────────────────────


class TestBookmarksManagerRemove:
    def test_remove_existing(self, populated_manager: BookmarksManager):
        populated_manager.remove("Documents")
        assert "Documents" not in populated_manager.list()
        # The other entries survive.
        assert "Home" in populated_manager.list()
        assert "Shared" in populated_manager.list()

    def test_remove_missing_is_noop(self, manager: BookmarksManager):
        # Must NOT raise — the architecture's "make sure it's gone"
        # contract tolerates a concurrent removal.
        manager.remove("does-not-exist")
        assert manager.list() == {}

    def test_remove_persists_to_settings(
        self, settings: Settings, populated_manager: BookmarksManager,
    ):
        populated_manager.remove("Documents")
        stored = settings.get(SETTINGS_KEY)
        assert stored == {
            "Home": "mock://Home",
            "Shared": "mock://Shared",
        }

    def test_remove_last_entry_leaves_empty_dict(
        self, settings: Settings, manager: BookmarksManager,
    ):
        manager.add("Only", "mock://X")
        manager.remove("Only")
        assert manager.list() == {}
        assert settings.get(SETTINGS_KEY) == {}


# ──────────────────────────────────────────────────────────────────────────────
# BookmarksManager — rename
# ──────────────────────────────────────────────────────────────────────────────


class TestBookmarksManagerRename:
    def test_rename_preserves_url(
        self, populated_manager: BookmarksManager,
    ):
        populated_manager.rename("Home", "MyHome")
        entries = populated_manager.list()
        assert "Home" not in entries
        assert entries["MyHome"] == "mock://Home"

    def test_rename_missing_old_is_noop(self, manager: BookmarksManager):
        manager.rename("ghost", "new")
        assert manager.list() == {}

    def test_rename_same_name_is_noop(
        self, populated_manager: BookmarksManager,
    ):
        before = populated_manager.list()
        populated_manager.rename("Home", "Home")
        assert populated_manager.list() == before

    def test_rename_collision_raises(
        self, populated_manager: BookmarksManager,
    ):
        # Renaming ``Home`` → ``Shared`` would destroy the existing
        # ``Shared`` bookmark's URL — callers must resolve the conflict.
        with pytest.raises(ValueError):
            populated_manager.rename("Home", "Shared")
        # The mapping is untouched.
        assert populated_manager.list()["Home"] == "mock://Home"
        assert populated_manager.list()["Shared"] == "mock://Shared"

    def test_rename_persists_to_settings(
        self, settings: Settings, populated_manager: BookmarksManager,
    ):
        populated_manager.rename("Home", "MyHome")
        stored = settings.get(SETTINGS_KEY)
        assert "MyHome" in stored
        assert stored["MyHome"] == "mock://Home"
        assert "Home" not in stored


# ──────────────────────────────────────────────────────────────────────────────
# BookmarksManager — list
# ──────────────────────────────────────────────────────────────────────────────


class TestBookmarksManagerList:
    def test_list_returns_fresh_dict_copy(
        self, populated_manager: BookmarksManager,
    ):
        first = populated_manager.list()
        second = populated_manager.list()
        # Different objects — the caller can't mutate the internal
        # state through the returned dict.
        assert first is not second
        first["Injected"] = "mock://bad"
        assert "Injected" not in populated_manager.list()

    def test_list_matches_insertion_order(
        self, populated_manager: BookmarksManager,
    ):
        assert list(populated_manager.list().keys()) == [
            "Home", "Documents", "Shared",
        ]


# ──────────────────────────────────────────────────────────────────────────────
# BookmarksManager — subscribe_changed
# ──────────────────────────────────────────────────────────────────────────────


class TestBookmarksManagerSubscribe:
    def _counter(self) -> tuple:
        calls: List[None] = []

        def _cb() -> None:
            calls.append(None)

        return calls, _cb

    def test_subscribe_returns_subscription_instance(
        self, manager: BookmarksManager,
    ):
        _calls, cb = self._counter()
        sub = manager.subscribe_changed(cb)
        assert isinstance(sub, Subscription)
        sub.cancel()

    def test_fires_on_add(self, manager: BookmarksManager):
        calls, cb = self._counter()
        sub = manager.subscribe_changed(cb)
        manager.add("Home", "mock://Home")
        assert len(calls) == 1
        sub.cancel()

    def test_fires_on_remove(self, populated_manager: BookmarksManager):
        calls, cb = self._counter()
        sub = populated_manager.subscribe_changed(cb)
        populated_manager.remove("Home")
        assert len(calls) == 1
        sub.cancel()

    def test_fires_on_rename(self, populated_manager: BookmarksManager):
        calls, cb = self._counter()
        sub = populated_manager.subscribe_changed(cb)
        populated_manager.rename("Home", "MyHome")
        assert len(calls) == 1
        sub.cancel()

    def test_no_fire_on_idempotent_add(self, populated_manager: BookmarksManager):
        calls, cb = self._counter()
        sub = populated_manager.subscribe_changed(cb)
        # Re-adding the same pair is a no-op — the persisted dict is
        # unchanged, so no notification.
        populated_manager.add("Home", "mock://Home")
        assert calls == []
        sub.cancel()

    def test_no_fire_on_missing_remove(self, manager: BookmarksManager):
        calls, cb = self._counter()
        sub = manager.subscribe_changed(cb)
        manager.remove("ghost")
        assert calls == []
        sub.cancel()

    def test_cancel_stops_notifications(self, manager: BookmarksManager):
        calls, cb = self._counter()
        sub = manager.subscribe_changed(cb)
        manager.add("A", "mock://A")
        assert len(calls) == 1
        sub.cancel()
        manager.add("B", "mock://B")
        # No further fires after cancel.
        assert len(calls) == 1

    def test_multiple_subscribers_all_fire(self, manager: BookmarksManager):
        calls1, cb1 = self._counter()
        calls2, cb2 = self._counter()
        sub1 = manager.subscribe_changed(cb1)
        sub2 = manager.subscribe_changed(cb2)
        manager.add("X", "mock://X")
        assert len(calls1) == 1
        assert len(calls2) == 1
        sub1.cancel()
        sub2.cancel()


# ──────────────────────────────────────────────────────────────────────────────
# BookmarksManager — persistence roundtrip
# ──────────────────────────────────────────────────────────────────────────────


class TestBookmarksManagerPersistence:
    def test_second_manager_loads_from_shared_settings(
        self, settings: Settings,
    ):
        first = BookmarksManager(settings)
        first.add("Home", "mock://Home")
        first.add("Shared", "mock://Shared")

        # A fresh manager on the same Settings instance reads the
        # bookmarks the first one persisted.
        second = BookmarksManager(settings)
        assert second.list() == {
            "Home": "mock://Home",
            "Shared": "mock://Shared",
        }

    def test_load_and_save_via_settings_file(self, tmp_path):
        # End-to-end: save settings to a file, load into a fresh
        # Settings, construct a manager, observe the bookmarks survive
        # the round-trip. This matches the application-startup flow
        # where ``Settings.load_from_file`` populates from the user's
        # on-disk preferences.
        settings1 = Settings()
        manager1 = BookmarksManager(settings1)
        manager1.add("Home", "mock://Home")
        manager1.add("Shared", "mock://Shared")

        save_path = tmp_path / "settings.json"
        settings1.save_to_file(str(save_path))

        settings2 = Settings()
        settings2.load_from_file(str(save_path))
        manager2 = BookmarksManager(settings2)
        assert manager2.list() == {
            "Home": "mock://Home",
            "Shared": "mock://Shared",
        }

    def test_manager_copies_stored_dict_on_construction(
        self, settings: Settings,
    ):
        # The manager must own its own copy of the stored dict so a
        # caller that mutates the Settings-held dict does not affect
        # the manager's mirror. (Settings itself does not defensively
        # copy dicts on get.)
        settings.set(SETTINGS_KEY, {"A": "mock://A"})
        manager = BookmarksManager(settings)

        raw = settings.get(SETTINGS_KEY)
        raw["Injected"] = "mock://bad"
        assert "Injected" not in manager.list()


# ──────────────────────────────────────────────────────────────────────────────
# BookmarksCollection — identity
# ──────────────────────────────────────────────────────────────────────────────


class TestBookmarksCollectionIdentity:
    def test_identifier(self):
        assert BookmarksCollection().identifier == "bookmarks"

    def test_title(self):
        assert BookmarksCollection().title == "Bookmarks"

    def test_icon_key(self):
        assert BookmarksCollection().icon_key == "content_bookmark"

    def test_is_folder(self):
        # Collection roots are always expandable in the nav tree.
        assert BookmarksCollection().is_folder is True

    def test_manager_property_returns_manager(self, manager: BookmarksManager):
        collection = BookmarksCollection(manager=manager)
        assert collection.manager is manager

    def test_none_manager_accepted(self):
        # Step 42 passed ``None`` — the Step 44 real collection must
        # keep that surface so the nav model stays constructible
        # without a Settings instance (e.g. from unit tests).
        collection = BookmarksCollection(manager=None)
        assert collection.manager is None


# ──────────────────────────────────────────────────────────────────────────────
# BookmarksCollection — children
# ──────────────────────────────────────────────────────────────────────────────


class TestBookmarksCollectionChildren:
    def test_empty_when_manager_none(self):
        collection = BookmarksCollection(manager=None)
        assert collection.get_children(MockBackend()) == []

    def test_empty_when_manager_has_no_bookmarks(
        self, manager: BookmarksManager,
    ):
        collection = BookmarksCollection(manager=manager)
        assert collection.get_children(MockBackend()) == []

    def test_one_file_item_per_bookmark(
        self, populated_manager: BookmarksManager,
    ):
        collection = BookmarksCollection(manager=populated_manager)
        children = collection.get_children(MockBackend())
        assert len(children) == 3
        for child in children:
            assert isinstance(child, FileItem)

    def test_child_names_and_urls_match_manager(
        self, populated_manager: BookmarksManager,
    ):
        collection = BookmarksCollection(manager=populated_manager)
        children = collection.get_children(MockBackend())
        pairs: Dict[str, str] = {c.name: c.url for c in children}
        assert pairs == populated_manager.list()

    def test_child_order_matches_manager_insertion_order(
        self, populated_manager: BookmarksManager,
    ):
        collection = BookmarksCollection(manager=populated_manager)
        children = collection.get_children(MockBackend())
        names = [c.name for c in children]
        assert names == list(populated_manager.list().keys())

    def test_is_folder_inferred_from_backend_stat(
        self, manager: BookmarksManager,
    ):
        # ``mock://Home/Documents/Projects/demo.usda`` is a file in
        # MockBackend's default tree; backend.stat should flag it as
        # NOT a folder, and the FileItem must reflect that.
        manager.add(
            "DemoFile", "mock://Home/Documents/Projects/demo.usda",
        )
        manager.add("HomeFolder", "mock://Home")

        collection = BookmarksCollection(manager=manager)
        children = collection.get_children(MockBackend())
        by_name = {c.name: c for c in children}
        assert by_name["DemoFile"].is_folder is False
        assert by_name["HomeFolder"].is_folder is True

    def test_unreachable_bookmark_defaults_to_folder(
        self, manager: BookmarksManager,
    ):
        # A URL that MockBackend cannot stat — the collection must
        # still surface it (so the user can remove the stale entry)
        # and default ``is_folder`` to ``True``.
        manager.add("Ghost", "mock://does/not/exist")
        collection = BookmarksCollection(manager=manager)
        children = collection.get_children(MockBackend())
        assert len(children) == 1
        assert children[0].name == "Ghost"
        assert children[0].is_folder is True


# ──────────────────────────────────────────────────────────────────────────────
# BookmarksCollection — caching contract
# ──────────────────────────────────────────────────────────────────────────────


class TestBookmarksCollectionCache:
    def test_returns_same_instances_across_calls(
        self, populated_manager: BookmarksManager,
    ):
        # Same cache invariant as :class:`MyComputerCollection`: the
        # TreeView holds items by raw C++ pointer via pybind11, so
        # fresh :class:`FileItem` instances on each call strip their
        # Python subclass on the delegate round-trip.
        collection = BookmarksCollection(manager=populated_manager)
        first = collection.get_children(MockBackend())
        second = collection.get_children(MockBackend())
        assert first is second

    def test_refresh_drops_cache(
        self, populated_manager: BookmarksManager,
    ):
        collection = BookmarksCollection(manager=populated_manager)
        first = collection.get_children(MockBackend())
        collection.refresh()
        second = collection.get_children(MockBackend())
        assert first is not second
        # The entries are still there — refresh rebuilds, not clears.
        assert len(second) == len(first)

    def test_manager_add_drops_cache(
        self, populated_manager: BookmarksManager,
    ):
        collection = BookmarksCollection(manager=populated_manager)
        first = collection.get_children(MockBackend())
        populated_manager.add("New", "mock://Home")
        second = collection.get_children(MockBackend())
        assert first is not second
        assert any(c.name == "New" for c in second)

    def test_manager_remove_drops_cache(
        self, populated_manager: BookmarksManager,
    ):
        collection = BookmarksCollection(manager=populated_manager)
        collection.get_children(MockBackend())
        populated_manager.remove("Home")
        second = collection.get_children(MockBackend())
        assert all(c.name != "Home" for c in second)


# ──────────────────────────────────────────────────────────────────────────────
# BookmarksCollection — on_changed hook
# ──────────────────────────────────────────────────────────────────────────────


class TestBookmarksCollectionOnChanged:
    def test_hook_fires_on_manager_add(
        self, populated_manager: BookmarksManager,
    ):
        collection = BookmarksCollection(manager=populated_manager)
        calls: List[None] = []
        collection.set_on_changed(lambda: calls.append(None))
        populated_manager.add("X", "mock://X")
        assert len(calls) == 1

    def test_hook_fires_on_manager_remove(
        self, populated_manager: BookmarksManager,
    ):
        collection = BookmarksCollection(manager=populated_manager)
        calls: List[None] = []
        collection.set_on_changed(lambda: calls.append(None))
        populated_manager.remove("Home")
        assert len(calls) == 1

    def test_hook_fires_on_manager_rename(
        self, populated_manager: BookmarksManager,
    ):
        collection = BookmarksCollection(manager=populated_manager)
        calls: List[None] = []
        collection.set_on_changed(lambda: calls.append(None))
        populated_manager.rename("Home", "MyHome")
        assert len(calls) == 1

    def test_hook_cleared_stops_firing(
        self, populated_manager: BookmarksManager,
    ):
        collection = BookmarksCollection(manager=populated_manager)
        calls: List[None] = []
        collection.set_on_changed(lambda: calls.append(None))
        populated_manager.add("X", "mock://X")
        collection.set_on_changed(None)
        populated_manager.add("Y", "mock://Y")
        # Only the first add fired a call.
        assert len(calls) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Integration — via NavigationModel
# ──────────────────────────────────────────────────────────────────────────────


class TestNavigationModelIntegration:
    def test_bookmarks_collection_reachable_via_nav_model(
        self, populated_manager: BookmarksManager,
    ):
        from ovwidgets.content.widget import NavigationModel

        model = NavigationModel(MockBackend(), bookmarks=populated_manager)
        bookmarks = model.find_collection("bookmarks")
        assert bookmarks is not None
        assert isinstance(bookmarks, BookmarksCollection)
        assert bookmarks.manager is populated_manager

    def test_nav_model_without_manager_still_works(self):
        # Preserves the Step 42 "no bookmarks" construction shape so
        # unit tests that instantiate :class:`NavigationModel` without
        # a Settings instance continue to pass.
        from ovwidgets.content.widget import NavigationModel

        model = NavigationModel(MockBackend())
        bookmarks = model.find_collection("bookmarks")
        assert bookmarks is not None
        assert bookmarks.manager is None
        assert list(model.get_item_children(bookmarks)) == []

    def test_manager_mutation_emits_item_changed(
        self, populated_manager: BookmarksManager,
    ):
        # End-to-end: a bookmark add must emit ``_item_changed`` on
        # the collection root so the TreeView re-queries its children.
        # We capture the invocation by monkey-patching ``_item_changed``
        # rather than spinning up a real ``ui.TreeView``, since the
        # omni.ui event loop is not running in the pytest harness.
        from ovwidgets.content.widget import NavigationModel

        model = NavigationModel(MockBackend(), bookmarks=populated_manager)
        bookmarks = model.find_collection("bookmarks")
        assert bookmarks is not None

        received: List = []
        original = model._item_changed

        def _spy(item):
            received.append(item)
            return original(item)

        model._item_changed = _spy  # type: ignore[method-assign]

        populated_manager.add("X", "mock://X")
        assert bookmarks in received

    def test_nav_model_returns_children_for_bookmarks_collection(
        self, populated_manager: BookmarksManager,
    ):
        from ovwidgets.content.widget import NavigationModel

        model = NavigationModel(MockBackend(), bookmarks=populated_manager)
        bookmarks = model.find_collection("bookmarks")
        children = list(model.get_item_children(bookmarks))
        assert len(children) == 3


# ──────────────────────────────────────────────────────────────────────────────
# Step 45 — Context menu Add / Remove Bookmark
# ──────────────────────────────────────────────────────────────────────────────


class _StubWidget:
    """Stand-in for :class:`FileBrowserWidget` for Step 45 context-menu tests.

    Exposes the attributes :class:`FileContextMenu` reaches for through
    the widget: ``_backend`` / ``_detail_model`` / ``_bookmarks``. The
    fake model's ``root_url`` is unused by the Add Bookmark flow but
    present so the existing menu paths (Create Folder / Refresh) still
    have something to read.
    """

    class _FakeModel:
        def __init__(self, root_url: str = "mock://Home") -> None:
            self.root_url = root_url
            self.refresh_all_count = 0

        def refresh_all(self) -> None:
            self.refresh_all_count += 1

    def __init__(
        self,
        bookmarks: Optional[BookmarksManager] = None,
        backend: Optional[Any] = None,
    ) -> None:
        self._backend = backend if backend is not None else MockBackend()
        self._detail_model = _StubWidget._FakeModel()
        self._bookmarks: Optional[BookmarksManager] = bookmarks


@pytest.fixture(scope="module")
def ephemeral_window_step45():
    """Single ovui Window reused across Step 45 build tests."""
    win = ui.Window("_test_bookmarks_step45", width=300, height=200)
    yield win
    win.destroy()


@contextmanager
def _in_frame(window):
    """Enter ``window.frame`` as a build context and clear on exit."""
    try:
        with window.frame:
            yield
    finally:
        window.frame.clear()


class TestAddBookmarkContextMenuEntry:
    def test_folder_menu_contains_add_bookmark(self):
        """The folder context menu still carries the Step 31 "Add Bookmark"
        entry — Step 45 swaps the click handler but leaves the label
        and slot in place."""
        menu = FileContextMenu(_StubWidget())
        try:
            specs = menu._folder_specs()
            labels = [spec.name for spec in specs]
            assert "Add Bookmark" in labels
        finally:
            menu.destroy()

    def test_file_menu_does_not_contain_add_bookmark(self):
        """Add Bookmark applies only to folders per architecture §17.3."""
        menu = FileContextMenu(_StubWidget())
        try:
            labels = [spec.name for spec in menu._file_specs()]
            assert "Add Bookmark" not in labels
        finally:
            menu.destroy()


class TestAddBookmarkContextFlow:
    def test_add_bookmark_opens_input_dialog_with_basename_default(
        self, settings: Settings, ephemeral_window_step45,
    ):
        """Clicking Add Bookmark opens the input dialog seeded with the
        folder's basename."""
        mgr = BookmarksManager(settings)
        widget = _StubWidget(bookmarks=mgr)
        menu = FileContextMenu(widget)
        try:
            folder = FileItem(
                url="mock://Home/Documents",
                name="Documents",
                is_folder=True,
            )
            with _in_frame(ephemeral_window_step45):
                menu._begin_add_bookmark(folder)
            dlg = menu._input_dialog
            assert dlg is not None
            assert dlg.is_open
            # The default is the backend basename of the folder URL.
            # ``Documents`` on ``mock://Home/Documents``.
            assert dlg._initial_value == "Documents"
        finally:
            menu.destroy()

    def test_add_bookmark_commits_on_ok(
        self, settings: Settings, ephemeral_window_step45,
    ):
        """OK in the dialog calls :meth:`BookmarksManager.add` with the
        typed name and the folder's URL."""
        mgr = BookmarksManager(settings)
        widget = _StubWidget(bookmarks=mgr)
        menu = FileContextMenu(widget)
        try:
            folder = FileItem(
                url="mock://Home/Shared",
                name="Shared",
                is_folder=True,
            )
            with _in_frame(ephemeral_window_step45):
                menu._begin_add_bookmark(folder)
            dlg = menu._input_dialog
            assert dlg is not None
            dlg._set_value_for_test("My Shared Folder")
            dlg._fire_ok_for_test()
            assert mgr.list() == {"My Shared Folder": "mock://Home/Shared"}
        finally:
            menu.destroy()

    def test_add_bookmark_rejects_empty_name(
        self, settings: Settings, ephemeral_window_step45,
    ):
        """A blank name leaves the manager unchanged — matches the
        Create Folder validation contract."""
        mgr = BookmarksManager(settings)
        widget = _StubWidget(bookmarks=mgr)
        menu = FileContextMenu(widget)
        try:
            folder = FileItem(
                url="mock://Home/Empty", name="Empty", is_folder=True,
            )
            with _in_frame(ephemeral_window_step45):
                menu._begin_add_bookmark(folder)
            dlg = menu._input_dialog
            assert dlg is not None
            dlg._set_value_for_test("   ")
            dlg._fire_ok_for_test()
            assert mgr.list() == {}
        finally:
            menu.destroy()

    def test_add_bookmark_refuses_file_target(
        self, settings: Settings, ephemeral_window_step45,
    ):
        """A file target falls through to the stub path — no dialog,
        no mutation. Covers a plug-in that wired Add Bookmark onto a
        different target kind."""
        mgr = BookmarksManager(settings)
        widget = _StubWidget(bookmarks=mgr)
        menu = FileContextMenu(widget)
        try:
            file_item = FileItem(
                url="mock://Home/test.usd", name="test.usd",
                is_folder=False,
            )
            with _in_frame(ephemeral_window_step45):
                menu._begin_add_bookmark(file_item)
            assert menu._input_dialog is None
            assert mgr.list() == {}
        finally:
            menu.destroy()

    def test_add_bookmark_without_manager_surfaces_warning(
        self, ephemeral_window_step45,
    ):
        """A widget without a manager surfaces a warning rather than
        silently accepting the click."""
        widget = _StubWidget(bookmarks=None)
        menu = FileContextMenu(widget)
        try:
            folder = FileItem(
                url="mock://Home/Shared", name="Shared", is_folder=True,
            )
            with _in_frame(ephemeral_window_step45):
                menu._begin_add_bookmark(folder)
            # No dialog should open because there is no manager to
            # write to. The warning goes through :class:`ErrorReporter`
            # which in a test harness is a silent no-op, so we just
            # assert the dialog slot remains empty.
            assert menu._input_dialog is None
        finally:
            menu.destroy()


class TestRemoveBookmarkContextFlow:
    def test_show_bookmark_menu_builds_remove_entry(
        self, populated_manager: BookmarksManager,
        ephemeral_window_step45, monkeypatch,
    ):
        """``show_bookmark_menu`` pops a menu with a "Remove Bookmark"
        entry. We stub :meth:`ui.Menu.show_at` to bypass the popup
        positioning (mirrors the :class:`FileContextMenu.show` tests in
        ``test_context_menu.py``)."""
        monkeypatch.setattr(
            ui.Menu, "show_at", lambda self, *a, **kw: None,
        )
        widget = _StubWidget(bookmarks=populated_manager)
        menu = FileContextMenu(widget)
        try:
            with _in_frame(ephemeral_window_step45):
                result = menu.show_bookmark_menu(10.0, 20.0, "Home")
            assert result is not None
            assert isinstance(result, ui.Menu)
        finally:
            menu.destroy()

    def test_show_bookmark_menu_after_destroy_returns_none(
        self, populated_manager: BookmarksManager,
    ):
        """Post-destroy short-circuit — no ovui access happens before
        the ``_widget is None`` guard fires."""
        widget = _StubWidget(bookmarks=populated_manager)
        menu = FileContextMenu(widget)
        menu.destroy()
        assert menu.show_bookmark_menu(0.0, 0.0, "Home") is None

    def test_remove_bookmark_commits(
        self, populated_manager: BookmarksManager,
    ):
        """Dispatching the Remove Bookmark click handler removes the
        named bookmark from the manager."""
        widget = _StubWidget(bookmarks=populated_manager)
        menu = FileContextMenu(widget)
        try:
            menu._begin_remove_bookmark("Home")
            assert "Home" not in populated_manager.list()
            # Remaining bookmarks are untouched.
            assert set(populated_manager.list().keys()) == {
                "Documents", "Shared",
            }
        finally:
            menu.destroy()

    def test_remove_bookmark_without_manager_is_noop(self):
        """A widget without a manager falls through silently rather
        than raising."""
        widget = _StubWidget(bookmarks=None)
        menu = FileContextMenu(widget)
        try:
            # Should not raise.
            menu._begin_remove_bookmark("anything")
        finally:
            menu.destroy()

    def test_remove_bookmark_empty_name_is_noop(
        self, populated_manager: BookmarksManager,
    ):
        """An empty name is a defensive refusal — does not touch the
        manager."""
        widget = _StubWidget(bookmarks=populated_manager)
        menu = FileContextMenu(widget)
        try:
            menu._begin_remove_bookmark("")
            # All three original bookmarks are still present.
            assert set(populated_manager.list().keys()) == {
                "Home", "Documents", "Shared",
            }
        finally:
            menu.destroy()


class TestTargetBookmarkConstant:
    def test_target_bookmark_is_unique_string(self):
        """``TARGET_BOOKMARK`` does not collide with the existing
        target constants — regression guard against a future refactor
        that folds the four constants into an Enum."""
        from ovwidgets.content.widget.context_menu import (
            TARGET_BOOKMARK as TB,
        )
        from ovwidgets.content.widget.context_menu import (
            TARGET_EMPTY as TE,
        )
        from ovwidgets.content.widget.context_menu import (
            TARGET_FILE as TF,
        )
        from ovwidgets.content.widget.context_menu import (
            TARGET_FOLDER as TD,
        )
        assert TB not in (TE, TF, TD)
        assert TARGET_BOOKMARK == "bookmark"


# ──────────────────────────────────────────────────────────────────────────────
# Step 45 — Toolbar bookmark star button
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_backend() -> MockBackend:
    return MockBackend()


@pytest.fixture
def star_button(
    ephemeral_window_step45,
    mock_backend: MockBackend,
    populated_manager: BookmarksManager,
):
    """Build a :class:`BookmarkButton` inside the ephemeral window.

    Yields the button + the manager so tests can drive both from a
    single arrangement step. Destroys the button on teardown so the
    manager subscription does not leak.
    """
    with _in_frame(ephemeral_window_step45):
        btn = BookmarkButton(
            manager=populated_manager,
            backend=mock_backend,
            current_url="mock://Home",
        )
    try:
        yield btn, populated_manager
    finally:
        btn.destroy()


class TestBookmarkButtonConstruction:
    def test_builds_widgets(
        self, ephemeral_window_step45, mock_backend: MockBackend,
    ):
        with _in_frame(ephemeral_window_step45):
            btn = BookmarkButton(
                manager=None,
                backend=mock_backend,
                current_url="",
            )
        try:
            assert btn._button is not None
            assert btn._icon_image is not None
            assert btn._zstack is not None
        finally:
            btn.destroy()

    def test_no_manager_is_allowed(
        self, ephemeral_window_step45, mock_backend: MockBackend,
    ):
        """A ``None`` manager still builds the button."""
        with _in_frame(ephemeral_window_step45):
            btn = BookmarkButton(
                manager=None, backend=mock_backend, current_url="mock://Home",
            )
        try:
            assert btn.is_bookmarked is False
        finally:
            btn.destroy()

    def test_reflects_initial_url_bookmarked(
        self, ephemeral_window_step45, mock_backend: MockBackend,
        populated_manager: BookmarksManager,
    ):
        """``populated_manager`` bookmarks ``mock://Home`` as ``Home`` —
        the button must reflect that on construction, without a
        ``set_current_url`` call."""
        with _in_frame(ephemeral_window_step45):
            btn = BookmarkButton(
                manager=populated_manager,
                backend=mock_backend,
                current_url="mock://Home",
            )
        try:
            assert btn.is_bookmarked is True
        finally:
            btn.destroy()

    def test_button_is_disabled_v1(
        self, ephemeral_window_step45, mock_backend: MockBackend,
    ):
        """Bug 9 — the toolbar star ships disabled in V1 because the
        on-click feedback is subtle (glyph swap + status-bar line) and
        the context-menu "Add to Bookmarks" covers the same action
        with more context. The Content.ToolBar.Button:disabled style
        grays the icon and strips the hover highlight.
        """
        with _in_frame(ephemeral_window_step45):
            btn = BookmarkButton(
                manager=None, backend=mock_backend, current_url="",
            )
        try:
            assert btn._button.enabled is False
            assert "not yet implemented" in btn._button.tooltip.lower()
        finally:
            btn.destroy()


class TestBookmarkButtonURLTracking:
    def test_set_current_url_updates_state(
        self, star_button,
    ):
        btn, mgr = star_button
        btn.set_current_url("mock://NotBookmarked")
        assert btn.is_bookmarked is False
        btn.set_current_url("mock://Shared")
        assert btn.is_bookmarked is True

    def test_set_current_url_idempotent(self, star_button):
        btn, _ = star_button
        btn.set_current_url("mock://Home")
        # No state change; current_url stays as the constructor value.
        assert btn.current_url == "mock://Home"


class TestBookmarkButtonAddFlow:
    def test_click_on_unbookmarked_opens_add_dialog(
        self, ephemeral_window_step45,
        mock_backend: MockBackend, populated_manager: BookmarksManager,
    ):
        with _in_frame(ephemeral_window_step45):
            btn = BookmarkButton(
                manager=populated_manager,
                backend=mock_backend,
                current_url="mock://New",
            )
        try:
            assert btn.is_bookmarked is False
            btn._fire_click_for_test()
            assert btn._input_dialog is not None
            assert btn._input_dialog.is_open
        finally:
            btn.destroy()

    def test_add_dialog_ok_commits_to_manager(
        self, ephemeral_window_step45,
        mock_backend: MockBackend, populated_manager: BookmarksManager,
    ):
        with _in_frame(ephemeral_window_step45):
            btn = BookmarkButton(
                manager=populated_manager,
                backend=mock_backend,
                current_url="mock://Home/NewFolder",
            )
        try:
            btn._fire_click_for_test()
            dlg = btn._input_dialog
            assert dlg is not None
            dlg._set_value_for_test("My New Bookmark")
            dlg._fire_ok_for_test()
            assert populated_manager.list().get("My New Bookmark") == (
                "mock://Home/NewFolder"
            )
        finally:
            btn.destroy()

    def test_add_dialog_rejects_empty_name(
        self, ephemeral_window_step45,
        mock_backend: MockBackend, populated_manager: BookmarksManager,
    ):
        with _in_frame(ephemeral_window_step45):
            btn = BookmarkButton(
                manager=populated_manager,
                backend=mock_backend,
                current_url="mock://Home/NewFolder",
            )
        try:
            btn._fire_click_for_test()
            dlg = btn._input_dialog
            assert dlg is not None
            dlg._set_value_for_test("   ")
            dlg._fire_ok_for_test()
            # No new bookmark — the three from the fixture remain.
            assert set(populated_manager.list().keys()) == {
                "Home", "Documents", "Shared",
            }
        finally:
            btn.destroy()

    def test_click_without_manager_does_not_open_dialog(
        self, ephemeral_window_step45, mock_backend: MockBackend,
    ):
        with _in_frame(ephemeral_window_step45):
            btn = BookmarkButton(
                manager=None,
                backend=mock_backend,
                current_url="mock://Home",
            )
        try:
            btn._fire_click_for_test()
            assert btn._input_dialog is None
            assert btn._confirm_dialog is None
        finally:
            btn.destroy()


class TestBookmarkButtonRemoveFlow:
    def test_click_on_bookmarked_opens_confirm(
        self, star_button,
    ):
        btn, mgr = star_button
        # ``mock://Home`` is bookmarked by the fixture.
        btn._fire_click_for_test()
        assert btn._confirm_dialog is not None
        assert btn._confirm_dialog.is_open

    def test_confirm_yes_removes_bookmark(
        self, star_button,
    ):
        btn, mgr = star_button
        btn._fire_click_for_test()
        dlg = btn._confirm_dialog
        assert dlg is not None
        dlg._fire_yes_for_test()
        assert "Home" not in mgr.list()

    def test_confirm_no_keeps_bookmark(
        self, star_button,
    ):
        btn, mgr = star_button
        btn._fire_click_for_test()
        dlg = btn._confirm_dialog
        assert dlg is not None
        dlg._fire_no_for_test()
        assert "Home" in mgr.list()


class TestBookmarkButtonReactivity:
    def test_manager_mutation_updates_icon_state(
        self, star_button,
    ):
        """Adding a bookmark for the current URL via another surface
        (e.g. a context menu click) drives the button's state without
        a navigation change."""
        btn, mgr = star_button
        btn.set_current_url("mock://NotYet")
        assert btn.is_bookmarked is False
        mgr.add("NotYet", "mock://NotYet")
        assert btn.is_bookmarked is True
        mgr.remove("NotYet")
        assert btn.is_bookmarked is False

    def test_destroy_cancels_subscription(
        self, ephemeral_window_step45, mock_backend: MockBackend,
        populated_manager: BookmarksManager,
    ):
        """Post-destroy, a manager mutation does not crash because the
        subscription is cancelled (the button's icon ref is ``None``;
        the ``_refresh_icon`` short-circuits)."""
        with _in_frame(ephemeral_window_step45):
            btn = BookmarkButton(
                manager=populated_manager,
                backend=mock_backend,
                current_url="mock://Home",
            )
        btn.destroy()
        # This must not raise.
        populated_manager.add("NewOne", "mock://NewOne")

    def test_destroy_idempotent(
        self, ephemeral_window_step45, mock_backend: MockBackend,
        populated_manager: BookmarksManager,
    ):
        with _in_frame(ephemeral_window_step45):
            btn = BookmarkButton(
                manager=populated_manager,
                backend=mock_backend,
                current_url="mock://Home",
            )
        btn.destroy()
        btn.destroy()  # Must not raise.


# ──────────────────────────────────────────────────────────────────────────────
# Step 45 — end-to-end: nav pane reflects Add / Remove
# ──────────────────────────────────────────────────────────────────────────────


class TestNavPaneReflectsBookmarkChanges:
    def test_add_appears_as_nav_child(
        self, populated_manager: BookmarksManager,
    ):
        """Adding a bookmark surfaces a new child under the nav-pane
        Bookmarks collection."""
        from ovwidgets.content.widget import NavigationModel

        model = NavigationModel(
            MockBackend(), bookmarks=populated_manager,
        )
        bookmarks = model.find_collection("bookmarks")
        before = [
            item.name for item in model.get_item_children(bookmarks)
        ]
        assert "Extra" not in before
        populated_manager.add("Extra", "mock://Extra")
        after = [
            item.name for item in model.get_item_children(bookmarks)
        ]
        assert "Extra" in after

    def test_remove_disappears_from_nav(
        self, populated_manager: BookmarksManager,
    ):
        """Removing a bookmark drops the corresponding nav child."""
        from ovwidgets.content.widget import NavigationModel

        model = NavigationModel(
            MockBackend(), bookmarks=populated_manager,
        )
        bookmarks = model.find_collection("bookmarks")
        before_names = {
            item.name for item in model.get_item_children(bookmarks)
        }
        assert "Home" in before_names
        populated_manager.remove("Home")
        after_names = {
            item.name for item in model.get_item_children(bookmarks)
        }
        assert "Home" not in after_names


# ──────────────────────────────────────────────────────────────────────────────
# Step 45 — NavigationDelegate right-click wiring
# ──────────────────────────────────────────────────────────────────────────────


class TestNavigationDelegateRightClick:
    def test_set_on_right_click_stores_handler(self):
        from ovwidgets.content.widget.navigation_model import (
            NavigationDelegate,
        )
        delegate = NavigationDelegate()
        captured: List[Any] = []

        def _handler(x, y, item):
            captured.append((x, y, item))

        delegate.set_on_right_click(_handler)
        assert delegate._on_right_click is _handler

    def test_set_on_right_click_none_clears(self):
        from ovwidgets.content.widget.navigation_model import (
            NavigationDelegate,
        )
        delegate = NavigationDelegate()
        delegate.set_on_right_click(lambda x, y, it: None)
        delegate.set_on_right_click(None)
        assert delegate._on_right_click is None

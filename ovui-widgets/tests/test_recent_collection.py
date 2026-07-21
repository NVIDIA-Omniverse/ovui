# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 46 — :class:`RecentFilesCollection`.

See the content browser behavior (file-event-history layer) and
the content browser implementation step 46. The navigation pane's "Recent" collection
renders one :class:`RecentFileItem` per entry in
:class:`ovui_widgets.common.recent_files.RecentFileList`, in most-recent-first
order, and subscribes to :class:`ovui_widgets.common.settings.Settings` so an
out-of-process write to the ``ui.recent_files`` key repaints the
nav tree. Non-existent entries are still rendered, but flagged
``is_missing=True`` so the nav delegate paints them grey.

These tests exercise:

* Identity and defaults of the collection.
* Enumeration contract — one :class:`RecentFileItem` per entry, in
  most-recent-first order, ``is_folder=False`` for every entry.
* Existence check — reachable URLs flag ``is_missing=False``;
  non-reachable ones flag ``is_missing=True`` but still render.
* Settings subscription — a write to ``ui.recent_files`` drops the
  cache and fires the ``on_changed`` hook.
* Cache invariants — identical :class:`RecentFileItem` instances on
  repeated :meth:`get_children` calls (pybind11 pointer-identity
  constraint shared with :class:`MyComputerCollection` /
  :class:`BookmarksCollection`).
* Navigation-model integration — the model wires the real collection
  (not the Step-42 stub) and a settings write emits ``_item_changed``
  on the collection root.
"""

from __future__ import annotations

from typing import List

import pytest

from ovui_widgets.app.testing.mock_backend import MockBackend
from ovui_widgets.common.recent_files import RecentFileList
from ovui_widgets.common.settings import Settings
from ovui_widgets.content.widget.collections import (
    CollectionItem,
    RecentFileItem,
    RecentFilesCollection,
)
from ovui_widgets.content.widget.file_item import FileItem

# The :class:`Settings` key that persists the recent-file list —
# mirrors the module-level constant inside the collection module.
_SETTINGS_KEY = "ui.recent_files"


# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def settings() -> Settings:
    """Fresh :class:`Settings` — no persisted recent files."""
    return Settings()


@pytest.fixture
def recent_files() -> RecentFileList:
    """Empty :class:`RecentFileList`."""
    return RecentFileList()


@pytest.fixture
def populated_recent_files() -> RecentFileList:
    """Populated list in most-recent-first order.

    The ``Shared`` entry is kept at the tail as a known-existing
    fallback for tests that need a reachable mock-backend URL.
    """
    rf = RecentFileList()
    # Add order is oldest → newest; :meth:`add` promotes on duplicate
    # so the final ordering is newest → oldest reading top-down.
    rf.add("mock://Home/Documents/Projects/demo.usda")
    rf.add("mock://Home/Textures/concrete.png")
    rf.add("mock://Shared")
    return rf


# ──────────────────────────────────────────────────────────────────────────────
# RecentFilesCollection — identity
# ──────────────────────────────────────────────────────────────────────────────


class TestRecentFilesCollectionIdentity:
    def test_identifier(self):
        assert RecentFilesCollection().identifier == "recent"

    def test_title(self):
        assert RecentFilesCollection().title == "Recent"

    def test_icon_key_is_non_empty(self):
        # The icon key must resolve to a registered glyph — a blank
        # value would leave the nav row without an icon. See
        # :mod:`ovui_widgets.common.style.urls`.
        assert RecentFilesCollection().icon_key

    def test_is_folder(self):
        # Collection roots are always expandable.
        assert RecentFilesCollection().is_folder is True

    def test_is_collection_item(self):
        # Sanity: the real collection must be a subclass so the
        # NavigationModel's ``isinstance(item, CollectionItem)`` path
        # still classifies it as a root rather than a leaf.
        assert isinstance(RecentFilesCollection(), CollectionItem)

    def test_recent_files_property_returns_reference(
        self, recent_files: RecentFileList,
    ):
        collection = RecentFilesCollection(recent_files=recent_files)
        assert collection.recent_files is recent_files

    def test_settings_property_returns_reference(self, settings: Settings):
        collection = RecentFilesCollection(settings=settings)
        assert collection.settings is settings

    def test_both_none_accepted(self):
        # Construction without either source must succeed — the
        # Step-42 stub accepted ``None`` and the real collection keeps
        # that surface so :class:`NavigationModel` can still be built
        # without an :class:`Application` (unit tests).
        collection = RecentFilesCollection()
        assert collection.recent_files is None
        assert collection.settings is None


# ──────────────────────────────────────────────────────────────────────────────
# RecentFilesCollection — children enumeration
# ──────────────────────────────────────────────────────────────────────────────


class TestRecentFilesCollectionChildren:
    def test_empty_when_no_sources(self):
        collection = RecentFilesCollection()
        assert collection.get_children(MockBackend()) == []

    def test_empty_when_list_empty(self, recent_files: RecentFileList):
        collection = RecentFilesCollection(recent_files=recent_files)
        assert collection.get_children(MockBackend()) == []

    def test_empty_when_settings_empty(self, settings: Settings):
        # No ``ui.recent_files`` key set → default ``[]``.
        collection = RecentFilesCollection(settings=settings)
        assert collection.get_children(MockBackend()) == []

    def test_one_child_per_entry(
        self, populated_recent_files: RecentFileList,
    ):
        collection = RecentFilesCollection(recent_files=populated_recent_files)
        children = collection.get_children(MockBackend())
        assert len(children) == 3

    def test_children_are_recent_file_items(
        self, populated_recent_files: RecentFileList,
    ):
        collection = RecentFilesCollection(recent_files=populated_recent_files)
        children = collection.get_children(MockBackend())
        for child in children:
            # Must be the subclass — the nav delegate reads
            # ``is_missing`` through ``getattr``, so a bare
            # :class:`FileItem` here would drop the grey style.
            assert isinstance(child, RecentFileItem)
            assert isinstance(child, FileItem)

    def test_order_matches_most_recent_first(
        self, populated_recent_files: RecentFileList,
    ):
        collection = RecentFilesCollection(recent_files=populated_recent_files)
        children = collection.get_children(MockBackend())
        # ``populated_recent_files`` fixture added in ascending-time
        # order (oldest first); :class:`RecentFileList.add` pushes each
        # new entry to the head, so the final ordered list is
        # ``[most-recent, …, oldest]`` — which is what we assert here.
        assert [c.url for c in children] == [
            "mock://Shared",
            "mock://Home/Textures/concrete.png",
            "mock://Home/Documents/Projects/demo.usda",
        ]

    def test_children_have_basename_as_name(
        self, populated_recent_files: RecentFileList,
    ):
        collection = RecentFilesCollection(recent_files=populated_recent_files)
        children = collection.get_children(MockBackend())
        names = [c.name for c in children]
        # ``mock://Shared`` → leaf "Shared"; the two nested paths
        # yield their trailing leaf names.
        assert names == ["Shared", "concrete.png", "demo.usda"]

    def test_children_are_files_not_folders(
        self, populated_recent_files: RecentFileList,
    ):
        # The recent-files list records URLs that went through
        # :meth:`Application.open_file` — always files, never folders —
        # so the collection surfaces them with ``is_folder=False``
        # regardless of the backend's own view of the URL.
        collection = RecentFilesCollection(recent_files=populated_recent_files)
        children = collection.get_children(MockBackend())
        for child in children:
            assert child.is_folder is False

    def test_skips_blank_path_entries(self):
        rf = RecentFileList()
        rf.add("mock://Home")
        # The settings layer can contain a spurious blank string if a
        # stale file was persisted. Defensive: blank entries do not
        # produce a zero-width row.
        collection = RecentFilesCollection(recent_files=rf)
        # Force a blank through :meth:`RecentFileList.add`'s raw deque
        # (the public ``add`` call refuses empty strings only by
        # convention — it promotes on duplicate but does accept "").
        # Using the internal deque keeps this test self-contained
        # rather than relying on a fixture file on disk.
        rf._items.appendleft("")
        children = collection.get_children(MockBackend())
        assert all(c.name for c in children)


# ──────────────────────────────────────────────────────────────────────────────
# RecentFilesCollection — existence / is_missing
# ──────────────────────────────────────────────────────────────────────────────


class TestRecentFilesCollectionMissingFlag:
    def test_reachable_entry_not_missing(self, recent_files: RecentFileList):
        # ``mock://Shared`` is a folder in the default mock tree;
        # stat returns OK so the item must render as live.
        recent_files.add("mock://Shared")
        collection = RecentFilesCollection(recent_files=recent_files)
        child = collection.get_children(MockBackend())[0]
        assert isinstance(child, RecentFileItem)
        assert child.is_missing is False

    def test_unreachable_entry_is_missing(self, recent_files: RecentFileList):
        # ``mock://does/not/exist`` fails backend.stat — the item
        # must still surface (so the user can see and later remove it)
        # but with ``is_missing=True``.
        recent_files.add("mock://does/not/exist")
        collection = RecentFilesCollection(recent_files=recent_files)
        child = collection.get_children(MockBackend())[0]
        assert isinstance(child, RecentFileItem)
        assert child.is_missing is True
        assert child.url == "mock://does/not/exist"

    def test_mix_of_reachable_and_missing(
        self, recent_files: RecentFileList,
    ):
        recent_files.add("mock://Shared")
        recent_files.add("mock://Home/Documents/Projects/demo.usda")
        recent_files.add("mock://gone")
        collection = RecentFilesCollection(recent_files=recent_files)
        children = collection.get_children(MockBackend())
        by_url = {c.url: c for c in children}
        assert by_url["mock://gone"].is_missing is True
        assert by_url["mock://Shared"].is_missing is False
        assert (
            by_url["mock://Home/Documents/Projects/demo.usda"].is_missing
            is False
        )

    def test_missing_entry_still_rendered(
        self, recent_files: RecentFileList,
    ):
        # Architectural contract (Step 46): non-existent files are
        # still displayed. If enumeration silently dropped them the
        # user could not remove stale entries.
        recent_files.add("mock://gone/also")
        collection = RecentFilesCollection(recent_files=recent_files)
        children = collection.get_children(MockBackend())
        assert len(children) == 1

    def test_recent_file_item_default_is_not_missing(self):
        # Direct construction contract — a bare :class:`RecentFileItem`
        # with no ``is_missing`` kwarg must default to live.
        item = RecentFileItem(url="mock://x", name="x")
        assert item.is_missing is False


# ──────────────────────────────────────────────────────────────────────────────
# RecentFilesCollection — settings subscription + caching
# ──────────────────────────────────────────────────────────────────────────────


class TestRecentFilesCollectionSubscription:
    def test_cache_returns_same_instances(
        self, populated_recent_files: RecentFileList,
    ):
        # Same pybind11 pointer-identity constraint as
        # :class:`BookmarksCollection` /
        # :class:`MyComputerCollection` — fresh :class:`FileItem`
        # instances on each call would lose their subclass identity
        # across the TreeView's raw-pointer round-trip.
        collection = RecentFilesCollection(
            recent_files=populated_recent_files,
        )
        first = collection.get_children(MockBackend())
        second = collection.get_children(MockBackend())
        assert first is second

    def test_refresh_drops_cache(
        self, populated_recent_files: RecentFileList,
    ):
        collection = RecentFilesCollection(
            recent_files=populated_recent_files,
        )
        first = collection.get_children(MockBackend())
        collection.refresh()
        second = collection.get_children(MockBackend())
        # Fresh list after refresh; content still identical since the
        # underlying :class:`RecentFileList` did not change.
        assert first is not second
        assert [c.url for c in first] == [c.url for c in second]

    def test_settings_change_drops_cache(
        self,
        settings: Settings,
        populated_recent_files: RecentFileList,
    ):
        # The settings subscription must invalidate the cache so the
        # next :meth:`get_children` re-reads the underlying
        # :class:`RecentFileList` (which may have been mutated in sync
        # with the settings write).
        collection = RecentFilesCollection(
            recent_files=populated_recent_files,
            settings=settings,
        )
        first = collection.get_children(MockBackend())
        # Simulate :meth:`Application.open_file`'s write-through:
        # mutate the in-memory list AND write the ordered snapshot to
        # :class:`Settings`.
        populated_recent_files.add("mock://Home/Scripts/test.py")
        settings.set(
            _SETTINGS_KEY, populated_recent_files.get_ordered(),
        )
        second = collection.get_children(MockBackend())
        assert first is not second
        assert second[0].url == "mock://Home/Scripts/test.py"

    def test_settings_change_fires_on_changed(
        self, settings: Settings,
    ):
        collection = RecentFilesCollection(settings=settings)
        calls: List[None] = []
        collection.set_on_changed(lambda: calls.append(None))
        settings.set(_SETTINGS_KEY, ["mock://Home"])
        assert len(calls) == 1

    def test_on_changed_cleared_stops_firing(
        self, settings: Settings,
    ):
        collection = RecentFilesCollection(settings=settings)
        calls: List[None] = []
        collection.set_on_changed(lambda: calls.append(None))
        settings.set(_SETTINGS_KEY, ["mock://A"])
        collection.set_on_changed(None)
        settings.set(_SETTINGS_KEY, ["mock://B"])
        assert len(calls) == 1

    def test_no_settings_subscription_when_settings_none(
        self, populated_recent_files: RecentFileList,
    ):
        # Construction without :class:`Settings` must not raise and
        # must not accidentally reach for a global singleton.
        collection = RecentFilesCollection(
            recent_files=populated_recent_files,
        )
        # Existence + smoke: no settings → no subscription handle.
        assert collection._subscription is None
        # And the children enumeration still works.
        assert len(collection.get_children(MockBackend())) == 3

    def test_settings_only_source(self, settings: Settings):
        # When no :class:`RecentFileList` is supplied, the collection
        # reads :class:`Settings` directly — the architectural fallback
        # that lets a :class:`NavigationModel` render without an
        # :class:`Application` singleton.
        settings.set(_SETTINGS_KEY, ["mock://Shared", "mock://gone"])
        collection = RecentFilesCollection(settings=settings)
        children = collection.get_children(MockBackend())
        urls = [c.url for c in children]
        assert urls == ["mock://Shared", "mock://gone"]


# ──────────────────────────────────────────────────────────────────────────────
# Integration — via NavigationModel
# ──────────────────────────────────────────────────────────────────────────────


class TestNavigationModelIntegration:
    def test_recent_collection_reachable_via_nav_model(
        self, populated_recent_files: RecentFileList,
    ):
        from ovui_widgets.content.widget import NavigationModel

        model = NavigationModel(
            MockBackend(), recent_files=populated_recent_files,
        )
        recent = model.find_collection("recent")
        assert recent is not None
        assert isinstance(recent, RecentFilesCollection)
        assert recent.recent_files is populated_recent_files

    def test_nav_model_without_recent_files_still_works(self):
        # Preserves the Step 42 "no recent files" construction shape.
        from ovui_widgets.content.widget import NavigationModel

        model = NavigationModel(MockBackend())
        recent = model.find_collection("recent")
        assert recent is not None
        assert recent.recent_files is None
        assert list(model.get_item_children(recent)) == []

    def test_nav_model_returns_children_for_recent_collection(
        self, populated_recent_files: RecentFileList,
    ):
        from ovui_widgets.content.widget import NavigationModel

        model = NavigationModel(
            MockBackend(), recent_files=populated_recent_files,
        )
        recent = model.find_collection("recent")
        children = list(model.get_item_children(recent))
        assert len(children) == 3

    def test_settings_write_emits_item_changed(
        self,
        settings: Settings,
        populated_recent_files: RecentFileList,
    ):
        # End-to-end: a settings write to ``ui.recent_files`` must
        # reach ``_item_changed`` on the Recent collection so the
        # TreeView re-queries its children. We spy on ``_item_changed``
        # rather than spinning up a real ``ui.TreeView`` (no event
        # loop in pytest).
        from ovui_widgets.content.widget import NavigationModel

        model = NavigationModel(
            MockBackend(),
            recent_files=populated_recent_files,
            settings=settings,
        )
        recent = model.find_collection("recent")
        assert recent is not None

        received: List = []
        original = model._item_changed

        def _spy(item):
            received.append(item)
            return original(item)

        model._item_changed = _spy  # type: ignore[method-assign]

        settings.set(_SETTINGS_KEY, ["mock://Home"])
        assert recent in received

    def test_nav_model_recent_sees_list_mutation_in_memory(
        self, populated_recent_files: RecentFileList,
    ):
        # When the in-memory :class:`RecentFileList` is mutated but
        # settings is NOT written (e.g. a pre-persist read), a manual
        # :meth:`refresh` must still reflect the new entries — the
        # cache is keyed on the collection, not on the list snapshot.
        from ovui_widgets.content.widget import NavigationModel

        model = NavigationModel(
            MockBackend(), recent_files=populated_recent_files,
        )
        recent = model.find_collection("recent")
        first = list(model.get_item_children(recent))
        populated_recent_files.add("mock://Home/Scripts/test.py")
        # No settings — refresh is the caller's responsibility.
        assert isinstance(recent, RecentFilesCollection)
        recent.refresh()
        second = list(model.get_item_children(recent))
        assert len(second) == len(first) + 1
        assert second[0].url == "mock://Home/Scripts/test.py"

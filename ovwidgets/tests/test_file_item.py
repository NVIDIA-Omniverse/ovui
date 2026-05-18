# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`ovwidgets.content.widget.file_item.FileItem`.

See the content browser implementation step 6. Covers construction, property surface, lazy
``SimpleStringModel`` allocation, icon-key derivation, folder/leaf
mutex selection, the ``populate`` state machine (OK / ERROR_NOT_FOUND
/ refresh / name-stable reuse / mark_dirty cycle), concurrent child
mutation via two threads, and the two module-level formatters
(``_format_size`` / ``_format_date``).
"""

from __future__ import annotations

import datetime
import threading
from collections import OrderedDict

import omni.ui as ui
import pytest

from ovwidgets.app.testing import MockBackend
from ovwidgets.common.asset_types import AssetCategory, get_category
from ovwidgets.content.backends.backend_adapter import (
    BackendFileFlags,
    BackendListEntry,
    BackendResult,
)
from ovwidgets.content.widget import FileItem as FileItemReexport
from ovwidgets.content.widget.file_item import (
    FileItem,
    _format_date,
    _format_size,
    _NoLock,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def backend() -> MockBackend:
    """Fresh :class:`MockBackend` with the default deterministic tree."""
    return MockBackend()


@pytest.fixture
def home_folder() -> FileItem:
    """Top-level folder item representing ``mock://Home``."""
    return FileItem("mock://Home", "Home", is_folder=True)


@pytest.fixture
def usd_leaf() -> FileItem:
    """Unpopulated USD leaf item for icon / category assertions."""
    return FileItem(
        "mock://Home/Documents/Projects/demo.usda",
        "demo.usda",
        is_folder=False,
        size=128,
        modified=1767225600.0,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Import / re-export surface
# ──────────────────────────────────────────────────────────────────────────────

class TestImports:
    def test_file_item_reexported_from_widget_package(self):
        assert FileItemReexport is FileItem

    def test_widget_package_all_contains_file_item(self):
        import ovwidgets.content.widget as pkg

        assert "FileItem" in pkg.__all__

    def test_is_abstract_item_subclass(self):
        assert issubclass(FileItem, ui.AbstractItem)


# ──────────────────────────────────────────────────────────────────────────────
# Construction and properties
# ──────────────────────────────────────────────────────────────────────────────

class TestConstruction:
    def test_folder_item_has_children_list(self, home_folder: FileItem):
        assert home_folder.is_folder is True
        assert home_folder.children == []

    def test_leaf_item_is_not_folder(self, usd_leaf: FileItem):
        assert usd_leaf.is_folder is False
        # Leaves always have an empty children list — mutation is a
        # no-op for them but the property must still be callable.
        assert usd_leaf.children == []

    def test_default_parent_is_none(self, home_folder: FileItem):
        assert home_folder.parent is None

    def test_parent_assigned_when_passed(self, home_folder: FileItem):
        child = FileItem(
            "mock://Home/Textures", "Textures", is_folder=True,
            parent=home_folder,
        )
        assert child.parent is home_folder

    def test_size_defaults_to_zero(self, home_folder: FileItem):
        assert home_folder.size == 0

    def test_modified_defaults_to_zero(self, home_folder: FileItem):
        assert home_folder.modified == 0.0

    def test_size_preserved_from_constructor(self, usd_leaf: FileItem):
        assert usd_leaf.size == 128

    def test_modified_preserved_from_constructor(self, usd_leaf: FileItem):
        assert usd_leaf.modified == 1767225600.0

    def test_url_preserved_from_constructor(self):
        item = FileItem("mock://Home", "Home", is_folder=True)
        assert item.url == "mock://Home"

    def test_name_preserved_from_constructor(self):
        item = FileItem("mock://Home", "Home", is_folder=True)
        assert item.name == "Home"

    def test_populated_starts_false(self, home_folder: FileItem):
        assert home_folder.populated is False

    def test_folder_category_is_folder_enum(self, home_folder: FileItem):
        assert home_folder.category is AssetCategory.FOLDER


# ──────────────────────────────────────────────────────────────────────────────
# Icon key / category derivation
# ──────────────────────────────────────────────────────────────────────────────

class TestIconKey:
    def test_icon_key_for_folder_is_asset_folder(self, home_folder: FileItem):
        assert home_folder.icon_key == "asset_folder"

    def test_icon_key_for_usd_file_is_asset_usd(self, usd_leaf: FileItem):
        assert usd_leaf.icon_key == "asset_usd"

    @pytest.mark.parametrize(
        ("filename", "expected_key"),
        [
            ("demo.usda",     "asset_usd"),
            ("demo.usdc",     "asset_usd"),
            ("scene.usdz",    "asset_usd"),
            ("tex.png",       "asset_image"),
            ("tex.jpg",       "asset_image"),
            ("tex.hdr",       "asset_image"),
            ("mat.mdl",       "asset_material"),
            ("mat.mtlx",      "asset_material"),
            ("char.fbx",      "asset_model"),
            ("model.obj",     "asset_model"),
            ("clip.wav",      "asset_sound"),
            ("clip.mp3",      "asset_sound"),
            ("script.py",     "asset_script"),
            ("cloud.vdb",     "asset_volume"),
            ("notes.txt",     "asset_text"),
            ("data.json",     "asset_text"),
            ("bundle.zip",    "asset_archive"),
            ("archive.tar.gz","asset_archive"),
            ("unknown.xyz",   "asset_unknown"),
            ("no_extension",  "asset_unknown"),
        ],
    )
    def test_icon_key_matches_category_mapping(self, filename, expected_key):
        item = FileItem(f"mock://Home/{filename}", filename, is_folder=False)
        assert item.icon_key == expected_key

    def test_category_matches_get_category(self, usd_leaf: FileItem):
        # The category property must agree with the module-level
        # dispatcher in :mod:`ovwidgets.common.asset_types`. They disagree only
        # for folders, which short-circuit because the backend flag is
        # authoritative.
        assert usd_leaf.category is get_category("demo.usda")

    @pytest.mark.parametrize(
        ("filename", "expected_category"),
        [
            ("a.usda",    AssetCategory.USD),
            ("b.png",     AssetCategory.IMAGE),
            ("c.mdl",     AssetCategory.MATERIAL),
            ("d.fbx",     AssetCategory.MODEL),
            ("e.wav",     AssetCategory.SOUND),
            ("f.py",      AssetCategory.SCRIPT),
            ("g.vdb",     AssetCategory.VOLUME),
            ("h.md",      AssetCategory.TEXT),
            ("i.zip",     AssetCategory.ARCHIVE),
            ("j.unknown", AssetCategory.UNKNOWN),
        ],
    )
    def test_category_matches_extension(self, filename, expected_category):
        item = FileItem(f"mock://{filename}", filename, is_folder=False)
        assert item.category is expected_category

    def test_uppercase_extension_still_matches(self):
        # ``get_category`` is case-insensitive, so icon derivation
        # should match regardless of how a backend capitalises
        # filenames.
        item = FileItem("mock://Home/A.USD", "A.USD", is_folder=False)
        assert item.category is AssetCategory.USD
        assert item.icon_key == "asset_usd"


# ──────────────────────────────────────────────────────────────────────────────
# Lazy value models
# ──────────────────────────────────────────────────────────────────────────────

class TestLazyModels:
    def test_name_model_is_lazy(self, home_folder: FileItem):
        assert home_folder._name_model is None
        model = home_folder.get_name_model()
        assert model is not None
        assert home_folder._name_model is model

    def test_size_model_is_lazy(self, home_folder: FileItem):
        assert home_folder._size_model is None
        home_folder.get_size_model()
        assert home_folder._size_model is not None

    def test_date_model_is_lazy(self, home_folder: FileItem):
        assert home_folder._date_model is None
        home_folder.get_date_model()
        assert home_folder._date_model is not None

    def test_get_name_model_cached(self, usd_leaf: FileItem):
        a = usd_leaf.get_name_model()
        b = usd_leaf.get_name_model()
        assert a is b

    def test_get_size_model_cached(self, usd_leaf: FileItem):
        a = usd_leaf.get_size_model()
        b = usd_leaf.get_size_model()
        assert a is b

    def test_get_date_model_cached(self, usd_leaf: FileItem):
        a = usd_leaf.get_date_model()
        b = usd_leaf.get_date_model()
        assert a is b

    def test_name_model_value_is_name(self, usd_leaf: FileItem):
        assert usd_leaf.get_name_model().get_value_as_string() == "demo.usda"

    def test_size_model_value_is_formatted(self, usd_leaf: FileItem):
        assert usd_leaf.get_size_model().get_value_as_string() == "128 B"

    def test_size_model_for_folder_is_empty_string(self, home_folder: FileItem):
        assert home_folder.get_size_model().get_value_as_string() == ""

    def test_date_model_for_zero_is_empty(self, home_folder: FileItem):
        assert home_folder.get_date_model().get_value_as_string() == ""

    def test_date_model_for_nonzero_matches_formatter(self, usd_leaf: FileItem):
        assert (
            usd_leaf.get_date_model().get_value_as_string()
            == _format_date(1767225600.0)
        )

    def test_name_model_returns_simple_string_model(self, usd_leaf: FileItem):
        assert isinstance(usd_leaf.get_name_model(), ui.SimpleStringModel)

    def test_size_model_returns_simple_string_model(self, usd_leaf: FileItem):
        assert isinstance(usd_leaf.get_size_model(), ui.SimpleStringModel)

    def test_date_model_returns_simple_string_model(self, usd_leaf: FileItem):
        assert isinstance(usd_leaf.get_date_model(), ui.SimpleStringModel)


# ──────────────────────────────────────────────────────────────────────────────
# populate(backend)
# ──────────────────────────────────────────────────────────────────────────────

class TestPopulate:
    def test_populate_fills_children_from_backend(
        self, backend: MockBackend, home_folder: FileItem,
    ):
        result = home_folder.populate(backend)
        assert result is BackendResult.OK
        names = [c.name for c in home_folder.children]
        assert names == ["Documents", "Textures", "Scripts", ".hidden_folder"]

    def test_populate_sets_populated_flag(
        self, backend: MockBackend, home_folder: FileItem,
    ):
        assert home_folder.populated is False
        home_folder.populate(backend)
        assert home_folder.populated is True

    def test_populate_assigns_parent_back_reference(
        self, backend: MockBackend, home_folder: FileItem,
    ):
        home_folder.populate(backend)
        for child in home_folder.children:
            assert child.parent is home_folder

    def test_populate_on_missing_url_returns_error_not_found(
        self, backend: MockBackend,
    ):
        ghost = FileItem("mock://does_not_exist", "does_not_exist", is_folder=True)
        result = ghost.populate(backend)
        assert result is BackendResult.ERROR_NOT_FOUND
        assert ghost.populated is False
        assert ghost.children == []

    def test_populate_on_injected_access_denied_returns_error(
        self, backend: MockBackend, home_folder: FileItem,
    ):
        backend._errors["mock://Home"] = BackendResult.ERROR_ACCESS_DENIED
        result = home_folder.populate(backend)
        assert result is BackendResult.ERROR_ACCESS_DENIED
        assert home_folder.populated is False

    def test_populate_on_leaf_returns_error_without_contacting_backend(
        self, usd_leaf: FileItem,
    ):
        # Pass a sentinel that would raise AttributeError if touched —
        # proves populate short-circuits on leaves.
        result = usd_leaf.populate(backend=object())  # type: ignore[arg-type]
        assert result is BackendResult.ERROR
        assert usd_leaf.populated is False

    def test_populate_sets_is_folder_flag_on_children(
        self, backend: MockBackend, home_folder: FileItem,
    ):
        home_folder.populate(backend)
        for child in home_folder.children:
            assert child.is_folder is True  # Every Home entry is a folder

    def test_populate_sets_sizes_on_file_children(
        self, backend: MockBackend,
    ):
        projects = FileItem(
            "mock://Home/Documents/Projects", "Projects", is_folder=True,
        )
        projects.populate(backend)
        sizes = {c.name: c.size for c in projects.children}
        assert sizes == {"demo.usda": 128, "demo.usdc": 2048, "readme.md": 512}

    def test_populate_replaces_children_on_refresh(
        self, backend: MockBackend, home_folder: FileItem,
    ):
        home_folder.populate(backend)
        # Delete one entry in the backend and repopulate — the missing
        # name must vanish from the item's children.
        backend.delete("mock://Home/Textures")
        home_folder.mark_dirty()
        home_folder.populate(backend)
        names = [c.name for c in home_folder.children]
        assert "Textures" not in names
        assert names == ["Documents", "Scripts", ".hidden_folder"]

    def test_populate_preserves_existing_items_by_name(
        self, backend: MockBackend, home_folder: FileItem,
    ):
        home_folder.populate(backend)
        first_documents = next(
            c for c in home_folder.children if c.name == "Documents"
        )
        # Second populate — Documents still exists — should reuse the
        # exact same object (preserving expansion state, references,
        # lazy model instances).
        home_folder.mark_dirty()
        home_folder.populate(backend)
        second_documents = next(
            c for c in home_folder.children if c.name == "Documents"
        )
        assert first_documents is second_documents

    def test_populate_updates_metadata_on_reused_items(
        self, backend: MockBackend,
    ):
        projects = FileItem(
            "mock://Home/Documents/Projects", "Projects", is_folder=True,
        )
        projects.populate(backend)
        demo = next(c for c in projects.children if c.name == "demo.usdc")
        # Touch the underlying mock entry so the next populate pushes
        # fresh metadata through ``update_metadata``.
        node, _ = backend._find("mock://Home/Documents/Projects/demo.usdc")
        assert node is not None
        node.size = 9999
        node.modified = 1800000000.0
        projects.mark_dirty()
        projects.populate(backend)
        assert demo.size == 9999
        assert demo.modified == 1800000000.0

    def test_populate_preserves_lazy_models_on_reused_item(
        self, backend: MockBackend,
    ):
        projects = FileItem(
            "mock://Home/Documents/Projects", "Projects", is_folder=True,
        )
        projects.populate(backend)
        demo = next(c for c in projects.children if c.name == "demo.usdc")
        original_name_model = demo.get_name_model()
        projects.mark_dirty()
        projects.populate(backend)
        # Same item identity → same cached model instance.
        assert demo.get_name_model() is original_name_model

    def test_populate_pushes_updated_size_through_size_model(
        self, backend: MockBackend,
    ):
        projects = FileItem(
            "mock://Home/Documents/Projects", "Projects", is_folder=True,
        )
        projects.populate(backend)
        demo = next(c for c in projects.children if c.name == "demo.usdc")
        size_model = demo.get_size_model()
        assert size_model.get_value_as_string() == "2.0 KB"
        node, _ = backend._find("mock://Home/Documents/Projects/demo.usdc")
        assert node is not None
        node.size = 10 * 1024 * 1024
        projects.mark_dirty()
        projects.populate(backend)
        assert size_model.get_value_as_string() == "10.0 MB"

    def test_populate_adds_new_entries_on_refresh(
        self, backend: MockBackend, home_folder: FileItem,
    ):
        home_folder.populate(backend)
        backend.create_folder("mock://Home/NewFolder")
        home_folder.mark_dirty()
        home_folder.populate(backend)
        names = [c.name for c in home_folder.children]
        assert "NewFolder" in names

    def test_mark_dirty_allows_repopulate(
        self, backend: MockBackend, home_folder: FileItem,
    ):
        home_folder.populate(backend)
        assert home_folder.populated is True
        home_folder.mark_dirty()
        assert home_folder.populated is False

    def test_populate_is_idempotent_after_ok(
        self, backend: MockBackend, home_folder: FileItem,
    ):
        r1 = home_folder.populate(backend)
        r2 = home_folder.populate(backend)
        assert r1 is r2 is BackendResult.OK
        assert home_folder.populated is True

    def test_populate_after_ok_does_not_rehit_backend(
        self, backend: MockBackend, home_folder: FileItem,
    ):
        """Populated folders short-circuit; no second ``list_dir`` call.

        The plan's state-machine contract says the second populate is
        a no-op absent ``mark_dirty()``. Spy on ``list_dir`` to pin
        the no-backend-round-trip invariant — without this a future
        edit could silently reintroduce a hot-path backend call.
        """
        call_count = 0
        real_list_dir = backend.list_dir

        def spy(url):
            nonlocal call_count
            call_count += 1
            return real_list_dir(url)

        backend.list_dir = spy  # type: ignore[method-assign]
        home_folder.populate(backend)
        home_folder.populate(backend)
        assert call_count == 1

    def test_populate_after_mark_dirty_rehits_backend(
        self, backend: MockBackend, home_folder: FileItem,
    ):
        call_count = 0
        real_list_dir = backend.list_dir

        def spy(url):
            nonlocal call_count
            call_count += 1
            return real_list_dir(url)

        backend.list_dir = spy  # type: ignore[method-assign]
        home_folder.populate(backend)
        home_folder.mark_dirty()
        home_folder.populate(backend)
        assert call_count == 2

    def test_populate_error_leaves_populated_false(
        self, backend: MockBackend, home_folder: FileItem,
    ):
        # Successful populate, then inject an error for the refresh —
        # the error must leave the flag False so a retry goes through.
        home_folder.populate(backend)
        home_folder.mark_dirty()
        backend._errors["mock://Home"] = BackendResult.ERROR_CONNECTION
        assert home_folder.populate(backend) is BackendResult.ERROR_CONNECTION
        assert home_folder.populated is False

    def test_populate_uses_backend_join_url_for_children(
        self, backend: MockBackend, home_folder: FileItem,
    ):
        home_folder.populate(backend)
        documents = next(
            c for c in home_folder.children if c.name == "Documents"
        )
        # ``join_url`` composes the backend-canonical form — no raw
        # string concatenation that could drop the scheme prefix.
        assert documents.url == "mock://Home/Documents"


# ──────────────────────────────────────────────────────────────────────────────
# add_child / remove_child
# ──────────────────────────────────────────────────────────────────────────────

class TestChildMutation:
    def test_add_child_inserts_by_name(self, home_folder: FileItem):
        child = FileItem("mock://Home/New", "New", is_folder=False)
        home_folder.add_child(child)
        assert home_folder.children == [child]

    def test_add_child_sets_parent_back_reference(self, home_folder: FileItem):
        child = FileItem("mock://Home/New", "New", is_folder=False)
        home_folder.add_child(child)
        assert child.parent is home_folder

    def test_add_child_overwrites_same_name(self, home_folder: FileItem):
        a = FileItem("mock://Home/X", "X", is_folder=False)
        b = FileItem("mock://Home/X", "X", is_folder=False, size=5)
        home_folder.add_child(a)
        home_folder.add_child(b)
        assert home_folder.children == [b]

    def test_remove_child_returns_removed(self, home_folder: FileItem):
        child = FileItem("mock://Home/New", "New", is_folder=False)
        home_folder.add_child(child)
        assert home_folder.remove_child("New") is child
        assert home_folder.children == []

    def test_remove_child_missing_returns_none(self, home_folder: FileItem):
        assert home_folder.remove_child("nope") is None

    def test_remove_child_uses_pop_not_del(self, home_folder: FileItem):
        # Regression guard: if ``remove_child`` is rewritten to ``del``
        # a missing name raises KeyError. Pop returns None.
        assert home_folder.remove_child("does_not_exist") is None


# ──────────────────────────────────────────────────────────────────────────────
# update_metadata
# ──────────────────────────────────────────────────────────────────────────────

class TestUpdateMetadata:
    def _entry(self, name: str, size: int, modified: float) -> BackendListEntry:
        return BackendListEntry(
            name=name, flags=BackendFileFlags.NONE,
            size=size, modified_time=modified, created_time=0.0,
        )

    def test_update_metadata_rewrites_size(self, usd_leaf: FileItem):
        usd_leaf.update_metadata(self._entry("demo.usda", 4096, 0.0))
        assert usd_leaf.size == 4096

    def test_update_metadata_rewrites_modified(self, usd_leaf: FileItem):
        usd_leaf.update_metadata(self._entry("demo.usda", 128, 1800000000.0))
        assert usd_leaf.modified == 1800000000.0

    def test_update_metadata_without_size_model_does_not_allocate(
        self, usd_leaf: FileItem,
    ):
        usd_leaf.update_metadata(self._entry("demo.usda", 4096, 0.0))
        # Model was never requested — should still be None.
        assert usd_leaf._size_model is None

    def test_update_metadata_pushes_to_size_model_when_present(
        self, usd_leaf: FileItem,
    ):
        model = usd_leaf.get_size_model()
        usd_leaf.update_metadata(self._entry("demo.usda", 4 * 1024 * 1024, 0.0))
        assert model.get_value_as_string() == "4.0 MB"

    def test_update_metadata_pushes_to_date_model_when_present(
        self, usd_leaf: FileItem,
    ):
        model = usd_leaf.get_date_model()
        usd_leaf.update_metadata(self._entry("demo.usda", 128, 1800000000.0))
        assert model.get_value_as_string() == _format_date(1800000000.0)


# ──────────────────────────────────────────────────────────────────────────────
# _NoLock
# ──────────────────────────────────────────────────────────────────────────────

class TestNoLock:
    def test_nolock_enter_returns_self(self):
        lock = _NoLock()
        with lock as acquired:
            assert acquired is lock

    def test_nolock_exit_returns_false(self):
        lock = _NoLock()
        assert lock.__exit__(None, None, None) is False

    def test_folder_item_uses_real_lock(self):
        item = FileItem("mock://Home", "Home", is_folder=True)
        # Assert against the lock's public contract, not against
        # ``type(threading.Lock())`` — that type has shifted between
        # CPython versions and we only care that it behaves like a
        # real ``Lock``.
        assert not isinstance(item._mutex, _NoLock)
        assert hasattr(item._mutex, "acquire")
        assert hasattr(item._mutex, "release")

    def test_leaf_item_uses_nolock(self):
        item = FileItem("mock://a.txt", "a.txt", is_folder=False)
        assert isinstance(item._mutex, _NoLock)


# ──────────────────────────────────────────────────────────────────────────────
# Threading — two workers adding and removing children on the same folder
# ──────────────────────────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_add_remove_child_threadsafe(self):
        """Hammer a folder with three threads; no exceptions must escape.

        Two writers add and remove items on disjoint name prefixes;
        one reader spins on ``folder.children`` while the writers
        mutate. The ``_mutex`` is what keeps the reader from seeing
        the underlying ``OrderedDict`` mid-mutation — without it the
        snapshot list comprehension would race and occasionally raise
        ``RuntimeError: dictionary changed size during iteration``.
        The reader joining cleanly is the real assertion; the
        clean-up to an empty dict is a secondary consistency check.
        """
        folder = FileItem("mock://hammer", "hammer", is_folder=True)
        iterations = 500
        errors: list[BaseException] = []
        stop_reader = threading.Event()

        def writer(prefix: str) -> None:
            try:
                for i in range(iterations):
                    name = f"{prefix}{i}"
                    child = FileItem(
                        f"mock://hammer/{name}", name, is_folder=False,
                    )
                    folder.add_child(child)
                    folder.remove_child(name)
            except BaseException as exc:
                errors.append(exc)

        def reader() -> None:
            try:
                while not stop_reader.is_set():
                    # Iterate the snapshot — if mutex were absent this
                    # is the call that would race with writer mutation.
                    for _ in folder.children:
                        pass
            except BaseException as exc:
                errors.append(exc)

        r = threading.Thread(target=reader)
        w1 = threading.Thread(target=writer, args=("a",))
        w2 = threading.Thread(target=writer, args=("b",))
        r.start()
        w1.start()
        w2.start()
        w1.join(timeout=30)
        w2.join(timeout=30)
        stop_reader.set()
        r.join(timeout=30)
        assert not (w1.is_alive() or w2.is_alive() or r.is_alive())
        assert errors == []
        assert folder.children == []


# ──────────────────────────────────────────────────────────────────────────────
# mark_dirty
# ──────────────────────────────────────────────────────────────────────────────

class TestMarkDirty:
    def test_mark_dirty_clears_populated(self, backend, home_folder):
        home_folder.populate(backend)
        assert home_folder.populated
        home_folder.mark_dirty()
        assert not home_folder.populated

    def test_mark_dirty_does_not_touch_children(self, backend, home_folder):
        home_folder.populate(backend)
        snapshot = list(home_folder.children)
        home_folder.mark_dirty()
        # mark_dirty is a flag flip — it does not clear the cached
        # children dict. The next populate will diff against it.
        assert list(home_folder.children) == snapshot

    def test_mark_dirty_is_idempotent(self, backend, home_folder):
        home_folder.populate(backend)
        home_folder.mark_dirty()
        home_folder.mark_dirty()
        assert not home_folder.populated


# ──────────────────────────────────────────────────────────────────────────────
# _format_size
# ──────────────────────────────────────────────────────────────────────────────

class TestFormatSize:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0,            "0 B"),
            (1,            "1 B"),
            (1023,         "1023 B"),
            (1024,         "1.0 KB"),
            (1536,         "1.5 KB"),
            (1024 * 1024,  "1.0 MB"),
            (int(1.2 * 1024 * 1024), "1.2 MB"),
            (4 * 1024 * 1024,        "4.0 MB"),
            (1024 ** 3,    "1.0 GB"),
            (2 * 1024 ** 3,"2.0 GB"),
        ],
    )
    def test_format_size_values(self, value, expected):
        assert _format_size(value) == expected

    def test_format_size_accepts_float(self):
        # ``entry.size`` is ``int`` but defensive: an external caller
        # might pass a float; the formatter should coerce.
        assert _format_size(1024.0) == "1.0 KB"

    def test_format_size_negative_treated_as_zero(self):
        # Negative sizes are meaningless; coerce to 0 B rather than
        # emitting confusing negative-prefixed strings.
        assert _format_size(-1) == "0 B"

    def test_format_size_large_values_stay_in_gb(self):
        # Keep matching Kit behaviour: anything ≥ 1 GiB stays in GB
        # rather than escalating to TB. Nothing above GB has an
        # entry in ``_SIZE_UNITS`` — a regression here would hint the
        # unit table was touched.
        assert _format_size(1024 ** 4) == "1024.0 GB"


# ──────────────────────────────────────────────────────────────────────────────
# _format_date
# ──────────────────────────────────────────────────────────────────────────────

class TestFormatDate:
    def test_format_date_zero_returns_empty(self):
        # Zero covers both ``0`` (``int``) and ``0.0`` (``float``) —
        # the formatter rejects on truthiness, so one assertion is
        # enough to pin the "no timestamp yet" contract.
        assert _format_date(0) == "" == _format_date(0.0)

    def test_format_date_nonzero_nonzero_formats(self):
        # Guard against a future "return '' for anything before 1970"
        # regression: the formatter must format any non-falsy
        # timestamp, not silently drop small-but-nonzero values.
        out = _format_date(1.0)
        assert out and out != ""

    def test_format_date_round_trip_local_time(self):
        # Build the expected string from the same local-time
        # conversion the formatter uses — otherwise the test would be
        # time-zone-dependent.
        ts = 1767225600.0
        expected = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        assert _format_date(ts) == expected

    def test_format_date_shape_is_yyyy_mm_dd_hh_mm(self):
        # Loosely check the format without pinning a timezone: length,
        # separator positions, digit layout.
        out = _format_date(1767225600.0)
        assert len(out) == 16
        assert out[4] == "-" and out[7] == "-" and out[10] == " "
        assert out[13] == ":"
        assert out[:4].isdigit()
        assert out[5:7].isdigit() and out[8:10].isdigit()
        assert out[11:13].isdigit() and out[14:16].isdigit()


# ──────────────────────────────────────────────────────────────────────────────
# Internal data-structure invariants
# ──────────────────────────────────────────────────────────────────────────────

class TestInternalInvariants:
    def test_children_backing_store_is_ordered_dict(self):
        item = FileItem("mock://Home", "Home", is_folder=True)
        # The plan calls out OrderedDict explicitly (§Step 6 Details).
        # A dict-to-OrderedDict regression would silently break sort
        # stability in Step 7's model layer.
        assert isinstance(item._children, OrderedDict)

    def test_populated_listing_preserves_backend_order(
        self, backend: MockBackend,
    ):
        projects = FileItem(
            "mock://Home/Documents/Projects", "Projects", is_folder=True,
        )
        projects.populate(backend)
        assert [c.name for c in projects.children] == [
            "demo.usda", "demo.usdc", "readme.md",
        ]

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`ovwidgets.content.widget.file_browser_model.FileBrowserModel`.

See the content browser implementation step 7. Covers the public AbstractItemModel API,
folders-first + natural-number sort, all three filters (folder-only,
hidden, asset-type whitelist, text), cache semantics including
``set_root_url`` eviction, deferred ``_item_changed`` dispatch, and the
``_natural_sort_key`` helper used for name ordering.
"""

from __future__ import annotations

from typing import Any, List

import omni.ui as ui
import pytest

from ovwidgets.app.testing import MockBackend
from ovwidgets.common.asset_types import AssetCategory
from ovwidgets.content.backends.backend_adapter import BackendResult
from ovwidgets.content.widget import (
    FileBrowserModel as FileBrowserModelReexport,
)
from ovwidgets.content.widget import (
    FileBrowserSortPolicy as FileBrowserSortPolicyReexport,
)
from ovwidgets.content.widget import (
    FileItem,
)
from ovwidgets.content.widget.file_browser_model import (
    FileBrowserModel,
    FileBrowserSortPolicy,
    _natural_sort_key,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def backend() -> MockBackend:
    """Fresh :class:`MockBackend` with the default deterministic tree."""
    return MockBackend()


@pytest.fixture
def model(backend: MockBackend) -> FileBrowserModel:
    """Model rooted at ``mock://Home``."""
    return FileBrowserModel(backend, "mock://Home")


class _RecordingBackend(MockBackend):
    """Mock backend that counts how often ``list_dir`` is called.

    Used by tests that verify laziness / idempotence / refresh-repopulates
    — pure spies are cheaper than monkey-patching on :class:`MockBackend`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.list_dir_calls: List[str] = []

    def list_dir(self, url: str):  # type: ignore[override]
        self.list_dir_calls.append(url)
        return super().list_dir(url)


# ──────────────────────────────────────────────────────────────────────────────
# Import / re-export surface
# ──────────────────────────────────────────────────────────────────────────────

class TestImports:
    def test_model_reexported_from_widget_package(self):
        assert FileBrowserModelReexport is FileBrowserModel

    def test_sort_policy_reexported_from_widget_package(self):
        assert FileBrowserSortPolicyReexport is FileBrowserSortPolicy

    def test_widget_package_all_contains_model(self):
        import ovwidgets.content.widget as pkg

        assert "FileBrowserModel" in pkg.__all__
        assert "FileBrowserSortPolicy" in pkg.__all__

    def test_is_abstract_item_model_subclass(self):
        assert issubclass(FileBrowserModel, ui.AbstractItemModel)


# ──────────────────────────────────────────────────────────────────────────────
# Natural sort helper
# ──────────────────────────────────────────────────────────────────────────────

class TestNaturalSortKey:
    def test_natural_sort_key_numeric_ordering(self):
        # 2.usd must sort before 10.usd — the canonical OM-12985 case.
        assert _natural_sort_key("2.usd") < _natural_sort_key("10.usd")

    def test_natural_sort_key_case_insensitive(self):
        assert _natural_sort_key("FILE.USD") == _natural_sort_key("file.usd")

    def test_natural_sort_key_pure_text(self):
        assert _natural_sort_key("alpha") < _natural_sort_key("beta")

    def test_natural_sort_key_digits_sort_before_text(self):
        # Leading tag ``(0, int)`` vs ``(1, str)`` puts numeric runs first.
        assert _natural_sort_key("1.txt") < _natural_sort_key("alpha.txt")

    def test_natural_sort_key_mixed_digits_and_text(self):
        # "frame_2" before "frame_10" even though lexically it would flip.
        assert _natural_sort_key("frame_2") < _natural_sort_key("frame_10")

    def test_natural_sort_key_preserves_same_digit_count(self):
        # Padded zeros still produce the same int.
        assert _natural_sort_key("001") == _natural_sort_key("1")

    def test_natural_sort_key_empty_string_yields_empty_tuple(self):
        assert _natural_sort_key("") == ()

    def test_natural_sort_key_trailing_digits(self):
        assert _natural_sort_key("part2") < _natural_sort_key("part10")


# ──────────────────────────────────────────────────────────────────────────────
# Construction
# ──────────────────────────────────────────────────────────────────────────────

class TestConstruction:
    def test_creates_root_in_cache(self, model: FileBrowserModel):
        assert "mock://Home" in model._cache
        assert model._cache["mock://Home"] is model.root

    def test_root_url_is_normalized(self, backend: MockBackend):
        # Double-slash / dot path normalizes.
        m = FileBrowserModel(backend, "mock://Home/./")
        assert m.root_url == "mock://Home"

    def test_default_sort_policy_is_name_asc(self, model: FileBrowserModel):
        assert model._sort_policy == FileBrowserSortPolicy.NAME_ASC

    def test_default_folder_only_false(self, model: FileBrowserModel):
        assert model._folder_only is False

    def test_default_show_hidden_false(self, model: FileBrowserModel):
        assert model._show_hidden is False

    def test_default_text_filter_empty(self, model: FileBrowserModel):
        assert model._text_filter == ""

    def test_default_asset_type_whitelist_none(self, model: FileBrowserModel):
        assert model._asset_type_whitelist is None

    def test_custom_folder_only_is_honoured(self, backend: MockBackend):
        m = FileBrowserModel(backend, "mock://Home", folder_only=True)
        assert m._folder_only is True

    def test_custom_sort_policy_is_honoured(self, backend: MockBackend):
        m = FileBrowserModel(
            backend, "mock://Home", sort_policy=FileBrowserSortPolicy.DATE_DESC,
        )
        assert m._sort_policy == FileBrowserSortPolicy.DATE_DESC

    def test_root_is_file_item_instance(self, model: FileBrowserModel):
        assert isinstance(model.root, FileItem)

    def test_root_is_folder(self, model: FileBrowserModel):
        assert model.root.is_folder is True


# ──────────────────────────────────────────────────────────────────────────────
# AbstractItemModel — get_item_children
# ──────────────────────────────────────────────────────────────────────────────

class TestGetItemChildren:
    def test_get_item_children_of_root_returns_children_after_populate(
        self, model: FileBrowserModel,
    ):
        children = model.get_item_children(model.root)
        names = [c.name for c in children]
        # Default MockBackend Home has Documents / Scripts / Textures visible
        # plus .hidden_folder hidden. Folder-only off, hidden off → three.
        assert names == ["Documents", "Scripts", "Textures"]

    def test_get_item_children_of_none_treats_as_root(
        self, model: FileBrowserModel,
    ):
        none_children = model.get_item_children(None)
        root_children = model.get_item_children(model.root)
        assert [c.name for c in none_children] == [c.name for c in root_children]

    def test_get_item_children_of_leaf_returns_empty(
        self, model: FileBrowserModel,
    ):
        # Descend to a leaf first so we have an actual FileItem.
        model.get_item_children(model.root)
        docs = next(
            c for c in model.get_item_children(model.root) if c.name == "Documents"
        )
        projects = next(
            c for c in model.get_item_children(docs) if c.name == "Projects"
        )
        demo = next(
            c for c in model.get_item_children(projects) if c.name == "demo.usda"
        )
        assert model.get_item_children(demo) == []

    def test_get_item_children_of_non_file_item_returns_empty(
        self, model: FileBrowserModel,
    ):
        # ui.AbstractItem instance that isn't a FileItem.
        foreign = ui.AbstractItem()
        assert model.get_item_children(foreign) == []

    def test_get_item_children_populates_lazily_on_first_call(
        self, model: FileBrowserModel,
    ):
        assert model.root.populated is False
        model.get_item_children(model.root)
        assert model.root.populated is True

    def test_get_item_children_second_call_does_not_re_hit_backend(self):
        recording = _RecordingBackend()
        m = FileBrowserModel(recording, "mock://Home")
        m.get_item_children(m.root)
        first_count = len(recording.list_dir_calls)
        m.get_item_children(m.root)
        assert len(recording.list_dir_calls) == first_count

    def test_get_item_children_adds_to_cache(self, model: FileBrowserModel):
        children = model.get_item_children(model.root)
        for child in children:
            assert model._cache.get(child.url) is child

    def test_get_item_children_on_access_denied_returns_empty(self):
        backend = MockBackend()
        backend._errors["mock://Home"] = BackendResult.ERROR_ACCESS_DENIED
        m = FileBrowserModel(backend, "mock://Home")
        # Should not raise; returns empty snapshot.
        assert m.get_item_children(m.root) == []
        # Left unpopulated so a retry still has a chance.
        assert m.root.populated is False


# ──────────────────────────────────────────────────────────────────────────────
# Filters
# ──────────────────────────────────────────────────────────────────────────────

class TestFolderOnlyFilter:
    def test_folder_only_hides_files(self, model: FileBrowserModel):
        # Drill into Projects which contains both files and no subfolders;
        # the Home level is all folders already.
        model._folder_only = True
        projects_parent = next(
            c for c in model.get_item_children(model.root) if c.name == "Documents"
        )
        # Documents contains a subfolder "Projects" only — perfect for this
        # test because with folder_only on, we expect just Projects.
        children = model.get_item_children(projects_parent)
        assert [c.name for c in children] == ["Projects"]
        # And Projects itself contains only files → folder_only returns [].
        projects = children[0]
        assert model.get_item_children(projects) == []

    def test_folder_only_off_shows_files(self, model: FileBrowserModel):
        # Drill into Projects which contains .usda/.usdc/.md files.
        docs = next(
            c for c in model.get_item_children(model.root) if c.name == "Documents"
        )
        projects = next(
            c for c in model.get_item_children(docs) if c.name == "Projects"
        )
        children = model.get_item_children(projects)
        names = [c.name for c in children]
        assert "demo.usda" in names
        assert "readme.md" in names


class TestShowHiddenFilter:
    def test_show_hidden_controls_visibility_of_dotfiles(
        self, model: FileBrowserModel,
    ):
        # Default: hidden entries suppressed.
        names = [c.name for c in model.get_item_children(model.root)]
        assert ".hidden_folder" not in names

        model.set_show_hidden(True)
        names = [c.name for c in model.get_item_children(model.root)]
        assert ".hidden_folder" in names

    def test_show_hidden_toggle_back_off(self, model: FileBrowserModel):
        model.set_show_hidden(True)
        model.set_show_hidden(False)
        names = [c.name for c in model.get_item_children(model.root)]
        assert ".hidden_folder" not in names


class TestAssetTypeWhitelist:
    def test_asset_type_whitelist_filters_usd_only(self, model: FileBrowserModel):
        # Drill to Projects which has .usda / .usdc / .md.
        docs = next(
            c for c in model.get_item_children(model.root) if c.name == "Documents"
        )
        projects = next(
            c for c in model.get_item_children(docs) if c.name == "Projects"
        )
        model.set_asset_type_whitelist({AssetCategory.USD})
        names = [c.name for c in model.get_item_children(projects)]
        assert "demo.usda" in names
        assert "demo.usdc" in names
        assert "readme.md" not in names

    def test_asset_type_whitelist_none_allows_all(self, model: FileBrowserModel):
        docs = next(
            c for c in model.get_item_children(model.root) if c.name == "Documents"
        )
        projects = next(
            c for c in model.get_item_children(docs) if c.name == "Projects"
        )
        model.set_asset_type_whitelist({AssetCategory.USD})
        model.set_asset_type_whitelist(None)
        names = [c.name for c in model.get_item_children(projects)]
        assert "readme.md" in names
        assert "demo.usda" in names

    def test_asset_type_whitelist_folders_always_pass(
        self, model: FileBrowserModel,
    ):
        # Home contains only folders — with a whitelist that excludes
        # folders' category, folders must still appear.
        model.set_asset_type_whitelist({AssetCategory.IMAGE})
        names = [c.name for c in model.get_item_children(model.root)]
        assert "Documents" in names
        assert "Scripts" in names
        assert "Textures" in names


class TestGlobFilter:
    """Step 49 — :meth:`FileBrowserModel.set_glob_filter`.

    Covers normalisation (None / empty / whitespace / ``*.*`` sentinel),
    single- and multi-pattern matching, the always-pass carve-out for
    folders, case-insensitive matching, AND composition with the text
    filter + asset-type whitelist, and the :attr:`glob_filter`
    read-back property.
    """

    @staticmethod
    def _projects(model: FileBrowserModel):
        """Navigate root → Documents → Projects and return the item."""
        docs = next(
            c for c in model.get_item_children(model.root)
            if c.name == "Documents"
        )
        return next(
            c for c in model.get_item_children(docs) if c.name == "Projects"
        )

    def test_glob_filter_default_none(self, model: FileBrowserModel):
        """Fresh model has no glob filter — :attr:`glob_filter` is empty."""
        assert model.glob_filter == []

    def test_glob_filter_empty_list_is_no_filter(
        self, model: FileBrowserModel,
    ):
        projects = self._projects(model)
        model.set_glob_filter(["*.usd", "*.usda"])
        model.set_glob_filter([])
        names = [c.name for c in model.get_item_children(projects)]
        assert "readme.md" in names
        assert "demo.usda" in names

    def test_glob_filter_none_is_no_filter(self, model: FileBrowserModel):
        projects = self._projects(model)
        model.set_glob_filter(["*.usd"])
        model.set_glob_filter(None)
        names = [c.name for c in model.get_item_children(projects)]
        assert "readme.md" in names
        assert "demo.usda" in names

    def test_glob_filter_single_pattern(self, model: FileBrowserModel):
        projects = self._projects(model)
        model.set_glob_filter(["*.usda"])
        names = [c.name for c in model.get_item_children(projects)]
        assert "demo.usda" in names
        assert "demo.usdc" not in names
        assert "readme.md" not in names

    def test_glob_filter_multiple_patterns_or(
        self, model: FileBrowserModel,
    ):
        """Multiple patterns OR — a leaf passes if any matches."""
        projects = self._projects(model)
        model.set_glob_filter(["*.usda", "*.usdc"])
        names = [c.name for c in model.get_item_children(projects)]
        assert "demo.usda" in names
        assert "demo.usdc" in names
        assert "readme.md" not in names

    def test_glob_filter_strips_whitespace(self, model: FileBrowserModel):
        """Leading / trailing whitespace on a pattern is ignored."""
        projects = self._projects(model)
        model.set_glob_filter(["  *.usda  ", "\t*.usdc"])
        names = [c.name for c in model.get_item_children(projects)]
        assert "demo.usda" in names
        assert "demo.usdc" in names

    def test_glob_filter_drops_blank_entries(
        self, model: FileBrowserModel,
    ):
        projects = self._projects(model)
        model.set_glob_filter(["", "   ", "*.usda"])
        assert model.glob_filter == ["*.usda"]
        names = [c.name for c in model.get_item_children(projects)]
        assert "demo.usda" in names
        assert "readme.md" not in names

    def test_glob_filter_case_insensitive(self, backend: MockBackend):
        """An uppercase pattern matches a lowercase filename."""
        from ovwidgets.app.testing.mock_backend import _MockEntry

        root = _MockEntry(name="", is_folder=True)
        holder = _MockEntry(name="Holder", is_folder=True, parent=root)
        root.children["Holder"] = holder
        for name in ("MIXED.USD", "lower.usda", "Upper.Usdc"):
            holder.children[name] = _MockEntry(
                name=name, is_folder=False, parent=holder,
            )
        b = MockBackend(root=root)
        m = FileBrowserModel(b, "mock://Holder")
        m.set_glob_filter(["*.USD", "*.USDA"])
        names = [c.name for c in m.get_item_children(m.root)]
        assert "MIXED.USD" in names
        assert "lower.usda" in names
        assert "Upper.Usdc" not in names

    def test_glob_filter_all_files_sentinel_is_no_filter(
        self, model: FileBrowserModel,
    ):
        """``*.*`` is the "All files" sentinel — reduces to no filter.

        Without this carve-out, ``fnmatch("Makefile", "*.*")`` → False
        would hide every extension-less file under the "All files"
        selection, which contradicts the combo entry's label.
        """
        projects = self._projects(model)
        model.set_glob_filter(["*.*"])
        assert model.glob_filter == []
        names = [c.name for c in model.get_item_children(projects)]
        assert "readme.md" in names
        assert "demo.usda" in names
        assert "demo.usdc" in names

    def test_glob_filter_mixed_with_star_dot_star_reduces_to_none(
        self, model: FileBrowserModel,
    ):
        """``["*.usd", "*.*"]`` also reduces to no filter.

        The "All files" sentinel dominates regardless of any other
        pattern in the list — a user who picked a concrete entry plus
        "All files" is asking for everything.
        """
        model.set_glob_filter(["*.usd", "*.*"])
        assert model.glob_filter == []

    def test_glob_filter_folders_always_pass(
        self, model: FileBrowserModel,
    ):
        """Folders pass the glob filter regardless of pattern match.

        Home contains Documents / Scripts / Textures. A glob that
        only matches leaves (``*.usd``) must not hide the folders so
        the user can drill into a subtree whose leaves would otherwise
        be filtered out.
        """
        model.set_glob_filter(["*.usd"])
        names = [c.name for c in model.get_item_children(model.root)]
        assert "Documents" in names
        assert "Scripts" in names
        assert "Textures" in names

    def test_glob_filter_composes_with_text_filter_and(
        self, model: FileBrowserModel,
    ):
        """Text + glob → AND. A leaf must satisfy both to pass."""
        projects = self._projects(model)
        model.set_text_filter("demo")
        model.set_glob_filter(["*.usda"])
        names = [c.name for c in model.get_item_children(projects)]
        assert names == ["demo.usda"]

    def test_glob_filter_composes_with_asset_whitelist_and(
        self, model: FileBrowserModel,
    ):
        """Asset-type whitelist + glob → AND. A leaf must satisfy both."""
        projects = self._projects(model)
        model.set_asset_type_whitelist({AssetCategory.USD})
        model.set_glob_filter(["*.usda"])
        names = [c.name for c in model.get_item_children(projects)]
        assert "demo.usda" in names
        assert "demo.usdc" not in names  # USD category but wrong glob
        assert "readme.md" not in names  # Right glob (fails) + wrong type

    def test_glob_filter_property_returns_copy(
        self, model: FileBrowserModel,
    ):
        """:attr:`glob_filter` returns a fresh list — mutations don't leak."""
        model.set_glob_filter(["*.usda"])
        returned = model.glob_filter
        returned.append("*.usdc")
        assert model.glob_filter == ["*.usda"]


class TestTextFilter:
    def test_text_filter_matches_case_insensitive_substring(
        self, model: FileBrowserModel,
    ):
        # Drill to Projects which contains demo.usda / demo.usdc / readme.md.
        docs = next(
            c for c in model.get_item_children(model.root) if c.name == "Documents"
        )
        projects = next(
            c for c in model.get_item_children(docs) if c.name == "Projects"
        )
        model.set_text_filter("DEMO")
        names = [c.name for c in model.get_item_children(projects)]
        assert "demo.usda" in names
        assert "demo.usdc" in names
        assert "readme.md" not in names

    def test_text_filter_empty_disables(self, model: FileBrowserModel):
        model.set_text_filter("demo")
        model.set_text_filter("")
        docs = next(
            c for c in model.get_item_children(model.root) if c.name == "Documents"
        )
        projects = next(
            c for c in model.get_item_children(docs) if c.name == "Projects"
        )
        names = [c.name for c in model.get_item_children(projects)]
        assert "readme.md" in names


# ──────────────────────────────────────────────────────────────────────────────
# Sort policy
# ──────────────────────────────────────────────────────────────────────────────

class TestSortPolicy:
    def test_sort_policy_name_asc_puts_folders_first_then_natural_sort(
        self, backend: MockBackend,
    ):
        # Build a bespoke tree where folders and files mix and numbered
        # names would sort differently under lex vs natural.
        from ovwidgets.app.testing.mock_backend import _MockEntry  # type: ignore

        root = _MockEntry(name="", is_folder=True)
        parent = _MockEntry(name="Top", is_folder=True, parent=root)
        root.children["Top"] = parent
        for name, is_folder, size in [
            ("10.usd", False, 128),
            ("Zeta", True, 0),
            ("2.usd", False, 64),
            ("Alpha", True, 0),
        ]:
            entry = _MockEntry(
                name=name, is_folder=is_folder, size=size, parent=parent,
            )
            parent.children[name] = entry

        b = MockBackend(root=root)
        m = FileBrowserModel(b, "mock://Top")
        names = [c.name for c in m.get_item_children(m.root)]
        # Folders first, alphabetic (natural sort preserves alpha order).
        # Then files — natural sort puts 2.usd before 10.usd.
        assert names == ["Alpha", "Zeta", "2.usd", "10.usd"]

    def test_sort_policy_name_desc_reverses_within_each_group(
        self, model: FileBrowserModel,
    ):
        model.set_sort_policy(FileBrowserSortPolicy.NAME_DESC)
        names = [c.name for c in model.get_item_children(model.root)]
        # Home contains only folders — DESC just reverses them.
        assert names == ["Textures", "Scripts", "Documents"]

    def test_sort_policy_date_desc_reverses_by_mtime(
        self, backend: MockBackend,
    ):
        # Custom tree with distinct mtimes on the files.
        from ovwidgets.app.testing.mock_backend import _MockEntry  # type: ignore

        root = _MockEntry(name="", is_folder=True)
        parent = _MockEntry(name="Top", is_folder=True, parent=root)
        root.children["Top"] = parent
        for name, modified in [("a.usd", 100.0), ("b.usd", 300.0), ("c.usd", 200.0)]:
            entry = _MockEntry(
                name=name, is_folder=False, size=1, modified=modified, parent=parent,
            )
            parent.children[name] = entry

        b = MockBackend(root=root)
        m = FileBrowserModel(
            b, "mock://Top", sort_policy=FileBrowserSortPolicy.DATE_DESC,
        )
        names = [c.name for c in m.get_item_children(m.root)]
        # Newest first: b (300), c (200), a (100).
        assert names == ["b.usd", "c.usd", "a.usd"]

    def test_sort_policy_date_asc(self, backend: MockBackend):
        from ovwidgets.app.testing.mock_backend import _MockEntry  # type: ignore

        root = _MockEntry(name="", is_folder=True)
        parent = _MockEntry(name="Top", is_folder=True, parent=root)
        root.children["Top"] = parent
        for name, modified in [("a.usd", 100.0), ("b.usd", 300.0), ("c.usd", 200.0)]:
            entry = _MockEntry(
                name=name, is_folder=False, size=1, modified=modified, parent=parent,
            )
            parent.children[name] = entry

        b = MockBackend(root=root)
        m = FileBrowserModel(
            b, "mock://Top", sort_policy=FileBrowserSortPolicy.DATE_ASC,
        )
        names = [c.name for c in m.get_item_children(m.root)]
        assert names == ["a.usd", "c.usd", "b.usd"]

    def test_sort_policy_size_asc(self, backend: MockBackend):
        from ovwidgets.app.testing.mock_backend import _MockEntry  # type: ignore

        root = _MockEntry(name="", is_folder=True)
        parent = _MockEntry(name="Top", is_folder=True, parent=root)
        root.children["Top"] = parent
        for name, size in [("big.dat", 9000), ("small.dat", 10), ("mid.dat", 500)]:
            entry = _MockEntry(
                name=name, is_folder=False, size=size, parent=parent,
            )
            parent.children[name] = entry

        b = MockBackend(root=root)
        m = FileBrowserModel(
            b, "mock://Top", sort_policy=FileBrowserSortPolicy.SIZE_ASC,
        )
        names = [c.name for c in m.get_item_children(m.root)]
        assert names == ["small.dat", "mid.dat", "big.dat"]

    def test_sort_policy_size_desc(self, backend: MockBackend):
        from ovwidgets.app.testing.mock_backend import _MockEntry  # type: ignore

        root = _MockEntry(name="", is_folder=True)
        parent = _MockEntry(name="Top", is_folder=True, parent=root)
        root.children["Top"] = parent
        for name, size in [("big.dat", 9000), ("small.dat", 10), ("mid.dat", 500)]:
            entry = _MockEntry(
                name=name, is_folder=False, size=size, parent=parent,
            )
            parent.children[name] = entry

        b = MockBackend(root=root)
        m = FileBrowserModel(
            b, "mock://Top", sort_policy=FileBrowserSortPolicy.SIZE_DESC,
        )
        names = [c.name for c in m.get_item_children(m.root)]
        assert names == ["big.dat", "mid.dat", "small.dat"]

    def test_sort_policy_folders_always_above_files_under_date_sort(
        self, backend: MockBackend,
    ):
        from ovwidgets.app.testing.mock_backend import _MockEntry  # type: ignore

        root = _MockEntry(name="", is_folder=True)
        parent = _MockEntry(name="Top", is_folder=True, parent=root)
        root.children["Top"] = parent
        # A file mtime that is newer than any folder's mtime.
        _f_old = _MockEntry(
            name="Older", is_folder=True, modified=100.0, parent=parent,
        )
        _file = _MockEntry(
            name="zzz.usd", is_folder=False, size=1, modified=999.0, parent=parent,
        )
        parent.children["Older"] = _f_old
        parent.children["zzz.usd"] = _file

        b = MockBackend(root=root)
        m = FileBrowserModel(
            b, "mock://Top", sort_policy=FileBrowserSortPolicy.DATE_DESC,
        )
        names = [c.name for c in m.get_item_children(m.root)]
        # Folder must come first even though the file is newer.
        assert names == ["Older", "zzz.usd"]

    def test_unknown_sort_policy_falls_back_to_name_asc(
        self, model: FileBrowserModel,
    ):
        model.set_sort_policy("bogus_policy")
        names = [c.name for c in model.get_item_children(model.root)]
        assert names == ["Documents", "Scripts", "Textures"]


# ──────────────────────────────────────────────────────────────────────────────
# AbstractItemModel — can_item_have_children / value models
# ──────────────────────────────────────────────────────────────────────────────

class TestCanItemHaveChildren:
    def test_can_item_have_children_folder_vs_file(
        self, model: FileBrowserModel,
    ):
        docs = next(
            c for c in model.get_item_children(model.root) if c.name == "Documents"
        )
        projects = next(
            c for c in model.get_item_children(docs) if c.name == "Projects"
        )
        demo = next(
            c for c in model.get_item_children(projects) if c.name == "demo.usda"
        )

        assert model.can_item_have_children(docs) is True
        assert model.can_item_have_children(projects) is True
        assert model.can_item_have_children(demo) is False

    def test_can_item_have_children_for_non_file_item(
        self, model: FileBrowserModel,
    ):
        foreign = ui.AbstractItem()
        assert model.can_item_have_children(foreign) is False


class TestGetItemValueModel:
    def test_get_item_value_model_count_is_3(self, model: FileBrowserModel):
        assert model.get_item_value_model_count(model.root) == 3

    def test_get_item_value_model_count_is_3_for_none_header_query(
        self, model: FileBrowserModel,
    ):
        # Plug-in columns land later; for now header count matches items.
        assert model.get_item_value_model_count(None) == 3

    def test_get_item_value_model_returns_string_models(
        self, model: FileBrowserModel,
    ):
        item = model.root
        name_model = model.get_item_value_model(item, 0)
        size_model = model.get_item_value_model(item, 1)
        date_model = model.get_item_value_model(item, 2)

        assert isinstance(name_model, ui.SimpleStringModel)
        assert isinstance(size_model, ui.SimpleStringModel)
        assert isinstance(date_model, ui.SimpleStringModel)
        assert name_model.get_value_as_string() == "Home"

    def test_get_item_value_model_caches_per_item(self, model: FileBrowserModel):
        # Same column request returns the same underlying model (shared
        # with the FileItem's lazy-allocated cache).
        first = model.get_item_value_model(model.root, 0)
        second = model.get_item_value_model(model.root, 0)
        assert first is second

    def test_get_item_value_model_unknown_column_returns_none(
        self, model: FileBrowserModel,
    ):
        assert model.get_item_value_model(model.root, 7) is None

    def test_get_item_value_model_non_file_item_returns_none(
        self, model: FileBrowserModel,
    ):
        foreign = ui.AbstractItem()
        assert model.get_item_value_model(foreign, 0) is None


# ──────────────────────────────────────────────────────────────────────────────
# Refresh
# ──────────────────────────────────────────────────────────────────────────────

class TestRefreshItem:
    def test_refresh_item_repopulates_from_backend(self):
        recording = _RecordingBackend()
        m = FileBrowserModel(recording, "mock://Home")
        m.get_item_children(m.root)
        hits_before = len(recording.list_dir_calls)

        # Mutate the tree — add a new folder so the next populate
        # surfaces it.
        recording.create_folder("mock://Home/NewFolder")

        m.refresh_item(m.root)
        children = m.get_item_children(m.root)
        names = [c.name for c in children]
        assert "NewFolder" in names
        # One populate triggers two ``list_dir`` calls: the folder
        # itself plus the Step 25 thumbnail-discovery pass on
        # ``<folder>/.thumbs/256x256``. The thumb dir does not exist
        # in the default mock tree so the second call errors silently.
        assert len(recording.list_dir_calls) == hits_before + 2

    def test_refresh_item_ignores_non_file_item(self, model: FileBrowserModel):
        foreign = ui.AbstractItem()
        # Must not raise.
        model.refresh_item(foreign)  # type: ignore[arg-type]

    def test_refresh_all_refreshes_root(self):
        recording = _RecordingBackend()
        m = FileBrowserModel(recording, "mock://Home")
        m.get_item_children(m.root)

        recording.create_folder("mock://Home/NewFolder")
        m.refresh_all()
        names = [c.name for c in m.get_item_children(m.root)]
        assert "NewFolder" in names


# ──────────────────────────────────────────────────────────────────────────────
# Root navigation
# ──────────────────────────────────────────────────────────────────────────────

class TestSetRootUrl:
    def test_set_root_url_changes_root(self, model: FileBrowserModel):
        model.set_root_url("mock://Shared")
        assert model.root_url == "mock://Shared"
        assert model.root.url == "mock://Shared"

    def test_set_root_url_evicts_stale_cache(self, model: FileBrowserModel):
        # Populate Home so multiple cache entries exist.
        children = model.get_item_children(model.root)
        assert "mock://Home/Documents" in model._cache

        model.set_root_url("mock://Shared")

        # Home and its children are now outside the new root.
        assert "mock://Home" not in model._cache
        assert "mock://Home/Documents" not in model._cache
        # New root is in the cache.
        assert "mock://Shared" in model._cache

    def test_set_root_url_is_noop_when_unchanged(self, model: FileBrowserModel):
        original_root = model.root
        model.set_root_url("mock://Home")
        assert model.root is original_root

    def test_set_root_url_normalizes_input(self, model: FileBrowserModel):
        model.set_root_url("mock://Shared/./")
        assert model.root_url == "mock://Shared"

    def test_set_root_url_preserves_descendants_of_new_root(
        self, model: FileBrowserModel,
    ):
        # Populate a deep path under Home first, then re-root to Home
        # (no change) and check nothing is evicted.
        docs = next(
            c for c in model.get_item_children(model.root) if c.name == "Documents"
        )
        model.get_item_children(docs)

        # No change in root — just verify the cache is populated.
        assert "mock://Home/Documents" in model._cache
        assert "mock://Home/Documents/Projects" in model._cache

        # Set to a subpath of the current root. Everything not under
        # the new root must be evicted, but mock://Home/Documents and
        # its descendants must remain.
        model.set_root_url("mock://Home/Documents")
        assert "mock://Home/Documents" in model._cache
        assert "mock://Home/Documents/Projects" in model._cache
        # The old root is outside the new root → evicted.
        assert "mock://Home" not in model._cache

    def test_set_root_url_does_not_evict_prefix_lookalike(self):
        # Build a tree with both "Home" and "Homework" at the top so
        # prefix matching without a trailing separator would over-match.
        from ovwidgets.app.testing.mock_backend import _MockEntry  # type: ignore

        root = _MockEntry(name="", is_folder=True)
        for name in ("Home", "Homework"):
            root.children[name] = _MockEntry(
                name=name, is_folder=True, parent=root,
            )

        b = MockBackend(root=root)
        m = FileBrowserModel(b, "mock://Home")
        # Prime the cache with Homework as a separate URL.
        m._get_or_create("mock://Homework", is_folder=True)
        assert "mock://Homework" in m._cache

        # Re-root to Home — Homework lives outside it, so it must be
        # evicted. The point of this test: eviction must not keep
        # "mock://Homework" around thinking it's a Home descendant.
        m.set_root_url("mock://Home")  # no-op
        # Force a real root change so eviction runs.
        m.set_root_url("mock://Homework")
        assert "mock://Homework" in m._cache
        assert "mock://Home" not in m._cache


# ──────────────────────────────────────────────────────────────────────────────
# Throttled item_changed dispatch
# ──────────────────────────────────────────────────────────────────────────────

class TestThrottledItemChanged:
    def test_schedule_item_changed_falls_back_to_immediate_without_application(
        self, model: FileBrowserModel,
    ):
        # No Application singleton → flush is synchronous; the pending
        # set is drained immediately.
        dispatched: List[Any] = []
        # Subscription must be held — the handle keeps the callback
        # alive; dropping it unsubscribes immediately.
        sub = model.subscribe_item_changed_fn(  # noqa: F841
            lambda m, item: dispatched.append(item)
        )
        model._schedule_item_changed(model.root)
        assert dispatched == [model.root]
        assert model._pending_item_changed == set()

    def test_schedule_item_changed_deduplicates_within_pending_set(
        self, model: FileBrowserModel,
    ):
        # Pre-populate pending set via the internal API so no flush
        # happens, then verify set-dedup semantics.
        # We temporarily spoof an already-scheduled flush by setting
        # the handle.
        model._item_changed_handle = object()
        model._schedule_item_changed(model.root)
        model._schedule_item_changed(model.root)
        # Set, not list — second add is a no-op.
        assert len(model._pending_item_changed) == 1

    def test_flush_item_changed_drains_pending(self, model: FileBrowserModel):
        dispatched: List[Any] = []
        sub = model.subscribe_item_changed_fn(  # noqa: F841
            lambda m, item: dispatched.append(item)
        )

        # Simulate: manually queue two items without firing dispatch.
        model._item_changed_handle = object()
        model._pending_item_changed.add(model.root)
        # Create a second item to queue.
        docs = next(
            c for c in model.get_item_children(model.root) if c.name == "Documents"
        )
        model._pending_item_changed.add(docs)

        # Manual flush.
        model._flush_item_changed()

        assert set(dispatched) == {model.root, docs}
        assert model._pending_item_changed == set()
        assert model._item_changed_handle is None


class TestThrottledWithApplication:
    """Uses the ``headless_app`` fixture so the deferred dispatch path
    (``Application.call_later``) is actually exercised."""

    def test_schedule_defers_to_next_frame(self, headless_app):
        b = MockBackend()
        m = FileBrowserModel(b, "mock://Home")
        dispatched: List[Any] = []
        sub = m.subscribe_item_changed_fn(  # noqa: F841
            lambda model, item: dispatched.append(item)
        )

        m._schedule_item_changed(m.root)
        # Not fired yet — deferred until the next frame update.
        assert dispatched == []
        assert m._pending_item_changed == {m.root}

        headless_app._on_frame_update(0.0)
        assert dispatched == [m.root]
        assert m._pending_item_changed == set()

    def test_multiple_schedules_coalesce_to_one_frame(self, headless_app):
        b = MockBackend()
        m = FileBrowserModel(b, "mock://Home")
        dispatched: List[Any] = []
        sub = m.subscribe_item_changed_fn(  # noqa: F841
            lambda model, item: dispatched.append(item)
        )

        m._schedule_item_changed(m.root)
        m._schedule_item_changed(m.root)
        m._schedule_item_changed(m.root)
        # Only one handle is scheduled.
        assert len(headless_app._pending_callbacks) == 1

        headless_app._on_frame_update(0.0)
        # Dispatch happened exactly once for the deduped root.
        assert dispatched == [m.root]

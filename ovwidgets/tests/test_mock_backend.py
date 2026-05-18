# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`ovwidgets.app.testing.MockBackend`.

See the content browser implementation step 3. Covers import surface, the default tree,
supports_url, stat / list_dir / create_folder / copy / move / delete
success and error paths, URL utilities (normalize / join / parent /
basename), error injection via ``_errors``, ``reset()`` teardown, and
flag decoding (IS_FOLDER / IS_HIDDEN / IS_READABLE / IS_WRITABLE).

No filesystem access, no timestamps pulled from ``time.time()`` — the
mock is fully deterministic, so tests can assert exact counts and
exact sizes.
"""

import pytest

from ovwidgets.app.testing import MockBackend
from ovwidgets.app.testing.mock_backend import (
    _BASE_TIME,
    _build_default_tree,
    _MockEntry,
    _parts_to_url,
    _url_to_parts,
)
from ovwidgets.content.backends import (
    BackendAdapter,
    BackendFileFlags,
    BackendListEntry,
    BackendResult,
)

# ──────────────────────────────────────────────────────────────────────────────
# Import / instantiation surface
# ──────────────────────────────────────────────────────────────────────────────

class TestImport:
    def test_mock_backend_exported_from_testing(self):
        from ovwidgets.app.testing import MockBackend as MB
        assert MB is MockBackend

    def test_package_all_contains_mock_backend(self):
        import ovwidgets.app.testing as pkg
        assert "MockBackend" in pkg.__all__

    def test_is_backend_adapter(self):
        assert isinstance(MockBackend(), BackendAdapter)

    def test_no_required_init_args(self):
        MockBackend()

    def test_accepts_custom_root(self):
        root = _MockEntry(name="", is_folder=True)
        b = MockBackend(root=root)
        assert b._root is root

    def test_scheme_constant_is_mock(self):
        assert MockBackend.SCHEME == "mock://"


# ──────────────────────────────────────────────────────────────────────────────
# URL parsing helpers
# ──────────────────────────────────────────────────────────────────────────────

class TestUrlParsing:
    def test_url_to_parts_root(self):
        assert _url_to_parts("mock://") == []

    def test_url_to_parts_triple_slash(self):
        assert _url_to_parts("mock:///") == []

    def test_url_to_parts_single_component(self):
        assert _url_to_parts("mock://Home") == ["Home"]

    def test_url_to_parts_deep(self):
        assert _url_to_parts("mock://Home/Documents/Projects") == [
            "Home", "Documents", "Projects",
        ]

    def test_url_to_parts_trailing_slash_stripped(self):
        assert _url_to_parts("mock://Home/") == ["Home"]

    def test_url_to_parts_rejects_non_mock(self):
        assert _url_to_parts("file:///Home") is None
        assert _url_to_parts("/Home") is None
        assert _url_to_parts("") is None

    def test_parts_to_url_root(self):
        assert _parts_to_url([]) == "mock://"

    def test_parts_to_url_single(self):
        assert _parts_to_url(["Home"]) == "mock://Home"

    def test_parts_to_url_round_trip(self):
        url = "mock://Home/Documents/Projects/demo.usda"
        assert _parts_to_url(_url_to_parts(url) or []) == url


# ──────────────────────────────────────────────────────────────────────────────
# supports_url
# ──────────────────────────────────────────────────────────────────────────────

class TestSupportsUrl:
    @pytest.fixture
    def backend(self):
        return MockBackend()

    def test_mock_scheme_supported(self, backend):
        assert backend.supports_url("mock://Home") is True

    def test_mock_root_supported(self, backend):
        assert backend.supports_url("mock://") is True

    def test_file_scheme_not_supported(self, backend):
        assert backend.supports_url("file:///tmp") is False

    def test_absolute_posix_not_supported(self, backend):
        assert backend.supports_url("/tmp/foo") is False

    def test_http_not_supported(self, backend):
        assert backend.supports_url("http://example.com") is False

    def test_omniverse_not_supported(self, backend):
        assert backend.supports_url("omniverse://server/path") is False

    def test_empty_string_not_supported(self, backend):
        assert backend.supports_url("") is False

    def test_relative_path_not_supported(self, backend):
        assert backend.supports_url("some/path") is False


# ──────────────────────────────────────────────────────────────────────────────
# Default tree shape
# ──────────────────────────────────────────────────────────────────────────────

class TestDefaultTree:
    @pytest.fixture
    def backend(self):
        return MockBackend()

    def test_root_has_home_and_shared(self, backend):
        code, entries = backend.list_dir("mock://")
        assert code == BackendResult.OK
        names = [e.name for e in entries]
        assert names == ["Home", "Shared"]

    def test_home_has_four_entries(self, backend):
        """the content browser implementation step 3 "Verify": Home yields exactly 4 entries."""
        code, entries = backend.list_dir("mock://Home")
        assert code == BackendResult.OK
        names = [e.name for e in entries]
        assert names == ["Documents", "Textures", "Scripts", ".hidden_folder"]

    def test_shared_is_empty(self, backend):
        code, entries = backend.list_dir("mock://Shared")
        assert code == BackendResult.OK
        assert entries == []

    def test_documents_has_projects(self, backend):
        code, entries = backend.list_dir("mock://Home/Documents")
        assert code == BackendResult.OK
        names = [e.name for e in entries]
        assert names == ["Projects"]

    def test_projects_has_three_files(self, backend):
        code, entries = backend.list_dir("mock://Home/Documents/Projects")
        assert code == BackendResult.OK
        names = {e.name for e in entries}
        assert names == {"demo.usda", "demo.usdc", "readme.md"}

    def test_textures_has_two_files(self, backend):
        code, entries = backend.list_dir("mock://Home/Textures")
        assert code == BackendResult.OK
        names = {e.name for e in entries}
        assert names == {"concrete.png", "metal.hdr"}

    def test_scripts_has_one_file(self, backend):
        code, entries = backend.list_dir("mock://Home/Scripts")
        assert code == BackendResult.OK
        names = {e.name for e in entries}
        assert names == {"test.py"}

    def test_hidden_folder_has_secret(self, backend):
        code, entries = backend.list_dir("mock://Home/.hidden_folder")
        assert code == BackendResult.OK
        names = {e.name for e in entries}
        assert names == {"secret.txt"}

    def test_default_tree_builds_standalone(self):
        # Sanity check that the module-level factory can be called
        # without going through the class.
        tree = _build_default_tree()
        assert tree.is_folder
        assert "Home" in tree.children
        assert "Shared" in tree.children


# ──────────────────────────────────────────────────────────────────────────────
# stat
# ──────────────────────────────────────────────────────────────────────────────

class TestStat:
    @pytest.fixture
    def backend(self):
        return MockBackend()

    def test_stat_existing_file(self, backend):
        code, entry = backend.stat("mock://Home/Documents/Projects/demo.usda")
        assert code == BackendResult.OK
        assert entry is not None
        assert entry.name == "demo.usda"
        assert entry.size == 128
        assert entry.modified_time == _BASE_TIME
        assert entry.created_time == _BASE_TIME

    def test_stat_existing_folder_has_folder_flag(self, backend):
        code, entry = backend.stat("mock://Home/Documents")
        assert code == BackendResult.OK
        assert entry is not None
        assert entry.name == "Documents"
        assert BackendFileFlags.IS_FOLDER in entry.flags
        assert entry.size == 0

    def test_stat_file_does_not_have_folder_flag(self, backend):
        _, entry = backend.stat("mock://Home/Scripts/test.py")
        assert entry is not None
        assert BackendFileFlags.IS_FOLDER not in entry.flags

    def test_stat_hidden_folder_has_hidden_flag(self, backend):
        _, entry = backend.stat("mock://Home/.hidden_folder")
        assert entry is not None
        assert BackendFileFlags.IS_HIDDEN in entry.flags

    def test_stat_normal_entry_has_no_hidden_flag(self, backend):
        _, entry = backend.stat("mock://Home/Documents")
        assert entry is not None
        assert BackendFileFlags.IS_HIDDEN not in entry.flags

    def test_stat_readable_writable(self, backend):
        _, entry = backend.stat("mock://Home/Scripts/test.py")
        assert entry is not None
        assert BackendFileFlags.IS_READABLE in entry.flags
        assert BackendFileFlags.IS_WRITABLE in entry.flags

    def test_stat_nonexistent_returns_not_found(self, backend):
        code, entry = backend.stat("mock://Home/does_not_exist")
        assert code == BackendResult.ERROR_NOT_FOUND
        assert entry is None

    def test_stat_through_file_returns_not_found(self, backend):
        # Walking past a file should yield NOT_FOUND, not an error.
        code, entry = backend.stat("mock://Home/Scripts/test.py/nested")
        assert code == BackendResult.ERROR_NOT_FOUND
        assert entry is None

    def test_stat_root_returns_ok(self, backend):
        code, entry = backend.stat("mock://")
        assert code == BackendResult.OK
        assert entry is not None
        assert entry.name == ""
        assert BackendFileFlags.IS_FOLDER in entry.flags

    def test_stat_non_mock_url_returns_not_supported(self, backend):
        code, entry = backend.stat("file:///tmp/x")
        assert code == BackendResult.ERROR_NOT_SUPPORTED
        assert entry is None

    def test_stat_returns_backend_list_entry(self, backend):
        _, entry = backend.stat("mock://Home")
        assert isinstance(entry, BackendListEntry)


# ──────────────────────────────────────────────────────────────────────────────
# list_dir
# ──────────────────────────────────────────────────────────────────────────────

class TestListDir:
    @pytest.fixture
    def backend(self):
        return MockBackend()

    def test_list_empty_folder(self, backend):
        code, entries = backend.list_dir("mock://Shared")
        assert code == BackendResult.OK
        assert entries == []

    def test_list_nonexistent_folder_returns_not_found(self, backend):
        code, entries = backend.list_dir("mock://Home/Nowhere")
        assert code == BackendResult.ERROR_NOT_FOUND
        assert entries == []

    def test_list_file_returns_error(self, backend):
        code, entries = backend.list_dir("mock://Home/Scripts/test.py")
        assert code == BackendResult.ERROR
        assert entries == []

    def test_list_non_mock_url_returns_not_supported(self, backend):
        code, entries = backend.list_dir("file:///tmp")
        assert code == BackendResult.ERROR_NOT_SUPPORTED
        assert entries == []

    def test_list_hidden_entries_included(self, backend):
        # the content browser implementation step 3: hidden-entry filtering is a model
        # concern (Step 25 / 56), not the backend's.
        _, entries = backend.list_dir("mock://Home")
        names = {e.name for e in entries}
        assert ".hidden_folder" in names

    def test_list_entries_are_backend_list_entries(self, backend):
        _, entries = backend.list_dir("mock://Home")
        for e in entries:
            assert isinstance(e, BackendListEntry)

    def test_list_folder_flag_set_correctly(self, backend):
        _, entries = backend.list_dir("mock://Home/Documents/Projects")
        by_name = {e.name: e for e in entries}
        for name in ("demo.usda", "demo.usdc", "readme.md"):
            assert BackendFileFlags.IS_FOLDER not in by_name[name].flags
        _, home_entries = backend.list_dir("mock://Home")
        for e in home_entries:
            assert BackendFileFlags.IS_FOLDER in e.flags

    def test_list_sizes_match_tree(self, backend):
        _, entries = backend.list_dir("mock://Home/Documents/Projects")
        by_name = {e.name: e for e in entries}
        assert by_name["demo.usda"].size == 128
        assert by_name["demo.usdc"].size == 2048
        assert by_name["readme.md"].size == 512


# ──────────────────────────────────────────────────────────────────────────────
# create_folder
# ──────────────────────────────────────────────────────────────────────────────

class TestCreateFolder:
    @pytest.fixture
    def backend(self):
        return MockBackend()

    def test_new_folder_ok(self, backend):
        assert backend.create_folder("mock://Home/NewStuff") == BackendResult.OK
        _, entries = backend.list_dir("mock://Home")
        names = {e.name for e in entries}
        assert "NewStuff" in names

    def test_new_folder_is_folder(self, backend):
        backend.create_folder("mock://Home/Nested")
        _, entry = backend.stat("mock://Home/Nested")
        assert entry is not None
        assert BackendFileFlags.IS_FOLDER in entry.flags

    def test_new_folder_then_list_shows_empty(self, backend):
        """Required by task: create_folder then list shows new folder."""
        backend.create_folder("mock://Home/Brand_New")
        code, entries = backend.list_dir("mock://Home/Brand_New")
        assert code == BackendResult.OK
        assert entries == []

    def test_duplicate_folder_rejected(self, backend):
        assert (
            backend.create_folder("mock://Home/Documents")
            == BackendResult.ERROR_ALREADY_EXISTS
        )

    def test_missing_parent_not_found(self, backend):
        # "Somewhere" does not exist — create is non-recursive.
        assert (
            backend.create_folder("mock://Home/Somewhere/Inside")
            == BackendResult.ERROR_NOT_FOUND
        )

    def test_root_already_exists(self, backend):
        assert backend.create_folder("mock://") == BackendResult.ERROR_ALREADY_EXISTS

    def test_non_mock_url_not_supported(self, backend):
        assert (
            backend.create_folder("file:///tmp/x")
            == BackendResult.ERROR_NOT_SUPPORTED
        )


# ──────────────────────────────────────────────────────────────────────────────
# copy
# ──────────────────────────────────────────────────────────────────────────────

class TestCopy:
    @pytest.fixture
    def backend(self):
        return MockBackend()

    def test_copy_file_preserves_source(self, backend):
        result = backend.copy(
            "mock://Home/Scripts/test.py",
            "mock://Shared/test_copy.py",
        )
        assert result == BackendResult.OK
        # Source still exists.
        code, _ = backend.stat("mock://Home/Scripts/test.py")
        assert code == BackendResult.OK
        # Destination exists with same size.
        code, entry = backend.stat("mock://Shared/test_copy.py")
        assert code == BackendResult.OK
        assert entry is not None
        assert entry.size == 1024

    def test_copy_folder_recursive(self, backend):
        result = backend.copy(
            "mock://Home/Documents/Projects",
            "mock://Shared/Projects",
        )
        assert result == BackendResult.OK
        _, entries = backend.list_dir("mock://Shared/Projects")
        names = {e.name for e in entries}
        assert names == {"demo.usda", "demo.usdc", "readme.md"}

    def test_copy_collision_without_overwrite_rejects(self, backend):
        result = backend.copy(
            "mock://Home/Scripts/test.py",
            "mock://Home/Documents/Projects/readme.md",
        )
        assert result == BackendResult.ERROR_ALREADY_EXISTS
        # Destination unchanged.
        _, entry = backend.stat("mock://Home/Documents/Projects/readme.md")
        assert entry is not None
        assert entry.size == 512

    def test_copy_collision_with_overwrite_replaces(self, backend):
        result = backend.copy(
            "mock://Home/Scripts/test.py",
            "mock://Home/Documents/Projects/readme.md",
            overwrite=True,
        )
        assert result == BackendResult.OK
        _, entry = backend.stat("mock://Home/Documents/Projects/readme.md")
        assert entry is not None
        assert entry.size == 1024

    def test_copy_nonexistent_src_returns_not_found(self, backend):
        assert (
            backend.copy("mock://Home/missing", "mock://Shared/x")
            == BackendResult.ERROR_NOT_FOUND
        )

    def test_copy_folder_overwrite_merges(self, backend):
        # shutil.copytree(dirs_exist_ok=True) merges; MockBackend mirrors.
        backend.create_folder("mock://Shared/Projects")
        backend.create_folder("mock://Shared/Projects/Extra")
        result = backend.copy(
            "mock://Home/Documents/Projects",
            "mock://Shared/Projects",
            overwrite=True,
        )
        assert result == BackendResult.OK
        _, entries = backend.list_dir("mock://Shared/Projects")
        names = {e.name for e in entries}
        # Pre-existing "Extra" survives; new files merged in.
        assert names == {"Extra", "demo.usda", "demo.usdc", "readme.md"}

    def test_copy_missing_dst_parent_returns_not_found(self, backend):
        assert (
            backend.copy(
                "mock://Home/Scripts/test.py",
                "mock://Nowhere/test.py",
            )
            == BackendResult.ERROR_NOT_FOUND
        )

    def test_copy_non_mock_dst_not_supported(self, backend):
        assert (
            backend.copy(
                "mock://Home/Scripts/test.py",
                "file:///tmp/test.py",
            )
            == BackendResult.ERROR_NOT_SUPPORTED
        )


# ──────────────────────────────────────────────────────────────────────────────
# move
# ──────────────────────────────────────────────────────────────────────────────

class TestMove:
    @pytest.fixture
    def backend(self):
        return MockBackend()

    def test_rename_file_same_dir(self, backend):
        result = backend.move(
            "mock://Home/Scripts/test.py",
            "mock://Home/Scripts/renamed.py",
        )
        assert result == BackendResult.OK
        assert (
            backend.stat("mock://Home/Scripts/test.py")[0]
            == BackendResult.ERROR_NOT_FOUND
        )
        _, entry = backend.stat("mock://Home/Scripts/renamed.py")
        assert entry is not None
        assert entry.size == 1024

    def test_move_file_across_dirs(self, backend):
        result = backend.move(
            "mock://Home/Scripts/test.py",
            "mock://Shared/test.py",
        )
        assert result == BackendResult.OK
        assert (
            backend.stat("mock://Home/Scripts/test.py")[0]
            == BackendResult.ERROR_NOT_FOUND
        )
        _, entry = backend.stat("mock://Shared/test.py")
        assert entry is not None

    def test_move_folder_recursive(self, backend):
        result = backend.move(
            "mock://Home/Documents/Projects",
            "mock://Shared/Projects",
        )
        assert result == BackendResult.OK
        # Source gone.
        assert (
            backend.stat("mock://Home/Documents/Projects")[0]
            == BackendResult.ERROR_NOT_FOUND
        )
        # Children preserved at new location.
        _, entries = backend.list_dir("mock://Shared/Projects")
        names = {e.name for e in entries}
        assert names == {"demo.usda", "demo.usdc", "readme.md"}

    def test_move_collision_without_overwrite_rejects(self, backend):
        result = backend.move(
            "mock://Home/Scripts/test.py",
            "mock://Home/Documents/Projects/readme.md",
        )
        assert result == BackendResult.ERROR_ALREADY_EXISTS
        # Both sides untouched.
        assert (
            backend.stat("mock://Home/Scripts/test.py")[0]
            == BackendResult.OK
        )

    def test_move_collision_with_overwrite_replaces(self, backend):
        result = backend.move(
            "mock://Home/Scripts/test.py",
            "mock://Home/Documents/Projects/readme.md",
            overwrite=True,
        )
        assert result == BackendResult.OK
        _, entry = backend.stat("mock://Home/Documents/Projects/readme.md")
        assert entry is not None
        assert entry.size == 1024
        assert (
            backend.stat("mock://Home/Scripts/test.py")[0]
            == BackendResult.ERROR_NOT_FOUND
        )

    def test_move_folder_overwrite_replaces_not_merges(self, backend):
        # Move semantics match LocalFSBackend.move: destination is
        # replaced, not merged.
        backend.create_folder("mock://Shared/Projects")
        backend.create_folder("mock://Shared/Projects/Leftover")
        result = backend.move(
            "mock://Home/Documents/Projects",
            "mock://Shared/Projects",
            overwrite=True,
        )
        assert result == BackendResult.OK
        _, entries = backend.list_dir("mock://Shared/Projects")
        names = {e.name for e in entries}
        assert "Leftover" not in names  # pre-existing dst child is gone
        assert names == {"demo.usda", "demo.usdc", "readme.md"}

    def test_move_nonexistent_src_not_found(self, backend):
        assert (
            backend.move("mock://Home/missing", "mock://Shared/x")
            == BackendResult.ERROR_NOT_FOUND
        )

    def test_move_root_rejected(self, backend):
        assert backend.move("mock://", "mock://X") == BackendResult.ERROR

    def test_move_into_own_descendant_rejected(self, backend):
        # Moving Home under Home/Documents would loop the tree.
        assert (
            backend.move("mock://Home", "mock://Home/Documents/Home")
            == BackendResult.ERROR
        )


# ──────────────────────────────────────────────────────────────────────────────
# delete
# ──────────────────────────────────────────────────────────────────────────────

class TestDelete:
    @pytest.fixture
    def backend(self):
        return MockBackend()

    def test_delete_file(self, backend):
        assert (
            backend.delete("mock://Home/Scripts/test.py")
            == BackendResult.OK
        )
        code, _ = backend.stat("mock://Home/Scripts/test.py")
        assert code == BackendResult.ERROR_NOT_FOUND

    def test_delete_folder_recursive(self, backend):
        assert (
            backend.delete("mock://Home/Documents")
            == BackendResult.OK
        )
        code, _ = backend.stat("mock://Home/Documents")
        assert code == BackendResult.ERROR_NOT_FOUND
        # And children are also gone (trying to walk in yields NOT_FOUND).
        code, _ = backend.stat("mock://Home/Documents/Projects/demo.usda")
        assert code == BackendResult.ERROR_NOT_FOUND

    def test_delete_nonexistent_returns_not_found(self, backend):
        assert (
            backend.delete("mock://Home/nope")
            == BackendResult.ERROR_NOT_FOUND
        )

    def test_delete_root_rejected(self, backend):
        # Root deletion is forbidden — root has no parent.
        assert backend.delete("mock://") == BackendResult.ERROR

    def test_delete_non_mock_url_not_supported(self, backend):
        assert (
            backend.delete("file:///tmp/foo")
            == BackendResult.ERROR_NOT_SUPPORTED
        )


# ──────────────────────────────────────────────────────────────────────────────
# URL utilities: normalize, join, parent, basename
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalizeUrl:
    @pytest.fixture
    def backend(self):
        return MockBackend()

    def test_collapses_dotdot(self, backend):
        assert backend.normalize_url("mock://a/b/../c") == "mock://a/c"

    def test_collapses_dot(self, backend):
        assert backend.normalize_url("mock://a/./b") == "mock://a/b"

    def test_strips_trailing_slash(self, backend):
        assert backend.normalize_url("mock://a/b/") == "mock://a/b"

    def test_root_stays_root(self, backend):
        assert backend.normalize_url("mock://") == "mock://"
        assert backend.normalize_url("mock:///") == "mock://"

    def test_dotdot_past_root_is_clamped(self, backend):
        assert backend.normalize_url("mock://../a") == "mock://a"

    def test_non_mock_pass_through(self, backend):
        # Non-mock URLs are returned unchanged (MockBackend doesn't
        # claim to canonicalise other schemes).
        assert backend.normalize_url("file:///tmp") == "file:///tmp"

    def test_idempotent(self, backend):
        once = backend.normalize_url("mock://a/b/../c/./d")
        assert backend.normalize_url(once) == once


class TestJoinUrl:
    @pytest.fixture
    def backend(self):
        return MockBackend()

    def test_basic_join(self, backend):
        assert backend.join_url("mock://Home", "Documents") == "mock://Home/Documents"

    def test_join_nested_child(self, backend):
        assert (
            backend.join_url("mock://Home", "Documents/Projects")
            == "mock://Home/Documents/Projects"
        )

    def test_join_collapses_dotdot(self, backend):
        assert backend.join_url("mock://a/b", "../c") == "mock://a/c"

    def test_join_empty_base(self, backend):
        assert backend.join_url("mock://", "Home") == "mock://Home"

    def test_join_non_mock_base_passthrough(self, backend):
        # Non-mock base: return opaque string join (backend just
        # doesn't own that scheme).
        assert backend.join_url("file:///a", "b") == "file:///a/b"


class TestParentUrl:
    @pytest.fixture
    def backend(self):
        return MockBackend()

    def test_parent_of_child(self, backend):
        assert backend.parent_url("mock://Home/Documents") == "mock://Home"

    def test_parent_of_home_is_root(self, backend):
        assert backend.parent_url("mock://Home") == "mock://"

    def test_parent_of_root_is_none(self, backend):
        assert backend.parent_url("mock://") is None

    def test_parent_of_deep_path(self, backend):
        assert (
            backend.parent_url("mock://Home/Documents/Projects/demo.usda")
            == "mock://Home/Documents/Projects"
        )

    def test_parent_of_non_mock_url_is_none(self, backend):
        assert backend.parent_url("file:///tmp") is None


class TestBasename:
    @pytest.fixture
    def backend(self):
        return MockBackend()

    def test_basic(self, backend):
        assert backend.basename("mock://Home/Documents") == "Documents"

    def test_deep(self, backend):
        assert (
            backend.basename("mock://Home/Documents/Projects/demo.usda")
            == "demo.usda"
        )

    def test_trailing_slash_handled(self, backend):
        assert backend.basename("mock://Home/Documents/") == "Documents"

    def test_root_is_empty(self, backend):
        assert backend.basename("mock://") == ""

    def test_non_mock_url_is_empty(self, backend):
        assert backend.basename("file:///tmp/x") == ""


# ──────────────────────────────────────────────────────────────────────────────
# Error injection via _errors map
# ──────────────────────────────────────────────────────────────────────────────

class TestErrorInjection:
    @pytest.fixture
    def backend(self):
        return MockBackend()

    def test_injected_error_on_stat(self, backend):
        url = "mock://Home/Documents/Projects/demo.usda"
        backend._errors[url] = BackendResult.ERROR_ACCESS_DENIED
        code, entry = backend.stat(url)
        assert code == BackendResult.ERROR_ACCESS_DENIED
        assert entry is None

    def test_injected_error_on_list_dir(self, backend):
        backend._errors["mock://Home"] = BackendResult.ERROR_ACCESS_DENIED
        code, entries = backend.list_dir("mock://Home")
        assert code == BackendResult.ERROR_ACCESS_DENIED
        assert entries == []

    def test_injected_error_on_delete(self, backend):
        url = "mock://Home/Documents/Projects/demo.usda"
        backend._errors[url] = BackendResult.ERROR_ACCESS_DENIED
        assert backend.delete(url) == BackendResult.ERROR_ACCESS_DENIED
        # Tree untouched: the entry should still exist.
        code, _ = backend.stat(url)
        assert code == BackendResult.ERROR_ACCESS_DENIED  # still injected
        del backend._errors[url]
        code, _ = backend.stat(url)
        assert code == BackendResult.OK

    def test_injected_error_on_create_folder(self, backend):
        url = "mock://Home/NewDir"
        backend._errors[url] = BackendResult.ERROR_CONNECTION
        assert backend.create_folder(url) == BackendResult.ERROR_CONNECTION
        # Tree untouched: folder not actually created.
        del backend._errors[url]
        code, _ = backend.stat(url)
        assert code == BackendResult.ERROR_NOT_FOUND

    def test_injected_error_on_copy_src(self, backend):
        src = "mock://Home/Scripts/test.py"
        backend._errors[src] = BackendResult.ERROR_ACCESS_DENIED
        result = backend.copy(src, "mock://Shared/test.py")
        assert result == BackendResult.ERROR_ACCESS_DENIED

    def test_injected_error_on_copy_dst(self, backend):
        dst = "mock://Shared/test.py"
        backend._errors[dst] = BackendResult.ERROR_ACCESS_DENIED
        result = backend.copy("mock://Home/Scripts/test.py", dst)
        assert result == BackendResult.ERROR_ACCESS_DENIED

    def test_injected_error_on_move(self, backend):
        src = "mock://Home/Scripts/test.py"
        backend._errors[src] = BackendResult.ERROR
        result = backend.move(src, "mock://Shared/test.py")
        assert result == BackendResult.ERROR

    def test_clearing_errors_restores_behaviour(self, backend):
        url = "mock://Home"
        backend._errors[url] = BackendResult.ERROR_ACCESS_DENIED
        assert backend.list_dir(url)[0] == BackendResult.ERROR_ACCESS_DENIED
        backend._errors.clear()
        assert backend.list_dir(url)[0] == BackendResult.OK

    def test_any_backend_result_can_be_injected(self, backend):
        # Full coverage: every enum member is usable as an injected error.
        url = "mock://Home/Scripts/test.py"
        for code in BackendResult:
            backend._errors[url] = code
            actual, _ = backend.stat(url)
            assert actual == code
        backend._errors.clear()


# ──────────────────────────────────────────────────────────────────────────────
# reset()
# ──────────────────────────────────────────────────────────────────────────────

class TestReset:
    @pytest.fixture
    def backend(self):
        return MockBackend()

    def test_reset_after_delete(self, backend):
        backend.delete("mock://Home/Scripts/test.py")
        assert (
            backend.stat("mock://Home/Scripts/test.py")[0]
            == BackendResult.ERROR_NOT_FOUND
        )
        backend.reset()
        code, entry = backend.stat("mock://Home/Scripts/test.py")
        assert code == BackendResult.OK
        assert entry is not None

    def test_reset_after_create(self, backend):
        backend.create_folder("mock://Home/Brand_New")
        backend.reset()
        code, _ = backend.stat("mock://Home/Brand_New")
        assert code == BackendResult.ERROR_NOT_FOUND

    def test_reset_clears_error_injection(self, backend):
        backend._errors["mock://Home"] = BackendResult.ERROR_ACCESS_DENIED
        backend.reset()
        assert backend._errors == {}
        assert backend.list_dir("mock://Home")[0] == BackendResult.OK

    def test_reset_rebuilds_full_tree(self, backend):
        # Wipe Home → reset → Home should be back with four children.
        backend.delete("mock://Home")
        backend.reset()
        _, entries = backend.list_dir("mock://Home")
        assert len(entries) == 4


# ──────────────────────────────────────────────────────────────────────────────
# Flag decoding
# ──────────────────────────────────────────────────────────────────────────────

class TestFlagDecoding:
    @pytest.fixture
    def backend(self):
        return MockBackend()

    def test_folder_flag_on_folder(self, backend):
        _, entry = backend.stat("mock://Home")
        assert entry is not None
        assert BackendFileFlags.IS_FOLDER in entry.flags

    def test_folder_flag_not_on_file(self, backend):
        _, entry = backend.stat("mock://Home/Scripts/test.py")
        assert entry is not None
        assert BackendFileFlags.IS_FOLDER not in entry.flags

    def test_hidden_flag_on_dotted_name(self, backend):
        """Required by task: hidden file has IS_HIDDEN flag."""
        _, entry = backend.stat("mock://Home/.hidden_folder")
        assert entry is not None
        assert BackendFileFlags.IS_HIDDEN in entry.flags

    def test_hidden_flag_off_for_normal_file(self, backend):
        _, entry = backend.stat("mock://Home/Documents/Projects/readme.md")
        assert entry is not None
        assert BackendFileFlags.IS_HIDDEN not in entry.flags

    def test_readable_always_set(self, backend):
        _, entry = backend.stat("mock://Home/Documents")
        assert entry is not None
        assert BackendFileFlags.IS_READABLE in entry.flags

    def test_writable_always_set(self, backend):
        _, entry = backend.stat("mock://Home/Documents")
        assert entry is not None
        assert BackendFileFlags.IS_WRITABLE in entry.flags

    def test_symlink_flag_never_set(self, backend):
        # MockBackend has no symlinks — the flag is never set.
        for url in (
            "mock://Home",
            "mock://Home/Scripts/test.py",
            "mock://Home/.hidden_folder",
            "mock://Home/.hidden_folder/secret.txt",
        ):
            _, entry = backend.stat(url)
            assert entry is not None
            assert BackendFileFlags.IS_SYMLINK not in entry.flags


# ──────────────────────────────────────────────────────────────────────────────
# subscribe_changes (inherits ABC default — no-op in v1)
# ──────────────────────────────────────────────────────────────────────────────

class TestSubscribeChangesDefault:
    def test_returns_cancellable(self):
        backend = MockBackend()
        sub = backend.subscribe_changes("mock://Home", lambda evt: None)
        assert hasattr(sub, "cancel")
        sub.cancel()
        sub.cancel()  # idempotent

    def test_callback_not_fired_on_mutation(self):
        backend = MockBackend()
        fired = []
        backend.subscribe_changes(
            "mock://Home", lambda evt: fired.append(evt),
        )
        backend.create_folder("mock://Home/X")
        backend.delete("mock://Home/X")
        # v1: no change events emitted by MockBackend.
        assert fired == []

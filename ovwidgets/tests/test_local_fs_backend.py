# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`ovwidgets.content.backends.LocalFSBackend`.

See the content browser implementation step 2. Covers URL translation, supports_url routing,
stat / list_dir / create_folder / copy / move / delete success and
error paths, URL utilities (normalize / join / parent / basename), and
flag decoding (IS_FOLDER / IS_HIDDEN / IS_SYMLINK / IS_READABLE /
IS_WRITABLE).

Tests use the pytest ``tmp_path`` fixture so they do not depend on any
real filesystem location. The broken-symlink test is POSIX-only.
"""

import os

import pytest

from ovwidgets.content.backends import (
    BackendAdapter,
    BackendFileFlags,
    BackendListEntry,
    BackendResult,
    LocalFSBackend,
)
from ovwidgets.content.backends.local_fs_backend import _fspath_to_url, _url_to_fspath

IS_WINDOWS = os.name == "nt"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _url(tmp_path, *parts: str) -> str:
    """Return a ``file://`` URL for ``tmp_path / *parts``."""
    p = tmp_path.joinpath(*parts) if parts else tmp_path
    return _fspath_to_url(str(p))


def _raw(tmp_path, *parts: str) -> str:
    """Return the raw OS path for ``tmp_path / *parts``."""
    p = tmp_path.joinpath(*parts) if parts else tmp_path
    return str(p)


# ──────────────────────────────────────────────────────────────────────────────
# Import / instantiation surface
# ──────────────────────────────────────────────────────────────────────────────

class TestImport:
    def test_localfs_exported(self):
        from ovwidgets.content.backends import LocalFSBackend as LFB
        assert LFB is LocalFSBackend

    def test_package_all_contains_localfs(self):
        import ovwidgets.content.backends as pkg
        assert "LocalFSBackend" in pkg.__all__

    def test_instantiable(self):
        backend = LocalFSBackend()
        assert isinstance(backend, BackendAdapter)

    def test_no_required_init_args(self):
        # Must be constructable without arguments — matches
        # ``StageAdapter`` auto-wrap pattern (the content browser implementation step 15).
        LocalFSBackend()


# ──────────────────────────────────────────────────────────────────────────────
# Internal URL ↔ fspath helpers
# ──────────────────────────────────────────────────────────────────────────────

class TestUrlToFspath:
    def test_strips_file_scheme_posix(self):
        if IS_WINDOWS:
            pytest.skip("POSIX path test")
        assert _url_to_fspath("file:///tmp/foo") == "/tmp/foo"

    def test_raw_path_passes_through(self):
        if IS_WINDOWS:
            pytest.skip("POSIX path test")
        assert _url_to_fspath("/tmp/foo") == "/tmp/foo"

    def test_expanduser_applied(self):
        if IS_WINDOWS:
            pytest.skip("POSIX path test")
        expanded = _url_to_fspath("~/foo")
        assert not expanded.startswith("~")
        assert expanded.endswith("/foo")

    @pytest.mark.skipif(not IS_WINDOWS, reason="Windows drive-letter handling")
    def test_windows_drops_leading_slash_before_drive(self):
        assert _url_to_fspath("file:///C:/Users/x") == "C:/Users/x"


class TestFspathToUrl:
    def test_posix_absolute_path(self):
        if IS_WINDOWS:
            pytest.skip("POSIX path test")
        assert _fspath_to_url("/tmp/foo") == "file:///tmp/foo"

    def test_round_trip_posix(self):
        if IS_WINDOWS:
            pytest.skip("POSIX path test")
        p = "/tmp/foo/bar"
        assert _url_to_fspath(_fspath_to_url(p)) == p


# ──────────────────────────────────────────────────────────────────────────────
# supports_url
# ──────────────────────────────────────────────────────────────────────────────

class TestSupportsUrl:
    @pytest.fixture
    def backend(self):
        return LocalFSBackend()

    def test_file_scheme_supported(self, backend):
        assert backend.supports_url("file:///tmp") is True

    def test_absolute_posix_supported(self, backend):
        assert backend.supports_url("/tmp/foo") is True

    def test_tilde_supported(self, backend):
        assert backend.supports_url("~/Documents") is True

    def test_http_not_supported(self, backend):
        assert backend.supports_url("http://example.com") is False

    def test_https_not_supported(self, backend):
        assert backend.supports_url("https://example.com") is False

    def test_omniverse_not_supported(self, backend):
        assert backend.supports_url("omniverse://server/path") is False

    def test_mock_scheme_not_supported(self, backend):
        assert backend.supports_url("mock://some/tree") is False

    def test_empty_string_not_supported(self, backend):
        assert backend.supports_url("") is False

    def test_relative_path_not_supported(self, backend):
        # the content browser implementation step 2: supports_url rejects relative paths.
        assert backend.supports_url("relative/path") is False


# ──────────────────────────────────────────────────────────────────────────────
# stat
# ──────────────────────────────────────────────────────────────────────────────

class TestStat:
    @pytest.fixture
    def backend(self):
        return LocalFSBackend()

    def test_existing_file_returns_ok_and_entry(self, backend, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("hello world")
        code, entry = backend.stat(_url(tmp_path, "hello.txt"))
        assert code == BackendResult.OK
        assert entry is not None
        assert entry.name == "hello.txt"
        assert entry.size == len("hello world")
        assert entry.modified_time > 0
        assert BackendFileFlags.IS_FOLDER not in entry.flags
        assert BackendFileFlags.IS_READABLE in entry.flags

    def test_existing_folder_returns_ok_and_folder_flag(
        self, backend, tmp_path,
    ):
        d = tmp_path / "sub"
        d.mkdir()
        code, entry = backend.stat(_url(tmp_path, "sub"))
        assert code == BackendResult.OK
        assert entry is not None
        assert entry.name == "sub"
        assert BackendFileFlags.IS_FOLDER in entry.flags

    def test_nonexistent_path_returns_not_found(self, backend, tmp_path):
        code, entry = backend.stat(_url(tmp_path, "does_not_exist"))
        assert code == BackendResult.ERROR_NOT_FOUND
        assert entry is None

    def test_accepts_raw_path(self, backend, tmp_path):
        f = tmp_path / "plain.txt"
        f.write_text("x")
        code, entry = backend.stat(_raw(tmp_path, "plain.txt"))
        assert code == BackendResult.OK
        assert entry is not None
        assert entry.name == "plain.txt"

    def test_hidden_dotfile_has_hidden_flag(self, backend, tmp_path):
        if IS_WINDOWS:
            pytest.skip("POSIX hidden-file detection test")
        f = tmp_path / ".secret"
        f.write_text("x")
        code, entry = backend.stat(_url(tmp_path, ".secret"))
        assert code == BackendResult.OK
        assert entry is not None
        assert BackendFileFlags.IS_HIDDEN in entry.flags

    def test_returns_backend_list_entry(self, backend, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("a")
        _, entry = backend.stat(_url(tmp_path, "a.txt"))
        assert isinstance(entry, BackendListEntry)

    @pytest.mark.skipif(
        IS_WINDOWS or os.geteuid() == 0,  # type: ignore[attr-defined]
        reason="POSIX permission test (not root)",
    )
    def test_unreadable_parent_returns_access_denied(
        self, backend, tmp_path,
    ):
        # Remove read+exec on the directory → children become
        # inaccessible. os.stat() raises PermissionError which we map
        # to ERROR_ACCESS_DENIED.
        locked = tmp_path / "locked"
        locked.mkdir()
        (locked / "inner.txt").write_text("x")
        orig_mode = locked.stat().st_mode
        try:
            os.chmod(locked, 0o000)
            code, entry = backend.stat(_url(locked, "inner.txt"))
            assert code in (
                BackendResult.ERROR_ACCESS_DENIED,
                BackendResult.ERROR_NOT_FOUND,
            )
            assert entry is None
        finally:
            os.chmod(locked, orig_mode)


# ──────────────────────────────────────────────────────────────────────────────
# list_dir
# ──────────────────────────────────────────────────────────────────────────────

class TestListDir:
    @pytest.fixture
    def backend(self):
        return LocalFSBackend()

    def test_populated_folder(self, backend, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("bb")
        (tmp_path / "sub").mkdir()
        code, entries = backend.list_dir(_url(tmp_path))
        assert code == BackendResult.OK
        names = {e.name for e in entries}
        assert names == {"a.txt", "b.txt", "sub"}

    def test_empty_folder(self, backend, tmp_path):
        code, entries = backend.list_dir(_url(tmp_path))
        assert code == BackendResult.OK
        assert entries == []

    def test_nonexistent_folder_returns_not_found(self, backend, tmp_path):
        code, entries = backend.list_dir(_url(tmp_path, "nowhere"))
        assert code == BackendResult.ERROR_NOT_FOUND
        assert entries == []

    def test_file_path_returns_error(self, backend, tmp_path):
        f = tmp_path / "regular.txt"
        f.write_text("x")
        code, entries = backend.list_dir(_url(tmp_path, "regular.txt"))
        assert code == BackendResult.ERROR
        assert entries == []

    def test_hidden_files_are_included(self, backend, tmp_path):
        # The backend does NOT filter hidden entries — the model does.
        # See the content browser implementation step 2 "Keep the backend pure."
        if IS_WINDOWS:
            pytest.skip("POSIX hidden-file detection test")
        (tmp_path / ".hidden").write_text("x")
        (tmp_path / "visible.txt").write_text("y")
        code, entries = backend.list_dir(_url(tmp_path))
        assert code == BackendResult.OK
        names = {e.name for e in entries}
        assert ".hidden" in names
        assert "visible.txt" in names
        hidden_entry = next(e for e in entries if e.name == ".hidden")
        assert BackendFileFlags.IS_HIDDEN in hidden_entry.flags

    def test_folder_entry_has_folder_flag(self, backend, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "file.txt").write_text("x")
        _, entries = backend.list_dir(_url(tmp_path))
        by_name = {e.name: e for e in entries}
        assert BackendFileFlags.IS_FOLDER in by_name["sub"].flags
        assert BackendFileFlags.IS_FOLDER not in by_name["file.txt"].flags

    @pytest.mark.skipif(
        IS_WINDOWS, reason="POSIX-specific broken-symlink behaviour",
    )
    def test_skips_broken_symlinks(self, backend, tmp_path):
        # the content browser implementation step 2: broken symlinks are skipped (not
        # propagated as errors) — matches filebrowser OM-80351.
        (tmp_path / "real.txt").write_text("hello")
        os.symlink(str(tmp_path / "missing.txt"), str(tmp_path / "broken"))
        code, entries = backend.list_dir(_url(tmp_path))
        assert code == BackendResult.OK
        names = {e.name for e in entries}
        assert "real.txt" in names
        assert "broken" not in names

    @pytest.mark.skipif(
        IS_WINDOWS, reason="POSIX-specific symlink test",
    )
    def test_live_symlink_has_symlink_flag(self, backend, tmp_path):
        target = tmp_path / "target.txt"
        target.write_text("hi")
        os.symlink(str(target), str(tmp_path / "link"))
        code, entries = backend.list_dir(_url(tmp_path))
        assert code == BackendResult.OK
        link = next(e for e in entries if e.name == "link")
        assert BackendFileFlags.IS_SYMLINK in link.flags

    def test_entries_are_backend_list_entries(self, backend, tmp_path):
        (tmp_path / "x").write_text("x")
        _, entries = backend.list_dir(_url(tmp_path))
        for e in entries:
            assert isinstance(e, BackendListEntry)


# ──────────────────────────────────────────────────────────────────────────────
# create_folder
# ──────────────────────────────────────────────────────────────────────────────

class TestCreateFolder:
    @pytest.fixture
    def backend(self):
        return LocalFSBackend()

    def test_new_folder_ok(self, backend, tmp_path):
        assert backend.create_folder(_url(tmp_path, "new")) == BackendResult.OK
        assert (tmp_path / "new").is_dir()

    def test_duplicate_folder_already_exists(self, backend, tmp_path):
        (tmp_path / "dup").mkdir()
        assert (
            backend.create_folder(_url(tmp_path, "dup"))
            == BackendResult.ERROR_ALREADY_EXISTS
        )

    def test_missing_parent_not_found(self, backend, tmp_path):
        # Parent "nope" does not exist; os.mkdir is non-recursive.
        assert (
            backend.create_folder(_url(tmp_path, "nope", "child"))
            == BackendResult.ERROR_NOT_FOUND
        )

    def test_accepts_raw_path(self, backend, tmp_path):
        assert backend.create_folder(_raw(tmp_path, "raw")) == BackendResult.OK
        assert (tmp_path / "raw").is_dir()


# ──────────────────────────────────────────────────────────────────────────────
# copy
# ──────────────────────────────────────────────────────────────────────────────

class TestCopy:
    @pytest.fixture
    def backend(self):
        return LocalFSBackend()

    def test_copy_file_and_verify_contents(self, backend, tmp_path):
        src = tmp_path / "src.txt"
        src.write_text("payload")
        dst = tmp_path / "dst.txt"
        assert (
            backend.copy(_url(tmp_path, "src.txt"), _url(tmp_path, "dst.txt"))
            == BackendResult.OK
        )
        assert dst.read_text() == "payload"
        assert src.exists()  # copy does not remove source

    def test_copy_folder_recursive(self, backend, tmp_path):
        src = tmp_path / "src_dir"
        src.mkdir()
        (src / "child.txt").write_text("c")
        (src / "nested").mkdir()
        (src / "nested" / "deep.txt").write_text("d")
        assert (
            backend.copy(
                _url(tmp_path, "src_dir"), _url(tmp_path, "dst_dir"),
            )
            == BackendResult.OK
        )
        assert (tmp_path / "dst_dir" / "child.txt").read_text() == "c"
        assert (tmp_path / "dst_dir" / "nested" / "deep.txt").read_text() == "d"

    def test_collision_without_overwrite_rejects(self, backend, tmp_path):
        src = tmp_path / "s.txt"
        src.write_text("new")
        dst = tmp_path / "d.txt"
        dst.write_text("existing")
        assert (
            backend.copy(_url(tmp_path, "s.txt"), _url(tmp_path, "d.txt"))
            == BackendResult.ERROR_ALREADY_EXISTS
        )
        assert dst.read_text() == "existing"  # unchanged

    def test_collision_with_overwrite_succeeds(self, backend, tmp_path):
        src = tmp_path / "s.txt"
        src.write_text("new")
        dst = tmp_path / "d.txt"
        dst.write_text("existing")
        assert (
            backend.copy(
                _url(tmp_path, "s.txt"),
                _url(tmp_path, "d.txt"),
                overwrite=True,
            )
            == BackendResult.OK
        )
        assert dst.read_text() == "new"

    def test_copy_nonexistent_src_returns_not_found(
        self, backend, tmp_path,
    ):
        assert (
            backend.copy(
                _url(tmp_path, "missing"), _url(tmp_path, "d"),
            )
            == BackendResult.ERROR_NOT_FOUND
        )

    def test_copy_folder_overwrite_merges(self, backend, tmp_path):
        # shutil.copytree with dirs_exist_ok=True merges into existing
        # destination — the overwrite contract.
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("A")
        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "b.txt").write_text("B")
        assert (
            backend.copy(
                _url(tmp_path, "src"),
                _url(tmp_path, "dst"),
                overwrite=True,
            )
            == BackendResult.OK
        )
        assert (dst / "a.txt").read_text() == "A"
        assert (dst / "b.txt").read_text() == "B"


# ──────────────────────────────────────────────────────────────────────────────
# move
# ──────────────────────────────────────────────────────────────────────────────

class TestMove:
    @pytest.fixture
    def backend(self):
        return LocalFSBackend()

    def test_rename_file_same_dir(self, backend, tmp_path):
        src = tmp_path / "a.txt"
        src.write_text("x")
        assert (
            backend.move(_url(tmp_path, "a.txt"), _url(tmp_path, "b.txt"))
            == BackendResult.OK
        )
        assert not src.exists()
        assert (tmp_path / "b.txt").read_text() == "x"

    def test_move_file_across_dirs(self, backend, tmp_path):
        (tmp_path / "dstdir").mkdir()
        src = tmp_path / "src.txt"
        src.write_text("p")
        assert (
            backend.move(
                _url(tmp_path, "src.txt"),
                _url(tmp_path, "dstdir", "src.txt"),
            )
            == BackendResult.OK
        )
        assert not src.exists()
        assert (tmp_path / "dstdir" / "src.txt").read_text() == "p"

    def test_move_folder_recursive(self, backend, tmp_path):
        src = tmp_path / "sd"
        src.mkdir()
        (src / "f.txt").write_text("f")
        assert (
            backend.move(_url(tmp_path, "sd"), _url(tmp_path, "dd"))
            == BackendResult.OK
        )
        assert not src.exists()
        assert (tmp_path / "dd" / "f.txt").read_text() == "f"

    def test_collision_without_overwrite_rejects(self, backend, tmp_path):
        (tmp_path / "a.txt").write_text("new")
        (tmp_path / "b.txt").write_text("old")
        assert (
            backend.move(_url(tmp_path, "a.txt"), _url(tmp_path, "b.txt"))
            == BackendResult.ERROR_ALREADY_EXISTS
        )
        # src and dst both survive unchanged
        assert (tmp_path / "a.txt").read_text() == "new"
        assert (tmp_path / "b.txt").read_text() == "old"

    def test_collision_with_overwrite_replaces(self, backend, tmp_path):
        (tmp_path / "a.txt").write_text("new")
        (tmp_path / "b.txt").write_text("old")
        assert (
            backend.move(
                _url(tmp_path, "a.txt"),
                _url(tmp_path, "b.txt"),
                overwrite=True,
            )
            == BackendResult.OK
        )
        assert not (tmp_path / "a.txt").exists()
        assert (tmp_path / "b.txt").read_text() == "new"

    def test_collision_folder_overwrite_replaces(self, backend, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "keep.txt").write_text("keep")
        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "drop.txt").write_text("drop")
        assert (
            backend.move(
                _url(tmp_path, "src"),
                _url(tmp_path, "dst"),
                overwrite=True,
            )
            == BackendResult.OK
        )
        assert not src.exists()
        assert (dst / "keep.txt").read_text() == "keep"
        assert not (dst / "drop.txt").exists()

    def test_move_nonexistent_src_not_found(self, backend, tmp_path):
        assert (
            backend.move(
                _url(tmp_path, "missing"), _url(tmp_path, "dest"),
            )
            == BackendResult.ERROR_NOT_FOUND
        )


# ──────────────────────────────────────────────────────────────────────────────
# delete
# ──────────────────────────────────────────────────────────────────────────────

class TestDelete:
    @pytest.fixture
    def backend(self):
        return LocalFSBackend()

    def test_delete_file(self, backend, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        assert backend.delete(_url(tmp_path, "a.txt")) == BackendResult.OK
        assert not f.exists()

    def test_delete_folder_recursive(self, backend, tmp_path):
        d = tmp_path / "sub"
        d.mkdir()
        (d / "inner.txt").write_text("i")
        (d / "nested").mkdir()
        (d / "nested" / "deep.txt").write_text("d")
        assert backend.delete(_url(tmp_path, "sub")) == BackendResult.OK
        assert not d.exists()

    def test_delete_nonexistent_returns_not_found(self, backend, tmp_path):
        assert (
            backend.delete(_url(tmp_path, "missing"))
            == BackendResult.ERROR_NOT_FOUND
        )

    @pytest.mark.skipif(
        IS_WINDOWS, reason="POSIX symlink test",
    )
    def test_delete_symlink_removes_link_not_target(self, backend, tmp_path):
        target = tmp_path / "target.txt"
        target.write_text("keep")
        link = tmp_path / "link"
        os.symlink(str(target), str(link))
        assert backend.delete(_url(tmp_path, "link")) == BackendResult.OK
        assert not link.exists()
        assert target.exists()  # target untouched


# ──────────────────────────────────────────────────────────────────────────────
# URL utilities: normalize, join, parent, basename
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalizeUrl:
    @pytest.fixture
    def backend(self):
        return LocalFSBackend()

    def test_collapses_dotdot(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        assert backend.normalize_url("/a/b/../c") == "/a/c"

    def test_collapses_dot(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        assert backend.normalize_url("/a/./b") == "/a/b"

    def test_strips_trailing_slash(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        assert backend.normalize_url("/a/b/") == "/a/b"

    def test_preserves_file_scheme(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        assert backend.normalize_url("file:///a/b/../c") == "file:///a/c"

    def test_root_posix(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        assert backend.normalize_url("/") == "/"
        assert backend.normalize_url("file:///") == "file:///"

    def test_round_trip_idempotent(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        once = backend.normalize_url("file:///a/b/../c/./d")
        twice = backend.normalize_url(once)
        assert once == twice


class TestJoinUrl:
    @pytest.fixture
    def backend(self):
        return LocalFSBackend()

    def test_join_without_scheme(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        assert backend.join_url("/a", "b") == "/a/b"

    def test_join_with_file_scheme(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        assert backend.join_url("file:///a", "b") == "file:///a/b"

    def test_join_preserves_scheme_when_nested(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        out = backend.join_url("file:///a", "b/c")
        assert out == "file:///a/b/c"

    def test_join_collapses_dotdot_child(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        assert backend.join_url("/a/b", "../c") == "/a/c"


class TestParentUrl:
    @pytest.fixture
    def backend(self):
        return LocalFSBackend()

    def test_posix_root_returns_none(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX root test")
        assert backend.parent_url("/") is None
        assert backend.parent_url("file:///") is None

    def test_parent_of_child(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        assert backend.parent_url("/a/b") == "/a"

    def test_parent_preserves_scheme(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        assert backend.parent_url("file:///a/b") == "file:///a"

    def test_grandparent(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        assert backend.parent_url("/a/b/c") == "/a/b"


class TestBasename:
    @pytest.fixture
    def backend(self):
        return LocalFSBackend()

    def test_basic(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        assert backend.basename("/tmp/foo.usd") == "foo.usd"

    def test_with_scheme(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        assert backend.basename("file:///tmp/foo.usd") == "foo.usd"

    def test_trailing_slash_still_works(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        assert backend.basename("/tmp/foo/") == "foo"

    def test_root_is_empty(self, backend):
        if IS_WINDOWS:
            pytest.skip("POSIX test")
        # Basename of root is "" — Kit-equivalent behaviour.
        assert backend.basename("/") == ""


# ──────────────────────────────────────────────────────────────────────────────
# Flag decoding edge cases
# ──────────────────────────────────────────────────────────────────────────────

class TestFlagDecoding:
    @pytest.fixture
    def backend(self):
        return LocalFSBackend()

    def test_folder_flag_set_for_directory(self, backend, tmp_path):
        (tmp_path / "d").mkdir()
        _, entry = backend.stat(_url(tmp_path, "d"))
        assert entry is not None
        assert BackendFileFlags.IS_FOLDER in entry.flags

    def test_folder_flag_unset_for_file(self, backend, tmp_path):
        (tmp_path / "f.txt").write_text("x")
        _, entry = backend.stat(_url(tmp_path, "f.txt"))
        assert entry is not None
        assert BackendFileFlags.IS_FOLDER not in entry.flags

    def test_hidden_flag_set_for_dotfile(self, backend, tmp_path):
        if IS_WINDOWS:
            pytest.skip("POSIX hidden-file test")
        (tmp_path / ".hidden").write_text("x")
        _, entry = backend.stat(_url(tmp_path, ".hidden"))
        assert entry is not None
        assert BackendFileFlags.IS_HIDDEN in entry.flags

    def test_hidden_flag_unset_for_normal_file(self, backend, tmp_path):
        (tmp_path / "visible.txt").write_text("x")
        _, entry = backend.stat(_url(tmp_path, "visible.txt"))
        assert entry is not None
        assert BackendFileFlags.IS_HIDDEN not in entry.flags

    def test_readable_flag_for_readable_file(self, backend, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text("x")
        _, entry = backend.stat(_url(tmp_path, "r.txt"))
        assert entry is not None
        assert BackendFileFlags.IS_READABLE in entry.flags

    def test_writable_flag_for_writable_file(self, backend, tmp_path):
        f = tmp_path / "w.txt"
        f.write_text("x")
        _, entry = backend.stat(_url(tmp_path, "w.txt"))
        assert entry is not None
        assert BackendFileFlags.IS_WRITABLE in entry.flags

    @pytest.mark.skipif(
        IS_WINDOWS or os.geteuid() == 0,  # type: ignore[attr-defined]
        reason="POSIX chmod test (not root)",
    )
    def test_writable_flag_unset_for_readonly_file(
        self, backend, tmp_path,
    ):
        f = tmp_path / "ro.txt"
        f.write_text("x")
        orig_mode = f.stat().st_mode
        try:
            os.chmod(f, 0o444)
            _, entry = backend.stat(_url(tmp_path, "ro.txt"))
            assert entry is not None
            assert BackendFileFlags.IS_READABLE in entry.flags
            assert BackendFileFlags.IS_WRITABLE not in entry.flags
        finally:
            os.chmod(f, orig_mode)

    @pytest.mark.skipif(
        IS_WINDOWS, reason="POSIX symlink test",
    )
    def test_symlink_flag_set_on_symlink(self, backend, tmp_path):
        target = tmp_path / "target.txt"
        target.write_text("t")
        os.symlink(str(target), str(tmp_path / "link"))
        _, entry = backend.stat(_url(tmp_path, "link"))
        assert entry is not None
        assert BackendFileFlags.IS_SYMLINK in entry.flags


# ──────────────────────────────────────────────────────────────────────────────
# subscribe_changes inherits the no-op default (the content browser implementation step 10 adds a
# real implementation; for now the ABC default is what's used).
# ──────────────────────────────────────────────────────────────────────────────

class TestSubscribeChangesDefault:
    def test_returns_cancellable(self):
        backend = LocalFSBackend()
        sub = backend.subscribe_changes("file:///tmp", lambda evt: None)
        assert hasattr(sub, "cancel")
        sub.cancel()  # must not raise
        sub.cancel()  # idempotent

    def test_callback_not_invoked_by_default(self, tmp_path):
        backend = LocalFSBackend()
        fired = []
        backend.subscribe_changes(
            _url(tmp_path), lambda evt: fired.append(evt),
        )
        (tmp_path / "x.txt").write_text("x")  # FS event — no callback yet
        assert fired == []

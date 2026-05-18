# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 43 — MyComputerCollection + disk_partitions.

See the content browser behavior (FileSystemCollectionItem) and
§14.1 (``disk_partitions.py``). ``MyComputerCollection`` enumerates
real disk roots (drive letters on Windows, mount points on POSIX) and
appends user-folder shortcuts. Its enumerator is a pure-Python parse
of ``/proc/mounts`` — no psutil — so the tests can drive the filter
logic with fixture files and monkey-patched home directories.

These tests are POSIX-focused. Windows drive enumeration goes through
``ctypes.windll.kernel32.GetLogicalDrives`` which is not available on
the test host; a single guard test asserts that the POSIX parser
raises :class:`NotImplementedError` there so the Windows codepath is
not silently exercised on the wrong platform.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List

import pytest

from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.content.widget.collections.disk_partitions import (
    FSTYPE_BLOCKLIST,
    Partition,
    _parse_mounts_line,
    disk_partitions,
)
from ovwidgets.content.widget.collections.my_computer import (
    MyComputerCollection,
)
from ovwidgets.content.widget.file_item import FileItem

# ──────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ──────────────────────────────────────────────────────────────────────────────


def _write_mounts_file(path: Path, lines: Iterable[str]) -> None:
    """Write a synthetic ``/proc/mounts`` fixture file.

    Each line is terminated with ``\\n`` — the kernel writes trailing
    newlines and :func:`disk_partitions` has to tolerate them.
    """
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def patched_mounts(monkeypatch, tmp_path):
    """Monkey-patch :data:`MOUNTS_PATH` so tests drive the parser off
    a deterministic fixture file instead of the host's ``/proc/mounts``.

    Returns a callable taking an iterable of ``/proc/mounts`` lines;
    the callable writes them to a temp file and patches the module
    constant to point at it. The parser re-reads the file on every
    :func:`disk_partitions` call so a single fixture can be rewritten
    mid-test if a future test wants to simulate a runtime mount change.
    """
    from ovwidgets.content.widget.collections import disk_partitions as dp_mod

    def _install(lines: Iterable[str]) -> Path:
        mounts_file = tmp_path / "proc_mounts"
        _write_mounts_file(mounts_file, lines)
        monkeypatch.setattr(dp_mod, "MOUNTS_PATH", str(mounts_file))
        return mounts_file

    return _install


@pytest.fixture
def patched_home(monkeypatch, tmp_path):
    """Monkey-patch :meth:`Path.home` so user-folder enumeration runs
    against a controlled directory tree instead of the real ``$HOME``.

    Returns the ``tmp_path`` / ``home`` root so the test can create /
    delete user-folder subdirectories to drive the existence check.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    return fake_home


# ──────────────────────────────────────────────────────────────────────────────
# disk_partitions — parser surface
# ──────────────────────────────────────────────────────────────────────────────


class TestDiskPartitionsParser:
    def test_parse_simple_line(self):
        partition = _parse_mounts_line(
            "/dev/sda1 /boot ext4 rw,relatime 0 0",
        )
        assert partition == Partition(
            device="/dev/sda1",
            mountpoint="/boot",
            fstype="ext4",
            opts="rw,relatime",
        )

    def test_parse_blank_line_returns_none(self):
        assert _parse_mounts_line("") is None
        assert _parse_mounts_line("   ") is None

    def test_parse_short_line_returns_none(self):
        # Fewer than 4 whitespace-separated fields — invalid kernel row.
        assert _parse_mounts_line("/dev/sda1 /boot") is None

    def test_parse_decodes_space_escape(self):
        # Kernel escapes ``' '`` as ``\040`` in mount-point paths.
        partition = _parse_mounts_line(
            "/dev/sdb1 /mnt/My\\040Drive ext4 rw 0 0",
        )
        assert partition is not None
        assert partition.mountpoint == "/mnt/My Drive"

    def test_parse_decodes_tab_escape(self):
        partition = _parse_mounts_line(
            "/dev/sdb1 /mnt/Weird\\011Tab ext4 rw 0 0",
        )
        assert partition is not None
        assert partition.mountpoint == "/mnt/Weird\tTab"

    def test_parse_decodes_backslash_escape(self):
        partition = _parse_mounts_line(
            "/dev/sdb1 /mnt/back\\134slash ext4 rw 0 0",
        )
        assert partition is not None
        assert partition.mountpoint == "/mnt/back\\slash"

    def test_partition_is_frozen(self):
        partition = Partition("/dev/sda1", "/", "ext4", "rw")
        with pytest.raises((AttributeError, Exception)):
            partition.mountpoint = "/other"  # type: ignore[misc]

    def test_disk_partitions_reads_fixture_file(self, patched_mounts):
        patched_mounts([
            "/dev/sda1 / ext4 rw,relatime 0 0",
            "/dev/sda2 /home ext4 rw,relatime 0 0",
        ])
        partitions = disk_partitions()
        assert [p.mountpoint for p in partitions] == ["/", "/home"]
        assert [p.fstype for p in partitions] == ["ext4", "ext4"]

    def test_disk_partitions_tolerates_trailing_blank(self, patched_mounts):
        patched_mounts([
            "/dev/sda1 / ext4 rw 0 0",
            "",
        ])
        partitions = disk_partitions()
        assert [p.mountpoint for p in partitions] == ["/"]

    def test_disk_partitions_preserves_mount_order(self, patched_mounts):
        patched_mounts([
            "/dev/sdb1 /z ext4 rw 0 0",
            "/dev/sda1 /a ext4 rw 0 0",
            "/dev/sdc1 /m ext4 rw 0 0",
        ])
        partitions = disk_partitions()
        # Kernel order — no sort applied by the parser.
        assert [p.mountpoint for p in partitions] == ["/z", "/a", "/m"]

    def test_fstype_blocklist_has_expected_entries(self):
        # The architecture spec (§13.7 / §14.1) names an explicit eight-
        # entry set. Asserting the full set catches accidental drift.
        assert FSTYPE_BLOCKLIST == frozenset({
            "tmpfs",
            "proc",
            "devpts",
            "sysfs",
            "nsfs",
            "autofs",
            "cgroup",
            "hugetlbfs",
        })


@pytest.mark.skipif(os.name != "nt", reason="Windows-only guard")
def test_disk_partitions_raises_on_windows():  # pragma: no cover - not run here
    # On Windows, ``disk_partitions`` must NOT silently return [] —
    # callers are expected to branch on ``os.name`` and not fall into
    # the POSIX codepath by mistake.
    with pytest.raises(NotImplementedError):
        disk_partitions()


# ──────────────────────────────────────────────────────────────────────────────
# MyComputerCollection — identity
# ──────────────────────────────────────────────────────────────────────────────


class TestMyComputerIdentity:
    def test_identifier(self):
        assert MyComputerCollection().identifier == "my-computer"

    def test_title(self):
        assert MyComputerCollection().title == "My Computer"

    def test_icon_key(self):
        # The style system registers ``content_home`` — a blank key
        # would leave the nav row icon-less, so the non-empty
        # invariant is what the delegate's render path cares about.
        assert MyComputerCollection().icon_key == "content_home"

    def test_is_folder(self):
        # Collections are always expandable.
        assert MyComputerCollection().is_folder is True


# ──────────────────────────────────────────────────────────────────────────────
# MyComputerCollection — POSIX enumeration
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only behaviour")
class TestPosixEnumeration:
    def test_filters_tmpfs_proc_sysfs(self, patched_mounts, patched_home):
        patched_mounts([
            "/dev/sda1 / ext4 rw,relatime 0 0",
            "tmpfs /run tmpfs rw 0 0",
            "proc /proc proc rw 0 0",
            "sysfs /sys sysfs rw 0 0",
            "/dev/sda2 /home ext4 rw,relatime 0 0",
        ])
        children = MyComputerCollection().get_children(MockBackend())
        mountpoints = [c.name for c in children]
        # The fstype-blocklist entries must not appear; the two real
        # mounts must.
        assert "/" in mountpoints
        assert "/home" in mountpoints
        assert "/run" not in mountpoints
        assert "/proc" not in mountpoints
        assert "/sys" not in mountpoints

    def test_filters_all_blocklist_fstypes(self, patched_mounts, patched_home):
        # One entry per blocklist fstype — every one must be dropped.
        lines = [f"dev{i} /mnt/{fs} {fs} rw 0 0"
                 for i, fs in enumerate(FSTYPE_BLOCKLIST)]
        # Plus one surviving real mount so we can confirm the filter
        # didn't swallow everything indiscriminately.
        lines.append("/dev/sda1 / ext4 rw 0 0")
        patched_mounts(lines)
        children = MyComputerCollection().get_children(MockBackend())
        mountpoints = {c.name for c in children}
        for fs in FSTYPE_BLOCKLIST:
            assert f"/mnt/{fs}" not in mountpoints
        assert "/" in mountpoints

    def test_inserts_root_if_missing(self, patched_mounts, patched_home):
        # No ``/`` entry in the mount table — the collection must
        # insert it at the top so the user always has a way to reach
        # the filesystem root from "My Computer".
        patched_mounts([
            "/dev/sda2 /home ext4 rw,relatime 0 0",
        ])
        children = MyComputerCollection().get_children(MockBackend())
        mount_names = [c.name for c in children]
        assert mount_names[0] == "/"
        assert mount_names[1] == "/home"

    def test_does_not_duplicate_root_when_present(
        self, patched_mounts, patched_home,
    ):
        patched_mounts([
            "/dev/sda1 / ext4 rw,relatime 0 0",
            "/dev/sda2 /home ext4 rw,relatime 0 0",
        ])
        children = MyComputerCollection().get_children(MockBackend())
        roots = [c for c in children if c.name == "/"]
        assert len(roots) == 1

    def test_dedups_repeated_mount_points(self, patched_mounts, patched_home):
        # A mount point that appears twice in ``/proc/mounts`` (the
        # kernel does this when a filesystem is mounted on top of
        # another) should surface only once.
        patched_mounts([
            "/dev/sda1 / ext4 rw 0 0",
            "/dev/sdb1 /data ext4 rw 0 0",
            "/dev/sdb1 /data ext4 rw 0 0",
        ])
        children = MyComputerCollection().get_children(MockBackend())
        data_entries = [c for c in children if c.name == "/data"]
        assert len(data_entries) == 1

    def test_children_are_file_items(self, patched_mounts, patched_home):
        patched_mounts([
            "/dev/sda1 / ext4 rw 0 0",
        ])
        children = MyComputerCollection().get_children(MockBackend())
        assert all(isinstance(c, FileItem) for c in children)

    def test_mount_urls_use_file_scheme(self, patched_mounts, patched_home):
        patched_mounts([
            "/dev/sda1 / ext4 rw 0 0",
            "/dev/sdb1 /mnt/extra ext4 rw 0 0",
        ])
        children = MyComputerCollection().get_children(MockBackend())
        urls = {c.name: c.url for c in children}
        assert urls["/"] == "file:///"
        assert urls["/mnt/extra"] == "file:///mnt/extra"

    def test_mount_items_are_folders(self, patched_mounts, patched_home):
        patched_mounts([
            "/dev/sda1 / ext4 rw 0 0",
            "/dev/sdb1 /mnt/extra ext4 rw 0 0",
        ])
        children = MyComputerCollection().get_children(MockBackend())
        assert all(c.is_folder for c in children)


# ──────────────────────────────────────────────────────────────────────────────
# MyComputerCollection — user folders
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only behaviour")
class TestUserFolders:
    def test_no_user_folders_when_none_exist(
        self, patched_mounts, patched_home,
    ):
        # patched_home creates ``home/`` but no subfolders — none of
        # the four user-folder names exist, so none are surfaced.
        patched_mounts([
            "/dev/sda1 / ext4 rw 0 0",
        ])
        children = MyComputerCollection().get_children(MockBackend())
        names = [c.name for c in children]
        for folder in ("Desktop", "Documents", "Downloads", "Pictures"):
            assert folder not in names

    def test_includes_existing_user_folders(
        self, patched_mounts, patched_home,
    ):
        (patched_home / "Desktop").mkdir()
        (patched_home / "Documents").mkdir()
        patched_mounts([
            "/dev/sda1 / ext4 rw 0 0",
        ])
        children = MyComputerCollection().get_children(MockBackend())
        names = [c.name for c in children]
        assert "Desktop" in names
        assert "Documents" in names
        # Not created → not surfaced.
        assert "Downloads" not in names
        assert "Pictures" not in names

    def test_user_folder_urls_point_at_home(
        self, patched_mounts, patched_home,
    ):
        (patched_home / "Documents").mkdir()
        patched_mounts([
            "/dev/sda1 / ext4 rw 0 0",
        ])
        children = MyComputerCollection().get_children(MockBackend())
        docs = next(c for c in children if c.name == "Documents")
        assert docs.url == f"file://{patched_home}/Documents"

    def test_user_folders_are_folders(
        self, patched_mounts, patched_home,
    ):
        (patched_home / "Pictures").mkdir()
        patched_mounts([
            "/dev/sda1 / ext4 rw 0 0",
        ])
        children = MyComputerCollection().get_children(MockBackend())
        pictures = next(c for c in children if c.name == "Pictures")
        assert pictures.is_folder is True

    def test_user_folders_follow_mounts(
        self, patched_mounts, patched_home,
    ):
        # Display contract: mount-point rows come first, then the
        # user-folder shortcuts. Lock the order so a later refactor
        # can't silently reshuffle the nav pane.
        (patched_home / "Desktop").mkdir()
        patched_mounts([
            "/dev/sda1 / ext4 rw 0 0",
            "/dev/sdb1 /mnt/extra ext4 rw 0 0",
        ])
        children = MyComputerCollection().get_children(MockBackend())
        names = [c.name for c in children]
        # Mount points appear before user folders.
        desktop_idx = names.index("Desktop")
        extra_idx = names.index("/mnt/extra")
        root_idx = names.index("/")
        assert root_idx < extra_idx < desktop_idx

    def test_user_folder_order_is_standard(
        self, patched_mounts, patched_home,
    ):
        # Desktop / Documents / Downloads / Pictures — the order Kit's
        # filebrowser uses for its quick-access links.
        for name in ("Desktop", "Documents", "Downloads", "Pictures"):
            (patched_home / name).mkdir()
        patched_mounts([
            "/dev/sda1 / ext4 rw 0 0",
        ])
        children = MyComputerCollection().get_children(MockBackend())
        names = [c.name for c in children]
        user_indices = [
            names.index(n)
            for n in ("Desktop", "Documents", "Downloads", "Pictures")
        ]
        assert user_indices == sorted(user_indices)


# ──────────────────────────────────────────────────────────────────────────────
# Caching contract
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only behaviour")
class TestChildrenCache:
    def test_returns_same_instances_across_calls(
        self, patched_mounts, patched_home,
    ):
        # The cache must hand back the SAME FileItem instances each
        # call — not freshly constructed ones — so ``omni.ui.TreeView``
        # (which holds items by raw C++ pointer via pybind11) can
        # reconstruct their Python-subclass identity on render. Fresh
        # instances would silently lose the ``FileItem`` type on the
        # C++ → Python boundary and the delegate's name / icon render
        # path would bail.
        patched_mounts([
            "/dev/sda1 / ext4 rw 0 0",
        ])
        collection = MyComputerCollection()
        first = collection.get_children(MockBackend())
        second = collection.get_children(MockBackend())
        assert len(first) > 0
        assert first is second

    def test_refresh_drops_cache(self, patched_mounts, patched_home):
        patched_mounts([
            "/dev/sda1 / ext4 rw 0 0",
        ])
        collection = MyComputerCollection()
        first = collection.get_children(MockBackend())
        collection.refresh()
        # Change the underlying mount fixture so a successful refresh
        # produces a visibly different result — otherwise a no-op
        # cache drop would pass this test trivially.
        patched_mounts([
            "/dev/sda1 / ext4 rw 0 0",
            "/dev/sdb1 /mnt/usb ext4 rw 0 0",
        ])
        second = collection.get_children(MockBackend())
        assert first is not second
        assert any(c.name == "/mnt/usb" for c in second)


# ──────────────────────────────────────────────────────────────────────────────
# Integration — via NavigationModel
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only behaviour")
class TestNavigationModelIntegration:
    def test_my_computer_collection_reachable_via_nav_model(
        self, patched_mounts, patched_home,
    ):
        # End-to-end: the NavigationModel's default collection list
        # contains the *real* MyComputerCollection (not the Step 42
        # stub), so get_item_children on that collection returns the
        # enumerated mount points.
        from ovwidgets.content.widget import NavigationModel

        patched_mounts([
            "/dev/sda1 / ext4 rw 0 0",
        ])
        model = NavigationModel(MockBackend())
        my_computer = model.find_collection("my-computer")
        assert my_computer is not None
        assert isinstance(my_computer, MyComputerCollection)

        children: List[FileItem] = list(
            model.get_item_children(my_computer),
        )
        names = [c.name for c in children]
        assert "/" in names

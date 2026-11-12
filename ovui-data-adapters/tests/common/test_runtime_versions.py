# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Help > About names the full version of the ovrtx copy that is loaded.

These tests write real small ovrtx copies on disk. Their version, 9.8.7.654321
with ``__version__ = "9.8.7"``, matches no released ovrtx, so a lookup of the
installed ovrtx instead of the loaded copy cannot pass them.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys

import pytest

from ovui_data_adapters.common import ovrtx_import


FULL = "9.8.7.654321"
SHORT = "9.8.7"


def _write_ovrtx(directory, *, version_file=None, metadata=None, raise_import=False):
    """Write an ovrtx copy into ``directory``, the folder on the import path."""
    package = directory / "ovrtx"
    package.mkdir(parents=True)
    body = f'__version__ = "{SHORT}"\n'
    if raise_import:
        body += 'raise ImportError("this copy is broken")\n'
    (package / "__init__.py").write_text(body, encoding="utf-8")
    if version_file is not None:
        (package / "_version.py").write_bytes(version_file)
    if metadata is not None:
        dist_info = directory / f"ovrtx-{FULL}.dist-info"
        dist_info.mkdir()
        (dist_info / "METADATA").write_bytes(metadata)
    return package


def _metadata(version: bytes) -> bytes:
    return b"Metadata-Version: 2.1\nName: ovrtx\nVersion: " + version + b"\n"


def _link_directory(link, target):
    """Make ``link`` reach the directory ``target`` (a junction on Windows)."""
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            raise
        import _winapi

        _winapi.CreateJunction(str(target), str(link))


def _forget_ovrtx():
    for name in list(sys.modules):
        if name == "ovrtx" or name.startswith("ovrtx."):
            del sys.modules[name]


@pytest.fixture
def resolve_from_root(monkeypatch):
    """Resolve ovrtx through ``OVRTX_ROOT`` with no ovrtx loaded before."""

    def resolve(root):
        _forget_ovrtx()
        ovrtx_import.reset_ovrtx_import_cache()
        monkeypatch.setenv(ovrtx_import.OVRTX_ROOT_ENV, str(root))
        return ovrtx_import.import_ovrtx()

    yield resolve
    _forget_ovrtx()
    ovrtx_import.reset_ovrtx_import_cache()


def test_version_file_gives_the_full_version_of_a_root_copy(tmp_path, resolve_from_root):
    root = tmp_path / "root"
    _write_ovrtx(
        root / "python",
        version_file=b"major = 9\nminor = 8\npatch = 7\nbuild_number = 654321\n",
    )

    result = resolve_from_root(root)

    assert result.module.__version__ == SHORT
    assert ovrtx_import.loaded_ovrtx_version() == FULL


def test_root_version_reads_the_metadata_of_a_root_copy_that_is_not_loaded(
    tmp_path, monkeypatch
):
    _forget_ovrtx()
    ovrtx_import.reset_ovrtx_import_cache()
    root = tmp_path / "root"
    _write_ovrtx(root / "python", metadata=_metadata(FULL.encode()))
    monkeypatch.setenv(ovrtx_import.OVRTX_ROOT_ENV, str(root))

    assert ovrtx_import.ovrtx_root_version() == FULL


def test_root_version_names_the_loaded_copy_not_a_rejected_one(tmp_path, resolve_from_root):
    root = tmp_path / "root"
    rejected = _write_ovrtx(root / "public" / "python", raise_import=True)
    (rejected / "_version.py").write_text("version = '0.4.0'\n", encoding="utf-8")
    _write_ovrtx(root / "python", metadata=_metadata(FULL.encode()))

    result = resolve_from_root(root)

    assert result.source == str(root / "python")
    assert ovrtx_import.ovrtx_root_version() == FULL


def test_openusd_session_reports_the_loaded_ovrtx(tmp_path, resolve_from_root):
    from ovui_data_adapters.openusd.provider import OpenUSDProviderSession

    root = tmp_path / "root"
    rejected = _write_ovrtx(root / "public" / "python", raise_import=True)
    (rejected / "_version.py").write_text("version = '0.4.0'\n", encoding="utf-8")
    _write_ovrtx(root / "python", metadata=_metadata(FULL.encode()))
    resolve_from_root(root)

    versions = dict(OpenUSDProviderSession().runtime_component_versions())

    assert versions["ovrtx"] == FULL


def test_a_linked_root_copy_gives_its_own_metadata(tmp_path, resolve_from_root):
    elsewhere = tmp_path / "elsewhere"
    target = _write_ovrtx(elsewhere, metadata=_metadata(b"1.2.3.4"))
    (elsewhere / f"ovrtx-{FULL}.dist-info").rename(elsewhere / "ovrtx-1.2.3.4.dist-info")
    root = tmp_path / "root"
    (root / "python").mkdir(parents=True)
    _link_directory(root / "python" / "ovrtx", target)
    dist_info = root / "python" / f"ovrtx-{FULL}.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_bytes(_metadata(FULL.encode()))

    resolve_from_root(root)

    assert ovrtx_import.loaded_ovrtx_version() == FULL


def test_corrupt_metadata_is_reported_with_the_fallback(tmp_path, resolve_from_root, caplog):
    root = tmp_path / "root"
    _write_ovrtx(root / "python", metadata=_metadata(b"\xff\xfe"))
    resolve_from_root(root)

    with caplog.at_level(logging.WARNING, logger=ovrtx_import.__name__):
        version = ovrtx_import.loaded_ovrtx_version()

    assert version == SHORT
    metadata_path = root / "python" / f"ovrtx-{FULL}.dist-info" / "METADATA"
    report = caplog.text
    assert str(metadata_path) in report
    assert "UnicodeDecodeError" in report
    assert "comes from __version__" in report


def test_unreadable_version_file_is_reported_and_metadata_is_used(
    tmp_path, resolve_from_root, caplog
):
    root = tmp_path / "root"
    _write_ovrtx(
        root / "python",
        version_file=b"major = 9\nminor = (\n",
        metadata=_metadata(FULL.encode()),
    )
    resolve_from_root(root)

    with caplog.at_level(logging.WARNING, logger=ovrtx_import.__name__):
        version = ovrtx_import.loaded_ovrtx_version()

    assert version == FULL
    report = caplog.text
    assert str(root / "python" / "ovrtx" / "_version.py") in report
    assert "SyntaxError" in report
    assert "comes from its metadata" in report


def test_a_copy_without_version_files_uses_its_version_quietly(
    tmp_path, resolve_from_root, caplog
):
    root = tmp_path / "root"
    _write_ovrtx(root / "python")
    resolve_from_root(root)

    with caplog.at_level(logging.WARNING, logger=ovrtx_import.__name__):
        version = ovrtx_import.loaded_ovrtx_version()

    assert version == SHORT
    assert caplog.text == ""


def test_root_version_does_not_name_a_copy_loaded_from_elsewhere(
    tmp_path, monkeypatch, resolve_from_root
):
    elsewhere = tmp_path / "site-packages"
    _write_ovrtx(elsewhere, metadata=_metadata(b"1.2.3.4"))
    (elsewhere / f"ovrtx-{FULL}.dist-info").rename(elsewhere / "ovrtx-1.2.3.4.dist-info")
    monkeypatch.syspath_prepend(str(elsewhere))
    _forget_ovrtx()
    ovrtx_import.reset_ovrtx_import_cache()
    monkeypatch.delenv(ovrtx_import.OVRTX_ROOT_ENV, raising=False)
    assert ovrtx_import.import_ovrtx().source == "active environment"
    root = tmp_path / "root"
    _write_ovrtx(root / "python", metadata=_metadata(FULL.encode()))
    monkeypatch.setenv(ovrtx_import.OVRTX_ROOT_ENV, str(root))

    assert ovrtx_import.ovrtx_root_version() == FULL


# Permission bits do not stop root, and Windows does not apply them this way.
needs_posix_permissions = pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason="needs POSIX permission bits that apply to this user",
)


@pytest.fixture
def restore_modes():
    """Give back the permissions a test took away, so the folder can be removed."""
    changed = []

    def take(path, mode):
        changed.append((path, path.lstat().st_mode & 0o777))
        path.chmod(mode)

    yield take
    for path, mode in reversed(changed):
        path.chmod(mode)


def _load_ovrtx(directory):
    spec = importlib.util.spec_from_file_location("ovrtx", directory / "ovrtx" / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@needs_posix_permissions
def test_version_file_that_cannot_be_reached_is_reported_and_metadata_is_used(
    tmp_path, restore_modes, caplog
):
    site = tmp_path / "site-packages"
    _write_ovrtx(site, metadata=_metadata(FULL.encode()))
    closed = tmp_path / "closed"
    closed.mkdir()
    (closed / "_version.py").write_text("major = 1\nminor = 0\npatch = 0\n", encoding="utf-8")
    (site / "ovrtx" / "_version.py").symlink_to(closed / "_version.py")
    module = _load_ovrtx(site)
    restore_modes(closed, 0o600)

    with caplog.at_level(logging.WARNING, logger=ovrtx_import.__name__):
        version = ovrtx_import.loaded_module_version(module, "ovrtx")

    assert version == FULL
    report = caplog.text
    assert str(site / "ovrtx" / "_version.py") in report
    assert "PermissionError" in report
    assert "comes from its metadata" in report


@needs_posix_permissions
def test_metadata_folder_that_cannot_be_listed_is_reported(tmp_path, restore_modes, caplog):
    site = tmp_path / "site-packages"
    _write_ovrtx(site, metadata=_metadata(FULL.encode()))
    module = _load_ovrtx(site)
    restore_modes(site / f"ovrtx-{FULL}.dist-info" / "METADATA", 0o000)
    restore_modes(site, 0o300)

    with caplog.at_level(logging.WARNING, logger=ovrtx_import.__name__):
        version = ovrtx_import.loaded_module_version(module, "ovrtx")

    assert version == SHORT
    report = caplog.text
    assert f"cannot list {site}" in report
    assert "PermissionError" in report
    assert "comes from __version__" in report

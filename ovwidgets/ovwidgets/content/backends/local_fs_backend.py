# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Concrete :class:`BackendAdapter` for the local filesystem.

See the content browser behavior and the content browser implementation step 2.

The backend accepts either ``file://`` URLs or raw OS paths, translates
at the boundary via :func:`_url_to_fspath` / :func:`_fspath_to_url`, and
reports every failure as a :class:`BackendResult` rather than an
exception. Filtering of ``.thumbs`` directories, system files, and
hidden entries is deliberately a *model*-layer concern (Step 25 / 56);
this backend stays pure I/O.

Uses Python stdlib only — no ``omni.client``, no external dependencies.
"""

import os
import shutil
import stat as _stat
from typing import List, Optional, Tuple

from ovwidgets.content.backends.backend_adapter import (
    BackendAdapter,
    BackendFileFlags,
    BackendListEntry,
    BackendResult,
)

# ``file://`` scheme prefix. Throughout the content browser, URLs are
# normalised to forward slashes with this prefix on display; raw OS
# paths are accepted at the input boundary and translated here.
_SCHEME = "file://"

# Windows ``FILE_ATTRIBUTE_HIDDEN`` bit — not exposed in stdlib constants.
_WIN_HIDDEN_ATTR = 0x2


# ──────────────────────────────────────────────────────────────────────────────
# URL ↔ OS path translation
# ──────────────────────────────────────────────────────────────────────────────

def _url_to_fspath(url: str) -> str:
    """Accept ``file:///path``, ``/path``, ``~/path`` or ``C:/path``;
    return an OS-native path suitable for ``os.*`` calls.

    Strips a leading ``file://`` prefix and, on Windows, drops the
    spurious leading slash before a drive letter (``/C:/x`` → ``C:/x``).
    Expands ``~`` so callers can say ``"~/Documents"`` naturally.
    """
    if url.startswith(_SCHEME):
        url = url[len(_SCHEME):]
        if os.name == "nt" and len(url) >= 3 and url[0] == "/" and url[2] == ":":
            url = url[1:]
    return os.path.expanduser(url)


def _fspath_to_url(path: str) -> str:
    """Return the canonical ``file://`` URL for ``path``.

    Absolute path on POSIX: ``/foo`` → ``file:///foo``.
    Absolute path on Windows: ``C:/foo`` → ``file:///C:/foo``.
    """
    abs_path = os.path.abspath(path).replace("\\", "/")
    if os.name == "nt":
        return f"{_SCHEME}/{abs_path}"
    return f"{_SCHEME}{abs_path}"


def _canonicalise(fspath: str, had_scheme: bool) -> str:
    """Collapse ``..``/``.``, forward-slash, lowercase drive letter,
    and optionally re-apply the ``file://`` prefix.

    Shared helper for :meth:`LocalFSBackend.normalize_url` and
    :meth:`LocalFSBackend.join_url` — both need the same post-
    processing after deriving a path.
    """
    normalised = os.path.normpath(fspath).replace("\\", "/")
    if os.name == "nt" and len(normalised) >= 2 and normalised[1] == ":":
        normalised = normalised[0].lower() + normalised[1:]
    if had_scheme:
        if os.name == "nt":
            return f"{_SCHEME}/{normalised}"
        return f"{_SCHEME}{normalised}"
    return normalised


# ──────────────────────────────────────────────────────────────────────────────
# Flag decoding
# ──────────────────────────────────────────────────────────────────────────────

def _stat_to_flags(
    st: os.stat_result, name: str, is_symlink: bool,
) -> BackendFileFlags:
    """Decode a :class:`os.stat_result` into :class:`BackendFileFlags`.

    POSIX hidden files are identified by a leading ``.`` in ``name``;
    Windows hidden files are identified by the
    ``FILE_ATTRIBUTE_HIDDEN`` bit on ``st_file_attributes``.
    """
    flags = BackendFileFlags.NONE
    mode = st.st_mode
    if _stat.S_ISDIR(mode):
        flags |= BackendFileFlags.IS_FOLDER
    if is_symlink:
        flags |= BackendFileFlags.IS_SYMLINK
    if mode & _stat.S_IRUSR:
        flags |= BackendFileFlags.IS_READABLE
    if mode & _stat.S_IWUSR:
        flags |= BackendFileFlags.IS_WRITABLE
    if name.startswith("."):
        flags |= BackendFileFlags.IS_HIDDEN
    if os.name == "nt":
        attrs = getattr(st, "st_file_attributes", 0)
        if attrs & _WIN_HIDDEN_ATTR:
            flags |= BackendFileFlags.IS_HIDDEN
    return flags


# ──────────────────────────────────────────────────────────────────────────────
# LocalFSBackend
# ──────────────────────────────────────────────────────────────────────────────

class LocalFSBackend(BackendAdapter):
    """Local-filesystem :class:`BackendAdapter`.

    Accepts ``file://`` URLs, ``/absolute/posix`` paths, ``~`` paths,
    or Windows ``C:/...`` paths. Every mutating call returns a
    :class:`BackendResult`; no exceptions escape into callers.
    """

    # ── Scheme support ──

    def supports_url(self, url: str) -> bool:
        if not url:
            return False
        if url.startswith(_SCHEME):
            return True
        # Reject any other scheme (``http://``, ``omniverse://``, ``mock://``).
        if "://" in url:
            return False
        if url.startswith("/") or url.startswith("~"):
            return True
        drive, _ = os.path.splitdrive(url)
        return bool(drive)

    # ── Reads ──

    def stat(self, url: str) -> Tuple[BackendResult, Optional[BackendListEntry]]:
        fspath = _url_to_fspath(url)
        try:
            st = os.stat(fspath)
            is_symlink = os.path.islink(fspath)
        except FileNotFoundError:
            return (BackendResult.ERROR_NOT_FOUND, None)
        except PermissionError:
            return (BackendResult.ERROR_ACCESS_DENIED, None)
        except OSError:
            return (BackendResult.ERROR, None)
        name = os.path.basename(os.path.normpath(fspath)) or fspath
        return (
            BackendResult.OK,
            BackendListEntry(
                name=name,
                flags=_stat_to_flags(st, name, is_symlink),
                size=st.st_size,
                modified_time=st.st_mtime,
                created_time=st.st_ctime,
            ),
        )

    def list_dir(
        self, url: str,
    ) -> Tuple[BackendResult, List[BackendListEntry]]:
        fspath = _url_to_fspath(url)
        if not os.path.exists(fspath):
            return (BackendResult.ERROR_NOT_FOUND, [])
        if not os.path.isdir(fspath):
            return (BackendResult.ERROR, [])
        entries: List[BackendListEntry] = []
        try:
            with os.scandir(fspath) as it:
                for entry in it:
                    # Broken symlinks and no-access entries: skip rather
                    # than abort the listing (matches filebrowser
                    # OM-80351, the content browser implementation step 2).
                    try:
                        st = entry.stat()
                        is_symlink = entry.is_symlink()
                    except OSError:
                        continue
                    entries.append(BackendListEntry(
                        name=entry.name,
                        flags=_stat_to_flags(st, entry.name, is_symlink),
                        size=st.st_size,
                        modified_time=st.st_mtime,
                        created_time=st.st_ctime,
                    ))
        except PermissionError:
            return (BackendResult.ERROR_ACCESS_DENIED, [])
        except OSError:
            return (BackendResult.ERROR, [])
        return (BackendResult.OK, entries)

    # ── Writes ──

    def create_folder(self, url: str) -> BackendResult:
        fspath = _url_to_fspath(url)
        try:
            os.mkdir(fspath)
        except FileExistsError:
            return BackendResult.ERROR_ALREADY_EXISTS
        except FileNotFoundError:
            return BackendResult.ERROR_NOT_FOUND
        except PermissionError:
            return BackendResult.ERROR_ACCESS_DENIED
        except OSError:
            return BackendResult.ERROR
        return BackendResult.OK

    def copy(
        self, src_url: str, dst_url: str, overwrite: bool = False,
    ) -> BackendResult:
        src_fs = _url_to_fspath(src_url)
        dst_fs = _url_to_fspath(dst_url)
        if not os.path.lexists(src_fs):
            return BackendResult.ERROR_NOT_FOUND
        if os.path.lexists(dst_fs) and not overwrite:
            return BackendResult.ERROR_ALREADY_EXISTS
        try:
            if os.path.isdir(src_fs) and not os.path.islink(src_fs):
                shutil.copytree(src_fs, dst_fs, dirs_exist_ok=overwrite)
            else:
                shutil.copy2(src_fs, dst_fs)
        except FileExistsError:
            return BackendResult.ERROR_ALREADY_EXISTS
        except FileNotFoundError:
            return BackendResult.ERROR_NOT_FOUND
        except PermissionError:
            return BackendResult.ERROR_ACCESS_DENIED
        except OSError:
            return BackendResult.ERROR
        return BackendResult.OK

    def move(
        self, src_url: str, dst_url: str, overwrite: bool = False,
    ) -> BackendResult:
        src_fs = _url_to_fspath(src_url)
        dst_fs = _url_to_fspath(dst_url)
        if not os.path.lexists(src_fs):
            return BackendResult.ERROR_NOT_FOUND
        if os.path.lexists(dst_fs):
            if not overwrite:
                return BackendResult.ERROR_ALREADY_EXISTS
            # shutil.move has a surprise: for an existing destination
            # folder it moves *inside* that folder rather than
            # overwriting it. Strip the destination first so overwrite
            # actually means overwrite.
            try:
                if os.path.isdir(dst_fs) and not os.path.islink(dst_fs):
                    shutil.rmtree(dst_fs)
                else:
                    os.remove(dst_fs)
            except PermissionError:
                return BackendResult.ERROR_ACCESS_DENIED
            except OSError:
                return BackendResult.ERROR
        try:
            shutil.move(src_fs, dst_fs)
        except PermissionError:
            return BackendResult.ERROR_ACCESS_DENIED
        except OSError:
            return BackendResult.ERROR
        return BackendResult.OK

    def delete(self, url: str) -> BackendResult:
        fspath = _url_to_fspath(url)
        if not os.path.lexists(fspath):
            return BackendResult.ERROR_NOT_FOUND
        try:
            if os.path.isdir(fspath) and not os.path.islink(fspath):
                shutil.rmtree(fspath)
            else:
                os.remove(fspath)
        except PermissionError:
            return BackendResult.ERROR_ACCESS_DENIED
        except OSError:
            return BackendResult.ERROR
        return BackendResult.OK

    # ── URL utilities ──

    def normalize_url(self, url: str) -> str:
        return _canonicalise(_url_to_fspath(url), url.startswith(_SCHEME))

    def join_url(self, base: str, child: str) -> str:
        base_fs = _url_to_fspath(base)
        return _canonicalise(os.path.join(base_fs, child),
                             base.startswith(_SCHEME))

    def parent_url(self, url: str) -> Optional[str]:
        had_scheme = url.startswith(_SCHEME)
        fspath = os.path.normpath(_url_to_fspath(url))
        parent_fs = os.path.dirname(fspath)
        # ``os.path.dirname`` is idempotent at the filesystem root:
        # ``dirname("/") == "/"``, ``dirname("C:\\") == "C:\\"``. Use
        # that as the root sentinel.
        if parent_fs == fspath:
            return None
        return _canonicalise(parent_fs, had_scheme)

    def basename(self, url: str) -> str:
        return os.path.basename(os.path.normpath(_url_to_fspath(url)))

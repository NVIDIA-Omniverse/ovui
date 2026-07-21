# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Shared optional ovrtx import resolver for adapter runtimes."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import platform
import sys
from typing import Any


OVRTX_ROOT_ENV = "OVRTX_ROOT"
OVRTX_BIN_DIR_ENV = "OVRTX_BIN_DIR"
OVRTX_LIBRARY_PATH_HINT_ENV = "OVRTX_LIBRARY_PATH_HINT"

_OVRTX_DLL_HANDLES: list[Any] = []
_OVRTX_IMPORT_RESULT: "OvRtxImportResult | None" = None


@dataclass(frozen=True)
class OvRtxImportResult:
    """Outcome of resolving the optional ovrtx Python module."""

    module: Any | None
    error: BaseException | None
    source: str = ""

    @property
    def available(self) -> bool:
        return self.module is not None


def reset_ovrtx_import_cache() -> None:
    """Clear the cached resolver outcome.

    This is intended for tests that patch import state. Production callers rely
    on the one-shot resolver cache to avoid repeated native import attempts.
    """
    global _OVRTX_IMPORT_RESULT
    _OVRTX_IMPORT_RESULT = None


def _ovrtx_python_path_candidates(raw_root: str) -> tuple[Path, ...]:
    """Return import roots to try for an external ovrtx checkout."""
    raw_root = str(raw_root or "").strip()
    if not raw_root:
        return ()
    root = Path(raw_root).expanduser()
    candidates: list[Path] = []
    for candidate in (root / "public" / "python", root / "python", root):
        if (candidate / "ovrtx").is_dir() and candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _ovrtx_runtime_dirs(raw_root: str) -> tuple[Path, ...]:
    """Return likely native-runtime directories for an external ovrtx checkout."""
    raw_root = str(raw_root or "").strip()
    if not raw_root:
        return ()
    root = Path(raw_root).expanduser()
    candidates: list[Path] = []
    raw_bin = os.environ.get(OVRTX_BIN_DIR_ENV, "").strip()
    if raw_bin:
        candidates.append(Path(raw_bin).expanduser())
    candidates.extend((root / "bin", root / "python" / "ovrtx" / "bin"))
    platform_dir = _platform_build_dir_name()
    for build_root in (root / "_build", root.parent / "_build"):
        for config_name in ("release", "debug", "relwithdebinfo"):
            candidates.append(build_root / platform_dir / config_name)
        if build_root.is_dir():
            for config_name in ("release", "debug", "relwithdebinfo"):
                candidates.extend(sorted(build_root.glob(f"*/{config_name}")))
    dirs: list[Path] = []
    for candidate in candidates:
        if candidate.is_dir() and candidate not in dirs:
            dirs.append(candidate)
            for plugin_dir in (candidate / "plugins", candidate / "plugins" / "rtx"):
                if plugin_dir.is_dir() and plugin_dir not in dirs:
                    dirs.append(plugin_dir)
    return tuple(dirs)


def _platform_build_dir_name() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        arch = "x86_64"
    elif machine in {"aarch64", "arm64"}:
        arch = "aarch64" if sys.platform.startswith("linux") else "arm64"
    else:
        arch = machine or "unknown"
    if sys.platform.startswith("linux"):
        return f"linux-{arch}"
    if os.name == "nt":
        return f"windows-{arch}"
    if sys.platform == "darwin":
        return f"macos-{arch}"
    return f"{sys.platform}-{arch}"


def _configure_ovrtx_runtime_environment(raw_root: str) -> tuple[Path, ...]:
    runtime_dirs = _ovrtx_runtime_dirs(raw_root)
    if not runtime_dirs:
        return ()
    primary_dir = str(runtime_dirs[0])
    os.environ[OVRTX_LIBRARY_PATH_HINT_ENV] = primary_dir
    _prepend_env_paths("PATH", runtime_dirs)
    if not sys.platform.startswith("win"):
        _prepend_env_paths("LD_LIBRARY_PATH", runtime_dirs)
    return runtime_dirs


def _prepend_env_paths(env_name: str, paths: tuple[Path, ...]) -> None:
    current = [part for part in os.environ.get(env_name, "").split(os.pathsep) if part]
    prepended: list[str] = []
    for path in paths:
        path_str = str(path)
        if path_str not in prepended and path_str not in current:
            prepended.append(path_str)
    if prepended:
        os.environ[env_name] = os.pathsep.join([*prepended, *current])


def _add_windows_ovrtx_dll_directories(raw_root: str) -> list[Any]:
    """Register external ovrtx DLL directories on Windows."""
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if os.name != "nt" or not callable(add_dll_directory):
        return []
    handles: list[Any] = []
    for runtime_dir in _ovrtx_runtime_dirs(raw_root):
        try:
            handles.append(add_dll_directory(str(runtime_dir)))
        except OSError:
            continue
    return handles


def _close_dll_handles(handles: list[Any]) -> None:
    for handle in handles:
        close = getattr(handle, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _import_ovrtx_from_path(candidate: Path) -> Any:
    """Import ovrtx with ``candidate`` temporarily leading ``sys.path``."""
    candidate_str = str(candidate)
    inserted = False
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)
        inserted = True
    try:
        return importlib.import_module("ovrtx")
    finally:
        if inserted:
            try:
                sys.path.remove(candidate_str)
            except ValueError:
                pass


def _compose_ovrtx_import_error(
    normal_error: BaseException,
    raw_root: str,
    root_errors: list[str],
) -> ImportError:
    message = (
        "Could not import ovrtx from the active environment "
        f"({type(normal_error).__name__}: {normal_error})."
    )
    if raw_root:
        if root_errors:
            detail = "; ".join(root_errors)
        else:
            detail = "no import attempts were made"
        message = f"{message} {OVRTX_ROOT_ENV}={raw_root!r} also failed: {detail}"
    else:
        message = f"{message} {OVRTX_ROOT_ENV} is not set."
    return ImportError(message)


def import_ovrtx() -> OvRtxImportResult:
    """Resolve ovrtx from the active env first, then ``OVRTX_ROOT``."""
    global _OVRTX_IMPORT_RESULT
    if _OVRTX_IMPORT_RESULT is not None:
        return _OVRTX_IMPORT_RESULT

    try:
        module = importlib.import_module("ovrtx")
    except (ImportError, RuntimeError, OSError) as exc:
        normal_error = exc
    else:
        _OVRTX_IMPORT_RESULT = OvRtxImportResult(
            module=module,
            error=None,
            source="active environment",
        )
        return _OVRTX_IMPORT_RESULT

    raw_root = os.environ.get(OVRTX_ROOT_ENV, "").strip()
    root_errors: list[str] = []
    if raw_root:
        sys.modules.pop("ovrtx", None)
        _configure_ovrtx_runtime_environment(raw_root)
        candidates = _ovrtx_python_path_candidates(raw_root)
        if not candidates:
            root_errors.append(
                f"no importable ovrtx package found under {OVRTX_ROOT_ENV}"
            )
        for candidate in candidates:
            sys.modules.pop("ovrtx", None)
            handles = _add_windows_ovrtx_dll_directories(raw_root)
            try:
                module = _import_ovrtx_from_path(candidate)
            except (ImportError, RuntimeError, OSError) as path_exc:
                sys.modules.pop("ovrtx", None)
                _close_dll_handles(handles)
                root_errors.append(
                    f"{candidate}: {type(path_exc).__name__}: {path_exc}"
                )
                continue
            _OVRTX_DLL_HANDLES.extend(handles)
            _OVRTX_IMPORT_RESULT = OvRtxImportResult(
                module=module,
                error=None,
                source=str(candidate),
            )
            return _OVRTX_IMPORT_RESULT

    sys.modules.pop("ovrtx", None)
    _OVRTX_IMPORT_RESULT = OvRtxImportResult(
        module=None,
        error=_compose_ovrtx_import_error(normal_error, raw_root, root_errors),
        source="",
    )
    return _OVRTX_IMPORT_RESULT

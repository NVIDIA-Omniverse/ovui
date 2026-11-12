# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared optional ovrtx import resolver for adapter runtimes."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import importlib
import logging
import os
from pathlib import Path
import platform
import re
import sys
from typing import Any


OVRTX_ROOT_ENV = "OVRTX_ROOT"
OVRTX_BIN_DIR_ENV = "OVRTX_BIN_DIR"
OVRTX_LIBRARY_PATH_HINT_ENV = "OVRTX_LIBRARY_PATH_HINT"

_LOGGER = logging.getLogger(__name__)

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


def ovrtx_runtime_dirs() -> tuple[Path, ...]:
    """Return the native-runtime directories of the ``OVRTX_ROOT`` install.

    An ``OVRTX_ROOT`` install keeps its Python package and its runtime files in
    separate trees, so resources that ship beside the native libraries are not
    found next to ``ovrtx.__file__``.
    """
    return _ovrtx_runtime_dirs(os.environ.get(OVRTX_ROOT_ENV, ""))


def ovrtx_root_mdl_base_dirs() -> tuple[Path, ...]:
    """Return the MDL ``Base`` library directories of the ``OVRTX_ROOT`` install."""
    raw_root = os.environ.get(OVRTX_ROOT_ENV, "").strip()
    if not raw_root:
        return ()
    root = Path(raw_root).expanduser()
    return tuple(
        bin_dir / "library" / "mdl" / "Base"
        for bin_dir in (root / "bin", root / "python" / "ovrtx" / "bin")
    )


_VERSION_ASSIGNMENT = re.compile(r"""^__version__\s*=\s*["']([^"']+)["']""", re.MULTILINE)
_METADATA_VERSION = re.compile(r"^Version:[ \t]*(\S+)[ \t]*$", re.MULTILINE)
_VERSION_FILE_PARTS = ("major", "minor", "patch", "build_number")


def _version_from_version_file(package_dir: Path) -> tuple[str, str]:
    """Return ``(version, problem)`` from the ``_version.py`` of a package.

    The ovrtx and ovstage builds generate ``_version.py`` with ``major``,
    ``minor``, ``patch`` and ``build_number``; ovstage also writes ``version``.
    The file is read as text, so nothing is imported. A source tree has no such
    file, and that is not a problem. A file that exists but cannot be read is a
    problem; so is a link to a file that is missing or that cannot be reached.
    """
    path = package_dir / "_version.py"
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError) as exc:
        if not os.path.lexists(path):
            return "", ""
        return "", f"cannot read {path} ({type(exc).__name__}: {exc})"
    except (OSError, UnicodeDecodeError) as exc:
        return "", f"cannot read {path} ({type(exc).__name__}: {exc})"
    try:
        tree = ast.parse(text, filename=str(path))
    except (SyntaxError, ValueError) as exc:
        return "", f"cannot read {path} ({type(exc).__name__}: {exc})"
    values: dict[str, Any] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
        ):
            values[node.targets[0].id] = node.value.value
    version = values.get("version")
    if isinstance(version, str) and version.strip():
        return version.strip(), ""
    parts = [values.get(name) for name in _VERSION_FILE_PARTS]
    if all(isinstance(part, int) for part in parts[:3]):
        if not isinstance(parts[3], int):
            parts = parts[:3]
        return ".".join(str(part) for part in parts), ""
    return "", f"{path} names no version"


def _version_from_distribution_metadata(directory: Path, distribution: str) -> tuple[str, str]:
    """Return ``(version, problem)`` from the ``*.dist-info`` in ``directory``.

    A copy outside an installed environment has no ``*.dist-info``, and that is
    not a problem. A folder that cannot be listed is a problem, because the
    metadata can be in it.
    """
    prefix = f"{distribution.replace('-', '_')}-"
    try:
        names = os.listdir(directory)
    except (FileNotFoundError, NotADirectoryError):
        return "", ""
    except OSError as exc:
        return "", f"cannot list {directory} for {distribution} metadata ({type(exc).__name__}: {exc})"
    found = sorted(
        directory / name for name in names if name.startswith(prefix) and name.endswith(".dist-info")
    )
    if not found:
        return "", ""
    if len(found) > 1:
        names = ", ".join(path.name for path in found)
        return "", f"{directory} has more than one {distribution} metadata folder ({names})"
    path = found[0] / "METADATA"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return "", f"cannot read {path} ({type(exc).__name__}: {exc})"
    match = _METADATA_VERSION.search(text)
    if not match:
        return "", f"{path} names no Version"
    return match.group(1), ""


def package_version(package_dir: Path, distribution: str, declared_version: str = "") -> str:
    """Return the full version of the ``distribution`` package in ``package_dir``.

    ``__version__`` can be shorter than the version of the copy: ovrtx
    0.5.1.385782 sets it to "0.5.1". The generated ``_version.py`` of the
    package comes first, then the metadata installed next to the package, and
    ``declared_version`` (the ``__version__`` of the package) last.
    ``package_dir`` is not resolved through links, so a copy selected by a root
    gives its own version, not the version of the copy it links to. A file that
    exists but cannot be read is reported, with the source used instead.
    """
    problems: list[str] = []
    readers = (
        ("_version.py", lambda: _version_from_version_file(package_dir)),
        ("metadata", lambda: _version_from_distribution_metadata(package_dir.parent, distribution)),
    )
    for source, read in readers:
        version, problem = read()
        if problem:
            problems.append(problem)
        if version:
            if problems:
                _LOGGER.warning(
                    "Reading the %s version: %s. The %s version %s comes from its %s.",
                    distribution, "; ".join(problems), distribution, version, source,
                )
            return version
    if problems:
        _LOGGER.warning(
            "Reading the %s version: %s. The %s version %r comes from __version__.",
            distribution, "; ".join(problems), distribution, declared_version,
        )
    return declared_version


def loaded_module_version(module: Any, distribution: str) -> str:
    """Return the full version of a loaded ovrtx or ovstage package."""
    if module is None:
        return ""
    declared = str(getattr(module, "__version__", "") or "")
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return declared
    return package_version(Path(os.path.abspath(module_file)).parent, distribution, declared)


def loaded_ovrtx_version() -> str:
    """Return the version of the ovrtx that is loaded, or "" when none is.

    This does not import ovrtx. It names the copy that ``import_ovrtx`` took,
    not a copy that it tried and rejected.
    """
    result = _OVRTX_IMPORT_RESULT
    return loaded_module_version(result.module if result is not None else None, "ovrtx")


def ovrtx_root_version() -> str:
    """Return the version of the ``OVRTX_ROOT`` ovrtx without importing it.

    When ``import_ovrtx`` has loaded a copy from the root, this is the version
    of that copy. Otherwise it is the version of the first copy under the root.
    """
    candidates = _ovrtx_python_path_candidates(os.environ.get(OVRTX_ROOT_ENV, ""))
    result = _OVRTX_IMPORT_RESULT
    if result is not None and result.module is not None:
        if result.source in {str(candidate) for candidate in candidates}:
            return loaded_ovrtx_version()
    for candidate in candidates:
        package_dir = candidate / "ovrtx"
        try:
            text = (package_dir / "__init__.py").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            _LOGGER.warning(
                "Reading the ovrtx version: cannot read %s (%s: %s). The next copy under %s is used.",
                package_dir / "__init__.py", type(exc).__name__, exc, OVRTX_ROOT_ENV,
            )
            continue
        match = _VERSION_ASSIGNMENT.search(text)
        version = package_version(package_dir, "ovrtx", match.group(1) if match else "")
        if version:
            return version
    return ""


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


def _clear_ovrtx_modules() -> None:
    """Drop ovrtx and every ovrtx.* submodule from the import cache.

    A new top-level ovrtx must not keep children loaded from another copy.
    """
    for loaded_name in list(sys.modules):
        if loaded_name == "ovrtx" or loaded_name.startswith("ovrtx."):
            sys.modules.pop(loaded_name, None)


def _imported_through(candidate: Path, module: Any) -> bool:
    """Return whether ``module`` was imported through ``candidate``.

    The found file path is compared without following symbolic links, so a
    package that ``candidate`` supplies through a link still counts as its own.
    A module without a file path cannot be placed, so it is accepted.
    """
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return True
    found = Path(os.path.abspath(module_file))
    root = Path(os.path.abspath(str(candidate)))
    return root == found or root in found.parents


def _import_ovrtx_from_path(candidate: Path) -> Any:
    """Import ovrtx with ``candidate`` leading ``sys.path``.

    ``candidate`` goes to the front even when it is already on the path later,
    so a copy earlier on the path does not win. The path order is restored.
    """
    candidate_str = str(candidate)
    original = list(sys.path)
    sys.path[:] = [candidate_str] + [p for p in original if p != candidate_str]
    try:
        return importlib.import_module("ovrtx")
    finally:
        sys.path[:] = original


def _compose_ovrtx_import_error(
    normal_error: BaseException | None,
    raw_root: str,
    root_errors: list[str],
) -> ImportError:
    if raw_root:
        detail = "; ".join(root_errors) if root_errors else "no import attempts were made"
        return ImportError(f"Could not import ovrtx from {OVRTX_ROOT_ENV}={raw_root!r}: {detail}")
    return ImportError(
        "Could not import ovrtx from the active environment "
        f"({type(normal_error).__name__}: {normal_error}). {OVRTX_ROOT_ENV} is not set."
    )


def import_ovrtx() -> OvRtxImportResult:
    """Resolve ovrtx from ``OVRTX_ROOT`` when it is set, else the active env."""
    global _OVRTX_IMPORT_RESULT
    if _OVRTX_IMPORT_RESULT is not None:
        return _OVRTX_IMPORT_RESULT

    raw_root = os.environ.get(OVRTX_ROOT_ENV, "").strip()
    normal_error: BaseException | None = None
    if not raw_root:
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

    # A set OVRTX_ROOT selects ovrtx, with no fallback to the active environment.
    root_errors: list[str] = []
    if raw_root:
        _clear_ovrtx_modules()
        _configure_ovrtx_runtime_environment(raw_root)
        candidates = _ovrtx_python_path_candidates(raw_root)
        if not candidates:
            root_errors.append(
                f"no importable ovrtx package found under {OVRTX_ROOT_ENV}"
            )
        for candidate in candidates:
            _clear_ovrtx_modules()
            handles = _add_windows_ovrtx_dll_directories(raw_root)
            try:
                module = _import_ovrtx_from_path(candidate)
                if not _imported_through(candidate, module):
                    raise ImportError(
                        f"ovrtx was imported from {getattr(module, '__file__', None)}"
                    )
            except (ImportError, RuntimeError, OSError) as path_exc:
                _clear_ovrtx_modules()
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

    _clear_ovrtx_modules()
    _OVRTX_IMPORT_RESULT = OvRtxImportResult(
        module=None,
        error=_compose_ovrtx_import_error(normal_error, raw_root, root_errors),
        source="",
    )
    return _OVRTX_IMPORT_RESULT

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OVSTAGE_ROOT import resolver for ovstage runtime modules."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import platform
import sys
from types import ModuleType
from typing import Any, Callable


OVSTAGE_ROOT_ENV = "OVSTAGE_ROOT"
OVSTAGE_BUILD_DIR_ENV = "OVSTAGE_BUILD_DIR"

OVSTAGE_LIBRARY_PATH_ENV = "OVSTAGE_LIBRARY_PATH"
OVPOPULATION_LIBRARY_PATH_ENV = "OVPOPULATION_LIBRARY_PATH"
OVHIERARCHY_LIBRARY_PATH_ENV = "OVHIERARCHY_LIBRARY_PATH"
OVSTAGE_LIBRARY_PATH_HINT_ENV = "OVSTAGE_LIBRARY_PATH_HINT"

_RUNTIME_MODULE_NAMES = ("ovstage", "ovhierarchy", "ovpopulation", "ovphysx")
_RUNTIME_LIBRARY_ENVS = (
    OVSTAGE_LIBRARY_PATH_ENV,
    OVPOPULATION_LIBRARY_PATH_ENV,
    OVHIERARCHY_LIBRARY_PATH_ENV,
)
_OVSTAGE_DLL_HANDLES: list[Any] = []
# One open Windows DLL-directory registration per directory, keyed by the
# directory, so repeated resolution does not add a second one.
_OVSTAGE_DLL_DIRECTORIES: dict[str, Any] = {}
# The module each runtime name was last resolved to from a root, with the root
# value it came from. Repeated resolution of the same root reuses it.
_OVSTAGE_ROOT_MODULES: dict[str, tuple[str, ModuleType, str]] = {}

ImportModuleFn = Callable[..., ModuleType]


@dataclass(frozen=True)
class OvstageRuntimeImportResult:
    """Outcome of resolving one ovstage runtime module."""

    module: ModuleType | None
    error: BaseException | None
    source: str = ""

    @property
    def available(self) -> bool:
        return self.module is not None


def ovstage_python_path_candidates(raw_root: str) -> tuple[Path, ...]:
    """Return import roots to try for an external ovstage checkout/install."""
    raw_root = str(raw_root or "").strip()
    if not raw_root:
        return ()
    root = Path(raw_root).expanduser()
    candidates: list[Path] = []
    for module_name in _RUNTIME_MODULE_NAMES:
        candidates.append(root / "src" / module_name / "python")
    candidates.extend((root / "public" / "python", root / "python", root))

    import_roots: list[Path] = []
    for candidate in candidates:
        if candidate in import_roots:
            continue
        if any(_contains_module(candidate, module_name) for module_name in _RUNTIME_MODULE_NAMES):
            import_roots.append(candidate)
    return tuple(import_roots)


def ovstage_runtime_dirs(raw_root: str) -> tuple[Path, ...]:
    """Return likely native-library directories for an ovstage root."""
    raw_root = str(raw_root or "").strip()
    if not raw_root:
        return ()
    root = Path(raw_root).expanduser()
    candidates: list[Path] = []
    raw_build_dir = os.environ.get(OVSTAGE_BUILD_DIR_ENV, "").strip()
    if raw_build_dir:
        candidates.append(Path(raw_build_dir).expanduser())
    platform_dir = _platform_build_dir_name()
    for config_name in ("release", "debug", "relwithdebinfo"):
        candidates.append(root / "_build" / platform_dir / config_name)
    build_root = root / "_build"
    if build_root.is_dir():
        for config_name in ("release", "debug", "relwithdebinfo"):
            candidates.extend(sorted(build_root.glob(f"*/{config_name}")))
    parent_build_root = root.parent / "_build"
    for config_name in ("release", "debug", "relwithdebinfo"):
        candidates.append(parent_build_root / platform_dir / config_name)
    if parent_build_root.is_dir():
        for config_name in ("release", "debug", "relwithdebinfo"):
            candidates.extend(sorted(parent_build_root.glob(f"*/{config_name}")))
    candidates.extend((root / "build", root / "lib", root))

    dirs: list[Path] = []
    for candidate in candidates:
        if candidate.is_dir() and candidate not in dirs:
            dirs.append(candidate)
            for plugin_dir in (candidate / "plugins", candidate / "plugins" / "rtx"):
                if plugin_dir.is_dir() and plugin_dir not in dirs:
                    dirs.append(plugin_dir)
    return tuple(dirs)


def configure_ovstage_root_environment(raw_root: str) -> tuple[Path, ...]:
    """Apply native-library env vars derived from ``OVSTAGE_ROOT``."""
    runtime_dirs = ovstage_runtime_dirs(raw_root)
    if not runtime_dirs:
        return ()
    primary_dir = str(runtime_dirs[0])
    for env_name in _RUNTIME_LIBRARY_ENVS:
        os.environ[env_name] = primary_dir
    os.environ[OVSTAGE_LIBRARY_PATH_HINT_ENV] = primary_dir
    _prepend_env_paths("PATH", runtime_dirs)
    if not sys.platform.startswith("win"):
        _prepend_env_paths("LD_LIBRARY_PATH", runtime_dirs)
    return runtime_dirs


def resolve_ovstage_runtime_module(
    module_name: str,
    *,
    import_module_fn: ImportModuleFn | None = None,
) -> OvstageRuntimeImportResult:
    """Resolve an ovstage runtime module from OVSTAGE_ROOT when set, else the active env."""
    if module_name not in _RUNTIME_MODULE_NAMES:
        return OvstageRuntimeImportResult(
            module=None,
            error=ImportError(
                f"unsupported OVStage runtime module: {module_name!r}"
            ),
        )
    importer = import_module_fn or importlib.import_module
    raw_root = os.environ.get(OVSTAGE_ROOT_ENV, "").strip()
    active_error: BaseException | None = None
    # A set OVSTAGE_ROOT selects ovstage and its parts, with no fallback to the
    # active environment. ovphysx is a separate product: the active
    # environment still comes first for it.
    if not raw_root or module_name == "ovphysx":
        try:
            module = importer(module_name)
        except (ImportError, RuntimeError, OSError) as exc:
            active_error = exc
        else:
            return OvstageRuntimeImportResult(
                module=module,
                error=None,
                source="active environment",
            )

    root_errors: list[str] = []
    if raw_root:
        selected = _selected_root_module(module_name, raw_root)
        if selected is not None:
            module, source = selected
            return OvstageRuntimeImportResult(
                module=module,
                error=None,
                source=source,
            )
        _clear_module(module_name)
        runtime_dirs = configure_ovstage_root_environment(raw_root)
        candidates = ovstage_python_path_candidates(raw_root)
        if not candidates:
            root_errors.append(
                f"no importable ovstage runtime package found under {OVSTAGE_ROOT_ENV}"
            )
        handles = _add_windows_dll_directories(runtime_dirs)
        try:
            module = _import_from_paths(module_name, candidates, importer)
            source = _source_for_module(module, candidates)
            if getattr(module, "__file__", None) and source == module.__file__:
                raise ImportError(
                    f"{module_name} was imported from {source}, which is outside "
                    f"{OVSTAGE_ROOT_ENV}"
                )
        except (ImportError, RuntimeError, OSError) as root_exc:
            _clear_module(module_name)
            _close_dll_handles(handles)
            root_errors.append(f"{type(root_exc).__name__}: {root_exc}")
        else:
            _OVSTAGE_DLL_HANDLES.extend(handles)
            _OVSTAGE_ROOT_MODULES[module_name] = (raw_root, module, source)
            return OvstageRuntimeImportResult(
                module=module,
                error=None,
                source=source,
            )

    _OVSTAGE_ROOT_MODULES.pop(module_name, None)
    _clear_module(module_name)
    return OvstageRuntimeImportResult(
        module=None,
        error=_compose_import_error(module_name, active_error, raw_root, root_errors),
        source="",
    )


def _selected_root_module(module_name: str, raw_root: str) -> tuple[ModuleType, str] | None:
    """Return the module already selected for this root, if it is still loaded.

    A root is resolved once per process. Resolving it again would import the
    package a second time and register its directories again, and on Windows
    each registration is kept for the life of the process.
    """
    selected = _OVSTAGE_ROOT_MODULES.get(module_name)
    if selected is None:
        return None
    selected_root, module, source = selected
    if selected_root != raw_root or sys.modules.get(module_name) is not module:
        return None
    return module, source


def reset_ovstage_import_cache() -> None:
    """Forget the resolved modules and close the directory registrations."""
    _OVSTAGE_ROOT_MODULES.clear()
    _close_dll_handles(list(_OVSTAGE_DLL_HANDLES))
    _OVSTAGE_DLL_HANDLES.clear()


def import_ovstage_runtime_module(
    module_name: str,
    *,
    import_module_fn: ImportModuleFn | None = None,
) -> ModuleType:
    """Import an ovstage runtime module or raise the resolver error."""
    result = resolve_ovstage_runtime_module(
        module_name,
        import_module_fn=import_module_fn,
    )
    if result.module is not None:
        return result.module
    raise result.error or ImportError(f"{module_name} is not available")


def _contains_module(candidate: Path, module_name: str) -> bool:
    return (candidate / module_name).is_dir() or (candidate / f"{module_name}.py").is_file()


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


def _add_windows_dll_directories(runtime_dirs: tuple[Path, ...]) -> list[Any]:
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if os.name != "nt" or not callable(add_dll_directory):
        return []
    handles: list[Any] = []
    for runtime_dir in runtime_dirs:
        # Windows keeps one registration per call. Add each directory once, so
        # resolving the same root again does not add another registration.
        key = os.path.normcase(os.path.abspath(str(runtime_dir)))
        if key in _OVSTAGE_DLL_DIRECTORIES:
            continue
        try:
            handle = add_dll_directory(str(runtime_dir))
        except OSError:
            continue
        _OVSTAGE_DLL_DIRECTORIES[key] = handle
        handles.append(handle)
    return handles


def _close_dll_handles(handles: list[Any]) -> None:
    for handle in handles:
        for key, registered in list(_OVSTAGE_DLL_DIRECTORIES.items()):
            if registered is handle:
                del _OVSTAGE_DLL_DIRECTORIES[key]
        close = getattr(handle, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _prepend_env_paths(env_name: str, paths: tuple[Path, ...]) -> None:
    current = [part for part in os.environ.get(env_name, "").split(os.pathsep) if part]
    prepended: list[str] = []
    for path in paths:
        path_str = str(path)
        if path_str not in prepended and path_str not in current:
            prepended.append(path_str)
    if prepended:
        os.environ[env_name] = os.pathsep.join([*prepended, *current])


def _clear_module(module_name: str) -> None:
    for loaded_name in list(sys.modules):
        if loaded_name == module_name or loaded_name.startswith(module_name + "."):
            sys.modules.pop(loaded_name, None)


def _import_from_paths(
    module_name: str,
    candidates: tuple[Path, ...],
    importer: ImportModuleFn,
) -> ModuleType:
    if not candidates:
        raise ImportError("no OVSTAGE_ROOT Python path candidates")
    # Lead sys.path with the candidates, even ones already on the path later,
    # so a copy earlier on the path does not win. The path order is restored.
    candidate_strs = [str(candidate) for candidate in candidates]
    original = list(sys.path)
    sys.path[:] = candidate_strs + [p for p in original if p not in candidate_strs]
    try:
        return importer(module_name)
    finally:
        sys.path[:] = original


def _source_for_module(module: ModuleType, candidates: tuple[Path, ...]) -> str:
    module_file = getattr(module, "__file__", None)
    if module_file:
        # Compare without following symbolic links, so a module that a
        # candidate supplies through a link still counts as that candidate's.
        found = Path(os.path.abspath(module_file))
        for candidate in candidates:
            root = Path(os.path.abspath(str(candidate)))
            if root == found or root in found.parents:
                return str(candidate)
        return str(module_file)
    return OVSTAGE_ROOT_ENV


def _compose_import_error(
    module_name: str,
    active_error: BaseException | None,
    raw_root: str,
    root_errors: list[str],
) -> ImportError:
    message = f"Could not import {module_name}"
    if active_error is not None:
        message = (
            f"{message} from the active environment "
            f"({type(active_error).__name__}: {active_error})."
        )
    if raw_root:
        detail = "; ".join(root_errors) if root_errors else "no import attempts were made"
        prefix = f"{message} Also failed:" if active_error is not None else f"{message}:"
        message = f"{prefix} {OVSTAGE_ROOT_ENV}={raw_root!r}: {detail}"
    else:
        message = f"{message} {OVSTAGE_ROOT_ENV} is not set."
    return ImportError(message)

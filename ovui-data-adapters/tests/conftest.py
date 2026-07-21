# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Shared pytest fixtures and runtime markers for data-adapter tests."""

from __future__ import annotations

import importlib.util
import os
import pathlib
import shutil
import sys

import pytest


TESTS_ROOT = pathlib.Path(__file__).resolve().parent
DATA_DIR = TESTS_ROOT / "data"
MONOREPO_ROOT = TESTS_ROOT.parents[1]
DATA_ADAPTERS_ROOT = MONOREPO_ROOT / "ovui-data-adapters"

if str(DATA_ADAPTERS_ROOT) not in sys.path:
    sys.path.insert(0, str(DATA_ADAPTERS_ROOT))


def _prepend_to_pythonpath(path: pathlib.Path) -> None:
    path_text = str(path)
    existing = os.environ.get("PYTHONPATH", "")
    existing_entries = [entry for entry in existing.split(os.pathsep) if entry]
    if path_text in existing_entries:
        return
    os.environ["PYTHONPATH"] = os.pathsep.join([path_text, *existing_entries])


def _prefer_runtime_usd_python_path() -> None:
    candidates: list[pathlib.Path] = []
    usd_root = os.environ.get("USD_ROOT", "").strip()
    if usd_root:
        candidates.append(pathlib.Path(usd_root).expanduser() / "lib" / "python")
    for entry in sys.path:
        if not entry:
            continue
        path = pathlib.Path(entry).expanduser()
        if path.name == "python" and path.parent.name == "lib":
            candidates.append(path)
    candidates.append(
        MONOREPO_ROOT.parent / "usd-build" / "install" / "lib" / "python"
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if not (resolved / "pxr").is_dir():
            continue
        resolved_text = str(resolved)
        sys.path[:] = [
            entry
            for entry in sys.path
            if str(pathlib.Path(entry).resolve()) != resolved_text
        ]
        sys.path.insert(0, resolved_text)
        _prepend_to_pythonpath(resolved)
        return


_prefer_runtime_usd_python_path()


RUNTIME_MARKER_MODULES: dict[str, tuple[str, ...]] = {
    # Kit ships population and hierarchy as part of the ovstage Python module.
    # Requiring the retired standalone modules would skip valid Kit runtimes.
    "requires_ovstage": ("ovstage",),
    "requires_ovphysx": ("ovphysx",),
    "requires_ovrtx": ("ovrtx",),
}


def _runtime_module_is_discoverable(module_name: str) -> bool:
    """Return whether ``module_name`` resolves to an importable module.

    Pytest adds test directories to ``sys.path`` while collecting.  The
    ``tests/ovstage`` directory can therefore resolve as a PEP 420 namespace
    package even though the native Kit ``ovstage`` module is absent.  A bare
    namespace cannot provide the top-level runtime API required by these
    markers, so do not treat it as runtime availability.
    """

    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return False
    return not (
        getattr(spec, "loader", object()) is None
        and getattr(spec, "origin", object()) is None
    )


def missing_runtime_modules(marker_name: str) -> tuple[str, ...]:
    """Return modules that are unavailable for a known runtime marker."""
    try:
        modules = RUNTIME_MARKER_MODULES[marker_name]
    except KeyError as exc:
        raise ValueError(f"unknown runtime marker: {marker_name}") from exc
    return tuple(name for name in modules if not _runtime_module_is_discoverable(name))


def runtime_skip_reason(marker_name: str) -> str | None:
    """Return the collection-time skip reason for ``marker_name``, if any."""
    missing = missing_runtime_modules(marker_name)
    if not missing:
        return None
    joined = ", ".join(missing)
    return f"{marker_name}: missing runtime module(s): {joined}"


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_ovstage: test needs the Kit-integrated ovstage runtime module",
    )
    config.addinivalue_line(
        "markers",
        "requires_ovphysx: test needs the ovphysx runtime module",
    )
    config.addinivalue_line(
        "markers",
        "requires_ovrtx: test needs the ovrtx runtime module",
    )


def pytest_collection_modifyitems(config, items) -> None:
    skip_reasons = {
        marker_name: runtime_skip_reason(marker_name)
        for marker_name in RUNTIME_MARKER_MODULES
    }
    for item in items:
        for marker_name, reason in skip_reasons.items():
            if reason is not None and marker_name in item.keywords:
                item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def ovstage_test_data_dir() -> pathlib.Path:
    return DATA_DIR


@pytest.fixture()
def ovstage_static_scene_path(
    ovstage_test_data_dir: pathlib.Path,
    tmp_path: pathlib.Path,
) -> pathlib.Path:
    """Return a per-test copy so no scene state leaks between tests.

    The native OVStage provider opens the scene file directly, and other
    provider tests may author real USD; sharing one source path would let
    per-test document state leak between otherwise independent tests, so each
    test gets its own copy.
    """

    source = ovstage_test_data_dir / "ovstage_static_scene.usda"
    assert source.is_file(), f"missing static fixture: {source}"
    path = tmp_path / source.name
    shutil.copy2(source, path)
    return path


@pytest.fixture(scope="session")
def ovstage_physics_scene_path(ovstage_test_data_dir: pathlib.Path) -> pathlib.Path:
    path = ovstage_test_data_dir / "ovstage_physics_scene.usda"
    assert path.is_file(), f"missing physics fixture: {path}"
    return path

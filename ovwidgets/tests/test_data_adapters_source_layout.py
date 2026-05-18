# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Source-layout invariants for the dash-form data-adapters folder.

Victor's requirement:

    "I still can see the folder name ovui_data_adapters. Please new pr
     where you rename it to ovui-data-adapters."

Python identifiers cannot contain dashes, so the import package name
must remain ``ovui_data_adapters``; only the *visible* repository
folder is renamed to dash-form. After the repo merge, both adapter
sub-packages share a single unified Python import-package root, with
pyproject stubs sitting under ``dist/<sub>/`` two levels up — same
``dist/<sub>/pyproject.toml`` + ``where = ["../.."]`` pattern as
``ovwidgets/dist/``.

Layout under ``<monorepo-root>/ovui-data-adapters/``::

    ovui-data-adapters/
        dist/
            common/pyproject.toml          (project for ovui-data-adapters-common)
            openusd/pyproject.toml         (project for ovui-data-adapters-openusd)
        ovui_data_adapters/                (unified import-package root)
            common/
                __init__.py
                ...
            openusd/
                __init__.py
                ...

This layout supports editable installs and in-tree wheel builds. It
deliberately does NOT support sdist publishing from the ``dist/<sub>/``
stubs — see ``test_data_adapters_install.py`` and the docstring in each
``dist/<sub>/pyproject.toml``.

Each test below pins one slice of this contract. Together they prevent
a regression that re-introduces a top-level ``ovui_data_adapters/``
folder, splits the import-package root back into per-distribution
copies, or re-introduces the legacy ``data-adapters-{common,openusd}/``
co-located project layout.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import pathlib
import subprocess
import sys

MONOREPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DASH_PARENT = MONOREPO_ROOT / "ovui-data-adapters"
COMMON_PROJECT = DASH_PARENT / "dist" / "common"
OPENUSD_PROJECT = DASH_PARENT / "dist" / "openusd"
COMMON_PACKAGE_DIR = DASH_PARENT / "ovui_data_adapters" / "common"
OPENUSD_PACKAGE_DIR = DASH_PARENT / "ovui_data_adapters" / "openusd"


def _git_ls_files(path: str) -> list[str]:
    """Return ``git ls-files <path>`` output as a list (one entry per line)."""
    proc = subprocess.run(
        ["git", "-C", str(MONOREPO_ROOT), "ls-files", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in proc.stdout.splitlines() if line]


def test_dash_parent_directory_exists():
    assert DASH_PARENT.is_dir(), (
        f"missing dash-form source folder: {DASH_PARENT}"
    )


def test_two_dist_pyprojects_and_unified_source_exist():
    """Each distribution must have its own ``pyproject.toml`` under
    ``dist/<sub>/``, AND both sub-packages must live under the unified
    ``ovui_data_adapters/`` import-package root.
    """
    assert (COMMON_PROJECT / "pyproject.toml").is_file(), (
        f"missing pyproject for common: {COMMON_PROJECT / 'pyproject.toml'}"
    )
    assert (OPENUSD_PROJECT / "pyproject.toml").is_file(), (
        f"missing pyproject for openusd: {OPENUSD_PROJECT / 'pyproject.toml'}"
    )
    assert COMMON_PACKAGE_DIR.is_dir() and (COMMON_PACKAGE_DIR / "__init__.py").is_file()
    assert OPENUSD_PACKAGE_DIR.is_dir() and (OPENUSD_PACKAGE_DIR / "__init__.py").is_file()


def test_no_tracked_top_level_underscore_source_folder():
    """Regression guard: ``<monorepo-root>/ovui_data_adapters/`` must
    contain no *tracked* files. Generated cache residue
    (``__pycache__``, ``*.pyc``) on a developer's working tree is
    irrelevant — only ``git ls-files`` matters for what the repository
    ships.
    """
    tracked = _git_ls_files("ovui_data_adapters")
    assert not tracked, (
        "legacy underscore source folder must contain no tracked files. "
        f"git ls-files reported {len(tracked)} entries:\n  "
        + "\n  ".join(tracked[:10])
        + ("\n  …" if len(tracked) > 10 else "")
    )


def test_no_tracked_files_under_legacy_co_located_project_paths():
    """The pre-merge layout split the import-package root across two
    co-located project directories
    (``ovui-data-adapters/data-adapters-{common,openusd}/``). The
    monorepo merge collapses that into a single unified
    ``ovui-data-adapters/ovui_data_adapters/`` root with the
    pyproject stubs moved under ``ovui-data-adapters/dist/<sub>/``.
    Anything still tracked under the old co-located paths would
    shadow the new layout.
    """
    for legacy in (
        "ovui-data-adapters/data-adapters-common",
        "ovui-data-adapters/data-adapters-openusd",
    ):
        tracked = _git_ls_files(legacy)
        assert not tracked, (
            f"legacy co-located project still has tracked files: {legacy}\n  "
            + "\n  ".join(tracked)
        )


def test_underscore_imports_still_resolve():
    """The folder restructure must not break Python import paths.
    ``ovui_data_adapters`` is a PEP 420 namespace package; both
    sub-packages now resolve under the unified import-package root.
    """
    top = importlib.util.find_spec("ovui_data_adapters")
    assert top is not None, "namespace package ovui_data_adapters not findable"

    common = importlib.import_module("ovui_data_adapters.common")
    assert common.__name__ == "ovui_data_adapters.common"
    common_file = pathlib.Path(common.__file__).resolve()
    assert common_file.is_relative_to(COMMON_PACKAGE_DIR), (
        f"common package resolved outside its unified import-package root: "
        f"{common_file} not under {COMMON_PACKAGE_DIR}"
    )


def test_dist_pyproject_where_points_two_levels_up():
    """Both data-adapter pyprojects must source-find from ``../..`` —
    i.e. the unified import-package root sits two levels above each
    ``dist/<sub>/pyproject.toml``. This pattern supports editable
    installs and in-tree wheel builds; sdist is intentionally not
    supported (setuptools cannot include source above the project
    root in a self-contained release tarball).
    """
    try:
        import tomllib  # Python ≥ 3.11
    except ImportError:  # pragma: no cover — older interpreters
        import tomli as tomllib  # type: ignore[no-redef]

    for project_dir, expected_include_prefix in (
        (COMMON_PROJECT, "ovui_data_adapters.common"),
        (OPENUSD_PROJECT, "ovui_data_adapters.openusd"),
    ):
        path = project_dir / "pyproject.toml"
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        find = data["tool"]["setuptools"]["packages"]["find"]
        assert find["where"] == ["../.."], (
            f"{path}: expected where=['../..'] (unified-source layout), "
            f"got {find['where']!r}"
        )
        for pattern in find["include"]:
            assert pattern.startswith(expected_include_prefix), (
                f"{path}: include pattern {pattern!r} must start with "
                f"{expected_include_prefix!r}"
            )


def test_subprocess_inherits_pythonpath_for_data_adapters():
    """Codex Finding 1 regression guard: the conftest must mirror the
    data-adapters source root onto ``PYTHONPATH`` so that subprocess
    tests resolve ``ovui_data_adapters`` the same way the parent does.

    Spawn a clean child Python with the inherited environment and
    confirm a representative import succeeds. A failure here means the
    conftest's ``PYTHONPATH`` mirror is broken or absent.
    """
    proc = subprocess.run(
        [sys.executable, "-c", "from ovui_data_adapters.common import StageAdapter; print(StageAdapter.__name__)"],
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        "child Python failed to import ovui_data_adapters.common.\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert "StageAdapter" in proc.stdout

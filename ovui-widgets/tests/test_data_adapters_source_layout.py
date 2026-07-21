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

Naming requirement: the *visible* repository folder must use the
dash-form name ``ovui-data-adapters``, not ``ovui_data_adapters``.

Python identifiers cannot contain dashes, so the import package name
must remain ``ovui_data_adapters``; only the *visible* repository
folder is renamed to dash-form. After the repo merge, adapter
sub-packages share a single unified Python import-package root, with
pyproject stubs sitting under ``dist/<sub>/`` two levels up — same
``dist/<sub>/pyproject.toml`` + ``where = ["../.."]`` pattern as
``ovui-widgets/dist/``.

Layout under ``<monorepo-root>/ovui-data-adapters/``::

    ovui-data-adapters/
        dist/
            common/pyproject.toml          (project for ovui-data-adapters-common)
            services/pyproject.toml        (project for ovui-data-adapters-services)
            openusd/pyproject.toml         (project for ovui-data-adapters-openusd)
            ovstage/pyproject.toml         (project for ovui-data-adapters-ovstage)
        ovui_data_adapters/                (unified import-package root)
            common/
                __init__.py
                ...
            services/
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
OVUI_WIDGETS_PARENT = MONOREPO_ROOT / "ovui-widgets"
DASH_PARENT = MONOREPO_ROOT / "ovui-data-adapters"
COMMON_PROJECT = DASH_PARENT / "dist" / "common"
SERVICES_PROJECT = DASH_PARENT / "dist" / "services"
OPENUSD_PROJECT = DASH_PARENT / "dist" / "openusd"
OVSTAGE_PROJECT = DASH_PARENT / "dist" / "ovstage"
OVUI_WIDGETS_APP_PROJECT = OVUI_WIDGETS_PARENT / "dist" / "app"
OVUI_WIDGETS_ALL_PROJECT = OVUI_WIDGETS_PARENT / "dist" / "all"
COMMON_PACKAGE_DIR = DASH_PARENT / "ovui_data_adapters" / "common"
SERVICES_PACKAGE_DIR = DASH_PARENT / "ovui_data_adapters" / "services"
SERVICES_SETTINGS_FILE = SERVICES_PACKAGE_DIR / "settings.py"
SERVICES_UNDO_FILE = SERVICES_PACKAGE_DIR / "undo.py"
SERVICES_SELECTION_FILE = SERVICES_PACKAGE_DIR / "selection.py"
SERVICES_TRANSFORMS_FILE = SERVICES_PACKAGE_DIR / "transforms.py"
SERVICES_TESTING_PACKAGE_DIR = SERVICES_PACKAGE_DIR / "testing"
SERVICES_LAYERS_PACKAGE_DIR = SERVICES_PACKAGE_DIR / "layers"
SERVICES_LAYER_COMMANDS_PACKAGE_DIR = SERVICES_LAYERS_PACKAGE_DIR / "commands"
SERVICES_CONTENT_PACKAGE_DIR = SERVICES_PACKAGE_DIR / "content"
SERVICES_ASSET_TYPES_FILE = SERVICES_CONTENT_PACKAGE_DIR / "asset_types.py"
SERVICES_CONTENT_CLIPBOARD_FILE = SERVICES_CONTENT_PACKAGE_DIR / "clipboard.py"
SERVICES_CONTENT_FILE_OPERATIONS_FILE = (
    SERVICES_CONTENT_PACKAGE_DIR / "file_operations.py"
)
SERVICES_CONTENT_NAVIGATION_FILE = SERVICES_CONTENT_PACKAGE_DIR / "navigation.py"
SERVICES_BACKENDS_PACKAGE_DIR = SERVICES_CONTENT_PACKAGE_DIR / "backends"
OPENUSD_PACKAGE_DIR = DASH_PARENT / "ovui_data_adapters" / "openusd"
OVSTAGE_PACKAGE_DIR = DASH_PARENT / "ovui_data_adapters" / "ovstage"


def _load_pyproject(path: pathlib.Path) -> dict:
    try:
        import tomllib  # Python >= 3.11
    except ImportError:  # pragma: no cover - older interpreters
        import tomli as tomllib  # type: ignore[no-redef]

    with path.open("rb") as fh:
        return tomllib.load(fh)


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


def test_dist_pyprojects_and_unified_source_exist():
    """Each distribution must have its own ``pyproject.toml`` under
    ``dist/<sub>/``, AND all sub-packages must live under the unified
    ``ovui_data_adapters/`` import-package root.
    """
    assert (COMMON_PROJECT / "pyproject.toml").is_file(), (
        f"missing pyproject for common: {COMMON_PROJECT / 'pyproject.toml'}"
    )
    assert (SERVICES_PROJECT / "pyproject.toml").is_file(), (
        f"missing pyproject for services: {SERVICES_PROJECT / 'pyproject.toml'}"
    )
    assert (OPENUSD_PROJECT / "pyproject.toml").is_file(), (
        f"missing pyproject for openusd: {OPENUSD_PROJECT / 'pyproject.toml'}"
    )
    assert (OVSTAGE_PROJECT / "pyproject.toml").is_file(), (
        f"missing pyproject for ovstage: {OVSTAGE_PROJECT / 'pyproject.toml'}"
    )
    assert COMMON_PACKAGE_DIR.is_dir() and (COMMON_PACKAGE_DIR / "__init__.py").is_file()
    assert SERVICES_PACKAGE_DIR.is_dir() and (SERVICES_PACKAGE_DIR / "__init__.py").is_file()
    assert SERVICES_SETTINGS_FILE.is_file()
    assert SERVICES_UNDO_FILE.is_file()
    assert SERVICES_SELECTION_FILE.is_file()
    assert SERVICES_TRANSFORMS_FILE.is_file()
    assert SERVICES_TESTING_PACKAGE_DIR.is_dir() and (
        SERVICES_TESTING_PACKAGE_DIR / "__init__.py"
    ).is_file()
    for filename in (
        "mock_backend.py",
        "mock_layer_stack.py",
        "mock_property.py",
        "mock_renderer.py",
        "mock_stage.py",
        "mock_transform.py",
    ):
        assert (SERVICES_TESTING_PACKAGE_DIR / filename).is_file()
    assert SERVICES_LAYERS_PACKAGE_DIR.is_dir() and (
        SERVICES_LAYERS_PACKAGE_DIR / "__init__.py"
    ).is_file()
    assert SERVICES_LAYER_COMMANDS_PACKAGE_DIR.is_dir() and (
        SERVICES_LAYER_COMMANDS_PACKAGE_DIR / "__init__.py"
    ).is_file()
    for filename in (
        "base.py",
        "file_io_commands.py",
        "layer_commands.py",
        "merge_flatten_commands.py",
        "sublayer_commands.py",
    ):
        assert (SERVICES_LAYER_COMMANDS_PACKAGE_DIR / filename).is_file()
    assert SERVICES_CONTENT_PACKAGE_DIR.is_dir() and (
        SERVICES_CONTENT_PACKAGE_DIR / "__init__.py"
    ).is_file()
    assert SERVICES_ASSET_TYPES_FILE.is_file()
    assert SERVICES_CONTENT_CLIPBOARD_FILE.is_file()
    assert SERVICES_CONTENT_FILE_OPERATIONS_FILE.is_file()
    assert SERVICES_CONTENT_NAVIGATION_FILE.is_file()
    assert SERVICES_BACKENDS_PACKAGE_DIR.is_dir() and (
        SERVICES_BACKENDS_PACKAGE_DIR / "__init__.py"
    ).is_file()
    assert OPENUSD_PACKAGE_DIR.is_dir() and (OPENUSD_PACKAGE_DIR / "__init__.py").is_file()
    assert OVSTAGE_PACKAGE_DIR.is_dir() and (OVSTAGE_PACKAGE_DIR / "__init__.py").is_file()


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
    ``ovui_data_adapters`` is a PEP 420 namespace package; adapter
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

    services = importlib.import_module("ovui_data_adapters.services")
    assert services.__name__ == "ovui_data_adapters.services"
    services_file = pathlib.Path(services.__file__).resolve()
    assert services_file.is_relative_to(SERVICES_PACKAGE_DIR), (
        f"services package resolved outside its unified import-package root: "
        f"{services_file} not under {SERVICES_PACKAGE_DIR}"
    )

    content_backends = importlib.import_module(
        "ovui_data_adapters.services.content.backends"
    )
    assert content_backends.LocalFSBackend().supports_url("file:///tmp")
    content_backends_file = pathlib.Path(content_backends.__file__).resolve()
    assert content_backends_file.is_relative_to(SERVICES_BACKENDS_PACKAGE_DIR), (
        "content backend service package resolved outside its unified "
        f"import-package root: {content_backends_file} not under "
        f"{SERVICES_BACKENDS_PACKAGE_DIR}"
    )

    content_asset_types = importlib.import_module(
        "ovui_data_adapters.services.content.asset_types"
    )
    assert content_asset_types.get_category("scene.usd").name == "USD"
    content_asset_types_file = pathlib.Path(content_asset_types.__file__).resolve()
    assert content_asset_types_file == SERVICES_ASSET_TYPES_FILE.resolve(), (
        "content metadata/classification service resolved outside its unified "
        f"import-package root: {content_asset_types_file} != "
        f"{SERVICES_ASSET_TYPES_FILE.resolve()}"
    )

    content_navigation = importlib.import_module(
        "ovui_data_adapters.services.content.navigation"
    )
    recent = content_navigation.RecentFileList(["/old.usd"])
    recent.add("/new.usd")
    assert recent.get_ordered() == ["/new.usd", "/old.usd"]
    content_navigation_file = pathlib.Path(content_navigation.__file__).resolve()
    assert content_navigation_file == SERVICES_CONTENT_NAVIGATION_FILE.resolve(), (
        "content navigation/persistence service resolved outside its unified "
        f"import-package root: {content_navigation_file} != "
        f"{SERVICES_CONTENT_NAVIGATION_FILE.resolve()}"
    )

    content_clipboard = importlib.import_module(
        "ovui_data_adapters.services.content.clipboard"
    )
    clip = content_clipboard.ContentClipboard()
    clip.save_to_clipboard(["/a.usd"], is_cut=True)
    assert clip.is_path_cut("/a.usd") is True
    content_clipboard_file = pathlib.Path(content_clipboard.__file__).resolve()
    assert content_clipboard_file == SERVICES_CONTENT_CLIPBOARD_FILE.resolve(), (
        "content internal clipboard service resolved outside its unified "
        f"import-package root: {content_clipboard_file} != "
        f"{SERVICES_CONTENT_CLIPBOARD_FILE.resolve()}"
    )

    content_file_operations = importlib.import_module(
        "ovui_data_adapters.services.content.file_operations"
    )
    assert (
        content_file_operations.next_copy_name("demo.usd", False, set())
        == "demo Copy.usd"
    )
    content_file_operations_file = pathlib.Path(
        content_file_operations.__file__
    ).resolve()
    assert content_file_operations_file == (
        SERVICES_CONTENT_FILE_OPERATIONS_FILE.resolve()
    ), (
        "content file-operation service resolved outside its unified "
        f"import-package root: {content_file_operations_file} != "
        f"{SERVICES_CONTENT_FILE_OPERATIONS_FILE.resolve()}"
    )

    services_settings = importlib.import_module("ovui_data_adapters.services.settings")
    assert services_settings.Settings().get("ui.theme") is None
    services_settings_file = pathlib.Path(services_settings.__file__).resolve()
    assert services_settings_file == SERVICES_SETTINGS_FILE.resolve(), (
        "generic settings/observer service resolved outside its unified "
        f"import-package root: {services_settings_file} != "
        f"{SERVICES_SETTINGS_FILE.resolve()}"
    )

    services_undo = importlib.import_module("ovui_data_adapters.services.undo")
    assert services_undo.UndoManager.null().can_undo() is False
    services_undo_file = pathlib.Path(services_undo.__file__).resolve()
    assert services_undo_file == SERVICES_UNDO_FILE.resolve(), (
        "undo service resolved outside its unified import-package root: "
        f"{services_undo_file} != {SERVICES_UNDO_FILE.resolve()}"
    )

    services_selection = importlib.import_module("ovui_data_adapters.services.selection")
    assert services_selection.SelectionBus().get_snapshot().paths() == []
    services_selection_file = pathlib.Path(services_selection.__file__).resolve()
    assert services_selection_file == SERVICES_SELECTION_FILE.resolve(), (
        "selection service resolved outside its unified import-package root: "
        f"{services_selection_file} != {SERVICES_SELECTION_FILE.resolve()}"
    )

    services_transforms = importlib.import_module("ovui_data_adapters.services.transforms")
    assert services_transforms.BatchTransformCommand.__name__ == "BatchTransformCommand"
    services_transforms_file = pathlib.Path(services_transforms.__file__).resolve()
    assert services_transforms_file == SERVICES_TRANSFORMS_FILE.resolve(), (
        "transform operation command service resolved outside its unified "
        f"import-package root: {services_transforms_file} != "
        f"{SERVICES_TRANSFORMS_FILE.resolve()}"
    )

    services_testing = importlib.import_module("ovui_data_adapters.services.testing")
    assert services_testing.MockStageAdapter().get_display_name(
        services_testing.MockStageAdapter().get_root()
    ) == "World"
    assert services_testing.MockBackend().supports_url("mock://Home") is True
    assert services_testing.MockLayerStackAdapter().get_root_layer().identifier == "@root@"
    assert services_testing.MockPropertyAdapter(paths=["/A"]).get_paths() == ["/A"]
    assert services_testing.MockTransformAdapter().can_transform("/A") is True
    assert services_testing.MockRendererAdapter.__name__ == "MockRendererAdapter"
    services_testing_file = pathlib.Path(services_testing.__file__).resolve()
    assert services_testing_file.is_relative_to(SERVICES_TESTING_PACKAGE_DIR), (
        "adapter testing fixture service resolved outside its unified "
        f"import-package root: {services_testing_file} not under "
        f"{SERVICES_TESTING_PACKAGE_DIR}"
    )

    services_layer_commands = importlib.import_module(
        "ovui_data_adapters.services.layers.commands"
    )
    assert services_layer_commands.SaveLayerCommand.non_undoable is True
    services_layer_commands_file = pathlib.Path(
        services_layer_commands.__file__
    ).resolve()
    assert services_layer_commands_file.is_relative_to(
        SERVICES_LAYER_COMMANDS_PACKAGE_DIR
    ), (
        "layer command service resolved outside its unified import-package "
        f"root: {services_layer_commands_file} not under "
        f"{SERVICES_LAYER_COMMANDS_PACKAGE_DIR}"
    )


def test_dist_pyproject_where_points_two_levels_up():
    """Both data-adapter pyprojects must source-find from ``../..`` —
    i.e. the unified import-package root sits two levels above each
    ``dist/<sub>/pyproject.toml``. This pattern supports editable
    installs and in-tree wheel builds; sdist is intentionally not
    supported (setuptools cannot include source above the project
    root in a self-contained release tarball).
    """
    for project_dir, expected_include_prefixes in (
        (COMMON_PROJECT, ("ovui_data_adapters.common",)),
        (SERVICES_PROJECT, ("ovui_data_adapters.services",)),
        (OPENUSD_PROJECT, ("ovui_data_adapters.openusd",)),
        (OVSTAGE_PROJECT, ("ovui_data_adapters.ovstage", "ovui_widgets_physx_controls")),
    ):
        path = project_dir / "pyproject.toml"
        data = _load_pyproject(path)
        find = data["tool"]["setuptools"]["packages"]["find"]
        assert find["where"] == ["../.."], (
            f"{path}: expected where=['../..'] (unified-source layout), "
            f"got {find['where']!r}"
        )
        for pattern in find["include"]:
            assert any(
                pattern.startswith(prefix)
                for prefix in expected_include_prefixes
            ), (
                f"{path}: include pattern {pattern!r} must start with one of "
                f"{expected_include_prefixes!r}"
            )


def test_data_adapter_dependencies_do_not_require_ovrtx():
    """Installing any data-adapter distribution must not pull ovrtx."""

    for project_dir in (
        COMMON_PROJECT,
        SERVICES_PROJECT,
        OPENUSD_PROJECT,
        OVSTAGE_PROJECT,
    ):
        path = project_dir / "pyproject.toml"
        data = _load_pyproject(path)
        dependencies = data.get("project", {}).get("dependencies", [])
        offenders = [
            dep
            for dep in dependencies
            if dep.split(";", 1)[0].strip().lower().startswith("ovrtx")
        ]
        assert offenders == [], f"{path} must not depend on ovrtx: {offenders!r}"


def test_app_and_data_adapter_dependencies_do_not_install_ovstage_runtime():
    """Installing our app/data-adapter wheels must not pull ovstage runtimes."""

    runtime_package_names = ("ovstage", "ovhierarchy", "ovpopulation", "ovphysx")
    for project_dir in (
        OVUI_WIDGETS_APP_PROJECT,
        OVUI_WIDGETS_ALL_PROJECT,
        COMMON_PROJECT,
        SERVICES_PROJECT,
        OPENUSD_PROJECT,
        OVSTAGE_PROJECT,
    ):
        path = project_dir / "pyproject.toml"
        data = _load_pyproject(path)
        dependencies = data.get("project", {}).get("dependencies", [])
        offenders = []
        for dep in dependencies:
            normalized = dep.split(";", 1)[0].strip().lower()
            if normalized.startswith(runtime_package_names):
                offenders.append(dep)
        assert offenders == [], (
            f"{path} must not depend on ovstage runtime packages: {offenders!r}"
        )


def test_aggregate_installs_standalone_openusd_without_changing_plain_adapter():
    """The full standalone stack supplies pxr without contaminating Kit installs."""

    aggregate = _load_pyproject(OVUI_WIDGETS_ALL_PROJECT / "pyproject.toml")["project"]
    openusd = _load_pyproject(OPENUSD_PROJECT / "pyproject.toml")["project"]

    aggregate_openusd = [
        dependency
        for dependency in aggregate["dependencies"]
        if dependency.startswith("ovui-data-adapters-openusd")
    ]
    assert aggregate_openusd == [
        "ovui-data-adapters-openusd[standalone]>=0.2.0"
    ]
    assert all(
        not dependency.startswith("usd-core")
        for dependency in openusd["dependencies"]
    )
    assert openusd["optional-dependencies"]["standalone"] == [
        "usd-core==25.11"
    ]


def test_subprocess_inherits_pythonpath_for_data_adapters():
    """Codex Finding 1 regression guard: the conftest must mirror the
    data-adapters source root onto ``PYTHONPATH`` so that subprocess
    tests resolve ``ovui_data_adapters`` the same way the parent does.

    Spawn a clean child Python with the inherited environment and
    confirm representative imports succeed. A failure here means the
    conftest's ``PYTHONPATH`` mirror is broken or absent.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from ovui_data_adapters.common import StageAdapter; "
                "from ovui_data_adapters.services.content.asset_types import get_category; "
                "from ovui_data_adapters.services.content.backends import LocalFSBackend; "
                "from ovui_data_adapters.services.content.clipboard import ContentClipboard; "
                "from ovui_data_adapters.services.content.file_operations import "
                "ContentFileRecord, next_copy_name; "
                "from ovui_data_adapters.services.content.navigation import "
                "BookmarksManager, RecentFileList; "
                "from ovui_data_adapters.services.layers.commands import SaveLayerCommand; "
                "from ovui_data_adapters.services.settings import Settings as ServiceSettings; "
                "from ovui_data_adapters.services.selection import SelectionBus; "
                "from ovui_data_adapters.services.testing import "
                "MockBackend, MockRendererAdapter, MockStageAdapter; "
                "from ovui_data_adapters.services.transforms import BatchTransformCommand; "
                "from ovui_data_adapters.services.undo import UndoManager; "
                "print(StageAdapter.__name__, LocalFSBackend().supports_url('file:///tmp'), "
                "get_category('scene.usd').name, UndoManager.null().can_undo(), "
                "ServiceSettings().get('ui.theme'), "
                "SelectionBus().get_snapshot().paths(), "
                "SaveLayerCommand.non_undoable, BatchTransformCommand.__name__, "
                "ContentClipboard().get_clipboard_urls(), "
                "ContentFileRecord('/a.usd', 'a.usd', False).name, "
                "next_copy_name('a.usd', False, set()), "
                "RecentFileList(['/a.usd']).get_ordered(), "
                "BookmarksManager(ServiceSettings()).list(), "
                "MockBackend().supports_url('mock://Home'), "
                "MockStageAdapter().get_display_name(MockStageAdapter().get_root()), "
                "MockRendererAdapter.__name__)"
            ),
        ],
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        "child Python failed to import ovui_data_adapters.common.\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert (
        "StageAdapter True USD False None [] True BatchTransformCommand "
        "[] a.usd a Copy.usd ['/a.usd'] {} True World MockRendererAdapter"
    ) in proc.stdout

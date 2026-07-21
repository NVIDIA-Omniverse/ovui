# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Editable-install smoke for ``ovui-data-adapters-common`` and services.

After the monorepo merge, the data-adapter pyproject stubs live at
``<monorepo-root>/ovui-data-adapters/dist/<sub>/`` and source lives at
``<monorepo-root>/ovui-data-adapters/ovui_data_adapters/<sub>/`` (same
``where = ["../.."]`` pattern as ``ovui-widgets/dist/``). Sdists from the
``dist/<sub>/`` stub are intentionally NOT supported — setuptools
cannot include source two levels above the project root in a
self-contained release tarball, so the previous
``test_data_adapters_sdist_build.py`` was rewritten as this editable-
install smoke.

This test verifies that ``ovui-data-adapters-common`` and
``ovui-data-adapters-services`` install editable in a fresh isolated
venv and are importable end-to-end. The common check imports its shipped
livestream module and therefore verifies that declared dependencies provide
NumPy without relying on the parent environment. The full concrete-provider
chain still depends on external runtimes, so this pytest remains limited to
common + services instead of using ``--no-deps`` workarounds that would defeat
the test's purpose.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import venv

import pytest

MONOREPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
COMMON_PROJECT = MONOREPO_ROOT / "ovui-data-adapters" / "dist" / "common"
SERVICES_PROJECT = MONOREPO_ROOT / "ovui-data-adapters" / "dist" / "services"


def _has_venv_module() -> bool:
    """Return True only if ``python -m venv`` is available in this interpreter."""
    proc = subprocess.run(
        [sys.executable, "-c", "import venv"],
        capture_output=True,
    )
    return proc.returncode == 0


pytestmark = pytest.mark.skipif(
    not _has_venv_module(),
    reason="python -m venv not available in this interpreter",
)


def _create_venv(tmp_path: pathlib.Path) -> tuple[str, str]:
    venv_dir = tmp_path / "venv"
    venv.create(str(venv_dir), with_pip=True, clear=False, symlinks=True)

    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    pip_name = "pip.exe" if os.name == "nt" else "pip"
    python_name = "python.exe" if os.name == "nt" else "python"
    pip = str(venv_dir / scripts_dir / pip_name)
    py = str(venv_dir / scripts_dir / python_name)
    assert pathlib.Path(pip).is_file(), f"pip missing at {pip}"
    assert pathlib.Path(py).is_file(), f"python missing at {py}"
    return pip, py


def _child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}


def test_common_editable_install_in_fresh_venv(tmp_path: pathlib.Path):
    """Editable install of ``ovui-data-adapters-common`` must succeed
    in a fresh isolated venv, ``pip check`` must be clean, and
    its NumPy-backed livestream module must import without inheriting the
    parent environment's ``PYTHONPATH``.
    """
    # All subprocess calls below must run with PYTHONPATH stripped.
    # The conftest mirrors ``<monorepo-root>/ovui-data-adapters`` onto
    # ``PYTHONPATH`` so sibling tests can import the adapters without
    # editable installs. If we let pip / pip-check / the test's import
    # subprocess inherit that PYTHONPATH, they pick up the in-tree
    # ``ovui_data_adapters_openusd.egg-info/`` (left in the source
    # tree by the parent venv's earlier editable install of openusd)
    # and treat ``ovui-data-adapters-openusd`` as installed in the
    # child venv. Stripping PYTHONPATH for every child invocation is what
    # makes this test about common alone and proves that NumPy came from the
    # common distribution's own dependency metadata.
    pip, py = _create_venv(tmp_path)
    child_env = _child_env()

    install_proc = subprocess.run(
        [pip, "install", "-e", str(COMMON_PROJECT)],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert install_proc.returncode == 0, (
        f"pip install -e {COMMON_PROJECT.name} failed:\n"
        f"--- stdout ---\n{install_proc.stdout}\n--- stderr ---\n{install_proc.stderr}"
    )

    check_proc = subprocess.run(
        [pip, "check"],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert check_proc.returncode == 0, (
        f"pip check reported broken dependencies:\n"
        f"--- stdout ---\n{check_proc.stdout}\n--- stderr ---\n{check_proc.stderr}"
    )

    # cwd=tmp_path also removes the working directory of the test
    # runner from the implicit module search.
    import_proc = subprocess.run(
        [
            py,
            "-c",
            (
                "from importlib import metadata; "
                "import sys; "
                "import numpy as np; "
                "import ovui_data_adapters.common as common; "
                "import ovui_data_adapters.common._livestream_tap as tap; "
                "requirements = metadata.requires('ovui-data-adapters-common') or []; "
                "assert 'numpy>=1.20' in requirements; "
                "assert 'ovstream' not in sys.modules; "
                "print(common.__file__, tap.__file__, np.__file__)"
            ),
        ],
        env=child_env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert import_proc.returncode == 0, (
        "child interpreter failed to import common and its livestream module:\n"
        f"--- stdout ---\n{import_proc.stdout}\n--- stderr ---\n{import_proc.stderr}"
    )
    out = import_proc.stdout.strip()
    assert out, f"child interpreter produced no output; stderr={import_proc.stderr!r}"


def test_services_editable_install_in_fresh_venv(tmp_path: pathlib.Path):
    """Editable install of ``ovui-data-adapters-services`` must succeed
    after common, pass ``pip check``, and import without UI/runtime modules.
    """
    pip, py = _create_venv(tmp_path)
    child_env = _child_env()

    for project in (COMMON_PROJECT, SERVICES_PROJECT):
        install_proc = subprocess.run(
            [pip, "install", "-e", str(project)],
            env=child_env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert install_proc.returncode == 0, (
            f"pip install -e {project.name} failed:\n"
            f"--- stdout ---\n{install_proc.stdout}\n--- stderr ---\n{install_proc.stderr}"
        )

    check_proc = subprocess.run(
        [pip, "check"],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert check_proc.returncode == 0, (
        f"pip check reported broken dependencies:\n"
        f"--- stdout ---\n{check_proc.stdout}\n--- stderr ---\n{check_proc.stderr}"
    )

    import_proc = subprocess.run(
        [
            py,
            "-c",
            (
                "import sys; "
                "import ovui_data_adapters.services as services; "
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
                "from ovui_data_adapters.services.undo import CommandCancelled, UndoManager; "
                "forbidden = [name for name in sys.modules "
                "if name == 'ovui_widgets' or name.startswith('ovui_widgets.') "
                "or name == 'omni' or name.startswith('omni.')]; "
                "backend = LocalFSBackend(); "
                "print(services.__file__, backend.supports_url('file:///tmp'), "
                "get_category('scene.usd').name, UndoManager.null().can_undo(), "
                "CommandCancelled.__name__, ServiceSettings().get('ui.theme'), "
                "SelectionBus().get_snapshot().paths(), "
                "SaveLayerCommand.non_undoable, BatchTransformCommand.__name__, "
                "ContentClipboard().get_clipboard_urls(), "
                "ContentFileRecord('/a.usd', 'a.usd', False).name, "
                "next_copy_name('a.usd', False, set()), "
                "RecentFileList(['/a.usd']).get_ordered(), "
                "BookmarksManager(ServiceSettings()).list(), "
                "MockBackend().supports_url('mock://Home'), "
                "MockStageAdapter().get_display_name(MockStageAdapter().get_root()), "
                "MockRendererAdapter.__name__, "
                "'numpy' in sys.modules); "
                "raise SystemExit(1 if forbidden else 0)"
            ),
        ],
        env=child_env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert import_proc.returncode == 0, (
        "child interpreter failed to import ovui_data_adapters.services "
        "without UI/runtime modules:\n"
        f"--- stdout ---\n{import_proc.stdout}\n--- stderr ---\n{import_proc.stderr}"
    )
    out = import_proc.stdout.strip()
    assert out, f"child interpreter produced no output; stderr={import_proc.stderr!r}"
    assert "True" in out
    assert "USD" in out
    assert "False" in out
    assert "CommandCancelled" in out
    assert "a Copy.usd" in out
    assert "['/a.usd']" in out
    assert "{}" in out
    assert "CommandCancelled None [] True BatchTransformCommand" in out

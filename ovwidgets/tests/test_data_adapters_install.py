# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Editable-install smoke for ``ovui-data-adapters-common``.

After the monorepo merge, the data-adapter pyproject stubs live at
``<monorepo-root>/ovui-data-adapters/dist/<sub>/`` and source lives at
``<monorepo-root>/ovui-data-adapters/ovui_data_adapters/<sub>/`` (same
``where = ["../.."]`` pattern as ``ovwidgets/dist/``). Sdists from the
``dist/<sub>/`` stub are intentionally NOT supported — setuptools
cannot include source two levels above the project root in a
self-contained release tarball, so the previous
``test_data_adapters_sdist_build.py`` was rewritten as this editable-
install smoke.

This test verifies that ``ovui-data-adapters-common`` (the only adapter
distribution with no external deps) installs editable in a fresh
isolated venv and is importable end-to-end. The full chain
(``ovrtx`` -> ``common`` -> ``openusd`` + ``usd-core`` + ``numpy``)
depends on a non-PyPI ``ovrtx`` checkout, so this pytest keeps the
isolated check limited to common instead of using ``--no-deps``
workarounds that would defeat the test's purpose.
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


def test_common_editable_install_in_fresh_venv(tmp_path: pathlib.Path):
    """Editable install of ``ovui-data-adapters-common`` must succeed
    in a fresh isolated venv, ``pip check`` must be clean, and
    ``import ovui_data_adapters.common`` must resolve from the venv —
    NOT from the in-tree source via the conftest's ``PYTHONPATH``
    mirror.
    """
    venv_dir = tmp_path / "venv"
    venv.create(str(venv_dir), with_pip=True, clear=False, symlinks=True)

    pip = str(venv_dir / "bin" / "pip")
    py = str(venv_dir / "bin" / "python")
    assert pathlib.Path(pip).is_file(), f"pip missing at {pip}"
    assert pathlib.Path(py).is_file(), f"python missing at {py}"

    # All subprocess calls below must run with PYTHONPATH stripped.
    # The conftest mirrors ``<monorepo-root>/ovui-data-adapters`` onto
    # ``PYTHONPATH`` so sibling tests can import the adapters without
    # editable installs. If we let pip / pip-check / the test's import
    # subprocess inherit that PYTHONPATH, they pick up the in-tree
    # ``ovui_data_adapters_openusd.egg-info/`` (left in the source
    # tree by the parent venv's earlier editable install of openusd)
    # and treat ``ovui-data-adapters-openusd`` as installed in the
    # child venv. pip check would then complain about openusd's
    # missing transitive deps (numpy / ovrtx / usd-core), which has
    # nothing to do with common's install. Stripping PYTHONPATH for
    # every child invocation is what makes this test about common
    # alone.
    child_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

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
            "import ovui_data_adapters.common as m; print(m.__file__)",
        ],
        env=child_env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert import_proc.returncode == 0, (
        f"child interpreter failed to import ovui_data_adapters.common:\n"
        f"--- stdout ---\n{import_proc.stdout}\n--- stderr ---\n{import_proc.stderr}"
    )
    out = import_proc.stdout.strip()
    assert out, f"child interpreter produced no output; stderr={import_proc.stderr!r}"

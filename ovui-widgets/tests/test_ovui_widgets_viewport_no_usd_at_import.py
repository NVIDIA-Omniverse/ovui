# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""CI invariant: importing ``ovui_widgets.viewport`` must NOT pull in ``pxr``.

Step 26 (Rev 4 §10.5): the widget tree is OpenUSD-free at import time.
A re-export reintroducing ``OvRtxRendererAdapter`` or
``OVRTX_AVAILABLE`` into ``ovui_widgets/viewport/__init__.py`` would
force every consumer of the viewport package to load the OpenUSD
plugin, defeating the whole point of the data-adapters split.

The test runs in a clean Python subprocess so ``sys.modules`` state is
not contaminated by earlier tests that legitimately import ``pxr``
through the openusd adapter package. The subprocess imports
``ovui_widgets.viewport`` and exits non-zero if ``pxr`` (or any USD
submodule) is in ``sys.modules`` afterwards.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap


def _venv_python() -> str:
    """Return the venv python that imports ovui-widgets cleanly.

    The repo's `_venv312/bin/python` is the canonical interpreter that
    has the editable installs from Step 25 wired up. Falling back to
    ``sys.executable`` keeps the test usable in CI environments where
    the venv lives elsewhere.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(repo_root, "_venv312", "bin", "python")
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return sys.executable


def test_import_ovui_widgets_viewport_does_not_load_pxr():
    """``import ovui_widgets.viewport`` must NOT bring ``pxr`` into ``sys.modules``."""
    child_dll_preamble = sys.modules[
        "tests.conftest"
    ].CHILD_PROCESS_VULKAN_DLL_PREAMBLE

    code = child_dll_preamble + textwrap.dedent(
        """
        import sys
        # Sanity: pxr must not already be in sys.modules at subprocess
        # start. If a site-customize / .pth file pulled it in, the
        # invariant we want to test is moot — fail loudly with a
        # distinct exit code.
        if "pxr" in sys.modules:
            sys.stderr.write("pxr already loaded at subprocess start\\n")
            sys.exit(3)
        import ovui_widgets.viewport  # noqa: F401
        leaked = sorted(m for m in sys.modules if m == "pxr" or m.startswith("pxr."))
        if leaked:
            sys.stderr.write(
                "ovui_widgets.viewport import leaked pxr submodules: "
                + ",".join(leaked)
                + "\\n"
            )
            sys.exit(1)
        sys.exit(0)
        """
    )
    env = dict(os.environ)
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env.setdefault("OVRTX_SKIP_USD_CHECK", "1")
    proc = subprocess.run(
        [_venv_python(), "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"subprocess exited {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )

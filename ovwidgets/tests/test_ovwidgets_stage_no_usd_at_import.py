# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""CI invariant: importing ``ovwidgets.stage`` must NOT pull in ``pxr``.

Step 26 (Rev 4 §10.5): analogous to
``test_ovwidgets_viewport_no_usd_at_import.py``. The stage widget
package owns the prim-tree window, delegates, and selection plumbing;
none of those need OpenUSD at import time. The concrete USD adapters
(``UsdStageAdapter``, ``UsdPropertyAdapter``,
``UsdLayerStackAdapter``, etc.) live in
``ovui_data_adapters.openusd`` and are loaded lazily by
``Application._load_stage`` only when a real stage is opened.

A re-export reintroducing ``UsdStageAdapter`` / ``UsdTransformAdapter``
into ``ovwidgets/stage/__init__.py`` would force every
``import ovwidgets.stage`` to load USD — exactly the regression the
data-adapters refactor was built to prevent.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap


def _venv_python() -> str:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(repo_root, "_venv312", "bin", "python")
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return sys.executable


def test_import_ovwidgets_stage_does_not_load_pxr():
    """``import ovwidgets.stage`` must NOT bring ``pxr`` into ``sys.modules``."""
    code = textwrap.dedent(
        """
        import sys
        if "pxr" in sys.modules:
            sys.stderr.write("pxr already loaded at subprocess start\\n")
            sys.exit(3)
        import ovwidgets.stage  # noqa: F401
        leaked = sorted(m for m in sys.modules if m == "pxr" or m.startswith("pxr."))
        if leaked:
            sys.stderr.write(
                "ovwidgets.stage import leaked pxr submodules: "
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

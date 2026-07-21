# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Layout-save witness test for issue #35 — Step 9.

Step 8 proves the subprocess exits with ``rc=0``. That alone could be
satisfied by a shutdown path that skipped :meth:`Application._save_layout`
entirely. Step 9 nails the ordering: ``_save_layout`` MUST run before
the shutdown tears windows down, otherwise the user loses their custom
panel layout on every clean exit.

Design constraints:

* Codex Round 1 F14 — HOME isolation. ``HOME=tmp_path`` means the
  child writes ``tmp_path/.ovgear/layout.json``, NEVER the user's real
  ``~/.ovgear/layout.json``. ``_child_env`` (Step 8) already enforces
  this; this test just relies on it.
* Plan §"Step 9" pseudocode uses ``headless=False`` (windowed) — the
  realistic user-clicks-X path. Skip if no ``DISPLAY`` so CI without
  an X server isn't a hard failure.
* Schema check pins ``{"version": 1, "windows": <dict>}`` — exactly
  what :func:`ovui_widgets.app.layout.save_layout_data` writes. A regression
  that wrote an empty file or a string would fail the parse OR the
  shape assertion.
"""
from __future__ import annotations

import json
import os

import pytest

from tests.test_clean_exit_subprocess import (
    _NO_GPU,
    _no_gpu_reason,
    _run_ovgear_subprocess,
)

pytestmark = pytest.mark.requires_ovrtx


@pytest.mark.skipif(_NO_GPU, reason=_no_gpu_reason)
def test_layout_saved_on_clean_exit(tmp_path) -> None:
    """OvGear must persist ``~/.ovgear/layout.json`` during shutdown.

    Witnesses the Step-5 ordering contract: :meth:`Application.shutdown`
    calls :meth:`Application._save_layout` BEFORE tearing down panel
    windows, so :func:`ovui_widgets.app.layout._collect_layout` still sees live
    ``ui.Window`` objects with position/size attributes.

    Uses windowed mode (matches plan §"Step 9" pseudocode) — the
    realistic user-clicks-X path. Skipped if no DISPLAY is available.
    """
    if not os.environ.get("DISPLAY"):
        pytest.skip("no DISPLAY for windowed mode")

    proc = _run_ovgear_subprocess(headless=False, tmp_path=tmp_path)

    # Sanity: subprocess succeeded. If it crashed, the layout-file
    # check below would be ambiguous (missing file because shutdown
    # never reached _save_layout, or because shutdown segfaulted
    # mid-write). Surface rc!=0 with the same diagnostics shape Step 8
    # uses, so a regression points to the right step.
    assert proc.returncode == 0, (
        f"subprocess rc={proc.returncode}; "
        f"stderr tail:\n"
        f"{proc.stderr.decode('utf-8', errors='replace')[-1500:]}"
    )

    layout = tmp_path / ".ovgear" / "layout.json"
    assert layout.exists(), (
        f"layout not written during shutdown — _save_layout() did not "
        f"run, OR ran after window teardown so _collect_layout() saw "
        f"no live windows. tmp_path contents: "
        f"{sorted(p.name for p in tmp_path.iterdir())}"
    )

    # Parse + schema check. Must match ovui_widgets.app.layout.save_layout_data:
    #   json.dump({"version": 1, "windows": <dict>}, ...)
    data = json.loads(layout.read_text(encoding="utf-8"))
    assert isinstance(data, dict), (
        f"layout.json top-level must be a dict; got {type(data).__name__}"
    )
    assert data.get("version") == 1, (
        f"layout.json version must be 1; got {data.get('version')!r}"
    )
    windows = data.get("windows")
    assert isinstance(windows, dict), (
        f"layout.json 'windows' must be a dict; got "
        f"{type(windows).__name__}"
    )

    # Codex Step-9 fix: an empty ``windows`` dict would still satisfy the
    # type-only check above, but it means ``_collect_layout()`` ran
    # AFTER the panel windows were torn down (or panels never came up).
    # Pin at least one of the five core panels — keys come straight
    # from :func:`ovui_widgets.app.layout._collect_layout`'s ``panel_map``. If the
    # panel set ever changes, update this list AND the layout module.
    expected_panels = {
        "Stage Browser",
        "Property Inspector",
        "Viewport",
        "Content",
        "Layers",
    }
    present = expected_panels & set(windows.keys())
    assert present, (
        f"layout.json 'windows' has no recognised panel keys — "
        f"_collect_layout() likely ran AFTER panel windows were torn "
        f"down (or no panels were created). "
        f"Expected at least one of {sorted(expected_panels)!r}; "
        f"got keys {sorted(windows.keys())!r}"
    )

    # And one inner-shape check on whichever panel happens to be
    # present: ``_collect_layout`` writes
    #   {"visible": bool, "position_x": float, "position_y": float,
    #    "width": float, "height": float}
    # Pinning these catches a regression that wrote stub/empty entries.
    sample_key = sorted(present)[0]
    sample = windows[sample_key]
    assert isinstance(sample, dict), (
        f"windows[{sample_key!r}] must be a dict; got "
        f"{type(sample).__name__}"
    )
    for field in ("visible", "position_x", "position_y", "width", "height"):
        assert field in sample, (
            f"windows[{sample_key!r}] missing field {field!r}; "
            f"got {sorted(sample.keys())!r}"
        )

#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run the full-GPU export checks and require normal process shutdown."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


_SELECTION = (
    "ovui/tests/test_headless_clear_color.py::TestHeadlessClearColor",
    "ovui/tests/test_headless_clear_color.py::TestClearColorBeforeInit",
    "ovui/tests/test_headless_frame.py::TestHeadlessFrameEndToEnd",
)
_REQUIRED = {
    ("tests.test_headless_clear_color.TestHeadlessClearColor", name)
    for name in (
        "test_default_clear_is_unchanged",
        "test_files_composite_like_a_direct_draw",
        "test_invalid_value_keeps_the_color",
        "test_transparent_clear_keeps_drawn_pixels",
    )
} | {
    ("tests.test_headless_clear_color.TestClearColorBeforeInit", "test_refused_before_init"),
    ("tests.test_headless_frame.TestHeadlessFrameEndToEnd", "test_end_to_end_copy_produces_nonzero_variance"),
    ("tests.test_headless_frame.TestHeadlessFrameEndToEnd", "test_export_has_the_clear_color"),
}


def check_report(path: Path) -> None:
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    found = Counter((case.get("classname"), case.get("name")) for case in cases)
    missing = _REQUIRED - found.keys()
    duplicates = [key for key, count in found.items() if count != 1]
    if missing or duplicates:
        raise ValueError(f"export report: missing {sorted(missing)}; duplicate {duplicates}")
    for node in root.iter():
        if node.tag in {"skipped", "failure", "error"}:
            raise ValueError(f"export report: {node.tag}: {node.get('message', '')}")
        if node.tag in {"testsuite", "testsuites"}:
            for outcome in ("errors", "failures", "skipped"):
                if int(node.get(outcome, "0")) != 0:
                    raise ValueError(f"export report: {outcome}={node.get(outcome)}")
    print(f"Export report: all {len(_REQUIRED)} required checks passed ({len(cases)} total).", flush=True)


def main() -> int:
    report = Path("headless-export.xml").resolve()
    # Never accept a report from an earlier attempt.
    report.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="ovui_export_exit_") as tmp:
        marker = Path(tmp) / "normal-exit"
        # Registered before product imports, so product atexit handlers run
        # first. os._exit skips this marker. A native crash still fails by rc.
        code = (
            "import atexit, pathlib, sys\n"
            "marker = pathlib.Path(sys.argv.pop(1))\n"
            "atexit.register(lambda: marker.write_text('normal exit\\n'))\n"
            "import pytest\n"
            "raise SystemExit(pytest.main(sys.argv[1:]))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(marker), "-c", "ovui/pyproject.toml",
             "-rs", "-v", "--timeout=120", *_SELECTION, f"--junitxml={report}"],
            timeout=180,
        )
        print(f"Export process exit: {result.returncode}", flush=True)
        if result.returncode != 0:
            raise RuntimeError(f"export process failed with exit code {result.returncode}")
        if not marker.is_file():
            raise RuntimeError("export process skipped normal interpreter shutdown")
    check_report(report)
    print("Export process and report checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, ET.ParseError, subprocess.TimeoutExpired) as error:
        print(f"Headless export verification failed: {error}", file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Fail unless every failed or errored test in a JUnit report is caused by missing pxr.

Used on Python versions that have no usd-core wheel for the tested release. The
test suites of the packages run there with collection errors allowed. This
script then requires that the error each failure ends with is the import error
of the pxr module itself (``ModuleNotFoundError: No module named 'pxr'``, or a
``pxr`` submodule). Any other failure, including an adapter failure that only
looks related, fails the job. It also requires a minimum number of passed tests,
so that a suite that stopped early cannot pass.

Tests that need pxr but fail with another message cannot be told apart from a
real defect here, so the workflow deselects them by exact test id.

    check_no_pxr_failures.py report.xml --min-passed 1000
    check_no_pxr_failures.py --selftest
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

# The last error line of the traceback must be the failed import of pxr.
_PXR_ERROR_LINE = re.compile(r"^E\s+ModuleNotFoundError: No module named 'pxr(?:\.\w+)*'\s*$")
_ERROR_LINE = re.compile(r"^E\s")


def _caused_by_missing_pxr(text: str) -> bool:
    error_lines = [line for line in text.splitlines() if _ERROR_LINE.match(line)]
    return bool(error_lines) and _PXR_ERROR_LINE.match(error_lines[-1]) is not None


def analyse(path: Path):
    passed = 0
    bad = []
    tolerated = 0
    for case in ET.parse(path).getroot().iter("testcase"):
        outcome = None
        for child in case:
            if child.tag in ("failure", "error"):
                outcome = child
        if outcome is None:
            if not any(child.tag == "skipped" for child in case):
                passed += 1
            continue
        text = (outcome.get("message") or "") + "\n" + (outcome.text or "")
        if _caused_by_missing_pxr(text):
            tolerated += 1
        else:
            bad.append((case.get("classname", ""), case.get("name", ""), (outcome.get("message") or "")[:160]))
    return passed, tolerated, bad


def selftest() -> int:
    def report(cases):
        body = "".join(cases)
        return f"<testsuites><testsuite>{body}</testsuite></testsuites>"

    def case(name, tag, message, body):
        return f'<testcase classname="a" name="{name}"><{tag} message="{message}">{body}</{tag}></testcase>'

    ok = '<testcase classname="a" name="t1"/>'
    pxr = case("t2", "error", "collection failure", "E   ModuleNotFoundError: No module named 'pxr'")
    pxr_sub = case("t2b", "error", "collection failure", "E   ModuleNotFoundError: No module named 'pxr.Usd'")
    other = case("t3", "failure", "AssertionError: 1 != 2", "E   AssertionError: 1 != 2")
    adapter_attr = case(
        "t4", "failure", "AttributeError", "E   AttributeError: module 'ovui_data_adapters' has no attribute 'openusd'"
    )
    adapter_module = case(
        "t5", "failure", "ModuleNotFoundError", "E   ModuleNotFoundError: No module named 'ovui_data_adapters.openusd.stage_adapter'"
    )
    selection = case(
        "t6", "failure", "AdapterProviderSelectionError",
        "E   ovui_data_adapters.common._adapter_registry.AdapterProviderSelectionError: no adapter providers are registered",
    )
    other_module = case("t7", "error", "collection failure", "E   ModuleNotFoundError: No module named 'ovstream'")
    # pxr is named in the text, but the failure ends with another error.
    pxr_then_other = case(
        "t8", "failure", "AssertionError",
        "E   ModuleNotFoundError: No module named 'pxr'\nE   During handling of the above exception, another exception occurred\nE   AssertionError: 1 != 2",
    )
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        for label, cases, want in (
            ("pass, pxr and pxr submodule failures are accepted", [ok, pxr, pxr_sub], 0),
            ("a failure with another cause is rejected", [ok, pxr, other], 1),
            ("a missing attribute of the openusd adapter package is rejected", [ok, pxr, adapter_attr], 1),
            ("a missing adapter module is rejected", [ok, pxr, adapter_module], 1),
            ("AdapterProviderSelectionError is rejected", [ok, pxr, selection], 1),
            ("another missing module is rejected", [ok, pxr, other_module], 1),
            ("a failure that ends with another error after pxr is rejected", [ok, pxr, pxr_then_other], 1),
        ):
            path = Path(tmp) / "r.xml"
            path.write_text(report(cases))
            _, _, bad = analyse(path)
            got = 1 if bad else 0
            print(f"selftest: {label}: {'ok' if got == want else 'FAILED'}")
            failures += got != want
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", nargs="?", type=Path)
    parser.add_argument("--min-passed", type=int, default=1)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if not args.report:
        parser.error("a report is required")
    passed, tolerated, bad = analyse(args.report)
    print(f"{args.report}: {passed} passed, {tolerated} failed only because OpenUSD is missing, {len(bad)} failed for another cause")
    for classname, name, message in bad:
        print(f"::error title=Test failed for a reason other than missing OpenUSD::{classname}::{name}: {message}")
    if passed < args.min_passed:
        print(f"::error title=Too few tests passed::{passed} passed, at least {args.min_passed} required")
        return 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

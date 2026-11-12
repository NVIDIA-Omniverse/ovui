#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Prove which commit a set of built wheels came from.

Workflow metadata identifies the ref that started the run. A manual dispatch
may build a different release tag, so the source provenance must be checked in
the wheels themselves against the resolved build commit.

`ovui/setup.py` writes `omni/ui/_build_info.py` into every native wheel:

    __version__ = '0.3.0'
    __commit__ = '0123456789abcdef0123456789abcdef01234567'

`__commit__` is the commit that was checked out when the wheel was built. A
wheel built from another commit carries that other commit, whatever the run
metadata says.

NATIVE wheels must each carry it. A native wheel is one whose filename tag is
not `py3-none-any`: it holds compiled payload and is built by a job that
records the commit. A native wheel with no
build info has no provenance at all, so it is REJECTED, not skipped. Counting
attested wheels across the set is not enough â€” one good wheel must never vouch
for another.

The pure-Python wheels carry no build info. They are produced by the same job,
from the same checkout, as the native Linux x64 wheel, so the native wheels are
the evidence for them. `--expect-native` pins how many native wheels the set
must contain, so a missing one cannot pass as "nothing to check".
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import sys
import tempfile
import zipfile

BUILD_INFO_SUFFIX = "/_build_info.py"

# A wheel's compatibility tag is the last three dash-separated fields of its
# name. `py3-none-any` is the pure-Python tag; anything else carries compiled
# payload for one platform.
PURE_TAG = "py3-none-any"


def is_native(wheel: pathlib.Path) -> bool:
    """True when the wheel carries compiled payload for a platform."""
    parts = wheel.stem.split("-")
    if len(parts) < 3:
        return False
    return "-".join(parts[-3:]) != PURE_TAG


def read_commit(wheel: pathlib.Path) -> str | None:
    """Return the `__commit__` a wheel records, or None if it records none."""
    with zipfile.ZipFile(wheel) as archive:
        members = [n for n in archive.namelist() if n.endswith(BUILD_INFO_SUFFIX)]
        if not members:
            return None
        # More than one would mean two packages in one wheel. Read them all and
        # let a disagreement surface as a mismatch rather than picking one.
        commits = set()
        for member in members:
            source = archive.read(member).decode("utf-8")
            for node in ast.parse(source).body:
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__commit__":
                        commits.add(ast.literal_eval(node.value))
        if not commits:
            return None
        if len(commits) > 1:
            return "<conflicting: %s>" % ", ".join(sorted(commits))
        return commits.pop()


def check(
    directory: pathlib.Path,
    expected: str,
    expect_native: int | None = None,
) -> int:
    wheels = sorted(directory.glob("*.whl"))
    if not wheels:
        print(f"ERROR: no wheels in {directory}", file=sys.stderr)
        return 1

    native = 0
    matched = 0
    mismatched = []
    unattested = []
    for wheel in wheels:
        commit = read_commit(wheel)
        kind = "native" if is_native(wheel) else "pure  "
        if is_native(wheel):
            native += 1
        if commit is None:
            print(f"  {wheel.name:<64} {kind} no build info")
            if is_native(wheel):
                # A native wheel without provenance is the hole this closes.
                unattested.append(wheel.name)
            continue
        if commit == expected:
            matched += 1
            print(f"  {wheel.name:<64} {kind} commit {commit} OK")
        else:
            mismatched.append(wheel.name)
            print(f"  {wheel.name:<64} {kind} commit {commit} MISMATCH")

    print(
        f"{len(wheels)} wheel(s), {native} native, "
        f"{matched} match, {len(mismatched)} mismatched, "
        f"{len(unattested)} native without build info"
    )

    failed = False
    if mismatched:
        print(
            f"::error title=Wheel commit mismatch::{len(mismatched)} wheel(s) were built "
            f"from a commit other than {expected}: {', '.join(mismatched)}. "
            f"These wheels must not be released.",
            file=sys.stderr,
        )
        failed = True
    if unattested:
        print(
            f"::error title=Native wheel without provenance::{len(unattested)} native "
            f"wheel(s) carry no build commit: {', '.join(unattested)}. Nothing proves "
            f"which commit they came from, so they must not be released.",
            file=sys.stderr,
        )
        failed = True
    if native == 0:
        print(
            "::error title=No native wheel to check::the set contains no native wheel, "
            "so nothing proves which commit it came from.",
            file=sys.stderr,
        )
        failed = True
    if expect_native is not None and native != expect_native:
        print(
            f"::error title=Wrong number of native wheels::expected {expect_native} "
            f"native wheel(s), found {native}. A missing native wheel must not pass as "
            f"'nothing to check'.",
            file=sys.stderr,
        )
        failed = True

    if failed:
        return 1
    print(f"OK: all {native} native wheel(s) were built from {expected}")
    return 0


def selftest() -> int:
    """Prove the check can fail. A gate that cannot fail is not a gate.

    Covers every way the release set can be wrong:
      * a native wheel built from another commit,
      * a native wheel with no build info at all â€” the hole an earlier version
        of this script left open, because it skipped what it could not read,
      * a set with no native wheel,
      * the wrong number of native wheels.
    """
    good = "a" * 40
    bad = "b" * 40

    def write(where: pathlib.Path, name: str, commit: str | None) -> None:
        with zipfile.ZipFile(where / name, "w") as archive:
            if commit is None:
                archive.writestr("omni/ui/__init__.py", "")
            else:
                archive.writestr(
                    "omni/ui/_build_info.py",
                    f"__version__ = '0.0.0'\n__commit__ = {commit!r}\n",
                )

    native = "ovui-0.0.0-cp312.cp313.cp314.cp315-cp312.cp313.cp314.cp315-win_amd64.whl"
    native2 = "ovui-0.0.0-cp312.cp313.cp314.cp315-cp312.cp313.cp314.cp315-linux_x86_64.whl"
    pure = "ovui_widgets_app-0.0.0-py3-none-any.whl"

    cases = [
        ("a matching native wheel beside a pure one", [(native, good), (pure, None)], 1, 0),
        ("a native wheel from another commit", [(native, bad), (pure, None)], 1, 1),
        ("a NATIVE wheel with no build info, beside a good one",
         [(native, good), (native2, None), (pure, None)], 2, 1),
        ("a set with no native wheel at all", [(pure, None)], None, 1),
        ("one native wheel short", [(native, good)], 2, 1),
    ]

    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        for index, (label, members, expect_native, want) in enumerate(cases):
            case_dir = pathlib.Path(tmp) / f"case{index}"
            case_dir.mkdir()
            for name, commit in members:
                write(case_dir, name, commit)
            print(f"selftest: {label}")
            got = 1 if check(case_dir, good, expect_native) != 0 else 0
            if got != want:
                verb = "rejected" if want else "accepted"
                print(f"SELFTEST FAILED: {label} should have been {verb}", file=sys.stderr)
                failures += 1
            print()

    if failures:
        return 1
    print("SELFTEST OK: the check accepts a sound set and rejects a mismatch, a native "
          "wheel without provenance, a set with no native wheel, and a short set")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", help="directory holding the wheels")
    parser.add_argument("--expected", help="the commit SHA the wheels must record")
    parser.add_argument(
        "--expect-native",
        type=int,
        default=None,
        help="fail unless the set holds exactly this many native wheels",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="prove the check accepts a matching set and rejects a mismatch",
    )
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if not args.directory or not args.expected:
        parser.error("directory and --expected are required unless --selftest is given")
    return check(pathlib.Path(args.directory), args.expected, args.expect_native)


if __name__ == "__main__":
    raise SystemExit(main())

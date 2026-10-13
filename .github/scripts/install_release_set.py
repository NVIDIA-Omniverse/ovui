#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Install the release wheel set, as a user would, and fail if it cannot.

First-party requirements are pinned to VERSION.md. Install the complete set
with --find-links pointing at the built wheels so those exact versions resolve
locally, while third-party requirements come from the package index. Run pip
check after each installation to catch incompatible package metadata.

What it does
------------
For the wheels compatible with the running platform:

* one environment takes every pure-Python wheel together with one native
  ``ovui`` wheel -- the pure wheels pin ``ovui==<version>`` and each other, so
  this is what exercises the pins across the whole set;
* each remaining compatible native wheel is installed on its own, so no
  compatible wheel goes unchecked (the plain and the ``manylinux`` build of the
  same version cannot share an environment: same name, same version);
* ``pip check`` runs in each environment.

Wheels for another platform are skipped and counted. If nothing was installable
the check fails, because then it proved nothing.

Usage:
    python install_release_set.py --wheels-dir <dir> [--python <exe>]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# (name, version) of a wheel, from its filename. A wheel filename is
# name-version-pytag-abitag-platformtag.whl, and name/version never contain '-'
# once escaped, so the first two fields are unambiguous.
_WHEEL_RE = re.compile(r"^(?P<name>[^-]+)-(?P<version>[^-]+)-(?P<rest>.+)\.whl$")

def _platform_tags(filename: str) -> str:
    m = _WHEEL_RE.match(filename)
    if not m:
        raise SystemExit(f"not a wheel filename: {filename}")
    return m.group("rest").rsplit("-", 1)[-1]


def _is_pure(filename: str) -> bool:
    return _platform_tags(filename) == "any"


def _machine() -> str:
    m = platform.machine().lower()
    if m in {"amd64", "x86_64"}:
        return "x86_64"
    if m in {"aarch64", "arm64"}:
        return "aarch64"
    return m


def _interpreter_ok(filename: str, py_version: tuple[int, int]) -> bool:
    """Does this wheel's interpreter tag accept the interpreter we install with?

    `ovui` ships CPython-specific wheels (`cp312`); the pure wheels are `py3`.
    Checking this keeps a wheel built for another CPython out of the compatible
    set, so it is reported as skipped instead of failing the check.
    """
    m = _WHEEL_RE.match(filename)
    if not m:
        raise SystemExit(f"not a wheel filename: {filename}")
    py_tags = m.group("rest").split("-")[0].split(".")
    want_cp = "cp{}{}".format(*py_version)
    for tag in py_tags:
        if tag in {"py3", f"py{py_version[0]}", want_cp}:
            return True
    return False


def _compatible(filename: str) -> bool:
    """Can this wheel install on the machine running the check?

    Conservative on purpose: a wheel this returns False for is reported as
    skipped, never as passed.
    """
    tags = _platform_tags(filename)
    if tags == "any":
        return True
    system = platform.system()
    machine = _machine()
    if system == "Windows":
        return tags.startswith("win") and ("amd64" in tags) == (machine == "x86_64")
    if system == "Linux":
        if not ("linux" in tags):
            return False
        # linux_x86_64 and manylinux_2_35_x86_64 both end in the machine name.
        return tags.endswith(machine)
    if system == "Darwin":
        return tags.startswith("macosx")
    return False


def _interpreter_version(executable: str) -> tuple[int, int]:
    out = subprocess.run(
        [executable, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
        text=True, capture_output=True, check=True).stdout.split()
    return int(out[0]), int(out[1])


def _venv_python(venv: Path) -> Path:
    if platform.system() == "Windows":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run([str(c) for c in cmd], text=True)


def _install(label: str, wheels: list[Path], find_links: Path, base_python: str) -> bool:
    """Install `wheels` together into a fresh environment. True when it worked."""
    print(f"\n=== {label}: {len(wheels)} wheel(s)", flush=True)
    for w in wheels:
        print(f"    {w.name}", flush=True)
    tmp = Path(tempfile.mkdtemp(prefix="install-set-"))
    try:
        venv = tmp / "venv"
        if _run([base_python, "-m", "venv", str(venv)]).returncode != 0:
            print(f"::error title=Release set install::{label}: could not create a venv")
            return False
        py = _venv_python(venv)
        # --find-links is the point of this check: the pinned first-party
        # siblings resolve against the set being released. The index stays
        # enabled so third-party requirements (numpy, usd-core, ...) still come
        # from where a user would get them.
        cmd = [py, "-m", "pip", "install", "--disable-pip-version-check",
               "--find-links", str(find_links)] + [str(w) for w in wheels]
        if _run(cmd).returncode != 0:
            print(f"::error title=Release set install::{label}: pip install failed")
            return False
        if _run([py, "-m", "pip", "check"]).returncode != 0:
            print(f"::error title=Release set install::{label}: pip check reported a broken environment")
            return False
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wheels-dir", required=True, type=Path)
    ap.add_argument("--python", default=sys.executable,
                    help="interpreter used to create the throwaway environments")
    args = ap.parse_args()

    wheels = sorted(args.wheels_dir.rglob("*.whl"))
    if not wheels:
        print(f"::error title=Release set install::no wheel found under {args.wheels_dir}")
        return 1

    py_version = _interpreter_version(args.python)
    compatible = [w for w in wheels
                  if _compatible(w.name) and _interpreter_ok(w.name, py_version)]
    skipped = [w for w in wheels if w not in compatible]
    pure = [w for w in compatible if _is_pure(w.name)]
    native = [w for w in compatible if not _is_pure(w.name)]

    print(f"platform: {platform.system()} {_machine()}  "
          f"install interpreter: {args.python} (CPython {py_version[0]}.{py_version[1]})")
    print(f"wheels: {len(wheels)}  compatible: {len(compatible)}  "
          f"skipped as cross-platform: {len(skipped)}")
    for w in skipped:
        print(f"    skipped {w.name}")

    if not compatible:
        print("::error title=Release set install::no wheel of this set is installable here "
              "-- the install check proved nothing")
        return 1

    ok = True
    installed: set[str] = set()

    # The pure wheels pin `ovui==<version>` and one another, so they need a
    # native ovui from this same set. One environment for all of them is what
    # proves the pins resolve.
    if pure:
        if native:
            first, rest = native[0], native[1:]
            group = pure + [first]
        else:
            # No native wheel for this platform: the pure set alone would fail
            # on its pinned `ovui==`, and that is a platform gap, not a defect.
            print("::warning title=Release set install::no native ovui wheel for this platform; "
                  "the pure wheels cannot be installed here")
            first, rest, group = None, [], []
        if group:
            if _install("the whole set", group, args.wheels_dir, args.python):
                installed.update(w.name for w in group)
            else:
                ok = False
    else:
        rest = native

    # Each remaining native build on its own: same name and version as the one
    # above, so it cannot share that environment.
    for w in rest:
        if _install(f"{w.name} alone", [w], args.wheels_dir, args.python):
            installed.add(w.name)
        else:
            ok = False

    unchecked = [w.name for w in compatible if w.name not in installed]
    if unchecked and ok:
        print("::error title=Release set install::compatible wheels were never installed: "
              + ", ".join(sorted(unchecked)))
        ok = False

    summary = {
        "platform": f"{platform.system()}-{_machine()}",
        "wheels": len(wheels),
        "compatible": len(compatible),
        "installed": len(installed),
        "skipped_cross_platform": len(skipped),
        "ok": ok,
    }
    print("\n" + json.dumps(summary))

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(f"### Release set install check ({summary['platform']})\n\n")
            fh.write("| Check | Result |\n|---|---|\n")
            fh.write(f"| Wheels in set | {summary['wheels']} |\n")
            fh.write(f"| Installable here | {summary['compatible']} |\n")
            fh.write(f"| Installed | {summary['installed']} |\n")
            fh.write(f"| Skipped (other platform) | {summary['skipped_cross_platform']} |\n\n")
            fh.write(f"**installed: {str(ok).lower()}**\n")

    if not ok:
        return 1
    print(f"OK: {len(installed)} wheel(s) of this set installed, "
          f"{len(skipped)} skipped as cross-platform")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

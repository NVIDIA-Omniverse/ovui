#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Combine per-interpreter native wheels into one combined-tag wheel, and check it.

Each native package ships one wheel per platform. The wheel holds the native
Python modules of every supported CPython version, and the native libraries
that do not depend on Python once. Its tag lists all versions, for example:

    ovui-1.0.0-cp312.cp313.cp314.cp315-cp312.cp313.cp314.cp315-manylinux_2_35_x86_64.whl

pip picks the wheel on each of the four versions, and the import system picks
the module whose file name suffix fits the running interpreter
(``_ui.cpython-313-x86_64-linux-gnu.so``, ``_ui.cp313-win_amd64.pyd``).

Commands:

    combine  one wheel per interpreter -> one combined wheel (and optional
             extra platform tags, for example the manylinux name of a
             linux_<arch> wheel)
    modules  verify that the native modules of a one-interpreter wheel carry the suffix of
             its interpreter
    check    verify a combined wheel: file name, WHEEL tags, RECORD, and the
             module suffix set of every native module
    selftest prove that combine and check accept good input and reject bad input

Rules of ``combine``:

  * The input wheels have the same name, version and platform tag, and one
    CPython version each (tag cpXY-cpXY). No version may be missing or repeated.
  * The wheel of the lowest version is the base. All files that are not
    version-suffixed native modules come from the base.
  * Every other wheel must hold exactly the same set of file names. A file that
    is not a native binary must have the same bytes. Native shared libraries,
    their debug symbol (PDB) files and the files that record their hashes differ
    between builds and are taken from the base; the modules of the other versions are linked to them by the
    library name, as in a single build.
  * Each input wheel may hold native modules of its own version only.
  * RECORD is written again from the final files. The WHEEL Tag lines list
    every tag of the file name.
"""

from __future__ import annotations

import argparse
import base64
import csv
import email.parser
import hashlib
import io
import itertools
import re
import sys
import tempfile
import zipfile
from pathlib import Path

DEFAULT_VERSIONS = ("cp312", "cp313", "cp314", "cp315")

# name-version-pytag-abitag-platformtag.whl. Name and version have no '-'.
_WHEEL_RE = re.compile(
    r"^(?P<name>[^-]+)-(?P<version>[^-]+)(?:-(?P<build>\d[^-]*))?-(?P<py>[^-]+)-(?P<abi>[^-]+)-(?P<plat>[^-]+)\.whl$"
)

# A native Python module carries the interpreter in its file name.
_SO_MODULE_RE = re.compile(r"^(?P<stem>[^.]+)\.cpython-(?P<ver>\d+)(?P<free>t?)-[^/]*\.so$")
_PYD_MODULE_RE = re.compile(r"^(?P<stem>[^.]+)\.cp(?P<ver>\d+)(?P<free>t?)-[^/]*\.pyd$")

# Native binaries and records of their hashes. They differ between two builds of
# the same sources, so they are taken from the base wheel and not compared.
_BUILD_OUTPUT_RE = re.compile(
    r"(\.so(\.\d+)*|\.dll|\.pdb|\.lib|\.dylib|\.a|\.exp)$|(^|/)sdk/manifest\.json$|(^|/)sbom\.cdx\.json$"
)

_DIST_INFO_RE = re.compile(r"^[^/]+\.dist-info/(?P<leaf>[^/]+)$")


class CombineError(Exception):
    pass


def parse_name(path: Path) -> dict:
    m = _WHEEL_RE.match(path.name)
    if not m:
        raise CombineError(f"not a wheel file name: {path.name}")
    return m.groupdict()


def module_info(member: str):
    """Return (key, version tag, free-threaded) for a version-suffixed module, else None."""
    directory, _, leaf = member.rpartition("/")
    for regex in (_SO_MODULE_RE, _PYD_MODULE_RE):
        m = regex.match(leaf)
        if m:
            return (directory, m.group("stem")), f"cp{m.group('ver')}", bool(m.group("free"))
    return None


def is_unsuffixed_module(member: str) -> bool:
    """A native module whose name does not say which Python it is for."""
    leaf = member.rpartition("/")[2]
    if module_info(member):
        return False
    if leaf.endswith(".pyd"):
        return True
    # lib*.so and lib*.so.N are shared libraries, not Python modules. A .so with
    # no lib prefix and no version tag is treated as a module (or an abi3 one).
    return leaf.endswith(".so") and not leaf.startswith("lib")


def record_line(name: str, data: bytes):
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
    return [name, f"sha256={digest}", str(len(data))]


def build_record(files: dict, record_name: str) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for name in sorted(files):
        if name == record_name:
            continue
        writer.writerow(record_line(name, files[name]))
    writer.writerow([record_name, "", ""])
    return out.getvalue().encode("utf-8")


def expand_tags(py: str, abi: str, plat: str):
    return [f"{p}-{a}-{pl}" for p, a, pl in itertools.product(py.split("."), abi.split("."), plat.split("."))]


def rewrite_wheel_file(text: str, py: str, abi: str, plat: str) -> str:
    # No blank line may stand between the headers: a header parser (pip check
    # uses one) stops at the first blank line and would then read no tag.
    kept = [line for line in text.splitlines() if line.strip() and not line.startswith("Tag:")]
    kept.extend(f"Tag: {tag}" for tag in expand_tags(py, abi, plat))
    return "\n".join(kept) + "\n"


def read_wheel(path: Path) -> dict:
    files = {}
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if info.filename in files:
                raise CombineError(f"{path.name}: duplicate member {info.filename}")
            files[info.filename] = zf.read(info)
    return files


def write_wheel(path: Path, files: dict) -> None:
    dist_info = {m.split("/")[0] for m in files if ".dist-info/" in m}
    if len(dist_info) != 1:
        raise CombineError(f"expected one dist-info directory, found {sorted(dist_info)}")
    record_name = f"{dist_info.pop()}/RECORD"
    files = dict(files)
    files[record_name] = build_record(files, record_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        # RECORD last, as in wheels written by the wheel package.
        for name in sorted(n for n in files if n != record_name):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, files[name])
        info = zipfile.ZipInfo(record_name, date_time=(2020, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        zf.writestr(info, files[record_name])
    tmp.replace(path)


def combine(wheels: list[Path], out_dir: Path, versions=DEFAULT_VERSIONS, extra_platforms=()) -> list[Path]:
    infos = []
    for w in wheels:
        info = parse_name(w)
        if "." in info["py"] or "." in info["abi"] or info["py"] != info["abi"] or info["py"] not in versions:
            raise CombineError(
                f"{w.name}: expected a single-interpreter wheel with one of {versions}, "
                f"got tag {info['py']}-{info['abi']}"
            )
        infos.append((info, w))
    for key in ("name", "version", "build", "plat"):
        values = {i[key] for i, _ in infos}
        if len(values) != 1:
            raise CombineError(f"input wheels differ in {key}: {sorted(map(str, values))}")
    got = sorted(i["py"] for i, _ in infos)
    if got != sorted(versions):
        missing = sorted(set(versions) - set(got))
        raise CombineError(f"need exactly one wheel per version {list(versions)}; got {got}; missing {missing}")

    infos.sort(key=lambda t: int(t[0]["py"][2:]))
    base_info, base_path = infos[0]
    base = read_wheel(base_path)

    def split(files: dict, tag: str, label: str):
        modules, other = {}, {}
        for name, data in files.items():
            mod = module_info(name)
            if mod:
                key, ver, free = mod
                if free:
                    raise CombineError(f"{label}: free-threaded module {name} is not supported")
                if ver != tag:
                    raise CombineError(f"{label}: module {name} is for {ver}, but the wheel is for {tag}")
                modules[key] = (name, data)
            elif is_unsuffixed_module(name):
                raise CombineError(f"{label}: native module {name} has no interpreter suffix")
            else:
                other[name] = data
        return modules, other

    base_modules, base_other = split(base, base_info["py"], base_path.name)
    if not base_modules:
        raise CombineError(f"{base_path.name}: holds no version-suffixed native module")

    merged = dict(base_other)
    all_modules = {tag: {} for tag in versions}
    for key, (name, data) in base_modules.items():
        all_modules[base_info["py"]][key] = (name, data)

    for info, path in infos[1:]:
        tag = info["py"]
        files = read_wheel(path)
        modules, other = split(files, tag, path.name)
        if set(modules) != set(base_modules):
            raise CombineError(
                f"{path.name}: native modules differ from {base_path.name}: "
                f"only here {sorted(set(modules) - set(base_modules))}, "
                f"only in base {sorted(set(base_modules) - set(modules))}"
            )
        if set(other) != set(base_other):
            raise CombineError(
                f"{path.name}: file list differs from {base_path.name}: "
                f"only here {sorted(set(other) - set(base_other))[:10]}, "
                f"only in base {sorted(set(base_other) - set(other))[:10]}"
            )
        for name, data in other.items():
            if data == base_other[name]:
                continue
            if _DIST_INFO_RE.match(name) and name.endswith(("/RECORD", "/WHEEL")):
                continue
            if _BUILD_OUTPUT_RE.search(name):
                continue
            raise CombineError(
                f"{path.name}: {name} differs from {base_path.name} but it is not a native build output"
            )
        all_modules[tag] = modules

    for tag in versions:
        for key, (name, data) in all_modules[tag].items():
            if name in merged:
                raise CombineError(f"duplicate member {name}")
            merged[name] = data

    py = ".".join(versions)
    tagged = {**base_info, "py": py, "abi": py}
    wheel_member = next(n for n in merged if _DIST_INFO_RE.match(n) and n.endswith("/WHEEL"))
    plats = [base_info["plat"], *extra_platforms]
    out = []
    for plat in plats:
        files = dict(merged)
        files[wheel_member] = rewrite_wheel_file(files[wheel_member].decode("utf-8"), py, py, plat).encode("utf-8")
        build = f"-{tagged['build']}" if tagged["build"] else ""
        target = out_dir / f"{tagged['name']}-{tagged['version']}{build}-{py}-{py}-{plat}.whl"
        write_wheel(target, files)
        out.append(target)
    return out


def check(path: Path, versions=DEFAULT_VERSIONS) -> list[str]:
    """Return the list of problems of a combined wheel; empty when it is sound."""
    problems: list[str] = []
    try:
        info = parse_name(path)
    except CombineError as exc:
        return [str(exc)]
    want = ".".join(versions)
    if info["py"] != want or info["abi"] != want:
        problems.append(f"{path.name}: tag is {info['py']}-{info['abi']}, expected {want}-{want}")
    try:
        files = read_wheel(path)
    except (zipfile.BadZipFile, CombineError) as exc:
        return problems + [f"{path.name}: {exc}"]

    # WHEEL tags
    wheel_members = [n for n in files if _DIST_INFO_RE.match(n) and n.endswith("/WHEEL")]
    record_members = [n for n in files if _DIST_INFO_RE.match(n) and n.endswith("/RECORD")]
    if len(wheel_members) != 1 or len(record_members) != 1:
        return problems + [f"{path.name}: needs exactly one WHEEL and one RECORD"]
    # Read the tags as pip does: as the headers of a mail message.
    tags = email.parser.Parser().parsestr(files[wheel_members[0]].decode("utf-8")).get_all("Tag", [])
    expected_tags = expand_tags(info["py"], info["abi"], info["plat"])
    if sorted(tags) != sorted(expected_tags):
        problems.append(f"{path.name}: WHEEL tags {sorted(tags)} differ from file name tags {sorted(expected_tags)}")

    # RECORD
    rows = list(csv.reader(io.StringIO(files[record_members[0]].decode("utf-8"))))
    recorded = {}
    for row in rows:
        if len(row) != 3:
            problems.append(f"{path.name}: bad RECORD row {row}")
            continue
        recorded[row[0]] = row
    for name, data in files.items():
        if name == record_members[0]:
            continue
        row = recorded.get(name)
        if row is None:
            problems.append(f"{path.name}: {name} is missing from RECORD")
        elif row != record_line(name, data):
            problems.append(f"{path.name}: RECORD hash or size of {name} is wrong")
    for name in recorded:
        if name not in files:
            problems.append(f"{path.name}: RECORD lists {name}, which is not in the wheel")

    # module suffix sets
    modules: dict = {}
    for name in files:
        mod = module_info(name)
        if mod:
            key, ver, free = mod
            if free:
                problems.append(f"{path.name}: free-threaded module {name}")
            modules.setdefault(key, []).append(ver)
        elif is_unsuffixed_module(name):
            problems.append(f"{path.name}: native module {name} has no interpreter suffix")
    if not modules:
        problems.append(f"{path.name}: holds no version-suffixed native module")
    for (directory, stem), vers in sorted(modules.items()):
        if sorted(vers) != sorted(versions):
            problems.append(
                f"{path.name}: module {directory}/{stem} has suffixes {sorted(vers)}, expected {list(versions)}"
            )
    return problems


def check_single(path: Path, python_tag: str) -> list[str]:
    """Return the problems of a one-interpreter wheel: every native module must carry its suffix."""
    problems: list[str] = []
    files = read_wheel(path)
    count = 0
    for name in files:
        mod = module_info(name)
        if mod:
            count += 1
            if mod[1] != python_tag or mod[2]:
                problems.append(f"{path.name}: module {name} is not for {python_tag}")
        elif is_unsuffixed_module(name):
            problems.append(f"{path.name}: native module {name} has no interpreter suffix")
    if count == 0:
        problems.append(f"{path.name}: holds no version-suffixed native module")
    return problems


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------


def _fake_wheel(out: Path, name: str, ver: str, plat: str, so: bool, extra=None, lib_bytes=None, drop=None):
    tag = ver
    suffix = (
        f".cpython-{ver[2:]}-x86_64-linux-gnu.so" if so else f".cp{ver[2:]}-win_amd64.pyd"
    )
    lib = "libovui.so" if so else "ovui.dll"
    files = {
        "omni/ui/__init__.py": b"x = 1\n",
        f"omni/ui/_ui{suffix}": f"ui-{ver}".encode(),
        f"omni/ui/_standalone{suffix}": f"sa-{ver}".encode(),
        f"omni/ui_scene/_scene{suffix}": f"sc-{ver}".encode(),
        f"omni/ui/{lib}": lib_bytes if lib_bytes is not None else f"lib-{ver}".encode(),
        f"{name}-1.0.dist-info/METADATA": b"Name: x\n",
        # A blank line ends the headers, as in the WHEEL file of a setuptools build.
        f"{name}-1.0.dist-info/WHEEL": f"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: {tag}-{tag}-{plat}\n\n".encode(),
    }
    files.update(extra or {})
    for d in drop or ():
        files.pop(d.replace("SUFFIX", suffix))
    path = out / f"{name}-1.0-{tag}-{tag}-{plat}.whl"
    write_wheel(path, files)
    return path


def selftest() -> int:
    failures = 0

    def expect(label, ok):
        nonlocal failures
        print(f"selftest: {label}: {'ok' if ok else 'FAILED'}")
        if not ok:
            failures += 1

    def raises(fn):
        try:
            fn()
        except CombineError:
            return True
        return False

    for so, plat in ((True, "linux_x86_64"), (False, "win_amd64")):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            ins = tmp / "in"
            wheels = [_fake_wheel(ins, "ovui", v, plat, so) for v in DEFAULT_VERSIONS]
            extra = ["manylinux_2_35_x86_64"] if so else []
            outs = combine(wheels, tmp / "out", extra_platforms=extra)
            expect(f"{plat}: combine writes {len(extra) + 1} wheel(s)", len(outs) == len(extra) + 1)
            for o in outs:
                expect(f"{plat}: {o.name} passes check", check(o) == [])
            names = {n for n in read_wheel(outs[0])}
            suffixed = [n for n in names if module_info(n)]
            expect(f"{plat}: 3 modules x 4 suffixes", len(suffixed) == 12)
            wheel_text = read_wheel(outs[0])[next(n for n in names if n.endswith(".dist-info/WHEEL"))].decode()
            parsed = email.parser.Parser().parsestr(wheel_text).get_all("Tag", [])
            expect(f"{plat}: a header parser reads all 16 tags", len(parsed) == 16)
            lib = "omni/ui/libovui.so" if so else "omni/ui/ovui.dll"
            expect(f"{plat}: shared library comes from the base wheel once",
                   read_wheel(outs[0])[lib] == b"lib-cp312")

            # the combined wheel loses a module of one version
            files = read_wheel(outs[0])
            victim = next(n for n in files if "cp315" in n or "cpython-315" in n)
            del files[victim]
            bad = tmp / "bad" / outs[0].name
            write_wheel(bad, files)
            expect(f"{plat}: check rejects a missing 3.15 module", any("suffixes" in p for p in check(bad)))

            # the RECORD no longer matches
            files = read_wheel(outs[0])
            files["omni/ui/__init__.py"] = b"x = 2\n"
            raw = tmp / "raw.whl"
            with zipfile.ZipFile(outs[0]) as src, zipfile.ZipFile(raw, "w") as dst:
                for info in src.infolist():
                    data = files[info.filename] if info.filename in files else src.read(info)
                    dst.writestr(info.filename, data)
            tampered = tmp / "tampered" / outs[0].name
            tampered.parent.mkdir()
            raw.replace(tampered)
            expect(f"{plat}: check rejects a changed file", any("RECORD hash" in p for p in check(tampered)))

            # tags after a blank line are invisible to pip check
            files = read_wheel(outs[0])
            wname = next(n for n in files if n.endswith(".dist-info/WHEEL"))
            files[wname] = files[wname].replace(b"Tag:", b"\nTag:", 1)
            hidden = tmp / "hidden" / outs[0].name
            write_wheel(hidden, files)
            expect(f"{plat}: check rejects WHEEL tags behind a blank line", any("WHEEL tags" in p for p in check(hidden)))

            # a single-version wheel is not a combined wheel
            expect(f"{plat}: check rejects a single-version wheel", check(wheels[0]) != [])

            # the missing version
            expect(f"{plat}: combine rejects a missing version",
                   raises(lambda: combine(wheels[:3], tmp / "o2", extra_platforms=extra)))
            # a different pure Python file
            changed = _fake_wheel(tmp / "in2", "ovui", "cp314", plat, so, extra={"omni/ui/__init__.py": b"x = 9\n"})
            mixed = [wheels[0], wheels[1], changed, wheels[3]]
            expect(f"{plat}: combine rejects a changed Python file",
                   raises(lambda: combine(mixed, tmp / "o3")))
            # a debug build: the PDB of a shared library differs in every build and
            # comes from the base wheel, like the library it belongs to
            symbols = [_fake_wheel(tmp / "in6", "ovui", v, plat, so, extra={"omni/ui/omni.ui.pdb": f"pdb-{v}".encode()})
                       for v in DEFAULT_VERSIONS]
            with_pdb = read_wheel(combine(symbols, tmp / "o7", extra_platforms=extra)[0])
            expect(f"{plat}: a debug symbol file comes from the base wheel",
                   with_pdb.get("omni/ui/omni.ui.pdb") == b"pdb-cp312")
            # an extra file in one wheel
            extra_file = _fake_wheel(tmp / "in3", "ovui", "cp313", plat, so, extra={"omni/ui/new.py": b""})
            expect(f"{plat}: combine rejects a file only one wheel has",
                   raises(lambda: combine([wheels[0], extra_file, wheels[2], wheels[3]], tmp / "o4")))
            # a module only one wheel has
            fewer = _fake_wheel(tmp / "in4", "ovui", "cp313", plat, so, drop=["omni/ui/_standalone" + "SUFFIX"])
            expect(f"{plat}: combine rejects a module only some wheels have",
                   raises(lambda: combine([wheels[0], fewer, wheels[2], wheels[3]], tmp / "o5")))
            # different platform
            other = _fake_wheel(tmp / "in5", "ovui", "cp313", "linux_aarch64" if so else "win32", so)
            expect(f"{plat}: combine rejects mixed platforms",
                   raises(lambda: combine([wheels[0], other, wheels[2], wheels[3]], tmp / "o6")))

    print()
    if failures:
        print(f"SELFTEST FAILED: {failures} check(s)", file=sys.stderr)
        return 1
    print("SELFTEST OK")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("combine", help="merge one wheel per interpreter into one combined wheel")
    pc.add_argument("wheels", nargs="+", type=Path)
    pc.add_argument("--out-dir", required=True, type=Path)
    pc.add_argument("--versions", default=",".join(DEFAULT_VERSIONS))
    pc.add_argument("--also-platform", action="append", default=[],
                    help="write one more wheel with this platform tag (for example the manylinux name)")

    pk = sub.add_parser("check", help="verify combined wheels")
    pk.add_argument("wheels", nargs="+", type=Path)
    pk.add_argument("--versions", default=",".join(DEFAULT_VERSIONS))

    pm = sub.add_parser("modules", help="verify the native modules of a one-interpreter wheel")
    pm.add_argument("wheels", nargs="+", type=Path)
    pm.add_argument("--python-tag", required=True, help="for example cp313")

    sub.add_parser("selftest", help="prove the checks accept good input and reject bad input")

    args = parser.parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    versions = tuple(v for v in getattr(args, "versions", ",".join(DEFAULT_VERSIONS)).split(",") if v)
    try:
        if args.cmd == "combine":
            for out in combine(args.wheels, args.out_dir, versions, args.also_platform):
                print(f"wrote {out}")
                problems = check(out, versions)
                if problems:
                    print("\n".join(problems), file=sys.stderr)
                    return 1
            return 0
        failed = 0
        for wheel in args.wheels:
            problems = check_single(wheel, args.python_tag) if args.cmd == "modules" else check(wheel, versions)
            if problems:
                failed += 1
                print("\n".join(f"::error title=Combined wheel::{p}" for p in problems), file=sys.stderr)
            else:
                print(f"OK: {wheel.name}")
        return 1 if failed else 0
    except CombineError as exc:
        print(f"::error title=Combined wheel::{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

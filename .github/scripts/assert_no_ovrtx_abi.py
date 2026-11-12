#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fail if a built `ovui` wheel carries the ovrtx ABI or needs ovrtx to build.

`ovui` does not depend on ovrtx. Everything that calls a renderer lives in a
separate package and fills ovui's renderer slot
(``_set_native_frame_pacing_hooks``) at start-up, so no ovrtx header, symbol,
library search or install requirement belongs in the `ovui` product.

This checks the artifact rather than the build configuration, because the
`ovrtx` wheel that CI installs for other packages puts the headers on the
machine; only the built wheel shows what actually shipped.

The bare word "ovrtx" is allowed in documents that ship with the wheel, such
as the license notices and the bundled agent skills. What is checked is
the ABI itself - the C entry points ovui used to call, the headers it used to
include, the build switches that found them, and an ovrtx requirement in the
wheel metadata.

Usage:
    python .github/scripts/assert_no_ovrtx_abi.py <wheel> [<wheel> ...]
"""

import re
import sys
import zipfile
from pathlib import Path

# The C entry points of the renderer, the headers that declare them, the build
# switches that used to find those headers, and the library-search hints.
ABI_TOKENS = (
    rb"ovrtx_get_version",
    rb"ovrtx_query_extension",
    rb"ovrtx_write_attribute",
    rb"ovrtx_step\b",
    rb"ovrtx_wait_op",
    rb"ovrtx_fetch_results",
    rb"ovrtx_map_render_var_output",
    rb"ovrtx_unmap_render_var_output",
    rb"ovrtx_destroy_results",
    rb"ovrtx_get_last_error",
    rb"ovrtx_renderer_t",
    rb"ovrtx_step_result_handle_t",
    rb"ovrtx_render_product_set_outputs_t",
    rb"ovrtx/ovrtx\.h",
    rb"ovrtx/ovrtx_types\.h",
    rb"OMNIUI_HAS_OVRTX_FRAME_PACING",
    rb"OMNIUI_OVRTX_INCLUDE_DIR",
    rb"OMNIUI_OVRTX_FRAME_PACING_CAPABLE",
    rb"OVRTX_INCLUDE_DIR",
)
TOKEN = re.compile(rb"|".join(ABI_TOKENS))

REQUIREMENT = re.compile(rb"^Requires-Dist:\s*(ovrtx|ovstage)\b", re.IGNORECASE | re.MULTILINE)

# How much of each hit to show, so a failure names the offending text rather
# than only counting it.
CONTEXT = 60
MAX_SHOWN = 6


def _samples(blob: bytes) -> list[str]:
    seen: list[str] = []
    for match in TOKEN.finditer(blob):
        start = max(0, match.start() - CONTEXT // 2)
        chunk = blob[start : match.end() + CONTEXT // 2]
        text = chunk.decode("utf-8", "replace")
        text = "".join(c if c.isprintable() else " " for c in text).strip()
        text = " ".join(text.split())
        if text not in seen:
            seen.append(text)
        if len(seen) >= MAX_SHOWN:
            break
    return seen


def check_wheel(path: Path) -> list[str]:
    offenders = []
    with zipfile.ZipFile(path) as zf:
        members = zf.namelist()
        if not members:
            raise SystemExit(f"{path}: the wheel is empty")
        for name in members:
            blob = zf.read(name)
            if name.endswith(".dist-info/METADATA"):
                for requirement in REQUIREMENT.findall(blob):
                    offenders.append(
                        f"{name}: Requires-Dist on {requirement.decode()}"
                    )
            count = len(TOKEN.findall(blob))
            if not count:
                continue
            lines = [f"{name}: {count} ABI reference(s)"]
            lines += [f"    ...{s}..." for s in _samples(blob)]
            offenders.append("\n".join(lines))
        print(f"{path.name}: scanned {len(members)} member(s)")
    return offenders


def main(argv: list[str]) -> int:
    wheels = [Path(a) for a in argv]
    if not wheels:
        raise SystemExit("usage: assert_no_ovrtx_abi.py <wheel> [<wheel> ...]")

    failed = False
    for wheel in wheels:
        if not wheel.is_file():
            raise SystemExit(f"{wheel}: not a file")
        offenders = check_wheel(wheel)
        if offenders:
            failed = True
            print(f"ERROR: {wheel.name} carries the ovrtx ABI:")
            for entry in offenders:
                print(f"  {entry}")

    if failed:
        print(
            "\novui does not depend on ovrtx. Move the renderer call into the "
            "package that owns it -- it fills ovui's renderer slot with "
            "_set_native_frame_pacing_hooks at start-up -- or drop it."
        )
        return 1

    print("OK: no ovrtx ABI in the built wheel(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

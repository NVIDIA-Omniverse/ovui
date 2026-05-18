#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Build clean 2-panel side-by-side PNGs for every (oracle, SUT) pair.

Output: markdown/quality_harness/artifacts/diff/<name>.sxs.png — panels capped
at 640 px wide each so the total stays ≤ 2000 px (640+12+640 = 1292).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

HARNESS = Path(__file__).resolve().parents[1]
ORACLE = HARNESS / "artifacts" / "oracle"
SUT = HARNESS / "artifacts" / "sut"
DIFF = HARNESS / "artifacts" / "diff"

PANEL_W = 640
BAR_W = 12


def _pair(ora_path: Path, sut_path: Path, out: Path) -> None:
    o = Image.open(ora_path).convert("RGB")
    s = Image.open(sut_path).convert("RGB")
    oh = int(round(o.height * PANEL_W / o.width))
    sh = int(round(s.height * PANEL_W / s.width))
    o = o.resize((PANEL_W, oh), Image.LANCZOS)
    s = s.resize((PANEL_W, sh), Image.LANCZOS)
    H = max(oh, sh)

    def pad(im: Image.Image) -> np.ndarray:
        a = np.asarray(im)
        if a.shape[0] >= H:
            return a
        # Sample the panel's own background colour so dark-theme panels
        # don't get a jarring white footer.
        bg_sample = a[min(20, a.shape[0] - 1), a.shape[1] // 2]
        bg = np.full((H - a.shape[0], a.shape[1], 3), bg_sample, dtype=np.uint8)
        return np.concatenate([a, bg], axis=0)

    oa = pad(o)
    sa = pad(s)
    # Divider colour: a neutral mid-gray that reads on either bg.
    bar = np.full((H, BAR_W, 3), 128, dtype=np.uint8)
    side = np.concatenate([oa, bar, sa], axis=1)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(side).save(out)


def main(argv: list[str]) -> int:
    theme_filter = argv[1] if len(argv) > 1 else None
    file_filter = argv[2] if len(argv) > 2 else None

    pairs = []
    for ora in sorted(ORACLE.rglob("*.png")):
        rel = ora.relative_to(ORACLE)
        theme = rel.parts[0]
        if theme_filter and theme != theme_filter:
            continue
        name = rel.with_suffix("").as_posix()
        if file_filter and file_filter not in name:
            continue
        sut = SUT / rel
        if not sut.exists():
            continue
        out = DIFF / f"{name.replace('/', '__')}.sxs.png"
        pairs.append((name, ora, sut, out))

    if not pairs:
        print("no pairs", file=sys.stderr)
        return 1

    for name, ora, sut, out in pairs:
        _pair(ora, sut, out)
        print(f"  {name}: {out.relative_to(HARNESS)}")
    print(f"\n{len(pairs)} side-by-sides written.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

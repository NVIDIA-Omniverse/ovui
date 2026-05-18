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

"""Diff pipeline — compare artifacts/oracle/*.png vs artifacts/sut/*.png.

Produces:
  * artifacts/diff/<name>.side_by_side.png  — oracle | sut | |diff| panels
  * artifacts/diff/<name>.heatmap.png       — per-pixel absolute difference
  * tracker/results.json                    — per-marker metrics (SSIM,
                                              pixel difference fraction, dims)

Metrics (intentionally simple for the first iteration; LPIPS/CLIP can be
added behind a flag once the pipeline produces usable SUT PNGs):
  * resize the smaller PNG up to the larger's size (nearest) before
    comparison so mismatched viewport heights don't blow up the metric
  * pixel_diff_fraction  = fraction of pixels with |delta| > 8 in any channel
  * ssim                 = skimage structural similarity on luma
  * max_delta, mean_delta

Usage:
    python3 markdown/quality_harness/scripts/compare.py            # diff everything
    python3 markdown/quality_harness/scripts/compare.py atoms/03_bold
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
ORACLE = HARNESS / "artifacts" / "oracle"
SUT = HARNESS / "artifacts" / "sut"
DIFF = HARNESS / "artifacts" / "diff"
TRACKER = HARNESS / "tracker" / "results.json"


@dataclass
class Metrics:
    name: str
    oracle_png: str
    sut_png: str
    width: int
    height: int
    pixel_diff_fraction: float
    ssim: float
    mean_delta: float
    max_delta: int


def _discover_pairs(filter_arg: str | None) -> list[tuple[str, Path, Path]]:
    pairs: list[tuple[str, Path, Path]] = []
    for ora in sorted(ORACLE.rglob("*.png")):
        rel = ora.relative_to(ORACLE)
        name = rel.with_suffix("").as_posix()
        if filter_arg and not name.startswith(filter_arg):
            continue
        sut = SUT / rel
        pairs.append((name, ora, sut))
    return pairs


def _compare_one(name: str, oracle_png: Path, sut_png: Path) -> Metrics | None:
    try:
        import numpy as np
        from PIL import Image
        from skimage.metrics import structural_similarity as ssim
    except ImportError as exc:  # pragma: no cover - scaffold branch
        raise SystemExit(
            "diff/compare.py requires numpy, Pillow, and scikit-image.\n"
            f"Install with: pip install numpy Pillow scikit-image\n(reason: {exc})"
        )

    if not sut_png.exists():
        print(f"  · {name}: no SUT render yet (skipping)")
        return None

    ora_img = Image.open(oracle_png).convert("RGB")
    sut_img = Image.open(sut_png).convert("RGB")

    # Oracle renders at device_scale=2 (2048 wide) and SUT at native 1× (1024
    # wide). Downscale the oracle to the SUT's width so the two can be
    # compared pixel-for-pixel; crop both to the shorter height.
    if ora_img.width != sut_img.width:
        ratio = sut_img.width / ora_img.width
        ora_img = ora_img.resize(
            (sut_img.width, int(ora_img.height * ratio)),
            Image.LANCZOS,
        )

    ora = np.array(ora_img)
    sut = np.array(sut_img)
    h = min(ora.shape[0], sut.shape[0])
    w = min(ora.shape[1], sut.shape[1])
    ora_c = ora[:h, :w]
    sut_c = sut[:h, :w]

    delta = np.abs(ora_c.astype(np.int16) - sut_c.astype(np.int16))
    diff_fraction = float((delta.max(axis=2) > 8).mean())
    mean_delta = float(delta.mean())
    max_delta = int(delta.max())
    s = float(ssim(ora_c, sut_c, channel_axis=2, data_range=255))

    # Side-by-side composition
    # Harness caps images at 2000 px; three panels + two 8-px bars must fit.
    # Cap each panel at 640 px wide => 640*3 + 16 = 1936 px. If the source is
    # already narrower than 640, leave it alone.
    DIFF.mkdir(parents=True, exist_ok=True)
    heat = (delta.max(axis=2) * 3).clip(0, 255).astype(np.uint8)
    heat_rgb = np.stack([heat, np.zeros_like(heat), np.zeros_like(heat)], axis=2)

    PANEL_MAX_W = 640
    PANEL_MAX_H = 1600
    if w > PANEL_MAX_W or h > PANEL_MAX_H:
        scale = min(PANEL_MAX_W / w, PANEL_MAX_H / h)
        tw = max(1, int(round(w * scale)))
        th = max(1, int(round(h * scale)))
        ora_p = np.array(Image.fromarray(ora_c).resize((tw, th), Image.LANCZOS))
        sut_p = np.array(Image.fromarray(sut_c).resize((tw, th), Image.LANCZOS))
        heat_p = np.array(Image.fromarray(heat_rgb).resize((tw, th), Image.NEAREST))
    else:
        ora_p, sut_p, heat_p = ora_c, sut_c, heat_rgb

    bar = np.full((ora_p.shape[0], 8, 3), 255, dtype=np.uint8)
    side = np.concatenate([ora_p, bar, sut_p, bar, heat_p], axis=1)
    Image.fromarray(side).save(DIFF / f"{name.replace('/', '__')}.side_by_side.png")
    Image.fromarray(heat_rgb).save(DIFF / f"{name.replace('/', '__')}.heatmap.png")

    return Metrics(
        name=name,
        oracle_png=str(oracle_png.relative_to(HARNESS)),
        sut_png=str(sut_png.relative_to(HARNESS)),
        width=w,
        height=h,
        pixel_diff_fraction=round(diff_fraction, 6),
        ssim=round(s, 6),
        mean_delta=round(mean_delta, 4),
        max_delta=max_delta,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("filter", nargs="?")
    args = ap.parse_args()

    pairs = _discover_pairs(args.filter)
    if not pairs:
        print("No oracle PNGs found — run render_oracle.py first.")
        return 1

    results: list[Metrics] = []
    for name, ora, sut in pairs:
        m = _compare_one(name, ora, sut)
        if m is not None:
            results.append(m)
            print(
                f"  {name}: ssim={m.ssim:.3f}  diff_frac={m.pixel_diff_fraction:.3f}  "
                f"mean_delta={m.mean_delta:.2f}"
            )

    TRACKER.parent.mkdir(parents=True, exist_ok=True)
    TRACKER.write_text(
        json.dumps([asdict(r) for r in results], indent=2, sort_keys=True)
    )
    print(f"\nWrote {len(results)} result rows to {TRACKER.relative_to(HARNESS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

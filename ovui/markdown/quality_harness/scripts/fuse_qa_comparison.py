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

"""Fuse ground-truth and ovui QA renders into side-by-side comparison images.

Reads:   markdown/quality_harness/artifacts/qa_ground_truth/*.png
         markdown/quality_harness/artifacts/qa_ovui/*.png
Writes:  markdown/quality_harness/artifacts/qa_comparison/*.png

Layout: a header strip labelling each side, then the two images placed at
the top-left of each column.  Columns are padded to the same height so
side-by-side reading lines up.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HARNESS = Path(__file__).resolve().parents[1]
GT_DIR = HARNESS / "artifacts" / "qa_ground_truth"
OV_DIR = HARNESS / "artifacts" / "qa_ovui"
OUT_DIR = HARNESS / "artifacts" / "qa_comparison"
OUT_DIR.mkdir(parents=True, exist_ok=True)

GUTTER = 12
HEADER_H = 36
BG = (22, 22, 22)
DIVIDER = (80, 80, 80)

BLUE = (120, 180, 255)
ORANGE = (255, 165, 64)


def _font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def fuse(gt_path: Path, ov_path: Path, out_path: Path) -> None:
    gt = Image.open(gt_path).convert("RGB")
    ov = Image.open(ov_path).convert("RGB")

    # Normalise widths so both columns share the same width.
    col_w = max(gt.width, ov.width)

    # Content height is the taller of the two, so neither side crops.
    content_h = max(gt.height, ov.height)
    total_h = HEADER_H + content_h
    total_w = col_w * 2 + GUTTER * 3

    canvas = Image.new("RGB", (total_w, total_h), BG)
    draw = ImageDraw.Draw(canvas)
    font = _font(14)

    # Header strip.
    draw.rectangle([0, 0, total_w, HEADER_H], fill=(14, 14, 14))
    draw.text((GUTTER + 6, 10), "GROUND TRUTH (HTML)", fill=BLUE, font=font)
    draw.text((GUTTER * 2 + col_w + 6, 10), "ovui WIDGET", fill=ORANGE, font=font)

    # Vertical divider between columns.
    x_div = GUTTER + col_w + GUTTER // 2
    draw.line([(x_div, 0), (x_div, total_h)], fill=DIVIDER, width=1)

    # Paste images (centered horizontally within their columns).
    canvas.paste(gt, (GUTTER + (col_w - gt.width) // 2, HEADER_H))
    canvas.paste(ov, (GUTTER * 2 + col_w + (col_w - ov.width) // 2, HEADER_H))

    canvas.save(out_path, "PNG")
    print(f"  {gt_path.name} + {ov_path.name} -> {out_path.name}  ({canvas.size})")


def main() -> int:
    gts = sorted(GT_DIR.glob("*.png"))
    if not gts:
        print(f"No ground-truth renders in {GT_DIR}", file=sys.stderr)
        return 1
    print(f"Fusing {len(gts)} comparisons into {OUT_DIR}")
    for gt in gts:
        ov = OV_DIR / gt.name
        if not ov.exists():
            print(f"  SKIP {gt.name}: missing {ov}", file=sys.stderr)
            continue
        out = OUT_DIR / gt.name
        fuse(gt, ov, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

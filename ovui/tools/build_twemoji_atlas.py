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

"""
Build a Twemoji sprite atlas from individual PNG files.

Downloads Twemoji PNGs if needed, resizes to cell_size, packs into a
single RGBA atlas PNG, and emits a JSON manifest mapping Unicode
codepoint sequences to grid positions.

Usage:
    python tools/build_twemoji_atlas.py \
        --twemoji-dir third_party/twemoji/assets/72x72 \
        --output-atlas resources/twemoji-atlas.png \
        --output-manifest resources/twemoji-atlas.json \
        --cell-size 32 \
        --atlas-size 2048

If --twemoji-dir does not exist, the script downloads Twemoji v15.1
from GitHub into that directory.
"""

import argparse
import json
import os
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image


def download_twemoji(target_dir: Path) -> None:
    """Download and extract Twemoji 72x72 PNGs from GitHub."""
    url = "https://github.com/jdecked/twemoji/archive/refs/tags/v16.0.1.zip"
    print(f"Downloading Twemoji from {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "build-twemoji-atlas"})
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        with urllib.request.urlopen(req, timeout=120) as resp:
            tmp.write(resp.read())
        tmp_path = tmp.name

    target_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(tmp_path) as zf:
        prefixes = [
            "twemoji-16.0.1/assets/72x72/",
            "twemoji-16.0.1/assets/72x72/",
        ]
        count = 0
        for info in zf.infolist():
            for prefix in prefixes:
                if info.filename.startswith(prefix) and info.filename.endswith(".png"):
                    basename = os.path.basename(info.filename)
                    data = zf.read(info.filename)
                    (target_dir / basename).write_bytes(data)
                    count += 1
                    break
        print(f"Extracted {count} PNGs to {target_dir}")

    os.unlink(tmp_path)


def build_atlas(
    twemoji_dir: Path,
    output_atlas: Path,
    output_manifest: Path,
    cell_size: int = 32,
    atlas_size: int = 2048,
) -> None:
    cols = atlas_size // cell_size
    max_slots = cols * cols

    pngs = sorted(twemoji_dir.glob("*.png"))
    if not pngs:
        print(f"ERROR: No PNG files found in {twemoji_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(pngs)} emoji PNGs, atlas grid {cols}x{cols} = {max_slots} slots")
    if len(pngs) > max_slots:
        print(f"WARNING: {len(pngs)} glyphs but only {max_slots} slots — truncating")
        pngs = pngs[:max_slots]

    atlas = Image.new("RGBA", (atlas_size, atlas_size), (0, 0, 0, 0))
    glyphs = {}

    for idx, png_path in enumerate(pngs):
        codepoint_str = png_path.stem  # e.g. "1f600" or "1f468-200d-1f4bb"
        row = idx // cols
        col = idx % cols

        try:
            img = Image.open(png_path).convert("RGBA")
        except Exception as e:
            print(f"  skip {png_path.name}: {e}")
            continue

        img = img.resize((cell_size, cell_size), Image.LANCZOS)
        x = col * cell_size
        y = row * cell_size
        atlas.paste(img, (x, y))
        glyphs[codepoint_str] = {"row": row, "col": col}

    output_atlas.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(str(output_atlas), "PNG")
    print(f"Atlas saved: {output_atlas} ({atlas_size}x{atlas_size})")

    manifest = {
        "version": "15.1",
        "cellSize": cell_size,
        "atlasSize": atlas_size,
        "cols": cols,
        "glyphs": glyphs,
    }
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    with open(output_manifest, "w") as f:
        json.dump(manifest, f, separators=(",", ":"))
    print(f"Manifest saved: {output_manifest} ({len(glyphs)} glyphs)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Twemoji sprite atlas")
    parser.add_argument(
        "--twemoji-dir",
        type=Path,
        default=Path("third_party/twemoji/assets/72x72"),
        help="Directory containing 72x72 Twemoji PNGs",
    )
    parser.add_argument(
        "--output-atlas",
        type=Path,
        default=Path("resources/twemoji-atlas.png"),
        help="Output atlas PNG path",
    )
    parser.add_argument(
        "--output-manifest",
        type=Path,
        default=Path("resources/twemoji-atlas.json"),
        help="Output JSON manifest path",
    )
    parser.add_argument("--cell-size", type=int, default=32)
    parser.add_argument("--atlas-size", type=int, default=2048)
    args = parser.parse_args()

    if not args.twemoji_dir.exists():
        download_twemoji(args.twemoji_dir)

    build_atlas(
        args.twemoji_dir,
        args.output_atlas,
        args.output_manifest,
        args.cell_size,
        args.atlas_size,
    )


if __name__ == "__main__":
    main()

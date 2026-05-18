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

"""Render the QA markdown corpus through the native ovui MarkdownWidget.

Requires a virtual X display large enough to fit the full document in a
single non-scrolling window.  Start one at DISPLAY=:100 via

    Xvfb :100 -screen 0 1024x2400x24 &

Then run:  DISPLAY=:100 PYTHONPATH=python:build/bindings python3
markdown/quality_harness/scripts/generate_qa_ovui.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image

HARNESS = Path(__file__).resolve().parents[1]
SRC_DIR = HARNESS / "corpus" / "qa"
OUT_DIR = HARNESS / "artifacts" / "qa_ovui"
OUT_DIR.mkdir(parents=True, exist_ok=True)

WIDTH = 760
HEIGHT = 2300  # headroom for the tallest doc; final image is bottom-trimmed.


# The rendering must happen in a *fresh* Python process per markdown file
# because omni.ui holds global ImGui / window state that can't be reset
# cleanly between captures.  This module writes a tiny runner script via
# its subprocess helper and invokes it N times.

RUNNER_SOURCE = r"""
import os, sys
from pathlib import Path
import omni.ui as ui

SRC_PATH = Path(sys.argv[1])
OUT_PATH = Path(sys.argv[2])
WIDTH = int(sys.argv[3])
HEIGHT = int(sys.argv[4])

ui.init("QA", width=WIDTH, height=HEIGHT)

source = SRC_PATH.read_text(encoding="utf-8")

win = ui.Window(
    "QA",
    width=WIDTH, height=HEIGHT,
    flags=ui.WINDOW_FLAGS_NO_SCROLLBAR | ui.WINDOW_FLAGS_NO_RESIZE,
)
with win.frame:
    ui.MarkdownWidget(source)


async def capture() -> None:
    from omni.ui import testing
    # Extra warmup frames -- tables and code blocks need a measurement pass
    # to settle column widths at full document width.
    await testing.wait_frames(15)
    testing.capture_screenshot(str(OUT_PATH))


ui.run(capture())
"""


def _trim_bottom(img: Image.Image, margin: int = 16, edge_ignore: int = 8) -> Image.Image:
    """Crop uniform background rows at the bottom, ignoring any frame border.

    The ImGui window has a 1-2 px bottom border that would otherwise fool the
    'is this row uniform' check; skip the last *edge_ignore* rows first.
    """
    px = img.load()
    w, h = img.size
    last_content = 0
    start = max(0, h - edge_ignore - 1)
    for y in range(start, -1, -1):
        # Find the first x that is not a left-edge frame border.
        first = px[4, y][:3]
        row_uniform = True
        for x in range(8, w - 8, 4):
            r, g, b = px[x, y][:3]
            if abs(r - first[0]) + abs(g - first[1]) + abs(b - first[2]) > 6:
                row_uniform = False
                break
        if not row_uniform:
            last_content = y
            break
    keep = min(h, last_content + margin)
    if keep >= h:
        return img
    return img.crop((0, 0, w, keep))


def render_file(md_path: Path, out_png: Path, *, keep_display: str | None) -> None:
    env = dict(**_env_for_subprocess(keep_display))
    runner = Path("/tmp/_qa_ovui_runner.py")
    runner.write_text(RUNNER_SOURCE)
    cmd = [
        sys.executable, str(runner),
        str(md_path), str(out_png),
        str(WIDTH), str(HEIGHT),
    ]
    res = subprocess.run(cmd, env=env, cwd=str(REPO), capture_output=True, text=True, timeout=60)
    # The standalone runner occasionally segfaults on shutdown AFTER writing
    # the screenshot.  Treat a valid output file as success; only fail when
    # the screenshot is missing or truncated.
    if not out_png.exists() or out_png.stat().st_size < 1024:
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)
        print("RETURN CODE:", res.returncode)
        raise RuntimeError(f"ovui render failed for {md_path}")

    img = Image.open(out_png).convert("RGB")
    # Strip the ImGui title bar (approx 26 px) and the 1px left/right frame
    # borders so the widget render aligns with the HTML ground truth.
    w, h = img.size
    img = img.crop((1, 26, w - 1, h))
    img = _trim_bottom(img)
    img.save(out_png)
    print(f"  {md_path.name} -> {out_png.name}  ({img.size})")


def _env_for_subprocess(keep_display: str | None) -> dict[str, str]:
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = "python:build/bindings"
    if keep_display:
        env["DISPLAY"] = keep_display
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--display", default=None, help="X display to use (default: inherit $DISPLAY)")
    ap.add_argument("--only", default=None, help="only render this filename stem")
    args = ap.parse_args()

    mds = sorted(SRC_DIR.glob("*.md"))
    if args.only:
        mds = [p for p in mds if p.stem == args.only]
    if not mds:
        print(f"No markdown files in {SRC_DIR}", file=sys.stderr)
        return 1

    print(f"Rendering {len(mds)} ovui widget screenshots into {OUT_DIR}")
    for md_path in mds:
        out_png = OUT_DIR / (md_path.stem + ".png")
        render_file(md_path, out_png, keep_display=args.display)
    return 0


if __name__ == "__main__":
    sys.exit(main())

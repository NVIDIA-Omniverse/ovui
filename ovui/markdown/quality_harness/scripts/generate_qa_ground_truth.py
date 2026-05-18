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

"""Render the QA markdown corpus to PNG ground-truth images.

Pipeline: markdown -> HTML (python-markdown) -> PDF (weasyprint) -> PNG (pymupdf).

Dark-theme CSS matches the ovui MarkdownWidget defaults (see
core/src/markdown/RenderConfig.h).  Output width is 760px at 2x DPI for crisp
comparison; the PNGs are then downscaled to 760px wide.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import fitz  # pymupdf
import markdown as md
import weasyprint
from PIL import Image

HARNESS = Path(__file__).resolve().parents[1]
SRC_DIR = HARNESS / "corpus" / "qa"
OUT_DIR = HARNESS / "artifacts" / "qa_ground_truth"
OUT_DIR.mkdir(parents=True, exist_ok=True)

WIDTH_PX = 760
# WeasyPrint uses CSS pixels at 96 DPI.  Render at 2x then resize down.
SCALE = 2

CSS = r"""
@page {
    size: 760px auto;
    margin: 16px 20px;
    background: #1e1e1e;
}
html, body {
    background: #1e1e1e;
    color: #dcdcdc;
    font-family: "DejaVu Sans", "Arial", sans-serif;
    font-size: 14px;
    line-height: 1.45;
    margin: 0;
    padding: 0;
}
h1 { font-size: 28px; color: #ffffff; margin: 14px 0 6px 0; font-weight: 700; }
h2 { font-size: 24px; color: #ffffff; margin: 12px 0 6px 0; font-weight: 700; }
h3 { font-size: 20px; color: #ffffff; margin: 10px 0 5px 0; font-weight: 700; }
h4 { font-size: 18px; color: #ffffff; margin: 10px 0 5px 0; font-weight: 700; }
h5 { font-size: 16px; color: #ffffff; margin: 8px 0 4px 0;  font-weight: 700; }
h6 { font-size: 14px; color: #ffffff; margin: 8px 0 4px 0;  font-weight: 700; }
p  { margin: 0 0 6px 0; }
strong { font-weight: 700; color: #ffffff; }
em     { font-style: italic; color: #dcdcdc; }
del    { text-decoration: line-through; color: #dcdcdc; }
a      { color: #6699ff; text-decoration: underline; }
code {
    font-family: "DejaVu Sans Mono", "Courier New", monospace;
    font-size: 13px;
    background: #282828;
    color: #e6c8b4;
    padding: 0 3px;
    border-radius: 3px;
}
pre {
    background: #1e1e1e;
    border: 1px solid #464646;
    border-radius: 4px;
    padding: 6px 8px;
    overflow-x: hidden;
    margin: 6px 0;
}
pre code {
    background: transparent;
    padding: 0;
    border-radius: 0;
    color: #e6c8b4;
    white-space: pre-wrap;
    word-break: break-word;
}
blockquote {
    border-left: 3px solid #787878;
    background: rgba(40, 50, 60, 0.31);
    margin: 6px 0;
    padding: 2px 12px;
    color: #b4b4b4;
}
hr {
    border: none;
    border-top: 1px solid #505050;
    margin: 6px 0;
}
ul, ol {
    margin: 2px 0 6px 0;
    padding-left: 26px;
}
li { margin: 1px 0; }
li > p { margin: 0 0 4px 0; }
table {
    border-collapse: collapse;
    margin: 6px 0;
    width: 100%;
    border: 1px solid #505050;
}
th, td {
    border: 1px solid #505050;
    padding: 6px 8px;
    text-align: left;
    vertical-align: top;
}
th { background: #323232; color: #ffffff; font-weight: 700; }
tr:nth-child(even) td { background: #282828; }
tr:nth-child(odd)  td { background: #1e1e1e; }
img {
    max-width: 100%;
    border: 1px solid #5a5a5a;
    background: #323232;
    padding: 40px;
    color: #a0a0a0;
    font-size: 12px;
}
input[type="checkbox"] {
    margin-right: 4px;
}
/* Task-list checkboxes (python-markdown gfm extension renders them this way). */
ul.task-list { list-style: none; padding-left: 18px; }
li.task-list-item { margin-left: 0; }
"""


_STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)
_TASK_RE = re.compile(r"^(\s*[-*+]\s+)\[([ xX])\]\s+", re.MULTILINE)


def _pre(src: str) -> str:
    # GFM strikethrough — python-markdown core doesn't handle ~~...~~.
    src = _STRIKE_RE.sub(lambda m: f"<del>{m.group(1)}</del>", src)
    # GFM task lists — convert to a checkbox entity the CSS can style.
    def _task(m: re.Match) -> str:
        marker = "&#9745;" if m.group(2).lower() == "x" else "&#9744;"
        return f"{m.group(1)}{marker} "
    src = _TASK_RE.sub(_task, src)
    return src


def render_markdown_to_html(src: str) -> str:
    src = _pre(src)
    return md.markdown(
        src,
        extensions=[
            "tables",
            "fenced_code",
            "sane_lists",
        ],
        output_format="html5",
    )


def _trim_bottom(img: Image.Image, margin: int) -> Image.Image:
    """Crop trailing rows that are visually uniform (page bg / edge hairline)."""
    px = img.load()
    w, h = img.size
    last_content = 0
    for y in range(h - 1, -1, -1):
        # A row is "empty" if every sampled pixel is identical (solid color).
        first = px[0, y][:3]
        row_uniform = True
        for x in range(0, w, 4):
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


def render_file(md_path: Path, out_png: Path) -> None:
    src = md_path.read_text(encoding="utf-8")
    body = render_markdown_to_html(src)
    full_html = f"<html><head><style>{CSS}</style></head><body>{body}</body></html>"

    pdf_bytes = weasyprint.HTML(string=full_html).write_pdf()
    assert pdf_bytes is not None
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    # Render each page to a pixmap and stitch vertically.
    pages = []
    for page in doc:
        mat = fitz.Matrix(SCALE, SCALE)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        pages.append(img)

    if not pages:
        raise RuntimeError(f"no pages rendered for {md_path}")

    target_w = pages[0].width
    total_h = sum(p.height for p in pages)
    stitched = Image.new("RGB", (target_w, total_h), (30, 30, 30))
    y = 0
    for p in pages:
        stitched.paste(p, (0, y))
        y += p.height

    # Downscale to the nominal width.
    if stitched.width != WIDTH_PX:
        new_h = int(stitched.height * WIDTH_PX / stitched.width)
        stitched = stitched.resize((WIDTH_PX, new_h), Image.LANCZOS)

    stitched = _trim_bottom(stitched, margin=24)

    stitched.save(out_png, "PNG")
    print(f"  {md_path.name} -> {out_png.name}  ({stitched.size})")


def main() -> int:
    mds = sorted(SRC_DIR.glob("*.md"))
    if not mds:
        print(f"No markdown files in {SRC_DIR}", file=sys.stderr)
        return 1
    print(f"Rendering {len(mds)} ground-truth images into {OUT_DIR}")
    for md_path in mds:
        out_png = OUT_DIR / (md_path.stem + ".png")
        render_file(md_path, out_png)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Check that oracle captures show long tables and code blocks in full.

Streamdown puts height limits on tables and code blocks by default. Longer
content then scrolls inside its box, and the whole-surface capture loses it.

For each theme this script renders a long table and a long code block, and
every corpus file that has a table or a code block. It takes the same
screenshot that render_oracle.py takes. Then, for the last table row and the
last code line, it checks two things:

* no scrolling or clipping box hides the line in the page, and
* the pixels of the saved image at the place of the line show text ink.

The script exits with 1 when a line is lost.

Usage:
    python3 markdown/quality_harness/scripts/check_oracle_capture.py
    python3 markdown/quality_harness/scripts/check_oracle_capture.py --save DIR
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_oracle import (  # noqa: E402
    CORPUS,
    DEVICE_SCALE,
    THEMES,
    URL,
    VIEWPORT,
    _start_vite,
    _stop_vite,
)

LONG_FILE = "_check/long.md"
TABLE_ROWS = 40
CODE_LINES = 60

# Ink = pixels that differ from the most common colour of the crop by more
# than this sum of channel steps. Code text in the dark themes is dim, so the
# step is small. A full stop is the smallest last line the corpus has.
INK_DELTA = 15
MIN_INK_PIXELS = 3


def long_markdown() -> str:
    rows = "\n".join(
        f"| row-{i:02d} | value {i} | text for row {i} |"
        for i in range(1, TABLE_ROWS + 1)
    )
    code = "\n".join(f"line_{i:02d} = {i}" for i in range(1, CODE_LINES + 1))
    return (
        "# Long content\n\n"
        f"| Name | Value | Text |\n| --- | --- | --- |\n{rows}\n\n"
        f"```python\n{code}\n```\n\nEnd of file.\n"
    )


# Returns the box of the last table row and of the last code line, and says
# whether a scrolling or clipping box in the page hides it.
PROBE_JS = """
() => {
  const surface = document.querySelector('.oracle-surface');
  const sr = surface.getBoundingClientRect();
  const hiddenBy = (rect, node) => {
    for (let a = node.parentElement; a && a !== surface; a = a.parentElement) {
      if (getComputedStyle(a).overflowY === 'visible') continue;
      const ar = a.getBoundingClientRect();
      // Only the vertical direction counts. A long line that scrolls sideways
      // is the same on every version and does not lose a row or a line.
      if (rect.bottom > ar.bottom + 1 || rect.top < ar.top - 1) {
        return a.tagName.toLowerCase() + '.' + a.className;
      }
    }
    return null;
  };
  const box = (kind, label, rect, node) => ({
    kind, label,
    x: rect.left - sr.left, y: rect.top - sr.top,
    w: rect.width, h: rect.height,
    hiddenBy: hiddenBy(rect, node),
  });
  const out = [];
  for (const table of surface.querySelectorAll('table')) {
    const rows = table.querySelectorAll('tbody tr');
    const row = rows[rows.length - 1];
    if (!row) continue;
    const cell = row.querySelector('td');
    const range = document.createRange();
    range.selectNodeContents(cell);
    out.push(box('table', cell.textContent.trim(), range.getBoundingClientRect(), cell));
  }
  for (const pre of surface.querySelectorAll('pre')) {
    const walker = document.createTreeWalker(pre, NodeFilter.SHOW_TEXT);
    let last = null;
    while (walker.nextNode()) {
      if (walker.currentNode.textContent.trim()) last = walker.currentNode;
    }
    if (!last) continue;
    const range = document.createRange();
    range.selectNodeContents(last);
    out.push(box('code', last.textContent.trim(), range.getBoundingClientRect(), last.parentElement));
  }
  return { height: sr.height, width: sr.width, boxes: out };
}
"""


def ink_pixels(img: Image.Image, x: float, y: float, w: float, h: float) -> int:
    left, top = max(int(x), 0), max(int(y), 0)
    right, bottom = min(int(x + w) + 1, img.width), min(int(y + h) + 1, img.height)
    if right <= left or bottom <= top:
        return 0
    crop = img.crop((left, top, right, bottom)).convert("RGB")
    colors = crop.getcolors(maxcolors=crop.width * crop.height)
    background = max(colors)[1]
    return sum(
        count
        for count, color in colors
        if sum(abs(a - b) for a, b in zip(color, background)) > INK_DELTA
    )


async def check_page(page, rel: str, theme: str, save: Path | None) -> list[str]:
    await page.goto(f"{URL}/?file={rel}&theme={theme}", wait_until="load")
    await page.wait_for_selector(
        '[data-testid="rendered-sentinel"]', state="attached", timeout=15000
    )
    await page.wait_for_load_state("networkidle", timeout=15000)
    await page.evaluate("document.fonts.ready")
    await page.wait_for_timeout(1500)
    probe = await page.evaluate(PROBE_JS)
    surface = await page.query_selector(".oracle-surface")
    png = await surface.screenshot()
    if save is not None:
        out = save / theme / rel.replace(".md", ".png")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(png)
    img = Image.open(io.BytesIO(png))
    problems = []
    for b in probe["boxes"]:
        where = f"{theme} {rel} last {b['kind']} {b['label']!r}"
        if b["hiddenBy"]:
            problems.append(f"{where}: hidden by {b['hiddenBy']}")
        if b["y"] + b["h"] > img.height + 1:
            problems.append(f"{where}: below the image ({img.height} px high)")
        ink = ink_pixels(img, b["x"], b["y"], b["w"], b["h"])
        if ink < MIN_INK_PIXELS:
            problems.append(f"{where}: only {ink} ink pixels in the image")
    return problems


async def run(save: Path | None) -> int:
    files = [LONG_FILE]
    for path in sorted(CORPUS.rglob("*.md")):
        text = path.read_text()
        if "```" in text or any(ln.startswith("|") for ln in text.splitlines()):
            files.append(path.relative_to(CORPUS).as_posix())
    problems: list[str] = []
    checked = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        for theme in THEMES:
            ctx = await browser.new_context(
                viewport=VIEWPORT,
                device_scale_factor=DEVICE_SCALE,
                color_scheme="light" if theme == "white" else "dark",
            )
            await ctx.route(
                f"{URL}/{LONG_FILE}",
                lambda route: route.fulfill(
                    body=long_markdown(), content_type="text/markdown"
                ),
            )
            page = await ctx.new_page()
            for rel in files:
                found = await check_page(page, rel, theme, save)
                problems += found
                checked += 1
                print(f"  {'✗' if found else '✓'} [{theme:10}] {rel}")
            await ctx.close()
        await browser.close()
    print()
    for line in problems:
        print("LOST:", line)
    print(f"{checked} captures checked, {len(problems)} lost lines.")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", type=Path, help="Folder to keep the checked images")
    args = ap.parse_args()
    vite = _start_vite()
    try:
        return asyncio.run(run(args.save))
    finally:
        _stop_vite(vite)


if __name__ == "__main__":
    sys.exit(main())

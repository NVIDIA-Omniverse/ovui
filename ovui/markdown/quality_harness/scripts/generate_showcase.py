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

"""Render per-feature showcase images for the MarkdownWidget.

Writes one PNG per token family into markdown/quality_harness/artifacts/showcase/.
Each PNG is rendered in a fresh subprocess (ImGui global state cannot
reset between captures) and auto-trimmed to its content height.

Usage:
    Xvfb :100 -screen 0 1024x1600x24 &
    DISPLAY=:100 PYTHONPATH=python:build/bindings \\
        python3 markdown/quality_harness/scripts/generate_showcase.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

HARNESS = Path(__file__).resolve().parents[1]
OUT_DIR = HARNESS / "artifacts" / "showcase"
OUT_DIR.mkdir(parents=True, exist_ok=True)

WIDTH = 760
HEIGHT = 1400


SHOWCASES: dict[str, str] = {
    "showcase_headings": """# Heading level 1

## Heading level 2

### Heading level 3

#### Heading level 4

##### Heading level 5

###### Heading level 6

Body text for reference.  Headings scale down from 28 px at H1 to the
body size at H6, and every level renders bold via the double-draw
shift so the hierarchy reads at a glance.
""",

    "showcase_emphasis": """## Emphasis

Plain body text for reference.

**Bold text** renders via a 1 px double-draw shift.

*Italic text* uses the dedicated `italicColor` (warm off-white) so it
never collides with link blue.

***Bold-italic*** combines both effects on the same run.

~~Strikethrough~~ draws a 1 px line through the glyph midline of every
visual segment, so wrapped strikes stay continuous.

`inline code` sits on a rounded pill background.

Combinations: **bold with `code` inside**, *italic with a [link
inside](https://example.com)*, and ~~strikethrough~~ mid-paragraph.
""",

    "showcase_code": """## Inline and fenced code

Use `array.length` or `len(x)` inline, and `while (i < N)` with real
token boundaries inside a sentence.

```python
def greet(name: str) -> str:
    '''Return a friendly greeting.'''
    return f"Hello, {name}!"


greet("world")
```

```cpp
// Monospace body text, rounded dark background,
// language chip in the top-right corner.
template <typename T>
T clamp(T v, T lo, T hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}
```

```
Plain fenced block with no language tag — chip is suppressed.
Lines preserve their exact whitespace and hard newlines.
```
""",

    "showcase_lists": """## Lists

Unordered, nested:

- First item
- Second item with **bold** and `code`
  - Nested one level (dash marker)
  - Another nested item
    - Two levels deep (asterisk marker)
- Back at root depth

Ordered:

1. Step one
2. Step two with a description that wraps onto a second visual line
   and indents under the marker correctly
3. Step three
   1. Nested ordered item
   2. Nested ordered item two
4. Step four

Task list:

- [x] Phase A — scaffolding
- [x] Phase B — headings and paragraphs
- [x] Phase C — inline styling
- [ ] Phase Z — not done yet
- [x] Phase L — comprehensive demo
""",

    "showcase_blockquotes": """## Block quotes

> A single-level block quote.  The accent bar spans the full height
> of the quoted region and the text is subtly dimmed.

> A longer block quote with **bold**, *italic*, and a `code` token.
> Quotes wrap at the available width just like paragraphs, and the
> bar continues down the left edge for every visual line.

> > Nested block quote — each level adds indent and an additional
> > accent bar segment.
> >
> > > Three levels deep.  The indent/bar pattern scales cleanly.

Regular paragraph after the quote returns to the base indent.
""",

    "showcase_tables": """## Tables

| Column A | Column B | Column C |
|----------|----------|----------|
| cell a1  | cell b1  | cell c1  |
| cell a2  | cell b2  | cell c2  |
| cell a3  | cell b3  | cell c3  |

Alignment modifiers (`:---`, `:---:`, `---:`):

| Left       | Center     | Right      |
|:-----------|:----------:|-----------:|
| apple      | banana     | cherry     |
| dog        | elephant   | fox        |
| 100        | 42         | 7          |

Wrapping cells wrap when their text is wider than the column:

| Short | A longer cell whose contents will wrap across multiple |
|-------|--------------------------------------------------------|
| A     | this cell has a lot of text that needs wrapping        |
| B     | short                                                  |
""",

    "showcase_links": """## Links

An [inline link](https://example.com) in the middle of a paragraph.

A [long link that should wrap across two visual lines to show that
the underline is re-drawn for every visual segment of the
link](https://example.com/some/very/long/path).

Two [consecutive](https://a.example.com) [links](https://b.example.com)
next to each other — each gets its own hit region and tooltip.

Link inside a list:

- First item
- Second item with [a link](https://example.com) and trailing text
- Third item

Link inside emphasis: *before [link](https://example.com) after* — the
italic color applies where the link color doesn't.
""",

    "showcase_mixed": """# MarkdownWidget — complete document

A realistic document exercising every feature class in one render.

## Introduction

The **MarkdownWidget** is a native ImGui renderer.  It supports
*inline* styling, `inline code`, [links](https://example.com),
~~strikethrough~~, and HTML entities like &amp; and &mdash;.

## Feature checklist

- [x] Headings H1–H6
- [x] Paragraphs with wrapping
- [x] Lists (ordered, unordered, task)
- [x] Block quotes, nested
- [x] Fenced code blocks
- [x] Tables with alignment
- [ ] Image loading — deferred to v1.1

## Example code

```python
import omni.ui as ui

ui.init("Demo", 800, 600)
with ui.Window("Demo") as win:
    with win.frame:
        with ui.ScrollingFrame():
            ui.MarkdownWidget("# Hello **world**")
ui.run()
```

## Quoted rationale

> Inline flow with correct mid-paragraph style changes — that is the
> problem the widget set out to solve.  Every other feature is a
> consequence of getting that one thing right.

## Status summary

| Phase | Feature             | Status |
|:-----:|:--------------------|:------:|
|   A   | Scaffolding         |   OK   |
|   B   | Paragraphs/headings |   OK   |
|   C   | Inline styling      |   OK   |
|   D   | Lists               |   OK   |
|   E   | Links               |   OK   |
|   F   | Block quotes        |   OK   |
|   G   | Code blocks         |   OK   |
|   H   | Thematic breaks     |   OK   |
|   I   | Tables              |   OK   |
|   J   | Images (placeholder)|   OK   |

---

End of showcase document.
""",
}


RUNNER_SOURCE = r"""
import os, sys
from pathlib import Path
import omni.ui as ui

SRC_PATH = Path(sys.argv[1])
OUT_PATH = Path(sys.argv[2])
WIDTH = int(sys.argv[3])
HEIGHT = int(sys.argv[4])

ui.init("Showcase", width=WIDTH, height=HEIGHT)

source = SRC_PATH.read_text(encoding="utf-8")

win = ui.Window(
    "Showcase",
    width=WIDTH, height=HEIGHT,
    flags=ui.WINDOW_FLAGS_NO_SCROLLBAR | ui.WINDOW_FLAGS_NO_RESIZE,
)
with win.frame:
    ui.MarkdownWidget(source)


async def capture() -> None:
    from omni.ui import testing
    await testing.wait_frames(15)
    testing.capture_screenshot(str(OUT_PATH))


ui.run(capture())
"""


def _trim_bottom(img: Image.Image, margin: int = 16, edge_ignore: int = 8) -> Image.Image:
    px = img.load()
    w, h = img.size
    last_content = 0
    start = max(0, h - edge_ignore - 1)
    for y in range(start, -1, -1):
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


def render_one(name: str, markdown: str, display: str | None) -> None:
    src_path = Path(f"/tmp/_showcase_{name}.md")
    src_path.write_text(markdown, encoding="utf-8")

    out_path = OUT_DIR / f"{name}.png"
    runner = Path("/tmp/_showcase_runner.py")
    runner.write_text(RUNNER_SOURCE)

    env = os.environ.copy()
    env["PYTHONPATH"] = "python:build/bindings"
    if display:
        env["DISPLAY"] = display

    cmd = [sys.executable, str(runner), str(src_path), str(out_path),
           str(WIDTH), str(HEIGHT)]
    res = subprocess.run(cmd, env=env, cwd=str(REPO),
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0 or not out_path.exists():
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)
        raise RuntimeError(f"showcase render failed for {name}")

    img = Image.open(out_path).convert("RGB")
    w, h = img.size
    img = img.crop((1, 26, w - 1, h))
    img = _trim_bottom(img)
    img.save(out_path)
    print(f"  {name} -> {out_path.name}  ({img.size})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--display", default=None, help="X display (default: inherit $DISPLAY)")
    ap.add_argument("--only", default=None, help="Only render one showcase by name")
    args = ap.parse_args()

    names = list(SHOWCASES.keys())
    if args.only:
        names = [n for n in names if n == args.only]
    if not names:
        print("nothing to render", file=sys.stderr)
        return 1

    print(f"Rendering {len(names)} showcases into {OUT_DIR}")
    for name in names:
        render_one(name, SHOWCASES[name], args.display)
    return 0


if __name__ == "__main__":
    sys.exit(main())

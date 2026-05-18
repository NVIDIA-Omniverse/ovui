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
Comprehensive demo for the native ImGui MarkdownWidget.

Run:  python examples/markdown_native_demo.py
      python examples/markdown_native_demo.py --screenshot
"""
import sys

import omni.ui as ui

_SCREENSHOT = "--screenshot" in sys.argv
WIDTH, HEIGHT = 820, 1100

ui.init("Markdown Native Demo", width=WIDTH, height=HEIGHT)

SAMPLE = '''# Markdown Native Demo

Welcome to the **ovui native markdown widget** — a full CommonMark +
GitHub-flavored renderer drawing every glyph through ImGui.  Every
feature listed below is rendered live by the widget you see now.

## Headings

# H1 The biggest
## H2 a bit smaller
### H3 still readable
#### H4 — emphasis
##### H5
###### H6 fine print

## Inline styling

Regular text with **bold**, *italic*, ***bold-italic***, `inline code`,
~~strikethrough~~, an [inline link](https://example.com), and a long
[link that should wrap across two lines so we can verify the underline
spans both visual segments](https://example.com/long/path).

HTML entities: AT&amp;T &copy; 2026 &mdash; quotes &quot;like this&quot;.

## Lists

Unordered, with nesting:

- First item with **bold** and a `code` token
- Second item, [with a link](https://example.org)
  - Nested bullet (one level deep)
  - Another nested bullet
    - Two levels deep
- Back at root depth

Ordered:

1. Step one
2. Step two
3. Step three with a wrapping description that flows onto a second
   visual line and indents under the marker

Task list:

- [x] Phase A — scaffolding
- [x] Phase B — paragraphs + headings
- [x] Phase C — inline styling
- [x] Phase D — lists
- [x] Phase E — links
- [x] Phase F — block quotes
- [x] Phase G — code blocks
- [x] Phase H — thematic breaks
- [x] Phase I — tables
- [x] Phase J — images
- [x] Phase K — polish
- [ ] Phase L — comprehensive demo (this file)

## Block quote

> A block quote with **bold**, an [embedded link](https://example.com),
> and `inline code`.  Quotes can wrap across multiple lines and the
> bar continues vertically through the whole quoted region.
>
> > Nested quote.  Even deeper indents get their own bar.

---

## Code block

```python
def render_markdown(source: str) -> None:
    """Parse and render a markdown source string."""
    doc = parse_markdown(source)
    layout(doc, available_width)
```

## Table

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
|   J   | Images              |   OK   |
|   K   | Polish              |   OK   |

## Images

An inline image ![alt text](https://example.com/img.png) renders as a
labelled placeholder in v1 — image loading is wired through the
`load_image_fn` slot in v1.1.

---

That's the full feature set.
'''


def on_link(url: str) -> None:
    print(f"[link clicked] {url}")


win = ui.Window(
    "Markdown Native Demo",
    width=WIDTH,
    height=HEIGHT,
    fill_app_window=True,
    flags=(
        ui.WINDOW_FLAGS_NO_SCROLLBAR
        | ui.WINDOW_FLAGS_NO_TITLE_BAR
        | ui.WINDOW_FLAGS_NO_RESIZE
    ),
)

with win.frame:
    with ui.ScrollingFrame():
        w = ui.MarkdownWidget(SAMPLE)
        w.set_link_clicked_fn(on_link)


async def capture(path: str) -> None:
    from omni.ui import testing
    await testing.wait_frames(8)
    testing.capture_screenshot(path)
    print(f"Screenshot saved: {path}")


if __name__ == "__main__":
    if _SCREENSHOT:
        ui.run(capture("examples/markdown_native_demo.png"))
    else:
        ui.run()

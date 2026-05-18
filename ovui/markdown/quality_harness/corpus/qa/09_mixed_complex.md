# ovui-md-native — README

**ovui-md-native** is a native ImGui markdown rendering widget that
targets full CommonMark plus GitHub-flavored extensions. This document
is a realistic README-style fixture intended to combine every element
class the widget supports into a single test file.

## Overview

The widget parses markdown via [md4c](https://github.com/mity/md4c) and
renders inline and block content with raw ImGui draw calls. Key design
goals:

- Zero dependencies beyond ImGui and md4c.
- Native word-wrap using `ImFont::CalcWordWrapPosition`.
- Full CommonMark + GFM coverage.
- Dark-theme aware — all colors resolve through OVUI's style cascade.

## Feature matrix

| Area         | Feature           | Status |
|--------------|-------------------|:------:|
| Block        | Heading H1–H6     |   ✔    |
| Block        | Paragraph         |   ✔    |
| Block        | Blockquote        |   ✔    |
| Block        | List (ul, ol)     |   ✔    |
| Block        | Code (fenced)     |   ✔    |
| Block        | Code (indented)   |   ✔    |
| Block        | Thematic break    |   ✔    |
| Block        | Table             |   ✔    |
| Inline       | Bold              |   ✔    |
| Inline       | Italic            |   ✔    |
| Inline       | Strikethrough     |   ✔    |
| Inline       | Inline code       |   ✔    |
| Inline       | Link              |   ✔    |
| Inline       | Image placeholder |   ✔    |

## Installation

Clone, build, and install as a Python extension:

```bash
git clone https://github.com/example/ovui-md-native.git
cd ovui-md-native
cmake -B build && cmake --build build --parallel
pip install -e .
```

## Quick start

```python
import omni.ui as ui

ui.init("Demo", width=800, height=600)
win = ui.Window("Demo")
with win.frame:
    ui.MarkdownWidget("# Hello\n\nWorld")
ui.run()
```

## Architecture

1. **Parse.** md4c walks the source and emits SAX-style events.
2. **Flatten.** Events become a linear `MdToken` stream with text
   payloads stored in an owning buffer.
3. **Render.** A single `_drawContent` walks the token stream and
   draws everything in one ImGui pass.

> **Design note:** the widget is a pure display surface. Block-level
> customization (embedding non-markdown widgets) is intentionally out
> of scope for v1 — see [SRD-A](./docs/SRD-A-WIDGET-HYBRID.md) for the
> alternative direction.

### Style cascade

Colors, fonts, and spacing resolve through OVUI's style system, so
applications can override any single key without subclassing. For
example, to change the link color application-wide:

```css
/* style.css (notional) */
MarkdownWidget::link {
    color: "#7ab7ff";
}
```

## Contributing

- [ ] Fork the repository
- [ ] Create a feature branch
- [x] Read the contribution guidelines
- [x] Run the QA suite before opening a PR
- [ ] Include test fixtures in `tests/markdown_qa/`

## Known limitations

1. Local file images and data URI images render; HTTP/S images need an application resolver or cached local file.
2. Inline formatting inside table cells is rendered as plain text.
3. Footnotes (`[^1]`) are not yet supported.
4. Text selection is not implemented.

## License

MIT — see [LICENSE](./LICENSE) for details.

---

*Built with ImGui, md4c, and determination.*

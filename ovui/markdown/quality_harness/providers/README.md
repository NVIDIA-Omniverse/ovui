# Markdown Provider Plugins

This folder is an optional local runtime for MarkdownWidget provider showcases.
It is intentionally outside the core widget package. Install the Node
dependencies here only when you want Mermaid and MathJax rasterization in the
example showcase.

```bash
npm ci --prefix ovui/markdown/quality_harness/providers
```

The Python provider plugins point at this folder through
`MarkdownProviderDocumentRenderer(..., provider_dir=...)`.

## Node.js version

The `puppeteer` range `^25.16.0` needs Node.js 22.12 or newer. These versions do not
use `extract-zip` or `basic-ftp`. The `engines` field in `package.json` states
the minimum version.

Puppeteer looks for Chrome in `~/.cache/puppeteer`. The Mermaid provider sets
`HOME` to a scratch folder. Set `PUPPETEER_EXECUTABLE_PATH` to a Chrome
binary when `npm ci` has not put Chrome in the default place.

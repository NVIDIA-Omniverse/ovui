# Markdown Provider Plugins

This folder is an optional local runtime for MarkdownWidget provider showcases.
It is intentionally outside the core widget package. Install the Node
dependencies here only when you want Mermaid and MathJax rasterization in the
example showcase.

```bash
npm install --prefix examples/markdown_provider_plugins
```

The Python provider plugins point at this folder through
`MarkdownProviderDocumentRenderer(..., provider_dir=...)`.

# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Markdown source transformation helpers for provider-rendered blocks."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .core import DEFAULT_CACHE_DIR, MarkdownProviderChain, MarkdownProviderRequest
from .math import MathJaxProviderPlugin
from .mermaid import MermaidCliProviderPlugin


_FENCE_RE = re.compile(
    r"(?P<fence>^[ \t]*`{3,}[ \t]*(?P<lang>[A-Za-z0-9_-]+)[^\n]*\n(?P<body>.*?)(?:\n^[ \t]*`{3,}[ \t]*$))",
    re.MULTILINE | re.DOTALL,
)

# `$$…$$` block math (multi-line allowed). Must come BEFORE the inline regex
# during substitution so a `$$` opener isn't mistaken for two `$` runs.
_MATH_BLOCK_RE = re.compile(r"\$\$(?P<body>.+?)\$\$", re.DOTALL)
# `$…$` inline math. Restricted to single line + non-empty body and rejects
# double-`$` (handled by the block regex above) so common dollar-sign use
# in prose ("$5 each") doesn't get matched.
_MATH_INLINE_RE = re.compile(r"(?<![\$\\])\$(?!\$)(?P<body>[^\$\n]+?)(?<![\\])\$(?!\$)")


class MarkdownProviderDocumentRenderer:
    """Rewrite provider-backed fenced blocks into image Markdown.

    This is a Python compatibility bridge until MarkdownWidget has a Python
    binding for native ``IMarkdownAssetProvider``.  It is intentionally
    non-blocking: first render returns placeholders while providers work in
    background, later render calls replace blocks with ready images.
    """

    def __init__(
        self,
        markdown_path: Path,
        cache_dir: Optional[Path] = None,
        *,
        chain: Optional[MarkdownProviderChain] = None,
        provider_dir: Optional[Path] = None,
        theme: str = "light",
    ):
        self.markdown_path = markdown_path.resolve()
        self.base_dir = self.markdown_path.parent
        self.cache_dir = (cache_dir or DEFAULT_CACHE_DIR).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.provider_dir = provider_dir.resolve() if provider_dir is not None else None
        self.theme = theme
        self.chain = chain or MarkdownProviderChain(
            [
                MermaidCliProviderPlugin(self.cache_dir, working_dir=self.provider_dir),
                MathJaxProviderPlugin(self.cache_dir, working_dir=self.provider_dir),
            ]
        )

    def _request_math(
        self,
        body: str,
        kind: str,
        alt: str,
        original: str,
        max_display_width: int,
        font_size: float,
    ) -> str:
        result = self.chain.first(
            MarkdownProviderRequest(
                kind=kind,
                source=body,
                language="math",
                base_dir=self.base_dir,
                cache_dir=self.cache_dir,
                max_display_width=max_display_width,
                font_size=font_size,
                theme=self.theme,
            )
        )
        if result.ready:
            return f"![{alt}]({Path(result.path).as_posix()})"
        # Pending / unsupported / failed: leave the original markdown in
        # place so later render() calls can pick up the cached output.
        return original

    def render(self, text: str, *, max_display_width: int = 900, font_size: float = 14.0) -> str:
        def replace_fence(match: "re.Match[str]") -> str:
            lang = match.group("lang").lower()
            body = match.group("body")
            if lang == "mermaid":
                kind = "diagram"
                alt = "Mermaid diagram"
            elif lang in {"math", "latex", "tex"}:
                kind = "math_block"
                alt = "Math expression"
            else:
                return match.group("fence")

            result = self.chain.first(
                MarkdownProviderRequest(
                    kind=kind,
                    source=body,
                    language=lang,
                    base_dir=self.base_dir,
                    cache_dir=self.cache_dir,
                    max_display_width=max_display_width,
                    font_size=font_size,
                    theme=self.theme,
                )
            )
            if result.ready:
                path = Path(result.path)
                image_src = path.as_posix()
                return f"![{alt}]({image_src})"
            if result.state == "pending":
                return f"> [!NOTE]\n> Rendering {alt.lower()}..."
            if result.state == "unsupported":
                return f"> [!WARNING]\n> Optional provider unavailable: {result.error or alt}\n\n{match.group('fence')}"
            return f"> [!CAUTION]\n> Provider failed: {result.error or alt}\n\n{match.group('fence')}"

        text = _FENCE_RE.sub(replace_fence, text)

        # KaTeX-style math syntax: `$$...$$` and `$...$`. Block first so the
        # block opener isn't treated as two adjacent inline `$`.
        def replace_math_block(match: "re.Match[str]") -> str:
            body = match.group("body").strip("\n")
            return self._request_math(
                body, "math_block", "Math expression", match.group(0),
                max_display_width=max_display_width, font_size=font_size,
            )

        def replace_math_inline(match: "re.Match[str]") -> str:
            body = match.group("body").strip()
            if not body:
                return match.group(0)
            return self._request_math(
                body, "math_inline", body, match.group(0),
                max_display_width=max_display_width, font_size=font_size,
            )

        text = _MATH_BLOCK_RE.sub(replace_math_block, text)
        text = _MATH_INLINE_RE.sub(replace_math_inline, text)
        return text

    def wait_for_idle(self, timeout: Optional[float] = None) -> None:
        self.chain.wait_for_idle(timeout=timeout)

    def shutdown(self) -> None:
        self.chain.shutdown()

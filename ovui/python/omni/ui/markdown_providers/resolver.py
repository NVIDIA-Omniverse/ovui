# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Compatibility resolver built from provider plugins."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .core import DEFAULT_CACHE_DIR, MarkdownProviderChain, MarkdownProviderRequest, MarkdownProviderResult
from .http import HttpImageProviderPlugin
from .svg import SvgRasterProviderPlugin


class MarkdownAssetResolver:
    """Resolve Markdown image sources to local raster paths.

    This is the provider-backed replacement for the old example-local resolver.
    It remains callable as ``fn(src: str) -> str`` so it can be passed directly
    to ``MarkdownWidget.set_image_url_provider_fn``.
    """

    def __init__(
        self,
        markdown_path: Path,
        cache_dir: Optional[Path] = None,
        *,
        svg_output_width: int = 256,
        chain: Optional[MarkdownProviderChain] = None,
    ):
        self.markdown_path = markdown_path.resolve()
        self.base_dir = self.markdown_path.parent
        self.cache_dir = (cache_dir or DEFAULT_CACHE_DIR).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.chain = chain or MarkdownProviderChain(
            [
                HttpImageProviderPlugin(self.cache_dir),
                SvgRasterProviderPlugin(self.cache_dir, output_width=svg_output_width),
            ]
        )
        self.last_result: Optional[MarkdownProviderResult] = None

    def __call__(self, src: str) -> str:
        return self.resolve_image_src(src)

    def resolve_image_src(self, src: str) -> str:
        """Return a local raster path or ``""`` to keep the widget fallback."""

        result = self.resolve(src)
        return result.path if result.ready else ""

    def resolve(self, src: str) -> MarkdownProviderResult:
        if not src or src.startswith("data:"):
            self.last_result = MarkdownProviderResult(state="unsupported", source=src)
            return self.last_result

        if src.startswith(("http://", "https://")):
            http_result = self.chain.first(self._request(src))
            if not http_result.ready:
                self.last_result = http_result
                return http_result
            src = http_result.path

        if src.startswith("file://"):
            src = src[7:]
        elif src.startswith("file:"):
            src = src[5:]

        path = Path(src)
        if not path.is_absolute():
            path = (self.base_dir / path).resolve()
        if not path.exists():
            self.last_result = MarkdownProviderResult(state="failed", error=f"image not found: {path}", source=src)
            return self.last_result

        if path.suffix.lower() in {".svg", ".svgz"}:
            svg_result = self.chain.first(self._request(str(path)))
            self.last_result = svg_result
            return svg_result

        self.last_result = MarkdownProviderResult(state="ready", path=str(path), source=src)
        return self.last_result

    def wait_for_idle(self, timeout: Optional[float] = None) -> None:
        self.chain.wait_for_idle(timeout=timeout)

    def shutdown(self) -> None:
        self.chain.shutdown()

    def _request(self, source: str) -> MarkdownProviderRequest:
        return MarkdownProviderRequest(
            kind="image",
            source=source,
            base_dir=self.base_dir,
            cache_dir=self.cache_dir,
        )

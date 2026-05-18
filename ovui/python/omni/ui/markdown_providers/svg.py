# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Optional SVG-to-raster provider for MarkdownWidget."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .core import AsyncProviderPlugin, MarkdownProviderRequest, MarkdownProviderResult, stable_digest


class SvgRasterProviderPlugin(AsyncProviderPlugin):
    """Rasterize static SVG files to PNG when CairoSVG is installed."""

    def __init__(self, cache_dir: Optional[Path] = None, *, output_width: int = 256):
        super().__init__(cache_dir)
        self.output_width = output_width

    def can_handle(self, request: MarkdownProviderRequest) -> bool:
        if request.kind != "image":
            return False
        return request.source.lower().endswith((".svg", ".svgz"))

    def cache_key(self, request: MarkdownProviderRequest) -> str:
        path = Path(request.source)
        stat_key = ""
        try:
            stat = path.stat()
            stat_key = f"{stat.st_mtime_ns}:{stat.st_size}"
        except OSError:
            pass
        return stable_digest("svg-raster", path.resolve() if path.exists() else request.source, self.output_width, stat_key)

    def _target_for_path(self, path: Path, request: MarkdownProviderRequest) -> Path:
        width = request.max_display_width or self.output_width
        return self.cache_dir / f"svg-{stable_digest(path.resolve(), width, path.stat().st_mtime_ns)}.png"

    def cached_result(self, request: MarkdownProviderRequest) -> Optional[MarkdownProviderResult]:
        path = Path(request.source)
        if not path.exists():
            return MarkdownProviderResult(state="failed", error=f"SVG file not found: {path}", source=request.source)
        target = self._target_for_path(path, request)
        if target.exists() and target.stat().st_size > 0:
            return MarkdownProviderResult(state="ready", path=str(target), source=request.source)
        return None

    def render(self, request: MarkdownProviderRequest) -> MarkdownProviderResult:
        path = Path(request.source)
        if not path.exists():
            return MarkdownProviderResult(state="failed", error=f"SVG file not found: {path}", source=request.source)

        try:
            import cairosvg  # type: ignore
        except Exception:
            return MarkdownProviderResult(
                state="unsupported",
                error="Install optional dependency 'cairosvg' to rasterize SVG images.",
                source=request.source,
            )

        target = self._target_for_path(path, request)
        width = request.max_display_width or self.output_width
        try:
            cairosvg.svg2png(url=str(path), write_to=str(target), output_width=width)
        except Exception as exc:
            return MarkdownProviderResult(state="failed", error=str(exc), source=request.source)
        return MarkdownProviderResult(state="ready", path=str(target), source=request.source)

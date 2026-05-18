# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Optional MathJax provider plugin for LaTeX/TeX math.

Same hardening approach as :mod:`.mermaid`: bounded input size, restricted
environment (``NODE_OPTIONS`` cleared, explicit ``PATH`` / ``HOME``), rlimit
where available, per-render nonce for scratch files.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .core import AsyncProviderPlugin, MarkdownProviderRequest, MarkdownProviderResult, stable_digest
from .mermaid import DEFAULT_MAX_SOURCE_BYTES, _build_restricted_env, _rlimit_preexec


_MATHJAX_NODE_SCRIPT = r"""
const fs = require('fs');
const path = require('path');
const {createRequire} = require('module');
const requireFromCwd = createRequire(path.join(process.cwd(), 'package.json'));
const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));

global.MathJax = {
  loader: {
    paths: {mathjax: '@mathjax/src/bundle'},
    load: ['adaptors/liteDOM'],
    require: requireFromCwd
  },
  output: {
    font: 'mathjax-newcm',
    linebreaks: { inline: false }
  }
};

requireFromCwd('@mathjax/src/bundle/tex-svg.js');

MathJax.startup.promise.then(() => {
  const em = payload.font_size || 16;
  const ex = em * 0.5;
  const width = Math.max(160, payload.width || 900);
  return MathJax.tex2svgPromise(payload.source || '', {
    display: payload.display !== false,
    em: em,
    ex: ex,
    containerWidth: width
  });
}).then((node) => {
  const adaptor = MathJax.startup.adaptor;
  let svg = adaptor.serializeXML(adaptor.tags(node, 'svg')[0]);
  if (payload.color) {
    if (svg.includes('style="')) {
      svg = svg.replace('style="', `style="color:${payload.color};`);
    } else {
      svg = svg.replace('<svg ', `<svg style="color:${payload.color};" `);
    }
  }
  process.stdout.write(svg);
  MathJax.done();
}).catch((err) => {
  console.error(err && err.message ? err.message : String(err));
  MathJax.done();
  process.exit(1);
});
"""


class MathJaxProviderPlugin(AsyncProviderPlugin):
    """Render TeX math through optional Node + MathJax.

    The provider emits PNG by default when CairoSVG is available because the
    current Python compatibility hook feeds local raster paths to the widget.
    Set ``output_format="svg"`` for C++/provider stacks that can rasterize SVG
    later.
    """

    DEFAULT_CONCURRENCY = 2

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        *,
        node_executable: str = "node",
        output_format: str = "png",
        working_dir: Optional[Path] = None,
        timeout: float = 20.0,
        max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
        concurrency: int = DEFAULT_CONCURRENCY,
    ):
        super().__init__(cache_dir, concurrency=concurrency)
        self.node_executable = node_executable
        self.output_format = output_format.lstrip(".").lower()
        self.working_dir = working_dir
        self.timeout = timeout
        self.max_source_bytes = int(max_source_bytes)

    def can_handle(self, request: MarkdownProviderRequest) -> bool:
        return request.kind in {"math", "math_block", "math_inline"} or request.language.lower() in {"math", "latex", "tex"}

    def cache_key(self, request: MarkdownProviderRequest) -> str:
        return stable_digest(
            "mathjax-v2",
            request.source,
            request.kind,
            request.font_size,
            request.max_display_width,
            request.device_scale,
            request.theme,
            self._color_for_theme(request.theme),
            self.output_format,
        )

    def _target_for_request(self, request: MarkdownProviderRequest) -> Path:
        ext = ".svg" if self.output_format == "svg" else ".png"
        return self.cache_dir / f"mathjax-{self.cache_key(request)}{ext}"

    def cached_result(self, request: MarkdownProviderRequest) -> Optional[MarkdownProviderResult]:
        target = self._target_for_request(request)
        if target.exists() and target.stat().st_size > 0:
            return MarkdownProviderResult(state="ready", path=str(target), source=request.source)
        return None

    def render(self, request: MarkdownProviderRequest) -> MarkdownProviderResult:
        source_bytes = request.source.encode("utf-8")
        if len(source_bytes) > self.max_source_bytes:
            return MarkdownProviderResult(
                state="failed",
                error=f"MathJax source exceeds {self.max_source_bytes} bytes",
                source=request.source,
            )

        node = shutil.which(self.node_executable)
        if not node:
            return MarkdownProviderResult(
                state="unsupported",
                error="Install optional dependency Node.js and '@mathjax/src' for MathJax rendering.",
                source=request.source,
            )

        key = self.cache_key(request)
        # Per-render nonce keeps parallel invocations from stepping on each
        # other's scratch files.  The render script is now per-nonce too; the
        # legacy ``mathjax-render.js`` single-location file is gone.
        nonce = secrets.token_hex(4)
        payload_path = self.cache_dir / f"mathjax-{key}-{nonce}.json"
        script_path = self.cache_dir / f"mathjax-{key}-{nonce}.js"
        svg_path = self.cache_dir / f"mathjax-{key}.svg"
        target = self._target_for_request(request)

        payload = {
            "source": request.source,
            "display": request.kind != "math_inline",
            "font_size": request.font_size,
            "width": request.max_display_width or 900,
            "color": self._color_for_theme(request.theme),
        }

        try:
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            script_path.write_text(_MATHJAX_NODE_SCRIPT, encoding="utf-8")

            tmp_home = self.cache_dir / "_subproc_home"
            tmp_home.mkdir(parents=True, exist_ok=True)
            env = _build_restricted_env(tmp_home)

            popen_kwargs: "dict[str, object]" = {
                "check": True,
                "timeout": self.timeout,
                "capture_output": True,
                "text": True,
                "cwd": str(self.working_dir) if self.working_dir else None,
                "env": env,
            }
            preexec = _rlimit_preexec()
            if preexec is not None:
                popen_kwargs["preexec_fn"] = preexec

            try:
                proc = subprocess.run(
                    [node, str(script_path), str(payload_path)],
                    **popen_kwargs,  # type: ignore[arg-type]
                )
            except subprocess.CalledProcessError as exc:
                error = (exc.stderr or exc.stdout or str(exc)).strip()
                if "Cannot find module '@mathjax/src" in error:
                    error = "Install optional npm dependency '@mathjax/src' for MathJax rendering."
                return MarkdownProviderResult(state="failed", error=error, source=request.source)
            except subprocess.TimeoutExpired:
                return MarkdownProviderResult(
                    state="failed",
                    error=f"MathJax renderer exceeded {self.timeout}s timeout",
                    source=request.source,
                )
            except Exception as exc:
                return MarkdownProviderResult(state="failed", error=str(exc), source=request.source)

            svg = proc.stdout
            if not svg.strip():
                return MarkdownProviderResult(state="failed", error="MathJax produced empty SVG output.", source=request.source)
            svg_path.write_text(svg, encoding="utf-8")

            if self.output_format == "svg":
                return MarkdownProviderResult(state="ready", path=str(svg_path), source=request.source)

            try:
                import cairosvg  # type: ignore
            except Exception:
                return MarkdownProviderResult(
                    state="unsupported",
                    path=str(svg_path),
                    error="Install optional dependency 'cairosvg' to rasterize MathJax SVG to PNG.",
                    source=request.source,
                )

            try:
                cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(target))
            except Exception as exc:
                return MarkdownProviderResult(state="failed", error=str(exc), source=request.source)

            return MarkdownProviderResult(state="ready", path=str(target), source=request.source)
        finally:
            for scratch in (payload_path, script_path):
                try:
                    scratch.unlink()
                except OSError:
                    pass

    @staticmethod
    def _color_for_theme(theme: str) -> str:
        value = theme.lower()
        if value in {"dark", "dark-blue", "black"}:
            return "#dbe7f6"
        return "#172033"

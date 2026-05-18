# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Optional Mermaid diagram provider plugin.

The provider shells out to the ``mmdc`` CLI (``@mermaid-js/mermaid-cli``).
Because ``mmdc`` drives headless Chromium / Node, we apply defence-in-depth
around subprocess execution: bounded input size, restricted environment,
``securityLevel=strict`` config, and an rlimit on memory where available.
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


#: Hard cap on the diagram source size written to disk.
DEFAULT_MAX_SOURCE_BYTES = 64 * 1024


def _build_restricted_env(tmp_home: Path, extra_path: Optional[str] = None) -> "dict[str, str]":
    """Return a minimal environment suitable for ``subprocess.run``.

    Node is notoriously happy to pick up things like ``NODE_OPTIONS`` /
    ``NODE_EXTRA_CA_CERTS`` from the environment; we explicitly neutralise
    those and pass just enough for the tool to run.
    """

    path_parts: "list[str]" = []
    if extra_path:
        path_parts.append(extra_path)
    # Canonical system locations.  Intentionally small.
    if os.name == "nt":
        default_path = os.environ.get("SystemRoot", "C:\\Windows")
        path_parts.extend([default_path, os.path.join(default_path, "System32")])
    else:
        path_parts.extend(["/usr/local/bin", "/usr/bin", "/bin"])
    env: "dict[str, str]" = {
        "PATH": os.pathsep.join(path_parts),
        "HOME": str(tmp_home),
        "NODE_OPTIONS": "",
        # A handful of Node & headless-Chrome variables carry arbitrary data
        # from the parent environment. Wipe them.
        "NODE_EXTRA_CA_CERTS": "",
        "PUPPETEER_EXECUTABLE_PATH": os.environ.get("PUPPETEER_EXECUTABLE_PATH", ""),
        "CHROME_PATH": os.environ.get("CHROME_PATH", ""),
    }
    # Windows really does need a few extras for Node to even start.
    if os.name == "nt":
        for key in ("SystemRoot", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA"):
            if key in os.environ:
                env[key] = os.environ[key]
    else:
        # LANG + TERM keep CLI tools happy without leaking secrets.
        env["LANG"] = os.environ.get("LANG", "C.UTF-8")
        env["TERM"] = "dumb"
    return env


def _rlimit_preexec():
    """Return a ``preexec_fn`` that caps child memory, or None if unavailable.

    Uses ``resource.setrlimit`` to cap address space.  Not available on
    Windows; we return ``None`` there so ``subprocess.run`` skips the
    restriction (still gated behind timeouts).
    """

    if os.name == "nt":
        return None
    try:
        import resource  # type: ignore
    except ImportError:  # pragma: no cover -- resource ships with CPython on POSIX
        return None

    # 1 GiB of virtual memory.  Mermaid / Puppeteer are heavy but this caps
    # worst-case runaway processes.
    cap = 1024 * 1024 * 1024

    def _apply():  # pragma: no cover -- runs post-fork, hard to test
        try:
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        except (ValueError, OSError):
            pass

    return _apply


class MermaidCliProviderPlugin(AsyncProviderPlugin):
    """Render Mermaid diagrams through the optional ``mmdc`` CLI.

    This provider is intentionally optional.  It returns ``unsupported`` when
    ``mmdc`` is not on PATH, so applications can install
    ``@mermaid-js/mermaid-cli`` only when they need diagram rendering.
    """

    DEFAULT_CONCURRENCY = 2

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        *,
        executable: str = "mmdc",
        theme: str = "default",
        background: str = "transparent",
        output_format: str = "png",
        working_dir: Optional[Path] = None,
        timeout: float = 20.0,
        max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
        concurrency: int = DEFAULT_CONCURRENCY,
    ):
        super().__init__(cache_dir, concurrency=concurrency)
        self.executable = executable
        self.theme = theme
        self.background = background
        self.output_format = output_format.lstrip(".").lower()
        self.working_dir = working_dir
        self.timeout = timeout
        self.max_source_bytes = int(max_source_bytes)

    def can_handle(self, request: MarkdownProviderRequest) -> bool:
        return request.kind in {"diagram", "code_block"} and request.language.lower() == "mermaid"

    def cache_key(self, request: MarkdownProviderRequest) -> str:
        return stable_digest("mermaid", request.source, request.theme, self.theme, self.background, self.output_format)

    def _target_for_request(self, request: MarkdownProviderRequest) -> Path:
        ext = ".svg" if self.output_format == "svg" else ".png"
        return self.cache_dir / f"mermaid-{self.cache_key(request)}{ext}"

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
                error=f"Mermaid source exceeds {self.max_source_bytes} bytes",
                source=request.source,
            )

        local_bin = None
        if self.working_dir is not None:
            suffix = ".cmd" if os.name == "nt" else ""
            local_bin = self.working_dir / "node_modules" / ".bin" / f"{self.executable}{suffix}"
        executable = str(local_bin) if local_bin and local_bin.exists() else shutil.which(self.executable)
        if not executable:
            return MarkdownProviderResult(
                state="unsupported",
                error="Install optional dependency '@mermaid-js/mermaid-cli' in the provider folder or ensure 'mmdc' is on PATH.",
                source=request.source,
            )

        key = self.cache_key(request)
        # Random nonce keeps parallel runs from clobbering each other.
        nonce = secrets.token_hex(4)
        source_path = self.cache_dir / f"mermaid-{key}-{nonce}.mmd"
        config_path = self.cache_dir / f"mermaid-{key}-{nonce}.config.json"
        target = self._target_for_request(request)

        try:
            source_path.write_bytes(source_bytes)
            config_path.write_text(
                json.dumps({"securityLevel": "strict"}),
                encoding="utf-8",
            )

            cmd = [
                executable,
                "-i",
                str(source_path),
                "-o",
                str(target),
                "-t",
                self.theme,
                "-b",
                self.background,
                "-c",
                str(config_path),
            ]
            extra_path = None
            if self.working_dir is not None:
                extra_path = str(self.working_dir / "node_modules" / ".bin")
            tmp_home = self.cache_dir / "_subproc_home"
            tmp_home.mkdir(parents=True, exist_ok=True)
            env = _build_restricted_env(tmp_home, extra_path=extra_path)

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
                subprocess.run(cmd, **popen_kwargs)  # type: ignore[arg-type]
            except subprocess.CalledProcessError as exc:
                error = (exc.stderr or exc.stdout or str(exc)).strip()
                return MarkdownProviderResult(state="failed", error=error, source=request.source)
            except subprocess.TimeoutExpired:
                return MarkdownProviderResult(
                    state="failed",
                    error=f"mmdc exceeded {self.timeout}s timeout",
                    source=request.source,
                )
            except Exception as exc:
                return MarkdownProviderResult(state="failed", error=str(exc), source=request.source)
        finally:
            # Clean up scratch files.  Keep target image untouched.
            for scratch in (source_path, config_path):
                try:
                    scratch.unlink()
                except OSError:
                    pass

        return MarkdownProviderResult(state="ready", path=str(target), source=request.source)

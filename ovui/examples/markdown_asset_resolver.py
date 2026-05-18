# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Image source resolver for MarkdownWidget showcase scripts."""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import urllib.parse
import urllib.request
from pathlib import Path


_LEGACY_IMAGES_DIR = Path.home() / ".cache" / "omni-ui-markdown-images"
_DEFAULT_IMAGES_DIR = Path.home() / ".cache" / "ovui-markdown-images"

_log = logging.getLogger(__name__)


def migrate_legacy_images_dir(
    legacy_path: Path = _LEGACY_IMAGES_DIR,
    new_path: Path = _DEFAULT_IMAGES_DIR,
) -> None:
    """Rename the pre-ovui markdown image cache to the ovui-branded path.

    Idempotent and concurrent-safe (atomic ``os.replace`` on POSIX). Failures
    are logged and swallowed -- the caller proceeds with a fresh directory.
    """

    legacy_path = Path(legacy_path)
    new_path = Path(new_path)
    try:
        if legacy_path.exists() and not new_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(legacy_path, new_path)
            _log.info("ovui: migrated markdown image cache %s -> %s", legacy_path, new_path)
    except OSError as exc:
        _log.info("ovui: markdown image cache migration skipped (%s)", exc)


_migration_lock = threading.Lock()
_migration_done = False


def _run_default_migration_once() -> None:
    global _migration_done
    with _migration_lock:
        if _migration_done:
            return
        _migration_done = True
    migrate_legacy_images_dir()


_run_default_migration_once()


class MarkdownAssetResolver:
    """Resolve Markdown image sources to local raster files.

    The native widget decodes local raster files and data URIs. This helper
    covers the application-level cases: document-relative paths, provider-backed
    HTTP/S cache, and optional SVG rasterization when cairosvg is installed.
    """

    def __init__(self, markdown_path: Path, cache_dir: Path | None = None):
        self.markdown_path = markdown_path.resolve()
        self.base_dir = self.markdown_path.parent
        self.cache_dir = cache_dir or _DEFAULT_IMAGES_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def __call__(self, src: str) -> str:
        if not src or src.startswith("data:"):
            return ""
        if src.startswith(("http://", "https://")):
            return self._cache_http(src)
        if src.startswith("file:"):
            return self._resolve_svg(Path(src[5:])) if src.lower().endswith(".svg") else ""

        path = Path(src)
        if not path.is_absolute():
            path = (self.base_dir / path).resolve()
        if not path.exists():
            return ""
        return self._resolve_svg(path) if path.suffix.lower() == ".svg" else str(path)

    def _cache_http(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        ext = Path(parsed.path).suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".svg"}:
            ext = ".img"
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
        target = self.cache_dir / f"{digest}{ext}"
        if not target.exists():
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    target.write_bytes(response.read())
            except Exception as exc:
                print(f"image cache miss: {url}: {exc}")
                return ""
        return self._resolve_svg(target) if target.suffix.lower() == ".svg" else str(target)

    def _resolve_svg(self, path: Path) -> str:
        try:
            import cairosvg  # type: ignore
        except Exception:
            return ""

        target = self.cache_dir / f"{path.stem}-{hashlib.sha256(str(path).encode()).hexdigest()[:12]}.png"
        if not target.exists() or target.stat().st_mtime < path.stat().st_mtime:
            try:
                cairosvg.svg2png(url=str(path), write_to=str(target), output_width=256)
            except Exception as exc:
                print(f"svg rasterization failed: {path}: {exc}")
                return ""
        return str(target)

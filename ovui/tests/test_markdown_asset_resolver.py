# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the MarkdownWidget example asset resolver."""

import functools
import http.server
import socketserver
import sys
import tempfile
import threading
import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLES = _ROOT / "examples"
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))

from markdown_asset_resolver import MarkdownAssetResolver  # noqa: E402


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass


class TestMarkdownAssetResolver(unittest.TestCase):
    def test_relative_and_http_images_resolve_to_local_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            resolver = MarkdownAssetResolver(_EXAMPLES / "markdown_feature_showcase.md", cache_dir=cache_dir)

            relative = resolver("test_icon_32.png")
            self.assertTrue(relative.endswith("test_icon_32.png"))
            self.assertTrue(Path(relative).exists())

            handler = functools.partial(_QuietHandler, directory=str(_EXAMPLES))
            server = socketserver.TCPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                url = f"http://{host}:{port}/test_http_badge.png"
                downloaded = resolver(url)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=1)

            self.assertTrue(downloaded.endswith(".png"))
            self.assertTrue(Path(downloaded).exists())
            self.assertGreater(Path(downloaded).stat().st_size, 0)

    def test_svg_resolves_when_cairosvg_is_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolver = MarkdownAssetResolver(
                _EXAMPLES / "markdown_feature_showcase.md",
                cache_dir=Path(tmp) / "cache",
            )
            resolved = resolver("test_badge.svg")

            try:
                import cairosvg  # noqa: F401
            except Exception:
                self.assertEqual(resolved, "")
            else:
                self.assertTrue(resolved.endswith(".png"))
                self.assertTrue(Path(resolved).exists())

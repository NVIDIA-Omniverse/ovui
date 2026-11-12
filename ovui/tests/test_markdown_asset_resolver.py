# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

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

    def test_svg_resolves_to_the_svg_file_for_the_native_widget(self):
        # The widget draws the SVG file itself, as ui.Image does, with or
        # without cairosvg: the resolver gives it the file, not a PNG copy.
        with tempfile.TemporaryDirectory() as tmp:
            resolver = MarkdownAssetResolver(
                _EXAMPLES / "markdown_feature_showcase.md",
                cache_dir=Path(tmp) / "cache",
            )
            resolved = resolver("test_badge.svg")

            self.assertEqual(resolved, str((_EXAMPLES / "test_badge.svg").resolve()))
            self.assertEqual(list((Path(tmp) / "cache").iterdir()), [], "no PNG copy is written")

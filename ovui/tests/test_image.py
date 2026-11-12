# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""``ui.Image`` with a local file source in the standalone build.

Before the standalone ``IImageBackend`` was registered, ``ui.Image(path)``
drew nothing and logged nothing. These tests draw a solid-colour PNG through
each kind of source and read the pixels back from a real frame capture, so they
do not depend on per-backend golden images.
"""

from __future__ import annotations

import os
import pathlib
import tempfile
import zlib

import omni.ui as ui
from omni.ui import _ui
from test_base import OmniUiTest

_SIZE = 64
_RED = (255, 0, 0)


def _write_png(path: pathlib.Path, rgb, size: int = 8, odd_rgb=None) -> None:
    """Write an opaque RGBA8 PNG without requiring Pillow; ``odd_rgb`` colours odd columns."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return len(payload).to_bytes(4, "big") + tag + payload + zlib.crc32(tag + payload).to_bytes(4, "big")

    header = size.to_bytes(4, "big") + size.to_bytes(4, "big") + bytes((8, 6, 0, 0, 0))
    row = b"".join(bytes((*(odd_rgb if x % 2 and odd_rgb else rgb), 255)) for x in range(size))
    raw = b"".join(b"\x00" + row for _ in range(size))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    )


class TestImageLocalFile(OmniUiTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._root = pathlib.Path(self._tmp.name)

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self._tmp.cleanup()

    async def _center_pixel(self, source: str, image_size: int = _SIZE):
        """Draw ``ui.Image(source)`` over a black window and return its centre pixel."""
        window = await self.create_test_window(_SIZE, _SIZE)
        with window.frame:
            ui.Image(source, width=image_size, height=image_size, fill_policy=ui.FillPolicy.STRETCH)
        await self.wait_n_updates(4)

        capture = self._root / "capture.png"
        self.assertTrue(_ui._schedule_screenshot(str(capture)), "screenshot request was refused")
        for _ in range(10):
            await self.wait_n_updates(1)
            if _ui._poll_screenshot_done() and capture.exists():
                break
        self.assertTrue(capture.exists(), "screenshot was not written")

        from PIL import Image

        with Image.open(capture) as img:
            return img.convert("RGB").getpixel((image_size // 2, image_size // 2))

    def _assert_red(self, pixel, where: str) -> None:
        for got, want in zip(pixel, _RED):
            self.assertLessEqual(abs(got - want), 8, f"{where}: centre pixel is {pixel}, expected {_RED}")

    async def test_local_path_draws_the_image(self):
        png = self._root / "red.png"
        _write_png(png, _RED)
        self._assert_red(await self._center_pixel(str(png)), "ui.Image(path)")

    async def test_file_url_draws_the_image(self):
        png = self._root / "dir with space" / "red.png"
        png.parent.mkdir()
        _write_png(png, _RED)
        url = png.as_uri()  # file:///.../dir%20with%20space/red.png
        self.assertIn("%20", url)
        self._assert_red(await self._center_pixel(url), "ui.Image(file:// URL)")

    async def test_shrunk_image_is_smooth(self):
        # 1 px white and black stripes drawn 3 times smaller must blend to grey
        # through the mip chain, not show single stripes (jagged small icons).
        png = self._root / "stripes.png"
        _write_png(png, (255, 255, 255), size=48, odd_rgb=(0, 0, 0))
        pixel = await self._center_pixel(str(png), image_size=16)
        for channel in pixel:
            self.assertTrue(64 <= channel <= 192, f"centre pixel is {pixel}, expected grey")

    async def test_missing_file_logs_an_error(self):
        missing = self._root / "does_not_exist.png"
        log = self._root / "stderr.txt"

        saved = os.dup(2)
        try:
            with open(log, "wb") as f:
                os.dup2(f.fileno(), 2)
                pixel = await self._center_pixel(str(missing))
        finally:
            os.dup2(saved, 2)
            os.close(saved)

        self.assertEqual(pixel, (0, 0, 0), "nothing must be drawn for a missing file")
        text = log.read_text(errors="replace")
        self.assertIn("[error] ui.Image: cannot load", text)
        self.assertIn(str(missing), text)

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The clear color of the headless Vulkan frame.

A headless ovui program can export only its UI (for example a gizmo) and
composite it over a frame from another renderer. For that, the pixels that no
widget draws must be transparent. The tests draw a small UI in a window with no
background, take the platform screenshot (the Vulkan read-back of the same
offscreen image that ``headless_frame`` exports) and read the file with Pillow:

* by default, the pixels that no widget draws keep the opaque default color;
* after ``set_clear_color(0, 0, 0, 0)`` they are ``(0, 0, 0, 0)``, and the drawn
  pixels keep their alpha; the file holds straight color, as PNG defines;
* the transparent ``.png`` and ``.bmp`` files, composited over a color by
  Pillow, are the same as the frame drawn on that color: there is no opaque
  rectangle and there are no dark shapes or edges;
* a value that is not valid raises ``ValueError`` and the frame keeps the
  current color.

On another backend (a window or headless EGL) ``set_clear_color`` raises
``RuntimeError``. ``test_headless_frame.py`` checks the CUDA export.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

import numpy
import omni.ui as ui
from omni.ui import _ui
from omni.ui import standalone
from test_base import OmniUiTest, _backend_tag

# Like standalone::init(): OMNIUI_HEADLESS=1 starts headless Vulkan whatever
# OMNIUI_BACKEND says, unless OMNIUI_HEADLESS_GL=1 selects headless EGL.
_IS_HEADLESS_VULKAN = os.environ.get("OMNIUI_HEADLESS") in ("1", "true") and _backend_tag() == "vulkan"

_SIZE = 96
# A point far from the test window: no widget draws there.
_UNTOUCHED = (_SIZE + 40, _SIZE + 40)
# The default clear (0.12, 0.13, 0.14, 1.0) in 8-bit values.
_DEFAULT_RGBA = (31, 33, 36, 255)
_RED = ui.color(1.0, 0.0, 0.0, 1.0)
_HALF_GREEN = ui.color(0.0, 1.0, 0.0, 0.5)
_BLUE = ui.color(0.2, 0.4, 1.0, 1.0)


@unittest.skipUnless(_IS_HEADLESS_VULKAN, "the clear color needs the headless Vulkan backend (OMNIUI_HEADLESS=1)")
class TestHeadlessClearColor(OmniUiTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="ovui_clear_color_")
        self._root = pathlib.Path(self._tmp.name)
        self._window = None
        # The backend can outlive this test (a run without --forked): keep its
        # state, and draw no software cursor into the pixels that are read.
        self._saved_clear_color = standalone.get_clear_color()
        self._saved_cursor = standalone.is_software_cursor_enabled()
        standalone.set_software_cursor(False)

    async def asyncTearDown(self):
        standalone.set_clear_color(*self._saved_clear_color)
        standalone.set_software_cursor(self._saved_cursor)
        if self._window is not None:
            self._window.destroy()
            self._window = None
        await super().asyncTearDown()
        self._tmp.cleanup()

    async def _draw_ui(self):
        """An opaque red square, a half-transparent green square, a blue circle and a label.

        The window has no background, so every other pixel keeps the clear color.
        """
        flags = (
            ui.WINDOW_FLAGS_NO_TITLE_BAR
            | ui.WINDOW_FLAGS_NO_RESIZE
            | ui.WINDOW_FLAGS_NO_MOVE
            | ui.WINDOW_FLAGS_NO_SCROLLBAR
            | ui.WINDOW_FLAGS_NO_BACKGROUND
        )
        self._window = ui.Window(
            "clear color test",
            dockPreference=ui.DockPreference.DISABLED,
            flags=flags,
            width=_SIZE,
            height=_SIZE,
            position_x=0,
            position_y=0,
        )
        self._window.frame.set_style({"Window": {"border_color": 0x0, "border_width": 0}})
        with self._window.frame:
            with ui.VStack(spacing=4):
                with ui.HStack(height=30, spacing=6):
                    ui.Rectangle(width=30, style={"background_color": _RED})
                    ui.Rectangle(width=30, style={"background_color": _HALF_GREEN})
                with ui.HStack(height=30, spacing=6):
                    ui.Circle(width=30, radius=14, style={"background_color": _BLUE})
                    ui.Label("Ab", style={"color": ui.color(1.0, 1.0, 1.0, 1.0), "font_size": 18})
        await self.wait_n_updates(4)

    async def _capture(self, name: str, suffix: str = ".png"):
        """Take a screenshot and return the file, read by Pillow, as an RGBA image."""
        from PIL import Image

        path = self._root / f"{name}{suffix}"
        self.assertTrue(_ui._schedule_screenshot(str(path)), "the screenshot request must be accepted")
        for _ in range(6):
            await self.wait_n_updates(1)
            if path.exists() and _ui._poll_screenshot_done():
                break
        self.assertTrue(path.exists(), "the screenshot must be written")
        return Image.open(path).convert("RGBA")

    def _count(self, picture, predicate) -> int:
        area = numpy.asarray(picture.crop((0, 0, _SIZE, _SIZE))).reshape(-1, 4)
        return sum(1 for pixel in area.tolist() if predicate(tuple(pixel)))

    async def test_default_clear_is_unchanged(self):
        await self._draw_ui()
        picture = await self._capture("default")
        self.assertEqual(picture.getpixel(_UNTOUCHED), _DEFAULT_RGBA)
        self.assertEqual(picture.getpixel((picture.width - 1, picture.height - 1)), _DEFAULT_RGBA)

    async def test_transparent_clear_keeps_drawn_pixels(self):
        standalone.set_clear_color(0.0, 0.0, 0.0, 0.0)
        await self._draw_ui()
        picture = await self._capture("transparent")

        self.assertEqual(picture.getpixel(_UNTOUCHED), (0, 0, 0, 0))
        self.assertEqual(picture.getpixel((picture.width - 1, picture.height - 1)), (0, 0, 0, 0))
        # The opaque red square stays opaque red.
        self.assertGreater(self._count(picture, lambda p: p == (255, 0, 0, 255)), 600)
        # The half-transparent green square keeps half alpha, and the PNG file
        # holds its straight color: full green.
        half = self._count(picture, lambda p: p[:3] == (0, 255, 0) and abs(p[3] - 128) <= 1)
        self.assertGreater(half, 600, "the half-transparent square must be green with half alpha")
        # Smooth edges of the circle and the text have partial alpha.
        partial = self._count(picture, lambda p: 0 < p[3] < 255)
        self.assertGreater(partial, 30, "the edges of the circle and the text must have partial alpha")

    async def test_files_composite_like_a_direct_draw(self):
        # A normal image reader takes the alpha of a PNG or BMP file as
        # straight. Pillow composites the transparent file over a color; the
        # result must equal the same UI drawn on that color.
        from PIL import Image

        standalone.set_clear_color(0.0, 0.0, 0.0, 0.0)
        await self._draw_ui()
        files = {suffix: await self._capture("overlay", suffix) for suffix in (".png", ".bmp")}
        for background in ((0.0, 0.0, 0.0), (0.2, 0.5, 0.8)):
            standalone.set_clear_color(*background, 1.0)
            direct = numpy.asarray(await self._capture("direct"), dtype=int)
            self.assertEqual(direct[_UNTOUCHED[1], _UNTOUCHED[0], 3], 255)
            plain = Image.new("RGBA", files[".png"].size, tuple(round(c * 255) for c in background) + (255,))
            for suffix, overlay in files.items():
                composite = numpy.asarray(Image.alpha_composite(plain, overlay), dtype=int)
                worst = int(numpy.abs(composite[..., :3] - direct[..., :3]).max())
                self.assertLessEqual(
                    worst, 2, f"the {suffix} file composited over {background} must equal the UI drawn on it"
                )

    async def test_invalid_value_keeps_the_color(self):
        standalone.set_clear_color(0.0, 0.0, 0.0, 0.0)
        for values, words in (
            ((float("nan"), 0.0, 0.0, 1.0), "red is nan"),
            ((0.0, -0.1, 0.0, 1.0), "green is -0.1"),
            ((0.0, 0.0, 1.5, 1.0), "blue is 1.5"),
            ((0.0, 0.0, 0.0, float("inf")), "alpha is inf"),
            ((0.0, 0.0, 0.0, 1.0000001), "alpha is "),
            ((0.12, 0.13, 0.14, 0.0), "red 0.12 is greater than alpha 0"),
        ):
            with self.assertRaises(ValueError) as caught:
                standalone.set_clear_color(*values)
            self.assertIn(words, str(caught.exception))
            if values[3] == 1.0000001:
                shown_alpha = str(caught.exception).split("alpha is ")[1].split(";")[0]
                self.assertGreater(float(shown_alpha), 1.0, "the message must show why alpha was refused")
        await self._draw_ui()
        picture = await self._capture("kept")
        self.assertEqual(picture.getpixel(_UNTOUCHED), (0, 0, 0, 0), "a refused value must not change the color")


@unittest.skipIf(_IS_HEADLESS_VULKAN, "on headless Vulkan the clear color is used")
class TestClearColorOtherBackends(unittest.TestCase):
    def test_refused_by_other_backends(self):
        standalone.init("test_headless_clear_color", 64, 64)
        with self.assertRaises(RuntimeError) as caught:
            standalone.set_clear_color(0.0, 0.0, 0.0, 0.0)
        self.assertIn("applies only to the headless Vulkan backend", str(caught.exception))
        self.assertIsNone(standalone.get_clear_color())


class TestClearColorBeforeInit(unittest.TestCase):
    def test_refused_before_init(self):
        # A new process, so that no other test has started the backend.
        code = (
            "from omni.ui import standalone\n"
            "try:\n"
            "    standalone.set_clear_color(0.0, 0.0, 0.0, 0.0)\n"
            "except RuntimeError as error:\n"
            "    print('RuntimeError:', error)\n"
            "print('get:', standalone.get_clear_color())\n"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RuntimeError:", result.stdout)
        self.assertIn("call init() first", result.stdout)
        self.assertIn("get: None", result.stdout)


if __name__ == "__main__":
    unittest.main()

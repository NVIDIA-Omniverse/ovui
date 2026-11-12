# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""An ``.svg`` file in ``ui.ImageWithProvider``, ``ui.Image`` and
``ui.MarkdownWidget`` in the standalone backend.

The standalone backend registers its SVG rasterizer inside ``ui.init``. Without
that registration an ``.svg`` URL draws nothing and logs nothing. The tests use
the application path: ``OmniUiTest`` calls ``standalone.init`` (the call behind
``ui.init``), a test puts a widget with an ``.svg`` path in a window, takes a
real screenshot, reads the pixels and reads the log. They register no
rasterizer themselves, so they fail when ``ui.init`` does not register one.

``ui.Image`` must draw the file as ``ui.ImageWithProvider`` draws it: the same
reference image, and no error (before, it drew nothing and logged "SVG files
are not supported"). ``ui.MarkdownWidget`` must draw the file at its own size
(before, it showed its image placeholder). It must draw the same picture for
the forms of the same SVG that the SVG reader accepts: elements with a
namespace prefix (``<s:svg xmlns:s=...>``; before, the widget showed its
placeholder and logged nothing), and a ``data:image/svg+xml;base64`` URI that
ends with one or two '=' of padding (before, the zero bytes that the base64
decoder gives for them made the XML reader refuse the text).

Each test checks the build it runs in. They never skip.

* SVG option ON (the default): the shapes draw. The colors of four known points
  must be right; they give a clear message when nothing is drawn, which is what
  happens when ``ui.init`` does not register the rasterizer. The whole
  screenshot must match the stored reference image
  ``tests/golden/shared/StandaloneSvgImage.shapes.png``, which fails on a wrong
  shape, edge or scale. Nothing is logged for the file. The Markdown
  screenshots must match ``tests/golden/shared/StandaloneSvgImage.markdown.png``.
* SVG option OFF (``-DOMNIUI_ENABLE_SVG=OFF``): the area stays empty and the
  cause is logged. The screenshot must match the reference image
  ``tests/golden/shared/StandaloneSvgImage.svg_off.png`` (the black window),
  every pixel must be the background color, and the log must have one error
  that names the file and the option. The Markdown screenshots must match
  ``tests/golden/shared/StandaloneSvgImage.markdown_svg_off.png`` (the image
  placeholder), and the log must have one error that names the option.

The option is read from the built library (``_ui._is_svg_rasterizer_built_in()``),
not from the environment of the test run. The CI job "B1 Vulkan-lavapipe, SVG
option OFF" builds that configuration and runs this file; the other B1 and the
B3 jobs run it on the default build.

The screenshot comes from the platform screenshot request that works on the
Vulkan and the EGL backend alike, so one reference image serves both. For this
test, the OpenGL read-back that ``finalize_test`` uses on EGL gave a frame of
one grey color, so a reference image taken that way could not check the picture.
"""

from __future__ import annotations

import base64
import os
import pathlib
import re
import tempfile

import omni.ui as ui
from omni.ui import _ui
from test_base import CAPTURED_DIR, GOLDEN_DIR, OmniUiTest

_SIZE = 128
# Mean per-channel difference (0..255), the metric of the other golden tests. The
# limit is 0.05, not their 0.01, so that the Vulkan and EGL captures (they differ
# by about 0.02) share one reference image; the shape, scale and edge errors the
# test must catch differ by much more (see tests/README.md).
_THRESHOLD = 0.05
_SHAPES_REFERENCE = GOLDEN_DIR / "shared" / "StandaloneSvgImage.shapes.png"
_SVG_OFF_REFERENCE = GOLDEN_DIR / "shared" / "StandaloneSvgImage.svg_off.png"
# The Markdown widget shows the image at the size of the file (128 x 128), as a
# PNG file is shown, in a window that is larger than it.
_MARKDOWN_WINDOW_SIZE = 2 * _SIZE
_MARKDOWN_REFERENCE = GOLDEN_DIR / "shared" / "StandaloneSvgImage.markdown.png"
_MARKDOWN_SVG_OFF_REFERENCE = GOLDEN_DIR / "shared" / "StandaloneSvgImage.markdown_svg_off.png"


def _svg_built_in() -> bool:
    """False only when the library was built with ``OMNIUI_ENABLE_SVG=OFF``.

    The value comes from the compiled library. A library older than the option
    has no such query and no OFF build: there the test expects the SVG to draw,
    so it starts the backend and fails when ``ui.init`` registers no rasterizer.
    """
    query = getattr(_ui, "_is_svg_rasterizer_built_in", None)
    return True if query is None else bool(query())


_SVG_BUILT_IN = _svg_built_in()

# An asymmetric picture on a transparent background, so that a flip, a shift, a
# wrong scale, a missing shape or a wrong edge changes many pixels: a red circle,
# a green triangle, a blue rounded rectangle with a yellow stroke and a white
# line with round caps. Coordinates are in the 128 x 128 user space of the SVG.
_SHAPES_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">'
    '<circle cx="40" cy="44" r="28" fill="#e53935"/>'
    '<polygon points="10,120 36,84 62,120" fill="#43a047"/>'
    '<rect x="72" y="70" width="48" height="40" rx="8" ry="8" fill="#1e88e5" stroke="#fdd835" stroke-width="4"/>'
    '<line x1="72" y1="14" x2="120" y2="58" stroke="#ffffff" stroke-width="4" stroke-linecap="round"/>'
    "</svg>"
)

# The same picture with a namespace prefix on each element, a form that the
# SVG reader accepts: <s:svg xmlns:s="http://www.w3.org/2000/svg"> ... </s:svg>.
_PREFIXED_SHAPES_SVG = re.sub(r"<(/?)(\w+)", r"<\1s:\2", _SHAPES_SVG).replace("xmlns=", "xmlns:s=")


def _shapes_svg_data_uri(padding: int) -> str:
    """A ``data:image/svg+xml;base64`` URI of the shapes SVG whose base64 text
    ends with ``padding`` '=' characters. White space after the root element
    (allowed in XML) sets the byte count."""
    text = _SHAPES_SVG
    while len(text) % 3 != (0, 2, 1)[padding]:
        text += " "
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    assert len(encoded) - len(encoded.rstrip("=")) == padding
    return f"data:image/svg+xml;base64,{encoded}"


# Points well inside each shape, and a point of the transparent background.
_RED_POINT = (40, 44)
_GREEN_POINT = (36, 108)
_BLUE_POINT = (96, 90)
_BACKGROUND_POINT = (4, 4)


def _near(pixel, rgb, tolerance=12) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(pixel[:3], rgb))


class TestStandaloneSvgImage(OmniUiTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        # A new folder for each run: the test never touches other files.
        self._tmp = tempfile.TemporaryDirectory(prefix="ovui_svg_image_")
        self._root = pathlib.Path(self._tmp.name)
        self._svg = self._root / "shapes.svg"
        self._svg.write_text(_SHAPES_SVG, encoding="utf-8")

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self._tmp.cleanup()

    async def _capture(self):
        """Take a screenshot of the window and return it as an RGBA PIL image."""
        from PIL import Image

        path = self._root / "capture.png"
        self.assertTrue(_ui._schedule_screenshot(str(path)), "the screenshot request must be accepted")
        for _ in range(6):
            await self.wait_n_updates(1)
            if path.exists() and _ui._poll_screenshot_done():
                break
        self.assertTrue(path.exists(), "the screenshot must be written")
        return Image.open(path).convert("RGBA")

    async def _draw_svg_and_capture(self, make_widget=None, size=_SIZE):
        """Draw the SVG in a window and return the screenshot and the log text.

        ``make_widget`` builds the widget inside the window frame; the default
        is the ``ImageWithProvider`` of the SVG. The log is what the library
        writes to the standard error stream while the image is made and drawn.
        """
        if make_widget is None:

            def make_widget():
                return ui.ImageWithProvider(
                    str(self._svg), width=_SIZE, height=_SIZE, fill_policy=ui.IwpFillPolicy.IWP_STRETCH
                )

        log = self._root / "stderr.txt"
        saved = os.dup(2)
        try:
            with open(log, "wb") as f:
                os.dup2(f.fileno(), 2)
                window = await self.create_test_window(size, size)
                with window.frame:
                    self._image = make_widget()
                await self.wait_n_updates(6)
                picture = await self._capture()
        finally:
            os.dup2(saved, 2)
            os.close(saved)
        return picture, log.read_text(errors="replace")

    async def test_svg_file_draws_as_the_build_option_says(self):
        picture, log = await self._draw_svg_and_capture()
        self._check_shapes_as_the_build_option_says(picture, log)
        await self.finalize_test_no_image()
        self._image = None

    async def test_image_draws_the_svg_file_as_image_with_provider(self):
        # The call of the report: ui.Image(svg_path, width=..., height=...).
        picture, log = await self._draw_svg_and_capture(
            lambda: ui.Image(str(self._svg), width=_SIZE, height=_SIZE)
        )
        self.assertNotIn("SVG files are not supported", log)
        self._check_shapes_as_the_build_option_says(picture, log)
        await self.finalize_test_no_image()
        self._image = None

    async def test_markdown_draws_the_svg_file_at_its_own_size(self):
        await self._check_markdown_image(self._svg.as_posix())

    async def test_markdown_draws_a_namespace_prefixed_svg_file(self):
        prefixed = self._root / "prefixed_shapes.svg"
        prefixed.write_text(_PREFIXED_SHAPES_SVG, encoding="utf-8")
        await self._check_markdown_image(prefixed.as_posix())

    async def test_markdown_draws_a_base64_svg_data_uri_with_one_padding_character(self):
        await self._check_markdown_image(_shapes_svg_data_uri(padding=1))

    async def test_markdown_draws_a_base64_svg_data_uri_with_two_padding_characters(self):
        await self._check_markdown_image(_shapes_svg_data_uri(padding=2))

    async def _check_markdown_image(self, source: str) -> None:
        """Show the shapes SVG from ``source`` in ``ui.MarkdownWidget`` and check
        the picture and the log as the build option says. Each form of the SVG
        must give the same picture."""
        window_size = _MARKDOWN_WINDOW_SIZE
        picture, log = await self._draw_svg_and_capture(
            lambda: ui.MarkdownWidget(f"![shapes]({source})\n"), size=window_size
        )
        area = picture.crop((0, 0, window_size, window_size))
        shape_colors = {"red": (0xE5, 0x39, 0x35), "green": (0x43, 0xA0, 0x47), "blue": (0x1E, 0x88, 0xE5)}
        counts = {name: 0 for name in shape_colors}
        for count, pixel in area.getcolors(window_size * window_size):
            for name, rgb in shape_colors.items():
                if _near(pixel, rgb):
                    counts[name] += count
        # The SVG errors of the Markdown widget name no file.
        svg_errors = [line for line in log.splitlines() if "[error]" in line and "SVG" in line]

        if _SVG_BUILT_IN:
            # The circle has about 2,400 pixels, the triangle about 900 and the
            # rectangle inside its stroke about 1,700 at the size of the file;
            # the image placeholder has none of these colors.
            self.assertGreater(counts["red"], 2000, f"the circle must be drawn, got {counts}")
            self.assertGreater(counts["green"], 700, f"the triangle must be drawn, got {counts}")
            self.assertGreater(counts["blue"], 1400, f"the rectangle must be drawn, got {counts}")
            # The size of the file, not twice the size: the shapes span x 10..122
            # and y 12..120 of the 128 x 128 SVG.
            box = area.convert("L").point(lambda v: 255 if v > 40 else 0).getbbox()
            self.assertIsNotNone(box, "the SVG must be drawn")
            width, height = box[2] - box[0], box[3] - box[1]
            self.assertTrue(100 <= width <= 124 and 96 <= height <= 124, f"the SVG must be drawn at its own size, got {box}")
            self.assertEqual(svg_errors, [], "a good SVG file must log no error")
            # Shape, edges and scale: the whole screenshot must match the reference image.
            self._compare_with_reference(picture, _MARKDOWN_REFERENCE, window_size)
        else:
            self.assertEqual(counts, {name: 0 for name in shape_colors}, "without the SVG option nothing is drawn")
            self.assertEqual(len(svg_errors), 1, f"the image must log one error with the cause, got: {log!r}")
            self.assertIn("SVG: cannot draw an image", svg_errors[0])
            self.assertIn("OMNIUI_ENABLE_SVG=OFF", svg_errors[0], "the error must name the build option")
            # The image placeholder of the widget, and nothing else.
            self._compare_with_reference(picture, _MARKDOWN_SVG_OFF_REFERENCE, window_size)
        await self.finalize_test_no_image()
        self._image = None

    def _check_shapes_as_the_build_option_says(self, picture, log) -> None:
        errors = [line for line in log.splitlines() if "[error]" in line and str(self._svg) in line]

        if _SVG_BUILT_IN:
            # Registration: with no rasterizer registered the window stays black.
            red = picture.getpixel(_RED_POINT)
            green = picture.getpixel(_GREEN_POINT)
            blue = picture.getpixel(_BLUE_POINT)
            background = picture.getpixel(_BACKGROUND_POINT)
            self.assertTrue(_near(red, (0xE5, 0x39, 0x35)), f"the circle must be red, got {red}")
            self.assertTrue(_near(green, (0x43, 0xA0, 0x47)), f"the triangle must be green, got {green}")
            self.assertTrue(_near(blue, (0x1E, 0x88, 0xE5)), f"the rounded rectangle must be blue, got {blue}")
            self.assertEqual(
                background[:3], (0, 0, 0), f"the transparent background must show black, got {background}"
            )

            # Shape, edges and scale: the whole screenshot must match the reference image.
            self._compare_with_reference(picture, _SHAPES_REFERENCE)
            self.assertEqual(errors, [], "a good SVG file must log no error")
        else:
            # Option OFF: nothing is drawn, and the log says why.
            self._compare_with_reference(picture, _SVG_OFF_REFERENCE)
            area = picture.crop((0, 0, _SIZE, _SIZE))
            self.assertEqual(
                area.getcolors(1),
                [(_SIZE * _SIZE, (0, 0, 0, 255))],
                "without the SVG option nothing is drawn: the window must stay black",
            )
            self.assertEqual(len(errors), 1, f"the file must log one error with the cause, got: {log!r}")
            self.assertIn("SVG: cannot draw", errors[0])
            self.assertIn("OMNIUI_ENABLE_SVG=OFF", errors[0], "the error must name the build option")

    def _compare_with_reference(self, picture, reference: pathlib.Path, size: int = _SIZE) -> None:
        from compare_utils import CompareMetric, compare

        captured = CAPTURED_DIR / reference.name
        diff = CAPTURED_DIR / f"diff_{reference.name}"
        captured.parent.mkdir(parents=True, exist_ok=True)
        # The headless Vulkan screenshot is the size of the offscreen image, so
        # keep the area of the test window, as finalize_test does.
        picture.crop((0, 0, size, size)).save(captured)

        if os.environ.get("OMNI_UI_GENERATE_GOLDEN", "").strip() == "1":
            reference.parent.mkdir(parents=True, exist_ok=True)
            reference.write_bytes(captured.read_bytes())
            return
        # Only OMNI_UI_GENERATE_GOLDEN=1 creates the reference image.
        self.assertTrue(reference.exists(), f"Golden reference missing: {reference}")

        error = compare(reference, captured, diff, threshold=_THRESHOLD, cmp_metric=CompareMetric.MEAN_ERROR)
        self.assertLess(
            error,
            _THRESHOLD,
            f"Golden image mismatch for {reference.name}: error={error:.6f} >= threshold={_THRESHOLD} "
            f"(metric={CompareMetric.MEAN_ERROR}); see {captured} and {diff}",
        )

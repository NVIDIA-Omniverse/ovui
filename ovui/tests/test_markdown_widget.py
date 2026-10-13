# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Visual smoke tests for the native MarkdownWidget."""

import unittest  # noqa: F401 -- retained for future skip decorators
from pathlib import Path

from test_base import OmniUiTest
import omni.ui as ui
from omni.ui import testing


_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "markdown" / "quality_harness" / "corpus" / "qa" / "11_p0_correctness.md"
)


def _resolve_image(src: str) -> str:
    if not src or src.startswith(("data:", "http://", "https://", "file:")):
        return ""
    path = Path(src)
    if not path.is_absolute():
        path = (_FIXTURE.parent / path).resolve()
    return str(path) if path.exists() else ""


class TestMarkdownWidget(OmniUiTest):
    def _style(self):
        return {
            "MarkdownWidget": {
                "font_size": 13,
                "color": ui.color(0.10, 0.12, 0.16),
                "secondary_color": ui.color(0.02, 0.05, 0.10),
                "secondary_selected_color": ui.color(0.0, 0.30, 0.64),
                "secondary_background_color": ui.color(0.92, 0.95, 0.98, 0.92),
                "border_color": ui.color(0.70, 0.76, 0.84),
            },
            "MarkdownWidget.Link": {
                "color": ui.color(0.0, 0.28, 0.62),
                "selected_color": ui.color(0.0, 0.42, 0.86),
            },
        }

    async def _render_source(self, source: str, *, threshold: float = 0.02):
        window = await self.create_test_window(width=256, height=256)

        with window.frame:
            with ui.ZStack(width=ui.Fraction(1), height=ui.Fraction(1), style=self._style()):
                ui.Rectangle(style={"background_color": ui.color(0.985, 0.99, 1.0)})
                with ui.ScrollingFrame(
                    width=ui.Fraction(1),
                    height=ui.Fraction(1),
                    style={"ScrollingFrame": {"background_color": 0x00000000}},
                ):
                    widget = ui.MarkdownWidget(source, width=ui.Fraction(1))
                    widget.set_image_url_provider_fn(_resolve_image)

        await self.finalize_test(threshold=threshold)

    async def test_p0_correctness(self):
        await self._render_source(_FIXTURE.read_text(encoding="utf-8"))

    async def test_p0_entities_and_attributes(self):
        source = (
            "# Entities\n\n"
            "Named: &AElig; &frac34; &ClockwiseContourIntegral; &ngE;.\n\n"
            "Numeric: &#35; &#x22; &#0; unknown &MadeUpEntity;.\n\n"
            "[title link](https://example.com?a=1&amp;b=2 \"Title &copy;\")\n\n"
            "![icon &copy;](../../examples/test_icon_32.png \"Image &trade;\")"
        )
        await self._render_source(source)

    async def test_p0_rich_table_cells(self):
        source = (
            "# Table Cells\n\n"
            "| Type | Rich content |\n"
            "|:---|:---|\n"
            "| Style | **bold**, *italic*, ~~strike~~, `code` |\n"
            "| Link | [cell link](https://example.com?a=1&amp;b=2 \"Cell &copy;\") wraps |\n"
            "| Image | ![icon &copy;](../../examples/test_icon_32.png \"Cell image\") text |"
        )
        await self._render_source(source)

    async def test_p0_raw_html_literal(self):
        source = (
            "# Raw HTML\n\n"
            "Inline stays visible: <kbd>Ctrl</kbd> + <span data-x=\"1\">K</span>.\n\n"
            "<div class=\"note\">\n"
            "  <strong>HTML block source is visible.</strong>\n"
            "</div>\n"
        )
        await self._render_source(source)

    # ------------------------------------------------------------------
    # ID-addressable replacements.  The previous pixel-scan tests
    # (`test_p0zz_code_block_copy_button` and `test_p1_heading_anchor_click`)
    # were deleted once the widget exposed `copy_code_block` /
    # `get_outline` / `scroll_to_anchor`; see the widget header for the
    # C++ API those map onto.
    # ------------------------------------------------------------------

    async def test_copy_button_via_id(self):
        """Drive the code-block copy path through the public API.

        The renderer emits a focusable ImGui item for the visual copy
        button; `copy_code_block(index)` is the deterministic equivalent
        we exercise here so the test doesn't depend on focus plumbing in
        the test harness.
        """
        window = await self.create_test_window(width=256, height=256)
        source = "```python\nalpha = 1\nbeta = alpha + 1\n```"

        with window.frame:
            with ui.ZStack(width=ui.Fraction(1), height=ui.Fraction(1), style=self._style()):
                ui.Rectangle(style={"background_color": ui.color(0.985, 0.99, 1.0)})
                widget = ui.MarkdownWidget(source, width=ui.Fraction(1))

        await self.wait_n_updates(4)
        testing.set_clipboard_text("")
        self.assertTrue(widget.copy_code_block(0))
        self.assertEqual(testing.get_clipboard_text(), "alpha = 1\nbeta = alpha + 1")
        await self.finalize_test_no_image()

    async def test_heading_anchor_via_id(self):
        """Navigate to a heading via the outline API.

        `get_outline()` mirrors the ImGui-focusable heading-anchor items
        emitted by the renderer.  `scroll_to_anchor` is the programmatic
        equivalent of activating that focusable anchor.
        """
        window = await self.create_test_window(width=256, height=180)
        source = "# Anchor Target\n\nBody text."

        with window.frame:
            with ui.ZStack(width=ui.Fraction(1), height=ui.Fraction(1), style=self._style()):
                ui.Rectangle(style={"background_color": ui.color(0.985, 0.99, 1.0)})
                widget = ui.MarkdownWidget(source, width=ui.Fraction(1))

        await self.wait_n_updates(4)
        outline = widget.get_outline()
        self.assertEqual(len(outline), 1)
        self.assertEqual(outline[0]["slug"], "anchor-target")
        self.assertEqual(outline[0]["level"], 1)
        self.assertTrue(widget.scroll_to_anchor("anchor-target"))
        await self.finalize_test_no_image()

    async def test_glyph_forms_do_not_depend_on_atlas_bake_order(self):
        """A character must render the same whether or not
        the font atlas had already rasterized it.

        The widget used to ask the atlas "is this glyph loaded?" to decide
        whether the active face was missing a character.  Since ImGui 1.92
        rasterizes glyphs lazily, every character the application had not
        drawn yet looked missing and was rerouted to the fallback face, so a
        source `v`/`w` came out in the fallback typeface's letterforms -- at
        body size those read as uppercase `V`/`W`.  Which characters were hit
        depended purely on what the application had drawn earlier, which is
        why the reporter saw it come and go between launches.

        This renders the same document twice: once while the characters are
        still cold, then again after a plain `ui.Label` has rasterized them.
        The two markdown renders must be identical.  The document uses
        Latin-1 letters no other fixture in this suite draws, so the first
        render really is cold no matter which tests ran before it.

        On a platform with no fallback face (the widget only has one when the
        styled or built-in fallback font file exists) both renders are
        trivially equal and the test still passes.
        """
        import tempfile

        from PIL import Image, ImageChops

        from omni.ui import _ui

        cold_chars = "þ ð ø ç ñ æ ß ý"
        source = f"Body text {cold_chars} in a paragraph.\n\n- List item {cold_chars}\n"
        width, height = 256, 160
        markdown_height = 96  # the band the widget occupies; excludes the primer

        window = await self.create_test_window(width=width, height=height)
        with window.frame:
            with ui.ZStack(width=ui.Fraction(1), height=ui.Fraction(1), style=self._style()):
                ui.Rectangle(style={"background_color": ui.color(0.985, 0.99, 1.0)})
                with ui.VStack():
                    ui.MarkdownWidget(source, width=ui.Fraction(1), height=markdown_height)
                    # Starts empty so it cannot rasterize the characters before
                    # the first markdown render; filled in below to prime them.
                    # Must match the widget's body size -- ovui bakes each font
                    # size separately, so a differently-sized label would prime
                    # a different glyph table and prove nothing.
                    primer = ui.Label(
                        "",
                        height=ui.Fraction(1),
                        style={"Label": {"font_size": self._style()["MarkdownWidget"]["font_size"]}},
                    )

        async def capture(path: str) -> Image.Image:
            # Schedule a pre-swap capture and pump frames until it lands --
            # the same mechanism finalize_test() uses.  ui.testing's
            # synchronous wrapper cannot be used here because it drives the
            # event loop itself, which IsolatedAsyncioTestCase owns.
            await self.wait_n_updates(6)
            self.assertTrue(_ui._schedule_screenshot(path), "screenshot capture failed")
            for _ in range(8):
                await self.wait_n_updates(1)
                if _ui._poll_screenshot_done():
                    break
            return Image.open(path).convert("RGB").crop((0, 0, width, markdown_height))

        with tempfile.TemporaryDirectory() as tmp:
            cold = await capture(f"{tmp}/cold.png")
            primer.text = cold_chars
            warm = await capture(f"{tmp}/warm.png")

            # Prove the glyphs really drew before comparing.  "Differs from
            # black" would prove nothing: the ZStack paints a near-white
            # rectangle over the whole area and the test window frames it in
            # dark chrome, so a frame with no text at all is already
            # non-black.  Inset past that 4 px chrome and count pixels
            # clearly darker than the backdrop -- inside that region only the
            # body colour (luma ~30, against the backdrop's ~252) can make
            # one, so the count is glyph coverage.
            inset = 8
            interior = cold.crop((inset, inset, width - inset, markdown_height))
            ink = sum(interior.convert("L").histogram()[:128])
            self.assertGreater(
                ink, 300,
                f"only {ink} foreground pixels inside the markdown band -- "
                "the text did not render, which would make the comparison "
                "below pass vacuously",
            )
            self.assertIsNone(
                ImageChops.difference(cold, warm).getbbox(),
                "MarkdownWidget rendered the same text differently once the "
                "font atlas had rasterized its glyphs",
            )

        await self.finalize_test_no_image()

    async def test_p1_alerts_render_smoke(self):
        window = await self.create_test_window(width=256, height=256)
        source = (
            "> [!NOTE]\n"
            "> Note body with **bold** text.\n\n"
            "> [!TIP]\n"
            "> Tip body.\n\n"
            "> [!IMPORTANT]\n"
            "> Important body.\n\n"
            "> [!WARNING]\n"
            "> Warning body.\n\n"
            "> [!CAUTION]\n"
            "> Caution body."
        )

        with window.frame:
            with ui.ZStack(width=ui.Fraction(1), height=ui.Fraction(1), style=self._style()):
                ui.Rectangle(style={"background_color": ui.color(0.985, 0.99, 1.0)})
                with ui.ScrollingFrame(
                    width=ui.Fraction(1),
                    height=ui.Fraction(1),
                    style={"ScrollingFrame": {"background_color": 0x00000000}},
                ):
                    ui.MarkdownWidget(source, width=ui.Fraction(1))

        await self.wait_n_updates(8)
        await self.finalize_test_no_image()

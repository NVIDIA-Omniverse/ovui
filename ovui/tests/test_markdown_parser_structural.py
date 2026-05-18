# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Structural (non-image) regression tests for the MarkdownWidget.

These tests exercise the parser / layout path through the Python bindings
without taking any screenshots. They are deliberately insensitive to font
rendering so they stay green across font/GPU changes and act as a cheap
smoke layer independent of the golden-image comparison tests.

For each file in ``tests/markdown_fuzz_corpus/`` we:
  * Construct a widget with that text and make sure construction succeeds.
  * Toggle the ``text`` property back-and-forth to smoke-test re-parsing.
  * Install a provider callback that raises and make sure a frame renders
    without crashing the widget.

The Python bindings don't currently expose the parse tree, so we can only
probe the widget from the outside. The C++ ``markdown_fuzz_tests`` binary
covers the token-stream invariants for the same corpus.
"""

from __future__ import annotations

from pathlib import Path

from test_base import OmniUiTest

import omni.ui as ui


_CORPUS_DIR = Path(__file__).resolve().parent / "markdown_fuzz_corpus"


def _corpus_files() -> list[Path]:
    if not _CORPUS_DIR.is_dir():
        return []
    return sorted(p for p in _CORPUS_DIR.iterdir() if p.suffix == ".md")


def _raising_provider(_src: str) -> str:
    raise RuntimeError("synthetic provider failure used by structural tests")


class TestMarkdownParserStructural(OmniUiTest):
    """Exercise parse/layout invariants for every corpus file."""

    async def _render_text(self, text: str) -> None:
        window = await self.create_test_window(width=256, height=256)
        with window.frame:
            with ui.ZStack(width=ui.Fraction(1), height=ui.Fraction(1)):
                ui.Rectangle(style={"background_color": ui.color(0.98, 0.99, 1.0)})
                with ui.ScrollingFrame(width=ui.Fraction(1), height=ui.Fraction(1)):
                    ui.MarkdownWidget(text, width=ui.Fraction(1))
        await self.wait_n_updates(4)
        await self.finalize_test_no_image()

    async def _render_with_failing_provider(self, text: str) -> None:
        import math

        window = await self.create_test_window(width=256, height=256)
        with window.frame:
            widget = ui.MarkdownWidget(text, width=ui.Fraction(1))
            widget.set_image_url_provider_fn(_raising_provider)
        # Pump frames so the provider is (potentially) invoked and the
        # widget has a chance to compute its height.  The widget must not
        # crash and its computed height must remain finite / non-negative.
        await self.wait_n_updates(4)

        # Probe the widget's computed height via whatever accessor is
        # available -- layer name varies slightly across builds.  Only
        # assert when a numeric value comes back; otherwise the structural
        # invariant we care about is simply that rendering did not raise.
        for attr in ("computed_height", "computed_content_height"):
            height = getattr(widget, attr, None)
            if isinstance(height, (int, float)):
                self.assertGreaterEqual(height, 0.0)
                self.assertTrue(math.isfinite(height))
                break

        await self.finalize_test_no_image()

    async def _render_toggle(self, a: str, b: str) -> None:
        window = await self.create_test_window(width=256, height=256)
        with window.frame:
            widget = ui.MarkdownWidget(a, width=ui.Fraction(1))
        await self.wait_n_updates(2)
        widget.text = b
        await self.wait_n_updates(2)
        widget.text = a
        await self.wait_n_updates(2)
        widget.text = b
        await self.wait_n_updates(2)
        await self.finalize_test_no_image()


def _make_corpus_test(path: Path):
    async def _test(self: TestMarkdownParserStructural) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        await self._render_text(text)

    _test.__name__ = f"test_parse_corpus_{path.stem}"
    _test.__doc__ = f"Parses {path.name} without raising."
    return _test


def _make_toggle_test(path: Path):
    async def _test(self: TestMarkdownParserStructural) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        # Toggle against a minimal document so reparse handles both small
        # and shape-of-file payloads.
        await self._render_toggle("# other\n\nbody", text)

    _test.__name__ = f"test_toggle_corpus_{path.stem}"
    _test.__doc__ = f"Toggles widget.text between a small doc and {path.name}."
    return _test


def _make_failing_provider_test(path: Path):
    async def _test(self: TestMarkdownParserStructural) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        await self._render_with_failing_provider(text)

    _test.__name__ = f"test_failing_provider_{path.stem}"
    _test.__doc__ = f"Widget survives a raising image_url_provider_fn for {path.name}."
    return _test


# Bind one test method per corpus file, per invariant, onto the class.
for _path in _corpus_files():
    _corpus_test = _make_corpus_test(_path)
    _toggle_test = _make_toggle_test(_path)
    _provider_test = _make_failing_provider_test(_path)
    setattr(TestMarkdownParserStructural, _corpus_test.__name__, _corpus_test)
    setattr(TestMarkdownParserStructural, _toggle_test.__name__, _toggle_test)
    setattr(TestMarkdownParserStructural, _provider_test.__name__, _provider_test)

# When the corpus directory is missing (e.g. stripped release tarball), keep a
# single sentinel test so the module still imports cleanly.
if not _corpus_files():
    async def test_corpus_directory_present(self):  # pragma: no cover
        self.fail(f"markdown_fuzz_corpus missing at {_CORPUS_DIR}")

    TestMarkdownParserStructural.test_corpus_directory_present = test_corpus_directory_present

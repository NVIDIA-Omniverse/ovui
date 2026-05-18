#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""SUT pipeline — render every MD file in corpus/ through omni.ui's native
``MarkdownWidget`` and save a PNG per (file, theme) under
markdown/quality_harness/artifacts/sut/.

Each capture needs its own process because ``ui.init()`` is a one-shot per
interpreter, so this script is both a coordinator (no ``--single`` flag)
and a single-shot renderer (``--single`` flag + paths).

Coordinator usage (requires Xvfb + DISPLAY):
    Xvfb :100 -screen 0 1024x2400x24 &
    DISPLAY=:100 python3 markdown/quality_harness/scripts/render_sut.py
    DISPLAY=:100 python3 markdown/quality_harness/scripts/render_sut.py atoms/17_fenced_code.md
    DISPLAY=:100 python3 markdown/quality_harness/scripts/render_sut.py --theme black

Single-shot usage (internal):
    python3 markdown/quality_harness/scripts/render_sut.py --single <md> <theme> <out>
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
REPO = HARNESS.parents[1]
CORPUS = HARNESS / "corpus"
OUT = HARNESS / "artifacts" / "sut"
THEMES = ("white", "black", "dark_blue")

WINDOW_WIDTH = 820
# Tall enough to fit even the longest document in the corpus without
# clipping. The oracle captures the full .oracle-surface element (~1800 px
# for D02_ai_technical); SUT must afford the same so the side-by-side isn't
# comparing a cropped-off SUT against a full oracle.
WINDOW_HEIGHT = 2400


def _enumerate(filter_arg: str | None) -> list[Path]:
    if filter_arg:
        target = (CORPUS / filter_arg).resolve()
        if not target.is_file():
            raise SystemExit(f"No such MD file: {target}")
        return [target]
    return sorted(CORPUS.rglob("*.md"))


def _render_single(md: Path, theme: str, out: Path) -> None:
    """Called inside a fresh subprocess — owns the only ``ui.init`` call."""
    sys.path.insert(0, str(REPO / "examples"))
    import omni.ui as ui
    from markdown_asset_resolver import MarkdownAssetResolver
    from omni.ui.markdown_providers import MarkdownProviderDocumentRenderer

    text = md.read_text(encoding="utf-8")
    theme_key = theme.replace("_", "-")

    # Pre-process the markdown source through the provider chain so
    # `$$...$$` block math, `$...$` inline math, and ``` ```math fences
    # are rasterised by MathJax (Node) and substituted with image
    # markdown the widget can display natively. This is what the
    # provider-plugin showcase does at runtime; we run it once up-front
    # for the test capture so MathJax has time to finish.
    provider_dir = HARNESS / "providers"
    doc_provider = MarkdownProviderDocumentRenderer(
        md, theme="dark" if theme != "white" else "light",
        provider_dir=provider_dir,
    )
    text = doc_provider.render(text, font_size=15.0)
    doc_provider.wait_for_idle(timeout=30)
    text = doc_provider.render(text, font_size=15.0)
    ui.init("SUT", width=WINDOW_WIDTH, height=WINDOW_HEIGHT)

    # ImGui NotoSans rasterises at roughly 0.85× the visible cap-height of
    # Chromium's CSS "Noto Sans" at the same nominal px. Oracle uses font-size:
    # 15px; to land the SUT's glyph cap-height near the same visual weight
    # we pass 17 through to the style cascade.
    theme_dict = ui.markdown_theme(theme_key, font_size=17)
    resolve_image_src = MarkdownAssetResolver(md)

    win = ui.Window(
        "SUT",
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        flags=(
            ui.WINDOW_FLAGS_NO_SCROLLBAR
            | ui.WINDOW_FLAGS_NO_RESIZE
            | ui.WINDOW_FLAGS_NO_TITLE_BAR
            | ui.WINDOW_FLAGS_NO_BACKGROUND
            | ui.WINDOW_FLAGS_NO_MOVE
        ),
    )
    with win.frame:
        with ui.ZStack(
            width=ui.Fraction(1),
            height=ui.Fraction(1),
            style=theme_dict["style"],
        ):
            ui.Rectangle(style={"background_color": theme_dict["background"]})
            # 16px outer gutter on both axes so SUT layout matches the oracle's
            # `.oracle-surface { padding: 16px 16px }`.
            with ui.VStack(width=ui.Fraction(1), height=ui.Fraction(1)):
                ui.Spacer(height=ui.Pixel(16))
                with ui.HStack(width=ui.Fraction(1), height=ui.Fraction(1)):
                    ui.Spacer(width=ui.Pixel(16))
                    with ui.ScrollingFrame(
                        width=ui.Fraction(1),
                        height=ui.Fraction(1),
                        style={"ScrollingFrame": {"background_color": 0x00000000}},
                    ):
                        widget = ui.MarkdownWidget(text, width=ui.Fraction(1))
                        widget.set_image_url_provider_fn(resolve_image_src)
                    ui.Spacer(width=ui.Pixel(16))
                ui.Spacer(height=ui.Pixel(16))

    async def capture() -> None:
        from omni.ui import testing

        await testing.wait_frames(60)
        ok = testing.capture_screenshot(str(out))
        print(f"[single] {'ok' if ok else 'FAIL'}  {out}", flush=True)
        if ok:
            _trim_trailing_bg(out)

    ui.run(capture())


def _trim_trailing_bg(png: Path) -> None:
    """Crop empty background rows off the bottom of a SUT capture.

    The SUT window is fixed-size for render determinism, but the oracle
    capture is sized to content. To compare the two images as the same
    apparent rectangle we drop trailing rows whose pixels all match the
    top-left background colour within a small tolerance.
    """
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return

    img = Image.open(png).convert("RGB")
    arr = np.asarray(img)
    if arr.size == 0:
        return
    h, w, _ = arr.shape
    # ImGui still paints a 2-3 px window border even with NO_BACKGROUND +
    # NO_TITLE_BAR. We want the SUT image to present the widget content on
    # the theme background, no frame, same as the oracle's .oracle-surface
    # capture. Strategy: sample the true theme bg from the interior (not
    # the corners), then trim every edge — top, bottom, left, right — up
    # to the first row/column that contains real content, with a small
    # breather so glyphs aren't clipped.
    rim = 8
    inner = arr[rim:h - rim, rim:w - rim]
    if inner.size == 0:
        return
    bg = inner[0, inner.shape[1] // 2].astype(np.int16)
    delta_full = np.abs(arr.astype(np.int16) - bg).max(axis=2)
    # Content mask ignores the outer rim entirely to avoid picking up
    # window-border pixels as "content".
    mask_ignore_rim = delta_full.copy()
    mask_ignore_rim[:rim, :] = 0
    mask_ignore_rim[-rim:, :] = 0
    mask_ignore_rim[:, :rim] = 0
    mask_ignore_rim[:, -rim:] = 0

    row_hits = (mask_ignore_rim > 6).sum(axis=1)
    row_thresh = max(2, (w - 2 * rim) // 100)
    content_rows = np.where(row_hits > row_thresh)[0]
    if len(content_rows) == 0:
        return

    # Only trim vertically — oracle captures always keep the full surface
    # width, so SUT must too for a fair side-by-side. Horizontal window
    # border is a narrow vertical rim; we mask it out by replacing the
    # outer columns with the theme bg colour.
    top = max(0, int(content_rows.min()) - 8)
    bot = min(h, int(content_rows.max()) + 16)

    out = arr[top:bot].copy()
    # Paint over the left/right border rim with the sampled theme bg so
    # the vertical frame disappears without narrowing the image.
    bg_u8 = bg.astype(np.uint8)
    out[:, :rim] = bg_u8
    out[:, -rim:] = bg_u8

    if out.shape[0] != arr.shape[0] or not np.array_equal(out, arr):
        Image.fromarray(out).save(png)


def _coordinate(filter_arg: str | None, themes: list[str]) -> int:
    files = _enumerate(filter_arg)
    if not files:
        print("No MD files found.")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    ok = 0
    fail = 0
    for theme in themes:
        for md in files:
            rel = md.relative_to(CORPUS)
            out = OUT / theme / rel.with_suffix(".png")
            out.parent.mkdir(parents=True, exist_ok=True)
            cmd = [
                sys.executable,
                str(HERE / "render_sut.py"),
                "--single",
                str(md),
                theme,
                str(out),
            ]
            env = os.environ.copy()
            env.setdefault("DISPLAY", ":100")
            # Ensure the in-tree omni.ui is importable from the subprocess.
            existing_pp = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = (
                f"{REPO / 'python'}:{REPO / 'examples'}"
                + (f":{existing_pp}" if existing_pp else "")
            )
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
            # omni.ui's shutdown path sometimes SIGSEGVs after the screenshot
            # commits to disk. Treat "file exists and has bytes" as success
            # regardless of exit code.
            if out.exists() and out.stat().st_size > 1024:
                ok += 1
                print(f"  ✓ [{theme:10}] {rel}  →  {out.relative_to(ROOT)}")
            else:
                fail += 1
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
                print(f"  ✗ [{theme:10}] {rel}: {' | '.join(tail)}")

    print()
    print(f"Done. {ok} ok, {fail} failed.")
    return 0 if fail == 0 else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("filter", nargs="?", help="MD path relative to corpus/")
    ap.add_argument(
        "--theme",
        default="all",
        choices=("all", *THEMES),
        help="Theme to render (default: all)",
    )
    ap.add_argument("--single", nargs=3, metavar=("MD", "THEME", "OUT"))
    args = ap.parse_args()

    if args.single:
        md_path = Path(args.single[0]).resolve()
        _render_single(md_path, args.single[1], Path(args.single[2]).resolve())
        return 0

    themes = list(THEMES) if args.theme == "all" else [args.theme]
    return _coordinate(args.filter, themes)


if __name__ == "__main__":
    sys.exit(main())

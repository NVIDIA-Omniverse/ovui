# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Generate placeholder PNG icons for the content browser implementation step 5.

Produces the 11 ``asset_*`` file-type icons (64x64 coloured squares
with a short text abbreviation) and the 12 ``content_*`` chrome icons
(64x64 white silhouettes on transparent) used by the content browser.

Run once from the repo root:

.. code-block:: bash

    python3.12 tests/data/gen_content_icons.py

PNGs are written directly to ``ovwidgets.app/style/icons/``. The script is
idempotent — rerunning overwrites in place. Placeholder quality is
intentional; production artwork replaces them in-place without any
code change.
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ICONS_DIR = _REPO_ROOT / "ovwidgets" / "app" / "style" / "icons"
_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

_SIZE = 64  # All icons are 64x64 to match the existing PNG suite.


# ---------------------------------------------------------------------------
# Asset file-type icons — (filename_stem, fill_color_rgb, label)
# ---------------------------------------------------------------------------

_ASSET_ICONS = [
    ("asset_folder",   (0xFF, 0xC5, 0x5C), "FD"),
    ("asset_usd",      (0x6A, 0xC7, 0xFF), "USD"),
    ("asset_image",    (0x7A, 0xBA, 0x5A), "IMG"),
    ("asset_material", (0xE8, 0x8A, 0x3A), "MAT"),
    ("asset_model",    (0xB8, 0x68, 0xD8), "FBX"),
    ("asset_sound",    (0x4A, 0xB0, 0xA0), "WAV"),
    ("asset_script",   (0xD8, 0x58, 0x58), "PY"),
    ("asset_volume",   (0xE5, 0x8C, 0xB0), "VDB"),
    ("asset_text",     (0xAA, 0xAA, 0xAA), "TXT"),
    ("asset_archive",  (0x8A, 0x5A, 0x3A), "ZIP"),
    ("asset_unknown",  (0x88, 0x88, 0x88), "?"),
]


def _pick_font(max_text_width: int, max_text_height: int, label: str) -> ImageFont.FreeTypeFont:
    """Return the largest font size that fits ``label`` inside the given box."""
    for size in range(32, 8, -1):
        font = ImageFont.truetype(_FONT_PATH, size=size)
        bbox = font.getbbox(label)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if w <= max_text_width and h <= max_text_height:
            return font
    return ImageFont.truetype(_FONT_PATH, size=10)


def _draw_asset_icon(out_path: Path, fill_rgb, label: str) -> None:
    img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Rounded rectangle matches the look of stage-badge PNGs.
    draw.rounded_rectangle(
        (2, 2, _SIZE - 2, _SIZE - 2),
        radius=8,
        fill=fill_rgb + (0xFF,),
    )
    font = _pick_font(max_text_width=_SIZE - 12, max_text_height=_SIZE - 18, label=label)
    bbox = font.getbbox(label)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    tx = (_SIZE - w) // 2 - bbox[0]
    ty = (_SIZE - h) // 2 - bbox[1]
    # White label for dark fills, black for very light fills.
    r, g, b = fill_rgb
    luminance = (0.299 * r + 0.587 * g + 0.114 * b)
    text_color = (0x22, 0x22, 0x22, 0xFF) if luminance > 170 else (0xFF, 0xFF, 0xFF, 0xFF)
    draw.text((tx, ty), label, font=font, fill=text_color)
    img.save(out_path, format="PNG")


# ---------------------------------------------------------------------------
# Content chrome icons — simple white silhouettes on transparent background
# ---------------------------------------------------------------------------

_WHITE = (0xFF, 0xFF, 0xFF, 0xFF)


def _new_chrome_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _draw_content_search(path: Path) -> None:
    img, draw = _new_chrome_canvas()
    # Circle (lens) with a diagonal handle.
    draw.ellipse((10, 10, 42, 42), outline=_WHITE, width=5)
    draw.line((38, 38, 54, 54), fill=_WHITE, width=6)
    img.save(path, format="PNG")


def _draw_content_filter(path: Path) -> None:
    img, draw = _new_chrome_canvas()
    # Funnel: trapezoid top + narrow stem bottom.
    draw.polygon(
        [(10, 12), (54, 12), (38, 34), (38, 54), (26, 54), (26, 34)],
        fill=_WHITE,
    )
    img.save(path, format="PNG")


def _draw_bookmark_shape(draw: ImageDraw.ImageDraw, filled: bool) -> None:
    pts = [(18, 10), (46, 10), (46, 54), (32, 44), (18, 54)]
    if filled:
        draw.polygon(pts, fill=_WHITE)
    else:
        draw.polygon(pts, outline=_WHITE, width=4)


def _draw_content_bookmark(path: Path) -> None:
    img, draw = _new_chrome_canvas()
    _draw_bookmark_shape(draw, filled=False)
    img.save(path, format="PNG")


def _draw_content_bookmark_filled(path: Path) -> None:
    img, draw = _new_chrome_canvas()
    _draw_bookmark_shape(draw, filled=True)
    img.save(path, format="PNG")


def _draw_content_arrow_left(path: Path) -> None:
    img, draw = _new_chrome_canvas()
    draw.polygon([(44, 12), (44, 52), (20, 32)], fill=_WHITE)
    img.save(path, format="PNG")


def _draw_content_arrow_right(path: Path) -> None:
    img, draw = _new_chrome_canvas()
    draw.polygon([(20, 12), (20, 52), (44, 32)], fill=_WHITE)
    img.save(path, format="PNG")


def _draw_content_arrow_up(path: Path) -> None:
    img, draw = _new_chrome_canvas()
    draw.polygon([(12, 44), (52, 44), (32, 20)], fill=_WHITE)
    img.save(path, format="PNG")


def _draw_content_arrow_down(path: Path) -> None:
    img, draw = _new_chrome_canvas()
    draw.polygon([(12, 20), (52, 20), (32, 44)], fill=_WHITE)
    img.save(path, format="PNG")


def _draw_content_grid_view(path: Path) -> None:
    img, draw = _new_chrome_canvas()
    # 2x2 of rounded tiles.
    for row in (12, 36):
        for col in (12, 36):
            draw.rounded_rectangle(
                (col, row, col + 16, row + 16), radius=2, fill=_WHITE,
            )
    img.save(path, format="PNG")


def _draw_content_list_view(path: Path) -> None:
    img, draw = _new_chrome_canvas()
    # Three rows: small dot on the left, horizontal line on the right.
    for y in (16, 30, 44):
        draw.rounded_rectangle((12, y, 18, y + 6), radius=1, fill=_WHITE)
        draw.rounded_rectangle((24, y, 54, y + 6), radius=1, fill=_WHITE)
    img.save(path, format="PNG")


def _draw_content_home(path: Path) -> None:
    img, draw = _new_chrome_canvas()
    # Pitched roof over a square body.
    draw.polygon([(32, 10), (10, 30), (54, 30)], fill=_WHITE)
    draw.rectangle((16, 28, 48, 54), fill=_WHITE)
    # Door cut-out.
    draw.rectangle((28, 38, 36, 54), fill=(0, 0, 0, 0))
    img.save(path, format="PNG")


def _draw_content_plus(path: Path) -> None:
    img, draw = _new_chrome_canvas()
    draw.rectangle((28, 12, 36, 52), fill=_WHITE)
    draw.rectangle((12, 28, 52, 36), fill=_WHITE)
    img.save(path, format="PNG")


def _draw_content_minus(path: Path) -> None:
    img, draw = _new_chrome_canvas()
    draw.rectangle((12, 28, 52, 36), fill=_WHITE)
    img.save(path, format="PNG")


_CHROME_DRAWERS = {
    "content_search":          _draw_content_search,
    "content_filter":          _draw_content_filter,
    "content_bookmark":        _draw_content_bookmark,
    "content_bookmark_filled": _draw_content_bookmark_filled,
    "content_arrow_left":      _draw_content_arrow_left,
    "content_arrow_right":     _draw_content_arrow_right,
    "content_arrow_up":        _draw_content_arrow_up,
    "content_arrow_down":      _draw_content_arrow_down,
    "content_grid_view":       _draw_content_grid_view,
    "content_list_view":       _draw_content_list_view,
    "content_home":            _draw_content_home,
    "content_plus":            _draw_content_plus,
    "content_minus":           _draw_content_minus,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    os.makedirs(_ICONS_DIR, exist_ok=True)

    for stem, rgb, label in _ASSET_ICONS:
        out = _ICONS_DIR / f"{stem}.png"
        _draw_asset_icon(out, rgb, label)
        print(f"wrote {out.relative_to(_REPO_ROOT)}")

    for stem, drawer in _CHROME_DRAWERS.items():
        out = _ICONS_DIR / f"{stem}.png"
        drawer(out)
        print(f"wrote {out.relative_to(_REPO_ROOT)}")


if __name__ == "__main__":
    main()

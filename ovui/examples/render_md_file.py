# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Render a markdown file through MarkdownWidget and save a screenshot."""
import argparse
from pathlib import Path

import omni.ui as ui

from markdown_asset_resolver import MarkdownAssetResolver


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown_path", type=Path)
    parser.add_argument("output_png", type=Path)
    parser.add_argument("--width", type=int, default=980)
    parser.add_argument("--height", type=int, default=2400)
    parser.add_argument(
        "--theme",
        choices=("black", "dark", "light", "default", "white", "dark-blue"),
        default="black",
        help="Background and MarkdownWidget color theme.",
    )
    parser.add_argument(
        "--table-policy",
        choices=("equal", "content-fit", "fixed", "clipped"),
        default="equal",
        help="MarkdownWidget.Table layout_policy for table review renders.",
    )
    return parser.parse_args()


ARGS = _parse_args()
SRC = ARGS.markdown_path
OUT = ARGS.output_png

ui.init(f"Render {SRC.name}", width=ARGS.width, height=ARGS.height)

text = SRC.read_text(encoding="utf-8")
resolve_image_src = MarkdownAssetResolver(SRC)

win = ui.Window(
    f"md: {SRC.name}",
    width=ARGS.width,
    height=ARGS.height,
    flags=ui.WINDOW_FLAGS_NO_SCROLLBAR | ui.WINDOW_FLAGS_NO_RESIZE,
)

theme = ui.markdown_theme(ARGS.theme, table_policy=ARGS.table_policy)
bg_color = theme["background"]
md_style = theme["style"]

with win.frame:
    with ui.ZStack(width=ui.Fraction(1), height=ui.Fraction(1), style=md_style):
        ui.Rectangle(style={"background_color": bg_color})
        with ui.ScrollingFrame(
            width=ui.Fraction(1),
            height=ui.Fraction(1),
            style={"ScrollingFrame": {"background_color": 0x00000000}}
        ):
            widget = ui.MarkdownWidget(text, width=ui.Fraction(1))
            widget.set_image_url_provider_fn(resolve_image_src)


async def capture(path: str) -> None:
    from omni.ui import testing

    await testing.wait_frames(12)
    testing.capture_screenshot(path)
    print(f"Screenshot saved: {path}")


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ui.run(capture(str(OUT)))

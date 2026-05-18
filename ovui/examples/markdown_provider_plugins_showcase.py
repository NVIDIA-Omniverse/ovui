# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Show optional Markdown provider plugins without blocking the UI thread."""
import argparse
from pathlib import Path

import omni.ui as ui
from omni.ui.markdown_providers import MarkdownAssetResolver, MarkdownProviderDocumentRenderer


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
SOURCE = ROOT / "markdown_provider_plugins_showcase.md"
PROVIDER_DIR = REPO / "markdown" / "quality_harness" / "providers"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", choices=("white", "dark-blue", "black"), default="dark-blue")
    parser.add_argument("--width", type=int, default=1100)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--screenshot", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "markdown_provider_plugins_showcase.png")
    parser.add_argument(
        "--provider-dir",
        type=Path,
        default=PROVIDER_DIR,
        help="Optional local Node provider runtime with package.json/node_modules.",
    )
    return parser.parse_args()


ARGS = parse_args()
RAW_TEXT = SOURCE.read_text(encoding="utf-8")

document_provider = MarkdownProviderDocumentRenderer(SOURCE, theme=ARGS.theme, provider_dir=ARGS.provider_dir)
image_resolver = MarkdownAssetResolver(SOURCE)

ui.init("Markdown Provider Plugins", width=ARGS.width, height=ARGS.height)
theme = ui.markdown_theme(ARGS.theme, table_policy="content-fit")

win = ui.Window(
    "Markdown Provider Plugins",
    width=ARGS.width,
    height=ARGS.height,
    flags=ui.WINDOW_FLAGS_NO_SCROLLBAR | ui.WINDOW_FLAGS_NO_RESIZE,
)


with win.frame:
    with ui.ZStack(width=ui.Fraction(1), height=ui.Fraction(1), style=theme["style"]):
        ui.Rectangle(style={"background_color": theme["background"]})
        with ui.ScrollingFrame(
            width=ui.Fraction(1),
            height=ui.Fraction(1),
            style={"ScrollingFrame": {"background_color": 0x00000000}},
        ):
            widget = ui.MarkdownWidget(document_provider.render(RAW_TEXT), width=ui.Fraction(1))
            widget.set_image_url_provider_fn(image_resolver)


async def refresh_provider_blocks() -> None:
    from omni.ui import testing

    # Let the first non-blocking provider requests get scheduled.
    await testing.wait_frames(4)
    document_provider.wait_for_idle(timeout=30)
    image_resolver.wait_for_idle(timeout=30)
    widget.text = document_provider.render(RAW_TEXT)
    await testing.wait_frames(8)


async def capture(path: Path) -> None:
    from omni.ui import testing

    await refresh_provider_blocks()
    testing.capture_screenshot(str(path))
    print(f"Screenshot saved: {path}")


async def run_interactive() -> None:
    await refresh_provider_blocks()
    while True:
        await ui.next_frame()


if __name__ == "__main__":
    if ARGS.screenshot:
        ARGS.output.parent.mkdir(parents=True, exist_ok=True)
        ui.run(capture(ARGS.output))
    else:
        ui.run(run_interactive())

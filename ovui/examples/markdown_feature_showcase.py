# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Render advanced MarkdownWidget feature coverage."""
import argparse
import functools
import http.server
import socketserver
import threading
from pathlib import Path

import omni.ui as ui

from markdown_asset_resolver import MarkdownAssetResolver


ROOT = Path(__file__).resolve().parent
TEMPLATE_PATH = ROOT / "markdown_feature_showcase.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", choices=("white", "dark-blue", "black", "split"), default="split")
    parser.add_argument("--width", type=int, default=1400)
    parser.add_argument("--height", type=int, default=1100)
    parser.add_argument("--screenshot", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass


def start_http_server() -> tuple[socketserver.TCPServer, str]:
    handler = functools.partial(QuietHandler, directory=str(ROOT))
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}/test_http_badge.png"


ARGS = parse_args()
SERVER, HTTP_ICON_URL = start_http_server()
TEXT = TEMPLATE_PATH.read_text(encoding="utf-8").replace("{{HTTP_ICON_URL}}", HTTP_ICON_URL)

ui.init("Markdown Feature Showcase", width=ARGS.width, height=ARGS.height)

THEMES = {
    "white": ui.markdown_theme("white", table_policy="content-fit"),
    "dark-blue": ui.markdown_theme("dark-blue", table_policy="content-fit"),
    "black": ui.markdown_theme("black", table_policy="content-fit"),
}


def on_link(url: str) -> None:
    print(f"link: {url}")


resolver = MarkdownAssetResolver(TEMPLATE_PATH)


def build_document(theme_name: str) -> None:
    theme = THEMES[theme_name]
    with ui.ZStack(width=ui.Fraction(1), height=ui.Fraction(1), style=theme["style"]):
        ui.Rectangle(style={"background_color": theme["background"]})
        with ui.ScrollingFrame(
            width=ui.Fraction(1),
            height=ui.Fraction(1),
            style={"ScrollingFrame": {"background_color": 0x00000000}},
        ):
            widget = ui.MarkdownWidget(TEXT, width=ui.Fraction(1))
            widget.set_link_clicked_fn(on_link)
            widget.set_image_url_provider_fn(resolver)


win = ui.Window(
    "Markdown Feature Showcase",
    width=ARGS.width,
    height=ARGS.height,
    fill_app_window=True,
    flags=(
        ui.WINDOW_FLAGS_NO_SCROLLBAR
        | ui.WINDOW_FLAGS_NO_TITLE_BAR
        | ui.WINDOW_FLAGS_NO_RESIZE
    ),
)

with win.frame:
    if ARGS.theme == "split":
        with ui.HStack(width=ui.Fraction(1), height=ui.Fraction(1), spacing=8):
            build_document("white")
            build_document("dark-blue")
    else:
        build_document(ARGS.theme)


def output_path() -> Path:
    if ARGS.output:
        return ARGS.output
    suffix = ARGS.theme.replace("-", "_")
    return ROOT / f"markdown_feature_{suffix}.png"


async def capture(path: Path) -> None:
    from omni.ui import testing

    await testing.wait_frames(20)
    testing.capture_screenshot(str(path))
    print(f"Screenshot saved: {path}")


if __name__ == "__main__":
    if ARGS.screenshot:
        out = output_path()
        out.parent.mkdir(parents=True, exist_ok=True)
        ui.run(capture(out))
    else:
        ui.run()
    SERVER.shutdown()

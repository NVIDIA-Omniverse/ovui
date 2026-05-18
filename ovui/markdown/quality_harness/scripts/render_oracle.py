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

"""Render every MD file in corpus/ through the streamdown oracle.

Starts the Vite dev server, then drives Playwright over the corpus and
saves a PNG per file under markdown/quality_harness/artifacts/oracle/ mirroring
the corpus tree.

Usage:
    python3 markdown/quality_harness/scripts/render_oracle.py            # render everything
    python3 markdown/quality_harness/scripts/render_oracle.py atoms/03_bold.md  # single file
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

HARNESS = Path(__file__).resolve().parents[1]
ORACLE = HARNESS / "oracle"
CORPUS = HARNESS / "corpus"
OUT = HARNESS / "artifacts" / "oracle"
HOST = "127.0.0.1"
PORT = 5173
URL = f"http://{HOST}:{PORT}"
VIEWPORT = {"width": 820, "height": 768}
DEVICE_SCALE = 1  # render at 1× so oracle pixels map 1:1 to SUT pixels
THEMES = ("white", "black", "dark_blue")


def _server_up() -> bool:
    try:
        urllib.request.urlopen(URL, timeout=0.5)
        return True
    except Exception:
        return False


def _wait_server(proc: subprocess.Popen, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _server_up():
            return
        if proc.poll() is not None:
            out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            raise RuntimeError(f"Vite exited early:\n{out}")
        time.sleep(0.3)
    raise RuntimeError(f"Vite did not come up within {timeout}s")


def _start_vite() -> subprocess.Popen:
    if _server_up():
        print(f"Vite already running at {URL}; reusing.")
        # Return a dummy process that won't be terminated
        return subprocess.Popen(["sleep", "1"], stdout=subprocess.DEVNULL)

    print(f"Starting Vite dev server at {URL}...")
    proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", HOST, "--port", str(PORT)],
        cwd=ORACLE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
    )
    _wait_server(proc)
    print("Vite is up.")
    return proc


def _stop_vite(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
    except Exception:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass


def _enumerate(filter_arg: str | None) -> list[Path]:
    if filter_arg:
        target = (CORPUS / filter_arg).resolve()
        if not target.is_file():
            raise SystemExit(f"No such MD file: {target}")
        return [target]
    return sorted(CORPUS.rglob("*.md"))


async def _render_one(page, md: Path, theme: str) -> Path:
    rel = md.relative_to(CORPUS).as_posix()
    out = OUT / theme / rel.replace(".md", ".png")
    out.parent.mkdir(parents=True, exist_ok=True)

    url = f"{URL}/?file={rel}&theme={theme}"
    await page.goto(url, wait_until="load")
    await page.wait_for_selector(
        '[data-testid="rendered-sentinel"]',
        state="attached",
        timeout=15000,
    )
    # Shiki syntax highlighting + KaTeX + Mermaid all load lazily; wait
    # for network idle and fonts, then give the tokenizer a beat to run.
    await page.wait_for_load_state("networkidle", timeout=15000)
    await page.evaluate("document.fonts.ready")
    await page.wait_for_timeout(1500)

    surface = await page.query_selector(".oracle-surface")
    if surface is None:
        raise RuntimeError(f"Could not locate .oracle-surface for {rel}")
    await surface.screenshot(path=str(out))
    return out


async def _render_all(
    files: list[Path], themes: list[str]
) -> list[tuple[Path, str, Path | Exception]]:
    results: list[tuple[Path, str, Path | Exception]] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        for theme in themes:
            # Keep color_scheme in lock-step with the theme class so the
            # GFM alert plugin's @media (prefers-color-scheme) rules match.
            cs = "dark" if theme != "white" else "light"
            ctx = await browser.new_context(
                viewport=VIEWPORT,
                device_scale_factor=DEVICE_SCALE,
                color_scheme=cs,
            )
            page = await ctx.new_page()
            for md in files:
                try:
                    png = await _render_one(page, md, theme)
                    results.append((md, theme, png))
                    print(
                        f"  ✓ [{theme:10}] {md.relative_to(CORPUS)}"
                        f"  →  {png.relative_to(HERE)}"
                    )
                except Exception as exc:
                    results.append((md, theme, exc))
                    print(f"  ✗ [{theme:10}] {md.relative_to(CORPUS)}: {exc}")
            await ctx.close()
        await browser.close()
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "filter",
        nargs="?",
        help="Optional MD path (relative to corpus/) to render a single file",
    )
    ap.add_argument(
        "--theme",
        default="all",
        choices=("all", *THEMES),
        help="Theme to render (default: all)",
    )
    args = ap.parse_args()

    files = _enumerate(args.filter)
    if not files:
        print("No MD files found.")
        return 1

    themes = list(THEMES) if args.theme == "all" else [args.theme]

    OUT.mkdir(parents=True, exist_ok=True)
    vite = _start_vite()
    try:
        results = asyncio.run(_render_all(files, themes))
    finally:
        _stop_vite(vite)

    ok = sum(1 for _, _, r in results if isinstance(r, Path))
    fail = len(results) - ok
    print()
    print(f"Done. {ok} ok, {fail} failed.")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())

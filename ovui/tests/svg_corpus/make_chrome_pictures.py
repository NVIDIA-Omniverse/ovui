# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Make the Chrome pictures that ``standalone_svg_rasterizer_tests`` compares with.

Run it after an SVG file of this folder changes or is added::

    python tests/svg_corpus/make_chrome_pictures.py

It needs Google Chrome (``google-chrome`` on the PATH, or the path in the
environment variable ``CHROME``). Chrome draws each file into a canvas with
``drawImage`` at a fixed size (128 pixels for the files of this folder, 64 for
``icons/``; the long side, the aspect ratio of the file is kept), and the canvas
pixels are saved as ``chrome/<name>.png`` and ``chrome/icons/<name>.png``. The
Chrome version is written to ``chrome/CHROME_VERSION.txt``. Nothing is installed
and no other program is used.
"""

from __future__ import annotations

import base64
import html
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SETS = ((HERE, HERE / "chrome", 128), (HERE / "icons", HERE / "chrome" / "icons", 64))

PAGE = """<!doctype html><html><body><pre id="out">PENDING</pre><script>
const items = %s; const size = %d; const results = {};
let left = items.length;
function done() { if (--left === 0) document.getElementById('out').textContent = JSON.stringify(results); }
for (const it of items) {
  const img = new Image();
  img.onload = () => {
    const w0 = img.naturalWidth || size, h0 = img.naturalHeight || size;
    const s = size / Math.max(w0, h0);
    const w = Math.max(1, Math.round(w0 * s)), h = Math.max(1, Math.round(h0 * s));
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    c.getContext('2d').drawImage(img, 0, 0, w, h);
    results[it.name] = c.toDataURL('image/png'); done();
  };
  img.onerror = () => { results[it.name] = 'ERROR'; done(); };
  img.src = it.src;
}
</script></body></html>"""


def render(chrome: str, files: list[pathlib.Path], size: int, out_dir: pathlib.Path) -> None:
    items = [
        {"name": f.stem, "src": "data:image/svg+xml;base64," + base64.b64encode(f.read_bytes()).decode()}
        for f in files
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="svg_corpus_chrome_") as tmp:
        page = pathlib.Path(tmp) / "page.html"
        page.write_text(PAGE % (json.dumps(items), size), encoding="utf-8")
        dom = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--force-color-profile=srgb",
             "--force-device-scale-factor=1", f"--user-data-dir={tmp}/profile",
             "--virtual-time-budget=20000", "--dump-dom", page.as_uri()],
            capture_output=True, text=True, timeout=300, check=True,
        ).stdout
    match = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S)
    if not match or match.group(1) == "PENDING":
        sys.exit("Chrome did not finish drawing the files")
    for name, url in json.loads(html.unescape(match.group(1))).items():
        if url == "ERROR":
            sys.exit(f"Chrome could not load {name}.svg")
        (out_dir / f"{name}.png").write_bytes(base64.b64decode(url.split(",", 1)[1]))


def main() -> None:
    chrome = os.environ.get("CHROME", "google-chrome")
    version = subprocess.run([chrome, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    for folder, out_dir, size in SETS:
        files = sorted(folder.glob("*.svg"))
        render(chrome, files, size, out_dir)
        print(f"{len(files)} pictures of {size} pixels in {out_dir.relative_to(HERE)}")
    (HERE / "chrome" / "CHROME_VERSION.txt").write_text(version + "\n", encoding="utf-8")
    print(version)


if __name__ == "__main__":
    main()

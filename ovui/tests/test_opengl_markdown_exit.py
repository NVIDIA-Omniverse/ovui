# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A windowed OpenGL app with a Markdown image must exit with code 0.

The Markdown image texture belongs to ``OpenGLRenderer``, which deletes it
when it is destroyed. If the GLFW platform is torn down first, the GL
library is already gone and the process dies with SIGSEGV at exit. The app
runs in a child process so that its exit code can be read.

The test never skips: it opens the window on the computer it runs on, and
gives the child a display with ``xvfb-run`` when none is set. The jobs that
run it are the Linux ones; see the comment in the Windows step of
``.github/workflows/build-app-wheelhouse.yml``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ICON = Path(__file__).resolve().parents[1] / "examples" / "test_icon_32.png"

_APP = """
import os
import sys

_VULKAN_DLL_DIRECTORY = None
if os.name == "nt":
    vulkan_dll_dir = os.environ.get("Vulkan_DLL_DIR")
    if vulkan_dll_dir:
        _VULKAN_DLL_DIRECTORY = os.add_dll_directory(vulkan_dll_dir)

import omni.ui as ui
from omni.ui import testing

ui.init("markdown-image-exit", 256, 256)
window = ui.Window("Markdown", width=256, height=256, fill_app_window=True)
with window.frame:
    widget = ui.MarkdownWidget("![icon](icon.png)", width=ui.Fraction(1))
    widget.set_image_url_provider_fn(lambda src: sys.argv[1])


async def draw():
    await testing.wait_frames(10)


ui.run(draw())
"""


def _run_child(script: str, *args: str) -> subprocess.CompletedProcess:
    """Run a child that opens its own OpenGL window, whatever the run sets."""
    env = dict(os.environ)
    env["OMNIUI_BACKEND"] = "opengl"
    env.pop("OMNIUI_HEADLESS", None)
    env.pop("OMNIUI_HEADLESS_GL", None)
    command = [sys.executable, "-c", script, *args]
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        # An unset DISPLAY is session settings, not missing hardware, so give
        # the child a display instead of skipping the test.
        command = ["xvfb-run", "-a", *command]
    return subprocess.run(command, env=env, capture_output=True, text=True, timeout=180)


def test_markdown_image_app_exits_cleanly_on_opengl():
    completed = _run_child(_APP, str(_ICON))
    assert completed.returncode == 0, (
        f"exit code {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )

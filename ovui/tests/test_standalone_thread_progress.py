# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A Python thread must keep running while the uncapped run loop draws.

The run loops never wait between frames when ``max_fps`` is unset, so the
main thread would keep the GIL almost all the time and a
``threading.Thread`` would get almost no turns. The fix hands the GIL over
in ``_tick_one_frame``, spaced out so it costs no frame rate.

The starvation shows only with the real native frame of a window: the
headless frame and a patched Python tick both let the thread run anyway.
So the loop runs in a child process with a real window (the ordinary
default backend), like ``test_backend_default_policy.py``.

The test never skips: it opens the window on the computer it runs on, and
gives the child a display with ``xvfb-run`` when none is set. It runs on the
Linux jobs and on the Windows computer with a graphics card that opens the
app window; see the comment in the Windows step of
``.github/workflows/build-app-wheelhouse.yml``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

_PROBE = """
import asyncio
import json
import os
import sys
import threading
import time

_VULKAN_DLL_DIRECTORY = None
if os.name == "nt":
    vulkan_dll_dir = os.environ.get("Vulkan_DLL_DIR")
    if vulkan_dll_dir:
        _VULKAN_DLL_DIRECTORY = os.add_dll_directory(vulkan_dll_dir)

import omni.ui as ui
import omni.ui.standalone as standalone

done = threading.Event()
steps = [0]
result = {}

def job():
    # 100 short sleeps: about 0.2 s when the thread gets its turns.
    for _ in range(100):
        time.sleep(0.002)
        steps[0] += 1
    done.set()

async def main():
    threading.Thread(target=job, daemon=True).start()
    start = time.perf_counter()
    while not done.is_set() and time.perf_counter() - start < 5.0:
        await ui.next_frame()
    result["steps"] = steps[0]

async def run_async_until_main_ends():
    runner = asyncio.ensure_future(standalone.run_async())
    await main()
    standalone.shutdown()
    await runner

ui.init("thread-progress-probe", 320, 240)
if sys.argv[1] == "run":
    ui.run(main())
else:
    asyncio.run(run_async_until_main_ends())
print("PROBE " + json.dumps(result), flush=True)
"""


def _run_child(script: str, *args: str) -> subprocess.CompletedProcess:
    """Run a child that opens its own window, like an ordinary launch.

    The settings of the run must not choose the backend or the headless
    frame for the child: the starvation this test is about needs the real
    native frame of a window.
    """
    env = dict(os.environ)
    env.pop("OMNIUI_HEADLESS", None)
    env.pop("OMNIUI_HEADLESS_GL", None)
    env.pop("OMNIUI_BACKEND", None)
    command = [sys.executable, "-c", script, *args]
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        # An unset DISPLAY is session settings, not missing hardware, so give
        # the child a display instead of skipping the test.
        command = ["xvfb-run", "-a", *command]
    return subprocess.run(command, env=env, capture_output=True, text=True, timeout=180)


@pytest.mark.parametrize("loop", ["run", "run_async"])
def test_thread_progresses_while_uncapped_loop_runs(loop):
    completed = _run_child(_PROBE, loop)
    assert completed.returncode == 0, (
        f"exit code {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    probe = None
    for line in completed.stdout.splitlines():
        if line.startswith("PROBE "):
            probe = json.loads(line[len("PROBE "):])
    if probe is None:
        pytest.fail(
            "the probe never reported\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    # Without the per-frame GIL yield the thread gets only a few of its
    # 100 steps in the whole 5 s.
    assert probe["steps"] == 100, (
        f"the thread made {probe['steps']}/100 steps in 5 s while ui.{loop}() ran"
    )

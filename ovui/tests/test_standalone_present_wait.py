# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A Python thread must run while a frame is blocked in native presentation.

A slow display (vsync, monitor off) makes ``glfwSwapBuffers`` or
``vkQueuePresentKHR`` wait for a long time. The standalone frame must not hold
the GIL during that wait. This test makes the wait long on purpose with the
native test delay of the standalone module, which runs inside the same scope
that wraps the real present call, so it needs no special display and runs on
every platform that opens the app window.

The count that matters is only the heartbeats that happen *inside* the wait.
The native code records the start and end of the wait in
``time.perf_counter()`` seconds, and the probe counts the heartbeats with a
time stamp between them. Heartbeats before or after the wait, such as the
hand-over between frames, do not count. The window of the wait also shows when
the frame is inside the wait, so the lock check does not depend on a sleep.

The window opens in the child process, on its main thread, which also runs
every frame (GLFW needs this). Other threads only watch.

The test opens the window on the computer it runs on. On Linux with no display
set it starts its own ``Xvfb`` for the child and stops it when the child is done;
it does not use ``xvfb-run``, whose failed cleanup of its temporary directory
replaces the exit code of the child with 5. The exit code of the child is the
result. The OpenGL case never skips. The
Vulkan case skips only when two facts hold together: the backend refuses the
window with its specific "independent graphics and present queues" message, and
a separate headless Vulkan child shows that the host device is a CPU software
renderer (Mesa Lavapipe has one queue); that is a missing present queue, which
is missing hardware. A build that has no Vulkan backend (the B3 EGL build) never
skips: it must open an OpenGL window for a Vulkan request, and the heartbeat and
lock checks run on that window. The headless Vulkan child tells the two builds
apart with the exact "requires Vulkan support" message of the native init, which
a build that has Vulkan never prints, so a silent OpenGL fallback there still
fails. Every other start failure, such as a
failed device, shader or swapchain on a real GPU, fails the test. In a build that
has Vulkan, a Vulkan case that runs must also show a real Vulkan swapchain, so it
cannot pass on a silent OpenGL fallback.

Vulkan FAST presentation (``OMNIUI_RENDER_FLOW_MODE=fast``) is left out of the
release on purpose: its present call runs while the frame holds the native queue
lock, and another Python thread that waits for that lock could deadlock with the
frame. The FAST case checks that the present of a FAST frame never enters the
release scope, and that the frames still complete. A change that wants to release
the GIL there must first move the present out of the queue lock, and then change
this case.
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import select
import subprocess
import sys
import tempfile

import pytest

_PROBE = """
import json
import os
import threading
import time

_VULKAN_DLL_DIRECTORY = None
if os.name == "nt":
    vulkan_dll_dir = os.environ.get("Vulkan_DLL_DIR")
    if vulkan_dll_dir:
        _VULKAN_DLL_DIRECTORY = os.add_dll_directory(vulkan_dll_dir)

import omni.ui as ui
import omni.ui.standalone as standalone
from omni.ui import _ui

WAIT_MS = 500

try:
    ui.init("present-wait-probe", 320, 200)
except RuntimeError:
    print("PROBE_INIT_FAILED", flush=True)
    raise SystemExit(3)
swapchain = list(ui.get_frame_pacing_status().get("swapchain_extent") or (0, 0))
standalone._tick_one_frame()  # the first frame has set-up cost
_ui._standalone_test_set_present_wait_delay_ms(WAIT_MS)

stamps = []
lock_free_in_wait = []
stop = threading.Event()

def heartbeat():
    while not stop.is_set():
        time.sleep(0.001)
        stamps.append(time.perf_counter())

def watch_lock():
    # shutdown() needs this lock, so it must stay held while the frame waits.
    while not stop.is_set():
        begin, end = _ui._standalone_test_present_wait_window()
        if begin > 0.0 and end == 0.0:
            free = standalone._native_lock.acquire(blocking=False)
            if free:
                standalone._native_lock.release()
            lock_free_in_wait.append(free)
        time.sleep(0.005)

threads = [threading.Thread(target=heartbeat, daemon=True),
           threading.Thread(target=watch_lock, daemon=True)]
for thread in threads:
    thread.start()
time.sleep(0.05)

_ui._standalone_test_set_present_wait_delay_ms(WAIT_MS)
standalone._tick_one_frame()  # on this (main) thread
time.sleep(0.05)
stop.set()
begin, end = _ui._standalone_test_present_wait_window()
lock_free_after = standalone._native_lock.acquire(blocking=False)
if lock_free_after:
    standalone._native_lock.release()
print("PROBE " + json.dumps({
    "swapchain": swapchain,
    "wait_s": end - begin,
    "wait_begin": begin,
    "beats_in_wait": sum(1 for s in stamps if begin <= s <= end),
    "beats_total": len(stamps),
    "lock_checks_in_wait": len(lock_free_in_wait),
    "lock_free_in_wait": sum(1 for free in lock_free_in_wait if free),
    "lock_free_after": lock_free_after,
}), flush=True)
"""


_NO_PRESENT_QUEUE = "windowed native output requires independent graphics and present queues"
_VULKAN_NOT_BUILT = "headless mode requires Vulkan support (OMNIUI_HAS_VULKAN)"


@functools.lru_cache(maxsize=None)
def _headless_vulkan_child() -> tuple[int, str]:
    """Ask a headless Vulkan child what this build and host offer.

    This is a fact about the build and host, found without the window path that
    is under test. Returns the exit code and the joined stdout and stderr.
    """
    env = dict(os.environ)
    env["OMNIUI_HEADLESS"] = "1"
    env.pop("OMNIUI_HEADLESS_GL", None)  # B3 sets it; an EGL build would pick EGL
    env["OMNIUI_BACKEND"] = "vulkan"
    code = "import omni.ui as ui; ui.init('device-probe', 64, 64)"
    completed = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=180
    )
    return completed.returncode, completed.stdout + completed.stderr


def _vulkan_device_is_software() -> bool:
    returncode, log = _headless_vulkan_child()
    return returncode == 0 and "type=CPU (software renderer)" in log


def _vulkan_backend_is_not_built() -> bool:
    """True only when this build was compiled without the Vulkan backend.

    The native init prints this exact message in that case and never in a build
    that has Vulkan, so a Vulkan build that silently falls back to OpenGL is not
    excused by it.
    """
    returncode, log = _headless_vulkan_child()
    return returncode != 0 and _VULKAN_NOT_BUILT in log



@contextlib.contextmanager
def _probe_display(env: dict):
    """The environment for the probe, with an X display when a Linux host has none.

    The test starts its own ``Xvfb`` and always stops it, so the exit code of the
    probe is the one that ``subprocess`` reports and no X server outlives the test.
    """
    if not sys.platform.startswith("linux") or env.get("DISPLAY"):
        yield env
        return
    command = ["Xvfb", "-displayfd", "1", "-nolisten", "tcp", "-screen", "0", "1280x1024x24"]
    with tempfile.TemporaryFile("w+") as log, subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=log, text=True
    ) as server:
        try:
            ready = select.select([server.stdout], [], [], 60)[0]
            display = server.stdout.readline().strip() if ready else ""
            if not display.isdigit():
                log.seek(0)
                pytest.fail(f"Xvfb did not report a display number: {display!r}\n{log.read()}")
            yield dict(env, DISPLAY=f":{display}")
        finally:
            server.terminate()
            try:
                server.wait(10)
            except subprocess.TimeoutExpired:
                server.kill()


def _run_probe(backend: str, fast: bool = False) -> dict:
    env = dict(os.environ)
    env.pop("OMNIUI_HEADLESS", None)
    env.pop("OMNIUI_HEADLESS_GL", None)
    env["OMNIUI_BACKEND"] = backend
    if fast:
        env["OMNIUI_RENDER_FLOW_MODE"] = "fast"
    else:
        env.pop("OMNIUI_RENDER_FLOW_MODE", None)
    with _probe_display(env) as probe_env:
        completed = subprocess.run(
            [sys.executable, "-c", _PROBE], env=probe_env, capture_output=True, text=True, timeout=180
        )
    if (
        backend == "vulkan"
        and completed.returncode == 3
        and "PROBE_INIT_FAILED" in completed.stdout
        and _NO_PRESENT_QUEUE in completed.stdout + completed.stderr
        and _vulkan_device_is_software()
    ):
        pytest.skip(
            "the Vulkan device of this host is a software renderer with no present queue\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    assert completed.returncode == 0, (
        f"exit code {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    for line in completed.stdout.splitlines():
        if line.startswith("PROBE "):
            return json.loads(line[len("PROBE "):])
    pytest.fail(
        "the probe never reported\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


@pytest.mark.parametrize("backend", ["opengl", "vulkan"])
def test_thread_progresses_and_lock_holds_inside_blocked_present(backend):
    probe = _run_probe(backend)
    # The backend that was asked for is the one that ran. A build without the
    # Vulkan backend can only run OpenGL; it is told apart from a silent
    # fallback in a Vulkan build by the native message, not by this probe.
    expect_vulkan = backend == "vulkan" and not _vulkan_backend_is_not_built()
    assert (probe["swapchain"] != [0, 0]) == expect_vulkan, probe
    # The delay stays: the goal is thread progress, not a faster present.
    assert probe["wait_s"] >= 0.45, probe
    # A beat every ~1 ms gives about 450 in the wait. With the GIL held for the
    # whole wait the count is 0, however long the hand-over after the frame is.
    assert probe["beats_in_wait"] >= 100, (
        f"only {probe['beats_in_wait']} heartbeats of an unrelated thread inside "
        f"the {probe['wait_s']:.2f} s native present wait ({backend}): {probe}"
    )
    # Frame and shutdown synchronization: the native lock that shutdown() needs
    # stays held for the whole wait, and is free after the frame.
    assert probe["lock_checks_in_wait"] >= 10, probe
    assert probe["lock_free_in_wait"] == 0, probe
    assert probe["lock_free_after"], probe


def test_vulkan_fast_present_stays_outside_the_gil_release():
    """FAST presentation is excluded from the release, and its frames complete.

    The probe makes every present wait of the release scope last 500 ms. A FAST
    frame must not enter that scope: the window record stays empty. A build
    without the Vulkan backend opens an OpenGL window for this request and the
    FAST mode does not exist there, so the OpenGL swap, which is covered, runs.
    """
    probe = _run_probe("vulkan", fast=True)
    if _vulkan_backend_is_not_built():
        assert probe["swapchain"] == [0, 0], probe
        assert probe["wait_begin"] > 0.0, probe
        return
    # A real Vulkan swapchain, and the FAST frames finished (the probe reports
    # only after its frames, with the delay armed, returned).
    assert probe["swapchain"] != [0, 0], probe
    assert probe["wait_begin"] == 0.0, (
        "a FAST frame entered the present-wait scope while it holds the native "
        f"queue lock: {probe}"
    )
    assert probe["lock_free_after"], probe

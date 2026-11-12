# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Each frame after a window size change reaches the window (Vulkan).

When the window gets a new size (a maximize, a drag of the window border, a
program resize), the swapchain no longer matches the window. Before, the backend
drew the next frame at the new size and presented it to the old swapchain: the
driver refused the present, the frame was lost, and the new window area stayed
black until the frame after it. Now the backend makes the new swapchain before
that present.

The probe draws frames, changes the window size with the public
``set_window_size``, and draws more frames, one at a time. After the size change
no present may be deferred more often, and no fewer frames may be presented,
than in the same number of frames before it, and the swapchain must get the new
size. The
counts come from the public ``get_frame_pacing_status``.

The test opens a real window in a child process, as
``test_standalone_present_wait`` does, and uses its display and skip helpers. On
Linux it always starts its own Xvfb with no window manager, because a window
manager can refuse or delay a program resize. It skips only when the Vulkan
device is a software renderer with no present queue (missing hardware), as on
the hosted CI runners. Every other start failure fails the test.

A build without the Vulkan backend also fails the test, and the failure names
that cause: the test checks the Vulkan swapchain, and a build option is not
missing hardware. So the jobs that build ovui without Vulkan (the EGL jobs) do
not run this file. The GPU jobs run it, and there a skip fails the step.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from test_standalone_present_wait import (
    _NO_PRESENT_QUEUE,
    _probe_display,
    _vulkan_backend_is_not_built,
    _vulkan_device_is_software,
)

_FRAMES = 12
_PROBE = f"""
import json
import os
import sys

if os.name == "nt":
    vulkan_dll_dir = os.environ.get("Vulkan_DLL_DIR")
    if vulkan_dll_dir:
        os.add_dll_directory(vulkan_dll_dir)

import omni.ui as ui
import omni.ui.standalone as standalone

try:
    standalone.init("resize-present", 640, 360)
except Exception as error:
    print("PROBE_INIT_FAILED", error, flush=True)
    sys.exit(3)
window = ui.Window("w", width=300, height=200, position_x=10, position_y=10)
with window.frame:
    ui.Rectangle(style={{"background_color": 0xFF336699}})


def status():
    s = ui.get_frame_pacing_status()
    return {{
        "backend": s.get("backend"),
        "presents": s.get("window_presents"),
        "deferrals": s.get("window_present_deferrals"),
        "extent": list(s.get("swapchain_extent") or ()),
        "window": list(standalone.get_window_size()),
    }}


for _ in range(10):
    standalone._tick_one_frame()
baseline = [status()]
for _ in range({_FRAMES}):
    standalone._tick_one_frame()
    baseline.append(status())
resized = standalone.set_window_size(960, 540)
after = [status()]
for _ in range({_FRAMES}):
    standalone._tick_one_frame()
    after.append(status())
standalone.shutdown()
print("PROBE " + json.dumps({{"resized": resized, "baseline": baseline, "after": after}}), flush=True)
"""


def _run_probe() -> dict:
    env = dict(os.environ)
    env.pop("OMNIUI_HEADLESS", None)
    env.pop("OMNIUI_HEADLESS_GL", None)
    env.pop("OMNIUI_RENDER_FLOW_MODE", None)
    env["OMNIUI_BACKEND"] = "vulkan"
    if sys.platform.startswith("linux"):
        # A window manager can refuse or delay a program resize: use a private
        # Xvfb with no window manager, as the CI jobs do.
        env.pop("DISPLAY", None)
    with _probe_display(env) as probe_env:
        completed = subprocess.run(
            [sys.executable, "-c", _PROBE], env=probe_env, capture_output=True, text=True, timeout=180
        )
    if (
        completed.returncode == 3
        and "PROBE_INIT_FAILED" in completed.stdout
        and _NO_PRESENT_QUEUE in completed.stdout + completed.stderr
        and _vulkan_device_is_software()
    ):
        pytest.skip(
            "the Vulkan device of this host is a software renderer with no present queue\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    assert completed.returncode == 0, (
        f"exit code {completed.returncode}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    for line in completed.stdout.splitlines():
        if line.startswith("PROBE "):
            return json.loads(line[len("PROBE "):])
    pytest.fail(f"the probe never reported\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")


def test_each_frame_after_a_window_size_change_is_presented_at_the_new_size():
    probe = _run_probe()
    baseline, after = probe["baseline"], probe["after"]
    report = json.dumps(probe, indent=1)

    uses_vulkan = all(s["backend"] == "vulkan" for s in baseline + after)
    if not uses_vulkan and _vulkan_backend_is_not_built():
        pytest.fail(
            "this build of ovui has no Vulkan backend, so the window used OpenGL; this test "
            "checks the Vulkan swapchain and needs a build with the Vulkan backend\n" + report
        )
    assert uses_vulkan, "the window must use the Vulkan backend\n" + report
    assert probe["resized"], "the window system refused the size 960x540\n" + report
    assert after[-1]["window"] == [960, 540], report
    assert after[-1]["extent"] == [960, 540], "the swapchain must get the new window size\n" + report

    baseline_deferrals = baseline[-1]["deferrals"] - baseline[0]["deferrals"]
    resize_deferrals = after[-1]["deferrals"] - after[0]["deferrals"]
    assert resize_deferrals <= baseline_deferrals, (
        f"{resize_deferrals} presents were deferred in the {len(after) - 1} frames after the size "
        f"change, {baseline_deferrals} in the {len(baseline) - 1} frames before it: a frame drawn "
        "at the new size was lost\n" + report
    )
    baseline_presents = baseline[-1]["presents"] - baseline[0]["presents"]
    resize_presents = after[-1]["presents"] - after[0]["presents"]
    assert resize_presents >= baseline_presents, (
        f"{resize_presents} of the {len(after) - 1} frames after the size change were presented, "
        f"{baseline_presents} of the {len(baseline) - 1} frames before it\n" + report
    )

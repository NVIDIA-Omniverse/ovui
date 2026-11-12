# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Windows must honor framebuffer sizes immediately, even beyond the desktop.

The default Win32 maximum tracking size used to clamp both initial creation
and programmatic resize. A fixed 1280x720 probe misses that bug on a larger
desktop, so also request thin windows beyond each current tracking limit.
Keeping the other dimension small avoids allocating a desktop-sized image
on machines with many monitors.

Each case opens a real native window in a child process and uses the public
window lifecycle APIs. There is deliberately no run loop,
frame tick, event pump, sleep, or retry between requesting and reading size.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 tracking limits")

_PROBE = """
import ctypes
from ctypes import wintypes
import math
import os
import sys

_VULKAN_DLL_DIRECTORY = None
vulkan_dll_dir = os.environ.get("Vulkan_DLL_DIR")
if vulkan_dll_dir:
    _VULKAN_DLL_DIRECTORY = os.add_dll_directory(vulkan_dll_dir)

import omni.ui.standalone as standalone

# GLFW enables per-monitor DPI awareness during init. Read physical tracking
# limits in that same coordinate system, then restore the caller's context
# so the test leaves initialization's own DPI handling in control.
user32 = ctypes.WinDLL("user32", use_last_error=True)
set_dpi_context = user32.SetThreadDpiAwarenessContext
set_dpi_context.argtypes = [ctypes.c_void_p]
set_dpi_context.restype = ctypes.c_void_p
previous_context = set_dpi_context(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
assert previous_context, ctypes.WinError(ctypes.get_last_error())
try:
    max_width = user32.GetSystemMetrics(59)  # SM_CXMAXTRACK
    max_height = user32.GetSystemMetrics(60)  # SM_CYMAXTRACK
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = ctypes.c_void_p
    primary = user32.MonitorFromPoint(wintypes.POINT(0, 0), 1)
    get_dpi = ctypes.WinDLL("shcore").GetDpiForMonitor
    get_dpi.argtypes = [
        ctypes.c_void_p, ctypes.c_int,
        ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT),
    ]
    get_dpi.restype = ctypes.c_long
    xdpi, ydpi = wintypes.UINT(), wintypes.UINT()
    assert get_dpi(primary, 0, ctypes.byref(xdpi), ctypes.byref(ydpi)) == 0
finally:
    set_dpi_context(previous_context)
assert max_width > 0 and max_height > 0, (max_width, max_height)
assert xdpi.value > 0 and ydpi.value > 0, (xdpi.value, ydpi.value)
xscale, yscale = xdpi.value / 96.0, ydpi.value / 96.0

# init takes logical dimensions and scales them by primary-monitor DPI;
# set_window_size takes physical framebuffer dimensions.
cases = {
    "reported": ((1280, 720), [(1100, 760)]),
    "wide": ((math.ceil((max_width + 64) / xscale), 240), [(max_width + 128, 260)]),
    "tall": ((320, math.ceil((max_height + 64) / yscale)), [(340, max_height + 128)]),
    "wide_resize": ((320, 240), [(max_width + 128, 260)]),
    "tall_resize": ((320, 240), [(340, max_height + 128)]),
}
initial, resizes = cases[sys.argv[1]]
expected_initial = (int(initial[0] * xscale + 0.5), int(initial[1] * yscale + 0.5))
print("tracking limits:", (max_width, max_height), "DPI:", (xdpi.value, ydpi.value),
      "initial:", initial, "expected framebuffer:", expected_initial, flush=True)

def check_size(expected, operation):
    actual = standalone.get_window_size()
    assert actual == expected, f"{operation}: requested {expected}, got {actual}"

try:
    standalone.init("window-size-probe", *initial)
    check_size(expected_initial, "init")
    # Exercise an oversize resize, ordinary shrink/grow, and repeated same-size
    # calls. Every observation must be correct at the API return boundary.
    for requested in [*resizes, (320, 240), (640, 480), (640, 480)]:
        succeeded = standalone.set_window_size(*requested)
        check_size(requested, "set_window_size")
        assert succeeded is True, f"set_window_size{requested} returned {succeeded}"
        assert standalone.set_window_position(30, 30) is True
        check_size(requested, "move after resize")

    for invalid in [(0, 480), (640, 0), (-1, 480), (640, -1)]:
        succeeded = standalone.set_window_size(*invalid)
        assert succeeded is False, f"set_window_size{invalid} returned {succeeded}"
        check_size((640, 480), "invalid resize")
finally:
    standalone.shutdown()

check_size((0, 0), "shutdown")
assert standalone.set_window_size(640, 480) is False
"""


@pytest.mark.parametrize("backend", ["default", "opengl"])
@pytest.mark.parametrize("case", ["reported", "wide", "tall", "wide_resize", "tall_resize"])
def test_window_size_is_immediate_and_not_clamped_to_desktop(backend, case):
    env = dict(os.environ)
    env.pop("OMNIUI_HEADLESS", None)
    env.pop("OMNIUI_HEADLESS_GL", None)
    env.pop("OMNIUI_BACKEND", None)
    if backend != "default":
        env["OMNIUI_BACKEND"] = backend

    completed = subprocess.run(
        [sys.executable, "-c", _PROBE, case],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, (
        f"{case}, {backend}: exit code {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )

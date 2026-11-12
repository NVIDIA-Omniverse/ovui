# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""``capture_screenshot`` in GLFW/Vulkan with the FAST render flow (issue 451).

FAST direct presentation draws into the swapchain image and keeps no
offscreen image. The capture must still return True and write the pixels of
the frame that was drawn, also after a live window resize. The case runs in a
child process because the render flow is read when the window starts.

The test skips only when the Vulkan library reports no device. A Vulkan library
that is missing, cannot load, has no function that the test needs, or returns an
error from vkCreateInstance or vkEnumeratePhysicalDevices fails the test. A
missing display setting is not missing hardware: if the Vulkan device is there
and the window does not start, the test fails. The screenshot
must match a reference image that was made in FAST mode. To make the reference
again, run with ``OMNI_UI_GENERATE_GOLDEN=1``.
"""

import ctypes
import ctypes.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from PIL import Image

from compare_utils import CompareMetric, compare

_GOLDEN = Path(__file__).parent / "golden" / "vulkan" / "glfw_fast_capture_960x540.png"
_CAPTURED = Path(__file__).parent / "captured"
_THRESHOLD = 0.01
_CHILD = textwrap.dedent(
    """
    import sys
    import omni.ui as ui
    from omni.ui import _ui, standalone, testing

    standalone.init("fast capture", 1280, 720)
    window = ui.Window("w", width=900, height=500, position_x=10, position_y=10)
    with window.frame:
        with ui.VStack():
            ui.Rectangle(height=100, style={"background_color": 0xFF0000FF})
            ui.Rectangle(height=100, style={"background_color": 0xFF00FF00})
    # Keep the pointer away from the window. A pointer on the resize edge
    # draws a highlight, and the display decides where the pointer starts.
    _ui._inject_mouse_move(1200, 700)
    for _ in range(10):
        standalone._tick_one_frame()
    standalone.set_window_size(960, 540)
    for _ in range(6):
        standalone._tick_one_frame()
    ok = testing.capture_screenshot(sys.argv[1])
    standalone.shutdown()
    sys.exit(0 if ok else 3)
    """
)


def _load_vulkan():
    """Load the Vulkan library, or fail the test.

    A Vulkan library that is missing, broken or incomplete is a software
    problem. It is not missing hardware, so the test must not skip.
    """
    name = "vulkan-1" if sys.platform == "win32" else "vulkan"
    library = ctypes.util.find_library(name)
    if library is None and sys.platform.startswith("linux"):
        library = "libvulkan.so.1"
    if library is None:
        pytest.fail(f"cannot find the Vulkan library '{name}'")
    try:
        vulkan = ctypes.CDLL(library)
    except OSError as error:
        pytest.fail(f"cannot load the Vulkan library {library}: {error}")
    for function in ("vkCreateInstance", "vkEnumeratePhysicalDevices", "vkDestroyInstance"):
        try:
            getattr(vulkan, function)
        except AttributeError as error:
            pytest.fail(f"the Vulkan library {library} has no {function}: {error}")
    return vulkan


def _vulkan_device_count():
    """Return the number of Vulkan devices, or fail the test on a Vulkan error.

    Zero means that a working Vulkan library started and found no device. This
    is the only result that lets the test skip. A library that cannot load, or
    a Vulkan call that returns an error, is a software problem and fails the
    test with the name of the call and its result code.
    """
    vulkan = _load_vulkan()
    # VkInstanceCreateInfo with sType 1 and no other field set.
    create_info = (ctypes.c_uint64 * 8)(1)
    instance = ctypes.c_void_p()
    result = vulkan.vkCreateInstance(create_info, None, ctypes.byref(instance))
    if result != 0:
        pytest.fail(f"vkCreateInstance failed with VkResult {result}")
    count = ctypes.c_uint32()
    result = vulkan.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), None)
    vulkan.vkDestroyInstance(instance, None)
    if result != 0:
        pytest.fail(f"vkEnumeratePhysicalDevices failed with VkResult {result}")
    return count.value


@pytest.mark.requires_glfw
def test_fast_vulkan_capture_writes_current_frame(tmp_path):
    # A software error in the Vulkan library fails the test. Only a working
    # library that reports no device lets the test skip.
    if _vulkan_device_count() == 0:
        pytest.skip("no Vulkan device on this machine")
    path = tmp_path / "fast.png"
    env = dict(os.environ, OMNIUI_BACKEND="vulkan", OMNIUI_RENDER_FLOW_MODE="fast")
    result = subprocess.run(
        [sys.executable, "-c", _CHILD, str(path)],
        env=env, capture_output=True, text=True, timeout=120,
    )
    output = result.stdout[-2000:] + result.stderr[-2000:]
    assert result.returncode == 0, f"exit status {result.returncode}:\n" + output
    assert "initialized fast direct presentation" in result.stdout, output
    with Image.open(path) as image:
        assert image.size == (960, 540)
    if os.environ.get("OMNI_UI_GENERATE_GOLDEN", "").strip() == "1":
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_bytes(path.read_bytes())
    assert _GOLDEN.exists(), f"Golden reference missing: {_GOLDEN}"
    error = compare(
        _GOLDEN, path, _CAPTURED / "diff_glfw_fast_capture_960x540.png",
        threshold=_THRESHOLD, cmp_metric=CompareMetric.MEAN_ERROR,
    )
    assert error < _THRESHOLD, f"screenshot differs from {_GOLDEN}: error={error:.6f}"

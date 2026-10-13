# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The ordinary windowed launch must really select Vulkan.

A silent revert of the default to OpenGL can leave every in-process test
passing while ordinary installed applications use the wrong interactive
backend. These cases therefore launch the real product in a child process
and read two runtime observables rather than any log text or patched value:

``swapchain_extent``
    Non-zero only when ``GlfwPlatform`` owns a real Vulkan swapchain, i.e.
    the process is genuinely on Vulkan. The value is exposed in backend
    telemetry; optional native frame-pacing support is not asserted here.
``get_window_size()``
    Non-zero only when a usable window was created, which separates a
    genuine OpenGL fallback from an explicit-Vulkan fail-closed exit.
``init_failed``
    True when ``init()`` raised because no window could be created.

Vulkan is made unavailable by pointing the loader at a missing ICD, so
the failure paths are exercised for real instead of being simulated.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

_PROBE = """
import json
import os

_VULKAN_DLL_DIRECTORY = None
if os.name == "nt":
    vulkan_dll_dir = os.environ.get("Vulkan_DLL_DIR")
    if vulkan_dll_dir:
        _VULKAN_DLL_DIRECTORY = os.add_dll_directory(vulkan_dll_dir)

import omni.ui as ui
import omni.ui.standalone as standalone

try:
    ui.init("backend-policy-probe", 320, 240)
    init_failed = False
except RuntimeError:
    init_failed = True
status = {} if init_failed else ui.get_frame_pacing_status()
try:
    window = list(standalone.get_window_size())
except Exception:
    window = [0, 0]
print("PROBE " + json.dumps({
    "swapchain": list(status.get("swapchain_extent") or (0, 0)),
    "window": window,
    "init_failed": init_failed,
}), flush=True)
standalone.shutdown()
"""


def _probe(backend: str | None, *, vulkan_available: bool) -> dict:
    """Launch the real product once and report what it actually selected."""
    env = dict(os.environ)
    env.pop("OMNIUI_HEADLESS", None)
    env.pop("OMNIUI_HEADLESS_GL", None)
    env.pop("OMNIUI_BACKEND", None)
    if backend is not None:
        env["OMNIUI_BACKEND"] = backend
    if not vulkan_available:
        missing = os.path.join(os.sep, "nonexistent", "ovui-no-icd.json")
        env["VK_ICD_FILENAMES"] = missing
        env["VK_DRIVER_FILES"] = missing

    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        env=env, capture_output=True, text=True, timeout=180,
    )
    for line in completed.stdout.splitlines():
        if line.startswith("PROBE "):
            return json.loads(line[len("PROBE "):])
    pytest.fail(
        "the probe never reported a backend\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


@pytest.fixture(scope="module", autouse=True)
def _requires_windowed_vulkan():
    """Establish capability without ever consulting the default policy.

    Capability and policy must not share a probe. If this gate launched
    with no override, a regression of the ordinary default back to OpenGL
    would look exactly like "this host has no Vulkan", and the module
    would skip instead of failing — which is the regression these tests
    exist to catch.

    Both probes therefore use an explicit backend, which is authoritative
    regardless of what the default happens to be:

    - explicit OpenGL proves a window can be created here at all;
    - explicit Vulkan proves this build/host can drive Vulkan at all.

    A capable environment then runs every case, so a regressed default
    fails on the assertion rather than being skipped away.
    """
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        pytest.skip("no display: a windowed backend cannot be created")
    if _probe("opengl", vulkan_available=True)["window"] == [0, 0]:
        pytest.skip("no windowed backend could be created in this environment")
    if _probe("vulkan", vulkan_available=True)["swapchain"] == [0, 0]:
        pytest.skip("this build/host has no working Vulkan backend")


def test_ordinary_launch_selects_vulkan_without_any_override():
    """No OMNIUI_BACKEND at all must still land on Vulkan."""
    selected = _probe(None, vulkan_available=True)
    assert selected["swapchain"] != [0, 0], (
        "an ordinary launch fell back to a non-Vulkan backend"
    )
    assert selected["window"] != [0, 0]


def test_explicit_opengl_request_is_authoritative():
    """Asking for OpenGL must be honoured, never overridden by the default."""
    selected = _probe("opengl", vulkan_available=True)
    assert selected["swapchain"] == [0, 0], (
        "OMNIUI_BACKEND=opengl still produced a Vulkan swapchain"
    )
    assert selected["window"] != [0, 0], "the OpenGL window must be usable"


def test_default_vulkan_falls_back_to_opengl_when_vulkan_cannot_initialize():
    """A machine without a usable Vulkan driver must still launch."""
    selected = _probe(None, vulkan_available=False)
    assert selected["swapchain"] == [0, 0]
    assert selected["window"] != [0, 0], (
        "the default Vulkan attempt failed without falling back to OpenGL, "
        "which strands every OpenGL-only system"
    )


def test_explicit_vulkan_fails_closed_instead_of_falling_back():
    """An explicit Vulkan request must not be silently downgraded."""
    selected = _probe("vulkan", vulkan_available=False)
    assert selected["init_failed"], "init() must raise when Vulkan cannot start"
    assert selected["window"] == [0, 0], (
        "OMNIUI_BACKEND=vulkan silently fell back to OpenGL; the caller "
        "would believe it is on Vulkan when it is not"
    )

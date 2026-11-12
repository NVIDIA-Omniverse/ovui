# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The memory check of the installed USD Viewer: one check for each scene load, none for an empty scene.

Regression: on DGX Spark the startup log had the same memory warning two times, with the minimum of the
smallest scene size for an empty scene. The renderer checked the memory when it started, with no scene,
and the scene load checked it again.

The installed windowed app starts the way a user starts it, ``python -m ovui_widgets.app scene.usda``,
with the real ovrtx renderer and each data provider. ``OVUI_MIN_GPU_MEMORY_GIB`` sets a GPU minimum that
no GPU has, so that each check of a scene with prims gives a warning on every computer:

1. The cube scene: each warning of the memory check names the minimum that it checked ("minimum of").
   The app log has each warning of the report of the check exactly one time, and no other memory warning;
   ``ovui-inspect health`` shows the same warnings. Exactly one of them is the GPU warning, with the
   minimum that the GPU reading of the app (``gpu_memory``) calls for: on a discrete GPU the GPU minimum;
   on an integrated GPU with unified memory (DGX Spark GB10) the GPU minimum plus the host minimum of the
   report, because the GPU and the host use the same memory; when the GPU memory is unknown, the GPU
   minimum that cannot be checked.
2. An empty scene (no prims): no memory warning in the log, no minimum in the report of the check, and no
   warning in ``health``.

The test reads the app log and the ``render_diagnostics``, ``gpu_memory`` and ``health`` answers of the
inspector. It takes no screenshot.
"""

from __future__ import annotations

import functools
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest


def _load_by_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HERE = Path(__file__).resolve().parent
driver = _load_by_path("ovui_e2e_driver_memory_check", _HERE / "driver.py")
pytestmark = pytest.mark.requires_ovrtx

# A GPU minimum that no GPU has: each check of a scene with prims warns.
MIN_GPU_GIB = 100000.0
# Each warning of the memory check names the minimum that it checked.
CHECK_TEXT = "minimum of"


@functools.lru_cache(maxsize=1)
def _probe_host() -> tuple[bool, str, bool, str]:
    """``nvidia-smi -L`` and the ovrtx probe, once for this module: the answer does not change between the
    cases, and each ovrtx probe makes a renderer in a new process, which takes minutes on a busy GPU runner."""
    gpu_present, gpu_detail = driver.nvidia_gpu_present()
    ovrtx_ok, ovrtx_detail = driver.ovrtx_device_available()
    return gpu_present, gpu_detail, ovrtx_ok, ovrtx_detail


def _require_renderer_and_display() -> None:
    """Skip only when ``nvidia-smi -L`` lists no NVIDIA GPU, an ``ovrtx.Renderer()`` cannot be made, and
    ``OVUI_E2E_REQUIRE_RENDER`` is not 1 (the CI jobs set it, so there a non-run fails); else run or fail.
    This is the rule of the other e2e tests (``test_wheel_app_window_golden_e2e.py``).

    A missing display is not missing hardware: on a host with the GPU and the
    renderer, a missing ``DISPLAY`` fails the test and names the cause.
    """
    require_render = os.environ.get("OVUI_E2E_REQUIRE_RENDER", "").strip() == "1"
    gpu_present, gpu_detail, ovrtx_ok, ovrtx_detail = _probe_host()
    if not ovrtx_ok:
        detail = f"nvidia-smi: {gpu_detail}. ovrtx probe: {ovrtx_detail}"
        if require_render or gpu_present:
            pytest.fail(f"The ovrtx renderer could not run. {detail}")
        pytest.skip(f"No ovrtx-capable NVIDIA GPU on this host. {detail}")
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        pytest.fail("This host has an ovrtx-capable NVIDIA GPU, but DISPLAY is not "
                    "set: the windowed app needs an X display (CI runs Xvfb).")


def _gpu_memory(session) -> dict:
    """The GPU reading of the app (``gpu_memory``): discrete, integrated (``unified``) or unknown.

    A busy frame loop answers "it was not run"; the driver asks again then, as for the other commands.
    """
    res = session._cli_retry("call", "gpu_memory", timeout=60)
    try:
        return json.loads(res.stdout)["result"]["gpu"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AssertionError(
            f"gpu_memory gave no reading ({exc!r}): {res.stdout[-2000:]}\n{res.stderr[-2000:]}"
        ) from exc


def _expected_gpu_warning(gpu: dict, min_host_gib: float) -> str:
    """The start of the GPU warning that the GPU reading of the app calls for."""
    if not gpu.get("available"):
        return f"cannot check the minimum of {MIN_GPU_GIB:g} GiB for "
    if gpu.get("unified"):
        # The GPU and the host use the same memory: the scene needs both minimums from it.
        return f"below the minimum of {MIN_GPU_GIB + min_host_gib:g} GiB for "
    return f"below the minimum of {MIN_GPU_GIB:g} GiB for "


def _resources(session, timeout: float = 120.0) -> dict:
    """The report of the memory check of the loaded scene, when the check has run."""
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        res = session._cli_retry("call", "render_diagnostics", timeout=60)
        try:
            resources = json.loads(res.stdout)["result"]["resources"]
        except (json.JSONDecodeError, KeyError, TypeError):
            resources = {}
        if resources.get("checked"):
            return resources
        last = f"{res.stdout[-2000:]}\n{res.stderr[-2000:]}"
        time.sleep(2.0)
    raise AssertionError(f"the memory check did not run: {last}\n--- app log ---\n{session.log_tail()}")


@pytest.mark.parametrize("scene", ["cube", "empty"])
@pytest.mark.parametrize("provider", driver.WINDOW_PROVIDERS)
def test_wheel_app_checks_memory_once_per_scene_and_not_for_an_empty_scene(
    provider, scene, tmp_path, monkeypatch
):
    _require_renderer_and_display()
    monkeypatch.setenv("OVUI_MIN_GPU_MEMORY_GIB", f"{MIN_GPU_GIB:g}")
    monkeypatch.delenv("OVUI_STRICT_RESOURCE_CHECK", raising=False)
    if scene == "empty":
        path = tmp_path / "empty.usda"
        path.write_text("#usda 1.0\n")
    else:
        path = driver.scene_path()
    log_path = tmp_path / "app.log"
    session = driver.FullAppSession(
        workdir=tmp_path, log_path=log_path, provider=provider, headless=False, scene=path,
        capture_frames=False,
    )
    session.start()
    try:
        session.wait_ready(timeout=300)
        resources = _resources(session)
        gpu = _gpu_memory(session)
        health = session.status().get("extensions", {}).get("render_diagnostics", {})
    finally:
        session.stop()

    log = log_path.read_text(errors="replace")
    checked = [line for line in log.splitlines() if CHECK_TEXT in line]
    warnings = resources.get("warnings", [])
    where = f"{provider}, {scene} scene, GPU reading {gpu}\n--- app log ---\n{log[-4000:]}"
    if scene == "empty":
        assert checked == [], where
        assert resources.get("scene_empty") is True and resources.get("minimum") is None, (resources, where)
        assert warnings == [] and health.get("resource_warnings") == [], (resources, health)
    else:
        assert resources.get("scene_empty") is False, (resources, where)
        minimum = resources.get("minimum") or {}
        assert minimum.get("min_gpu_gib") == MIN_GPU_GIB, (resources, where)
        # One check for this load: each warning of its report is in the log one time, and the log has no
        # other memory warning (main also checked when the renderer started, with scene size 0).
        assert warnings and len(checked) == len(warnings), (warnings, where)
        assert all(sum(warning in line for line in checked) == 1 for warning in warnings), (warnings, where)
        expected = _expected_gpu_warning(gpu, minimum.get("min_host_gib", 0.0))
        assert len([warning for warning in warnings if expected in warning]) == 1, (expected, warnings, where)
        assert health.get("resource_warnings") == warnings, (health, warnings)

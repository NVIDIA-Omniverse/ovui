# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""omni.ui and an ovrtx renderer in one process, in both orders.

ovui and ovrtx both ship a library named imgui, and a process holds only one.
A user script that constructs ``ovrtx.Renderer()`` and imports ``omni.ui``
must work whichever comes first. Earlier releases failed in both orders
or when the renderer came first ("DLL load failed while
importing _standalone" on Windows, "undefined symbol: _ZN10ImDrawListD1Ev" on
Linux). Each order runs in a fresh process with only the installed wheels.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _load_by_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


driver = _load_by_path("ovui_e2e_driver_load_order", Path(__file__).resolve().parent / "driver.py")
pytestmark = pytest.mark.requires_ovrtx

ORDERS = {
    "renderer_then_omni_ui": "import ovrtx\nr = ovrtx.Renderer()\nimport omni.ui\n",
    "omni_ui_then_renderer": "import omni.ui\nimport ovrtx\nr = ovrtx.Renderer()\n",
}


@pytest.mark.parametrize("order", sorted(ORDERS))
def test_omni_ui_and_ovrtx_renderer_in_one_process(order):
    ok, detail = driver.ovrtx_device_available()
    if not ok:
        gpu_present, gpu_detail = driver.nvidia_gpu_present()
        if os.environ.get("OVUI_E2E_REQUIRE_RENDER", "").strip() == "1" or gpu_present:
            pytest.fail(f"The ovrtx renderer could not run alone. {detail}; {gpu_detail}")
        pytest.skip(f"No ovrtx-capable NVIDIA GPU on this host. {detail}")
    proc = subprocess.run(
        [sys.executable, "-c", ORDERS[order] + "print('LOAD_ORDER_OK')\n"],
        capture_output=True, text=True, timeout=600, env=driver.app_env(),
    )
    assert proc.returncode == 0 and "LOAD_ORDER_OK" in proc.stdout, (
        f"{order} failed (exit {proc.returncode}):\n{proc.stdout}\n{proc.stderr[-4000:]}"
    )

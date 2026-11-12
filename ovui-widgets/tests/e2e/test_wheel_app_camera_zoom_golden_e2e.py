# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Camera zoom golden test of the regular (windowed) USD Viewer.

The app starts on an empty stage, in a real window of exactly 1000x720, with
the real ovrtx renderer required. The test then does what a user does:

1. Close the Content browser with the mouse (it lists the user's home folder,
   which differs on every machine).
2. Create a cube with the mouse: *Create*, *Shape*, *Cube*. The new cube is
   selected.
3. Zoom the camera out: scroll the mouse wheel down over the viewport.
4. When the window has settled, check that the cube area shrank and that the
   render changed. Then compare the whole
   1000x720 frame with the per-provider golden (stored at 500x360).

The flow and the compare live in ``driver.py``. A missing golden fails.
Goldens are written only with ``OMNI_UI_GENERATE_GOLDEN=1`` (in CI: a
``workflow_dispatch`` run with ``mode: generate``).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest


def _load_by_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HERE = Path(__file__).resolve().parent
driver = _load_by_path("ovui_e2e_driver_camera_zoom", _HERE / "driver.py")
pytestmark = pytest.mark.requires_ovrtx


def _require_renderer_and_display() -> None:
    """Skip only when this host honestly cannot run the app; else fail."""
    require_render = os.environ.get("OVUI_E2E_REQUIRE_RENDER", "").strip() == "1"
    gpu_present, gpu_detail = driver.nvidia_gpu_present()
    ovrtx_ok, ovrtx_detail = driver.ovrtx_device_available()
    if not ovrtx_ok:
        detail = f"nvidia-smi: {gpu_detail}. ovrtx probe: {ovrtx_detail}"
        if require_render or gpu_present:
            pytest.fail(f"The ovrtx renderer could not run. {detail}")
        pytest.skip(f"No ovrtx-capable NVIDIA GPU on this host. {detail}")
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        # The GPU and ovrtx work, so a missing display is a setup error.
        pytest.fail("DISPLAY is not set. The windowed app needs an X display; "
                    "start one (for example Xvfb :99) and export DISPLAY.")


@pytest.mark.parametrize("provider", driver.WINDOW_PROVIDERS)
def test_wheel_app_camera_zoom_golden(provider, tmp_path):
    _require_renderer_and_display()

    modules = (
        driver.OVSTAGE_PRODUCT_MODULES if provider == "ovstage" else driver.PRODUCT_MODULES
    )
    provenance = driver.assert_installed_provenance(modules)
    print("[provenance] installed product modules:")
    for name, path in provenance.items():
        print(f"    {name}: {path}")

    scene = tmp_path / "empty_scene.usda"
    scene.write_text(driver.EMPTY_SCENE)
    golden = driver.golden_dir() / driver.camera_zoom_golden_name(provider)
    session = driver.FullAppSession(
        workdir=tmp_path, log_path=tmp_path / "app.log", provider=provider,
        headless=False, scene=scene,
    )
    session.start()
    try:
        frame, viewport = driver.run_camera_zoom_flow(session, tmp_path)
    finally:
        session.stop()
    driver.check_frame_and_golden(
        frame, viewport, golden, tmp_path, f"camera-zoom/{provider}"
    )

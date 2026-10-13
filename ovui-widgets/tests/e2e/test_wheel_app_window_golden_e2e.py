# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Full-window golden test of the regular (windowed) USD Viewer.

The companion of :mod:`test_wheel_app_golden_e2e` (the headless app). This
test launches the app the way a user does, ``python -m ovui_widgets.app
scene.usda``, with a real window of exactly 1000x720 on every platform, and
compares the whole window as the user sees it:

1. The installed app starts with the real ovrtx renderer required and the data
   provider selected by ``OVUI_DATA_ADAPTER_PROVIDER`` — once with ``openusd``
   and once with ``ovstage`` (each in its own clean install).
2. The Content browser lists the user's home folder, which differs on every
   machine, so it is closed the way a user closes it: a mouse click on the
   *Window* menu, then a click on *Content Browser*. A read-only probe proves
   Content is hidden and every other window is still shown, and the viewport
   must grow into the freed space.
3. The cube is selected by clicking it in the resized viewport (real pick
   path); the move gizmo must be drawn at the right place and shape.
4. When the window has settled (identical consecutive frames, with the live
   FPS number masked), the whole 1000x720 frame is checked (viewport not
   blank, selection highlight and move gizmo drawn) and compared with the
   per-provider golden shared by all platforms (stored at 500x360): the UI
   and the viewport toolbar/HUD almost pixel for pixel, the viewport render
   by its mean error and by the number of clearly changed pixels.

The flow and the compare live in ``driver.py``. A missing golden fails.
Goldens are written only with ``OMNI_UI_GENERATE_GOLDEN=1`` and require
separate visual review; ordinary compare runs never regenerate them.
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


_HERE = Path(__file__).resolve().parent
driver = _load_by_path("ovui_e2e_driver_window", _HERE / "driver.py")
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
        if require_render:
            pytest.fail("OVUI_E2E_REQUIRE_RENDER=1 but DISPLAY is not set; the "
                        "windowed app needs an X display (for example, Xvfb).")
        pytest.skip("No X display (DISPLAY unset) for the windowed app.")


@pytest.mark.parametrize("provider", driver.WINDOW_PROVIDERS)
def test_wheel_app_window_golden(provider, tmp_path):
    _require_renderer_and_display()

    modules = (
        driver.OVSTAGE_PRODUCT_MODULES if provider == "ovstage" else driver.PRODUCT_MODULES
    )
    provenance = driver.assert_installed_provenance(modules)
    print("[provenance] installed product modules:")
    for name, path in provenance.items():
        print(f"    {name}: {path}")
    if provider == "ovstage":
        # The ovstage install is native-only: no OpenUSD runtime may be present.
        probe = subprocess.run(
            [sys.executable, "-c", "import importlib.util as u; print(u.find_spec('pxr'))"],
            capture_output=True, text=True, timeout=120, env=driver.app_env(),
        )
        assert probe.stdout.strip() == "None", (
            f"OpenUSD (pxr) is importable in the ovstage install: {probe.stdout}{probe.stderr}"
        )

    golden = driver.golden_dir() / driver.window_golden_name(provider)
    session = driver.FullAppSession(
        workdir=tmp_path, log_path=tmp_path / "app.log", provider=provider, headless=False
    )
    session.start()
    try:
        frame, viewport = driver.run_user_flow(session, tmp_path)
    finally:
        session.stop()
    driver.check_frame_and_golden(frame, viewport, golden, tmp_path, f"window/{provider}")

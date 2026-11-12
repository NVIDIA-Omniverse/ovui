# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""End-to-end wheel-install golden test for the USD Viewer.

This is a *full integration* test, not a unit test. It exercises the exact
path a user takes and that unit tests cannot cover:

1. The *installed* ``ovui_widgets`` application (from the CI-built wheels) is
   launched headless — ``python -m ovui_widgets.app.headless --width 1000
   --height 720`` — with the real ovrtx renderer **required**
   (``OVUI_WIDGETS_REQUIRE_OVRTX=1``), so a renderer that fails to load, e.g.
   the Windows ``imgui.dll`` collision, makes the app exit
   non-zero and this test fail. The viewport renders at a fixed 1000x720
   (its Resolution setting, from the app's settings file).
2. A checked-in scene (``simple_scene.usda``) is opened.
3. The cube is selected by **clicking it in the viewport** through the ovui
   inspector (real injected input through the picking path — not a selection
   setter). The selection is asserted from ``/state``.
4. The test captures what the headless app outputs: the viewport's rendered
   frame (what its viewport stream sends), 1000x720, without any editor UI.
   Once three consecutive outputs are identical it checks the output is not
   blank and shows the cube's selection outline, then compares it with the
   golden shared by all platforms (stored at 500x360). The offscreen editor UI
   is saved for reference only.

The test is marked ``requires_ovrtx``: it needs a supported NVIDIA GPU. On a
host with no ovrtx-capable device (e.g. a GPU-less CI runner) it skips with an
explicit reason rather than faking a pass. Where a GPU *is* present, any
failure of the render/selection/compare is a hard failure.

Regenerate the golden for the current platform with::

    OMNI_UI_GENERATE_GOLDEN=1 pytest ovui-widgets/tests/e2e/test_wheel_app_golden_e2e.py
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


def _load_by_path(name: str, path: Path):
    """Import a helper module by file path, without mutating ``sys.path``.

    Keeps this test's imports from leaking onto the global import search path
    when the GPU-less widgets lane collects (but deselects) it.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HERE = Path(__file__).resolve().parent
driver = _load_by_path("ovui_e2e_driver", _HERE / "driver.py")
pytestmark = pytest.mark.requires_ovrtx


def test_wheel_app_viewport_selection_golden(tmp_path):
    # 1. Skip-vs-fail gate. A renderer that cannot initialize is only an
    #    *environment* limit (honest skip) when there is genuinely no GPU. If a
    #    GPU is present but the renderer fails, that is the real break this test
    #    exists to catch -> FAIL. And in the dedicated GPU workflow
    #    (OVUI_E2E_REQUIRE_RENDER=1) a non-run always fails the job.
    require_render = os.environ.get("OVUI_E2E_REQUIRE_RENDER", "").strip() == "1"
    gpu_present, gpu_detail = driver.nvidia_gpu_present()
    ovrtx_ok, ovrtx_detail = driver.ovrtx_device_available()
    if not ovrtx_ok:
        detail = f"nvidia-smi: {gpu_detail}. ovrtx probe: {ovrtx_detail}"
        if require_render:
            pytest.fail(
                "OVUI_E2E_REQUIRE_RENDER=1 but the ovrtx renderer could not run, "
                f"so the end-to-end test did not execute. {detail}"
            )
        if gpu_present:
            pytest.fail(
                "An NVIDIA GPU is present but the ovrtx renderer failed to "
                "initialize. This is a real break (missing/broken renderer), not "
                f"a missing GPU. {detail}"
            )
        pytest.skip(
            "No ovrtx-capable NVIDIA GPU on this host, so the USD Viewer cannot "
            f"render; the full wheel-app golden test cannot run. {detail}"
        )

    assert driver.scene_path().exists(), f"missing scene: {driver.scene_path()}"
    assert driver.inspector_cli().with_suffix(".py").exists(), (
        f"missing inspector CLI: {driver.inspector_cli()}.py"
    )

    # 1b. Prove the app runs only installed wheel code, not the source checkout.
    provenance = driver.assert_installed_provenance()
    print("[provenance] installed product modules:")
    for name, path in provenance.items():
        print(f"    {name}: {path}")

    golden = driver.golden_dir() / driver.HEADLESS_GOLDEN_NAME
    session = driver.FullAppSession(
        workdir=tmp_path, log_path=tmp_path / "app.log", provider="openusd", headless=True
    )
    session.start()
    try:
        output = driver.run_headless_flow(session, tmp_path)
    finally:
        session.stop()
    driver.check_viewport_output_and_golden(output, golden, tmp_path, "headless/openusd")

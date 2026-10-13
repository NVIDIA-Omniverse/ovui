# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""First stationary selection must reach the real USD Viewer framebuffer.

Removing the initial outline-pass activation invalidation must fail this test:
after an idle, unselected startup, selecting a prim used to leave its outline
invisible until the camera moved. A standalone adapter render loop does not
reproduce the Application's native state, so this uses the stock headless
launch sequence and captures the composed framebuffer without extra render
calls. Mouse injection exercises native picking after a stationary startup;
selecting during the first few startup frames can mask the failure.

Requires a native Vulkan ovui build, OVStage, OVRTX, an RTX-capable GPU, numpy,
and Pillow. Native initialization happens only in a fresh subprocess. Hosted
CI excludes this test through the existing runtime markers.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.requires_ovstage, pytest.mark.requires_ovrtx]

_SCENE = Path(__file__).parent / "data" / "simple_scene.usda"

_SESSION = r"""
import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path

missing = [name for name in ("ovrtx", "ovstage", "PIL", "numpy")
           if importlib.util.find_spec(name) is None]
if missing:
    print("RESULT " + json.dumps({"missing": missing}), flush=True)
    sys.exit(0)

import numpy as np

# Identical native construction order to ovui_widgets.app.headless.main.
from ovui_widgets.app.native_runtime_bootstrap import (
    install_preconstructed_renderer,
    preconstruct_selected_native_renderer,
)
bootstrap = preconstruct_selected_native_renderer()
import ovui_data_adapters.ovstage.renderer_adapter as adapter_module
import omni.ui as ui
import ovui_widgets.app.application as application_module
from ovui_widgets.app.application import Application

app = Application(settings_overrides={"layout.save_path": str(Path.cwd() / "layout.json")})
install_preconstructed_renderer(app, bootstrap)
out = {"application_module": application_module.__file__,
       "adapter_module": adapter_module.__file__, "captures": []}
phases = [("idle", None), ("first_selection", ["/World/Cube"]),
          ("clear", []), ("reselect", ["/World/Cube"])]
state = {"index": 0, "started": None, "frames": 0, "capture": None, "input": []}
deadline = time.monotonic() + 180.0
camera = None
original_update = app._on_native_pacing_frame_update


def click_steps(viewport, image, selected):
    if selected:
        pose = viewport.capture_aov_camera_state()
        # A visible point on the fixture's cube, away from the central pyramid.
        clip = (np.asarray(pose.projection_matrix) @ np.asarray(pose.view_matrix)
                @ np.array([-1.5, 0.6, 0.0, 1.0]))
        ndc = clip[:2] / clip[3]
        u, v = (ndc[0] + 1.0) / 2.0, (1.0 - ndc[1]) / 2.0
    else:
        u, v = 0.85, 0.75  # Empty background in the auto-framed fixture.
    x = image.screen_position_x + u * image.computed_width
    y = image.screen_position_y + v * image.computed_height
    return [lambda: ui._ui._inject_mouse_move(float(x), float(y)),
            lambda: ui._ui._inject_mouse_button(0, True),
            lambda: ui._ui._inject_mouse_button(0, False)]


def finish():
    print("RESULT " + json.dumps(out), flush=True)
    state["index"] = len(phases)
    app.request_exit()


def observe(dt):
    global camera
    original_update(dt)
    if state["index"] == len(phases):
        return
    try:
        assert time.monotonic() < deadline, "native outline session timed out"
        viewport = app._viewport_window
        renderer = getattr(viewport, "renderer_adapter", None)
        if renderer is None or type(renderer).__name__ == "MockRendererAdapter":
            return
        assert type(renderer).__name__ == "OvstageRendererAdapter", type(renderer).__name__
        image = viewport._image
        if image is None or image.computed_width <= 0 or image.computed_height <= 0:
            return
        name, paths = phases[state["index"]]
        if state["started"] is None:
            if paths is not None:
                state["input"] = click_steps(viewport, image, bool(paths))
            state["started"] = time.monotonic()
            state["frames"] = 0
            return
        if state["input"]:
            state["input"].pop(0)()
            state["started"] = time.monotonic()
            return
        state["frames"] += 1
        # Match the idle full-HD viewer reproduction, not a click during the
        # first startup frames (which can mask the missing activation).
        # A selection-triggered rebuild may retain the old frame briefly;
        # allow it to publish its replacement.
        wait_seconds = 20.0 if name == "idle" else 1.0
        if time.monotonic() - state["started"] < wait_seconds or state["frames"] < 8:
            return
        pose = viewport.capture_aov_camera_state()
        assert pose is not None, "viewport has no camera state"
        if camera is None:
            camera = pose
        assert pose == camera, "camera moved during stationary selection test"
        if state["capture"] is None:
            path = Path.cwd() / (name + ".png")
            assert ui._ui._schedule_screenshot(str(path)), "framebuffer capture rejected"
            state["capture"] = str(path)
            return
        if not ui._ui._poll_screenshot_done():
            return
        path = state["capture"]
        assert Path(path).is_file(), "framebuffer capture did not produce a PNG"
        out["captures"].append({
            "name": name, "path": path,
            "selection": [item.path for item in app.selection_bus.get_snapshot().items],
            "rect": [float(image.screen_position_x), float(image.screen_position_y),
                     float(image.computed_width), float(image.computed_height)],
        })
        state.update(index=state["index"] + 1, started=None, capture=None)
        if state["index"] == len(phases):
            finish()
    except Exception:
        out["error"] = traceback.format_exc()
        finish()


app._on_native_pacing_frame_update = observe
app.run(usd_path=sys.argv[1])
"""


def test_first_selection_and_reselection_show_outline_without_camera_motion(tmp_path):
    """Check native pixels, including clear, in one isolated product session."""
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p),
        "OVUI_DATA_ADAPTER_PROVIDER": "ovstage",
        "OVUI_WIDGETS_REQUIRE_OVRTX": "1",
        "OVRTX_SKIP_USD_CHECK": "1",
        "OMNIUI_HEADLESS": "1",
        "OMNIUI_BACKEND": "vulkan",
        "OVGEAR_HEADLESS_WIDTH": "1920",
        "OVGEAR_HEADLESS_HEIGHT": "1080",
        "OVGEAR_LIVESTREAM": "0",
        "OVUIINSPECT_ENABLED": "0",
        "OVUI_WIDGETS_SETTINGS_PATH": str(tmp_path / "settings.json"),
        "OVUI_WIDGETS_NATIVE_FAST_EXIT": "1",
    })
    # Use the product's post-shutdown native exit path, avoiding late plugin
    # teardown at Python finalization. The result is flushed before shutdown.
    env.pop("PYTEST_CURRENT_TEST", None)
    preamble = sys.modules["tests.conftest"].CHILD_PROCESS_VULKAN_DLL_PREAMBLE
    done = subprocess.run(
        [sys.executable, "-c", preamble + _SESSION, str(_SCENE.resolve())],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=240,
    )
    diagnostics = f"rc={done.returncode}\n{done.stdout[-6000:]}\n{done.stderr[-6000:]}"
    assert done.returncode == 0, diagnostics
    result = next((line[7:] for line in done.stdout.splitlines()
                   if line.startswith("RESULT ")), None)
    assert result is not None, diagnostics
    observed = json.loads(result)
    if "missing" in observed:
        pytest.skip("native outline prerequisites unavailable: " + ", ".join(observed["missing"]))
    assert "error" not in observed, observed.get("error")
    # Match the parent's intended product origin in both source-checkout and
    # OVUI_TEST_INSTALLED_RELEASE modes, without importing Application/UI here.
    application_spec = importlib.util.find_spec("ovui_widgets.app.application")
    assert application_spec is not None and application_spec.origin is not None
    assert Path(observed["application_module"]).resolve() == Path(application_spec.origin).resolve()

    import numpy as np
    from PIL import Image

    counts = {}
    expected_selections = [[], ["/World/Cube"], [], ["/World/Cube"]]
    assert len(observed["captures"]) == 4, observed
    for capture, selection in zip(observed["captures"], expected_selections):
        assert capture["selection"] == selection, capture
        with Image.open(capture["path"]) as screenshot:
            x, y, width, height = capture["rect"]
            box = tuple(round(value) for value in (x, y, x + width, y + height))
            assert 0 <= box[0] < box[2] <= screenshot.width, capture
            assert 0 <= box[1] < box[3] <= screenshot.height, capture
            rgb = np.asarray(screenshot.convert("RGB").crop(box))
        # Neutral fixture geometry and the muted blue transform axis do not
        # satisfy this saturated selection-blue range. Cropping excludes the
        # Stage Browser's selected row and the Property panel's authored dots.
        red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        counts[capture["name"]] = int(np.count_nonzero(
            (blue > 220) & (red < 70) & (green > 90) & (green < 220)
        ))

    print(f"Native outline pixels: {counts}; adapter: {observed['adapter_module']}")
    assert counts["idle"] < 100, counts
    assert counts["first_selection"] >= counts["idle"] + 100, (
        f"first stationary selection has no visible outline: {counts}; "
        f"adapter: {observed['adapter_module']}; images: {tmp_path}"
    )
    assert abs(counts["clear"] - counts["idle"]) <= 5, counts
    assert counts["reselect"] >= counts["idle"] + 100, counts

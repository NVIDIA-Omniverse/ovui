<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Wheel-install end-to-end golden test

Two full integration tests for the USD Viewer. They reproduce exactly what a
user does and what unit tests cannot cover (for example, the Windows
`imgui.dll` collision slipped through unit tests):

- `test_wheel_app_golden_e2e.py` — the **headless** app
  (`python -m ovui_widgets.app.headless`), provider openusd. It checks what
  the headless app outputs: the viewport's rendered frame, without editor UI.
- `test_wheel_app_window_golden_e2e.py` — the **regular** app as a user starts
  it (`python -m ovui_widgets.app scene.usda`, a real window), once per data
  provider. It checks the whole window.

The headless jobs also run `test_wheel_imgui_load_order_e2e.py`: a script
that constructs `ovrtx.Renderer()` and imports `omni.ui`, in both orders, in a
fresh process (no image, no golden).

**Every capture is exactly 1000x720 on every platform.** The window size is
set with the app's own `OVGEAR_HEADLESS_WIDTH`/`OVGEAR_HEADLESS_HEIGHT` (read by
`ui.init` for the windowed and the headless app; the headless app also gets
`--width 1000 --height 720`); 1000 px wide also fits the Windows runner's
1024x768 screen. The headless viewport renders at a fixed 1000x720 (its
Resolution setting, `viewport.instances.main.resolution`, in the test's
settings file).

Both tests launch the **installed** `ovui_widgets` app with the **real ovrtx
renderer required** (`OVUI_WIDGETS_REQUIRE_OVRTX=1`), fresh settings and layout
files in the test directory, and open `ovui-widgets/tests/data/simple_scene.usda`.
All input goes through the ovui inspector (`skills/omniverse-ui-inspector`):
real injected mouse input, the same ImGui input path as a real mouse.

## Windowed test flow

1. Assert the window is exactly 1000x720 and every window, the Content
   browser included, is shown (default layout).
2. Close the Content browser **with the mouse** (it lists the user's home
   folder, which differs on every machine): click the *Window* menu, then
   *Content Browser*. The row to click is read from the live menu (the
   inspector's read-only `menus.top_levels[].items`), never hard-coded, so a
   new Window-menu entry moves the click instead of redirecting it to another
   command. A read-only probe proves Content is hidden while Stage
   Browser, Property Inspector, Viewport and Layers stay shown, and the
   viewport must grow into the freed space (450x376 -> 450x643). The stable
   frame after the resize is kept.
3. **Click the cube in the resized viewport**; assert the renderer highlight
   and that the selection came from the viewport.
4. Park the cursor and wait for 3 identical frames. The live FPS number in
   the viewport HUD is the only masked area (painted black, also in the golden).
5. Check the viewport is not blank, shows the selection highlight, and shows
   the **move gizmo**: a red x arrow running sideways and a green vertical y
   arrow, each >= 80 px, meeting at the gizmo origin.
6. The render right after the resize (step 2) must already match the final
   render apart from the selection overlay: MEAN_ERROR <= 2.5 (the outline
   and gizmo alone are 0.6-1.1; a viewport left showing the pre-resize image
   is 6.5).
7. Assert the app is still on the tier-2 zero-copy GPU ingest path
   (`renderer.zero_copy.mode == "enabled"`). `ZeroCopyState` retires tier-2
   permanently on the first CUDA map that raises and renders from a CPU
   readback instead — same pixels, so every golden still passes. That is how
   an ovrtx 0.5 mapping change (`MappedRenderVar.tensor` removed) took all
   three ovstage jobs off the GPU path unnoticed. `fallback` now fails the job.
8. Compare with the golden (see "Goldens").

## Headless test flow

The headless app has no window; a headless user consumes its viewport output
(its media `stream_start` defaults to `source: "viewport"`, the viewport's RTX
render). The editor UI it also draws offscreen is not what it shows anyone, so
it is not compared.

1. Start the headless app; assert the offscreen frame is 1000x720 and the
   viewport renders at exactly 1000x720.
2. Click the cube in the viewport (injected input through the offscreen UI,
   the same path a remote user's click takes); assert the selection.
3. Read the frame the viewport presents (`get_presentation_image()`, via a
   read-only inspector `execute`) until three consecutive outputs are
   identical. That 1000x720 render, with no editor UI, is the capture
   (`viewport_output.png`); the offscreen editor UI is saved as
   `ui_frame.png` for reference only.
4. Check the output is not blank and shows the cube's blue **selection
   outline** (>= 150 px; observed 1271), then compare with the golden.

This headless session is the only one launched with `OVGEAR_ZERO_COPY=0`.
Step 3 reads the presented frame back in Python, and on the default tier-2
zero-copy path the renderer hands ovui a live CUDA device pointer, so no CPU
image exists and `get_presentation_image()` returns `None` by design (see
`ovui_data_adapters.common._gpu_frame`). The renderer produces the same pixels
on either tier, and the windowed runs — which screenshot through ovui
itself — cover the default zero-copy path end to end. The flow asserts
`renderer.zero_copy.mode == "disabled"` afterwards, so the CPU readback is
provably this deliberate pin and never a tier-2 path that failed and retired
itself.

## Field Delete/Backspace test

`test_wheel_app_field_delete_e2e.py` runs in the openusd window jobs. It has
no golden. It opens a copy of `simple_scene.usda` in which the cube also has
`custom int segmentCount = 42`, clicks the cube in the viewport, and then, for
the float field `size` and the int field `segmentCount`, with Backspace and
with Delete: double-clicks the field (keyboard-edit mode), presses End or
Home, presses the key until the text is empty, types a value and presses
Enter. After every key press `/World/Cube` must exist; after Enter the
attribute must hold the typed value. Then it checks that intentional deletion
still works: Delete with the cube selected in the Stage Browser removes it,
Ctrl+Z restores it, Backspace with the cube selected in the viewport removes
it. Every step is saved as a numbered PNG in the test directory.

## Providers and runtimes

The window test runs once per data provider, each from its own clean install:

| Variant | Provider (`OVUI_DATA_ADAPTER_PROVIDER`) | Install |
|---|---|---|
| `openusd` | OpenUSD | all product wheels + `usd-core` (conda-forge `openusd` on ARM64) |
| `ovstage` | native OVStage | product wheels except the OpenUSD adapter and `ovui-widgets-all`, no OpenUSD at all, plus the `ovstage` runtime from pypi.nvidia.com |

The headless test uses the `openusd` install. On Linux the window needs an
X display, which may be supplied by Xvfb; the NVIDIA Vulkan driver must still
render it on the GPU. The checked-in reference captures used matched runtimes
`ovrtx==0.5.1.385782` and `ovstage==0.2.1.385922`. Use these versions when
comparing the references, and investigate differences when changing runtimes.

## Product defects this test found (fixed)

- **No selection outline in the headless app** — the OpenUSD data adapter
  lacked the one-shot outline-pass activation reset the OVStage adapter has; with ovrtx 0.5 a
  camera-static (headless) viewport never showed the outline.

- **Viewport kept the pre-resize image until the next click (Linux,
  OVStage)** — `ovui` native frame pacing. A render pause starts a
  new ownership generation and clears the renderer-time anchors, but an image
  presented across the pause re-set them; after the renderer reset that
  follows a resize, every new frame was rejected as "non-increasing renderer
  timestamp". Caught by the post-resize check (step 6 of the window flow).

## Requirements and skip-vs-fail

Needs a real **ovrtx-capable NVIDIA GPU**. ovrtx uses hardware ray tracing and
cannot render on software Vulkan (Lavapipe). The gate is honest:

- No NVIDIA GPU at all → **skip**, with the full reason (an environment limit).
- A GPU is present but the renderer fails to init → **fail** (the real break
  this test exists to catch, e.g. the Windows imgui.dll collision).
- `OVUI_E2E_REQUIRE_RENDER=1` (set for a required GPU run) → any non-run is a
  **failure**, so a required run cannot pass by skipping the test.

The test also proves it runs only **installed wheel code**: it launches the app
with a clean `PYTHONPATH` (only the inspector skill) and asserts every product
module imports from site-packages, not the checkout.

## Run from compiled wheels on a GPU machine

The public hosted workflows build wheels and run tests that do not require a
GPU. Run these rendering tests separately on a machine with a compatible
NVIDIA GPU and driver. On Linux, provide a working X display for windowed
checks (for example, Xvfb); software Vulkan alone is insufficient.

Create and activate a fresh Python 3.12 virtual environment for each provider.
Install exactly one compatible wheel for each product distribution from the
compiled wheelhouse using `pip install --no-index --no-deps <wheel files>`.
Keep every product wheel at version 0.3.0. For the native OVStage environment,
omit both the OpenUSD adapter and `ovui-widgets-all` (which depends on the
OpenUSD adapter). Do not install `usd-core` or another `pxr` provider.

Install third-party dependencies from public indexes (`pypi.org` and
`pypi.nvidia.com`), including the matched renderer/runtime versions above,
`numpy`, `pydantic`, `platformdirs`, `Pillow`, `pytest`, `fastapi`, and `uvicorn`.
The OpenUSD environment also needs `usd-core`, or compatible OpenUSD Python
bindings supplied separately on a platform without a matching wheel. Run
`python -m pip check` before testing.

From the repository root, the following Bash commands use only installed
product code. In PowerShell, set the two variables with `$env:NAME = "1"`.

```bash
export OVUI_TEST_INSTALLED_RELEASE=1
export OVUI_E2E_REQUIRE_RENDER=1

# In the OpenUSD virtual environment:
python -m pytest -q \
  ovui-widgets/tests/e2e/test_wheel_app_golden_e2e.py \
  'ovui-widgets/tests/e2e/test_wheel_app_window_golden_e2e.py::test_wheel_app_window_golden[openusd]' \
  ovui-widgets/tests/e2e/test_wheel_app_field_delete_e2e.py \
  ovui-widgets/tests/e2e/test_wheel_imgui_load_order_e2e.py

# In the separate OVStage virtual environment:
python -m pytest -q \
  'ovui-widgets/tests/e2e/test_wheel_app_window_golden_e2e.py::test_wheel_app_window_golden[ovstage]'
```

Leave `OMNI_UI_GENERATE_GOLDEN` unset for validation. Preserve the pytest
artifacts (screenshots, app logs, and provenance) for any failing comparison.

## Goldens

**One golden per test for all platforms**, stored at **half size (500x360)**
in `golden/`: `app_window_openusd.png`, `app_window_ovstage.png`,
`headless_viewport_openusd.png`. The 1000x720 capture is reduced by a 2x2 box
average (`Image.reduce(2)`) before it is written or compared. The checked-in references
were generated on Linux x86_64 with an optional Linux gizmo backend that is
not included in the public package set. Historical Windows comparisons used
ovui's default SceneView and passed against these same images. The public
package set uses the default SceneView on every platform; the historical
results do not prove that the public Linux configuration will match.

The reference images and comparison tolerances are retained unchanged. A
failure must be investigated as a possible product, runtime, or backend
difference before any reference image is considered for replacement.

The compare (`driver.py`, `golden_metrics`) judges two regions of the
half-size image (headless output: render region only):

- **strict** — the UI around the viewport and the viewport's toolbar and
  SCENE/FPS/RES HUD band: at most 10 pixels may differ by more than 16 levels.
  Historical reference validation observed zero changed UI pixels.
- **render** — the rest of the viewport: mean error <= 1.0, and after a 3x3
  box blur of both images at most 40 pixels may differ by more than 32 levels.
  The blur accommodates small sub-pixel rasterization differences between
  platforms; the pixel count catches local changes that barely move the mean.

The historical reference validation measured cross-platform render mean
errors of 0.09-0.43 and zero changed pixels after blurring; those measurements
include the optional Linux backend described above. They are provenance for
the existing images, not fresh validation of this public source tree.

Why half size: a 2x2 average reduces small rasterization differences while
retaining visible defects. Mean error alone can miss a localized defect, so
the comparison also enforces the changed-pixel limit. These thresholds and
the checked-in images must not be adjusted merely to turn a failed test green.

**A compare run fails when its golden is missing.** Generating a proposed
reference is a deliberate, separate local action:

```bash
OMNI_UI_GENERATE_GOLDEN=1 python -m pytest <the selected test node above>
```

Review generated images visually and compare their provenance and product
behavior before accepting any update. Ordinary validation runs must keep
`OMNI_UI_GENERATE_GOLDEN` unset and compare against the checked-in references.

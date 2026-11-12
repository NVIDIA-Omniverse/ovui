<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Wheel-install end-to-end golden test

Full integration tests for the USD Viewer. They reproduce exactly what a
user does and what unit tests cannot cover (for example, the Windows
`imgui.dll` collision slipped through unit tests):

- `test_wheel_app_golden_e2e.py` — the **headless** app
  (`python -m ovui_widgets.app.headless`), provider openusd. It checks what
  the headless app outputs: the viewport's rendered frame, without editor UI.
- `test_wheel_app_window_golden_e2e.py` — the **regular** app as a user starts
  it (`python -m ovui_widgets.app scene.usda`, a real window), once per data
  provider. It checks the whole window.

- `test_wheel_app_camera_pan_golden_e2e.py` — the **regular** app on an empty
  stage, once per data provider. It creates a cube, pans the camera a little
  and compares the whole window.

- `test_wheel_app_camera_zoom_golden_e2e.py` — the same start, once per data
  provider. It creates a cube, zooms the camera out with the mouse wheel and
  compares the whole window.

- `test_wheel_app_light_pick_e2e.py` — the **regular** app, once per data
  provider, on a scene with a dome light and a distant light at the origin.
  With no light selected, clicks on the cube at the origin and on
  a small cube near it must select those cubes. After the sphere light is
  selected in the Stage Browser, a click on a drawn pixel of its gizmo must be
  a viewport pick that keeps the light. After each step it compares the whole
  window with the golden of that step (see "Light pick test").

- `test_wheel_app_livestream_e2e.py` — the **regular** and the **headless**
  app stream and record a red/green/blue scene; real stream clients decode
  the frames, which must keep red and blue in their places. See
  "Livestream test".

- `test_wheel_app_memory_check_e2e.py` — the **regular** app, once per data
  provider, with the cube scene and with an empty scene. It checks
  the memory check in the app log and in `ovui-inspect health`; see "Memory
  check test".

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

## Property field keys test

`test_wheel_app_property_field_keys_e2e.py` runs in the openusd window jobs.
It has no golden and takes no screenshot. It opens `simple_scene.usda`, clicks
the cube in the viewport, and then, for the text fields Display Color and
Extent, the Purpose dropdown and the Double Sided checkbox, with Backspace and
with Delete: clicks the field and presses the key. After every click and key
press `/World/Cube` must exist in the app state. Escape closes the dropdown
list. Then it checks that intentional deletion still works after the Property
Inspector had the focus: Delete with the cube selected in the Stage Browser
removes it, Ctrl+Z restores it, Backspace with the cube selected in the
viewport removes it. The test skips only on a machine without an
ovrtx-capable NVIDIA GPU. On Linux with such a GPU and no `DISPLAY`, it fails
and names the missing display.

## Path bar keys test

`test_wheel_app_path_bar_keys_e2e.py` runs in the openusd window jobs. It has
no golden and takes no screenshot. A real key gives a key event and a
character, so the test sends both for each typed letter (`press`, then
`type`). After each action it reads the camera orbit state
(`viewport.camera`), the viewport tool and the path bar (`content_ui`) from
the app state.

1. Click the cube in the viewport and zoom out with the mouse wheel.
2. Double-click the Content Browser path bar and type `f` and `h`. The camera
   must not change; the path field must hold `fh`. Press Escape.
3. Single-click the path bar outside the breadcrumbs. The path field must
   edit. Type the path of a test folder; the letters of its last part,
   `frame_home_view`, are keys. After each of F, H, W, E and R the camera and
   the tool must not change. The folder suggestions must list
   `frame_home_view/`, and Enter must take the Content Browser to the folder.
4. Single-click a folder name that the narrow bar shows, then another one.
   Each click must take the Content Browser to that folder and keep the folder
   names: the path field must not open.
5. Type the test folder path with a slash at the end, press Down until
   `other_folder/` is highlighted and press Enter: the Content Browser must go
   to `other_folder`. Click the path bar, press Tab, type the test folder path
   and `fr`, then click the suggestion `frame_home_view/`: the Content Browser
   must go to that folder.
   The camera must not change.
6. Click the cube in the viewport, press F (the camera must change) and H (the
   camera must go back to the view the scene opened with).
7. Drag the Content tab out of the dock, so that the Content Browser floats.
   Single-click its path bar outside the breadcrumbs and type `f`: the camera
   and the tool must not change, and the field must hold `f`. Then type the
   test folder path: the field must hold all the typed text.

The test compares paths as the platform does: on Windows a path has no case,
and the Content Browser shows a typed `C:/...` as `c:/...`.

## Property Inspector focus Delete/Backspace test

`test_wheel_app_property_panel_keys_e2e.py` runs in the window jobs, once per
provider. It has no golden and takes no screenshot. It clicks the cube in the
viewport, clicks empty Property Inspector space below the last row and
presses Delete, then Backspace. Each relationship field (Proxy Prim with the
openusd provider, Material Binding with ovstage) must be disabled; the test
clicks it and presses Backspace, then clicks it again and presses Delete.
After every key `/World/Cube` must exist and the undo stack must not grow.
Then it checks that intentional deletion still works: Delete with the cube
selected in the Stage Browser removes it and adds one undo step labelled
`Delete`, Ctrl+Z restores it, Backspace with the cube selected in the
viewport removes it.

## Camera pan test

`test_wheel_app_camera_pan_golden_e2e.py` runs in the window jobs, once per
provider. It starts the app on an empty stage (`World` only), at 1000x720.
All input is real mouse input through the inspector.

1. Close the Content browser with the mouse, as in the windowed test.
2. Create a cube: click *Create*, hover *Shape*, click *Cube*. The test
   checks that `/World/Cube` is selected and shown in the viewport.
3. Park the cursor and wait for 3 identical frames (`4_before_pan.png`).
4. Pan the camera: drag with the **middle mouse button** in the viewport
   centre, 80 px right and 40 px down, in 20 move steps.
5. Park the cursor and wait for 3 identical frames (`5_after_pan.png`).
6. Check that the cube's move gizmo (drawn at the cube centre, read from the
   pixels) moved on screen by the drag distance (within 12 px) and that the
   render changed (MEAN_ERROR >= 1.0 against the frame
   before the pan). A tumble or a zoom does not move the cube by the drag
   distance, so they fail this check.
7. Assert the zero-copy GPU path is still on, then compare with the golden
   (`golden/camera_pan_<provider>.png`) with the same two-region compare as
   the windowed test.

## Camera zoom test

`test_wheel_app_camera_zoom_golden_e2e.py` runs in the window jobs, once per
provider. It starts like the camera pan test: empty stage, 1000x720, Content
browser closed with the mouse, cube made with *Create*, *Shape*, *Cube*.

1. Park the cursor and wait for 3 identical frames (`4_before_zoom.png`).
2. Zoom out: scroll the **mouse wheel** down by 10 over the viewport centre.
   (The ovstage provider frames the cube so close that zoom in would clip it.)
3. Park the cursor and wait for 3 identical frames (`5_after_zoom.png`).
4. Check that the light grey cube area is at most 0.85 times the area before
   (a zoom out gives about 0.55) and that the render changed
   (MEAN_ERROR >= 1.0 against the frame before the zoom).
5. Assert the zero-copy GPU path is still on, then compare with the golden
   (`golden/camera_zoom_<provider>.png`) with the same two-region compare as
   the windowed test.

## Light pick test

`test_wheel_app_light_pick_e2e.py` runs in the window jobs, once per
provider. The scene has a dome light and a distant light at the origin, a cube
at the origin, a small cube at (0.6, 1.4, 0.6), and a sphere light (`Lamp`)
above a side cube. Each test starts its own app at 1000x720 and closes the
Content browser with the mouse, as the windowed test does. The frames before
that show the Content browser, which lists the home folder of the machine, so
they have no golden (their names start with `_`).

After each step the test parks the cursor in the bottom-right corner, waits
for 3 identical frames (FPS value masked) and compares the window with the
golden of the step: `golden/light_pick_<step>_<provider>.png`, with the same
two-region compare as the windowed test. Steps that must look the same use
one golden. Each click waits until the renderer pick of that click is done,
so a click that must change nothing cannot pass before its pick ends.

The `small_cube`, `lamp_selected` and `lamp_gizmo_click` steps have one golden
per platform, `golden/light_pick_<step>_<provider>_<platform>.png`
(`linux_x86_64`, `windows_amd64`, `linux_aarch64`). In these steps the window is
not the same on all platforms, so one golden cannot pass everywhere. Measured
with the images of a `mode: generate` run of this test on all platforms (run
41016982725; half size, against the Linux x86_64 golden):

- `lamp_selected`, `lamp_gizmo_click` on Windows: the light gizmo lines are
  thinner (default SceneView) than on Linux (OpenGL). Render changed pixels:
  48 (OpenUSD) and 59 (OVStage), limit 40.
- `lamp_selected`, `lamp_gizmo_click` on Linux ARM64 with OpenUSD: the OpenUSD
  of conda-forge lists two more `Mode` rows for the light in the Property
  Inspector. Strict changed pixels: 4419, limit 10.
- `small_cube` on Windows with OpenUSD: the move gizmo of the small cube
  touches the right edge of the viewport, and Windows draws a handle 2 px past
  that edge. Strict changed pixels: 16 (one column), limit 10.

The other steps (`start`, `origin_cube`, `cleared`) differ by at most 14 render
pixels (mean 0.106) and 0 strict pixels between the platforms. On each platform,
the images of two Python versions are the same (0 changed pixels). The
`lamp_selected` and `lamp_gizmo_click` steps also differ from each other in the
Layers panel: after a viewport pick it shows the spec of the selected prim.

| Test | Step | Expected selection | Golden step |
|---|---|---|---|
| both | start, Content browser closed | nothing | `start` |
| clicks near the origin | click empty background | nothing | `start` |
| clicks near the origin | click the cube at the origin | `/World/OriginCube` | `origin_cube` |
| clicks near the origin | click empty background | nothing | `cleared` |
| clicks near the origin | click the small cube | `/World/SmallCube` | `small_cube` |
| drawn light gizmo | open the rows above `Lamp` with their chevrons, click the `Lamp` row | `/World/Lamp`, from the Stage Browser | `lamp_selected` |
| drawn light gizmo | click a drawn pixel of the Lamp gizmo, at least 12 px from anything else drawn | `/World/Lamp`, from the viewport | `lamp_gizmo_click` |

Each compare writes its golden-size capture and the diffs in a
`<step>_<name>_compare` folder next to the capture.

## Livestream test

`test_wheel_app_livestream_e2e.py` runs in the openusd window jobs on Python
3.12, in its own step. It has no golden. It opens
`tests/data/livestream_red_green_blue.usda` (a red cube left, a green cube
middle, a blue cube right) and checks frames that real stream clients decode:

1. Windowed app, viewport at a fixed 1000x720 (the viewport Resolution
   setting): `stream_start` (inspector media command) with `webrtc`, `native`
   and `rtsp`. The app log at the start must have no R/B line, the status no
   error, and the decoded frame red left of blue. The native client is
   `ovstream.Client` (NATIVE); the RTSP client is ffmpeg (from
   `imageio-ffmpeg`); the WebRTC client is the ovstream browser client
   (`examples/webrtc_client` of the ovstream release) in Google Chrome or
   Microsoft Edge (`OVUI_E2E_REQUIRE_WEBRTC_DECODE=1` makes a missing browser
   a failure). The Linux runners have no browser that decodes H.264, so there
   the WebRTC start is checked but not decoded. After streaming the viewport
   must still be on the zero-copy GPU ingest path.
2. Headless app: an MP4 recording (`recording_start`/`recording_stop`; the
   last frame is decoded), then `stream_start` with `source: application`
   (the composed window) and the native and RTSP clients. Every decoded frame
   must have red left of blue in the viewport area. This needs the
   CUDA-Vulkan frame export; on a partitioned (MIG) GPU, which cannot export,
   this test skips with the reason.

Every protocol of a test must start: a failed `stream_start` fails the test
with its cause, after the other protocols are checked. The WebRTC and native
servers of StreamSDK need a Direct3D device on Windows, which the session of
a Windows service (session 0) cannot give
(`NVST_DISCONN_SERVER_VIDEO_ADAPTER_INITIALIZE_D3D_FAILED`). Run the Windows test from the logged-in user's interactive console
session, where the required graphics device is available. The decoded
frames are saved as PNGs in the test directory.

The test skips only on a computer without the hardware: no NVIDIA GPU that
ovrtx can use, or on Linux no X display (`OVUI_E2E_REQUIRE_RENDER=1` makes
this a failure too). When the hardware is there, a missing `ovstream` or
`imageio-ffmpeg` fails the test with the install command.

Run `ovui-data-adapters/tests/test_swap_kernel.py` separately against the
installed adapters to validate the R/B swap kernels. These tests launch
the R/B swap kernels on the GPU and compare the result with NumPy. They need
only the NVIDIA driver (libcuda or nvcuda.dll), not a CUDA toolkit. They skip
on a computer without a CUDA GPU, such as the hosted wheelhouse jobs; on the
GPU test machine, require these tests to execute successfully.

## Memory check test

`test_wheel_app_memory_check_e2e.py` runs in all window jobs, with both data
providers. It has no golden and takes no screenshot. It starts the app with
`OVUI_MIN_GPU_MEMORY_GIB=100000`, a GPU minimum that no GPU has, so that each
memory check of a scene with prims gives a warning on every computer:

- `simple_scene.usda`: each warning of the report of the check
  (`render_diagnostics`, `resources.warnings`) is in the app log exactly one
  time, and the log has no other memory warning (the renderer does not check
  the memory when it starts; the scene load checks it once). `ovui-inspect
  health` shows the same warnings. Exactly one of them is the GPU warning, with
  the minimum that the GPU reading of the app (`gpu_memory`) calls for: the GPU
  minimum on a discrete GPU; the GPU minimum plus the host minimum on an
  integrated GPU with unified memory (DGX Spark GB10); the GPU minimum that
  cannot be checked when the GPU memory is unknown.
- An empty scene (`#usda 1.0` only): no memory warning in the log, no minimum
  in the report of the check (`resources.scene_empty`), and no warning in
  `health`.

The CI runners have discrete GPUs. The integrated-GPU case is tested only where
the GPU reading of the app is `unified`.

The test skips only when `nvidia-smi -L` lists no NVIDIA GPU, an
`ovrtx.Renderer()` cannot be made, and `OVUI_E2E_REQUIRE_RENDER` is not 1, as
the other e2e tests do. The CI jobs set `OVUI_E2E_REQUIRE_RENDER=1`, so there it
fails instead. On Linux with a working renderer and no `DISPLAY`, it fails and
names the missing display.

## Providers and runtimes

The window test runs once per data provider, each from its own clean install:

| Variant | Provider (`OVUI_DATA_ADAPTER_PROVIDER`) | Install |
|---|---|---|
| `openusd` | OpenUSD | all product wheels + `usd-core` (conda-forge `openusd` on ARM64) |
| `ovstage` | native OVStage | product wheels except the OpenUSD adapter and `ovui-widgets-all`, no OpenUSD at all, plus the `ovstage` runtime from pypi.nvidia.com |

The headless test uses the `openusd` install. On Linux the window needs an
X display, which may be supplied by Xvfb; the NVIDIA Vulkan driver must still
render on a compatible GPU. Install compatible `ovrtx` and, for native
OVStage checks, `ovstage` runtimes in the test environment.

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
- The renderer works but, on Linux, `DISPLAY` is not set (the camera pan and
  zoom tests) → **fail** with a setup message, with or without
  `OVUI_E2E_REQUIRE_RENDER`: the windowed app needs an X display.
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
Keep every product wheel at version 0.3.1. For the native OVStage environment,
omit both the OpenUSD adapter and `ovui-widgets-all` (which depends on the
OpenUSD adapter). Do not install `usd-core` or another `pxr` provider.

Install third-party dependencies from public indexes (`pypi.org` and
`pypi.nvidia.com`), including compatible renderer/runtime versions,
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

**One golden per test for all platforms** (except three steps of the light pick
test, see "Light pick test"), stored at **half size (500x360)** in `golden/`: `app_window_openusd.png`, `app_window_ovstage.png`,
`headless_viewport_openusd.png`, `camera_pan_openusd.png`,
`camera_pan_ovstage.png`, `camera_zoom_openusd.png`, `camera_zoom_ovstage.png`
and, for the light pick test, `light_pick_<step>_<provider>.png` (steps
`start`, `origin_cube` and `cleared`) and
`light_pick_<step>_<provider>_<platform>.png` (steps `small_cube`,
`lamp_selected` and `lamp_gizmo_click`, see "Light pick test"). The 1000x720 capture is reduced by a 2x2 box
average (`Image.reduce(2)`) before it is written or compared. The golden is
made on Linux x86_64; a per-platform golden is made on its own platform.
Some historical Linux references used an optional gizmo backend that is not
included in this public source tree. A comparison against those references
may reveal backend differences; investigate them without weakening the checks.

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
